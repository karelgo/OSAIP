"""Python recipe sandbox (spec §3.2/§10, ADR-0007 §5): run user code in a subprocess
with CPU/mem/time limits, no network, and no ambient credentials.

v1 is subprocess isolation — NOT container isolation (that's a later hardening). The
compensating control for that gap (blocking BSN/bijzonder inputs) lives in the build
path, not here.
"""

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Resource limits. RLIMIT_AS is unsettable on macOS (setrlimit raises), so each limit
# is applied independently and AS is Linux-only; the wall-clock kill below is the
# cross-platform memory backstop.
_CPU_SECONDS = int(os.environ.get("OSAIP_SANDBOX_CPU_SECONDS", "30"))
_MEM_BYTES = int(os.environ.get("OSAIP_SANDBOX_MEM_BYTES", str(1024 * 1024 * 1024)))
_FSIZE_BYTES = int(os.environ.get("OSAIP_SANDBOX_FSIZE_BYTES", str(512 * 1024 * 1024)))
_WALL_SECONDS = float(os.environ.get("OSAIP_SANDBOX_WALL_SECONDS", "60"))

_IS_LINUX = sys.platform.startswith("linux")


class SandboxError(Exception):
    """User-visible sandbox failure. `public_message` is safe to show."""

    def __init__(self, public_message: str, *, logs: str = "") -> None:
        super().__init__(public_message)
        self.public_message = public_message
        self.logs = logs


@dataclass
class SandboxResult:
    output_path: str
    logs: str


def _apply_limits() -> None:  # pragma: no cover — runs in the child, before exec
    """preexec_fn: drop into a new session and set rlimits. EACH setrlimit is guarded
    — a single unsettable limit (RLIMIT_AS on macOS) must not abort the whole exec."""
    import resource

    os.setsid()
    limits = [
        ("RLIMIT_CPU", (_CPU_SECONDS, _CPU_SECONDS)),
        ("RLIMIT_FSIZE", (_FSIZE_BYTES, _FSIZE_BYTES)),
    ]
    if _IS_LINUX:
        # AS is Linux-only (macOS rejects the set → would abort the launch).
        limits.append(("RLIMIT_AS", (_MEM_BYTES, _MEM_BYTES)))
    for name, value in limits:
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, value)
        except (ValueError, OSError):
            continue  # best-effort; never abort exec over one limit


def _command(script_path: str) -> list[str]:
    """`python -I` (isolated) running the recipe. On Linux, wrap in `unshare -n` to
    deny network (LOCKED no-network; degraded-and-documented on macOS dev)."""
    python = os.environ.get("OSAIP_SANDBOX_PYTHON", sys.executable)
    base = [python, "-I", script_path]
    if _IS_LINUX and _network_isolation_available():
        # -n = new network namespace with no interfaces; -r maps root so it needs no
        # privilege. Falls back (below) if unshare is missing.
        return ["unshare", "-n", "-r", *base]
    return base


def _network_isolation_available() -> bool:
    from shutil import which

    return which("unshare") is not None


# A tiny bootstrap that runs the user's code with the SDK importable. The user code is
# written to its own file; this wrapper just execs it after confirming the manifest.
_BOOTSTRAP = """\
import os, runpy, sys
if not os.environ.get("OSAIP_IO_MANIFEST"):
    sys.stderr.write("sandbox misconfigured: no IO manifest\\n")
    sys.exit(3)
runpy.run_path(os.environ["_OSAIP_USER_SCRIPT"], run_name="__main__")
"""


def run_python_recipe(
    code: str,
    *,
    inputs: dict[str, str],
    output_path: str,
    sandbox_python: str | None = None,
    workdir: str | None = None,
) -> SandboxResult:
    """Run `code` with `osaip.input/output` wired to `inputs`/`output_path`. Blocking —
    the worker calls this in a thread. Raises SandboxError on non-zero exit / timeout /
    missing output."""
    tmp = tempfile.mkdtemp(prefix="osaip-sandbox-", dir=workdir)
    tmp_path = Path(tmp)
    user_script = tmp_path / "recipe.py"
    bootstrap = tmp_path / "_bootstrap.py"
    manifest = tmp_path / "manifest.json"
    user_script.write_text(code, encoding="utf-8")
    bootstrap.write_text(_BOOTSTRAP, encoding="utf-8")
    manifest.write_text(json.dumps({"inputs": inputs, "output": output_path}), encoding="utf-8")

    # Minimal env: HOME/TMPDIR to the job tempdir, PATH to the venv bin only, the
    # manifest + user-script pointers — and NOTHING from OSAIP_/AWS_ (no ambient creds).
    python = sandbox_python or os.environ.get("OSAIP_SANDBOX_PYTHON", sys.executable)
    venv_bin = str(Path(python).parent)
    env = {
        "HOME": tmp,
        "TMPDIR": tmp,
        "PATH": f"{venv_bin}:/usr/bin:/bin",
        "OSAIP_IO_MANIFEST": str(manifest),
        "_OSAIP_USER_SCRIPT": str(user_script),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    command = _command(str(bootstrap))
    if sandbox_python:
        os.environ.setdefault("OSAIP_SANDBOX_PYTHON", sandbox_python)
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, minimal env, no shell
            command,
            env=env,
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=_WALL_SECONDS,
            preexec_fn=_apply_limits if os.name == "posix" else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(
            f"The recipe exceeded the {int(_WALL_SECONDS)}s time limit.",
            logs=_as_text(exc.stdout) + _as_text(exc.stderr),
        ) from exc
    except FileNotFoundError as exc:
        raise SandboxError("The sandbox interpreter could not be launched.") from exc

    logs = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise SandboxError("The Python recipe exited with an error.", logs=logs)
    if not Path(output_path).exists():
        raise SandboxError(
            "The recipe did not write an output — call osaip.output() and write parquet to it.",
            logs=logs,
        )
    return SandboxResult(output_path=output_path, logs=logs)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
