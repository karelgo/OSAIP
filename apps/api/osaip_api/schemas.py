"""Response models — the OpenAPI contract the TS client is generated from (§3.2)."""

from typing import Any

from pydantic import BaseModel


class StatusOut(BaseModel):
    status: str


class CapabilitiesOut(BaseModel):
    can_edit: bool
    can_manage_members: bool
    can_archive: bool
    can_manage_connections: bool


class ConnectionOut(BaseModel):
    id: str
    name: str
    kind: str
    config: dict[str, Any]
    has_secret: bool
    legal_basis: str
    purpose_codes: list[str]
    status: str
    created_at: str
    updated_at: str


class ConnectionListOut(BaseModel):
    items: list[ConnectionOut]


class ConnectionTestOut(BaseModel):
    ok: bool
    latency_ms: float


class ColumnOut(BaseModel):
    name: str
    type: str
    nullable: bool = True
    classification: str = "none"  # CP-1, per-column


class UploadOut(BaseModel):
    upload_id: str
    filename: str
    format: str
    # named `columns`, not `schema` — the latter collides with pydantic internals
    columns: list[ColumnOut]
    params: dict[str, Any]
    preview: list[dict[str, Any]]


class InspectOut(BaseModel):
    columns: list[ColumnOut]
    preview: list[dict[str, Any]]


class DatasetOut(BaseModel):
    name: str
    kind: str
    description: str
    status: str
    classification: str
    bbn_level: str | None
    confidentiality: str | None
    legal_basis: str
    purpose_codes: list[str]
    params: dict[str, Any]
    connection_id: str | None
    current_version: int
    columns: list[ColumnOut]
    row_count: int | None
    row_count_kind: str | None
    has_profile: bool
    created_at: str
    updated_at: str


class DatasetListItemOut(BaseModel):
    name: str
    kind: str
    description: str
    classification: str
    bbn_level: str | None
    confidentiality: str | None
    row_count: int | None
    row_count_kind: str | None
    current_version: int
    updated_at: str


class DatasetListOut(BaseModel):
    items: list[DatasetListItemOut]
    next_cursor: str | None


class SampleOut(BaseModel):
    columns: list[ColumnOut]
    rows: list[dict[str, Any]]
    limit: int


class ProfileOut(BaseModel):
    profile: dict[str, Any]


class ProjectOut(BaseModel):
    key: str
    name: str
    description: str
    status: str
    role: str
    capabilities: CapabilitiesOut
    created_at: str
    updated_at: str


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    next_cursor: str | None


class MemberOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    role: str


class MembersOut(BaseModel):
    items: list[MemberOut]


class AuditEntryOut(BaseModel):
    seq: int
    ts: str
    actor_id: str | None
    project_id: str | None = None
    action: str
    object_kind: str
    object_id: str | None
    details: dict[str, Any]


class AuditListOut(BaseModel):
    items: list[AuditEntryOut]
    next_before_seq: int | None


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    first_bad_seq: int | None
    reason: str | None


class SearchItemOut(BaseModel):
    kind: str
    name: str
    description: str
    url_path: str
    project_key: str | None


class SearchOut(BaseModel):
    items: list[SearchItemOut]


class NotificationOut(BaseModel):
    id: str
    kind: str
    severity: str
    title: str
    body: str
    ref_kind: str | None
    ref_id: str | None
    created_at: str
    read_at: str | None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread_count: int


class MarkAllReadOut(BaseModel):
    marked_read: int


class LogoutOut(BaseModel):
    logout_url: str | None


class EmitTestEventOut(BaseModel):
    notification_id: str
