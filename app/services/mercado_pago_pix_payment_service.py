import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.core.enums import OrderStatus, PaymentAccountProvider, PaymentProvider, PaymentStatus, PaymentTransactionMethod
from app.models import CompanyPaymentAccount, Order, OrderStatusHistory, Payment, User
from app.repositories.company_payment_account_repository import CompanyPaymentAccountRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_repository import PaymentRepository
from app.services.company_payment_account_service import _sanitize_for_log
from app.services.realtime_service import RealtimeEventType, publish_company_order_event

logger = logging.getLogger(__name__)

MERCADO_PAGO_PIX_TIMEZONE = ZoneInfo("America/Sao_Paulo")
MIN_CHECKOUT_EXPIRATION_MINUTES = 30
MERCADO_PAGO_APPROVED_STATUSES = {"approved"}
MERCADO_PAGO_PENDING_STATUSES = {"pending", "in_process", "authorized"}
MERCADO_PAGO_CANCELLED_STATUSES = {"cancelled", "canceled"}
MERCADO_PAGO_REJECTED_STATUSES = {"rejected"}
MERCADO_PAGO_EXPIRED_STATUS_DETAILS = {"expired", "cc_rejected_other_reason"}
PAYMENT_PENDING_STATUSES = {PaymentStatus.PENDING.value, PaymentStatus.IN_PROCESS.value}
PAYMENT_RETRYABLE_STATUSES = {
    PaymentStatus.CANCELLED.value,
    PaymentStatus.REJECTED.value,
    PaymentStatus.EXPIRED.value,
    PaymentStatus.FAILED.value,
}
TOKEN_REFRESH_SKEW_MINUTES = 5


