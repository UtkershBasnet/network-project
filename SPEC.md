# BinHTTP/1 — a binary framing of HTTP GET

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.
All integers are unsigned and big-endian (network byte order).

## 1. Model

A client opens **one** TCP connection to the server and sends requests over it
one at a time. It waits for each response to finish before sending the next
request. Either side MAY close the connection at any time. A server MUST NOT
close it just because a response has finished. Everything on the wire is a
**frame**.

## 2. Frame layout (8-byte fixed header + payload)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-----------------------------------------------+---------------+
|                  Length (24)                  |   Type (8)    |
+---------------+-----------------------------------------------+
|   Flags (8)   |                 Stream ID (24)                |
+---------------+-----------------------------------------------+
|                    Payload (Length bytes) ...                 |
+---------------------------------------------------------------+
```

| Field     | Bits | Meaning |
|-----------|------|---------|
| Length    | 24   | Number of payload bytes after the 8-byte header (0 – 16 777 215). |
| Type      | 8    | What the payload is (§3). |
| Flags     | 8    | Bit flags; their meaning depends on the type. Bits not defined for a type MUST be sent as 0 and MUST be ignored. |
| Stream ID | 24   | Which request/response this frame belongs to. 0 is reserved for connection-level frames. |

**Why these widths.**
*Length = 24* is HTTP/2's choice and it holds up here too. With 16 bits a frame
could carry only 64 KiB, which is easy to hit. With 32 bits we would spend a
byte to permit 4 GiB frames that no receiver should buffer. 16 MiB is enough
headroom, and big bodies are split across DATA frames anyway.
*Type = 8* allows 256 frame types. v1 uses two, so the rest are room for growth.
*Flags = 8* is enough because v1 needs one bit and HTTP/2 never needed more
than four per type.
*Stream ID = 24* replaces HTTP/2's 31 bits plus a reserved bit. v1 does not
multiplex, but carrying a stream ID now means a v2 can multiplex without
changing the header. 24 bits allows ~16.7 M requests per connection, and it
makes the whole header exactly **8 bytes**. That is two 32-bit words, which are
easy to parse and to read in a hexdump.

## 3. Frame types

| Type | Name    | Payload | Flags |
|------|---------|---------|-------|
| 0x01 | HEADERS | A header block (§4) | 0x01 END_STREAM |
| 0x02 | DATA    | Raw body bytes | 0x01 END_STREAM |

END_STREAM marks the last frame of a request or response.

> **Unknown frame types.** A receiver that meets a frame type it does not know
> **MUST skip it cleanly**: it reads and discards exactly `Length` payload
> bytes and then carries on reading the next frame. It MUST NOT close the
> connection or report an error. This is what makes a version 2 possible.

## 4. Header block (HEADERS payload)

A header block is a sequence of fields that fills the payload exactly. Each
field starts with a one-byte **Index**:

```
Index 1..10  (static name):  | Index (8) | VLen (16) | Value (VLen bytes) |
Index 0      (literal name): | 0x00 | NLen (8) | Name (NLen) | VLen (16) | Value (VLen) |
```

**Static table.** These are the ten names that v1 implementations actually send:

| Idx | Name           | Idx | Name           |
|-----|----------------|-----|----------------|
| 1   | `:method`      | 6   | `accept`       |
| 2   | `:path`        | 7   | `content-type` |
| 3   | `:status`      | 8   | `content-length` |
| 4   | `host`         | 9   | `server`       |
| 5   | `user-agent`   | 10  | `date`         |

- Names are lowercase ASCII. Values are UTF-8. `:status` is three ASCII
  digits, for example `"404"`.
- Any other header uses Index 0 and carries its name as a literal with a length
  prefix. NLen MUST be at least 1.
- Index 11–255 is reserved for future static entries. Because the value is
  always length-prefixed, a receiver MUST skip such a field and ignore it.
- These are the first two mechanisms of HPACK: a static table plus length-prefixed
  literals. BinHTTP has no dynamic table and no Huffman coding.

## 5. Exchange

**Request.** The client sends exactly one HEADERS frame with END_STREAM set.
It MUST contain `:method` and `:path`, and `:path` MUST start with `/`.
Stream IDs start at 1 and go up by 1 for each request on the connection.

**Response.** The server answers on the **same stream ID** with:
1. one HEADERS frame with `:status` (and SHOULD include `content-type` and
   `content-length`), then
2. zero or more DATA frames carrying the body.

If the body is empty, the HEADERS frame carries END_STREAM. Otherwise the last
DATA frame does. Senders SHOULD keep DATA payloads at 16 KiB or less.

**Path mapping.** The server strips any `?query` or `#fragment` from `:path`
and resolves the rest under its document root. A path ending in `/`, or naming
a directory, means `index.html` inside it. A path that resolves outside the
root MUST be treated as not found.

## 6. Status codes and errors

| Status | When |
|--------|------|
| 200 | File found, body follows. |
| 400 | The frame was delimited correctly but its payload is malformed: a field runs past the payload, `:method`/`:path` is missing, the path does not start with `/`, the bytes are not valid UTF-8, END_STREAM is missing, the stream ID is 0, or the header block is larger than the server's limit (bserve: 64 KiB). |
| 404 | No such file under the root. |
| 405 | `:method` is not `GET`. |
| 500 | The file exists but could not be read. |

The connection **stays open after every error response**. Because `Length`
always tells the receiver where the next frame starts, a bad payload never
desynchronises the stream. The connection is lost only when it ends in the
middle of a frame. In that case the receiver closes it.

A client SHOULD report 4xx/5xx to its user. `bcurl` exits with 0 when every
response is 2xx/3xx, 1 when any is 4xx/5xx, 2 on bad usage and 3 on a network
or protocol error.

## 7. Rules for receivers (summary)

1. Read 8 bytes, then read exactly `Length` more.
2. Unknown type → discard the payload and continue.
3. Undefined flag bits → ignore.
4. Unknown static index (11–255) → skip that field.
5. A DATA frame arriving at a server is ignored in v1, because requests have
   no body.
