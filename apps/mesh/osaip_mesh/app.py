"""Mesh application factory.

The mesh is an INTERNAL service: api/worker call it with a service token, and it is
never published to the browser (spec §5b makes it the single choke point for model
calls, so it must not be reachable around the api's authz).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request

from osaip_api.db import make_engine, make_sessionmaker
from osaip_api.problem import Problem, register_problem_handlers
from osaip_api.secrets import Vault
from osaip_mesh.config import MeshSettings, get_mesh_settings
from osaip_mesh.routers import complete, health


async def require_service_token(
    request: Request,
    x_osaip_mesh_token: Annotated[str | None, Header()] = None,
) -> None:
    # Read the token from THIS app's settings, not a process-global — an app built with
    # explicit settings must authenticate against them.
    settings: MeshSettings = request.app.state.settings
    # Constant-time compare; the token is a shared secret, not a password hash.
    import hmac

    if x_osaip_mesh_token is None or not hmac.compare_digest(
        x_osaip_mesh_token, settings.mesh_service_token
    ):
        raise Problem(
            401,
            title="Mesh authentication failed",
            detail="A valid mesh service token is required.",
            hint="Callers must send X-OSAIP-Mesh-Token; the browser never calls the mesh.",
            slug="unauthenticated",
        )


def create_mesh_app(settings: MeshSettings | None = None) -> FastAPI:
    settings = settings or get_mesh_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.vault = Vault(settings.secret_key)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="OSAIP Mesh",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.dev else None,
        openapi_url="/openapi.json" if settings.dev else None,
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.settings = settings
    register_problem_handlers(app)

    app.include_router(health.router)
    app.include_router(complete.router, dependencies=[Depends(require_service_token)])
    return app
