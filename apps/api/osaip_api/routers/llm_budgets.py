"""Quotas, usage rollups, prompts and guardrail policies (Phase 3a).

§10 makes budgets mandatory from Phase 3, so quotas are a first-class managed object
rather than a config file. Usage is the other half of the same story: a budget nobody
can see the spend against is not a control.
"""

import datetime
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.etag import etag_json_response
from osaip_api.idempotency import check_idempotency, store_idempotent_response
from osaip_api.models import GuardrailPolicy, Prompt, Quota
from osaip_api.permissions import load_project_context, require_site_admin
from osaip_api.problem import Problem
from osaip_api.usage import GROUP_BY_VALUES, GroupBy, usage_report
from osaip_shared.ids import new_id

router = APIRouter(tags=["llm-budgets"])

DbSession = Annotated[AsyncSession, Depends(get_session)]

ScopeType = Literal["project", "user", "connection", "agent"]
Period = Literal["day", "month"]
Action = Literal["warn", "block"]

# A window longer than this is not a budget anyone reviews.
MAX_RANGE_DAYS = 366


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ── quotas ──────────────────────────────────────────────────────────────────────


class QuotaCreate(BaseModel):
    scope_type: ScopeType = "project"
    # Optional for a project-scoped quota: the path already names the project, and the
    # API addresses projects by KEY — it never hands out the uuid, so requiring one here
    # would make the common case impossible to express.
    scope_id: uuid.UUID | None = None
    period: Period = "month"
    limit_cost_micros: int | None = Field(default=None, ge=0)
    limit_calls: int | None = Field(default=None, ge=0)
    action: Action = "block"

    @model_validator(mode="after")
    def _coherent(self) -> "QuotaCreate":
        if self.limit_cost_micros is None and self.limit_calls is None:
            # A quota with no limit is not a permissive quota, it is a no-op that looks
            # like a control — the worst kind of configuration.
            raise ValueError("set limit_cost_micros, limit_calls, or both")
        if self.scope_type != "project" and self.scope_id is None:
            raise ValueError(f"a {self.scope_type} quota needs a scope_id")
        return self


class QuotaUpdate(BaseModel):
    limit_cost_micros: int | None = Field(default=None, ge=0)
    limit_calls: int | None = Field(default=None, ge=0)
    action: Action | None = None


def _quota_payload(quota: Quota) -> dict[str, Any]:
    return {
        "id": str(quota.id),
        "scope_type": quota.scope_type,
        "scope_id": str(quota.scope_id),
        "period": quota.period,
        "limit_cost_micros": quota.limit_cost_micros,
        "limit_calls": quota.limit_calls,
        "action": quota.action,
        "created_at": quota.created_at.isoformat(),
        "updated_at": quota.updated_at.isoformat(),
    }


@router.get("/projects/{key}/quotas")
async def list_quotas(key: str, request: Request, user: CurrentUser, session: DbSession) -> Any:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    rows = (
        (
            await session.execute(
                select(Quota)
                .where(Quota.scope_type == "project", Quota.scope_id == ctx.project.id)
                .order_by(Quota.period)
            )
        )
        .scalars()
        .all()
    )
    return etag_json_response(request, {"items": [_quota_payload(row) for row in rows]})


