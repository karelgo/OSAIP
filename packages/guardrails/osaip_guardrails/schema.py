"""Output-shape validation for the `post` stage.

A deliberately SMALL subset of JSON Schema — type, required, properties, items, enum,
minimum/maximum, minLength/maxLength — implemented here rather than pulled in as a
dependency, because the guardrails package must stay installable with nothing but the
standard library (air-gapped installs, ADR-0008 §5).

Unsupported keywords are IGNORED, never silently treated as satisfied in a way that
could mislead: `supported_keywords()` lets a caller show which parts of a schema this
validator actually enforces, so nobody believes a `$ref` was checked when it was not.
"""

import json
from typing import Any

SUPPORTED = frozenset(
    {
        "type",
        "required",
        "properties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
    }
)

_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def unsupported_keywords(schema: dict[str, Any]) -> set[str]:
    """Every keyword in the schema this validator does not enforce, at any depth.

    Only descends where the values are themselves SCHEMAS. Under `properties` the keys
    are property names, not keywords — walking them as keywords would report every
    field of every object as unsupported.
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key not in SUPPORTED:
                found.add(key)
            elif key == "properties" and isinstance(value, dict):
                for subschema in value.values():
                    walk(subschema)
            elif key == "items":
                walk(value)

    walk(schema)
    return found


def validate(value: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    problems: list[str] = []

    expected = schema.get("type")
    if isinstance(expected, str) and expected in _TYPES:
        python_type = _TYPES[expected]
        # bool is a subclass of int in Python; a boolean is not an integer here.
        if expected in {"number", "integer"} and isinstance(value, bool):
            problems.append(f"{path}: expected {expected}, got boolean")
            return problems
        if not isinstance(value, python_type):
            problems.append(f"{path}: expected {expected}, got {type(value).__name__}")
            return problems

    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            problems.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(f"{path}: longer than maxLength {schema['maxLength']}")

    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{path}: above maximum {schema['maximum']}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{path}: missing required property {key!r}")
        for key, subschema in (schema.get("properties") or {}).items():
            if key in value and isinstance(subschema, dict):
                problems.extend(validate(value[key], subschema, path=f"{path}.{key}"))

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            problems.extend(validate(item, schema["items"], path=f"{path}[{index}]"))

    return problems


def validate_json_text(text: str, schema: dict[str, Any]) -> list[str]:
    """Parse then validate. Models fence JSON in ``` often enough that stripping it is
    worth doing here rather than failing a response that is otherwise correct."""
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 2:
            candidate = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return [f"$: response is not valid JSON ({exc.msg})"]
    return validate(parsed, schema)
