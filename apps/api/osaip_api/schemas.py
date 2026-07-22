"""Response models — the OpenAPI contract the TS client is generated from (§3.2)."""

from typing import Any

from pydantic import BaseModel


class StatusOut(BaseModel):
    status: str


class CapabilitiesOut(BaseModel):
    can_edit: bool
    can_manage_members: bool
    can_archive: bool


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
