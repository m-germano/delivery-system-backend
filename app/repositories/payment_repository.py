from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Payment


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payment: Payment) -> Payment:
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def get_by_id(self, payment_id: int) -> Payment | None:
        result = await self.session.execute(select(Payment).where(Payment.id == payment_id))
        return result.scalar_one_or_none()

    async def get_by_provider_payment_id(self, provider_payment_id: str) -> Payment | None:
        result = await self.session.execute(select(Payment).where(Payment.provider_payment_id == str(provider_payment_id)))
        return result.scalar_one_or_none()

    async def get_latest_by_order(self, order_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_pix_by_order(self, order_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .where(Payment.payment_method == "pix")
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_order(self, order_id: int, *, limit: int = 50, offset: int = 0) -> tuple[list[Payment], int]:
        total_result = await self.session.execute(select(func.count(Payment.id)).where(Payment.order_id == order_id))
        payments_result = await self.session.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(payments_result.scalars().all()), int(total_result.scalar_one() or 0)

    async def list_by_company(self, company_id: int, *, limit: int = 50, offset: int = 0) -> tuple[list[Payment], int]:
        total_result = await self.session.execute(select(func.count(Payment.id)).where(Payment.company_id == company_id))
        payments_result = await self.session.execute(
            select(Payment)
            .where(Payment.company_id == company_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(payments_result.scalars().all()), int(total_result.scalar_one() or 0)
