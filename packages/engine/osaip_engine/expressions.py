"""Safe expression language for formula / filter / split recipe steps (spec §10,
ADR-0007 §4). User text is parsed with the stdlib `ast` in eval mode and compiled to
an Ibis expression through a STRICT node whitelist. There is NO eval/exec anywhere —
CI grep-gates for it.

Grammar (everything else is rejected):
- literals: int, float, str, True/False/None
- column refs: `col("name")`  (bare Names are NOT allowed — CSV headers may have
  spaces/case/leading digits, and bare Names invite ambiguity)
- arithmetic: + - * / // % ** (unary + -)
- comparison: == != < <= > >=  (chained comparisons expand to AND-pairs)
- boolean: and / or / not
- calls: only the allowlisted functions below
"""

import ast
from collections.abc import Callable
from typing import Any

import ibis
from ibis.expr.types import Value

from osaip_engine.errors import InvalidInput


class ExpressionError(InvalidInput):
    public_message = "The expression could not be parsed."


def _fn_if_else(cond: Value, then: Value, otherwise: Value) -> Value:
    return ibis.ifelse(cond, then, otherwise)


def _fn_coalesce(*args: Value) -> Value:
    return ibis.coalesce(*args)


def _fn_concat(*args: Value) -> Value:
    parts = [a.cast("string") if isinstance(a, Value) else ibis.literal(str(a)) for a in args]
    result = parts[0]
    for part in parts[1:]:
        result = result + part
    return result


def _fn_cast(value: Value, type_name: Any) -> Value:
    if not isinstance(type_name, str):
        raise ExpressionError("cast(x, 'type') needs a string type name.")
    return value.cast(type_name)


# Allowlisted functions → callables producing Ibis expressions. Anything not here is
# rejected at compile time.
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "upper": lambda x: x.upper(),
    "lower": lambda x: x.lower(),
    "trim": lambda x: x.strip(),
    "length": lambda x: x.length(),
    "replace": lambda x, a, b: x.replace(a, b),
    "round": lambda x, d=0: x.round(d),
    "abs": lambda x: x.abs(),
    "year": lambda x: x.year(),
    "month": lambda x: x.month(),
    "day": lambda x: x.day(),
    "concat": _fn_concat,
    "coalesce": _fn_coalesce,
    "if_else": _fn_if_else,
    "cast": _fn_cast,
}

_MAX_STR_LITERAL = 10_000


class _Compiler:
    def __init__(self, table: ibis.Table) -> None:
        self.table = table

    def compile(self, expression: str) -> Value:
        if len(expression) > 4000:
            raise ExpressionError("The expression is too long.")
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError("The expression has a syntax error.") from exc
        return self._eval(tree.body)

    def _eval(self, node: ast.AST) -> Any:
        method = getattr(self, f"_node_{type(node).__name__}", None)
        if method is None:
            raise ExpressionError(f"`{type(node).__name__}` is not allowed in an expression.")
        return method(node)

    # ── literals ────────────────────────────────────────────────────────────────

    def _node_Constant(self, node: ast.Constant) -> Any:
        value = node.value
        if isinstance(value, str) and len(value) > _MAX_STR_LITERAL:
            raise ExpressionError("String literal is too long.")
        if isinstance(value, bool | int | float | str) or value is None:
            return value
        raise ExpressionError("Only numbers, strings, booleans, and None are allowed.")

    # ── column reference ──────────────────────────────────────────────────────────

    def _node_Call(self, node: ast.Call) -> Any:
        if node.keywords:
            raise ExpressionError("Keyword arguments are not supported.")
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("Only direct function calls are allowed.")
        name = node.func.id
        if name == "col":
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
                raise ExpressionError('col() takes one string, e.g. col("amount").')
            column = node.args[0].value
            if not isinstance(column, str) or column not in self.table.columns:
                raise ExpressionError(f"Unknown column: {column!r}.")
            return self.table[column]
        func = _FUNCTIONS.get(name)
        if func is None:
            raise ExpressionError(f"Function {name!r} is not allowed.")
        args = [self._eval(arg) for arg in node.args]
        try:
            return func(*args)
        except ExpressionError:
            raise
        except Exception as exc:  # noqa: BLE001 — user error surfaces as a clean message
            raise ExpressionError(f"{name}() could not be applied.") from exc

    # ── arithmetic ────────────────────────────────────────────────────────────────

    def _node_BinOp(self, node: ast.BinOp) -> Any:
        left = self._eval(node.left)
        right = self._eval(node.right)
        op = type(node.op).__name__
        if op == "Add":
            return left + right
        if op == "Sub":
            return left - right
        if op == "Mult":
            return left * right
        if op == "Div":
            return left / _nz(right)  # nullif(denom,0) — no inf, no crash
        if op == "FloorDiv":
            return (left / _nz(right)).floor()
        if op == "Mod":
            return left % _nz(right)
        if op == "Pow":
            return left**right
        raise ExpressionError(f"Operator {op} is not allowed.")

    def _node_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self._eval(node.operand)
        op = type(node.op).__name__
        if op == "USub":
            return -operand
        if op == "UAdd":
            return operand
        if op == "Not":
            return ~_as_bool(operand)
        raise ExpressionError(f"Unary operator {op} is not allowed.")

    # ── comparison (chained → AND-pairs) ─────────────────────────────────────────

    def _node_Compare(self, node: ast.Compare) -> Any:
        # Python parses `1 < x < 10` as one Compare with two ops; expand to an
        # AND-chain of pairwise comparisons so the second bound is never dropped.
        operands = [node.left, *node.comparators]
        result: Value | None = None
        for index, op in enumerate(node.ops):
            left = self._eval(operands[index])
            right = self._eval(operands[index + 1])
            pair = self._compare(op, left, right)
            result = pair if result is None else (result & pair)
        assert result is not None
        return result

    @staticmethod
    def _compare(op: ast.cmpop, left: Any, right: Any) -> Value:
        name = type(op).__name__
        if name == "Eq":
            return left == right
        if name == "NotEq":
            return left != right
        if name == "Lt":
            return left < right
        if name == "LtE":
            return left <= right
        if name == "Gt":
            return left > right
        if name == "GtE":
            return left >= right
        raise ExpressionError(f"Comparison {name} is not allowed (in/is unsupported).")

    def _node_BoolOp(self, node: ast.BoolOp) -> Any:
        values = [_as_bool(self._eval(v)) for v in node.values]
        result = values[0]
        is_and = isinstance(node.op, ast.And)
        for value in values[1:]:
            result = (result & value) if is_and else (result | value)
        return result


def _nz(value: Any) -> Any:
    """nullif(value, 0) so division/modulo by zero yields NULL, never inf or a crash."""
    if isinstance(value, Value):
        return value.nullif(0)
    return None if value == 0 else value


def _as_bool(value: Any) -> Value:
    if isinstance(value, Value):
        return value
    return ibis.literal(bool(value))


def compile_expression(table: ibis.Table, expression: str) -> Value:
    """Compile a user expression to an Ibis value bound to `table`."""
    return _Compiler(table).compile(expression)


def compile_predicate(table: ibis.Table, expression: str) -> Value:
    """Compile a boolean predicate (filter/split); non-Value results become literals."""
    return _as_bool(compile_expression(table, expression))
