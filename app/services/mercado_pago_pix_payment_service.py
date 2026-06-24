import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from decimal import Decimal
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
MIN_PIX_EXPIRATION_MINUTES = 30
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


class MercadoPagoPixPaymentService:
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

    async def create_pix_payment_for_order(self, order: Order, payer: User) -> Payment:
        account = await self._get_active_account_or_409(order.company_id)
        idempotency_key = f"order-{order.id}-pix-{uuid4()}"
        expires_at = self._build_pix_expiration_datetime()

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
        await self.session.commit()
        await self.session.refresh(payment)

        mp_payload = self._build_pix_payload(order, payer, expires_at)
        response_data = await self._create_mercado_pago_payment(account, mp_payload, idempotency_key=idempotency_key)
        self._apply_provider_payload(payment, response_data)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    async def cancel_pending_pix_payment(self, order: Order, current_user: User) -> Payment:
        self._ensure_customer_can_manage_order(order, current_user)
        self._ensure_order_is_waiting_for_payment(order)
        payment = await self._get_latest_pix_or_404(order.id)

        if payment.status == PaymentStatus.APPROVED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pagamento aprovado não pode ser cancelado por esta rota.")

        if payment.status not in PAYMENT_PENDING_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Só é possível cancelar uma cobrança Pix pendente.")

        if payment.status in PAYMENT_PENDING_STATUSES and payment.provider_payment_id:
            account = await self._get_active_account_or_409(payment.company_id)
            try:
                response_data = await self._cancel_mercado_pago_payment(account, payment.provider_payment_id)
                self._apply_provider_payload(payment, response_data)
            except HTTPException:
                raise

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
        self._ensure_customer_can_manage_order(order, current_user)
        self._ensure_order_is_waiting_for_payment(order)

        latest_payment = await self.payment_repository.get_latest_pix_by_order(order.id)
        if latest_payment and latest_payment.status in PAYMENT_PENDING_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe um Pix pendente para este pedido.")
        if latest_payment and latest_payment.status == PaymentStatus.APPROVED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pagamento já aprovado.")
        if latest_payment and latest_payment.status not in PAYMENT_RETRYABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Status do pagamento não permite gerar novo QR Code.")

        return await self.create_pix_payment_for_order(order, current_user)

    async def switch_pending_order_to_pay_on_delivery(self, order: Order, current_user: User) -> Order:
        self._ensure_customer_can_manage_order(order, current_user)
        self._ensure_order_is_waiting_for_payment(order)

        latest_payment = await self.payment_repository.get_latest_pix_by_order(order.id)
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
        """Cancela/reembolsa pagamento online quando a loja recusa o pedido.

        Retorna um marcador simples para a camada de pedidos ajustar mensagens.
        """
        payment = await self.payment_repository.get_latest_pix_by_order(order.id)
        if payment is None or order.payment_method != "PIX_ONLINE":
            return "not_online"

        if payment.provider != PaymentProvider.MERCADO_PAGO.value:
            return "not_mercado_pago"

        if payment.status == PaymentStatus.REFUNDED.value:
            logger.info(
                "Pagamento já reembolsado ao recusar pedido. order_id=%s provider_payment_id=%s status=%s",
                order.id,
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
        refund_data = await self._refund_mercado_pago_payment(account, payment.provider_payment_id)
        self._apply_refund_payload(payment, refund_data)
        await self.session.flush()
        logger.info(
            "Pagamento reembolsado ao recusar pedido. order_id=%s provider_payment_id=%s refund_status=%s",
            order.id,
            payment.provider_payment_id,
            payment.provider_status,
        )
        return "refunded"

    async def process_mercado_pago_webhook(self, payload: dict) -> None:
        provider_payment_id = self._extract_provider_payment_id(payload)
        if not provider_payment_id:
            logger.info("Webhook Mercado Pago sem payment id reconhecido. payload=%s", _sanitize_for_log(payload))
            return

        payment = await self.payment_repository.get_by_provider_payment_id(str(provider_payment_id))
        if payment is None:
            logger.info("Webhook Mercado Pago para pagamento ainda não registrado. provider_payment_id=%s", provider_payment_id)
            return

        await self.refresh_payment_from_provider(payment)

    def validate_webhook_signature(self, payload: dict, *, x_signature: str | None, x_request_id: str | None) -> None:
        provider_payment_id = self._extract_provider_payment_id(payload)
        event_type = payload.get("type") or payload.get("topic") or payload.get("action")
        secret = str(settings.MERCADO_PAGO_WEBHOOK_SECRET or "").strip()

        if not secret:
            logger.warning(
                "Validação de assinatura do webhook Mercado Pago desativada. event_type=%s provider_payment_id=%s x_request_id=%s",
                event_type,
                provider_payment_id,
                x_request_id,
            )
            return

        if not provider_payment_id or not x_signature or not x_request_id:
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
        if not payment.provider_payment_id:
            return payment
        if payment.provider != PaymentProvider.MERCADO_PAGO.value:
            logger.info("Ignorando refresh de pagamento de provider não suportado. payment_id=%s provider=%s", payment.id, payment.provider)
            return payment

        account = await self._get_active_account_or_409(payment.company_id)
        response_data = await self._get_mercado_pago_payment(account, payment.provider_payment_id)
        order = await self.order_repository.get_by_id(payment.order_id)

        can_apply_approval = self._can_apply_provider_approval(payment, order, response_data)
        self._apply_provider_payload(payment, response_data, can_apply_approval=can_apply_approval)
        if order is not None and can_apply_approval:
            await self._apply_order_status_from_payment(order, payment)
        await self.session.commit()
        await self.session.refresh(payment)
        return payment

    def _build_pix_payload(self, order: Order, payer: User, expires_at: datetime) -> dict:
        payload = {
            "transaction_amount": float(order.total),
            "description": f"Pedido #{order.id}",
            "payment_method_id": "pix",
            "payer": {
                "email": payer.email,
                "first_name": payer.name,
            },
            "external_reference": str(order.id),
            "metadata": {
                "order_id": order.id,
                "company_id": order.company_id,
            },
            "date_of_expiration": self._format_mercado_pago_expiration(expires_at),
        }

        webhook_url = str(settings.MERCADO_PAGO_WEBHOOK_URL or "").strip()
        if webhook_url:
            payload["notification_url"] = webhook_url

        return payload

    @staticmethod
    def _build_pix_expiration_datetime() -> datetime:
        expiration_minutes = max(
            int(settings.MERCADO_PAGO_PIX_EXPIRATION_MINUTES or 0),
            MIN_PIX_EXPIRATION_MINUTES,
        )
        return (
            datetime.now(MERCADO_PAGO_PIX_TIMEZONE)
            .replace(microsecond=0)
            + timedelta(minutes=expiration_minutes)
        )

    @staticmethod
    def _format_mercado_pago_expiration(expires_at: datetime) -> str:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            expires_at = expires_at.replace(tzinfo=MERCADO_PAGO_PIX_TIMEZONE)
        return expires_at.astimezone(MERCADO_PAGO_PIX_TIMEZONE).isoformat(timespec="milliseconds")

    @staticmethod
    def _sanitize_pix_create_payload_for_log(payload: dict) -> dict:
        payer = payload.get("payer") if isinstance(payload.get("payer"), dict) else {}
        return {
            "date_of_expiration": payload.get("date_of_expiration"),
            "transaction_amount": payload.get("transaction_amount"),
            "payment_method_id": payload.get("payment_method_id"),
            "external_reference": payload.get("external_reference"),
            "has_payer_email": bool(payer.get("email")),
            "has_notification_url": bool(payload.get("notification_url")),
        }

    async def _create_mercado_pago_payment(self, account: CompanyPaymentAccount, payload: dict, *, idempotency_key: str) -> dict:
        access_token = decrypt_secret(account.access_token_encrypted)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": idempotency_key,
        }
        logger.info(
            "Criando cobrança Pix Mercado Pago endpoint=%s payload_sanitizado=%s idempotency_key=%s",
            settings.MERCADO_PAGO_PAYMENTS_URL,
            self._sanitize_pix_create_payload_for_log(payload),
            idempotency_key,
        )
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.MERCADO_PAGO_PAYMENTS_URL, json=payload, headers=headers)
        if response.is_error:
            logger.warning("Erro ao criar cobrança Pix Mercado Pago. status_code=%s body=%s", response.status_code, self._safe_response_body(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível criar cobrança Pix no Mercado Pago.")
        return response.json()

    async def _get_mercado_pago_payment(self, account: CompanyPaymentAccount, provider_payment_id: str) -> dict:
        access_token = decrypt_secret(account.access_token_encrypted)
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{settings.MERCADO_PAGO_PAYMENTS_URL}/{provider_payment_id}", headers=headers)
        if response.is_error:
            logger.warning("Erro ao consultar pagamento Mercado Pago. status_code=%s body=%s", response.status_code, self._safe_response_body(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível consultar pagamento no Mercado Pago.")
        return response.json()

    async def _cancel_mercado_pago_payment(self, account: CompanyPaymentAccount, provider_payment_id: str) -> dict:
        access_token = decrypt_secret(account.access_token_encrypted)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
            response = await client.put(f"{settings.MERCADO_PAGO_PAYMENTS_URL}/{provider_payment_id}", json={"status": "cancelled"}, headers=headers)
        if response.is_error:
            logger.warning("Erro ao cancelar pagamento Mercado Pago. status_code=%s body=%s", response.status_code, self._safe_response_body(response))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível cancelar pagamento no Mercado Pago.")
        return response.json()

    async def _refund_mercado_pago_payment(self, account: CompanyPaymentAccount, provider_payment_id: str) -> dict:
        access_token = decrypt_secret(account.access_token_encrypted)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        endpoint = f"{settings.MERCADO_PAGO_PAYMENTS_URL}/{provider_payment_id}/refunds"
        logger.info(
            "Solicitando reembolso Mercado Pago. order_provider_payment_id=%s endpoint=%s",
            provider_payment_id,
            endpoint,
        )
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
                detail="Não foi possível processar o reembolso no Mercado Pago. Tente novamente antes de recusar o pedido.",
            )
        return response.json()

    async def _cancel_pending_payment_for_rejected_order(self, payment: Payment) -> None:
        if payment.provider_payment_id:
            account = await self._get_active_account_or_409(payment.company_id)
            try:
                response_data = await self._cancel_mercado_pago_payment(account, payment.provider_payment_id)
                self._apply_provider_payload(payment, response_data)
            except HTTPException:
                logger.warning(
                    "Falha ao cancelar Pix pendente durante recusa. payment_id=%s provider_payment_id=%s",
                    payment.id,
                    payment.provider_payment_id,
                )
                raise

        if payment.status in PAYMENT_PENDING_STATUSES:
            now = datetime.utcnow()
            payment.status = PaymentStatus.CANCELLED.value
            payment.provider_status = payment.provider_status or PaymentStatus.CANCELLED.value
            payment.raw_status = payment.raw_status or payment.provider_status
            payment.cancelled_at = payment.cancelled_at or now
        await self.session.flush()

    def _apply_provider_payload(self, payment: Payment, response_data: dict, *, can_apply_approval: bool = True) -> None:
        provider_status = str(response_data.get("status") or "")
        provider_status_detail = response_data.get("status_detail")
        transaction_data = response_data.get("point_of_interaction", {}).get("transaction_data", {})
        now = datetime.utcnow()

        payment.provider_payment_id = str(response_data.get("id")) if response_data.get("id") is not None else payment.provider_payment_id
        payment.provider_order_id = str(response_data.get("order", {}).get("id")) if isinstance(response_data.get("order"), dict) and response_data.get("order", {}).get("id") else payment.provider_order_id
        payment.provider_status = provider_status or None
        payment.provider_status_detail = str(provider_status_detail) if provider_status_detail is not None else None
        payment.raw_status = payment.provider_status
        payment.raw_status_detail = payment.provider_status_detail
        payment.raw_response = _sanitize_for_log(response_data)
        payment.qr_code = transaction_data.get("qr_code") or payment.qr_code
        payment.qr_code_base64 = transaction_data.get("qr_code_base64") or payment.qr_code_base64

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
        if provider_amount is None or provider_amount != Decimal(str(order.total)):
            logger.warning(
                "Valor aprovado no Mercado Pago diverge do total do pedido. payment_id=%s provider_amount=%s order_total=%s",
                payment.id,
                provider_amount,
                order.total,
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

    async def _get_latest_pix_or_404(self, order_id: int) -> Payment:
        payment = await self.payment_repository.get_latest_pix_by_order(order_id)
        if payment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pagamento Pix não encontrado.")
        return payment

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
                detail="Só é possível alterar pagamento Pix enquanto o pedido aguarda pagamento.",
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
    def _extract_provider_payment_id(payload: dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return data.get("id") or payload.get("id") or payload.get("resource")

    @staticmethod
    def _parse_mercado_pago_signature(x_signature: str) -> dict[str, str]:
        parts: dict[str, str] = {}
        for item in x_signature.split(","):
            key, separator, value = item.partition("=")
            if separator:
                parts[key.strip()] = value.strip()
        return parts

    @staticmethod
    def _build_mercado_pago_webhook_signature(*, secret: str, provider_payment_id: str, x_request_id: str, timestamp: str) -> str:
        manifest = f"id:{provider_payment_id};request-id:{x_request_id};ts:{timestamp};"
        return hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _safe_response_body(response: httpx.Response):
        try:
            return _sanitize_for_log(response.json())
        except ValueError:
            return response.text[:2000]
