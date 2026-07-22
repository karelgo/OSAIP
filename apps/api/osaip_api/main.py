"""ASGI entrypoint: `uvicorn osaip_api.main:app`."""

from osaip_api.app import create_app

app = create_app()
