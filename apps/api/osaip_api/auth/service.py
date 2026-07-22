"""User provisioning and server-side session management (ADR-0001)."""

import datetime
import hashlib
import secrets
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.config import Settings
from osaip_api.models import Session as SessionRow
from osaip_api.models import User

SESSION_COOKIE = "osaip_session"


def _serializer(settings: Settings) -> URLSafeSerializer:
    return URLSafeSerializer(settings.session_secret, salt="osaip.session")


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


async def provision_user(session: AsyncSession, *, claims: dict[str, Any], ip: str | None) -> User:
    """Upsert by oidc_sub on login; audits first-time creation and every login."""
    sub = str(claims["sub"])
    email = str(claims.get("email") or f"{sub}@unknown.invalid")
    display_name = str(claims.get("name") or claims.get("preferred_username") or email)
    now = datetime.datetime.now(datetime.UTC)

    user = (await session.execute(select(User).where(User.oidc_sub == sub))).scalar_one_or_none()
    created = user is None
    if user is None:
        user = User(oidc_sub=sub, email=email, display_name=display_name)
        session.add(user)
        await session.flush()
    else:
        user.email = email
        user.display_name = display_name
    user.last_login_at = now

    if created:
        await write_audit(
            session,
            actor_id=user.id,
            project_id=None,
            action="user.created",
            object_kind="user",
            object_id=str(user.id),
            details={"email": email},
            ip=ip,
        )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=None,
        action="auth.login",
        object_kind="user",
        object_id=str(user.id),
        ip=ip,
    )
    return user


async def create_session(
    session: AsyncSession,
    settings: Settings,
    *,
    user: User,
    oidc_sid: str | None,
    id_token: str | None,
) -> str:
    """Insert a session row and return the SIGNED cookie value (raw token never stored)."""
    raw = secrets.token_urlsafe(32)
    row = SessionRow(
        token_hash=_hash_token(raw),
        user_id=user.id,
        oidc_sub=user.oidc_sub,
        oidc_sid=oidc_sid,
        id_token=id_token,
        expires_at=datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(seconds=settings.session_ttl_seconds),
    )
    session.add(row)
    await session.flush()
    return _serializer(settings).dumps(raw)


async def resolve_session(
    session: AsyncSession, settings: Settings, cookie_value: str | None
) -> tuple[User, SessionRow] | None:
    if not cookie_value:
        return None
    try:
        raw = _serializer(settings).loads(cookie_value)
    except BadSignature:
        return None
    row = (
        await session.execute(select(SessionRow).where(SessionRow.token_hash == _hash_token(raw)))
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at <= datetime.datetime.now(datetime.UTC):
        await session.delete(row)
        await session.commit()
        return None
    user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None:
        return None
    return user, row


async def destroy_session(session: AsyncSession, row_id: Any) -> None:
    await session.execute(delete(SessionRow).where(SessionRow.id == row_id))
