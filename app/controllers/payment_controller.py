from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.repositories.company_repository import CompanyRepository
from app.schemas.payment_schema import CompanyPaymentAvailabilityResponse, MercadoPagoWebhookResponse
from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService

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
        mercado_pago_connected = await MercadoPagoPixPaymentService(db).is_pix_available_for_company(company_id)

    return CompanyPaymentAvailabilityResponse(
        company_id=company_id,
        mercado_pago_connected=mercado_pago_connected,
        pix_online_available=mercado_pago_connected,
    )


@router.post("/payments/mercado-pago/webhook", response_model=MercadoPagoWebhookResponse)
async def mercado_pago_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()
    payment_service = MercadoPagoPixPaymentService(db)
    payment_service.validate_webhook_signature(
        payload,
        x_signature=request.headers.get("x-signature"),
        x_request_id=request.headers.get("x-request-id"),
    )
    await payment_service.process_mercado_pago_webhook(payload)
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
        mercado_pago_connected = await MercadoPagoPixPaymentService(db).is_pix_available_for_company(company.id)
    return CompanyPaymentAvailabilityResponse(
        company_id=company_id,
        mercado_pago_connected=mercado_pago_connected,
        pix_online_available=mercado_pago_connected,
    )