@router.post("/projects/{key}/quotas", status_code=201)
async def create_quota(
    key: str, body: QuotaCreate, request: Request, user: CurrentUser, session: DbSession
) -> JSONResponse:
    ctx = await load_project_context(session, user, key, min_role="admin")
    if body.scope_type == "project":
        if body.scope_id is not None and body.scope_id != ctx.project.id:
            # Otherwise a project admin could set a budget on someone else's project.
            raise Problem(
                403,
                title="Scope outside this project",
                detail="A project-scoped quota must target the project in the path.",
                hint="Omit scope_id — the path already names the project.",
                slug="forbidden",
            )
        scope_id = ctx.project.id
    else:
        assert body.scope_id is not None  # guaranteed by the model validator
        scope_id = body.scope_id
    idem_key, req_hash, stored = await check_idempotency(
        session, request, user, {**body.model_dump(mode="json"), "scope_id": str(scope_id)}
    )
    if stored is not None:
        return JSONResponse(content=stored[1], status_code=stored[0])

    duplicate = (
        await session.execute(
            select(Quota.id).where(
                Quota.scope_type == body.scope_type,
                Quota.scope_id == scope_id,
                Quota.period == body.period,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise Problem(
            409,
            title="Quota already exists",
            detail=f"This scope already has a {body.period} budget.",
            hint="Update the existing one instead.",
            slug="conflict",
        )

    quota = Quota(
        id=new_id(),
        scope_type=body.scope_type,
        scope_id=scope_id,
        period=body.period,
        limit_cost_micros=body.limit_cost_micros,
        limit_calls=body.limit_calls,
        action=body.action,
    )
    session.add(quota)
    await session.flush()
    payload = _quota_payload(quota)
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="quota.created",
        object_kind="quota",
        object_id=str(quota.id),
        details={
            "scope_type": body.scope_type,
            "period": body.period,
            "action": body.action,
            "limit_cost_micros": body.limit_cost_micros,
            "limit_calls": body.limit_calls,
        },
        ip=_client_ip(request),
    )
    if idem_key:
        await store_idempotent_response(session, user, idem_key, request, req_hash, 201, payload)
    await session.commit()
    return JSONResponse(content=payload, status_code=201)


async def _load_quota(session: AsyncSession, quota_id: uuid.UUID) -> Quota:
    quota = (await session.execute(select(Quota).where(Quota.id == quota_id))).scalar_one_or_none()
    if quota is None:
        raise Problem(
            404,
            title="Quota not found",
            detail="No such quota.",
            hint="It may have been deleted.",
            slug="not-found",
        )
    return quota


@router.patch("/projects/{key}/quotas/{quota_id}")
async def update_quota(
    key: str,
    quota_id: uuid.UUID,
    body: QuotaUpdate,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> Any:
    ctx = await load_project_context(session, user, key, min_role="admin")
    quota = await _load_quota(session, quota_id)
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(quota, field, value)
    if quota.limit_cost_micros is None and quota.limit_calls is None:
        raise Problem(
            422,
            title="A quota needs a limit",
            detail="Clearing both limits would leave a control that enforces nothing.",
            hint="Keep at least one of limit_cost_micros or limit_calls, or delete it.",
            slug="validation",
        )
    await session.flush()
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="quota.updated",
        object_kind="quota",
        object_id=str(quota.id),
        details={"fields": sorted(changes)},
        ip=_client_ip(request),
    )
    await session.commit()
    await session.refresh(quota)
    return _quota_payload(quota)


@router.delete("/projects/{key}/quotas/{quota_id}", status_code=204)
async def delete_quota(
    key: str, quota_id: uuid.UUID, request: Request, user: CurrentUser, session: DbSession
) -> Response:
    ctx = await load_project_context(session, user, key, min_role="admin")
    quota = await _load_quota(session, quota_id)
    details = {
        "scope_type": quota.scope_type,
        "period": quota.period,
        "limit_cost_micros": quota.limit_cost_micros,
        "limit_calls": quota.limit_calls,
    }
    await session.delete(quota)
    await session.flush()
    # Removing a budget is a control being switched off; it belongs in the audit with
    # what it used to be, not merely as "deleted".
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="quota.deleted",
        object_kind="quota",
        object_id=str(quota_id),
        details=details,
        ip=_client_ip(request),
    )
    await session.commit()
    return Response(status_code=204)


# ── usage ───────────────────────────────────────────────────────────────────────


@router.get("/projects/{key}/usage")
async def get_usage(
    key: str,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    group_by: Annotated[GroupBy, Query()] = "day",
    from_: Annotated[datetime.datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime.datetime | None, Query()] = None,
) -> Any:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    if group_by not in GROUP_BY_VALUES:
        raise Problem(
            422,
            title="Unknown grouping",
            detail=f"group_by must be one of: {', '.join(GROUP_BY_VALUES)}.",
            hint="Try group_by=day.",
            slug="validation",
        )
    to_ts = _aware(to) or datetime.datetime.now(datetime.UTC)
    from_ts = _aware(from_) or (to_ts - datetime.timedelta(days=30))
    if from_ts >= to_ts:
        raise Problem(
            422,
            title="Empty range",
            detail="`from` must be before `to`.",
            hint="Check the dates.",
            slug="validation",
        )
    if (to_ts - from_ts).days > MAX_RANGE_DAYS:
        raise Problem(
            422,
            title="Range too large",
            detail=f"Usage can be queried over at most {MAX_RANGE_DAYS} days.",
            hint="Narrow the range.",
            slug="validation",
        )

    report = await usage_report(
        session,
        project_id=ctx.project.id,
        from_ts=from_ts,
        to_ts=to_ts,
        group_by=group_by,
    )
    payload = {
        "from": report.from_ts.isoformat(),
        "to": report.to_ts.isoformat(),
        "group_by": report.group_by,
        "currency": report.currency,
        # True when some call used a model with no pinned price: the total is a FLOOR,
        # and the UI must say so rather than imply the spend is exact.
        "pricing_incomplete": report.pricing_incomplete,
        "total": _bucket(report.total),
        "buckets": [_bucket(bucket) for bucket in report.buckets],
    }
    return etag_json_response(request, payload)


def _aware(value: datetime.datetime | None) -> datetime.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=datetime.UTC)


