"""Demo seed (`make seed`) — per-resource idempotent (Phase 1 plan §10): each ensure
step checks its own resource, so a Phase-0-seeded database gains the Phase-1 objects
on the next run instead of being skipped by an early return.

Users mirror the dev Keycloak realm: the realm export pins user ids, and Keycloak's
`sub` claim IS the user id, so first login attaches to these rows instead of creating
duplicates. Uses the same uuid helper as the app (ADR-0005).
"""

import asyncio
import contextlib
import datetime
import logging
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.config import Settings, get_settings
from osaip_api.db import make_engine, make_sessionmaker
from osaip_api.models import (
    Dataset,
    DatasetVersion,
    Notification,
    Project,
    ProjectMember,
    User,
)
from osaip_api.object_refs import upsert_object_ref
from osaip_engine import duck
from osaip_engine.storage import Storage, StorageConfig
from osaip_shared.ids import new_id
from osaip_shared.storage_layout import dataset_version_location

log = logging.getLogger("osaip.seed")

# Must match infra/compose/keycloak/realm-osaip.json user ids (= OIDC sub claims).
SEED_USERS = [
    ("10000000-0000-4000-8000-000000000001", "admin@osaip.dev", "Ada Admin", True),
    ("10000000-0000-4000-8000-000000000002", "editor@osaip.dev", "Evi Editor", False),
    ("10000000-0000-4000-8000-000000000003", "viewer@osaip.dev", "Vik Viewer", False),
]

DEMO_KEY = "demo"
DATASET_NAME = "sales_orders"
SEED_CSV = Path(__file__).parent / "seed_data" / "sales_orders.csv"


def _storage(settings: Settings) -> Storage:
    return Storage(
        StorageConfig(
            endpoint=settings.s3_endpoint,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
            use_ssl=settings.s3_use_ssl,
        )
    )


async def _ensure_user(
    session: AsyncSession, sub: str, email: str, name: str, site_admin: bool
) -> User:
    user = (await session.execute(select(User).where(User.oidc_sub == sub))).scalar_one_or_none()
    if user is None:
        # A user with this email may already exist from a real login (different sub,
        # e.g. a non-realm IdP in tests) — emails are unique, so reuse that row.
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(oidc_sub=sub, email=email, display_name=name, is_site_admin=site_admin)
        session.add(user)
        await session.flush()
        log.info("created user %s", email)
    return user


async def _ensure_project(session: AsyncSession, admin: User) -> Project:
    project = (
        await session.execute(select(Project).where(Project.key == DEMO_KEY))
    ).scalar_one_or_none()
    if project is None:
        project = Project(
            key=DEMO_KEY,
            name="Demo",
            description="Seeded demo project with sample objects.",
            storage_prefix=f"projects/{DEMO_KEY}",
            created_by=admin.id,
        )
        session.add(project)
        await session.flush()
        await write_audit(
            session,
            actor_id=admin.id,
            project_id=project.id,
            action="project.created",
            object_kind="project",
            object_id=DEMO_KEY,
            details={"name": "Demo", "seed": True},
        )
        log.info("created demo project")
    await upsert_object_ref(
        session,
        kind="project",
        project_id=project.id,
        name="Demo",
        description=f"{DEMO_KEY} Seeded demo project",
        url_path=f"/p/{DEMO_KEY}",
    )
    return project


