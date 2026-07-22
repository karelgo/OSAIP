"""Request auth dependencies."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.auth.service import SESSION_COOKIE, resolve_session
from osaip_api.db import get_session
from osaip_api.models import Session as SessionRow
from osaip_api.models import User
from osaip_api.problem import Problem


async def current_user_and_session(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> tuple[User, SessionRow]:
    resolved = await resolve_session(
        session, request.app.state.settings, request.cookies.get(SESSION_COOKIE)
    )
    if resolved is None:
        raise Problem(
            401,
            title="Not signed in",
            detail="This request requires a signed-in user.",
            hint="Sign in and try again.",
            slug="unauthenticated",
        )
    return resolved


async def current_user(
    user_and_session: Annotated[tuple[User, SessionRow], Depends(current_user_and_session)],
) -> User:
    return user_and_session[0]


CurrentUser = Annotated[User, Depends(current_user)]
