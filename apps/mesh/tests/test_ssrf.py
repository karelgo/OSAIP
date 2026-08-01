"""SSRF guard (spec §8): a user-supplied provider base_url is fetched server-side, so
loopback / link-local / private targets are refused unless explicitly allowlisted."""

import pytest

from osaip_mesh.ssrf import UrlNotAllowed, validate_base_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://127.0.0.1:8000/v1",
        "http://localhost:11434/v1",
        "http://10.0.0.5/v1",
        "http://192.168.1.10/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_blocks_internal_targets(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        validate_base_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/",
    ],
)
def test_blocks_non_http_schemes(url: str) -> None:
    with pytest.raises(UrlNotAllowed, match="http"):
        validate_base_url(url)


def test_blocks_credentials_in_url() -> None:
    with pytest.raises(UrlNotAllowed, match="Credentials"):
        validate_base_url("https://user:secret@api.example.com/v1")


def test_allows_public_https() -> None:
    assert validate_base_url("https://api.openai.com/v1").startswith("https://")


def test_operator_allowlist_permits_on_prem(monkeypatch: pytest.MonkeyPatch) -> None:
    # An on-prem Ollama on the compose network is private by design — reachable only
    # because the operator opted in.
    monkeypatch.setenv("OSAIP_MESH_URL_ALLOWLIST", "ollama")
    assert validate_base_url("http://ollama:11434/v1") == "http://ollama:11434/v1"
    with pytest.raises(UrlNotAllowed):
        validate_base_url("http://192.168.1.10/v1")  # still blocked
