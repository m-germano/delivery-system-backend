from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Any

from app.core.config import settings


def _normalise_created_at(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


class DeliveryCodeService:
    """Gera e valida o código de confirmação da entrega.

    O código não fica salvo no banco. Ele é gerado de forma determinística a partir
    do id da entrega, id do pedido, data de criação e SECRET_KEY da API.

    Como o entregador não recebe esse código nas respostas de entrega, ele precisa
    pedir o código ao cliente no momento da entrega.
    """

    CODE_LENGTH = 4

    @classmethod
    def generate_code(cls, delivery) -> str:
        secret = str(settings.SECRET_KEY).encode("utf-8")
        payload = f"{delivery.id}:{delivery.order_id}:{_normalise_created_at(delivery.created_at)}".encode("utf-8")
        digest = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        number = int(digest[:12], 16) % (10 ** cls.CODE_LENGTH)
        return str(number).zfill(cls.CODE_LENGTH)

    @classmethod
    def normalize_code(cls, code: str | int | None) -> str:
        digits = "".join(character for character in str(code or "") if character.isdigit())
        return digits[: cls.CODE_LENGTH]

    @classmethod
    def is_valid_code(cls, delivery, code: str | int | None) -> bool:
        provided_code = cls.normalize_code(code)
        if len(provided_code) != cls.CODE_LENGTH:
            return False

        expected_code = cls.generate_code(delivery)
        return hmac.compare_digest(provided_code, expected_code)


class PickupCodeService:
    """Gera e valida o código de confirmação da retirada.

    Segue o mesmo padrão do código de entrega: não salva o código em texto puro no
    banco e gera um valor estável a partir de dados imutáveis do pedido.
    """

    CODE_LENGTH = 4

    @classmethod
    def generate_code(cls, order) -> str:
        secret = str(settings.SECRET_KEY).encode("utf-8")
        payload = (
            f"pickup:{order.id}:{order.company_id}:{order.customer_user_id}:{_normalise_created_at(order.created_at)}"
        ).encode("utf-8")
        digest = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        number = int(digest[:12], 16) % (10 ** cls.CODE_LENGTH)
        return str(number).zfill(cls.CODE_LENGTH)

    @classmethod
    def normalize_code(cls, code: str | int | None) -> str:
        digits = "".join(character for character in str(code or "") if character.isdigit())
        return digits[: cls.CODE_LENGTH]

    @classmethod
    def is_valid_code(cls, order, code: str | int | None) -> bool:
        provided_code = cls.normalize_code(code)
        if len(provided_code) != cls.CODE_LENGTH:
            return False

        expected_code = cls.generate_code(order)
        return hmac.compare_digest(provided_code, expected_code)
