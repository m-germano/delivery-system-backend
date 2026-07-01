import re
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
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

    async def rollback(self):
        return None

    async def refresh(self, instance):
        return None

    async def flush(self):
        return None


class FakeAccountRepository:
    def __init__(self, account=None, accounts=None):
        self.account = account
        self.accounts = accounts if accounts is not None else ([account] if account else [])

    async def get_active_by_company_and_provider(self, company_id, provider):
        if self.account and self.account.company_id == company_id and self.account.provider == provider and self.account.is_active:
            return self.account
        return None

    async def list_active_by_provider(self, provider):
        return [account for account in self.accounts if account and account.provider == provider and account.is_active]


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

    async def get_by_id(self, payment_id):
        if self.latest_payment and self.latest_payment.id == payment_id:
            return self.latest_payment
        return None

    async def get_by_id_and_order(self, payment_id, order_id):
        if self.latest_payment and self.latest_payment.id == payment_id and self.latest_payment.order_id == order_id:
            return self.latest_payment
        return None

    async def get_latest_online_by_order(self, order_id):
        if self.latest_payment and self.latest_payment.order_id == order_id:
            return self.latest_payment
        return None

    async def get_latest_pix_by_order(self, order_id):
        return await self.get_latest_online_by_order(order_id)

    async def get_by_provider_payment_id(self, provider_payment_id):
        if self.latest_payment and self.latest_payment.provider_payment_id == str(provider_payment_id):
            return self.latest_payment
        return None

    async def get_by_provider_order_id(self, provider_order_id):
        if self.latest_payment and self.latest_payment.provider_order_id == str(provider_order_id):
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


def make_pending_checkout_payment(**overrides):
    payload = {
        "id": 1,
        "order_id": 10,
        "company_id": 1,
        "provider": "mercado_pago",
        "status": PaymentStatus.PENDING.value,
        "provider_payment_id": None,
        "provider_order_id": "pref-123",
        "provider_status": "preference_created",
        "provider_status_detail": None,
        "raw_status": "preference_created",
        "raw_status_detail": None,
        "raw_response": {
            "preference": {
                "id": "pref-123",
                "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-123",
                "sandbox_init_point": "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-123",
            }
        },
        "qr_code": None,
        "qr_code_base64": None,
        "paid_at": None,
        "refunded_at": None,
        "cancelled_at": None,
        "failed_at": None,
        "payment_method": "pix",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.mark.asyncio
async def test_pix_unavailable_when_company_has_no_active_mercado_pago_account():
    service = MercadoPagoPixPaymentService(FakeSession())
    service.account_repository = FakeAccountRepository(account=None)

    assert await service.is_pix_available_for_company(1) is False
    assert await service.is_checkout_pro_available_for_company(1) is False


@pytest.mark.asyncio
async def test_create_pix_payment_for_order_with_connected_company_creates_checkout_pro_preference(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, total=Decimal("42.50"))
    payer = SimpleNamespace(id=99, name="Cliente Teste", email="cliente@example.com")
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")
    captured_payload = {}

    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.FRONTEND_BASE_URL", "https://frontend.test")
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_CHECKOUT_SUCCESS_URL", None)
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_CHECKOUT_FAILURE_URL", None)
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_CHECKOUT_PENDING_URL", None)
    monkeypatch.setattr(
        "app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_WEBHOOK_URL",
        "https://backend.test/api/payments/mercado-pago/webhook",
    )

    service = MercadoPagoPixPaymentService(FakeSession())
    service.account_repository = FakeAccountRepository(account=account)
    service.payment_repository = FakePaymentRepository()

    async def fake_create_mp_preference(account, payload, *, idempotency_key):
        captured_payload.update(payload)

        assert payload["external_reference"] == str(order.id)
        assert payload["metadata"] == {
            "order_id": order.id,
            "company_id": order.company_id,
            "local_payment_id": 1,
        }
        assert payload["items"] == [
            {
                "id": str(order.id),
                "title": f"Pedido #{order.id}",
                "description": "Pedido realizado no DishDash",
                "quantity": 1,
                "unit_price": 42.5,
                "currency_id": "BRL",
            }
        ]
        assert payload["payer"] == {
            "email": "cliente@example.com",
            "name": "Cliente",
            "surname": "Teste",
        }
        assert payload["back_urls"] == {
            "success": "https://frontend.test/checkout/pix/10?mp_result=success",
            "failure": "https://frontend.test/checkout/pix/10?mp_result=failure",
            "pending": "https://frontend.test/checkout/pix/10?mp_result=pending",
        }
        assert payload["auto_return"] == "approved"
        assert payload["expires"] is True
        assert payload["statement_descriptor"] == "DISHDASH"

        expiration = datetime.fromisoformat(payload["expiration_date_to"])
        assert expiration.tzinfo is not None
        assert expiration.utcoffset() is not None
        assert expiration > datetime.now(ZoneInfo("America/Sao_Paulo"))
        assert payload["expiration_date_to"] == expiration.isoformat(timespec="milliseconds")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}-\d{2}:\d{2}$", payload["expiration_date_to"])
        assert payload["expiration_date_to"].endswith(".000-03:00")
        assert "UTC" not in payload["expiration_date_to"]
        assert not re.match(r"^\d{2}-\d{2}-\d{4}T", payload["expiration_date_to"])

        parsed_notification_url = urlparse(payload["notification_url"])
        parsed_query = parse_qs(parsed_notification_url.query)
        assert parsed_notification_url.scheme == "https"
        assert parsed_notification_url.netloc == "backend.test"
        assert parsed_query["order_id"] == ["10"]
        assert parsed_query["local_payment_id"] == ["1"]

        assert idempotency_key.startswith("order-10-checkout-pro-")
        return {
            "id": "1639933473-pref-test",
            "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=1639933473-pref-test",
            "sandbox_init_point": "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=1639933473-pref-test",
        }

    monkeypatch.setattr(service, "_create_mercado_pago_preference", fake_create_mp_preference)

    payment = await service.create_pix_payment_for_order(order, payer)

    assert payment.order_id == order.id
    assert payment.company_id == order.company_id
    assert payment.payment_method == "pix"
    assert payment.status == PaymentStatus.PENDING.value
    assert payment.provider_payment_id is None
    assert payment.provider_order_id == "1639933473-pref-test"
    assert payment.checkout_preference_id == "1639933473-pref-test"
    assert payment.checkout_url == "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=1639933473-pref-test"
    assert payment.sandbox_checkout_url == "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=1639933473-pref-test"
    assert payment.qr_code is None
    assert payment.qr_code_base64 is None
    assert payment.expires_at.isoformat(timespec="milliseconds") == captured_payload["expiration_date_to"]


