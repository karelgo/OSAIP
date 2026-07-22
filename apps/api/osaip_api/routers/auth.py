"""OIDC BFF login/callback/logout (ADR-0001)."""

import secrets
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.auth.deps import current_user_and_session
from osaip_api.auth.service import (
    SESSION_COOKIE,
    create_session,
    destroy_session,
    provision_user,
)
from osaip_api.db import get_session
from osaip_api.models import Session as SessionRow
from osaip_api.models import User
from osaip_api.problem import Problem

router = APIRouter(prefix="/auth", tags=["auth"])

_OIDC_STATE_KEY = "oidc"


def _validate_next(next_path: str) -> str:
    """Same-origin relative paths only — open-redirect guard (ADR-0001)."""
    if not next_path.startswith("/") or next_path.startswith("//") or ":" in next_path:
        raise Problem(
            400,
            title="Invalid redirect",
            detail="The `next` parameter must be a path inside this app.",
            hint="Use a relative path such as /p/demo.",
            slug="invalid-redirect",
        )
    return next_path


def _redirect_uri(request: Request) -> str:
    # The callback must return to the same origin the browser is on (vite origin in
    # dev, api origin in e2e) so the session cookie is first-party.
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/auth/callback"


@router.get("/login")
async def login(request: Request, next: str = "/") -> RedirectResponse:
    next_path = _validate_next(next)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = request.app.state.oidc.new_pkce_pair()
    request.session[_OIDC_STATE_KEY] = {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "next": next_path,
    }
    url = await request.app.state.oidc.build_authorize_url(
        redirect_uri=_redirect_uri(request),
        state=state,
        nonce=nonce,
        code_challenge=challenge,
    )
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    if error:
        raise Problem(
            502,
            title="Sign-in failed",
            detail=f"The identity provider returned an error: {error}.",
            hint="Try signing in again.",
            slug="oidc-error",
        )
    pending = request.session.pop(_OIDC_STATE_KEY, None)
    if not pending or not state or not secrets.compare_digest(pending["state"], state):
        raise Problem(
            400,
            title="Sign-in failed",
            detail="The sign-in state is missing or does not match (possible CSRF or timeout).",
            hint="Start the sign-in again from the app.",
            slug="oidc-state-mismatch",
        )
    tokens = await request.app.state.oidc.exchange_code(
        code=code, redirect_uri=_redirect_uri(request), code_verifier=pending["verifier"]
    )
    claims = await request.app.state.oidc.validate_id_token(
        tokens["id_token"], nonce=pending["nonce"]
    )

    client_ip = request.client.host if request.client else None
    user = await provision_user(session, claims=claims, ip=client_ip)
    cookie_value = await create_session(
        session,
        request.app.state.settings,
        user=user,
        oidc_sid=claims.get("sid"),
        # Kept ONLY for RP-initiated logout; access/refresh tokens are discarded.
        id_token=tokens.get("id_token"),
    )
    await session.commit()

    response = RedirectResponse(pending["next"], status_code=302)
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE,
        cookie_value,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=not settings.dev,
        path="/",
    )
    return response


@router.post("/logout")
async def logout(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_and_session: Annotated[tuple[User, SessionRow], Depends(current_user_and_session)],
) -> dict[str, str | None]:
    user, row = user_and_session
    id_token = row.id_token
    await destroy_session(session, row.id)
    await session.commit()

    meta = await request.app.state.oidc.metadata()
    logout_url: str | None = None
    if meta.end_session_endpoint and id_token:
        params = httpx.QueryParams(
            id_token_hint=id_token,
            post_logout_redirect_uri=request.app.state.settings.public_url,
        )
        logout_url = f"{meta.end_session_endpoint}?{params}"

    # The SPA clears its state and navigates to logout_url so the IdP SSO session
    # ends too (otherwise the next login silently re-authenticates the same user).
    return {"logout_url": logout_url}
