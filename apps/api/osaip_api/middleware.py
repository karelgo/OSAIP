"""Cross-cutting HTTP middleware: API-Version header (CP-14) and CSRF (ADR-0001)."""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response

from osaip_api.problem import Problem, problem_response

API_VERSION = "1.0.0"

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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
