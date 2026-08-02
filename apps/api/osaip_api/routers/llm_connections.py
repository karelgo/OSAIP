"""LLM connections CRUD + test (Phase 3a, spec §4/§5b).

Admin-only, because a connection decides where data may be sent and on whose budget.
API keys are write-only: they go into `secrets` via the Vault and are never readable
back through the API, not even by the admin who set them.

Two fields carry compliance weight and are therefore mandatory rather than optional:

* `data_residency` drives the CP-11 gate at the mesh. It is OPERATOR-ASSERTED metadata
  (ADR-0008 §7) — the platform enforces the declaration and audits it, but cannot verify
  where a remote endpoint really runs, so every response says so explicitly.
* `legal_basis` + `purpose_codes` (CP-2): a model endpoint is a processor, and a RoPA
  needs to say why data goes to it.
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.etag import etag_json_response
from osaip_api.idempotency import check_idempotency, store_idempotent_response
from osaip_api.mesh_client import MeshCallFailed, call_mesh
from osaip_api.models import GuardrailPolicy, LlmConnection, Secret
from osaip_api.object_refs import upsert_object_ref
from osaip_api.permissions import ProjectContext, load_project_context, require_site_admin
from osaip_api.problem import Problem
from osaip_api.secrets import Vault
from osaip_shared.ids import new_id

router = APIRouter(tags=["llm-connections"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

Provider = Literal["echo", "openai", "anthropic", "ollama"]
Residency = Literal["local", "eu", "external"]
AuditMode = Literal["full", "redacted", "off"]

# Providers that reach outside the operator's own boundary. Declaring one of these as
# `local` is the single most consequential mistake an operator can make here, so the
# API refuses the combination outright rather than trusting the dropdown.
_EXTERNAL_ONLY = {"openai", "anthropic"}


class LlmConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider: Provider
    base_config: dict[str, Any] = Field(default_factory=dict)
    allowed_models: list[str] = Field(default_factory=list, max_length=100)
    data_residency: Residency
    audit_mode: AuditMode = "redacted"
    cache_ttl_s: int = Field(default=0, ge=0, le=86_400)
    guardrail_policy_id: uuid.UUID | None = None
    # CP-2: a connection is a processor; a RoPA needs the why.
    legal_basis: str = Field(min_length=1, max_length=200)
    purpose_codes: list[str] = Field(min_length=1, max_length=20)
    # Write-only. Never echoed back, by anyone.
    secret: str | None = Field(default=None, min_length=1, max_length=4_000)

    @field_validator("allowed_models")
    @classmethod
    def _models(cls, value: list[str]) -> list[str]:
        for model in value:
            if not model or len(model) > 200:
                raise ValueError("model names must be 1-200 characters")
        return value


class LlmConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_config: dict[str, Any] | None = None
    allowed_models: list[str] | None = None
    data_residency: Residency | None = None
    audit_mode: AuditMode | None = None
    cache_ttl_s: int | None = Field(default=None, ge=0, le=86_400)
    guardrail_policy_id: uuid.UUID | None = None
    legal_basis: str | None = Field(default=None, min_length=1, max_length=200)
    purpose_codes: list[str] | None = Field(default=None, min_length=1, max_length=20)
    secret: str | None = Field(default=None, min_length=1, max_length=4_000)
    status: Literal["active", "archived"] | None = None


def _payload(connection: LlmConnection) -> dict[str, Any]:
    return {
        "id": str(connection.id),
        "scope": connection.scope,
        "project_id": str(connection.project_id) if connection.project_id else None,
        "name": connection.name,
        "provider": connection.provider,
        "base_config": connection.base_config,
        "allowed_models": list(connection.allowed_models),
        "data_residency": connection.data_residency,
        # Stated on every read so no UI or export can present the declaration as if the
        # platform had verified it.
        "residency_is_operator_asserted": True,
        "audit_mode": connection.audit_mode,
        "cache_ttl_s": connection.cache_ttl_s,
        "guardrail_policy_id": (
            str(connection.guardrail_policy_id) if connection.guardrail_policy_id else None
        ),
        "legal_basis": connection.legal_basis,
        "purpose_codes": list(connection.purpose_codes),
        "status": connection.status,
        # Whether a credential EXISTS — never the credential.
        "has_secret": connection.secret_id is not None,
        "created_at": connection.created_at.isoformat(),
        "updated_at": connection.updated_at.isoformat(),
    }


def _check_residency(provider: str, residency: str) -> None:
    if provider in _EXTERNAL_ONLY and residency != "external":
        raise Problem(
            422,
            title="Residency does not match the provider",
            detail=(
                f"{provider!r} is a hosted service outside your boundary, so it cannot be "
                f"declared {residency!r}."
            ),
            hint="Declare it `external`, or point base_url at a self-hosted endpoint.",
            slug="validation",
        )
    if provider == "echo" and residency != "local":
        raise Problem(
            422,
            title="Echo connections must be local",
            detail="The echo provider is a built-in mock; it never leaves this process.",
            hint="Set data_residency to 'local'.",
            slug="validation",
        )


async def _check_policy(session: AsyncSession, policy_id: uuid.UUID | None) -> None:
    if policy_id is None:
        return
    exists = (
        await session.execute(select(GuardrailPolicy.id).where(GuardrailPolicy.id == policy_id))
    ).scalar_one_or_none()
    if exists is None:
        raise Problem(
            422,
            title="Guardrail policy not found",
            detail="No such guardrail policy.",
            hint="Create the policy first, or omit guardrail_policy_id for the baseline.",
            slug="validation",
        )


async def _store_secret(
    session: AsyncSession,
    vault: Vault,
    connection: LlmConnection,
    value: str,
    *,
    project_id: uuid.UUID | None,
) -> None:
    secret = Secret(
        id=new_id(),
        project_id=project_id,
        name=f"llm_connection:{connection.name}",
        ciphertext=vault.encrypt(value),
        # Which key encrypted it, so a rotation can tell what still needs re-wrapping.
        key_id=vault.primary_key_id,
    )
    session.add(secret)
    await session.flush()
    connection.secret_id = secret.id


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ── project-scoped ──────────────────────────────────────────────────────────────


@router.get("/projects/{key}/llm-connections")
async def list_project_connections(
    key: str, request: Request, user: CurrentUser, session: DbSession
) -> Any:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    # Global connections are usable by every project, so the list a project sees is
    # its own plus the global ones — otherwise the UI would offer a model the mesh
    # would happily serve but the operator could not find.
    rows = (
        (
            await session.execute(
                select(LlmConnection)
                .where(
                    (LlmConnection.project_id == ctx.project.id)
                    | (LlmConnection.scope == "global"),
                    LlmConnection.status == "active",
                )
                .order_by(LlmConnection.scope, LlmConnection.name)
            )
        )
        .scalars()
        .all()
    )
    return etag_json_response(request, {"items": [_payload(row) for row in rows]})


@router.post("/projects/{key}/llm-connections", status_code=201)
async def create_project_connection(
    key: str,
    body: LlmConnectionCreate,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> JSONResponse:
    ctx = await load_project_context(session, user, key, min_role="admin")
    idem_key, req_hash, stored = await check_idempotency(
        session, request, user, body.model_dump(exclude={"secret"})
    )
    if stored is not None:
        return JSONResponse(content=stored[1], status_code=stored[0])

    _check_residency(body.provider, body.data_residency)
    await _check_policy(session, body.guardrail_policy_id)
    await _assert_name_free(session, ctx.project.id, body.name)

    connection = LlmConnection(
        id=new_id(),
        scope="project",
        project_id=ctx.project.id,
        name=body.name,
        provider=body.provider,
        base_config=body.base_config,
        allowed_models=body.allowed_models,
        data_residency=body.data_residency,
        audit_mode=body.audit_mode,
        cache_ttl_s=body.cache_ttl_s,
        guardrail_policy_id=body.guardrail_policy_id,
        legal_basis=body.legal_basis,
        purpose_codes=body.purpose_codes,
        status="active",
    )
    session.add(connection)
    await session.flush()
    if body.secret:
        await _store_secret(
            session, request.app.state.vault, connection, body.secret, project_id=ctx.project.id
        )
    await session.flush()
    await session.refresh(connection)

    payload = _payload(connection)
    await upsert_object_ref(
        session,
        kind="llm_connection",
        project_id=ctx.project.id,
        name=connection.name,
        description=f"{connection.provider} · {connection.data_residency}",
        url_path=f"/projects/{key}/settings?tab=llm&connection={connection.id}",
    )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="llm_connection.created",
        object_kind="llm_connection",
        object_id=str(connection.id),
        details={
            "name": body.name,
            "provider": body.provider,
            "data_residency": body.data_residency,
            "audit_mode": body.audit_mode,
        },
        ip=_client_ip(request),
    )
    if idem_key:
        await store_idempotent_response(session, user, idem_key, request, req_hash, 201, payload)
    await session.commit()
    return JSONResponse(content=payload, status_code=201)


async def _assert_name_free(session: AsyncSession, project_id: uuid.UUID | None, name: str) -> None:
    duplicate = (
        await session.execute(
            select(LlmConnection.id).where(
                LlmConnection.project_id.is_(project_id)
                if project_id is None
                else LlmConnection.project_id == project_id,
                LlmConnection.name == name,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise Problem(
            409,
            title="Name already in use",
            detail=f"An LLM connection named {name!r} already exists here.",
            hint="Pick a different name.",
            slug="conflict",
        )


async def _load(
    session: AsyncSession, ctx: ProjectContext, connection_id: uuid.UUID
) -> LlmConnection:
    connection = (
        await session.execute(select(LlmConnection).where(LlmConnection.id == connection_id))
    ).scalar_one_or_none()
    if connection is None:
        raise Problem(
            404,
            title="LLM connection not found",
            detail="No such LLM connection.",
            hint="It may have been deleted.",
            slug="not-found",
        )
    if connection.scope == "project" and connection.project_id != ctx.project.id:
        # Same answer as a missing row: whether another project owns a connection with
        # this id is not this project's business.
        raise Problem(
            404,
            title="LLM connection not found",
            detail="No such LLM connection.",
            hint="It may have been deleted.",
            slug="not-found",
        )
    return connection


@router.get("/projects/{key}/llm-connections/{connection_id}")
async def get_project_connection(
    key: str,
    connection_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> Any:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    connection = await _load(session, ctx, connection_id)
    return etag_json_response(request, _payload(connection))


@router.patch("/projects/{key}/llm-connections/{connection_id}")
async def update_project_connection(
    key: str,
    connection_id: uuid.UUID,
    body: LlmConnectionUpdate,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> Any:
    ctx = await load_project_context(session, user, key, min_role="admin")
    connection = await _load(session, ctx, connection_id)
    if connection.scope == "global":
        require_site_admin(user)

    changes = body.model_dump(exclude_unset=True, exclude={"secret"})
    provider = connection.provider
    residency = changes.get("data_residency", connection.data_residency)
    _check_residency(provider, residency)
    if "guardrail_policy_id" in changes:
        await _check_policy(session, body.guardrail_policy_id)
    if "name" in changes and changes["name"] != connection.name:
        await _assert_name_free(session, connection.project_id, str(changes["name"]))

    for field, value in changes.items():
        setattr(connection, field, value)
    if body.secret:
        await _store_secret(
            session,
            request.app.state.vault,
            connection,
            body.secret,
            project_id=connection.project_id,
        )
    await session.flush()

    # audit_mode is the setting that decides whether raw prompt text is retained, so a
    # change to it is recorded on its own terms rather than buried in a field list.
    if "audit_mode" in changes:
        await write_audit(
            session,
            actor_id=user.id,
            project_id=connection.project_id,
            action="llm_connection.audit_mode_changed",
            object_kind="llm_connection",
            object_id=str(connection.id),
            details={"to": connection.audit_mode},
            ip=_client_ip(request),
        )
    await write_audit(
        session,
        actor_id=user.id,
        project_id=connection.project_id,
        action="llm_connection.updated",
        object_kind="llm_connection",
        object_id=str(connection.id),
        details={"fields": sorted(changes), "secret_rotated": bool(body.secret)},
        ip=_client_ip(request),
    )
    await session.commit()
    await session.refresh(connection)
    return _payload(connection)


@router.delete("/projects/{key}/llm-connections/{connection_id}", status_code=204)
async def archive_project_connection(
    key: str,
    connection_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    ctx = await load_project_context(session, user, key, min_role="admin")
    connection = await _load(session, ctx, connection_id)
    if connection.scope == "global":
        require_site_admin(user)
    # Archived, not deleted: the ledger references it, and a deleted connection would
    # orphan the history of what was sent where.
    connection.status = "archived"
    await session.flush()
    await write_audit(
        session,
        actor_id=user.id,
        project_id=connection.project_id,
        action="llm_connection.archived",
        object_kind="llm_connection",
        object_id=str(connection.id),
        details={"name": connection.name},
        ip=_client_ip(request),
    )
    await session.commit()
    return Response(status_code=204)


@router.post("/projects/{key}/llm-connections/{connection_id}/test")
async def test_project_connection(
    key: str,
    connection_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> Any:
    """Send one tiny call through the MESH, not around it.

    Testing by calling the provider directly here would prove the credentials work
    while bypassing exactly the layer that matters — the residency gate, the
    guardrails, the ledger. A test that skips them tests the wrong thing.
    """
    ctx = await load_project_context(session, user, key, min_role="admin")
    connection = await _load(session, ctx, connection_id)
    model = connection.allowed_models[0] if connection.allowed_models else "echo-1"
    try:
        result = await call_mesh(
            request.app.state.settings,
            connection_id=connection.id,
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            project_id=ctx.project.id,
            user_id=user.id,
            purpose="connection_test",
            max_classification="none",
            max_tokens=16,
        )
    except MeshCallFailed as exc:
        return {
            "ok": False,
            "status": exc.status,
            "detail": exc.detail,
            "hint": exc.hint,
        }
    return {
        "ok": True,
        "model_version": result.get("model_version"),
        "tokens_in": result.get("tokens_in"),
        "tokens_out": result.get("tokens_out"),
        "cost_micros": result.get("cost_micros"),
        "currency": result.get("currency"),
        "latency_ms": result.get("latency_ms"),
    }


# ── global (site-admin) ─────────────────────────────────────────────────────────


@router.get("/llm-connections")
async def list_global_connections(request: Request, user: CurrentUser, session: DbSession) -> Any:
    require_site_admin(user)
    rows = (
        (
            await session.execute(
                select(LlmConnection)
                .where(LlmConnection.scope == "global")
                .order_by(LlmConnection.name)
            )
        )
        .scalars()
        .all()
    )
    return etag_json_response(request, {"items": [_payload(row) for row in rows]})


@router.post("/llm-connections", status_code=201)
async def create_global_connection(
    body: LlmConnectionCreate, request: Request, user: CurrentUser, session: DbSession
) -> JSONResponse:
    require_site_admin(user)
    idem_key, req_hash, stored = await check_idempotency(
        session, request, user, body.model_dump(exclude={"secret"})
    )
    if stored is not None:
        return JSONResponse(content=stored[1], status_code=stored[0])

    _check_residency(body.provider, body.data_residency)
    await _check_policy(session, body.guardrail_policy_id)
    await _assert_name_free(session, None, body.name)

    connection = LlmConnection(
        id=new_id(),
        scope="global",
        project_id=None,
        name=body.name,
        provider=body.provider,
        base_config=body.base_config,
        allowed_models=body.allowed_models,
        data_residency=body.data_residency,
        audit_mode=body.audit_mode,
        cache_ttl_s=body.cache_ttl_s,
        guardrail_policy_id=body.guardrail_policy_id,
        legal_basis=body.legal_basis,
        purpose_codes=body.purpose_codes,
        status="active",
    )
    session.add(connection)
    await session.flush()
    if body.secret:
        await _store_secret(
            session, request.app.state.vault, connection, body.secret, project_id=None
        )
    await session.flush()
    await session.refresh(connection)

    payload = _payload(connection)
    await write_audit(
        session,
        actor_id=user.id,
        project_id=None,
        action="llm_connection.created",
        object_kind="llm_connection",
        object_id=str(connection.id),
        details={
            "scope": "global",
            "name": body.name,
            "provider": body.provider,
            "data_residency": body.data_residency,
        },
        ip=_client_ip(request),
    )
    if idem_key:
        await store_idempotent_response(session, user, idem_key, request, req_hash, 201, payload)
    await session.commit()
    return JSONResponse(content=payload, status_code=201)
