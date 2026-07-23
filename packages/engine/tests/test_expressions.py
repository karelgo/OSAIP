"""Expression language: allowlist matrix + hostile-input rejection + the specific
correctness traps the review flagged (chained comparisons, division by zero)."""

from typing import Any

import ibis
import pytest

from osaip_engine.expressions import ExpressionError, compile_expression, compile_predicate

# An in-memory DuckDB table to compile + execute against.
_CON = ibis.duckdb.connect()
_T = _CON.create_table(
    "t",
    schema={"a": "int64", "b": "int64", "amount": "float64", "region": "string"},
)


def _run(expr: str) -> list[Any]:
    _CON.raw_sql("DELETE FROM t")
    _CON.raw_sql("INSERT INTO t VALUES (1,2,10.0,'NL'),(3,0,20.5,'BE'),(5,4,NULL,'nl')")
    value = compile_expression(_T, expr)
    result: list[Any] = _CON.execute(_T.mutate(out=value).order_by("a")["out"]).tolist()
    return result


def test_arithmetic_and_columns() -> None:
    assert _run('col("a") + col("b")') == [3, 3, 9]
    assert _run('col("a") * 2') == [2, 6, 10]


def test_division_by_zero_is_null_not_inf_or_crash() -> None:
    # row 2 has b=0 → NULL, never inf, never an exception
    out = _run('col("a") / col("b")')
    assert out[0] == 0.5
    assert out[1] is None or (isinstance(out[1], float) and out[1] != out[1])  # NULL/NaN
    out_mod = _run('col("a") % col("b")')
    assert out_mod[1] is None or out_mod[1] != out_mod[1]
    out_floor = _run('col("a") // col("b")')  # must not raise ConversionException
    assert out_floor[1] is None or out_floor[1] != out_floor[1]


def test_chained_comparison_enforces_both_bounds() -> None:
    _CON.raw_sql("DELETE FROM t")
    _CON.raw_sql("INSERT INTO t VALUES (5,0,0.0,'x'),(15,0,0.0,'y'),(-1,0,0.0,'z')")
    pred = compile_predicate(_T, '0 < col("a") < 10')
    rows = _CON.execute(_T.filter(pred)["a"]).tolist()
    assert rows == [5]  # 15 fails the upper bound, -1 the lower — NOT just `0 < a`


def test_functions() -> None:
    assert _run('upper(col("region"))') == ["NL", "BE", "NL"]
    assert _run('coalesce(col("amount"), -1.0)')[2] == -1.0
    assert _run('if_else(col("a") > 2, "big", "small")') == ["small", "big", "big"]


@pytest.mark.parametrize(
    "hostile",
    [
        "__import__('os').system('id')",
        "col.__class__",
        "col('a').__class__",
        "(lambda: 1)()",
        "[x for x in range(10)]",
        "{1: 2}",
        "{1, 2}",
        "f'{col(\"a\")}'",
        "col('a')[0]",
        "a",  # bare name — must use col()
        "open('/etc/passwd')",
        "col('a') @ col('b')",
        "().__class__.__bases__",
        "col('nonexistent')",
        "unknownfunc(1)",
    ],
)
def test_hostile_inputs_rejected(hostile: str) -> None:
    with pytest.raises(ExpressionError):
        compile_expression(_T, hostile)
