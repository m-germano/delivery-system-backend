import re
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.core.enums import OrderStatus, PaymentMethod, PaymentStatus, RoleId
from app.services.order_service import OrderService
from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, instance):
        self.added.append(instance)

    async def commit(self):
        return None

    async def refresh(self, instance):
        return None

    async def flush(self):
        return None


class FakeAccountRepository:
    def __init__(self, account=None):
        self.account = account

    async def get_active_by_company_and_provider(self, company_id, provider):
        if self.account and self.account.company_id == company_id and self.account.provider == provider and self.account.is_active:
            return self.account
        return None


class FakePaymentRepository:
    def __init__(self, latest_payment=None):
        self.latest_payment = latest_payment
        self.created_payment = None

    async def create(self, payment):
        payment.id = 1
        payment.created_at = datetime.utcnow()
        payment.updated_at = datetime.utcnow()
        self.created_payment = payment
        self.latest_payment = payment
        return payment

    async def get_latest_pix_by_order(self, order_id):
        if self.latest_payment and self.latest_payment.order_id == order_id:
            return self.latest_payment
        return None

    async def get_by_provider_payment_id(self, provider_payment_id):
        if self.latest_payment and self.latest_payment.provider_payment_id == provider_payment_id:
            return self.latest_payment
        return None


class FakeOrderRepository:
    def __init__(self, order=None):
        self.order = order

    async def get_by_id(self, order_id):
        if self.order and self.order.id == order_id:
            return self.order
        return None


def make_payment_for_refund(status_value=PaymentStatus.APPROVED.value):
    return SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        provider="mercado_pago",
        status=status_value,
        provider_payment_id="123456",
        provider_order_id=None,
        provider_status=status_value,
        provider_status_detail=None,
        raw_status=status_value,
        raw_status_detail=None,
        raw_response=None,
        qr_code=None,
        qr_code_base64=None,
        paid_at=None,
        refunded_at=None,
        cancelled_at=None,
        failed_at=None,
    )


@pytest.mark.asyncio
async def test_pix_unavailable_when_company_has_no_active_mercado_pago_account():
    service = MercadoPagoPixPaymentService(FakeSession())
    service.account_repository = FakeAccountRepository(account=None)

    assert await service.is_pix_available_for_company(1) is False


@pytest.mark.asyncio
async def test_create_pix_payment_for_order_with_connected_company(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, total=Decimal("42.50"))
    payer = SimpleNamespace(id=99, name="Cliente Teste", email="cliente@example.com")
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")
    captured_payload = {}

    service = MercadoPagoPixPaymentService(FakeSession())
    service.account_repository = FakeAccountRepository(account=account)
    service.payment_repository = FakePaymentRepository()

    async def fake_create_mp_payment(account, payload, *, idempotency_key):
        captured_payload.update(payload)
        assert payload["payment_method_id"] == "pix"
        assert payload["external_reference"] == str(order.id)
        assert payload["metadata"]["order_id"] == order.id
        expiration = datetime.fromisoformat(payload["date_of_expiration"])
        assert expiration.tzinfo is not None
        assert expiration.utcoffset() is not None
        assert expiration > datetime.now(ZoneInfo("America/Sao_Paulo"))
        assert payload["date_of_expiration"] == expiration.isoformat(timespec="milliseconds")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}-\d{2}:\d{2}$", payload["date_of_expiration"])
        assert payload["date_of_expiration"].endswith(".000-03:00")
        assert "UTC" not in payload["date_of_expiration"]
        assert not re.match(r"^\d{2}-\d{2}-\d{4}T", payload["date_of_expiration"])
        assert idempotency_key
        return {
            "id": 123456,
            "status": "pending",
            "status_detail": "pending_waiting_payment",
            "point_of_interaction": {
                "transaction_data": {
                    "qr_code": "000201-copy-paste",
                    "qr_code_base64": "base64-image",
                }
            },
        }

    monkeypatch.setattr(service, "_create_mercado_pago_payment", fake_create_mp_payment)

    payment = await service.create_pix_payment_for_order(order, payer)

    assert payment.order_id == order.id
    assert payment.company_id == order.company_id
    assert payment.payment_method == "pix"
    assert payment.status == PaymentStatus.PENDING.value
    assert payment.provider_payment_id == "123456"
    assert payment.qr_code == "000201-copy-paste"
    assert payment.qr_code_base64 == "base64-image"
    assert payment.expires_at.isoformat(timespec="milliseconds") == captured_payload["date_of_expiration"]


