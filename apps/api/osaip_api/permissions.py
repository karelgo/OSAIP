"""THE permissions module (spec §3.2): every authorization decision goes through here.

Project roles: viewer < editor < admin. Site admins hold virtual admin on every
project. Non-members get 404 (existence is not leaked); members below the needed
role get 403. Capability flags are computed server-side so the UI never guesses
(§6.6).
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.models import Project, ProjectMember, User
from osaip_api.problem import Problem

ROLE_ORDER: dict[str, int] = {"viewer": 1, "editor": 2, "admin": 3}


def has_role(actual: str | None, needed: str) -> bool:
    if actual is None:
        return False
    return ROLE_ORDER[actual] >= ROLE_ORDER[needed]


@dataclass
class ProjectContext:
    project: Project
    role: str  # effective role (site admins: "admin")

    @property
    def capabilities(self) -> dict[str, bool]:
        active = self.project.status == "active"
        return {
            "can_edit": active and has_role(self.role, "editor"),
            "can_manage_members": active and has_role(self.role, "admin"),
            "can_archive": active and has_role(self.role, "admin"),
            # Connections carry credentials — admin only (Phase 1 plan, RBAC matrix).
            "can_manage_connections": active and has_role(self.role, "admin"),
        }


async def membership_role(session: AsyncSession, user: User, project: Project) -> str | None:
    if user.is_site_admin:
        return "admin"
    row = (
        await session.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    return row


def _not_found(key: str) -> Problem:
    return Problem(
        404,
        title="Project not found",
        detail=f"No project {key!r} is visible to you.",
        hint="Check the project key, or ask a project admin to add you as a member.",
        slug="not-found",
    )


async def load_project_context(
    session: AsyncSession, user: User, key: str, *, min_role: str
) -> ProjectContext:
    project = (
        await session.execute(select(Project).where(Project.key == key))
    ).scalar_one_or_none()
    if project is None:
        raise _not_found(key)
    role = await membership_role(session, user, project)
    if role is None:
        raise _not_found(key)
    if not has_role(role, min_role):
        raise Problem(
            403,
            title="Insufficient role",
            detail=f"This action needs the {min_role} role; you have {role}.",
            hint="Ask a project admin to raise your role if you need this.",
            slug="forbidden",
        )
    return ProjectContext(project=project, role=role)


def require_site_admin(user: User) -> None:
    if not user.is_site_admin:
        raise Problem(
            403,
            title="Site admin only",
            detail="This action is restricted to site administrators.",
            hint="Ask a site administrator to perform this action.",
            slug="forbidden",
        )


def project_payload(ctx: ProjectContext) -> dict[str, Any]:
    project = ctx.project
    return {
        "key": project.key,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "role": ctx.role,
        "capabilities": ctx.capabilities,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }
