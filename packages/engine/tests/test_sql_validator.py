"""SQL validator — the exfiltration vectors the review verified must all be rejected,
and legitimate SELECT/join/CTE queries must pass."""

import pytest

from osaip_engine.errors import InvalidInput
from osaip_engine.sql_validator import validate_sql

INPUTS = {"in_1", "in_2"}


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM in_1",
        "SELECT a, sum(b) AS total FROM in_1 GROUP BY a",
        "SELECT * FROM in_1 JOIN in_2 ON in_1.id = in_2.id",
        "WITH x AS (SELECT * FROM in_1) SELECT * FROM x",
        "SELECT upper(name), round(amount, 2) FROM in_1 WHERE amount > 0",
        "SELECT * FROM main.in_1",
    ],
)
def test_accepts_legitimate_selects(query: str) -> None:
    validate_sql(query, INPUTS)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM duckdb_secrets()",
        "SELECT * FROM read_parquet('s3://other-project/data.parquet')",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM glob('*')",
        "SELECT getenv('HOME')",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM system.information_schema.tables",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM 'sales'",  # quoted-string table = file path
        "SELECT * FROM other_dataset",  # not an input
        "INSERT INTO in_1 VALUES (1)",
        "UPDATE in_1 SET a = 1",
        "CREATE TABLE x AS SELECT * FROM in_1",
        "COPY in_1 TO '/tmp/out.csv'",
        "ATTACH 'other.db'",
        "PRAGMA database_list",
        "SELECT * FROM in_1; DROP TABLE in_1",  # multi-statement
        "SELECT which_secret('s3://x', 's3')",
    ],
)
def test_rejects_exfiltration_and_writes(query: str) -> None:
    with pytest.raises(InvalidInput):
        validate_sql(query, INPUTS)
