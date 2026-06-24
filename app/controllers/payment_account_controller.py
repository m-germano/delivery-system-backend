import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import require_roles
from app.core.config import settings
from app.db.session import get_db
from app.schemas.payment_schema import CompanyPaymentAccountListResponse, CompanyPaymentAccountResponse, MercadoPagoConnectUrlResponse
from app.services.company_payment_account_service import CompanyPaymentAccountService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies/{company_id}/payment-accounts", tags=["Payment Accounts"])
callback_router = APIRouter(prefix="/payment-accounts/mercado-pago", tags=["Payment Accounts"])


@router.get("/mercado-pago/connect-url", response_model=MercadoPagoConnectUrlResponse)
async def get_mercado_pago_connect_url(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY, RoleId.ADMIN)),
):
    authorization_url = await CompanyPaymentAccountService(db).build_mercado_pago_connect_url(company_id, current_user)
    return MercadoPagoConnectUrlResponse(authorization_url=authorization_url)


@router.get("", response_model=CompanyPaymentAccountListResponse)
async def list_payment_accounts(
    company_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY, RoleId.ADMIN)),
):
    accounts = await CompanyPaymentAccountService(db).list_by_company(company_id, current_user)
    return CompanyPaymentAccountListResponse(items=accounts, total=len(accounts))


@router.delete("/{account_id}", response_model=CompanyPaymentAccountResponse)
async def deactivate_payment_account(
    company_id: int,
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY, RoleId.ADMIN)),
):
    return await CompanyPaymentAccountService(db).deactivate_account(company_id, account_id, current_user)


@callback_router.get("/callback")
async def mercado_pago_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    try:
        await CompanyPaymentAccountService(db).connect_mercado_pago_from_callback(code=code, state=state)
    except Exception:
        logger.exception("Falha ao concluir callback OAuth do Mercado Pago. Redirecionando para URL de erro.")
        return RedirectResponse(settings.FRONTEND_MERCADO_PAGO_ERROR_URL, status_code=302)

    return RedirectResponse(settings.FRONTEND_MERCADO_PAGO_SUCCESS_URL, status_code=302)
