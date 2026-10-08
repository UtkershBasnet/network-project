# Annotated hexdump — one complete request and response

Captured with:

```
$ ./bserve ./www 9000 &
$ ./bcurl -v localhost:9000/index.html
```

`www/index.html` contains the 25 bytes `<h1>Hello, BinHTTP!</h1>\n`.
Three frames cross the wire: one request frame (58 bytes) and two response
frames (91 + 33 = 124 bytes).

---

## Frame 1 — client → server: HEADERS (the request)

```
00000000  00 00 32 01 01 00 00 01  01 00 03 47 45 54 02 00   |..2........GET..|
00000010  0b 2f 69 6e 64 65 78 2e  68 74 6d 6c 04 00 09 6c   |./index.html...l|
00000020  6f 63 61 6c 68 6f 73 74  05 00 09 62 63 75 72 6c   |ocalhost...bcurl|
00000030  2f 31 2e 30 06 00 03 2a  2f 2a                     |/1.0...*/*|
```

| Offset | Bytes | Field | Meaning |
|--------|-------|-------|---------|
| 0x00 | `00 00 32` | Length | 0x32 = **50** payload bytes follow the header |
| 0x03 | `01` | Type | **HEADERS** |
| 0x04 | `01` | Flags | **END_STREAM**: the request is complete (GET has no body) |
| 0x05 | `00 00 01` | Stream ID | **1**, the first request on this connection |
| | | | *— payload: header block, 50 bytes —* |
| 0x08 | `01` | Index | 1 = `:method` (static table) |
| 0x09 | `00 03` | VLen | 3 |
| 0x0b | `47 45 54` | Value | `GET` |
| 0x0e | `02` | Index | 2 = `:path` |
| 0x0f | `00 0b` | VLen | 11 |
| 0x11 | `2f 69 … 6c` | Value | `/index.html` |
| 0x1c | `04` | Index | 4 = `host` |
| 0x1d | `00 09` | VLen | 9 |
| 0x1f | `6c 6f … 74` | Value | `localhost` |
| 0x28 | `05` | Index | 5 = `user-agent` |
| 0x29 | `00 09` | VLen | 9 |
| 0x2b | `62 63 … 30` | Value | `bcurl/1.0` |
| 0x34 | `06` | Index | 6 = `accept` |
| 0x35 | `00 03` | VLen | 3 |
| 0x37 | `2a 2f 2a` | Value | `*/*` |

Check: 6 + 14 + 12 + 12 + 6 = 50 = Length. ✔
None of the header *names* appear on the wire. Each one is a single index byte.

---

## Frame 2 — server → client: HEADERS (status + response headers)

```
00000000  00 00 53 01 00 00 00 01  03 00 03 32 30 30 07 00   |..S........200..|
00000010  18 74 65 78 74 2f 68 74  6d 6c 3b 20 63 68 61 72   |.text/html; char|
00000020  73 65 74 3d 75 74 66 2d  38 08 00 02 32 35 09 00   |set=utf-8...25..|
00000030  0a 62 73 65 72 76 65 2f  31 2e 30 0a 00 1d 54 68   |.bserve/1.0...Th|
00000040  75 2c 20 30 38 20 4f 63  74 20 32 30 32 36 20 31   |u, 08 Oct 2026 1|
00000050  35 3a 30 34 3a 32 35 20  47 4d 54                  |5:04:25 GMT|
```

| Offset | Bytes | Field | Meaning |
|--------|-------|-------|---------|
| 0x00 | `00 00 53` | Length | 0x53 = **83** payload bytes |
| 0x03 | `01` | Type | **HEADERS** |
| 0x04 | `00` | Flags | END_STREAM **not** set, so a body follows in DATA frames |
| 0x05 | `00 00 01` | Stream ID | **1**, the answer to request 1 |
| | | | *— payload: header block, 83 bytes —* |
| 0x08 | `03` `00 03` | Index, VLen | 3 = `:status`, 3 bytes |
| 0x0b | `32 30 30` | Value | `200` |
| 0x0e | `07` `00 18` | Index, VLen | 7 = `content-type`, 24 bytes |
| 0x11 | `74 65 … 38` | Value | `text/html; charset=utf-8` |
| 0x29 | `08` `00 02` | Index, VLen | 8 = `content-length`, 2 bytes |
| 0x2c | `32 35` | Value | `25` |
| 0x2e | `09` `00 0a` | Index, VLen | 9 = `server`, 10 bytes |
| 0x31 | `62 73 … 30` | Value | `bserve/1.0` |
| 0x3b | `0a` `00 1d` | Index, VLen | 10 = `date`, 29 bytes |
| 0x3e | `54 68 … 54` | Value | `Thu, 08 Oct 2026 15:04:25 GMT` |

Check: 6 + 27 + 5 + 13 + 32 = 83 = Length. ✔

---

## Frame 3 — server → client: DATA (the body)

```
00000000  00 00 19 02 01 00 00 01  3c 68 31 3e 48 65 6c 6c   |........<h1>Hell|
00000010  6f 2c 20 42 69 6e 48 54  54 50 21 3c 2f 68 31 3e   |o, BinHTTP!</h1>|
00000020  0a                                                 |.|
```

| Offset | Bytes | Field | Meaning |
|--------|-------|-------|---------|
| 0x00 | `00 00 19` | Length | 0x19 = **25** bytes, which matches `content-length: 25` |
| 0x03 | `02` | Type | **DATA** |
| 0x04 | `01` | Flags | **END_STREAM**: the response is complete |
| 0x05 | `00 00 01` | Stream ID | **1** |
| 0x08 | `3c 68 … 3e 0a` | Payload | `<h1>Hello, BinHTTP!</h1>\n`, written by bcurl to stdout |

After this frame the connection is **still open**. The client could send
another HEADERS frame on stream 2 right away (`./bcurl localhost:9000/ /about.txt`).