def test_format_mercado_pago_expiration_uses_iso_year_first_with_offset():
    expires_at = datetime(2026, 6, 24, 2, 57, 52, tzinfo=ZoneInfo("America/Sao_Paulo"))

    date_of_expiration = MercadoPagoPixPaymentService._format_mercado_pago_expiration(expires_at)

    assert date_of_expiration == "2026-06-24T02:57:52.000-03:00"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}-\d{2}:\d{2}$", date_of_expiration)
    assert date_of_expiration.endswith(".000-03:00")
    assert "UTC" not in date_of_expiration
    assert not re.match(r"^\d{2}-\d{2}-\d{4}T", date_of_expiration)


def test_checkout_expiration_uses_sao_paulo_timezone_and_minimum_30_minutes(monkeypatch):
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_CHECKOUT_EXPIRATION_MINUTES", 5)
    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_PIX_EXPIRATION_MINUTES", 5)

    before = datetime.now(ZoneInfo("America/Sao_Paulo"))
    expires_at = MercadoPagoPixPaymentService._build_checkout_expiration_datetime()
    after = datetime.now(ZoneInfo("America/Sao_Paulo"))

    assert expires_at.tzinfo is not None
    assert expires_at.utcoffset() is not None
    assert expires_at.isoformat().endswith("-03:00")
    assert expires_at > after
    assert (expires_at - before).total_seconds() >= 30 * 60 - 1
    assert (expires_at - after).total_seconds() <= 30 * 60 + 1


