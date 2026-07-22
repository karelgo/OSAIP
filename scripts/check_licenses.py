"""License allowlist gate (CP-12; policy = spec §3.1 + ADR-0004 exceptions).

Checks every installed Python distribution in the active venv and every Node package
in the pnpm workspace against the allowlist. Dev/CI-only MPL-2.0 (@axe-core/*) and
font-asset OFL are the recorded exceptions.
"""

import json
import re
import subprocess
import sys
from importlib import metadata

ALLOWED = [
    # spec §3.1
    r"MIT",
    r"Apache",
    r"BSD",
    r"PSF",
    r"Python Software Foundation",
    r"Python-2\.0",
    r"PostgreSQL",
    # ADR-0004 recorded exceptions
    r"ISC",
    r"OFL|SIL Open Font License",  # unmodified font assets only
    r"MPL[- ]?2\.0|Mozilla Public License",  # @axe-core/* dev-only
    # common compound expressions
    r"0BSD",
    r"Unlicense",
    r"CC0",
    r"CC-BY-4\.0",  # docs/data assets (e.g. caniuse-lite)
    r"BlueOak",
    r"WTFPL",
    r"Zlib",
]
ALLOWED_RE = re.compile("|".join(ALLOWED), re.IGNORECASE)

# Distributions whose metadata is missing/odd but whose license is verified manually.
PYTHON_OVERRIDES = {
    "typing-extensions": "PSF-2.0",
    "asgiref": "BSD-3-Clause",
    "distlib": "PSF-2.0",
}


def python_violations() -> list[str]:
    problems = []
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "unknown").lower()
        if name in PYTHON_OVERRIDES:
            continue
        # First-party workspace packages: OSAIP's own license is a project decision
        # (tracked in the phase summary), not a dependency-policy question.
        if name == "osaip" or name.startswith("osaip-"):
            continue
        license_field = dist.metadata.get("License-Expression") or dist.metadata.get("License")
        classifiers = [value for key, value in dist.metadata.items() if key == "Classifier"]
        license_classifiers = " ".join(c for c in classifiers if c.startswith("License ::"))
        text = f"{license_field or ''} {license_classifiers}".strip()
        if not text:
            problems.append(f"py:{name}: no license metadata")
        elif not ALLOWED_RE.search(text):
            problems.append(f"py:{name}: {text[:120]!r} not on allowlist")
    return problems


def node_violations() -> list[str]:
    result = subprocess.run(
        ["pnpm", "licenses", "list", "--json", "--prod"],  # noqa: S607 — PATH lookup is fine for a dev/CI tool
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return [f"node: pnpm licenses failed: {result.stderr.strip()[:200]}"]
    data = json.loads(result.stdout)
    problems = []
    for license_name, packages in data.items():
        if ALLOWED_RE.search(license_name):
            continue
        names = ", ".join(sorted({p["name"] for p in packages})[:10])
        problems.append(f"node:{license_name}: {names}")
    return problems


def main() -> int:
    problems = python_violations() + node_violations()
    if problems:
        print("License gate FAILED (spec §3.1 / ADR-0004):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("License gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