def test_format_mercado_pago_expiration_uses_iso_year_first_with_offset():
    expires_at = datetime(2026, 6, 24, 2, 57, 52, tzinfo=ZoneInfo("America/Sao_Paulo"))

    date_of_expiration = MercadoPagoPixPaymentService._format_mercado_pago_expiration(expires_at)

    assert date_of_expiration == "2026-06-24T02:57:52.000-03:00"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}-\d{2}:\d{2}$", date_of_expiration)
    assert date_of_expiration.endswith(".000-03:00")
    assert "UTC" not in date_of_expiration
    assert not re.match(r"^\d{2}-\d{2}-\d{4}T", date_of_expiration)


def test_pix_expiration_uses_sao_paulo_timezone_and_minimum_30_minutes(monkeypatch):
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_PIX_EXPIRATION_MINUTES", 5)

    before = datetime.now(ZoneInfo("America/Sao_Paulo"))
    expires_at = MercadoPagoPixPaymentService._build_pix_expiration_datetime()
    after = datetime.now(ZoneInfo("America/Sao_Paulo"))

    assert expires_at.tzinfo is not None
    assert expires_at.utcoffset() is not None
    assert expires_at.isoformat().endswith("-03:00")
    assert expires_at > after
    assert (expires_at - before).total_seconds() >= 30 * 60 - 1
    assert (expires_at - after).total_seconds() <= 30 * 60 + 1


def test_build_pix_payload_sends_notification_url_when_configured(monkeypatch):
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_WEBHOOK_URL", "https://example.com/api/payments/mercado-pago/webhook")
    service = MercadoPagoPixPaymentService(FakeSession())
    order = SimpleNamespace(id=10, company_id=1, total=Decimal("42.50"))
    payer = SimpleNamespace(name="Cliente Teste", email="cliente@example.com")
    expires_at = datetime(2026, 6, 24, 3, 8, 42, tzinfo=ZoneInfo("America/Sao_Paulo"))

    payload = service._build_pix_payload(order, payer, expires_at)
    sanitized_payload = service._sanitize_pix_create_payload_for_log(payload)

    assert payload["notification_url"] == "https://example.com/api/payments/mercado-pago/webhook"
    assert sanitized_payload["has_notification_url"] is True
    assert sanitized_payload["date_of_expiration"] == "2026-06-24T03:08:42.000-03:00"
    assert sanitized_payload["transaction_amount"] == 42.5
    assert sanitized_payload["payment_method_id"] == "pix"
    assert sanitized_payload["external_reference"] == "10"
    assert sanitized_payload["has_payer_email"] is True


@pytest.mark.asyncio
async def test_approved_payment_releases_order_to_open_status():
    service = MercadoPagoPixPaymentService(FakeSession())
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value)
    payment = SimpleNamespace(status=PaymentStatus.APPROVED.value)

    await service._apply_order_status_from_payment(order, payment)

    assert order.status == OrderStatus.OPEN.value


@pytest.mark.asyncio
async def test_cancel_pending_pix_payment_does_not_cancel_order():
    current_user = SimpleNamespace(id=7)
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value)
    payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        status=PaymentStatus.PENDING.value,
        provider_payment_id=None,
        provider_status=None,
        raw_status=None,
        cancelled_at=None,
    )

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)

    cancelled_payment = await service.cancel_pending_pix_payment(order, current_user)

    assert cancelled_payment.status == PaymentStatus.CANCELLED.value
    assert cancelled_payment.provider_status == PaymentStatus.CANCELLED.value
    assert cancelled_payment.cancelled_at is not None
    assert order.status == OrderStatus.PENDING_PAYMENT.value


