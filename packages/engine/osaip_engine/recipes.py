"""Visual + SQL recipe compilation to Ibis/DuckDB (spec §3.2 "Visual recipe JSON →
Ibis → engine"). Enters DuckDB exclusively through `duck._connect` + ibis
`from_connection` so the P1 hardening (extension dir, memory/thread caps, autoload
off) carries. Inputs are registered as views aliased by ordinal (`in_1`, `in_2`) —
DuckDB identifiers are case-insensitive, so dataset names 'Sales'/'sales' would
collide (ADR-0007 §4).
"""

from dataclasses import dataclass
from typing import Any

import ibis
from ibis.expr.types import Table

from osaip_engine import duck
from osaip_engine.errors import InvalidInput
from osaip_engine.expressions import compile_expression, compile_predicate
from osaip_engine.sql_validator import validate_sql
from osaip_engine.storage import StorageConfig


def input_alias(ordinal: int) -> str:
    return f"in_{ordinal + 1}"


@dataclass
class InputSource:
    """A resolved recipe input: a parquet URI (dataset version) bound to an alias."""

    ordinal: int
    s3_uri: str  # s3://bucket/.../part-0.parquet (or a glob for multi-part)


def _register_inputs(con: Any, sources: list[InputSource]) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for source in sources:
        alias = input_alias(source.ordinal)
        tables[alias] = con.read_parquet(source.s3_uri, table_name=alias)
    return tables


# ── Visual compilers (config dict → Ibis Table) ──────────────────────────────────


def _compile_prepare(table: Table, config: dict[str, Any]) -> Table:
    for step in config["steps"]:
        op = step["op"]
        if op == "rename":
            table = table.rename({new: old for old, new in step["mapping"].items()})
        elif op == "cast":
            table = table.cast(step["casts"])
        elif op == "filter":
            table = table.filter(compile_predicate(table, step["expression"]))
        elif op == "formula":
            table = table.mutate(**{step["column"]: compile_expression(table, step["expression"])})
        elif op == "fill_nulls":
            table = table.fill_null(step["values"])
        elif op == "dedupe":
            subset = step.get("subset") or table.columns
            table = table.distinct(on=subset, keep="first")
        elif op == "select":
            columns = step["columns"]
            missing = [c for c in columns if c not in table.columns]
            if missing:
                raise InvalidInput(f"Unknown column(s): {missing}.")
            if step.get("drop"):
                table = table.drop(*columns)
            else:
                table = table.select(*columns)
        else:  # pragma: no cover — pydantic restricts op
            raise InvalidInput(f"Unknown prepare step: {op}.")
    return table


def _compile_join(left: Table, right: Table, config: dict[str, Any]) -> Table:
    predicates = [left[k["left"]] == right[k["right"]] for k in config["on"]]
    return left.join(
        right, predicates, how=config["how"], rname="{name}" + config.get("right_suffix", "_right")
    )


def _compile_group(table: Table, config: dict[str, Any]) -> Table:
    aggs = {}
    for agg in config["aggregations"]:
        column = agg["column"]
        func = agg["func"]
        name = agg.get("as") or agg.get("as_") or f"{func}_{column}"
        col = table[column]
        if func == "count":
            aggs[name] = col.count()
        elif func == "count_distinct":
            aggs[name] = col.nunique()
        elif func == "mean":
            aggs[name] = col.mean()
        else:
            aggs[name] = getattr(col, func)()
    return table.group_by(config["by"]).aggregate(**aggs)


def _compile_stack(tables: list[Table]) -> Table:
    # union by name; a column missing from one input is filled with a NULL cast to
    # the type it carries elsewhere (set operations require identical schemas).
    all_columns: list[str] = []
    column_types: dict[str, Any] = {}
    for table in tables:
        schema = table.schema()
        for column in table.columns:
            if column not in all_columns:
                all_columns.append(column)
                column_types[column] = schema[column]
    aligned = []
    for table in tables:
        additions = {
            c: ibis.null().cast(column_types[c]) for c in all_columns if c not in table.columns
        }
        aligned.append(
            table.mutate(**additions).select(*all_columns)
            if additions
            else table.select(*all_columns)
        )
    result = aligned[0]
    for table in aligned[1:]:
        result = result.union(table)
    return result


def _compile_sample(table: Table, config: dict[str, Any]) -> Table:
    if config.get("method") == "random" and config.get("fraction") is not None:
        return table.sample(config["fraction"], method="row", seed=config.get("seed", 42))
    return table.head(config.get("n") or 1000)


# ── Public entry points ──────────────────────────────────────────────────────────


def compile_recipe(
    con: Any, kind: str, config: dict[str, Any], sources: list[InputSource]
) -> Table:
    """Compile a single-output recipe to an Ibis Table. `split` uses compile_split."""
    tables = _register_inputs(con, sources)
    ordered = [tables[input_alias(s.ordinal)] for s in sorted(sources, key=lambda s: s.ordinal)]
    if kind == "prepare":
        return _compile_prepare(ordered[0], config)
    if kind == "join":
        return _compile_join(ordered[0], ordered[1], config)
    if kind == "group":
        return _compile_group(ordered[0], config)
    if kind == "stack":
        return _compile_stack(ordered)
    if kind == "sample":
        return _compile_sample(ordered[0], config)
    if kind == "sql":
        validate_sql(config["query"], set(tables.keys()))
        return con.sql(config["query"])
    raise InvalidInput(f"{kind} is not a single-output recipe.")


def compile_split(
    con: Any, config: dict[str, Any], sources: list[InputSource]
) -> tuple[Table, Table]:
    """Split → (match, rest)."""
    tables = _register_inputs(con, sources)
    table = tables[input_alias(sources[0].ordinal)]
    predicate = compile_predicate(table, config["expression"])
    return table.filter(predicate), table.filter(~predicate)


def open_connection(storage: StorageConfig | None, *, memory_limit: str | None = None) -> Any:
    """An ibis DuckDB backend over a hardened duck connection (P1 config carries)."""
    raw = duck._connect(storage)
    if memory_limit:
        raw.execute(f"SET memory_limit='{memory_limit}'")
    return ibis.duckdb.from_connection(raw)
