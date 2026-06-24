from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import require_roles
from app.db.session import get_db
from app.schemas.company_review_schema import (
    CompanyReviewCreateRequest,
    CompanyReviewListResponse,
    CompanyReviewResponse,
    CompanyReviewSummaryResponse,
)
from app.services.company_review_service import CompanyReviewService

router = APIRouter(tags=["Reviews"])


@router.post("/orders/{order_id}/review", response_model=CompanyReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_order_review(
    order_id: int,
    data: CompanyReviewCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await CompanyReviewService(db).create_order_review(order_id, data, current_user)


@router.get("/companies/me/reviews", response_model=CompanyReviewListResponse)
async def list_my_company_reviews(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await CompanyReviewService(db).list_my_company_reviews(current_user, page=page, limit=limit)


@router.get("/companies/{company_id}/reviews/summary", response_model=CompanyReviewSummaryResponse)
async def get_company_review_summary(company_id: int, db: AsyncSession = Depends(get_db)):
    return await CompanyReviewService(db).get_company_review_summary(company_id)


@router.get("/companies/{company_id}/reviews", response_model=CompanyReviewListResponse)
async def list_company_reviews(
    company_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    return await CompanyReviewService(db).list_company_reviews(company_id, page=page, limit=limit)