async def _ensure_members(session: AsyncSession, project: Project, users: dict[str, User]) -> None:
    for email, role in [
        ("admin@osaip.dev", "admin"),
        ("editor@osaip.dev", "editor"),
        ("viewer@osaip.dev", "viewer"),
    ]:
        existing = (
            await session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == users[email].id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(ProjectMember(project_id=project.id, user_id=users[email].id, role=role))


async def _ensure_welcome(session: AsyncSession, admin: User) -> None:
    existing = (
        await session.execute(
            select(Notification).where(
                Notification.user_id == admin.id, Notification.kind == "welcome"
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Notification(
                user_id=admin.id,
                kind="welcome",
                severity="info",
                title="Welcome to OSAIP",
                body="The demo project is ready. Press ⌘K and try searching for sales_orders.",
            )
        )


async def _ensure_sales_dataset(
    session: AsyncSession, settings: Settings, project: Project, admin: User
) -> None:
    """The REAL sales_orders dataset: bundled CSV → typed parquet v1 + profile.
    Replaces the fake Phase-0 object_ref via upsert."""
    existing = (
        await session.execute(
            select(Dataset).where(Dataset.project_id == project.id, Dataset.name == DATASET_NAME)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    duck.install_extensions()  # host runs need httpfs on first use (ADR-0006 §3)
    storage = _storage(settings)
    storage.ensure_bucket()
    dest_key = dataset_version_location(DEMO_KEY, DATASET_NAME, 1)
    # Blocking engine calls are fine here: seed is a CLI, not a server event loop.
    columns, row_count = duck.convert_upload_to_parquet(
        str(SEED_CSV), SEED_CSV.name, storage.config, dest_key
    )
    location = f"s3://{storage.config.bucket}/{dest_key}"
    profile = duck.profile_parquet(storage.config, location)

    dataset = Dataset(
        id=new_id(),
        project_id=project.id,
        name=DATASET_NAME,
        kind="file",
        description="Sample sales orders (seeded demo data).",
        classification="none",
        legal_basis="Demo/sample data — contains no personal data",
        purpose_codes=["demo"],
        params={"format": "csv", "seed": True},
        current_version=1,
        created_by=admin.id,
    )
    session.add(dataset)
    await session.flush()
    session.add(
        DatasetVersion(
            id=new_id(),
            dataset_id=dataset.id,
            version=1,
            location=location,
            format="parquet",
            schema_json={
                "columns": [
                    {
                        "name": col.name,
                        "type": col.type,
                        "nullable": col.nullable,
                        "classification": "none",
                    }
                    for col in columns
                ]
            },
            row_count=row_count,
            row_count_kind="exact",
            profile_json=profile,
        )
    )
    await upsert_object_ref(
        session,
        kind="dataset",
        project_id=project.id,
        name=DATASET_NAME,
        description="Sample sales orders (seeded demo data).",
        url_path=f"/p/{DEMO_KEY}/datasets/{DATASET_NAME}",
    )
    await write_audit(
        session,
        actor_id=admin.id,
        project_id=project.id,
        action="dataset.created",
        object_kind="dataset",
        object_id=DATASET_NAME,
        details={"kind": "file", "seed": True},
    )
    log.info("created %s dataset (%s rows)", DATASET_NAME, row_count)


async def _ensure_demo_src(settings: Settings) -> None:
    """A second Postgres database (`demo_src`) with a `sales` table — the AC-2
    'register a Postgres table' path. CREATE DATABASE runs on a dedicated asyncpg
    connection (no transaction), duplicate-tolerant."""
    url = urlsplit(settings.database_url.replace("+asyncpg", ""))
    base_dsn = dict(
        host=url.hostname,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
    )
    conn = await asyncpg.connect(database=url.path.lstrip("/"), **base_dsn)
    try:
        with contextlib.suppress(asyncpg.DuplicateDatabaseError):
            await conn.execute("CREATE DATABASE demo_src")
    finally:
        await conn.close()

    demo = await asyncpg.connect(database="demo_src", **base_dsn)
    try:
        await demo.execute(
            """
            CREATE TABLE IF NOT EXISTS sales (
                sale_id bigint PRIMARY KEY,
                sale_date date NOT NULL,
                region text NOT NULL,
                amount numeric(10, 2) NOT NULL
            )
            """
        )
        count = await demo.fetchval("SELECT count(*) FROM sales")
        if count == 0:
            await demo.executemany(
                "INSERT INTO sales (sale_id, sale_date, region, amount) VALUES ($1, $2, $3, $4)",
                [
                    (
                        i,
                        datetime.date(2025, (i % 12) + 1, (i % 27) + 1),
                        ["NL", "BE", "DE"][i % 3],
                        round(50 + (i * 13.7) % 400, 2),
                    )
                    for i in range(1, 41)
                ],
            )
            log.info("filled demo_src.sales with 40 rows")
    finally:
        await demo.close()


async def _ensure_enriched_recipe(
    session: AsyncSession, settings: Settings, project: Project, admin: User
) -> None:
    """A prebuilt prepare recipe over sales_orders so the Flow renders a live (fresh)
    node on first boot (Phase 2 seed v2.1). Adds a `margin` formula column and builds
    v1 directly (seed is a CLI, not the async request loop)."""
    from osaip_api.models import Recipe, RecipeInput, RecipeOutput
    from osaip_api.object_refs import upsert_object_ref
    from osaip_engine import recipes as engine_recipes
    from osaip_engine.recipes import InputSource
    from osaip_shared.recipes import config_hash

    existing = (
        await session.execute(
            select(Recipe).where(Recipe.project_id == project.id, Recipe.name == "sales_enriched")
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    source = (
        await session.execute(
            select(Dataset).where(Dataset.project_id == project.id, Dataset.name == DATASET_NAME)
        )
    ).scalar_one()
    source_version = (
        await session.execute(
            select(DatasetVersion).where(
                DatasetVersion.dataset_id == source.id,
                DatasetVersion.version == source.current_version,
            )
        )
    ).scalar_one()

    config = {
        "kind": "prepare",
        "steps": [
            {"op": "formula", "column": "margin", "expression": 'col("revenue") * 0.3'},
        ],
    }
    recipe = Recipe(
        id=new_id(),
        project_id=project.id,
        name="sales_enriched",
        kind="prepare",
        config=config,
        config_hash=config_hash(config),
        purpose_codes=["demo"],
        created_by=admin.id,
    )
    output = Dataset(
        id=new_id(),
        project_id=project.id,
        name="sales_enriched",
        kind="file",
        description="Sales orders with a derived margin column (seeded recipe output).",
        legal_basis=source.legal_basis,
        purpose_codes=source.purpose_codes,
        params={"produced_by_recipe": True},
        current_version=0,
        created_by=admin.id,
    )
    session.add_all([recipe, output])
    await session.flush()
    session.add(RecipeInput(recipe_id=recipe.id, dataset_id=source.id, ordinal=0))
    session.add(RecipeOutput(recipe_id=recipe.id, dataset_id=output.id, ordinal=0))

    # Build v1 directly (blocking engine calls are fine in the seed CLI).
    storage = _storage(settings)
    dest_key = dataset_version_location(DEMO_KEY, "sales_enriched", 1)
    con = engine_recipes.open_connection(storage.config)
    try:
        table = engine_recipes.compile_recipe(
            con, "prepare", config, [InputSource(0, source_version.location)]
        )
        con.to_parquet(table, f"s3://{storage.config.bucket}/{dest_key}")
    finally:
        con.disconnect()
    location = f"s3://{storage.config.bucket}/{dest_key}"
    columns, row_count = duck.validate_parquet(storage.config, location)
    profile = duck.profile_parquet(storage.config, location)
    output.current_version = 1
    session.add(
        DatasetVersion(
            id=new_id(),
            dataset_id=output.id,
            version=1,
            location=location,
            format="parquet",
            schema_json={
                "columns": [
                    {
                        "name": c.name,
                        "type": c.type,
                        "nullable": c.nullable,
                        "classification": "none",
                    }
                    for c in columns
                ]
            },
            row_count=row_count,
            row_count_kind="exact",
            profile_json=profile,
            recipe_config_hash=recipe.config_hash,
            input_versions={str(source.id): source.current_version},
        )
    )
    await upsert_object_ref(
        session,
        kind="recipe",
        project_id=project.id,
        name="sales_enriched",
        description="Prepare: add margin",
        url_path=f"/p/{DEMO_KEY}?sel=recipe:{recipe.id}",
    )
    await upsert_object_ref(
        session,
        kind="dataset",
        project_id=project.id,
        name="sales_enriched",
        description="Sales orders with margin (seeded).",
        url_path=f"/p/{DEMO_KEY}/datasets/sales_enriched",
    )
    log.info("created sales_enriched recipe + built v1 (%s rows)", row_count)


async def seed(session: AsyncSession, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    users = {
        email: await _ensure_user(session, sub, email, name, site_admin)
        for sub, email, name, site_admin in SEED_USERS
    }
    admin = users["admin@osaip.dev"]
    project = await _ensure_project(session, admin)
    await _ensure_members(session, project, users)
    await _ensure_welcome(session, admin)
    await _ensure_sales_dataset(session, settings, project, admin)
    await _ensure_enriched_recipe(session, settings, project, admin)
    await _ensure_demo_src(settings)
    log.info("seed complete (idempotent)")


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)
    async with maker() as session:
        await seed(session, settings)
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
