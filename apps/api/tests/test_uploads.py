"""Upload endpoint: preview-first inference, validation, size caps (413 both via
Content-Length and mid-stream), RBAC, audit."""

from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LoginAs = Callable[..., Awaitable[httpx.AsyncClient]]

CSV_CONTENT = b"order_id,amount,order_date,region\n1,12.50,2024-01-15,NL\n2,99.95,2024-01-16,BE\n"


async def _project(client: httpx.AsyncClient, key: str) -> None:
    assert (
        await client.post("/api/v1/projects", json={"key": key, "name": key})
    ).status_code == 201


async def test_upload_csv_infers_typed_schema(
    duck_extensions: None, login_as: LoginAs, db_session: AsyncSession
) -> None:
    admin = await login_as("up-admin", "up-admin@osaip.dev")
    await _project(admin, "upl1")
    response = await admin.post(
        "/api/v1/projects/upl1/uploads",
        files={"file": ("orders.csv", CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    types = {col["name"]: col["type"] for col in body["columns"]}
    assert types["order_id"] == "BIGINT"
    assert types["order_date"] == "DATE"
    assert body["params"]["format"] == "csv"
    assert body["preview"][0]["region"] == "NL"
    assert body["upload_id"]

    audit = (
        await db_session.execute(
            text("SELECT count(*) FROM audit_log WHERE action='upload.created'")
        )
    ).scalar_one()
    assert audit >= 1


async def test_viewer_cannot_upload(login_as: LoginAs) -> None:
    admin = await login_as("up-admin2", "up-admin2@osaip.dev")
    await _project(admin, "upl2")
    members = [
        {"email": "up-admin2@osaip.dev", "role": "admin"},
        {"email": "up-viewer@osaip.dev", "role": "viewer"},
    ]
    viewer = await login_as("up-viewer", "up-viewer@osaip.dev")
    await admin.put("/api/v1/projects/upl2/members", json={"members": members})
    response = await viewer.post(
        "/api/v1/projects/upl2/uploads",
        files={"file": ("orders.csv", CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 403


async def test_bad_extension_rejected(login_as: LoginAs) -> None:
    admin = await login_as("up-admin3", "up-admin3@osaip.dev")
    await _project(admin, "upl3")
    response = await admin.post(
        "/api/v1/projects/upl3/uploads",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:osaip:problem:unsupported-file-type"


async def test_empty_file_rejected(login_as: LoginAs) -> None:
    admin = await login_as("up-admin4", "up-admin4@osaip.dev")
    await _project(admin, "upl4")
    response = await admin.post(
        "/api/v1/projects/upl4/uploads",
        files={"file": ("orders.csv", b"", "text/csv")},
    )
    assert response.status_code == 422


async def test_content_length_over_cap_is_413(login_as: LoginAs) -> None:
    admin = await login_as("up-admin5", "up-admin5@osaip.dev")
    await _project(admin, "upl5")
    # settings fixture caps uploads at 1 MiB
    big = b"a" * (1024 * 1024 + 100)
    response = await admin.post(
        "/api/v1/projects/upl5/uploads",
        files={"file": ("big.csv", big, "text/csv")},
    )
    assert response.status_code == 413
    assert response.json()["type"] == "urn:osaip:problem:upload-too-large"


async def test_chunked_body_over_cap_aborts_mid_stream(login_as: LoginAs) -> None:
    """No Content-Length (chunked): the byte-counting ASGI guard must cut off the
    stream before the multipart parser spools the whole body (plan §6)."""
    admin = await login_as("up-admin6", "up-admin6@osaip.dev")
    await _project(admin, "upl6")

    async def chunks() -> AsyncIterator[bytes]:
        # A well-formed multipart opening so the parser keeps consuming file bytes…
        yield (
            b"--deadbeef\r\n"
            b'Content-Disposition: form-data; name="file"; filename="big.csv"\r\n'
            b"Content-Type: text/csv\r\n\r\n"
        )
        for _ in range(300):  # …then ~2.4 MiB of content, never a closing boundary
            yield b"x" * 8192

    response = await admin.post(
        "/api/v1/projects/upl6/uploads",
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=deadbeef"},
    )
    assert response.status_code == 413


async def test_xlsx_over_its_own_cap_is_413(duck_extensions: None, login_as: LoginAs) -> None:
    import hashlib

    admin = await login_as("up-admin7", "up-admin7@osaip.dev")
    await _project(admin, "upl7")
    # Build an xlsx > the 64 KiB test cap (but < the 1 MiB absolute cap): poorly
    # compressible md5 strings.
    import tempfile
    from pathlib import Path

    import duckdb as ddb

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "big.xlsx"
        conn = ddb.connect()
        conn.load_extension("excel")
        conn.execute(
            f"COPY (SELECT i, md5(i::VARCHAR) AS a, md5((i*7)::VARCHAR) AS b "
            f"FROM range(6000) t(i)) TO '{path}' WITH (FORMAT xlsx, HEADER true)"
        )
        conn.close()
        data = path.read_bytes()
    assert 64 * 1024 < len(data) < 1024 * 1024, f"fixture size drifted: {len(data)}"
    digest_before = hashlib.sha256(data).hexdigest()

    response = await admin.post(
        "/api/v1/projects/upl7/uploads",
        files={"file": ("big.xlsx", data, "application/vnd.ms-excel")},
    )
    assert response.status_code == 413
    assert "XLSX" in response.json()["detail"]
    assert hashlib.sha256(data).hexdigest() == digest_before


async def test_filename_is_sanitized(duck_extensions: None, login_as: LoginAs) -> None:
    admin = await login_as("up-admin8", "up-admin8@osaip.dev")
    await _project(admin, "upl8")
    response = await admin.post(
        "/api/v1/projects/upl8/uploads",
        files={"file": ("../../evil name!!.csv", CSV_CONTENT, "text/csv")},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "evil_name_.csv"
