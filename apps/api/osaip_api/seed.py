"""Demo seed (`make seed`) — idempotent; drives the Phase 0 acceptance tests.

Users mirror the dev Keycloak realm: the realm export pins user ids, and Keycloak's
`sub` claim IS the user id, so first login attaches to these rows instead of creating
duplicates. Uses the same uuid helper as the app (ADR-0005).
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.config import get_settings
from osaip_api.db import make_engine, make_sessionmaker
from osaip_api.models import Notification, ObjectRef, Project, ProjectMember, User

log = logging.getLogger("osaip.seed")

# Must match infra/compose/keycloak/realm-osaip.json user ids (= OIDC sub claims).
SEED_USERS = [
    ("10000000-0000-4000-8000-000000000001", "admin@osaip.dev", "Ada Admin", True),
    ("10000000-0000-4000-8000-000000000002", "editor@osaip.dev", "Evi Editor", False),
    ("10000000-0000-4000-8000-000000000003", "viewer@osaip.dev", "Vik Viewer", False),
]

DEMO_KEY = "demo"


async def _ensure_user(
    session: AsyncSession, sub: str, email: str, name: str, site_admin: bool
) -> User:
    user = (await session.execute(select(User).where(User.oidc_sub == sub))).scalar_one_or_none()
    if user is None:
        user = User(oidc_sub=sub, email=email, display_name=name, is_site_admin=site_admin)
        session.add(user)
        await session.flush()
        log.info("created user %s", email)
    return user


async def seed(session: AsyncSession) -> None:
    users = {
        email: await _ensure_user(session, sub, email, name, site_admin)
        for sub, email, name, site_admin in SEED_USERS
    }
    admin = users["admin@osaip.dev"]

    existing = (
        await session.execute(select(Project).where(Project.key == DEMO_KEY))
    ).scalar_one_or_none()
    if existing is not None:
        log.info("demo project already seeded; nothing to do")
        return

    project = Project(
        key=DEMO_KEY,
        name="Demo",
        description="Seeded demo project with sample objects.",
        storage_prefix=f"projects/{DEMO_KEY}",
        created_by=admin.id,
    )
    session.add(project)
    await session.flush()

    for email, role in [
        ("admin@osaip.dev", "admin"),
        ("editor@osaip.dev", "editor"),
        ("viewer@osaip.dev", "viewer"),
    ]:
        session.add(ProjectMember(project_id=project.id, user_id=users[email].id, role=role))

    session.add_all(
        [
            ObjectRef(
                kind="project",
                project_id=project.id,
                name="Demo",
                description=f"{DEMO_KEY} Seeded demo project",
                url_path=f"/p/{DEMO_KEY}",
            ),
            # The seeded dataset ref makes the ⌘K acceptance test real (spec §7 AC-6);
            # the actual dataset object arrives in Phase 1.
            ObjectRef(
                kind="dataset",
                project_id=project.id,
                name="sales_orders",
                description="Sample sales orders (seeded reference; data lands in phase 1)",
                url_path=f"/p/{DEMO_KEY}/datasets/sales_orders",
            ),
        ]
    )

    session.add(
        Notification(
            user_id=admin.id,
            kind="welcome",
            severity="info",
            title="Welcome to OSAIP",
            body="The demo project is ready. Press ⌘K and try searching for sales_orders.",
        )
    )

    await write_audit(
        session,
        actor_id=admin.id,
        project_id=project.id,
        action="project.created",
        object_kind="project",
        object_id=DEMO_KEY,
        details={"name": "Demo", "seed": True},
    )
    log.info("seeded demo project with 3 members, 2 object refs, 1 notification")


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = make_engine(get_settings().database_url)
    maker = make_sessionmaker(engine)
    async with maker() as session:
        await seed(session)
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
