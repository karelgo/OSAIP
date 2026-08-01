"""ASGI entrypoint: `uvicorn osaip_mesh.main:app`."""

from osaip_mesh.app import create_mesh_app

app = create_mesh_app()
