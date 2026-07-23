"""Engine tests: inference, conversion, sampling, profiling, safety helpers, and the
interrupt watchdog — against a real SeaweedFS testcontainer (root conftest)."""

from pathlib import Path

import duckdb
import pytest

from osaip_engine import duck
from osaip_engine.errors import Interrupted, InvalidInput
from osaip_engine.safety import qualified_ident, sql_ident, sql_literal
from osaip_engine.storage import Storage, StorageConfig

CSV_CONTENT = """order_id,amount,order_date,region,active
1,12.50,2024-01-15,NL,true
2,99.95,2024-01-16,BE,false
3,7.25,2024-01-17,NL,true
4,,2024-01-18,DE,true
"""


@pytest.fixture
def csv_path(tmp_path: Path) -> str:
    path = tmp_path / "orders.csv"
    path.write_text(CSV_CONTENT)
    return str(path)


def test_infer_csv_types(duck_extensions: None, csv_path: str) -> None:
    result = duck.infer_file(csv_path, "orders.csv")
    types = {col.name: col.type for col in result.columns}
    assert types["order_id"] == "BIGINT"
    assert types["amount"] in {"DOUBLE", "DECIMAL(4,2)"}
    assert types["order_date"] == "DATE"
    assert types["region"] == "VARCHAR"
    assert types["active"] == "BOOLEAN"
    assert result.params["format"] == "csv"
    # preview rows are JSON-safe (dates as ISO strings)
    assert result.preview[0]["order_date"] == "2024-01-15"
    assert result.preview[3]["amount"] is None


def test_infer_rejects_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("hello")
    with pytest.raises(InvalidInput):
        duck.infer_file(str(path), "data.txt")


def test_convert_sample_profile_roundtrip(
    duck_extensions: None, seaweed_config: StorageConfig, csv_path: str
) -> None:
    dest_key = "projects/enginetest/datasets/orders/v1/part-0.parquet"
    columns, row_count = duck.convert_upload_to_parquet(
        csv_path, "orders.csv", seaweed_config, dest_key
    )
    assert row_count == 4
    assert {c.name for c in columns} == {"order_id", "amount", "order_date", "region", "active"}

    s3_uri = f"s3://{seaweed_config.bucket}/{dest_key}"
    sample_cols, rows = duck.sample_parquet(seaweed_config, s3_uri, limit=2)
    assert len(rows) == 2
    assert rows[0]["order_id"] == 1

    profile = duck.profile_parquet(seaweed_config, s3_uri)
    assert profile["row_count"] == 4
    by_name = {col["name"]: col for col in profile["columns"]}
    assert by_name["amount"]["null_count"] == 1
    assert float(by_name["amount"]["min"]) == 7.25
    assert float(by_name["amount"]["max"]) == 99.95
    region_top = {entry["value"]: entry["count"] for entry in by_name["region"]["top_values"]}
    assert region_top["NL"] == 2
    assert by_name["order_date"]["min"] == "2024-01-15"


def test_validate_parquet_rejects_corrupt(
    duck_extensions: None, seaweed_config: StorageConfig
) -> None:
    storage = Storage(seaweed_config)
    storage.put_bytes(b"definitely not parquet", "projects/enginetest/corrupt.parquet")
    with pytest.raises(InvalidInput):
        duck.validate_parquet(
            seaweed_config, f"s3://{seaweed_config.bucket}/projects/enginetest/corrupt.parquet"
        )


def test_infer_xlsx(duck_extensions: None, tmp_path: Path) -> None:
    xlsx_path = str(tmp_path / "orders.xlsx")
    conn = duckdb.connect()
    conn.load_extension("excel")
    conn.execute(
        "COPY (SELECT * FROM (VALUES (1, 'NL', DATE '2024-01-15'), (2, 'BE', DATE '2024-01-16'))"
        " t(order_id, region, order_date)) "
        f"TO '{xlsx_path}' WITH (FORMAT xlsx, HEADER true)"
    )
    conn.close()
    result = duck.infer_file(xlsx_path, "orders.xlsx")
    names = [col.name for col in result.columns]
    assert names == ["order_id", "region", "order_date"]
    assert len(result.preview) == 2
    assert result.params["format"] == "xlsx"


def test_interrupt_watchdog(duck_extensions: None) -> None:
    conn = duck._connect()
    try:
        with pytest.raises(Interrupted):
            duck._with_timeout(
                conn,
                lambda: conn.execute(
                    "SELECT count(*) FROM range(100000000) a, range(10000) b"
                ).fetchone(),
                timeout_s=0.1,
            )
    finally:
        conn.close()


def test_sql_escaping_helpers() -> None:
    assert sql_literal("it's") == "'it''s'"
    assert sql_ident('weird"name') == '"weird""name"'
    assert qualified_ident("public.orders") == '"public"."orders"'
    assert qualified_ident("orders") == '"orders"'
    with pytest.raises(ValueError, match="schema.table"):
        qualified_ident("a.b.c")
    # an injection attempt stays inert inside the literal
    hostile = sql_literal("x', SECRET 'stolen")
    assert hostile == "'x'', SECRET ''stolen'"
