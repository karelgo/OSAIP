"""A minimal OpenAI-compatible server for the test suite.

Phase 3a's acceptance clause is that a call through TWO different connections — echo and
a real provider — shares one code path. Asserting that with a mocked `litellm.acompletion`
would prove nothing: the mock would be the code path. So this is a real HTTP server
speaking the real `/v1/chat/completions` wire format, which LiteLLM talks to over a real
socket. What it does not do is reach the network, cost money, or vary between runs.

It can be told to misbehave — 401, 429, malformed body, missing `usage` — so the
adapter's error sanitisation and token-estimation fallback are exercised against actual
provider responses rather than against hand-built exception objects.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# Set by the fixture; read by the handler thread.
_MODE = "ok"
_REQUESTS: list[dict[str, Any]] = []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # keep pytest output readable
        return

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        _REQUESTS.append(
            {
                "path": self.path,
                "body": body,
                "authorization": self.headers.get("Authorization"),
                "headers": {k.lower(): v for k, v in self.headers.items()},
            }
        )

        if _MODE == "unauthorized":
            # The message deliberately echoes the key and the prompt, exactly as real
            # providers do — the adapter must not forward any of it.
            return self._json(
                401,
                {
                    "error": {
                        "message": (
                            "Incorrect API key provided: sk-SECRETKEY123. "
                            f"Request body was {json.dumps(body)}"
                        ),
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                    }
                },
            )
        if _MODE == "rate_limited":
            return self._json(
                429,
                {"error": {"message": "Rate limit reached", "type": "rate_limit_error"}},
            )
        if _MODE == "malformed":
            return self._json(200, {"nonsense": True})

        content = _answer(body)
        payload: dict[str, Any] = {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": 1_770_000_000,
            # Deliberately different from what was requested, so the ledger's
            # model_version is proven to record what was SERVED.
            "model": "stub-model-2026-01",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }
        if _MODE != "no_usage":
            payload["usage"] = {
                "prompt_tokens": _count(body),
                "completion_tokens": len(content.split()),
                "total_tokens": _count(body) + len(content.split()),
            }
        return self._json(200, payload)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages = body.get("messages")
    return messages if isinstance(messages, list) else []


def _count(body: dict[str, Any]) -> int:
    return sum(len(str(m.get("content", "")).split()) for m in _messages(body))


def _answer(body: dict[str, Any]) -> str:
    """Echo the last user turn, so a test can prove what the provider actually RECEIVED
    — which is how redaction-before-the-provider is verified end to end."""
    for message in reversed(_messages(body)):
        if message.get("role") == "user":
            return f"stub: {message.get('content', '')}"
    return "stub: (no user message)"


@contextmanager
def openai_stub(mode: str = "ok") -> Iterator[dict[str, Any]]:
    """Run the stub on an ephemeral port. Yields a handle with `base_url` and the list
    of requests it received."""
    global _MODE
    _MODE, previous = mode, _MODE
    _REQUESTS.clear()
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield {"base_url": f"http://{host}:{port}/v1", "requests": _REQUESTS, "port": port}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _MODE = previous
