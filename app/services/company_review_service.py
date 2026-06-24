from math import ceil

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, RoleId
from app.models import CompanyReview, User
from app.repositories.company_repository import CompanyRepository
from app.repositories.company_review_repository import CompanyReviewRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.company_review_schema import CompanyReviewCreateRequest, CompanyReviewListResponse, CompanyReviewSummaryResponse

REVIEWABLE_ORDER_STATUSES = {OrderStatus.DELIVERED.value, OrderStatus.PICKED_UP.value}


class CompanyReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.company_repository = CompanyRepository(session)
        self.order_repository = OrderRepository(session)
        self.review_repository = CompanyReviewRepository(session)

    async def create_order_review(self, order_id: int, data: CompanyReviewCreateRequest, current_user: User) -> CompanyReview:
        self._ensure_customer(current_user)
        order = await self.order_repository.get_by_id(order_id)

        if order is None or order.customer_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        if order.status not in REVIEWABLE_ORDER_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este pedido ainda não pode ser avaliado. Avalie apenas pedidos entregues ou retirados.",
            )

        existing_review = await self.review_repository.get_by_order_id(order.id)
        if existing_review is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este pedido já foi avaliado.")

        review = await self.review_repository.create(
            CompanyReview(
                company_id=order.company_id,
                customer_user_id=current_user.id,
                order_id=order.id,
                rating=data.rating,
                comment=data.comment,
            )
        )
        await self.session.commit()
        return review

    async def list_company_reviews(self, company_id: int, *, page: int = 1, limit: int = 10) -> CompanyReviewListResponse:
        company = await self.company_repository.get_by_id(company_id)
        if company is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada.")

        return await self._list_reviews_for_company(company.id, page=page, limit=limit)

    async def get_company_review_summary(self, company_id: int) -> CompanyReviewSummaryResponse:
        company = await self.company_repository.get_by_id(company_id)
        if company is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada.")

        average_rating, reviews_count = await self.review_repository.get_summary_by_company(company.id)
        return CompanyReviewSummaryResponse(company_id=company.id, average_rating=average_rating, reviews_count=reviews_count)

    async def list_my_company_reviews(self, current_user: User, *, page: int = 1, limit: int = 10) -> CompanyReviewListResponse:
        self._ensure_company(current_user)
        company = await self.company_repository.get_by_owner_user_id(current_user.id)
        if company is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Configure sua empresa antes de consultar avaliações.")

        return await self._list_reviews_for_company(company.id, page=page, limit=limit)

    async def _list_reviews_for_company(self, company_id: int, *, page: int, limit: int) -> CompanyReviewListResponse:
        safe_page = max(1, page)
        safe_limit = max(1, min(limit, 50))
        offset = (safe_page - 1) * safe_limit
        reviews, total = await self.review_repository.list_by_company(company_id, limit=safe_limit, offset=offset)
        average_rating, reviews_count = await self.review_repository.get_summary_by_company(company_id)
        total_pages = max(1, ceil(total / safe_limit)) if total else 0

        return CompanyReviewListResponse(
            items=reviews,
            total=total,
            page=safe_page,
            limit=safe_limit,
            total_pages=total_pages,
            average_rating=average_rating,
            reviews_count=reviews_count,
        )

    @staticmethod
    def _ensure_customer(current_user: User) -> None:
        if current_user.role_id != RoleId.CUSTOMER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas clientes podem avaliar pedidos.")

    @staticmethod
    def _ensure_company(current_user: User) -> None:
        if current_user.role_id != RoleId.COMPANY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas empresas podem consultar suas avaliações.")
