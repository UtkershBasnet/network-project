# BinHTTP/1 — HTTP, in binary

| File | What |
|------|------|
| `SPEC.md` | The protocol spec (hand-in #1) |
| `bserve` | Track 1: the server (hand-in #2) |
| `bcurl` | Track 2: the client (hand-in #2) |
| `HEXDUMP.md` | Annotated request + response (hand-in #3) |
| `tests.py` | Conformance tests for both programs |
| `www/` | Sample document root |

Python 3.8+ and the standard library only. `bserve` and `bcurl` are each
self-contained: they share no code, only the spec.

```sh
./bserve ./www 9000                               # terminal 1
./bcurl -v localhost:9000/index.html              # terminal 2: hexdump every frame
./bcurl localhost:9000/index.html /about.txt /docs/   # 3 requests, 1 connection
./bcurl localhost:9000/nope; echo $?              # 404 -> exit 1
./bcurl -v --send-unknown localhost:9000/         # server must skip the unknown frame
./bserve --send-unknown ./www 9000                # client must skip unknown frames
python3 tests.py                                  # run all tests
```
