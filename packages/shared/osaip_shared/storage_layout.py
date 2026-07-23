"""Object-storage path layout (spec §3.2) — constants only; I/O lives in
osaip_engine.storage. Datasets: projects/<key>/datasets/<name>/v<N>/part-*.parquet."""


def dataset_version_prefix(project_key: str, dataset_name: str, version: int) -> str:
    return f"projects/{project_key}/datasets/{dataset_name}/v{version}"


def dataset_version_location(project_key: str, dataset_name: str, version: int) -> str:
    return f"{dataset_version_prefix(project_key, dataset_name, version)}/part-0.parquet"


def upload_prefix(project_key: str, upload_id: str) -> str:
    # Raw uploads are transient run-artifacts (pruned >24h by the worker).
    return f"projects/{project_key}/uploads/{upload_id}"


def project_prefix(project_key: str) -> str:
    return f"projects/{project_key}/"
