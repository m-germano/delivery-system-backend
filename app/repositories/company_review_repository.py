from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import CompanyReview


class CompanyReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_order_id(self, order_id: int) -> CompanyReview | None:
        result = await self.session.execute(
            select(CompanyReview)
            .options(selectinload(CompanyReview.customer), selectinload(CompanyReview.order))
            .where(CompanyReview.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def create(self, review: CompanyReview) -> CompanyReview:
        self.session.add(review)
        await self.session.flush()
        created_review = await self.get_by_order_id(review.order_id)
        return created_review or review

    async def list_by_company(self, company_id: int, *, limit: int = 10, offset: int = 0) -> tuple[list[CompanyReview], int]:
        base_filter = CompanyReview.company_id == company_id
        total_result = await self.session.execute(select(func.count(CompanyReview.id)).where(base_filter))
        reviews_result = await self.session.execute(
            select(CompanyReview)
            .options(selectinload(CompanyReview.customer), selectinload(CompanyReview.order))
            .where(base_filter)
            .order_by(CompanyReview.created_at.desc(), CompanyReview.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(reviews_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def get_summary_by_company(self, company_id: int) -> tuple[Decimal | None, int]:
        result = await self.session.execute(
            select(func.avg(CompanyReview.rating), func.count(CompanyReview.id)).where(CompanyReview.company_id == company_id)
        )
        average, count = result.one()
        return self._normalize_average(average), int(count or 0)

    async def get_summaries_by_company_ids(self, company_ids: list[int]) -> dict[int, tuple[Decimal | None, int]]:
        if not company_ids:
            return {}

        result = await self.session.execute(
            select(CompanyReview.company_id, func.avg(CompanyReview.rating), func.count(CompanyReview.id))
            .where(CompanyReview.company_id.in_(company_ids))
            .group_by(CompanyReview.company_id)
        )
        return {
            int(company_id): (self._normalize_average(average), int(count or 0))
            for company_id, average, count in result.all()
        }

    async def list_by_order_ids(self, order_ids: list[int]) -> dict[int, CompanyReview]:
        if not order_ids:
            return {}

        result = await self.session.execute(
            select(CompanyReview)
            .options(selectinload(CompanyReview.customer), selectinload(CompanyReview.order))
            .where(CompanyReview.order_id.in_(order_ids))
        )
        reviews = list(result.scalars().unique().all())
        return {review.order_id: review for review in reviews}

    @staticmethod
    def _normalize_average(value) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
