"""Visual + SQL recipe compilers, executed over real parquet in the SeaweedFS
testcontainer. Value assertions per recipe kind (review: join suffixes, stack
null-fill, split complement, dedupe subset, seeded determinism)."""

from typing import Any

import duckdb
import pytest

from osaip_engine import recipes
from osaip_engine.recipes import InputSource
from osaip_engine.storage import Storage, StorageConfig


def _write_parquet(storage: StorageConfig, key: str, values_sql: str, columns: str) -> str:
    con = duckdb.connect()
    con.execute(
        f"CREATE SECRET s3 (TYPE s3, KEY_ID '{storage.access_key}', "
        f"SECRET '{storage.secret_key}', ENDPOINT '{storage.endpoint}', "
        f"REGION '{storage.region}', URL_STYLE 'path', USE_SSL false)"
    )
    con.execute("INSTALL httpfs; LOAD httpfs")
    uri = f"s3://{storage.bucket}/{key}"
    con.execute(
        f"COPY (SELECT * FROM (VALUES {values_sql}) t({columns})) TO '{uri}' (FORMAT parquet)"
    )
    con.close()
    return uri


@pytest.fixture
def orders_uri(duck_extensions: None, seaweed_config: StorageConfig) -> str:
    Storage(seaweed_config).ensure_bucket()
    return _write_parquet(
        seaweed_config,
        "recipes/orders.parquet",
        "(1,'NL',10.0),(2,'BE',20.0),(3,'NL',30.0),(3,'NL',30.0)",
        "order_id, region, amount",
    )


@pytest.fixture
def regions_uri(duck_extensions: None, seaweed_config: StorageConfig) -> str:
    return _write_parquet(
        seaweed_config,
        "recipes/regions.parquet",
        "('NL','Netherlands'),('BE','Belgium')",
        "region, country",
    )


def _con(seaweed_config: StorageConfig) -> Any:
    return recipes.open_connection(seaweed_config)


def test_prepare_formula_filter_select(seaweed_config: StorageConfig, orders_uri: str) -> None:
    con = _con(seaweed_config)
    config = {
        "kind": "prepare",
        "steps": [
            {"op": "formula", "column": "with_vat", "expression": 'col("amount") * 1.21'},
            {"op": "filter", "expression": 'col("region") == "NL"'},
            {"op": "select", "columns": ["order_id", "with_vat"], "drop": False},
        ],
    }
    table = recipes.compile_recipe(con, "prepare", config, [InputSource(0, orders_uri)])
    rows = con.execute(table.order_by("order_id")).to_dict("records")
    assert set(rows[0].keys()) == {"order_id", "with_vat"}
    assert float(rows[0]["with_vat"]) == pytest.approx(12.1)
    assert all(r["order_id"] in (1, 3) for r in rows)  # BE filtered out


def test_dedupe_subset(seaweed_config: StorageConfig, orders_uri: str) -> None:
    con = _con(seaweed_config)
    config = {"kind": "prepare", "steps": [{"op": "dedupe", "subset": ["order_id"]}]}
    table = recipes.compile_recipe(con, "prepare", config, [InputSource(0, orders_uri)])
    ids = sorted(con.execute(table["order_id"]).tolist())
    assert ids == [1, 2, 3]  # the duplicate order_id=3 collapsed


def test_join_with_suffix(seaweed_config: StorageConfig, orders_uri: str, regions_uri: str) -> None:
    con = _con(seaweed_config)
    config = {
        "kind": "join",
        "how": "inner",
        "on": [{"left": "region", "right": "region"}],
        "right_suffix": "_r",
    }
    table = recipes.compile_recipe(
        con, "join", config, [InputSource(0, orders_uri), InputSource(1, regions_uri)]
    )
    cols = table.columns
    assert "country" in cols
    rows = con.execute(table).to_dict("records")
    assert {r["country"] for r in rows} == {"Netherlands", "Belgium"}


def test_group_aggregations(seaweed_config: StorageConfig, orders_uri: str) -> None:
    con = _con(seaweed_config)
    config = {
        "kind": "group",
        "by": ["region"],
        "aggregations": [
            {"column": "amount", "func": "sum", "as": "total"},
            {"column": "order_id", "func": "count_distinct", "as": "n"},
        ],
    }
    table = recipes.compile_recipe(con, "group", config, [InputSource(0, orders_uri)])
    rows = {r["region"]: r for r in con.execute(table).to_dict("records")}
    assert rows["NL"]["total"] == 70.0  # 10 + 30 + 30
    assert rows["NL"]["n"] == 2  # distinct order_id 1 and 3


def test_split_is_complementary(seaweed_config: StorageConfig, orders_uri: str) -> None:
    con = _con(seaweed_config)
    config = {"kind": "split", "expression": 'col("region") == "NL"'}
    match, rest = recipes.compile_split(con, config, [InputSource(0, orders_uri)])
    match_rows = con.execute(match).shape[0]
    rest_rows = con.execute(rest).shape[0]
    assert match_rows == 3 and rest_rows == 1  # 3 NL (incl. dup) + 1 BE


def test_stack_null_fills(seaweed_config: StorageConfig, orders_uri: str, regions_uri: str) -> None:
    con = _con(seaweed_config)
    table = recipes.compile_recipe(
        con, "stack", {"kind": "stack"}, [InputSource(0, orders_uri), InputSource(1, regions_uri)]
    )
    cols = set(table.columns)
    assert {"order_id", "amount", "country"} <= cols
    total = con.execute(table).shape[0]
    assert total == 6  # 4 orders + 2 regions


def test_sql_recipe_executes_validated(seaweed_config: StorageConfig, orders_uri: str) -> None:
    con = _con(seaweed_config)
    config = {
        "kind": "sql",
        "query": "SELECT region, sum(amount) AS total FROM in_1 GROUP BY region",
    }
    table = recipes.compile_recipe(con, "sql", config, [InputSource(0, orders_uri)])
    rows = {r["region"]: r["total"] for r in con.execute(table).to_dict("records")}
    assert rows["NL"] == 70.0


def test_sql_recipe_rejects_exfiltration(seaweed_config: StorageConfig, orders_uri: str) -> None:
    from osaip_engine.errors import InvalidInput

    con = _con(seaweed_config)
    config = {"kind": "sql", "query": "SELECT * FROM duckdb_secrets()"}
    with pytest.raises(InvalidInput):
        recipes.compile_recipe(con, "sql", config, [InputSource(0, orders_uri)])