@pytest.mark.asyncio
async def test_regenerate_pix_after_cancelled_payment_keeps_order_waiting_and_creates_new_payment(monkeypatch):
    current_user = SimpleNamespace(id=7, name="Cliente Teste", email="cliente@example.com")
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, total=Decimal("42.50"))
    latest_payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        status=PaymentStatus.CANCELLED.value,
        provider_payment_id="old-payment",
    )
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    service = MercadoPagoPixPaymentService(FakeSession())
    service.account_repository = FakeAccountRepository(account=account)
    service.payment_repository = FakePaymentRepository(latest_payment=latest_payment)

    async def fake_create_mp_payment(account, payload, *, idempotency_key):
        return {
            "id": 222,
            "status": "pending",
            "point_of_interaction": {
                "transaction_data": {
                    "qr_code": "new-copy-paste",
                    "qr_code_base64": "new-base64-image",
                }
            },
        }

    monkeypatch.setattr(service, "_create_mercado_pago_payment", fake_create_mp_payment)

    new_payment = await service.regenerate_pix_payment_for_order(order, current_user)

    assert order.status == OrderStatus.PENDING_PAYMENT.value
    assert new_payment.id == 1
    assert new_payment.status == PaymentStatus.PENDING.value
    assert new_payment.provider_payment_id == "222"
    assert new_payment.qr_code == "new-copy-paste"


@pytest.mark.asyncio
async def test_switch_to_delivery_after_cancelled_pix_payment_releases_order(monkeypatch):
    current_user = SimpleNamespace(id=7)
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, payment_method=PaymentMethod.PIX_ONLINE.value)
    latest_payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        status=PaymentStatus.CANCELLED.value,
        provider_payment_id="old-payment",
        cancelled_at=datetime.utcnow(),
    )

    async def fake_publish_company_order_event(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.publish_company_order_event", fake_publish_company_order_event)

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=latest_payment)

    updated_order = await service.switch_pending_order_to_pay_on_delivery(order, current_user)

    assert updated_order.status == OrderStatus.OPEN.value
    assert updated_order.payment_method == "PIX"


@pytest.mark.asyncio
async def test_cancel_order_by_customer_still_cancels_whole_order(monkeypatch):
    current_user = SimpleNamespace(id=7, role_id=RoleId.CUSTOMER)
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value)

    async def fake_get_order_or_404(order_id):
        return order

    async def fake_get_visible_order(order_id, user):
        return order

    async def fake_publish_company_order_event(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.order_service.publish_company_order_event", fake_publish_company_order_event)

    service = OrderService(FakeSession())
    monkeypatch.setattr(service, "_get_order_or_404", fake_get_order_or_404)
    monkeypatch.setattr(service, "_get_visible_order", fake_get_visible_order)

    cancelled_order = await service.cancel_order_by_customer(order.id, current_user)

    assert cancelled_order.status == OrderStatus.CANCELED.value


@pytest.mark.asyncio
async def test_cannot_regenerate_pix_when_order_is_cancelled():
    current_user = SimpleNamespace(id=7)
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.CANCELED.value)
    payment = SimpleNamespace(id=1, order_id=10, company_id=1, status=PaymentStatus.CANCELLED.value)

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)

    with pytest.raises(HTTPException, match="aguarda pagamento"):
        await service.regenerate_pix_payment_for_order(order, current_user)


@pytest.mark.asyncio
async def test_cannot_switch_to_delivery_when_order_is_cancelled():
    current_user = SimpleNamespace(id=7)
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.CANCELED.value)
    payment = SimpleNamespace(id=1, order_id=10, company_id=1, status=PaymentStatus.CANCELLED.value)

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)

    with pytest.raises(HTTPException, match="aguarda pagamento"):
        await service.switch_pending_order_to_pay_on_delivery(order, current_user)


