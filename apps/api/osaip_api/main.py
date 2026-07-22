"""ASGI entrypoint. Placeholder app — the real app factory lands with the API base slice."""

from fastapi import FastAPI

app = FastAPI(title="OSAIP API")


@app.get("/api/v1/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
