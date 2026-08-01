"""Provider adapters. Every provider implements one protocol so callers — and the
acceptance criterion "two connections, identical code path" — exercise the same
pipeline regardless of who serves the tokens (ADR-0008 §9)."""

from osaip_mesh.providers.base import (
    CompletionRequest,
    CompletionResult,
    Message,
    Provider,
    ProviderError,
)
from osaip_mesh.providers.echo import EchoProvider

__all__ = [
    "CompletionRequest",
    "CompletionResult",
    "EchoProvider",
    "Message",
    "Provider",
    "ProviderError",
]
