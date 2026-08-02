"""problem+json error envelope (§6.6): every error carries a user-facing hint and a
docs link. Raise `Problem` anywhere; handlers translate everything else."""

from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"


class Problem(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str,
        *,
        hint: str | None = None,
        slug: str = "general",
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.hint = hint
        self.slug = slug
        self.extra = extra or {}


def problem_response(request: Request, problem: Problem) -> Response:
    docs_base: str = request.app.state.settings.docs_base_url
    body: dict[str, Any] = {
        "type": f"urn:osaip:problem:{problem.slug}",
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
        "hint": problem.hint,
        "docs_url": f"{docs_base}/problems/{problem.slug}.md",
        **problem.extra,
    }
    import json

    return Response(
        # Encoded first: `extra` carries caller-supplied values (uuids, datetimes, and
        # — before this — pydantic's raw exception objects). A problem response that
        # cannot serialise turns a clean 4xx into a 500, which is the one thing an
        # error path must never do.
        content=json.dumps(jsonable_encoder(body)),
        status_code=problem.status,
        media_type=PROBLEM_CONTENT_TYPE,
    )


def _safe_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Strip pydantic's `ctx`, which holds the raw exception OBJECT for any validator
    that raises ValueError. `msg` already carries the text, and jsonable_encoder would
    render the exception as an empty object — informative to nobody.
    """
    safe: list[dict[str, Any]] = []
    for error in errors:
        item = {
            "type": error.get("type"),
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": error.get("msg"),
        }
        safe.append(item)
    return safe


def register_problem_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> Response:
        return problem_response(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        slug = {401: "unauthenticated", 403: "forbidden", 404: "not-found"}.get(
            exc.status_code, "http-error"
        )
        return problem_response(
            request,
            Problem(
                exc.status_code,
                title=str(exc.detail),
                detail=str(exc.detail),
                hint="Check the URL and your access, then try again.",
                slug=slug,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> Response:
        return problem_response(
            request,
            Problem(
                422,
                title="Request validation failed",
                detail="One or more fields are missing or invalid.",
                hint="Fix the fields listed in `errors` and resend the request.",
                slug="validation",
                extra={"errors": _safe_errors(exc.errors())},
            ),
        )
