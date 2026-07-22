from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.db import get_session
from osaip_api.problem import Problem

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise Problem(
            503,
            title="Not ready",
            detail="The database is unreachable.",
            hint="Check that postgres is up and OSAIP_DATABASE_URL is correct.",
            slug="not-ready",
        ) from exc
    return {"status": "ready"}
