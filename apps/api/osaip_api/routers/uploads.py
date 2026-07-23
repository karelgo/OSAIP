"""Preview-first upload path (plan §3, §6.3(3) LOCKED):

POST /projects/{key}/uploads stores the raw file under the project's transient
uploads prefix, infers schema + a ~50-row preview with DuckDB, and returns
{upload_id, columns, params, preview}. NOTHING is built yet — the user confirms via
POST /projects/{key}/datasets {source: {kind: "upload", upload_id}} (next slice).
The worker prunes raw uploads older than 24h.
"""

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from osaip_api.audit import write_audit
from osaip_api.auth.deps import CurrentUser
from osaip_api.db import get_session
from osaip_api.permissions import load_project_context
from osaip_api.problem import Problem
from osaip_api.schemas import UploadOut
from osaip_engine import duck
from osaip_engine.aio import run_engine
from osaip_engine.errors import EngineError, InvalidInput
from osaip_engine.storage import Storage
from osaip_shared.ids import new_id
from osaip_shared.storage_layout import upload_prefix

router = APIRouter(prefix="/projects/{key}/uploads", tags=["uploads"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


DbSession = Annotated[AsyncSession, Depends(get_session)]

ALLOWED_EXTENSIONS = (".csv", ".parquet", ".xlsx")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(raw: str) -> str:
    name = Path(raw).name  # strip any path components
    name = _SAFE_NAME_RE.sub("_", name).strip("._")
    if not name or not name.lower().endswith(ALLOWED_EXTENSIONS):
        raise Problem(
            422,
            title="Unsupported file type",
            detail="Only .csv, .parquet, and .xlsx files can be uploaded.",
            hint="Convert the file to CSV, Parquet, or XLSX and try again.",
            slug="unsupported-file-type",
        )
    return name


@router.post("", status_code=201, response_model=UploadOut)
async def create_upload(
    key: str, file: UploadFile, request: Request, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    ctx = await load_project_context(session, user, key, min_role="editor")
    settings = request.app.state.settings
    storage: Storage = request.app.state.storage
    filename = _safe_filename(file.filename or "")

    # Spooled size check (xlsx gets a tighter cap — zip container, plan §6).
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if filename.endswith(".xlsx") and size > settings.upload_max_bytes_xlsx:
        raise Problem(
            413,
            title="Upload too large",
            detail=(
                f"XLSX uploads are capped at {settings.upload_max_bytes_xlsx // (1024 * 1024)} MB "
                "(spreadsheets expand heavily in memory)."
            ),
            hint="Export the sheet as CSV, or split it.",
            slug="upload-too-large",
        )
    if size == 0:
        raise Problem(
            422,
            title="Empty file",
            detail="The uploaded file contains no data.",
            hint="Check the file and try again.",
            slug="validation",
        )

    upload_id = str(new_id())
    prefix = upload_prefix(ctx.project.key, upload_id)

    with tempfile.TemporaryDirectory(prefix="osaip-upload-") as tmp_dir:
        local_path = str(Path(tmp_dir) / filename)

        def _persist_and_infer() -> duck.InferResult:
            storage.ensure_bucket()
            with open(local_path, "wb") as local_file:
                shutil.copyfileobj(file.file, local_file)
            with open(local_path, "rb") as raw:
                storage.put_fileobj(raw, f"{prefix}/{filename}")
            return duck.infer_file(local_path, filename)

        try:
            inferred = await run_engine(_persist_and_infer)
        except InvalidInput as exc:
            raise Problem(
                422,
                title="File could not be parsed",
                detail=exc.public_message,
                hint="Check the file's contents and format, then upload again.",
                slug="validation",
            ) from exc
        except EngineError as exc:
            raise Problem(
                502,
                title="Upload processing failed",
                detail=exc.public_message,
                hint="Try again; if it persists, check that object storage is healthy.",
                slug="engine-error",
            ) from exc

    columns = [
        {"name": col.name, "type": col.type, "nullable": col.nullable, "classification": "none"}
        for col in inferred.columns
    ]
    meta = {
        "upload_id": upload_id,
        "filename": filename,
        "format": inferred.params.get("format", "csv"),
        "columns": columns,
        "params": inferred.params,
    }
    await run_engine(lambda: storage.put_bytes(json.dumps(meta).encode(), f"{prefix}/meta.json"))

    await write_audit(
        session,
        actor_id=user.id,
        project_id=ctx.project.id,
        action="upload.created",
        object_kind="upload",
        object_id=upload_id,
        details={"filename": filename, "size_bytes": size},
        ip=_client_ip(request),
    )
    await session.commit()

    return {**meta, "preview": inferred.preview}
