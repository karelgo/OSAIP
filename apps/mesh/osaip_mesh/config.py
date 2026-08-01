"""Mesh settings. Reuses the api's OSAIP_* env so one compose anchor configures all
services; adds the mesh-only service token and engine knobs."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MeshSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAIP_", extra="ignore")

    database_url: str = "postgresql+asyncpg://osaip:osaip@localhost:5433/osaip"
    dev: bool = False
    secret_key: str = "b3NhaXAtZGV2LW9ubHktc2VjcmV0LWtleS0zMmJ5dGU="

    # Shared secret between api/worker and the mesh. The mesh is NEVER browser-reachable
    # (no compose port publish); this token is the second line of that rule.
    mesh_service_token: str = "dev-mesh-token-not-for-prod"
    # Where callers reach the mesh (compose-internal hostname).
    mesh_url: str = "http://mesh:8100"

    # Guardrails
    guardrail_nlp_model: str = "nl_core_news_sm"
    # Judge recursion: depth >= this many hops skips post-moderation (ADR-0008 §5).
    guardrail_max_depth: int = 1

    docs_base_url: str = "https://github.com/osaip/osaip/blob/main/docs"


@lru_cache
def get_mesh_settings() -> MeshSettings:
    return MeshSettings()