@pytest.mark.asyncio
async def test_cannot_regenerate_or_switch_when_payment_is_approved():
    current_user = SimpleNamespace(id=7)
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value)
    payment = SimpleNamespace(id=1, order_id=10, company_id=1, status=PaymentStatus.APPROVED.value)

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)

    with pytest.raises(HTTPException, match="Pagamento já aprovado"):
        await service.regenerate_pix_payment_for_order(order, current_user)

    with pytest.raises(HTTPException, match="Pagamento já aprovado"):
        await service.switch_pending_order_to_pay_on_delivery(order, current_user)


def test_payment_action_flags_after_cancelled_pix_payment():
    order = SimpleNamespace(id=10, status=OrderStatus.PENDING_PAYMENT.value)
    payment = SimpleNamespace(status=PaymentStatus.CANCELLED.value)

    flags = MercadoPagoPixPaymentService.get_payment_action_flags(order, payment)

    assert flags == {
        "can_cancel_payment": False,
        "can_regenerate_pix": True,
        "can_switch_to_delivery": True,
        "can_cancel_order": True,
    }


@pytest.mark.asyncio
async def test_webhook_approved_updates_payment_and_releases_order(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, total=Decimal("42.50"))
    payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        provider="mercado_pago",
        status=PaymentStatus.PENDING.value,
        provider_payment_id="164726173751",
        provider_order_id=None,
        provider_status=PaymentStatus.PENDING.value,
        provider_status_detail=None,
        raw_status=None,
        raw_status_detail=None,
        raw_response=None,
        qr_code=None,
        qr_code_base64=None,
        paid_at=None,
    )
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "approved", "transaction_amount": "42.50"}

    async def fake_publish_company_order_event(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.publish_company_order_event", fake_publish_company_order_event)

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)
    service.order_repository = FakeOrderRepository(order)
    service.account_repository = FakeAccountRepository(account)
    monkeypatch.setattr(service, "_get_mercado_pago_payment", fake_get_mp_payment)

    await service.process_mercado_pago_webhook({"data": {"id": "164726173751"}})

    assert payment.status == PaymentStatus.APPROVED.value
    assert payment.provider_status == "approved"
    assert payment.paid_at is not None
    assert order.status == OrderStatus.OPEN.value


@pytest.mark.asyncio
async def test_payment_status_fallback_approved_releases_order(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, total=Decimal("42.50"))
    payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        provider="mercado_pago",
        status=PaymentStatus.PENDING.value,
        provider_payment_id="164726173751",
        provider_order_id=None,
        provider_status=PaymentStatus.PENDING.value,
        provider_status_detail=None,
        raw_status=None,
        raw_status_detail=None,
        raw_response=None,
        qr_code=None,
        qr_code_base64=None,
        paid_at=None,
    )
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "approved", "transaction_amount": "42.50"}

    async def fake_publish_company_order_event(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.publish_company_order_event", fake_publish_company_order_event)

    service = MercadoPagoPixPaymentService(FakeSession())
    service.order_repository = FakeOrderRepository(order)
    service.account_repository = FakeAccountRepository(account)
    monkeypatch.setattr(service, "_get_mercado_pago_payment", fake_get_mp_payment)

    refreshed_payment = await service.refresh_payment_from_provider(payment)

    assert refreshed_payment.status == PaymentStatus.APPROVED.value
    assert order.status == OrderStatus.OPEN.value


@pytest.mark.asyncio
async def test_payment_status_fallback_pending_keeps_pending(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, total=Decimal("42.50"))
    payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        provider="mercado_pago",
        status=PaymentStatus.PENDING.value,
        provider_payment_id="164726173751",
        provider_order_id=None,
        provider_status=PaymentStatus.PENDING.value,
        provider_status_detail=None,
        raw_status=None,
        raw_status_detail=None,
        raw_response=None,
        qr_code=None,
        qr_code_base64=None,
        paid_at=None,
    )
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "pending", "transaction_amount": "42.50"}

    service = MercadoPagoPixPaymentService(FakeSession())
    service.order_repository = FakeOrderRepository(order)
    service.account_repository = FakeAccountRepository(account)
    monkeypatch.setattr(service, "_get_mercado_pago_payment", fake_get_mp_payment)

    refreshed_payment = await service.refresh_payment_from_provider(payment)

    assert refreshed_payment.status == PaymentStatus.PENDING.value
    assert order.status == OrderStatus.PENDING_PAYMENT.value


