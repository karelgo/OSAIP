"""The Provider protocol every adapter implements."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class CompletionRequest:
    model: str
    messages: list[Message]
    max_tokens: int = 512
    temperature: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionResult:
    content: str
    tokens_in: int
    tokens_out: int
    model_version: str | None = None
    # True when the provider did not report usage and we estimated the counts; the
    # ledger flags these so an estimate is never presented as exact (ADR-0008 §2).
    tokens_estimated: bool = False


class ProviderError(Exception):
    """A provider failure with a message safe to show a user. Raw driver/HTTP text
    never escapes an adapter — it could carry the API key or an internal URL."""

    def __init__(self, public_message: str, *, retryable: bool = False) -> None:
        super().__init__(public_message)
        self.public_message = public_message
        self.retryable = retryable


class Provider(Protocol):
    """Adapters are constructed per call with their connection's config + secret."""

    name: str

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...
