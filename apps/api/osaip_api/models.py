"""Phase 0 domain tables (spec §4 foundation subset + app-shell tables).

Ordering rules (ADR-0003/0005): UUIDv7 `id` columns are identifiers only; anything that
needs a total order (audit chain, SSE cursor) has its own sequence column.
"""

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from osaip_api.db import Base
from osaip_shared.ids import new_id


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)


def _created_at() -> Mapped[datetime.datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _updated_at() -> Mapped[datetime.datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    oidc_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_site_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Session(Base):
    """Server-side auth session (ADR-0001). The cookie holds a signed random token;
    only its SHA-256 lands here (spec §8: hash all tokens)."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    oidc_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    oidc_sid: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    id_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = _created_at()
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint(r"key ~ '^[a-z][a-z0-9_-]{1,63}$'", name="key_slug"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    storage_prefix: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (CheckConstraint("role IN ('viewer', 'editor', 'admin')", name="role"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()


class AuditLog(Base):
    """Hash-chained, append-only (CP-7; ADR-0005). `seq` is the chain order; triggers
    in migration 0001 block UPDATE/DELETE/TRUNCATE."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    ts: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Text, not INET: asyncpg decodes INET to ipaddress objects, which would break the
    # byte-stable canonical round-trip the hash chain depends on (ADR-0005).
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_audit_log_project_seq", "project_id", "seq"),)


class ObjectRef(Base):
    """Search registry powering ⌘K (§6.6). `embedding` joins in Phase 3 (hybrid)."""

    __tablename__ = "object_refs"
    __table_args__ = (
        UniqueConstraint("kind", "project_id", "name", name="uq_object_refs_kind_project_name"),
        Index("ix_object_refs_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url_path: Mapped[str] = mapped_column(String(500), nullable=False)
    updated_at: Mapped[datetime.datetime] = _updated_at()
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', name || ' ' || description)", persisted=True),
        nullable=True,
    )


class Event(Base):
    """SSE bus row (ADR-0003). `seq` is the only cursor."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True, nullable=False)
    ts: Mapped[datetime.datetime] = _created_at()
    topic: Mapped[str] = mapped_column(String(50), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("severity IN ('info', 'success', 'warning', 'error')", name="severity"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ref_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = _created_at()
    read_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserPrefs(Base):
    __tablename__ = "user_prefs"
    __table_args__ = (
        CheckConstraint("theme IN ('system', 'light', 'dark')", name="theme"),
        CheckConstraint("density IN ('comfortable', 'compact')", name="density"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    density: Mapped[str] = mapped_column(String(16), nullable=False, default="comfortable")
    pinned: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    method_path: Mapped[str] = mapped_column(String(500), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()


class Secret(Base):
    """MultiFernet ciphertext for connection credentials (ADR-0006 §1). Write-only
    through the API; `key_id` records which key encrypted this value."""

    __tablename__ = "secrets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class Connection(Base):
    """Data connection (spec §4). `config` is non-secret; credentials live in
    `secrets`. CP-2: legal basis + purpose codes are mandatory."""

    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint("kind IN ('postgres', 's3', 'duckdb_file')", name="kind"),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        UniqueConstraint("project_id", "name", name="uq_connections_project_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("secrets.id", ondelete="SET NULL"), nullable=True
    )
    legal_basis: Mapped[str] = mapped_column(String(500), nullable=False)
    purpose_codes: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class Dataset(Base):
    """Dataset = schema + location + params (spec §1). CP-1 labels are tri-field
    (classification / bbn_level / confidentiality — orthogonal axes); CP-2 purpose
    metadata mirrors connections and is required at creation."""

    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("kind IN ('file', 'table', 's3', 'duckdb_file')", name="kind"),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint(
            "classification IN ('none', 'persoonsgegevens', 'bijzonder', 'bsn')",
            name="classification",
        ),
        CheckConstraint(
            "bbn_level IS NULL OR bbn_level IN ('bbn1', 'bbn2', 'bbn3')", name="bbn_level"
        ),
        CheckConstraint(
            "confidentiality IS NULL OR confidentiality IN ('intern', 'vertrouwelijk', 'geheim')",
            name="confidentiality",
        ),
        UniqueConstraint("project_id", "name", name="uq_datasets_project_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("connections.id", ondelete="RESTRICT"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    bbn_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    confidentiality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    legal_basis: Mapped[str] = mapped_column(String(500), nullable=False)
    purpose_codes: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        CheckConstraint("format IN ('parquet', 'external')", name="format"),
        CheckConstraint(
            "row_count_kind IS NULL OR row_count_kind IN ('exact', 'estimate')",
            name="row_count_kind",
        ),
        UniqueConstraint("dataset_id", "version", name="uq_dataset_versions_dataset_version"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[str] = mapped_column(String(1000), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    row_count_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Phase 2 staleness + reconstructability (ADR-0007 §2/§3): the producer's config
    # hash, the input versions this build consumed, and a snapshot of the exact recipe
    # config that produced this version.
    recipe_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_versions: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = _created_at()


# ── Phase 2: recipes, flow, jobs ─────────────────────────────────────────────────

RECIPE_KINDS = ("prepare", "join", "group", "stack", "split", "sample", "sql", "python")


class Recipe(Base):
    """A transformation node in the Flow. `config` is the recipe-kind-specific JSON;
    `config_hash` is computed in Python from the validated model (ADR-0007 §2).
    Single-producer is enforced by the unique constraint on recipe_outputs."""

    __tablename__ = "recipes"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('prepare', 'join', 'group', 'stack', 'split', 'sample', 'sql', 'python')",
            name="kind",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        UniqueConstraint("project_id", "name", name="uq_recipes_project_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, server_default=text("'{}'::text[]")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class RecipeInput(Base):
    __tablename__ = "recipe_inputs"
    __table_args__ = (
        UniqueConstraint("recipe_id", "ordinal", name="uq_recipe_inputs_recipe_ordinal"),
    )

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class RecipeOutput(Base):
    """A dataset is produced by at most ONE recipe (spec §4 single-producer): the
    unique constraint on dataset_id is GLOBAL, not per-recipe."""

    __tablename__ = "recipe_outputs"
    __table_args__ = (UniqueConstraint("dataset_id", name="uq_recipe_outputs_dataset"),)

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "trigger IN ('manual', 'cron', 'dataset_updated', 'scenario')", name="trigger"
        ),
        Index("ix_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="build")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Post-claim concurrency is guarded by status + heartbeat, not the row lock
    # (ADR-0007 §1): the claim commit releases FOR UPDATE immediately.
    heartbeat_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = _created_at()
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class JobStep(Base):
    __tablename__ = "job_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')", name="status"
        ),
        UniqueConstraint("job_id", "ordinal", name="uq_job_steps_job_ordinal"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )
    target_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    log_prefix: Mapped[str | None] = mapped_column(String(500), nullable=True)
    log_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ── Phase 3a: the LLM Mesh (ADR-0008) ────────────────────────────────────────────

PROVIDERS = ("echo", "openai", "anthropic", "ollama")
DATA_RESIDENCY = ("local", "eu", "external")


class LlmConnection(Base):
    """A model endpoint the mesh may call (spec §4). Credentials live in `secrets`;
    `data_residency` is OPERATOR-ASSERTED metadata the CP-11 gate acts on (ADR-0008
    §7) — it records an assertion, it does not prove geography."""

    __tablename__ = "llm_connections"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'project')", name="scope"),
        CheckConstraint("provider IN ('echo', 'openai', 'anthropic', 'ollama')", name="provider"),
        CheckConstraint("data_residency IN ('local', 'eu', 'external')", name="data_residency"),
        CheckConstraint("audit_mode IN ('full', 'redacted', 'off')", name="audit_mode"),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        # Global connections have no project; project-scoped ones must have one.
        CheckConstraint(
            "(scope = 'global' AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL)",
            name="scope_project",
        ),
        UniqueConstraint("project_id", "name", name="uq_llm_connections_project_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="project")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    base_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    allowed_models: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)), nullable=False, server_default=text("'{}'::text[]")
    )
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("secrets.id", ondelete="SET NULL"), nullable=True
    )
    guardrail_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("guardrail_policies.id", ondelete="SET NULL"), nullable=True
    )
    cache_ttl_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="redacted")
    data_residency: Mapped[str] = mapped_column(String(16), nullable=False, default="external")
    # CP-2 / Art 30 RoPA: an LLM connection is a processor relationship.
    legal_basis: Mapped[str] = mapped_column(String(500), nullable=False)
    purpose_codes: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class GuardrailPolicy(Base):
    """Named stage configuration. The baseline PII-redaction stage is applied to every
    call regardless of policy and cannot be removed (BIO2 8.12, ADR-0008 §5)."""

    __tablename__ = "guardrail_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_guardrail_policies_project_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stages: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class Trace(Base):
    """Root of a span tree (spec §4). Phase 3a writes recipe/manual roots; agents,
    chat, evals and semantic plans join in later phases."""

    __tablename__ = "traces"
    __table_args__ = (
        CheckConstraint(
            "root_kind IN ('agent', 'recipe', 'chat', 'eval', 'semantic', 'manual')",
            name="root_kind",
        ),
    )

    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    root_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime.datetime] = _created_at()
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    span_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Span(Base):
    __tablename__ = "spans"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('llm', 'tool', 'retrieval', 'guardrail', 'agent', 'plan', 'recipe')",
            name="kind",
        ),
        Index("ix_spans_trace", "trace_id", "t0"),
    )

    span_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("traces.trace_id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    t0: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    t1: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")


class LlmCall(Base):
    """The usage ledger (spec §4 + build attribution). Rows are plain inserts in their
    OWN short transaction — deliberately outside the hash-chained audit's global
    advisory lock, so per-row LLM builds never serialize the platform (ADR-0008 §8)."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_calls_project_ts", "project_id", "ts"),
        Index("ix_llm_calls_job", "job_id"),
        Index("ix_llm_calls_trace", "trace_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    ts: Mapped[datetime.datetime] = _created_at()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    span_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Attribution: which build/step/row produced this call (§6.3(7) "why?").
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    job_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    row_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_connections.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    pricing_unknown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
    guardrail_events_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class LlmCallMessage(Base):
    """Audited prompt/response text. `content_redacted` is ALWAYS stored; the raw
    variant only when the connection's audit_mode='full' (ADR-0008 §8)."""

    __tablename__ = "llm_call_messages"
    __table_args__ = (UniqueConstraint("call_id", "seq", name="uq_llm_call_messages_call_seq"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    content_raw: Mapped[str | None] = mapped_column(Text, nullable=True)


class LlmCache(Base):
    """Response cache keyed on the REDACTED payload (ADR-0008 §4); project_id is part
    of the key so a global connection never leaks one project's completions."""

    __tablename__ = "llm_cache"

    request_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_connections.id", ondelete="CASCADE"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime.datetime] = _created_at()
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Quota(Base):
    __tablename__ = "quotas"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('project', 'user', 'connection', 'agent')", name="scope_type"
        ),
        CheckConstraint("period IN ('day', 'month')", name="period"),
        CheckConstraint("action IN ('warn', 'block')", name="action"),
        UniqueConstraint("scope_type", "scope_id", "period", name="uq_quotas_scope_period"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False, default="month")
    limit_cost_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    limit_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False, default="block")
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()


class QuotaReservation(Base):
    """Reserve/settle (ADR-0008 §3): a reservation is visible to concurrent callers'
    window sums, so parallel calls cannot collectively overshoot a budget."""

    __tablename__ = "quota_reservations"
    __table_args__ = (Index("ix_quota_reservations_scope_ts", "scope_type", "scope_id", "ts"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ts: Mapped[datetime.datetime] = _created_at()
    estimated_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    settled_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class GuardrailEvent(Base):
    __tablename__ = "guardrail_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_calls.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    rule: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = _created_at()


class Prompt(Base):
    """Prompt registry (spec §4). System prompts are assembled server-side FROM HERE —
    a client may select a version, never supply the system role (§5d, ADR-0008 §6)."""

    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint("project_id", "name", "version", name="uq_prompts_project_name_version"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    model_defaults: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, server_default=text("'{}'::text[]")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = _created_at()
    updated_at: Mapped[datetime.datetime] = _updated_at()
