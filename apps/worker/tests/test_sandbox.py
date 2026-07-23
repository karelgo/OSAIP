"""Python sandbox: env has no credentials, launches on the host OS, denies network
(linux), enforces limits, and rejects a missing output."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from osaip_worker.sandbox import SandboxError, run_python_recipe


def _stage_input(tmp_path: Path) -> dict[str, str]:
    table = pa.table({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    path = tmp_path / "in.parquet"
    pq.write_table(table, path)
    return {"orders": str(path)}


def test_transform_runs_and_writes_output(tmp_path: Path) -> None:
    inputs = _stage_input(tmp_path)
    output = str(tmp_path / "out.parquet")
    code = (
        "import osaip\n"
        "import pyarrow.parquet as pq\n"
        "t = pq.read_table(osaip.input('orders'))\n"
        "pq.write_table(t.slice(0, 2), osaip.output())\n"
    )
    result = run_python_recipe(code, inputs=inputs, output_path=output, workdir=str(tmp_path))
    assert Path(result.output_path).exists()
    assert pq.read_table(output).num_rows == 2


def test_env_has_no_ambient_credentials(tmp_path: Path) -> None:
    inputs = _stage_input(tmp_path)
    output = str(tmp_path / "out.parquet")
    # The recipe writes the environment it sees; assert no OSAIP_/AWS_ leaked in.
    code = (
        "import os, osaip\n"
        "import pyarrow as pa, pyarrow.parquet as pq\n"
        "leaked = [k for k in os.environ if k.startswith(('OSAIP_S3', 'AWS_', 'OSAIP_SECRET', "
        "'OSAIP_DATABASE', 'OSAIP_OIDC'))]\n"
        "pq.write_table(pa.table({'leaked': leaked}), osaip.output())\n"
    )
    run_python_recipe(code, inputs=inputs, output_path=output, workdir=str(tmp_path))
    assert pq.read_table(output).num_rows == 0  # nothing sensitive in the child env


def test_missing_output_is_rejected(tmp_path: Path) -> None:
    inputs = _stage_input(tmp_path)
    output = str(tmp_path / "out.parquet")
    with pytest.raises(SandboxError, match="did not write an output"):
        run_python_recipe("x = 1\n", inputs=inputs, output_path=output, workdir=str(tmp_path))


def test_user_error_surfaces_cleanly(tmp_path: Path) -> None:
    inputs = _stage_input(tmp_path)
    output = str(tmp_path / "out.parquet")
    with pytest.raises(SandboxError, match="exited with an error") as excinfo:
        run_python_recipe(
            "raise ValueError('boom')\n", inputs=inputs, output_path=output, workdir=str(tmp_path)
        )
    assert "boom" in excinfo.value.logs


def test_network_is_denied_when_netns_available(tmp_path: Path) -> None:
    from osaip_worker.sandbox import _unshare_prefix

    if not _unshare_prefix():
        pytest.skip("network namespaces unavailable here (needs unprivileged userns)")
    inputs = _stage_input(tmp_path)
    output = str(tmp_path / "out.parquet")
    # A socket connect must fail with no network namespace interfaces.
    code = (
        "import socket, osaip\n"
        "import pyarrow as pa, pyarrow.parquet as pq\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2).close()\n"
        "    reached = True\n"
        "except OSError:\n"
        "    reached = False\n"
        "pq.write_table(pa.table({'reached': [reached]}), osaip.output())\n"
    )
    run_python_recipe(code, inputs=inputs, output_path=output, workdir=str(tmp_path))
    assert pq.read_table(output).column("reached")[0].as_py() is False