def _bucket(bucket: Any) -> dict[str, Any]:
    return {
        "key": bucket.key,
        "calls": bucket.calls,
        "tokens_in": bucket.tokens_in,
        "tokens_out": bucket.tokens_out,
        "cost_micros": bucket.cost_micros,
        "cache_hits": bucket.cache_hits,
        "errors": bucket.errors,
    }


# ── prompts ─────────────────────────────────────────────────────────────────────


class PromptUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template: str = Field(min_length=1, max_length=100_000)
    variables: dict[str, Any] = Field(default_factory=dict)
    model_defaults: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=20)


def _prompt_payload(prompt: Prompt) -> dict[str, Any]:
    return {
        "id": str(prompt.id),
        "project_id": str(prompt.project_id) if prompt.project_id else None,
        "name": prompt.name,
        "version": prompt.version,
        "template": prompt.template,
        "variables": prompt.variables,
        "model_defaults": prompt.model_defaults,
        "tags": list(prompt.tags),
        "created_at": prompt.created_at.isoformat(),
    }


@router.get("/projects/{key}/prompts")
async def list_prompts(key: str, request: Request, user: CurrentUser, session: DbSession) -> Any:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    rows = (
        (
            await session.execute(
                select(Prompt)
                .where(Prompt.project_id == ctx.project.id)
                .order_by(Prompt.name, Prompt.version.desc())
            )
        )
        .scalars()
        .all()
    )
    # Latest version per name; the history stays reachable via the detail route.
    latest: dict[str, Prompt] = {}
    for row in rows:
        latest.setdefault(row.name, row)
    return etag_json_response(request, {"items": [_prompt_payload(p) for p in latest.values()]})


