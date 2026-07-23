"""Repo-wide fixtures: one SeaweedFS container per test session (S3 for engine +
upload tests) and one-time DuckDB extension install for host runs (network needed on
first run; cached afterwards — ADR-0006 §3)."""

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from osaip_engine.storage import Storage, StorageConfig

S3_TEST_ACCESS_KEY = "osaiptest"
S3_TEST_SECRET_KEY = "osaip-test-s3-secret"  # noqa: S105 — test-only credential
S3_TEST_BUCKET = "osaip-test"


@pytest.fixture(scope="session")
def seaweed_config() -> Iterator[StorageConfig]:
    identities = {
        "identities": [
            {
                "name": "osaip-test",
                "credentials": [{"accessKey": S3_TEST_ACCESS_KEY, "secretKey": S3_TEST_SECRET_KEY}],
                "actions": ["Admin", "Read", "Write", "List", "Tagging"],
            }
        ]
    }
    config_dir = tempfile.mkdtemp(prefix="osaip-seaweed-")
    config_path = Path(config_dir) / "s3.json"
    config_path.write_text(json.dumps(identities))

    container = (
        DockerContainer("chrislusf/seaweedfs:3.80")
        .with_command(
            "server -ip.bind=0.0.0.0 -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json -dir=/data"
        )
        .with_exposed_ports(8333)
        .with_volume_mapping(str(config_path), "/etc/seaweedfs/s3.json")
    )
    container.start()
    try:
        wait_for_logs(container, "Start Seaweed S3 API Server", timeout=60)
        config = StorageConfig(
            endpoint=f"{container.get_container_host_ip()}:{container.get_exposed_port(8333)}",
            bucket=S3_TEST_BUCKET,
            access_key=S3_TEST_ACCESS_KEY,
            secret_key=S3_TEST_SECRET_KEY,
        )
        Storage(config).ensure_bucket()
        yield config
    finally:
        container.stop()


@pytest.fixture(scope="session")
def duck_extensions() -> None:
    from osaip_engine.duck import install_extensions

    install_extensions()
