"""Cross-cutting HTTP middleware: API-Version header (CP-14), CSRF (ADR-0001),
and the upload body-size guard (plan §6)."""

import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response

from osaip_api.problem import Problem, problem_response

API_VERSION = "1.0.0"

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class UploadSizeLimit:
    """Raw ASGI guard for multipart uploads. Two layers (plan §6): reject early on
    Content-Length, and count streamed bytes so chunked/lying clients are cut off
    BEFORE Starlette's multipart parser spools the whole body to disk."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].endswith("/uploads")
        ):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._send_413(send)
                    return
            except ValueError:
                pass

        seen = 0
        app_responded = False
        we_responded = False

        # On overflow we answer 413 OURSELVES and feed the app a disconnect: an
        # exception raised inside receive() would be swallowed by FastAPI's form
        # parsing and surface as a generic 400.
        async def counting_receive() -> Any:
            nonlocal seen, we_responded
            if we_responded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    if not app_responded:
                        await self._send_413(send)
                        we_responded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Any) -> None:
            nonlocal app_responded
            if we_responded:
                return  # drop the app's late error response — the 413 already went out
            app_responded = True
            await send(message)

        await self.app(scope, counting_receive, guarded_send)

    async def _send_413(self, send: Any) -> None:
        body = json.dumps(
            {
                "type": "urn:osaip:problem:upload-too-large",
                "title": "Upload too large",
                "status": 413,
                "detail": f"Uploads are capped at {self.max_bytes // (1024 * 1024)} MB in this "
                "phase.",
                "hint": "Split the file or wait for background jobs (Phase 2) to lift the cap.",
                "docs_url": None,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def api_version_header(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["API-Version"] = API_VERSION
        return response

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Cookie auth is ambient: reject state-changing requests that are provably
        cross-site. Same-origin XHR sends Sec-Fetch-Site: same-origin; navigations
        from other sites send cross-site; non-browser clients send neither header
        and carry no ambient cookie risk beyond what they present."""
        if request.method not in _SAFE_METHODS:
            sec_fetch_site = request.headers.get("sec-fetch-site")
            if sec_fetch_site in {"cross-site", "same-site"}:
                # same-site (different port/subdomain) is still not our origin
                return problem_response(
                    request,
                    Problem(
                        403,
                        title="Cross-site request blocked",
                        detail="State-changing requests must come from the OSAIP app itself.",
                        hint="Open the app and retry the action from there.",
                        slug="csrf",
                    ),
                )
            if sec_fetch_site is None:
                origin = request.headers.get("origin")
                if origin is not None and not _same_origin(origin, request):
                    return problem_response(
                        request,
                        Problem(
                            403,
                            title="Cross-site request blocked",
                            detail="This request's Origin does not match the OSAIP app.",
                            hint="Open the app and retry the action from there.",
                            slug="csrf",
                        ),
                    )
        return await call_next(request)


def _same_origin(origin: str, request: Request) -> bool:
    public = urlsplit(request.app.state.settings.public_url)
    got = urlsplit(origin)
    if (got.scheme, got.netloc) == (public.scheme, public.netloc):
        return True
    # Direct-to-API origin (e2e serves the built app from the API origin)
    host = request.headers.get("host")
    return host is not None and got.netloc == host
