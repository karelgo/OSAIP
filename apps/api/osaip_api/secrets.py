"""Connection-secret vault: MultiFernet at rest (ADR-0006 §1).

`OSAIP_SECRET_KEY` is a comma-separated key list — encrypt with the first, decrypt
with any. Keys are validated at startup (fail boot, not first write). Secret values
are write-only through the API and never appear in logs or audit details.
"""

import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretKeyError(RuntimeError):
    pass


class Vault:
    def __init__(self, key_csv: str) -> None:
        raw_keys = [part.strip() for part in key_csv.split(",") if part.strip()]
        if not raw_keys:
            raise SecretKeyError(
                "OSAIP_SECRET_KEY is empty. Provide one or more comma-separated "
                "urlsafe-base64 32-byte Fernet keys (rotation: prepend a new key)."
            )
        fernets: list[Fernet] = []
        for index, key in enumerate(raw_keys):
            try:
                fernets.append(Fernet(key))
            except (ValueError, TypeError) as exc:
                raise SecretKeyError(
                    f"OSAIP_SECRET_KEY entry {index} is not a valid Fernet key "
                    "(expected urlsafe-base64 of 32 bytes)."
                ) from exc
        self._multi = MultiFernet(fernets)
        # key_id of the PRIMARY (encrypting) key, recorded per ciphertext for audit.
        self.primary_key_id = _key_id(raw_keys[0])

    def encrypt(self, value: str) -> bytes:
        return self._multi.encrypt(value.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            # No TTL: connection secrets do not expire via Fernet (ADR-0006).
            return self._multi.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise SecretKeyError(
                "A stored secret could not be decrypted with any configured key. "
                "Was a key removed from OSAIP_SECRET_KEY before re-encryption?"
            ) from exc


def _key_id(key: str) -> str:
    return hashlib.sha256(key.encode("ascii")).hexdigest()[:12]
