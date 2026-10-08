#!/usr/bin/env python3
"""Conformance tests for bserve and bcurl. Run: python3 tests.py"""
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def frame(ftype, flags, sid, payload):
    return len(payload).to_bytes(3, "big") + bytes([ftype, flags]) + sid.to_bytes(3, "big") + payload


def field(idx, value, name=None):
    v = value.encode()
    if idx == 0:
        return b"\x00" + bytes([len(name)]) + name.encode() + struct.pack(">H", len(v)) + v
    return bytes([idx]) + struct.pack(">H", len(v)) + v


def get(path, sid=1, extra=b""):
    return frame(0x01, 0x01, sid, field(1, "GET") + field(2, path) + extra)


def read_frame(sock):
    hdr = b""
    while len(hdr) < 8:
        hdr += sock.recv(8 - len(hdr))
    n = int.from_bytes(hdr[:3], "big")
    payload = b""
    while len(payload) < n:
        payload += sock.recv(n - len(payload))
    return hdr[3], hdr[4], int.from_bytes(hdr[5:8], "big"), payload


def read_response(sock):
    """Return (status, body, number_of_data_frames)."""
    status, body, ndata = None, b"", 0
    while True:
        ftype, flags, _sid, payload = read_frame(sock)
        if ftype == 0x01:
            pos = 0
            while pos < len(payload):
                idx = payload[pos]; pos += 1
                if idx == 0:
                    pos += 1 + payload[pos]
                vlen = struct.unpack_from(">H", payload, pos)[0]; pos += 2
                if idx == 3:
                    status = int(payload[pos:pos + vlen])
                pos += vlen
        elif ftype == 0x02:
            body += payload
            ndata += 1
        if flags & 0x01:
            return status, body, ndata


class Server:
    def __init__(self, root, *extra):
        self.port = free_port()
        self.proc = subprocess.Popen([sys.executable, os.path.join(HERE, "bserve"), *extra,
                                      root, str(self.port)], stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", self.port)).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def connect(self):
        s = socket.create_connection(("127.0.0.1", self.port))
        s.settimeout(5)
        return s

    def stop(self):
        self.proc.terminate()
        self.proc.wait()


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.tmp.name
        with open(os.path.join(root, "index.html"), "w") as f:
            f.write("hello\n")
        with open(os.path.join(root, "big.bin"), "wb") as f:
            f.write(os.urandom(40000))
        cls.server = Server(root)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        cls.tmp.cleanup()

    def test_200(self):
        with self.server.connect() as s:
            s.sendall(get("/index.html"))
            self.assertEqual(read_response(s)[:2], (200, b"hello\n"))

    def test_root_maps_to_index(self):
        with self.server.connect() as s:
            s.sendall(get("/"))
            self.assertEqual(read_response(s)[0], 200)

    def test_404_then_connection_still_open(self):
        with self.server.connect() as s:
            s.sendall(get("/missing", sid=1))
            self.assertEqual(read_response(s)[0], 404)
            s.sendall(get("/index.html", sid=2))
            self.assertEqual(read_response(s)[0], 200)

    def test_truncated_field_is_400_and_connection_survives(self):
        bad = frame(0x01, 0x01, 1, field(1, "GET") + b"\x02\x00\xff/x")  # claims 255-byte value
        with self.server.connect() as s:
            s.sendall(bad)
            self.assertEqual(read_response(s)[0], 400)
            s.sendall(get("/index.html", sid=2))
            self.assertEqual(read_response(s)[0], 200)

    def test_missing_path_is_400(self):
        with self.server.connect() as s:
            s.sendall(frame(0x01, 0x01, 1, field(1, "GET")))
            self.assertEqual(read_response(s)[0], 400)

    def test_stream_zero_is_400(self):
        with self.server.connect() as s:
            s.sendall(get("/index.html", sid=0))
            self.assertEqual(read_response(s)[0], 400)

    def test_unknown_frame_type_is_skipped(self):
        with self.server.connect() as s:
            s.sendall(frame(0x7F, 0xFF, 0, b"from the future") + get("/index.html"))
            self.assertEqual(read_response(s)[0], 200)

    def test_literal_and_unknown_index_headers(self):
        extra = field(0, "x-custom", name="x-custom") + field(200, "ignored")
        with self.server.connect() as s:
            s.sendall(get("/index.html", extra=extra))
            self.assertEqual(read_response(s)[0], 200)

    def test_non_get_is_405(self):
        with self.server.connect() as s:
            s.sendall(frame(0x01, 0x01, 1, field(1, "POST") + field(2, "/index.html")))
            self.assertEqual(read_response(s)[0], 405)

    def test_path_traversal_is_404(self):
        with self.server.connect() as s:
            s.sendall(get("/../../../../etc/passwd"))
            self.assertEqual(read_response(s)[0], 404)

    def test_large_body_split_into_data_frames(self):
        with self.server.connect() as s:
            s.sendall(get("/big.bin"))
            status, body, ndata = read_response(s)
            self.assertEqual((status, len(body)), (200, 40000))
            self.assertEqual(ndata, 3)   # 16384 + 16384 + 7232


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(os.path.join(HERE, "www"), "--send-unknown")

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def bcurl(self, *args):
        return subprocess.run([sys.executable, os.path.join(HERE, "bcurl"), *args],
                              capture_output=True, timeout=10)

    def test_body_to_stdout_exit_0(self):
        r = self.bcurl(f"localhost:{self.server.port}/index.html")
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"Hello, BinHTTP!", r.stdout)

    def test_404_exits_nonzero(self):
        r = self.bcurl(f"localhost:{self.server.port}/nope")
        self.assertEqual(r.returncode, 1)

    def test_405_exits_nonzero(self):
        r = self.bcurl("-X", "DELETE", f"localhost:{self.server.port}/index.html")
        self.assertEqual(r.returncode, 1)

    def test_skips_unknown_frames_from_server(self):
        # this server sends an unknown type-0x7F frame before every response
        r = self.bcurl("-v", f"localhost:{self.server.port}/index.html")
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"UNKNOWN(0x7f)", r.stderr)

    def test_many_paths_one_connection(self):
        r = self.bcurl("-v", f"localhost:{self.server.port}/index.html", "/about.txt")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr.count(b"* connected"), 1)
        self.assertIn(b"stream=2", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
