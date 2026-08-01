"""The built-in echo provider (ADR-0008 §9).

Deterministic, offline, token-counted. It exists so CI and the acceptance suite are
hermetic and free — and because it implements the SAME protocol as the real adapters,
"two connections, identical code path" is genuinely exercised rather than special-cased.

It is labelled as a mock in the UI and refuses any connection whose residency is not
`local`: a mock must never be mistaken for, or stand in for, a real external provider.
"""

import hashlib
import re
from typing import Any

from osaip_mesh.providers.base import CompletionRequest, CompletionResult, ProviderError

_WORD = re.compile(r"\S+")


def count_tokens(text: str) -> int:
    """A stable, provider-independent word-ish count. Deliberately simple: echo's
    numbers must be reproducible across machines and Python versions."""
    return len(_WORD.findall(text))


class EchoProvider:
    name = "echo"

    def __init__(self, config: dict[str, Any] | None = None, secret: str | None = None) -> None:
        self._config = config or {}
        # echo takes no credentials; accepting one would invite treating it as real.
        if secret:
            raise ProviderError("The echo provider does not take credentials.")

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        prompt = "\n".join(message.content for message in request.messages)
        tokens_in = count_tokens(prompt)
        # Deterministic body: the same request always yields the same response, so
        # tests can assert on content and the cache is exercised honestly.
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
        mode = str(self._config.get("mode", "echo"))
        if mode == "classify":
            labels = self._config.get("labels") or ["positive", "negative"]
            content = str(labels[int(digest, 16) % len(labels)])
        else:
            last_user = next(
                (m.content for m in reversed(request.messages) if m.role == "user"), ""
            )
            content = f"echo[{digest}] {last_user}"[: request.max_tokens * 8]
        return CompletionResult(
            content=content,
            tokens_in=tokens_in,
            tokens_out=count_tokens(content),
            model_version=f"{request.model}@echo-1",
        )