@router.post("/projects/{key}/prompts", status_code=201)
async def upsert_prompt(
    key: str, body: PromptUpsert, request: Request, user: CurrentUser, session: DbSession
) -> JSONResponse:
    """Prompts are append-only: saving an existing name adds a VERSION.

    A prompt is part of how a decision was produced, so overwriting one would erase the
    explanation of every past call that used it (AI Act Art 12).
    """
    ctx = await load_project_context(session, user, key, min_role="editor")
    _reject_hand_rolled_delimiters(body.template)

    current = (
        await session.execute(
            select(Prompt)
            .where(Prompt.project_id == ctx.project.id, Prompt.name == body.name)
            .order_by(Prompt.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    version = (current.version + 1) if current else 1

    prompt = Prompt(
        id=new_id(),
        project_id=ctx.project.id,
        name=body.name,
        version=version,
        template=body.template,
        variables=body.variables,
        model_defaults=body.model_defaults,
        tags=body.tags,
        created_by=user.id,
    )
    session.add(prompt)
    await session.flush()
    payload = _prompt_payload(prompt)
    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="prompt.saved",
        object_kind="prompt",
        object_id=str(prompt.id),
        details={"name": body.name, "version": version},
        ip=_client_ip(request),
    )
    await session.commit()
    return JSONResponse(content=payload, status_code=201)


def _reject_hand_rolled_delimiters(template: str) -> None:
    """§5d: untrusted content is interpolated with `untrusted_block()`, never by writing
    the delimiters into a template — a hand-written closing tag is exactly what an
    attacker can forge."""
    from osaip_guardrails.untrusted import has_delimiter_syntax

    if has_delimiter_syntax(template):
        raise Problem(
            422,
            title="Template writes the untrusted delimiters itself",
            detail=(
                "This template contains <untrusted> markup. Untrusted content is wrapped "
                "by the platform, not by the template."
            ),
            hint="Use a {placeholder}; the platform wraps the value it substitutes.",
            slug="validation",
        )


@router.get("/projects/{key}/prompts/{name}")
async def get_prompt_versions(
    key: str, name: str, request: Request, user: CurrentUser, session: DbSession
) -> Any:
    ctx = await load_project_context(session, user, key, min_role="viewer")
    rows = (
        (
            await session.execute(
                select(Prompt)
                .where(Prompt.project_id == ctx.project.id, Prompt.name == name)
                .order_by(Prompt.version.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise Problem(
            404,
            title="Prompt not found",
            detail=f"No prompt named {name!r} in this project.",
            hint="Check the name.",
            slug="not-found",
        )
    return etag_json_response(
        request,
        {"name": name, "versions": [_prompt_payload(row) for row in rows]},
    )


# ── guardrail policies ──────────────────────────────────────────────────────────


class PolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stages: dict[str, Any] = Field(default_factory=dict)


def _policy_payload(policy: GuardrailPolicy, *, effective: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(policy.id),
        "project_id": str(policy.project_id) if policy.project_id else None,
        "name": policy.name,
        "stages": policy.stages,
        # What the policy ACTUALLY resolves to once merged with the non-removable
        # baseline — so an operator can see that PII redaction is on regardless of what
        # the document says (BIO2 8.12).
        "effective": effective,
        "created_at": policy.created_at.isoformat(),
        "updated_at": policy.updated_at.isoformat(),
    }


def _effective(stages: dict[str, Any]) -> dict[str, Any]:
    from osaip_guardrails.policy import merge_policy
    from osaip_guardrails.presidio_nl import is_available

    policy = merge_policy(stages)
    return {
        "redact_pii": policy.redact_pii,
        "use_presidio": policy.use_presidio,
        # Whether the model-backed pass can actually run here: the Dutch model is
        # operator-installed (ADR-0009), so a policy may ask for it and not get it.
        "presidio_available": is_available() if policy.use_presidio else None,
        "max_input_chars": policy.max_input_chars,
        "judge_model": policy.judge_model,
        "has_output_schema": policy.output_schema is not None,
    }


@router.get("/guardrail-policies")
async def list_policies(request: Request, user: CurrentUser, session: DbSession) -> Any:
    require_site_admin(user)
    rows = (
        (await session.execute(select(GuardrailPolicy).order_by(GuardrailPolicy.name)))
        .scalars()
        .all()
    )
    return etag_json_response(
        request,
        {"items": [_policy_payload(row, effective=_effective(row.stages)) for row in rows]},
    )


@router.post("/guardrail-policies", status_code=201)
async def create_policy(
    body: PolicyCreate, request: Request, user: CurrentUser, session: DbSession
) -> JSONResponse:
    require_site_admin(user)
    idem_key, req_hash, stored = await check_idempotency(session, request, user, body.model_dump())
    if stored is not None:
        return JSONResponse(content=stored[1], status_code=stored[0])

    duplicate = (
        await session.execute(
            select(GuardrailPolicy.id).where(
                GuardrailPolicy.project_id.is_(None), GuardrailPolicy.name == body.name
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise Problem(
            409,
            title="Name already in use",
            detail=f"A guardrail policy named {body.name!r} already exists.",
            hint="Pick a different name.",
            slug="conflict",
        )

    policy = GuardrailPolicy(id=new_id(), project_id=None, name=body.name, stages=body.stages)
    session.add(policy)
    await session.flush()
    payload = _policy_payload(policy, effective=_effective(policy.stages))
    await write_audit(
        session,
        actor_id=user.id,
        project_id=None,
        action="guardrail_policy.created",
        object_kind="guardrail_policy",
        object_id=str(policy.id),
        details={"name": body.name, "effective": payload["effective"]},
        ip=_client_ip(request),
    )
    if idem_key:
        await store_idempotent_response(session, user, idem_key, request, req_hash, 201, payload)
    await session.commit()
    return JSONResponse(content=payload, status_code=201)
