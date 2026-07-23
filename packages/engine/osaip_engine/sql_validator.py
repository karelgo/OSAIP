"""Allowlist SQL validator for SQL recipes (ADR-0007 §4). A tables-only allowlist is
exploitable — `SELECT * FROM duckdb_secrets()` and `read_parquet('s3://…')` bypass it
and leak credentials — so this validates BOTH tables and functions, and SQL recipes
additionally run on a secret-less connection (defense in depth).
"""

from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from osaip_engine.errors import InvalidInput

# Scalar/aggregate functions a SQL recipe may call. Table-producing and
# environment-reading functions are deliberately absent.
_ALLOWED_FUNCTIONS = {
    # aggregates
    "count",
    "sum",
    "min",
    "max",
    "avg",
    "mean",
    "median",
    "stddev",
    "variance",
    "count_distinct",
    "approx_count_distinct",
    "first",
    "last",
    "list",
    "string_agg",
    # scalar
    "abs",
    "round",
    "ceil",
    "floor",
    "coalesce",
    "nullif",
    "cast",
    "try_cast",
    "upper",
    "lower",
    "trim",
    "ltrim",
    "rtrim",
    "length",
    "substring",
    "substr",
    "replace",
    "concat",
    "concat_ws",
    "left",
    "right",
    "lpad",
    "rpad",
    "reverse",
    "contains",
    "starts_with",
    "ends_with",
    "position",
    "strlen",
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "second",
    "date_part",
    "date_trunc",
    "date_diff",
    "datediff",
    "now",
    "current_date",
    "strftime",
    "strptime",
    "greatest",
    "least",
    "sign",
    "power",
    "pow",
    "sqrt",
    "exp",
    "ln",
    "log",
    "mod",
    "row_number",
    "rank",
    "dense_rank",
    "lag",
    "lead",
    "sum_over",
    "ifnull",
    "if",
    "case",
    "typeof",
    "to_json",
    "json_extract",
}

# Explicit denylist for clarity in errors (also caught by the allowlist).
_FORBIDDEN = {
    "duckdb_secrets",
    "which_secret",
    "read_parquet",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "glob",
    "getenv",
    "sniff_csv",
    "parquet_scan",
    "csv_scan",
    "read_text",
    "read_blob",
}

_ALLOWED_DBS = {"", "main", "memory", "temp"}


def validate_sql(query: str, input_aliases: set[str]) -> None:
    """Raise InvalidInput unless `query` is a single SELECT that reads only from the
    given input view aliases and calls only allowlisted functions."""
    try:
        statements = parse(query, dialect="duckdb", error_level="raise")  # type: ignore[arg-type]
    except ParseError as exc:
        raise InvalidInput("The SQL could not be parsed.") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise InvalidInput("Provide exactly one SQL statement.")
    root = statements[0]
    # Whitelist the statement TYPE (blacklisting keywords misses CALL/LOAD/PRAGMA,
    # which fall back to exp.Command, and CHECKPOINT which parses as exp.Column).
    if not isinstance(root, exp.Select | exp.Subquery | exp.Union | exp.With):
        raise InvalidInput("Only SELECT statements are allowed in a SQL recipe.")
    if isinstance(root, exp.Union):
        raise InvalidInput("Only a single SELECT is allowed (no set operations at top level).")

    # CTE names are valid FROM targets (they resolve within the query, not to storage).
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    allowed_names = {alias.lower() for alias in input_aliases} | cte_names

    for table in root.find_all(exp.Table):
        # Reject string-literal "tables" (FROM 'sales' → a file path).
        name_node = table.this
        if isinstance(name_node, exp.Literal):
            raise InvalidInput("Quoted-string table names are not allowed.")
        catalog = table.catalog or ""
        db = (table.db or "").lower()
        if catalog:
            raise InvalidInput(f"Cross-catalog reference is not allowed: {table.sql()}.")
        if db not in _ALLOWED_DBS:
            raise InvalidInput(f"Schema {db!r} is not allowed.")
        name = table.name.lower()
        if name not in allowed_names:
            raise InvalidInput(
                f"Table {table.name!r} is not an input of this recipe. "
                f"Available: {sorted(input_aliases)}."
            )

    for func in root.find_all(exp.Func):
        fname = _function_name(func)
        if fname is None:
            continue
        if fname in _FORBIDDEN or fname not in _ALLOWED_FUNCTIONS:
            raise InvalidInput(f"Function {fname!r} is not allowed in a SQL recipe.")


def _function_name(node: Any) -> str | None:
    # exp.Anonymous (unknown/user function): the name is in `.this`.
    if isinstance(node, exp.Anonymous):
        this = node.this
        return str(this).lower() if this else None
    # Built-in Func subclasses expose their canonical SQL name via sql_name().
    sql_name = getattr(node, "sql_name", None)
    if callable(sql_name):
        try:
            return str(sql_name()).lower()
        except Exception:  # noqa: BLE001
            return None
    return None