class MercadoPagoPixPaymentService:
    """Serviço de pagamento online Mercado Pago.

    O nome foi mantido para não quebrar imports existentes, mas a criação de
    novos pagamentos online agora usa Checkout Pro (/checkout/preferences), não
    a cobrança Pix direta em /v1/payments.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.account_repository = CompanyPaymentAccountRepository(session)
        self.payment_repository = PaymentRepository(session)
        self.order_repository = OrderRepository(session)

    async def is_pix_available_for_company(self, company_id: int) -> bool:
        account = await self.account_repository.get_active_by_company_and_provider(
            company_id,
            PaymentAccountProvider.MERCADO_PAGO.value,
        )
        return account is not None

    async def is_checkout_pro_available_for_company(self, company_id: int) -> bool:
        return await self.is_pix_available_for_company(company_id)

    async def create_pix_payment_for_order(self, order: Order, payer: User) -> Payment:
        return await self.create_checkout_pro_payment_for_order(order, payer)

    async def create_checkout_pro_payment_for_order(self, order: Order, payer: User) -> Payment:
        account = await self._get_active_account_or_409(order.company_id)
        idempotency_key = f"order-{order.id}-checkout-pro-{uuid4()}"
        expires_at = self._build_checkout_expiration_datetime()

        payment = Payment(
            order_id=order.id,
            company_id=order.company_id,
            provider=PaymentProvider.MERCADO_PAGO.value,
            payment_method=PaymentTransactionMethod.PIX.value,
            status=PaymentStatus.PENDING.value,
            amount=order.total,
            currency="BRL",
            idempotency_key=idempotency_key,
            expires_at=expires_at,
        )
        await self.payment_repository.create(payment)

        preference_payload = self._build_checkout_preference_payload(order, payer, payment, expires_at)
        try:
            preference_data = await self._create_mercado_pago_preference(account, preference_payload, idempotency_key=idempotency_key)
        except HTTPException:
            await self.session.rollback()
            raise

        self._apply_preference_payload(payment, preference_data)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def cancel_pending_pix_payment(self, order: Order, current_user: User) -> Payment:
        self._ensure_customer_can_manage_order(order, current_user)
        self._ensure_order_is_waiting_for_payment(order)
        payment = await self._get_latest_online_or_404(order.id)

        if payment.status == PaymentStatus.APPROVED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pagamento aprovado não pode ser cancelado por esta rota.")

        if payment.status not in PAYMENT_PENDING_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Só é possível cancelar um pagamento online pendente.")

        if payment.status in PAYMENT_PENDING_STATUSES and payment.provider_payment_id:
            account = await self._get_active_account_or_409(payment.company_id)
            response_data = await self._cancel_mercado_pago_payment(account, payment.provider_payment_id)
            self._apply_provider_payload(payment, response_data)

        if payment.status != PaymentStatus.APPROVED.value:
            now = datetime.utcnow()
            payment.status = PaymentStatus.CANCELLED.value
            payment.provider_status = getattr(payment, "provider_status", None) or PaymentStatus.CANCELLED.value
            payment.raw_status = getattr(payment, "raw_status", None) or payment.provider_status
            payment.cancelled_at = payment.cancelled_at or now
            order.status = OrderStatus.PENDING_PAYMENT.value
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def regenerate_pix_payment_for_order(self, order: Order, current_user: User) -> Payment:
        return await self.regenerate_checkout_pro_payment_for_order(order, current_user)

    async def regenerate_checkout_pro_payment_for_order(self, order: Order, current_user: User) -> Payment:
        self._ensure_customer_can_manage_order(order, current_user)
        self._ensure_order_is_waiting_for_payment(order)

        latest_payment = await self.payment_repository.get_latest_online_by_order(order.id)
        if latest_payment and latest_payment.status in PAYMENT_PENDING_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um pagamento online pendente para este pedido.")
        if latest_payment and latest_payment.status == PaymentStatus.APPROVED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pagamento já aprovado.")
        if latest_payment and latest_payment.status not in PAYMENT_RETRYABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Status do pagamento não permite gerar novo link de pagamento.")

        return await self.create_checkout_pro_payment_for_order(order, current_user)

    async def switch_pending_order_to_pay_on_delivery(self, order: Order, current_user: User) -> Order:
        self._ensure_customer_can_manage_order(order, current_user)
        self._ensure_order_is_waiting_for_payment(order)

        latest_payment = await self.payment_repository.get_latest_online_by_order(order.id)
        if latest_payment and latest_payment.status == PaymentStatus.APPROVED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pagamento já aprovado.")
        if latest_payment and latest_payment.status not in PAYMENT_PENDING_STATUSES | PAYMENT_RETRYABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Status do pagamento não permite trocar para pagamento na entrega.")

        if latest_payment and latest_payment.status in PAYMENT_PENDING_STATUSES:
            latest_payment.status = PaymentStatus.CANCELLED.value
            latest_payment.provider_status = getattr(latest_payment, "provider_status", None) or PaymentStatus.CANCELLED.value
            latest_payment.raw_status = getattr(latest_payment, "raw_status", None) or latest_payment.provider_status
            latest_payment.cancelled_at = datetime.utcnow()

        order.payment_method = "PIX"
        order.status = OrderStatus.OPEN.value
        await self.session.commit()
        await publish_company_order_event(
            order.company_id,
            {
                "type": RealtimeEventType.ORDER_CREATED,
                "order_id": order.id,
                "company_id": order.company_id,
                "status": order.status,
                "message": f"Pedido #{order.id} liberado para preparo.",
            },
        )
        return order

    async def handle_order_rejected_by_company(self, order: Order) -> str:
        return await self.handle_order_closed_by_company(order, action_label="recusar")

    async def handle_order_cancelled_by_company(self, order: Order) -> str:
        return await self.handle_order_closed_by_company(order, action_label="cancelar")

    async def handle_order_closed_by_company(self, order: Order, *, action_label: str) -> str:
        payment = await self.payment_repository.get_latest_online_by_order(order.id)
        if payment is None or order.payment_method != "PIX_ONLINE":
            return "not_online"

        if payment.provider != PaymentProvider.MERCADO_PAGO.value:
            return "not_mercado_pago"

        if payment.status == PaymentStatus.REFUNDED.value:
            logger.info(
                "Pagamento já reembolsado ao %s pedido. order_id=%s payment_id=%s provider_payment_id=%s status=%s",
                action_label,
                order.id,
                payment.id,
                payment.provider_payment_id,
                payment.status,
            )
            return "already_refunded"

        if payment.status in PAYMENT_PENDING_STATUSES:
            await self._cancel_pending_payment_for_rejected_order(payment)
            return "cancelled_pending"

        if payment.status != PaymentStatus.APPROVED.value:
            return "not_approved"

        if not payment.provider_payment_id:
            logger.warning("Pagamento aprovado sem provider_payment_id para reembolso. order_id=%s payment_id=%s", order.id, payment.id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pedido pago online, mas não possui identificador do Mercado Pago para reembolso.",
            )

        account = await self._get_active_account_or_409(payment.company_id)
        logger.info(
            "Preparando reembolso Mercado Pago ao %s pedido. order_id=%s payment_id=%s provider_payment_id=%s",
            action_label,
            order.id,
            payment.id,
            payment.provider_payment_id,
        )
        refund_data = await self._refund_mercado_pago_payment(account, payment.provider_payment_id)
        self._apply_refund_payload(payment, refund_data)
        await self.session.flush()
        logger.info(
            "Pagamento reembolsado ao %s pedido. order_id=%s payment_id=%s provider_payment_id=%s refund_status=%s",
            action_label,
            order.id,
            payment.id,
            payment.provider_payment_id,
            payment.provider_status,
        )
        return "refunded"

    async def process_mercado_pago_webhook(self, payload: dict, *, query_params: Mapping[str, str] | None = None) -> None:
        if not self.is_supported_payment_webhook(payload, query_params=query_params):
            logger.info("Webhook Mercado Pago ignorado por não ser evento de pagamento. payload=%s", _sanitize_for_log(payload))
            return

        provider_payment_id = self._extract_provider_payment_id(payload, query_params=query_params)
        if not provider_payment_id:
            logger.info("Webhook Mercado Pago sem payment id reconhecido. payload=%s", _sanitize_for_log(payload))
            return

        payment = await self._find_local_payment_for_webhook(provider_payment_id, payload, query_params=query_params)
        if payment is None:
            logger.info("Webhook Mercado Pago sem pagamento local correspondente. provider_payment_id=%s", provider_payment_id)
            return

        account = await self._get_active_account_or_409(payment.company_id)
        response_data = await self._get_mercado_pago_payment(account, str(provider_payment_id))
        order = await self.order_repository.get_by_id(payment.order_id)

        can_apply_approval = self._can_apply_provider_approval(payment, order, response_data)
        self._apply_provider_payload(payment, response_data, can_apply_approval=can_apply_approval)
        if order is not None and can_apply_approval:
            await self._apply_order_status_from_payment(order, payment)
        await self.session.commit()

    async def _find_local_payment_for_webhook(
        self,
        provider_payment_id: str,
        payload: dict,
        *,
        query_params: Mapping[str, str] | None = None,
    ) -> Payment | None:
        local_payment_id = self._extract_local_payment_id(query_params=query_params)
        order_id_from_query = self._extract_order_id_from_query(query_params=query_params)

        if local_payment_id and order_id_from_query:
            payment = await self.payment_repository.get_by_id_and_order(local_payment_id, order_id_from_query)
            if payment is not None:
                return payment

        if local_payment_id:
            payment = await self.payment_repository.get_by_id(local_payment_id)
            if payment is not None:
                return payment

        payment = await self.payment_repository.get_by_provider_payment_id(str(provider_payment_id))
        if payment is not None:
            return payment

        if order_id_from_query:
            payment = await self.payment_repository.get_latest_online_by_order(order_id_from_query)
            if payment is not None:
                return payment

        response_data = await self._get_mercado_pago_payment_from_any_active_account(str(provider_payment_id))
        if response_data is None:
            return None

        provider_order_id = self._extract_provider_order_id(response_data)
        if provider_order_id:
            payment = await self.payment_repository.get_by_provider_order_id(provider_order_id)
            if payment is not None:
                return payment

        order_id = self._extract_order_id_from_provider_payload(response_data)
        if order_id is not None:
            return await self.payment_repository.get_latest_online_by_order(order_id)

        return None

    def validate_webhook_signature(
        self,
        payload: dict,
        *,
        query_params: Mapping[str, str] | None = None,
        x_signature: str | None,
        x_request_id: str | None,
    ) -> None:
        if not self.is_supported_payment_webhook(payload, query_params=query_params):
            return

        provider_payment_id = self._extract_provider_payment_id(payload, query_params=query_params)
        event_type = payload.get("type") or payload.get("topic") or payload.get("action") or (query_params or {}).get("topic")
        secret = str(settings.MERCADO_PAGO_WEBHOOK_SECRET or "").strip()

        if not secret:
            logger.warning(
                "Validação de assinatura do webhook Mercado Pago desativada. event_type=%s provider_payment_id=%s x_request_id=%s",
                event_type,
                provider_payment_id,
                x_request_id,
            )
            return

        if not provider_payment_id or not x_signature:
            logger.warning(
                "Webhook Mercado Pago com assinatura inválida. Motivo=missing_signature_data event_type=%s provider_payment_id=%s x_request_id=%s",
                event_type,
                provider_payment_id,
                x_request_id,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura do webhook inválida.")

        signature_parts = self._parse_mercado_pago_signature(x_signature)
        timestamp = signature_parts.get("ts")
        received_signature = signature_parts.get("v1")
        if not timestamp or not received_signature:
            logger.warning(
                "Webhook Mercado Pago com assinatura inválida. Motivo=malformed_signature event_type=%s provider_payment_id=%s x_request_id=%s",
                event_type,
                provider_payment_id,
                x_request_id,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura do webhook inválida.")

        self._ensure_webhook_timestamp_is_fresh(timestamp)

        expected_signature = self._build_mercado_pago_webhook_signature(
            secret=secret,
            provider_payment_id=str(provider_payment_id),
            x_request_id=x_request_id,
            timestamp=timestamp,
        )
        if not hmac.compare_digest(expected_signature, received_signature):
            logger.warning(
                "Webhook Mercado Pago com assinatura inválida. Motivo=signature_mismatch event_type=%s provider_payment_id=%s x_request_id=%s",
                event_type,
                provider_payment_id,
                x_request_id,
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura do webhook inválida.")

        logger.info(
            "Webhook Mercado Pago com assinatura validada. event_type=%s provider_payment_id=%s x_request_id=%s",
            event_type,
            provider_payment_id,
            x_request_id,
        )

    async def refresh_payment_from_provider(self, payment: Payment) -> Payment:
        if payment.provider != PaymentProvider.MERCADO_PAGO.value:
            logger.info("Ignorando refresh de pagamento de provider não suportado. payment_id=%s provider=%s", payment.id, payment.provider)
            return payment

        account = await self._get_active_account_or_409(payment.company_id)
        order = await self.order_repository.get_by_id(payment.order_id)

        response_data = None
        if payment.provider_payment_id:
            response_data = await self._get_mercado_pago_payment(account, payment.provider_payment_id)
        else:
            response_data = await self._search_latest_mercado_pago_payment_for_order(account, payment.order_id)

        if response_data is None:
            await self.session.refresh(payment)
            return payment

        can_apply_approval = self._can_apply_provider_approval(payment, order, response_data)
        self._apply_provider_payload(payment, response_data, can_apply_approval=can_apply_approval)
        if order is not None and can_apply_approval:
            await self._apply_order_status_from_payment(order, payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    def _build_checkout_preference_payload(self, order: Order, payer: User, payment: Payment, expires_at: datetime) -> dict:
        payload = {
            "items": [
                {
                    "id": str(order.id),
                    "title": f"Pedido #{order.id}",
                    "description": "Pedido realizado no DishDash",
                    "quantity": 1,
                    "unit_price": float(Decimal(str(order.total)).quantize(Decimal("0.01"))),
                    "currency_id": "BRL",
                }
            ],
            "external_reference": str(order.id),
            "metadata": {
                "order_id": order.id,
                "company_id": order.company_id,
                "local_payment_id": payment.id,
            },
            "payer": self._build_checkout_payer(payer),
            "back_urls": {
                "success": self._build_frontend_checkout_return_url(order.id, "success"),
                "failure": self._build_frontend_checkout_return_url(order.id, "failure"),
                "pending": self._build_frontend_checkout_return_url(order.id, "pending"),
            },
            "auto_return": "approved",
            "expires": True,
            "expiration_date_from": self._format_mercado_pago_expiration(datetime.now(MERCADO_PAGO_PIX_TIMEZONE).replace(microsecond=0)),
            "expiration_date_to": self._format_mercado_pago_expiration(expires_at),
            "statement_descriptor": "DISHDASH",
        }

        webhook_url = self._build_mercado_pago_notification_url(order.id, payment.id)
        if webhook_url:
            payload["notification_url"] = webhook_url

        return payload

    @staticmethod
    def _build_checkout_payer(payer: User) -> dict:
        full_name = str(getattr(payer, "name", "") or "").strip()
        parts = full_name.split()
        payer_payload = {
            "email": getattr(payer, "email", None),
            "name": parts[0] if parts else None,
            "surname": " ".join(parts[1:]) if len(parts) > 1 else None,
        }
        return {key: value for key, value in payer_payload.items() if value}

    @staticmethod
    def _build_frontend_checkout_return_url(order_id: int, result: str) -> str:
        specific_by_result = {
            "success": settings.MERCADO_PAGO_CHECKOUT_SUCCESS_URL,
            "pending": settings.MERCADO_PAGO_CHECKOUT_PENDING_URL,
            "failure": settings.MERCADO_PAGO_CHECKOUT_FAILURE_URL,
        }
        specific_url = specific_by_result.get(result)
        if specific_url:
            return specific_url.replace("{order_id}", str(order_id)).replace("{result}", result)

        return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/checkout/pix/{order_id}?mp_result={result}"

    @staticmethod
    def _build_mercado_pago_notification_url(order_id: int, payment_id: int) -> str | None:
        webhook_url = str(settings.MERCADO_PAGO_WEBHOOK_URL or "").strip()
        if not webhook_url:
            return None

        parsed = urlsplit(webhook_url)
        current_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        current_query.update(
            {
                "order_id": str(order_id),
                "local_payment_id": str(payment_id),
            }
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(current_query), parsed.fragment))

    @staticmethod
    def _build_checkout_expiration_datetime() -> datetime:
        configured_minutes = settings.MERCADO_PAGO_CHECKOUT_EXPIRATION_MINUTES or settings.MERCADO_PAGO_PIX_EXPIRATION_MINUTES
        expiration_minutes = max(int(configured_minutes or 0), MIN_CHECKOUT_EXPIRATION_MINUTES)
        return datetime.now(MERCADO_PAGO_PIX_TIMEZONE).replace(microsecond=0) + timedelta(minutes=expiration_minutes)

    @staticmethod
    def _format_mercado_pago_expiration(expires_at: datetime) -> str:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            expires_at = expires_at.replace(tzinfo=MERCADO_PAGO_PIX_TIMEZONE)
        return expires_at.astimezone(MERCADO_PAGO_PIX_TIMEZONE).isoformat(timespec="milliseconds")

    @staticmethod
    def _sanitize_checkout_preference_payload_for_log(payload: dict) -> dict:
        payer = payload.get("payer") if isinstance(payload.get("payer"), dict) else {}
        return {
            "items_count": len(payload.get("items") or []),
            "external_reference": payload.get("external_reference"),
            "transaction_amount": (payload.get("items") or [{}])[0].get("unit_price") if payload.get("items") else None,
            "has_payer_email": bool(payer.get("email")),
            "has_notification_url": bool(payload.get("notification_url")),
            "has_back_urls": bool(payload.get("back_urls")),
            "expires": payload.get("expires"),
            "expiration_date_to": payload.get("expiration_date_to"),
        }

    async def _create_mercado_pago_preference(self, account: CompanyPaymentAccount, payload: dict, *, idempotency_key: str) -> dict:
        access_token = await self._get_valid_access_token(account)
        endpoint = str(settings.MERCADO_PAGO_CHECKOUT_PREFERENCES_URL).rstrip("/")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": idempotency_key,
        }
        logger.info(
            "Criando preferência Checkout Pro Mercado Pago endpoint=%s payload_sanitizado=%s idempotency_key=%s",
            endpoint,
            self._sanitize_checkout_preference_payload_for_log(payload),
            idempotency_key,
        )
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
        if response.is_error:
            logger.warning("Erro ao criar preferência Checkout Pro Mercado Pago. status_code=%s body=%s", response.status_code, self._safe_response_body(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível criar o checkout no Mercado Pago.")
        return response.json()

    async def _get_mercado_pago_payment(self, account: CompanyPaymentAccount, provider_payment_id: str) -> dict:
        access_token = await self._get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{str(settings.MERCADO_PAGO_PAYMENTS_URL).rstrip('/')}/{provider_payment_id}", headers=headers)
        if response.is_error:
            logger.warning("Erro ao consultar pagamento Mercado Pago. status_code=%s body=%s", response.status_code, self._safe_response_body(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível consultar pagamento no Mercado Pago.")
        return response.json()

    async def _search_latest_mercado_pago_payment_for_order(self, account: CompanyPaymentAccount, order_id: int) -> dict | None:
        access_token = await self._get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        endpoint = f"{str(settings.MERCADO_PAGO_PAYMENTS_URL).rstrip('/')}/search"
        params = {
            "external_reference": str(order_id),
            "sort": "date_created",
            "criteria": "desc",
        }
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.get(endpoint, headers=headers, params=params)
        if response.is_error:
            logger.warning(
                "Erro ao buscar pagamentos Mercado Pago por external_reference. order_id=%s status_code=%s body=%s",
                order_id,
                response.status_code,
                self._safe_response_body(response),
            )
            return None

        data = response.json()
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            return None

        for candidate in results:
            if str(candidate.get("external_reference")) == str(order_id):
                return candidate
        return results[0]

    async def _get_mercado_pago_payment_from_any_active_account(self, provider_payment_id: str) -> dict | None:
        accounts = await self.account_repository.list_active_by_provider(PaymentAccountProvider.MERCADO_PAGO.value)
        for account in accounts:
            try:
                return await self._get_mercado_pago_payment(account, provider_payment_id)
            except HTTPException:
                continue
        return None

    async def _cancel_mercado_pago_payment(self, account: CompanyPaymentAccount, provider_payment_id: str) -> dict:
        access_token = await self._get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.put(f"{str(settings.MERCADO_PAGO_PAYMENTS_URL).rstrip('/')}/{provider_payment_id}", json={"status": "cancelled"}, headers=headers)
        if response.is_error:
            logger.warning("Erro ao cancelar pagamento Mercado Pago. status_code=%s body=%s", response.status_code, self._safe_response_body(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível cancelar pagamento no Mercado Pago.")
        return response.json()

    async def _refund_mercado_pago_payment(self, account: CompanyPaymentAccount, provider_payment_id: str) -> dict:
        access_token = await self._get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        endpoint = f"{str(settings.MERCADO_PAGO_PAYMENTS_URL).rstrip('/')}/{provider_payment_id}/refunds"
        logger.info("Solicitando reembolso Mercado Pago. provider_payment_id=%s endpoint=%s", provider_payment_id, endpoint)
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, json={}, headers=headers)
        if response.is_error:
            logger.warning(
                "Erro ao reembolsar pagamento Mercado Pago. provider_payment_id=%s status_code=%s body=%s",
                provider_payment_id,
                response.status_code,
                self._safe_response_body(response),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Não foi possível processar o reembolso no Mercado Pago. Tente novamente antes de alterar o pedido.",
            )
        return response.json()

    async def _cancel_pending_payment_for_rejected_order(self, payment: Payment) -> None:
        if payment.provider_payment_id:
            account = await self._get_active_account_or_409(payment.company_id)
            response_data = await self._cancel_mercado_pago_payment(account, payment.provider_payment_id)
            self._apply_provider_payload(payment, response_data)

        if payment.status in PAYMENT_PENDING_STATUSES:
            now = datetime.utcnow()
            payment.status = PaymentStatus.CANCELLED.value
            payment.provider_status = payment.provider_status or PaymentStatus.CANCELLED.value
            payment.raw_status = payment.raw_status or payment.provider_status
            payment.cancelled_at = payment.cancelled_at or now
        await self.session.flush()

    def _apply_preference_payload(self, payment: Payment, preference_data: dict) -> None:
        preference_id = preference_data.get("id")
        payment.provider_order_id = str(preference_id) if preference_id is not None else payment.provider_order_id
        payment.provider_status = "preference_created"
        payment.provider_status_detail = None
        payment.raw_status = payment.provider_status
        payment.raw_status_detail = None
        payment.raw_response = {
            **(payment.raw_response if isinstance(payment.raw_response, dict) else {}),
            "preference": _sanitize_for_log(preference_data),
        }
        payment.status = PaymentStatus.PENDING.value

    def _apply_provider_payload(self, payment: Payment, response_data: dict, *, can_apply_approval: bool = True) -> None:
        provider_status = str(response_data.get("status") or "")
        provider_status_detail = response_data.get("status_detail")
        transaction_data = response_data.get("point_of_interaction", {}).get("transaction_data", {})
        now = datetime.utcnow()

        payment.provider_payment_id = str(response_data.get("id")) if response_data.get("id") is not None else payment.provider_payment_id
        payment.provider_order_id = self._extract_provider_order_id(response_data) or payment.provider_order_id
        payment.provider_status = provider_status or None
        payment.provider_status_detail = str(provider_status_detail) if provider_status_detail is not None else None
        payment.raw_status = payment.provider_status
        payment.raw_status_detail = payment.provider_status_detail
        payment.raw_response = {
            **(payment.raw_response if isinstance(payment.raw_response, dict) else {}),
            "payment": _sanitize_for_log(response_data),
        }
        payment.qr_code = transaction_data.get("qr_code") or payment.qr_code
        payment.qr_code_base64 = transaction_data.get("qr_code_base64") or payment.qr_code_base64

        normalized_method = self._normalize_provider_payment_method(response_data)
        if normalized_method:
            payment.payment_method = normalized_method

        if provider_status in MERCADO_PAGO_APPROVED_STATUSES and can_apply_approval:
            payment.status = PaymentStatus.APPROVED.value
            payment.paid_at = payment.paid_at or now
        elif provider_status in MERCADO_PAGO_APPROVED_STATUSES:
            logger.warning(
                "Pagamento Mercado Pago aprovado não foi aplicado ao pedido por validação de segurança. payment_id=%s provider_payment_id=%s",
                payment.id,
                payment.provider_payment_id,
            )
        elif provider_status in MERCADO_PAGO_PENDING_STATUSES:
            payment.status = PaymentStatus.IN_PROCESS.value if provider_status == "in_process" else PaymentStatus.PENDING.value
        elif provider_status in MERCADO_PAGO_CANCELLED_STATUSES:
            payment.status = PaymentStatus.CANCELLED.value
            payment.cancelled_at = payment.cancelled_at or now
        elif provider_status in MERCADO_PAGO_REJECTED_STATUSES:
            payment.status = PaymentStatus.REJECTED.value
            payment.failed_at = payment.failed_at or now
        elif provider_status_detail in MERCADO_PAGO_EXPIRED_STATUS_DETAILS:
            payment.status = PaymentStatus.EXPIRED.value
            payment.failed_at = payment.failed_at or now

    @staticmethod
    def _normalize_provider_payment_method(response_data: dict) -> str | None:
        payment_method_id = str(response_data.get("payment_method_id") or "").strip().lower()
        payment_type_id = str(response_data.get("payment_type_id") or "").strip().lower()
        if payment_method_id == "pix":
            return "pix"
        if payment_type_id in {"credit_card", "debit_card"}:
            return payment_type_id
        if payment_type_id == "bank_transfer":
            return "pix"
        return None

    def _apply_refund_payload(self, payment: Payment, refund_data: dict) -> None:
        now = datetime.utcnow()
        refund_status = str(refund_data.get("status") or "refunded")
        payment.status = PaymentStatus.REFUNDED.value
        payment.provider_status = refund_status
        payment.provider_status_detail = str(refund_data.get("status_detail")) if refund_data.get("status_detail") is not None else None
        payment.raw_status = payment.provider_status
        payment.raw_status_detail = payment.provider_status_detail
        payment.raw_response = {
            **(payment.raw_response if isinstance(payment.raw_response, dict) else {}),
            "refund": _sanitize_for_log(refund_data),
        }
        payment.refunded_at = payment.refunded_at or now

    async def _apply_order_status_from_payment(self, order: Order, payment: Payment) -> None:
        if payment.status == PaymentStatus.APPROVED.value and order.status == OrderStatus.PENDING_PAYMENT.value:
            old_status = order.status
            order.status = OrderStatus.OPEN.value
            self.session.add(
                OrderStatusHistory(
                    order_id=order.id,
                    old_status=old_status,
                    new_status=OrderStatus.OPEN.value,
                    changed_by_user_id=order.customer_user_id,
                )
            )
            await publish_company_order_event(
                order.company_id,
                {
                    "type": RealtimeEventType.ORDER_CREATED,
                    "order_id": order.id,
                    "company_id": order.company_id,
                    "status": order.status,
                    "message": f"Pedido #{order.id} pago e liberado para preparo.",
                },
            )
        elif payment.status in PAYMENT_RETRYABLE_STATUSES and order.status == OrderStatus.PENDING_PAYMENT.value:
            order.status = OrderStatus.PENDING_PAYMENT.value

    def _can_apply_provider_approval(self, payment: Payment, order: Order | None, response_data: dict) -> bool:
        provider_status = str(response_data.get("status") or "")
        if provider_status not in MERCADO_PAGO_APPROVED_STATUSES:
            return True

        if order is None:
            logger.warning("Pagamento aprovado no Mercado Pago sem pedido local encontrado. payment_id=%s order_id=%s", payment.id, payment.order_id)
            return False

        if payment.order_id != order.id:
            logger.warning("Pagamento aprovado pertence a outro pedido. payment_id=%s payment_order_id=%s order_id=%s", payment.id, payment.order_id, order.id)
            return False

        if payment.provider != PaymentProvider.MERCADO_PAGO.value:
            logger.warning("Pagamento aprovado com provider inesperado. payment_id=%s provider=%s", payment.id, payment.provider)
            return False

        if order.status == OrderStatus.CANCELED.value:
            logger.warning("Pagamento aprovado para pedido já cancelado. payment_id=%s order_id=%s", payment.id, order.id)
            return False

        provider_amount = self._extract_provider_transaction_amount(response_data)
        if provider_amount is None or provider_amount != Decimal(str(order.total)).quantize(Decimal("0.01")):
            logger.warning(
                "Valor aprovado no Mercado Pago diverge do total do pedido. payment_id=%s provider_amount=%s order_total=%s",
                payment.id,
                provider_amount,
                order.total,
            )
            return False

        provider_order_id = self._extract_order_id_from_provider_payload(response_data)
        if provider_order_id is not None and provider_order_id != order.id:
            logger.warning(
                "external_reference/metadata.order_id diverge do pedido local. payment_id=%s provider_order_id=%s order_id=%s",
                payment.id,
                provider_order_id,
                order.id,
            )
            return False

        return True

    @staticmethod
    def _extract_provider_transaction_amount(response_data: dict) -> Decimal | None:
        value = response_data.get("transaction_amount")
        if value is None:
            value = response_data.get("transaction_details", {}).get("total_paid_amount") if isinstance(response_data.get("transaction_details"), dict) else None
        if value is None:
            return None
        return Decimal(str(value)).quantize(Decimal("0.01"))

    @staticmethod
    def _extract_order_id_from_provider_payload(response_data: dict) -> int | None:
        value = response_data.get("external_reference")
        if value is None and isinstance(response_data.get("metadata"), dict):
            value = response_data["metadata"].get("order_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_provider_order_id(response_data: dict) -> str | None:
        order = response_data.get("order")
        if isinstance(order, dict) and order.get("id"):
            return str(order.get("id"))
        return None

    async def _get_latest_online_or_404(self, order_id: int) -> Payment:
        payment = await self.payment_repository.get_latest_online_by_order(order_id)
        if payment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pagamento online não encontrado.")
        return payment

    async def _get_latest_pix_or_404(self, order_id: int) -> Payment:
        return await self._get_latest_online_or_404(order_id)

    async def _get_valid_access_token(self, account: CompanyPaymentAccount) -> str:
        expires_at = getattr(account, "token_expires_at", None)
        should_refresh = bool(
            expires_at
            and getattr(account, "refresh_token_encrypted", None)
            and expires_at <= datetime.utcnow() + timedelta(minutes=TOKEN_REFRESH_SKEW_MINUTES)
        )

        if should_refresh:
            from app.services.company_payment_account_service import CompanyPaymentAccountService

            account = await CompanyPaymentAccountService(self.session).refresh_mercado_pago_access_token(account)

        return decrypt_secret(account.access_token_encrypted)

    async def _get_active_account_or_409(self, company_id: int) -> CompanyPaymentAccount:
        account = await self.account_repository.get_active_by_company_and_provider(company_id, PaymentAccountProvider.MERCADO_PAGO.value)
        if account is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Empresa não possui Mercado Pago conectado.")
        return account

    @staticmethod
    def _ensure_customer_can_manage_order(order: Order, current_user: User) -> None:
        if order.customer_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

    @staticmethod
    def _ensure_order_is_waiting_for_payment(order: Order) -> None:
        if order.status != OrderStatus.PENDING_PAYMENT.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Só é possível alterar pagamento online enquanto o pedido aguarda pagamento.",
            )

    @staticmethod
    def get_payment_action_flags(order: Order, payment: Payment | None) -> dict:
        is_waiting_payment = order.status == OrderStatus.PENDING_PAYMENT.value
        payment_status = payment.status if payment else None
        has_approved_payment = payment_status == PaymentStatus.APPROVED.value
        has_pending_payment = payment_status in PAYMENT_PENDING_STATUSES
        has_retryable_payment = payment is None or payment_status in PAYMENT_RETRYABLE_STATUSES

        return {
            "can_cancel_payment": bool(is_waiting_payment and has_pending_payment and not has_approved_payment),
            "can_regenerate_pix": bool(is_waiting_payment and has_retryable_payment and not has_approved_payment),
            "can_switch_to_delivery": bool(is_waiting_payment and (has_pending_payment or has_retryable_payment) and not has_approved_payment),
            "can_cancel_order": order.status in {OrderStatus.PENDING_PAYMENT.value, OrderStatus.OPEN.value},
        }

    @staticmethod
    def is_supported_payment_webhook(payload: dict, *, query_params: Mapping[str, str] | None = None) -> bool:
        query_params = query_params or {}
        topic = str(payload.get("type") or payload.get("topic") or query_params.get("topic") or "").lower()
        action = str(payload.get("action") or "").lower()
        if topic in {"payment", "payments"}:
            return True
        if action.startswith("payment."):
            return True
        # Eventos mp-connect/application.authorized pertencem ao OAuth, não ao
        # endpoint de pagamentos. Se vierem por engano, são ignorados.
        return False

    @staticmethod
    def _extract_provider_payment_id(payload: dict, *, query_params: Mapping[str, str] | None = None):
        query_params = query_params or {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        data_id = data.get("id") or query_params.get("data.id") or query_params.get("id")
        if data_id:
            return str(data_id)

        resource = payload.get("resource")
        if isinstance(resource, str) and resource.strip():
            return resource.rstrip("/").split("/")[-1]

        payload_id = payload.get("id")
        return str(payload_id) if payload_id is not None else None

    @staticmethod
    def _extract_local_payment_id(*, query_params: Mapping[str, str] | None = None) -> int | None:
        query_params = query_params or {}
        value = query_params.get("local_payment_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_order_id_from_query(*, query_params: Mapping[str, str] | None = None) -> int | None:
        query_params = query_params or {}
        value = query_params.get("order_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_mercado_pago_signature(x_signature: str) -> dict[str, str]:
        parts: dict[str, str] = {}
        for item in x_signature.split(","):
            key, separator, value = item.partition("=")
            if separator:
                parts[key.strip()] = value.strip()
        return parts

    @staticmethod
    def _ensure_webhook_timestamp_is_fresh(timestamp: str) -> None:
        tolerance_seconds = int(settings.MERCADO_PAGO_WEBHOOK_TOLERANCE_SECONDS or 0)
        if tolerance_seconds <= 0:
            return

        try:
            timestamp_value = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura do webhook inválida.") from exc

        timestamp_seconds = timestamp_value / 1000 if timestamp_value > 10_000_000_000 else timestamp_value
        now_seconds = datetime.utcnow().timestamp()
        if abs(now_seconds - timestamp_seconds) > tolerance_seconds:
            logger.warning("Webhook Mercado Pago rejeitado por timestamp fora da janela permitida. ts=%s", timestamp)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Assinatura do webhook expirada.")

    @staticmethod
    def _build_mercado_pago_webhook_signature(*, secret: str, provider_payment_id: str | None, x_request_id: str | None, timestamp: str) -> str:
        manifest = ""
        if provider_payment_id:
            manifest += f"id:{provider_payment_id};"
        if x_request_id:
            manifest += f"request-id:{x_request_id};"
        manifest += f"ts:{timestamp};"
        return hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _safe_response_body(response: httpx.Response):
        try:
            return _sanitize_for_log(response.json())
        except ValueError:
            return response.text[:2000]
