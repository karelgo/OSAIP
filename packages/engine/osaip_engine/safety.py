"""SQL literal/identifier escaping for the few places DuckDB SQL is assembled from
values that cannot be bound as parameters (DDL, ATTACH, CREATE SECRET). Identifiers
and secret fields are ALSO validated upstream (routers/connections.py); this is the
second, in-engine layer (ADR-0006 §4 / plan §6)."""

import re

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def sql_literal(value: str) -> str:
    """A single-quoted SQL string literal with quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


def sql_ident(value: str) -> str:
    """A double-quoted SQL identifier with quotes doubled. Rejects control chars."""
    if "\x00" in value:
        raise ValueError("identifier contains a null byte")
    return '"' + value.replace('"', '""') + '"'


def qualified_ident(qualified: str) -> str:
    """Quote a possibly schema-qualified name: schema.table → "schema"."table"."""
    parts = qualified.split(".")
    if len(parts) > 2 or any(not part for part in parts):
        raise ValueError("expected `table` or `schema.table`")
    return ".".join(sql_ident(part) for part in parts)


def is_plain_ident(value: str) -> bool:
    return bool(_IDENT_RE.match(value))