@pytest.mark.asyncio
async def test_approved_payment_with_amount_mismatch_does_not_release_order(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, total=Decimal("42.50"))
    payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        provider="mercado_pago",
        status=PaymentStatus.PENDING.value,
        provider_payment_id="164726173751",
        provider_order_id=None,
        provider_status=PaymentStatus.PENDING.value,
        provider_status_detail=None,
        raw_status=None,
        raw_status_detail=None,
        raw_response=None,
        qr_code=None,
        qr_code_base64=None,
        paid_at=None,
    )
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "approved", "transaction_amount": "41.00"}

    service = MercadoPagoPixPaymentService(FakeSession())
    service.order_repository = FakeOrderRepository(order)
    service.account_repository = FakeAccountRepository(account)
    monkeypatch.setattr(service, "_get_mercado_pago_payment", fake_get_mp_payment)

    refreshed_payment = await service.refresh_payment_from_provider(payment)

    assert refreshed_payment.provider_status == "approved"
    assert refreshed_payment.status == PaymentStatus.PENDING.value
    assert refreshed_payment.paid_at is None
    assert order.status == OrderStatus.PENDING_PAYMENT.value


@pytest.mark.asyncio
async def test_cannot_cancel_approved_pix_payment():
    current_user = SimpleNamespace(id=7)
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value)
    payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        status=PaymentStatus.APPROVED.value,
        provider_payment_id="123",
    )

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)

    with pytest.raises(HTTPException, match="Pagamento aprovado"):
        await service.cancel_pending_pix_payment(order, current_user)


@pytest.mark.asyncio
async def test_rejecting_approved_pix_payment_refunds_payment(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, payment_method=PaymentMethod.PIX_ONLINE.value)
    payment = make_payment_for_refund(PaymentStatus.APPROVED.value)
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")
    captured = {"refund_calls": 0}

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)
    service.account_repository = FakeAccountRepository(account)

    async def fake_refund(account, provider_payment_id):
        captured["refund_calls"] += 1
        assert provider_payment_id == "123456"
        return {"id": "refund-1", "status": "approved"}

    monkeypatch.setattr(service, "_refund_mercado_pago_payment", fake_refund)

    result = await service.handle_order_rejected_by_company(order)

    assert result == "refunded"
    assert captured["refund_calls"] == 1
    assert payment.status == PaymentStatus.REFUNDED.value
    assert payment.provider_status == "approved"
    assert payment.refunded_at is not None
    assert payment.raw_response["refund"]["id"] == "refund-1"


@pytest.mark.asyncio
async def test_rejecting_already_refunded_pix_payment_is_idempotent(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, payment_method=PaymentMethod.PIX_ONLINE.value)
    payment = make_payment_for_refund(PaymentStatus.REFUNDED.value)
    captured = {"refund_calls": 0}

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)

    async def fake_refund(account, provider_payment_id):
        captured["refund_calls"] += 1
        return {"id": "refund-1", "status": "approved"}

    monkeypatch.setattr(service, "_refund_mercado_pago_payment", fake_refund)

    result = await service.handle_order_rejected_by_company(order)

    assert result == "already_refunded"
    assert captured["refund_calls"] == 0
    assert payment.status == PaymentStatus.REFUNDED.value


