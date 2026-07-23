"""OSAIP SDK — the IO broker for sandboxed Python recipes (spec §3.2 "all data IO via
the SDK broker; no ambient credentials").

Inside a Python recipe the worker sets `OSAIP_IO_MANIFEST` to a JSON file mapping
input names → staged parquet paths and providing the output path. User code:

    import osaip
    import pyarrow.parquet as pq

    table = pq.read_table(osaip.input("orders"))
    ...
    pq.write_table(result, osaip.output())

The manifest never contains credentials; the subprocess has no network and no
OSAIP_/AWS_ env (ADR-0007 §5). The worker uploads the written output parquet.
"""

import json
import os
from functools import lru_cache
from typing import Any

__version__ = "0.2.0"

_MANIFEST_ENV = "OSAIP_IO_MANIFEST"


@lru_cache(maxsize=1)
def _manifest() -> dict[str, Any]:
    path = os.environ.get(_MANIFEST_ENV)
    if not path:
        raise RuntimeError(
            "osaip.input/output are only available inside a running OSAIP Python recipe."
        )
    with open(path, encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


def input(name: str) -> str:  # noqa: A001 — the recipe-facing name is deliberately `input`
    """Local parquet path for the named recipe input."""
    inputs: dict[str, str] = _manifest()["inputs"]
    if name not in inputs:
        available = ", ".join(sorted(inputs)) or "(none)"
        raise KeyError(f"No input named {name!r}. Available inputs: {available}.")
    return inputs[name]


def inputs() -> dict[str, str]:
    """All input names → local parquet paths."""
    return dict(_manifest()["inputs"])


def output() -> str:
    """Local path to write the recipe's output parquet to."""
    return str(_manifest()["output"])
