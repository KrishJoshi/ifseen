"""A tiny local stand-in for the real decision APIs.

Speaks the Gemini Decisions, System One (Jev/Azure) and OpenAI chat wire formats, validates
the request shape the way the real services document it, and answers by actually looking at
the image: a statement mentioning a colour ("red", "green", "blue", "white", "black") gets
the fraction of pixels dominated by that colour as its probability. Anything else gets 0.05.
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

COLOURS = ("red", "green", "blue", "white", "black")


def colour_fractions(jpeg: bytes) -> dict[str, float]:
    img = Image.open(io.BytesIO(jpeg)).convert("RGB").resize((64, 64))
    counts = dict.fromkeys(COLOURS, 0)
    raw = img.tobytes()
    px = [tuple(raw[i : i + 3]) for i in range(0, len(raw), 3)]
    for r, g, b in px:
        if r > 200 and g > 200 and b > 200:
            counts["white"] += 1
        elif r < 50 and g < 50 and b < 50:
            counts["black"] += 1
        elif r > g + 60 and r > b + 60:
            counts["red"] += 1
        elif g > r + 60 and g > b + 60:
            counts["green"] += 1
        elif b > r + 60 and b > g + 60:
            counts["blue"] += 1
    return {k: v / len(px) for k, v in counts.items()}


def answer(statement: str, fractions: dict[str, float] | None) -> float:
    if fractions:
        for colour in COLOURS:
            if re.search(rf"\b{colour}\b", statement.lower()):
                return round(min(0.99, max(0.01, fractions[colour])), 4)
    return 0.05


class FakeDecisionServer:
    def __init__(self, api_key: str = "test-key"):
        self.api_key = api_key
        self.requests: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                server.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": body}
                )
                try:
                    if self.path.endswith("/v1beta/decisions"):
                        status, out = server.gemini(self.headers, body)
                    elif self.path.endswith("/systemone"):
                        status, out = server.systemone(self.headers, body)
                    elif self.path.endswith("/chat/completions"):
                        status, out = server.chat(self.headers, body)
                    elif self.path.endswith("/hook"):
                        status, out = 200, {"ok": True}
                    else:
                        status, out = 404, {"error": {"message": "not found"}}
                except AssertionError as e:
                    status, out = 400, {"error": {"code": 400, "message": str(e)}}
                data = json.dumps(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_PUT(self):  # noqa: N802 - ntfy uses PUT for attachments
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                server.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "raw_len": len(raw)}
                )
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeDecisionServer:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    # -- protocols -------------------------------------------------------------------------

    def gemini(self, headers, body):
        if headers.get("x-goog-api-key") != self.api_key:
            return 403, {"error": {"code": 403, "message": "API key not valid"}}
        assert body.get("model") == "gemini-decision-1", "unknown model"
        blocks = body.get("input")
        assert isinstance(blocks, list) and blocks, "input must be a non-empty list"
        fractions = None
        tokens = 0
        for b in blocks:
            assert b.get("type") in ("text", "image", "audio", "video", "document"), "bad block"
            if b["type"] == "text":
                tokens += len(b["text"]) // 4
            elif b["type"] == "image":
                assert b.get("mime_type") == "image/jpeg", "bad mime"
                fractions = colour_fractions(base64.b64decode(b["data"]))
                tokens += 258
            elif b["type"] == "audio":
                assert b.get("mime_type") == "audio/wav", "bad audio mime"
                tokens += 32 * 4
        qs = body.get("questions")
        assert isinstance(qs, dict) and 1 <= len(qs) <= 1000, "1-1000 questions"
        answers = {}
        for key, q in qs.items():
            assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key), f"bad key {key}"
            assert q.get("type") == "noul", "only noul in tests"
            if "criteria" in q:
                assert set(q["criteria"]) <= {"true_description", "false_description"}
            p = answer(q["instructions"], fractions)
            answers[key] = {"type": "noul", "noul": p, "confidence": max(p, 1 - p)}
        return 200, {
            "answers": answers,
            "usage": {
                "total_input_tokens": tokens,
                "total_output_tokens": 0,
                "total_tokens": tokens,
            },
        }

    def systemone(self, headers, body):
        auth = headers.get("Authorization") or headers.get("api-key")
        if not auth or self.api_key not in auth:
            return 401, {"detail": "unauthorized"}
        state = body.get("state")
        assert isinstance(state, str), "state must be a string here"
        fractions = None
        for key, asset in (body.get("assets") or {}).items():
            assert key in state, "every asset must be referenced"
            assert asset.get("format") in ("png", "jpg", "jpeg"), "bad format"
            assert headers.get("TypeSafe-Danger-Zone-Images") == "true" or headers.get("api-key"), (
                "image header required for Jev"
            )
            img_bytes = base64.b64decode(asset["data_base64"])
            w, h = Image.open(io.BytesIO(img_bytes)).size
            assert min(w, h) >= 280 and max(w, h) <= 1568, f"image {w}x{h} out of bounds"
            fractions = colour_fractions(img_bytes)
        answers = {
            k: {"type": "noul", "noul": answer(q["instructions"], fractions)}
            for k, q in body["questions"].items()
        }
        return 200, {
            "model": body.get("model"),
            "answers": answers,
            "usage": {"input_tokens": 300, "output_tokens": 0},
        }

    def chat(self, headers, body):
        msg = body["messages"][-1]["content"]
        text = next(c["text"] for c in msg if c["type"] == "text")
        statements = json.loads(text.split("Statements (id -> statement):\n", 1)[1])
        fractions = None
        for c in msg:
            if c["type"] == "image_url":
                b64 = c["image_url"]["url"].split(",", 1)[1]
                fractions = colour_fractions(base64.b64decode(b64))
        result = {k: answer(v, fractions) for k, v in statements.items()}
        content = "Sure! Here you go:\n```json\n" + json.dumps(result) + "\n```"
        return 200, {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 400, "completion_tokens": 20},
        }


if __name__ == "__main__":  # python tests/fake_server.py [port]
    import sys
    import time

    srv = FakeDecisionServer()
    srv.httpd.server_close()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    srv.__init__()  # rebind below on a fixed port
    srv.httpd.server_close()
    from http.server import ThreadingHTTPServer

    srv.httpd = ThreadingHTTPServer(("127.0.0.1", port), srv.httpd.RequestHandlerClass)
    srv.thread = threading.Thread(target=srv.httpd.serve_forever, daemon=True)
    with srv:
        print(f"fake decision server on {srv.url} (key: test-key)", flush=True)
        while True:
            time.sleep(3600)
