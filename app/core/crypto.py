from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _get_fernet() -> Fernet:
    if not settings.TOKEN_ENCRYPTION_KEY:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY não configurada. "
            "Gere uma chave com: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    try:
        return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode())
    except ValueError as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY inválida. Use uma chave Fernet válida em base64 url-safe.") from exc


def encrypt_secret(value: str) -> str:
    if not value:
        raise ValueError("Valor secreto não pode ser vazio.")

    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    if not value:
        raise ValueError("Valor criptografado não pode ser vazio.")

    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Não foi possível descriptografar o segredo informado.") from exc


def encrypt_payload(value: str) -> str:
    if not value:
        raise ValueError("Payload não pode ser vazio.")

    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_payload(value: str) -> str:
    if not value:
        raise ValueError("Payload criptografado não pode ser vazio.")

    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Payload criptografado inválido.") from exc
