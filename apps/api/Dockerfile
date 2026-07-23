# Dev-oriented image; production hardening (non-root, multi-stage slim, signing) is a
# later-phase deliverable (ADR-0005: cosign activates with first published image).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /repo
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

# Workspace metadata first for layer caching
COPY pyproject.toml uv.lock .python-version ./
COPY packages packages
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
RUN uv sync --frozen --all-packages --no-install-workspace

COPY apps/api apps/api
COPY apps/worker apps/worker
RUN uv sync --frozen --all-packages

# Bake DuckDB extensions into a HOME-independent directory (ADR-0006 §3). Runtime
# connections set autoinstall/autoload=false and LOAD explicitly — a missing
# extension fails loudly instead of silently downloading.
ENV OSAIP_DUCKDB_EXTENSION_DIR=/opt/duckdb-extensions
RUN uv run --no-sync python -c "from osaip_engine.duck import install_extensions; install_extensions()"

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "osaip_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
