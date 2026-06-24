from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.controllers.payment_controller import mercado_pago_webhook
from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService


class FakeRequest:
    def __init__(self, payload: dict, headers: dict | None = None):
        self._payload = payload
        self.headers = headers or {}

    async def json(self):
        return self._payload


def build_signature(*, secret: str, provider_payment_id: str, x_request_id: str, timestamp: str) -> str:
    signature = MercadoPagoPixPaymentService._build_mercado_pago_webhook_signature(
        secret=secret,
        provider_payment_id=provider_payment_id,
        x_request_id=x_request_id,
        timestamp=timestamp,
    )
    return f"ts={timestamp},v1={signature}"


@pytest.mark.asyncio
async def test_webhook_without_secret_accepts_and_processes(monkeypatch):
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_WEBHOOK_SECRET", "")
    processed = {"called": False}

    async def fake_process(self, payload):
        processed["called"] = True

    monkeypatch.setattr(MercadoPagoPixPaymentService, "process_mercado_pago_webhook", fake_process)

    response = await mercado_pago_webhook(
        FakeRequest({"type": "payment", "data": {"id": "164726173751"}}),
        db=SimpleNamespace(),
    )

    assert response.received is True
    assert processed["called"] is True


@pytest.mark.asyncio
async def test_webhook_with_valid_signature_accepts_and_processes(monkeypatch):
    secret = "webhook-secret"
    provider_payment_id = "164726173751"
    x_request_id = "request-123"
    timestamp = "1719191332"
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_WEBHOOK_SECRET", secret)
    processed = {"called": False}

    async def fake_process(self, payload):
        processed["called"] = True

    monkeypatch.setattr(MercadoPagoPixPaymentService, "process_mercado_pago_webhook", fake_process)

    response = await mercado_pago_webhook(
        FakeRequest(
            {"type": "payment", "data": {"id": provider_payment_id}},
            headers={
                "x-request-id": x_request_id,
                "x-signature": build_signature(
                    secret=secret,
                    provider_payment_id=provider_payment_id,
                    x_request_id=x_request_id,
                    timestamp=timestamp,
                ),
            },
        ),
        db=SimpleNamespace(),
    )

    assert response.received is True
    assert processed["called"] is True


@pytest.mark.asyncio
async def test_webhook_with_invalid_signature_rejects_and_does_not_process(monkeypatch):
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_WEBHOOK_SECRET", "webhook-secret")
    processed = {"called": False}

    async def fake_process(self, payload):
        processed["called"] = True

    monkeypatch.setattr(MercadoPagoPixPaymentService, "process_mercado_pago_webhook", fake_process)

    with pytest.raises(HTTPException) as exc_info:
        await mercado_pago_webhook(
            FakeRequest(
                {"type": "payment", "data": {"id": "164726173751"}},
                headers={
                    "x-request-id": "request-123",
                    "x-signature": "ts=1719191332,v1=invalid",
                },
            ),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 401
    assert processed["called"] is False
