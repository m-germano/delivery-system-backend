import json
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.enums import RoleId
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.repositories.company_repository import CompanyRepository
from app.schemas.payment_schema import CompanyPaymentAvailabilityResponse, MercadoPagoWebhookResponse
from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService
from fastapi.responses import RedirectResponse
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Payments"])


@router.get("/companies/{company_id}/payment-availability", response_model=CompanyPaymentAvailabilityResponse)
async def get_company_payment_availability(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    company = await CompanyRepository(db).get_by_id(company_id, include_inactive=True)
    mercado_pago_connected = False
    if company is not None:
        mercado_pago_connected = await MercadoPagoPixPaymentService(db).is_checkout_pro_available_for_company(company_id)

    return CompanyPaymentAvailabilityResponse(
        company_id=company_id,
        mercado_pago_connected=mercado_pago_connected,
        pix_online_available=mercado_pago_connected,
        checkout_pro_available=mercado_pago_connected,
    )


@router.post("/payments/mercado-pago/webhook", response_model=MercadoPagoWebhookResponse)
async def mercado_pago_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except json.JSONDecodeError:
        logger.warning("Webhook Mercado Pago recebido com JSON inválido.")
        payload = {}

    query_params = dict(request.query_params)
    payment_service = MercadoPagoPixPaymentService(db)
    payment_service.validate_webhook_signature(
        payload,
        query_params=query_params,
        x_signature=request.headers.get("x-signature"),
        x_request_id=request.headers.get("x-request-id"),
    )
    await payment_service.process_mercado_pago_webhook(payload, query_params=query_params)
    return MercadoPagoWebhookResponse(received=True)


@router.get("/payments/company/availability", response_model=CompanyPaymentAvailabilityResponse)
async def get_my_company_payment_availability(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    company = await CompanyRepository(db).get_by_owner_user_id(current_user.id)
    company_id = company.id if company is not None else 0
    mercado_pago_connected = False
    if company is not None:
        mercado_pago_connected = await MercadoPagoPixPaymentService(db).is_checkout_pro_available_for_company(company.id)
    return CompanyPaymentAvailabilityResponse(
        company_id=company_id,
        mercado_pago_connected=mercado_pago_connected,
        pix_online_available=mercado_pago_connected,
        checkout_pro_available=mercado_pago_connected,
    )

@router.get("/mercado-pago/checkout-return")
async def mercado_pago_checkout_return(request: Request):
    query = dict(request.query_params)

    order_id = query.get("order_id")
    mp_result = query.get("mp_result") or query.get("status") or "pending"

    frontend_base_url = str(settings.FRONTEND_BASE_URL or "http://localhost:5173").rstrip("/")

    if order_id:
        redirect_url = f"{frontend_base_url}/checkout/pix/{order_id}?mp_result={mp_result}"
    else:
        redirect_url = f"{frontend_base_url}/customer/orders?mp_result={mp_result}"

    passthrough_keys = [
        "collection_id",
        "payment_id",
        "status",
        "external_reference",
        "payment_type",
        "merchant_order_id",
        "preference_id",
        "site_id",
    ]

    extra_params = []
    for key in passthrough_keys:
        value = query.get(key)
        if value:
            extra_params.append(f"{key}={value}")

    if extra_params:
        separator = "&" if "?" in redirect_url else "?"
        redirect_url = f"{redirect_url}{separator}{'&'.join(extra_params)}"

    return RedirectResponse(url=redirect_url, status_code=302)