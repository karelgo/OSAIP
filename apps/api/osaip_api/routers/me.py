"""Current-user profile and preferences."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.models import UserPrefs

router = APIRouter(tags=["me"])


class PrefsOut(BaseModel):
    theme: str = "system"
    density: str = "comfortable"
    pinned: list[Any] = Field(default_factory=list)


class MeOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_site_admin: bool
    prefs: PrefsOut


class PrefsPatch(BaseModel):
    theme: str | None = Field(default=None, pattern="^(system|light|dark)$")
    density: str | None = Field(default=None, pattern="^(comfortable|compact)$")
    pinned: list[Any] | None = None


async def _load_prefs(session: AsyncSession, user_id: Any) -> PrefsOut:
    row = (
        await session.execute(select(UserPrefs).where(UserPrefs.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        return PrefsOut()
    return PrefsOut(theme=row.theme, density=row.density, pinned=row.pinned)


@router.get("/me")
async def get_me(
    user: CurrentUser, session: Annotated[AsyncSession, Depends(get_session)]
) -> MeOut:
    return MeOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        is_site_admin=user.is_site_admin,
        prefs=await _load_prefs(session, user.id),
    )


@router.patch("/me/prefs")
async def patch_prefs(
    patch: PrefsPatch,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PrefsOut:
    row = (
        await session.execute(select(UserPrefs).where(UserPrefs.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        row = UserPrefs(user_id=user.id)
        session.add(row)
    if patch.theme is not None:
        row.theme = patch.theme
    if patch.density is not None:
        row.density = patch.density
    if patch.pinned is not None:
        row.pinned = patch.pinned
    await session.commit()
    return PrefsOut(theme=row.theme, density=row.density, pinned=row.pinned)
