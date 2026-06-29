import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import settings


def test_encrypt_secret_and_decrypt_secret_returns_original_value(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

    encrypted = crypto.encrypt_secret("APP_USR-secret")

    assert encrypted != "APP_USR-secret"
    assert crypto.decrypt_secret(encrypted) == "APP_USR-secret"


def test_encrypt_secret_requires_token_encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", None)

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        crypto.encrypt_secret("APP_USR-secret")
