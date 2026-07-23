"""Typed, sanitized engine errors (ADR-0006 §4).

The engine NEVER imports the API layer; the API translates these to problem+json.
Messages are safe for end users by construction — no DSNs, hosts, or credentials.
"""


class EngineError(Exception):
    """Base class. `public_message` is safe to show verbatim."""

    public_message = "The data engine reported an error."

    def __init__(self, public_message: str | None = None) -> None:
        if public_message is not None:
            self.public_message = public_message
        super().__init__(self.public_message)


class AuthFailed(EngineError):
    public_message = "Authentication failed: the connection's credentials were rejected."


class HostUnreachable(EngineError):
    public_message = "The host could not be reached (network error or wrong host/port)."


class DatabaseNotFound(EngineError):
    public_message = "The database does not exist on that host."


class ObjectNotFound(EngineError):
    public_message = "The requested table or file was not found."


class InvalidInput(EngineError):
    public_message = "The input could not be parsed."


class Interrupted(EngineError):
    public_message = "The operation took too long and was cancelled."


class StorageError(EngineError):
    public_message = "Object storage rejected the operation."
