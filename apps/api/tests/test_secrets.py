import pytest
from cryptography.fernet import Fernet

from osaip_api.secrets import SecretKeyError, Vault


def test_round_trip() -> None:
    vault = Vault(Fernet.generate_key().decode())
    ciphertext = vault.encrypt("s3cr3t-value")
    assert vault.decrypt(ciphertext) == "s3cr3t-value"
    assert ciphertext != b"s3cr3t-value"


def test_rotation_prepend_decrypts_old_values() -> None:
    old_key = Fernet.generate_key().decode()
    old_vault = Vault(old_key)
    ciphertext = old_vault.encrypt("value-from-before-rotation")

    new_key = Fernet.generate_key().decode()
    rotated = Vault(f"{new_key},{old_key}")
    # Old ciphertext still readable; new writes use the new key.
    assert rotated.decrypt(ciphertext) == "value-from-before-rotation"
    assert rotated.primary_key_id != old_vault.primary_key_id
    fresh = rotated.encrypt("value-after-rotation")
    assert rotated.decrypt(fresh) == "value-after-rotation"
    with pytest.raises(SecretKeyError, match="could not be decrypted"):
        Vault(new_key).decrypt(ciphertext)  # key removed too early → loud error


def test_invalid_key_fails_at_construction() -> None:
    with pytest.raises(SecretKeyError, match="entry 0"):
        Vault("not-a-fernet-key")
    with pytest.raises(SecretKeyError, match="empty"):
        Vault(" , ")


def test_dev_default_key_is_valid() -> None:
    from osaip_api.config import Settings

    Vault(Settings().secret_key)