@pytest.mark.asyncio
async def test_rejecting_pending_pix_payment_cancels_without_refund(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, payment_method=PaymentMethod.PIX_ONLINE.value)
    payment = make_payment_for_refund(PaymentStatus.PENDING.value)
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")
    captured = {"refund_calls": 0, "cancel_calls": 0}

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)
    service.account_repository = FakeAccountRepository(account)

    async def fake_refund(account, provider_payment_id):
        captured["refund_calls"] += 1
        return {"id": "refund-1", "status": "approved"}

    async def fake_cancel(account, provider_payment_id):
        captured["cancel_calls"] += 1
        return {"id": provider_payment_id, "status": "cancelled"}

    monkeypatch.setattr(service, "_refund_mercado_pago_payment", fake_refund)
    monkeypatch.setattr(service, "_cancel_mercado_pago_payment", fake_cancel)

    result = await service.handle_order_rejected_by_company(order)

    assert result == "cancelled_pending"
    assert captured["refund_calls"] == 0
    assert captured["cancel_calls"] == 1
    assert payment.status == PaymentStatus.CANCELLED.value
    assert payment.refunded_at is None


@pytest.mark.asyncio
async def test_failed_refund_does_not_mark_payment_as_refunded(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, payment_method=PaymentMethod.PIX_ONLINE.value)
    payment = make_payment_for_refund(PaymentStatus.APPROVED.value)
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)
    service.account_repository = FakeAccountRepository(account)

    async def fake_refund(account, provider_payment_id):
        raise HTTPException(status_code=502, detail="Falha de reembolso")

    monkeypatch.setattr(service, "_refund_mercado_pago_payment", fake_refund)

    with pytest.raises(HTTPException, match="Falha de reembolso"):
        await service.handle_order_rejected_by_company(order)

    assert payment.status == PaymentStatus.APPROVED.value
    assert payment.refunded_at is None


@pytest.mark.asyncio
async def test_rejecting_non_online_order_does_not_call_mercado_pago(monkeypatch):
    current_user = SimpleNamespace(id=99, role_id=RoleId.COMPANY)
    order = SimpleNamespace(
        id=10,
        company_id=1,
        customer_user_id=7,
        status=OrderStatus.OPEN.value,
        payment_method=PaymentMethod.PIX.value,
    )
    company = SimpleNamespace(id=1)
    captured = {"changed": False}

    service = OrderService(FakeSession())

    async def fake_get_order_or_404(order_id):
        return order

    async def fake_get_by_owner_user_id(user_id):
        return company

    async def fake_change(order_id, new_status, user):
        captured["changed"] = True
        assert new_status == OrderStatus.REJECTED.value
        order.status = new_status
        return order

    monkeypatch.setattr(service, "_get_order_or_404", fake_get_order_or_404)
    monkeypatch.setattr(service.company_repository, "get_by_owner_user_id", fake_get_by_owner_user_id)
    monkeypatch.setattr(service, "_change_company_order_status", fake_change)

    rejected_order = await service.reject_order(order.id, current_user)

    assert captured["changed"] is True
    assert rejected_order.status == OrderStatus.REJECTED.value


def make_company_order(status_value=OrderStatus.ACCEPTED.value, payment_method=PaymentMethod.PIX.value):
    return SimpleNamespace(
        id=10,
        company_id=1,
        customer_user_id=7,
        status=status_value,
        payment_method=payment_method,
        delivery=None,
    )


async def _noop_publish(*args, **kwargs):
    return None


def prepare_company_order_service(monkeypatch, order):
    current_user = SimpleNamespace(id=99, role_id=RoleId.COMPANY)
    company = SimpleNamespace(id=1)
    service = OrderService(FakeSession())

    async def fake_get_order_or_404(order_id):
        return order

    async def fake_get_by_owner_user_id(user_id):
        return company

    async def fake_get_visible_order(order_id, user):
        return order

    async def fake_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "_get_order_or_404", fake_get_order_or_404)
    monkeypatch.setattr(service.company_repository, "get_by_owner_user_id", fake_get_by_owner_user_id)
    monkeypatch.setattr(service, "_get_visible_order", fake_get_visible_order)
    monkeypatch.setattr(service, "_broadcast_tracking_snapshot", fake_broadcast)
    monkeypatch.setattr("app.services.order_service.publish_company_order_event", _noop_publish)
    monkeypatch.setattr("app.services.order_service.publish_courier_delivery_event", _noop_publish)

    return service, current_user