def test_build_checkout_preference_payload_sends_notification_url_and_back_urls_when_configured(monkeypatch):
    monkeypatch.setattr(
        "app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_WEBHOOK_URL",
        "https://example.com/api/payments/mercado-pago/webhook",
    )
    monkeypatch.setattr(
        "app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_CHECKOUT_SUCCESS_URL",
        "https://example.com/api/payments/mercado-pago/checkout-return?order_id={order_id}&mp_result=success",
    )
    monkeypatch.setattr(
        "app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_CHECKOUT_FAILURE_URL",
        "https://example.com/api/payments/mercado-pago/checkout-return?order_id={order_id}&mp_result=failure",
    )
    monkeypatch.setattr(
        "app.services.mercado_pago_pix_payment_service.settings.MERCADO_PAGO_CHECKOUT_PENDING_URL",
        "https://example.com/api/payments/mercado-pago/checkout-return?order_id={order_id}&mp_result=pending",
    )

    service = MercadoPagoPixPaymentService(FakeSession())
    order = SimpleNamespace(id=10, company_id=1, total=Decimal("42.50"))
    payer = SimpleNamespace(name="Cliente Teste", email="cliente@example.com")
    payment = SimpleNamespace(id=15)
    expires_at = datetime(2026, 6, 24, 3, 8, 42, tzinfo=ZoneInfo("America/Sao_Paulo"))

    payload = service._build_checkout_preference_payload(order, payer, payment, expires_at)
    sanitized_payload = service._sanitize_checkout_preference_payload_for_log(payload)
    parsed_notification_url = urlparse(payload["notification_url"])
    parsed_query = parse_qs(parsed_notification_url.query)

    assert payload["notification_url"].startswith("https://example.com/api/payments/mercado-pago/webhook?")
    assert parsed_query["order_id"] == ["10"]
    assert parsed_query["local_payment_id"] == ["15"]
    assert payload["back_urls"] == {
        "success": "https://example.com/api/payments/mercado-pago/checkout-return?order_id=10&mp_result=success",
        "failure": "https://example.com/api/payments/mercado-pago/checkout-return?order_id=10&mp_result=failure",
        "pending": "https://example.com/api/payments/mercado-pago/checkout-return?order_id=10&mp_result=pending",
    }
    assert sanitized_payload["has_notification_url"] is True
    assert sanitized_payload["has_back_urls"] is True
    assert sanitized_payload["expiration_date_to"] == "2026-06-24T03:08:42.000-03:00"
    assert sanitized_payload["transaction_amount"] == 42.5
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
async def test_regenerate_pix_after_cancelled_payment_keeps_order_waiting_and_creates_new_checkout_link(monkeypatch):
    current_user = SimpleNamespace(id=7, name="Cliente Teste", email="cliente@example.com")
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, total=Decimal("42.50"))
    latest_payment = SimpleNamespace(
        id=1,
        order_id=10,
        company_id=1,
        status=PaymentStatus.CANCELLED.value,
        provider_payment_id="old-payment",
        provider_order_id="old-preference",
    )
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    service = MercadoPagoPixPaymentService(FakeSession())
    service.account_repository = FakeAccountRepository(account=account)
    service.payment_repository = FakePaymentRepository(latest_payment=latest_payment)

    async def fake_create_mp_preference(account, payload, *, idempotency_key):
        return {
            "id": "new-preference",
            "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=new-preference",
            "sandbox_init_point": "https://sandbox.mercadopago.com.br/checkout/v1/redirect?pref_id=new-preference",
        }

    monkeypatch.setattr(service, "_create_mercado_pago_preference", fake_create_mp_preference)

    new_payment = await service.regenerate_pix_payment_for_order(order, current_user)

    assert order.status == OrderStatus.PENDING_PAYMENT.value
    assert new_payment.id == 1
    assert new_payment.status == PaymentStatus.PENDING.value
    assert new_payment.provider_payment_id is None
    assert new_payment.provider_order_id == "new-preference"
    assert new_payment.checkout_url == "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=new-preference"
    assert new_payment.qr_code is None


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
    payment = make_pending_checkout_payment()
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "approved", "transaction_amount": "42.50", "external_reference": str(order.id)}

    async def fake_publish_company_order_event(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.mercado_pago_pix_payment_service.publish_company_order_event", fake_publish_company_order_event)

    service = MercadoPagoPixPaymentService(FakeSession())
    service.payment_repository = FakePaymentRepository(latest_payment=payment)
    service.order_repository = FakeOrderRepository(order)
    service.account_repository = FakeAccountRepository(account)
    monkeypatch.setattr(service, "_get_mercado_pago_payment", fake_get_mp_payment)

    await service.process_mercado_pago_webhook(
        {"type": "payment", "data": {"id": "164726173751"}},
        query_params={"local_payment_id": "1", "order_id": "10"},
    )

    assert payment.status == PaymentStatus.APPROVED.value
    assert payment.provider_status == "approved"
    assert payment.provider_payment_id == "164726173751"
    assert payment.paid_at is not None
    assert order.status == OrderStatus.OPEN.value


@pytest.mark.asyncio
async def test_payment_status_fallback_approved_releases_order(monkeypatch):
    order = SimpleNamespace(id=10, company_id=1, customer_user_id=7, status=OrderStatus.PENDING_PAYMENT.value, total=Decimal("42.50"))
    payment = make_pending_checkout_payment(provider_payment_id="164726173751", provider_status=PaymentStatus.PENDING.value)
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "approved", "transaction_amount": "42.50", "external_reference": str(order.id)}

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
    payment = make_pending_checkout_payment(provider_payment_id="164726173751", provider_status=PaymentStatus.PENDING.value)
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "pending", "transaction_amount": "42.50", "external_reference": str(order.id)}

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
    payment = make_pending_checkout_payment(provider_payment_id="164726173751", provider_status=PaymentStatus.PENDING.value)
    account = SimpleNamespace(company_id=1, provider="mercado_pago", is_active=True, access_token_encrypted="encrypted")

    async def fake_get_mp_payment(account, provider_payment_id):
        return {"id": provider_payment_id, "status": "approved", "transaction_amount": "41.00", "external_reference": str(order.id)}

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
