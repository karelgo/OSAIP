"""ObjectRef (⌘K search registry) upsert/remove helpers.

Upsert is ON CONFLICT on (kind, project_id, name): datasets seeded as fake refs in
Phase 0 (and re-runs of seed) must replace rather than collide.
"""

import uuid

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import ObjectRef
from osaip_shared.ids import new_id


async def upsert_object_ref(
    session: AsyncSession,
    *,
    kind: str,
    project_id: uuid.UUID | None,
    name: str,
    description: str,
    url_path: str,
) -> None:
    statement = (
        insert(ObjectRef)
        .values(
            id=new_id(),
            kind=kind,
            project_id=project_id,
            name=name,
            description=description,
            url_path=url_path,
        )
        .on_conflict_do_update(
            constraint="uq_object_refs_kind_project_name",
            set_={"description": description, "url_path": url_path, "updated_at": func.now()},
        )
    )
    await session.execute(statement)


async def remove_object_ref(
    session: AsyncSession, *, kind: str, project_id: uuid.UUID | None, name: str
) -> None:
    await session.execute(
        delete(ObjectRef).where(
            ObjectRef.kind == kind,
            ObjectRef.project_id == project_id,
            ObjectRef.name == name,
        )
    )
