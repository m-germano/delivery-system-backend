from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import require_roles
from app.db.session import get_db
from app.schemas.company_order_settings_schema import CompanyOrderSettingsResponse, CompanyOrderSettingsUpdateRequest
from app.schemas.company_schema import CompanyCreateRequest, CompanyListResponse, CompanyNearbyListResponse, CompanyResponse, CompanyUpdateRequest
from app.services.company_order_settings_service import CompanyOrderSettingsService
from app.services.company_service import CompanyService

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.get("", response_model=CompanyListResponse)
async def list_companies(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    companies = await CompanyService(db).list_active_companies(limit=limit, offset=offset)
    return CompanyListResponse(items=companies, total=len(companies))


@router.get("/nearby", response_model=CompanyNearbyListResponse)
async def list_nearby_companies(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    companies = await CompanyService(db).list_nearby_companies_for_customer(
        current_user,
        limit=limit,
        offset=offset,
    )
    return CompanyNearbyListResponse(items=companies, total=len(companies))


@router.get("/me", response_model=CompanyResponse)
async def get_my_company(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await CompanyService(db).get_my_company(current_user)


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    data: CompanyCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await CompanyService(db).create_company(data, current_user)


@router.put("/me", response_model=CompanyResponse)
async def update_my_company(
    data: CompanyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await CompanyService(db).update_my_company(data, current_user)


@router.get("/me/order-settings", response_model=CompanyOrderSettingsResponse)
async def get_my_order_settings(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await CompanyOrderSettingsService(db).get_my_settings(current_user)


@router.put("/me/order-settings", response_model=CompanyOrderSettingsResponse)
async def update_my_order_settings(
    data: CompanyOrderSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await CompanyOrderSettingsService(db).update_my_settings(data, current_user)


@router.get("/{company_id}/order-settings", response_model=CompanyOrderSettingsResponse)
async def get_company_order_settings(company_id: int, db: AsyncSession = Depends(get_db)):
    return await CompanyOrderSettingsService(db).get_public_settings(company_id)


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: int, db: AsyncSession = Depends(get_db)):
    return await CompanyService(db).get_company(company_id)