@pytest.mark.asyncio
async def test_company_cannot_cancel_order_before_accepting(monkeypatch):
    order = make_company_order(status_value=OrderStatus.OPEN.value)
    service, current_user = prepare_company_order_service(monkeypatch, order)

    with pytest.raises(HTTPException) as exc_info:
        await service.cancel_order_by_company(order.id, current_user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Pedido ainda não foi aceito. Use a opção de recusar."


@pytest.mark.asyncio
async def test_company_cannot_reject_already_accepted_order(monkeypatch):
    order = make_company_order(status_value=OrderStatus.ACCEPTED.value)
    service, current_user = prepare_company_order_service(monkeypatch, order)

    with pytest.raises(HTTPException) as exc_info:
        await service.reject_order(order.id, current_user)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Pedido já foi aceito. Use a opção de cancelar."


@pytest.mark.asyncio
async def test_company_can_cancel_accepted_order_without_online_payment(monkeypatch):
    order = make_company_order(status_value=OrderStatus.ACCEPTED.value, payment_method=PaymentMethod.PIX.value)
    service, current_user = prepare_company_order_service(monkeypatch, order)
    captured = {"refund_calls": 0}

    async def fake_refund(self, order):
        captured["refund_calls"] += 1

    monkeypatch.setattr(MercadoPagoPixPaymentService, "handle_order_cancelled_by_company", fake_refund)

    cancelled_order = await service.cancel_order_by_company(order.id, current_user)

    assert cancelled_order.status == OrderStatus.CANCELED.value
    assert captured["refund_calls"] == 0


@pytest.mark.asyncio
async def test_company_cancel_accepted_pix_online_calls_refund(monkeypatch):
    order = make_company_order(status_value=OrderStatus.ACCEPTED.value, payment_method=PaymentMethod.PIX_ONLINE.value)
    service, current_user = prepare_company_order_service(monkeypatch, order)
    captured = {"refund_calls": 0}

    async def fake_refund(self, received_order):
        captured["refund_calls"] += 1
        assert received_order is order
        return "refunded"

    monkeypatch.setattr(MercadoPagoPixPaymentService, "handle_order_cancelled_by_company", fake_refund)

    cancelled_order = await service.cancel_order_by_company(order.id, current_user)

    assert cancelled_order.status == OrderStatus.CANCELED.value
    assert getattr(cancelled_order, "refund_result") == "refunded"
    assert captured["refund_calls"] == 1


@pytest.mark.asyncio
async def test_company_cancel_refund_failure_does_not_cancel_order(monkeypatch):
    order = make_company_order(status_value=OrderStatus.ACCEPTED.value, payment_method=PaymentMethod.PIX_ONLINE.value)
    service, current_user = prepare_company_order_service(monkeypatch, order)

    async def fake_refund(self, received_order):
        raise HTTPException(status_code=502, detail="Falha de reembolso")

    monkeypatch.setattr(MercadoPagoPixPaymentService, "handle_order_cancelled_by_company", fake_refund)

    with pytest.raises(HTTPException) as exc_info:
        await service.cancel_order_by_company(order.id, current_user)

    assert exc_info.value.status_code == 502
    assert order.status == OrderStatus.ACCEPTED.value


@pytest.mark.asyncio
async def test_company_cancel_twice_does_not_refund_again(monkeypatch):
    order = make_company_order(status_value=OrderStatus.CANCELED.value, payment_method=PaymentMethod.PIX_ONLINE.value)
    service, current_user = prepare_company_order_service(monkeypatch, order)
    captured = {"refund_calls": 0}

    async def fake_refund(self, received_order):
        captured["refund_calls"] += 1
        return "refunded"

    monkeypatch.setattr(MercadoPagoPixPaymentService, "handle_order_cancelled_by_company", fake_refund)

    cancelled_order = await service.cancel_order_by_company(order.id, current_user)

    assert cancelled_order.status == OrderStatus.CANCELED.value
    assert captured["refund_calls"] == 0
