from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Company, Order, Product


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.status_history),
                selectinload(Order.company).selectinload(Company.address),
                selectinload(Order.customer_address),
                selectinload(Order.delivery),
            )
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def list_by_customer(self, customer_user_id: int, *, limit: int = 50, offset: int = 0) -> tuple[list[Order], int]:
        base_filters = Order.customer_user_id == customer_user_id
        total_result = await self.session.execute(select(func.count(Order.id)).where(base_filters))
        orders_result = await self.session.execute(
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.status_history),
                selectinload(Order.company).selectinload(Company.address),
                selectinload(Order.customer_address),
                selectinload(Order.delivery),
            )
            .where(base_filters)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(orders_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def list_by_company(self, company_id: int, *, limit: int = 50, offset: int = 0) -> tuple[list[Order], int]:
        base_filters = Order.company_id == company_id
        total_result = await self.session.execute(select(func.count(Order.id)).where(base_filters))
        orders_result = await self.session.execute(
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.status_history),
                selectinload(Order.company).selectinload(Company.address),
                selectinload(Order.customer_address),
                selectinload(Order.delivery),
            )
            .where(base_filters)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(orders_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def list_all(self, *, limit: int = 50, offset: int = 0) -> tuple[list[Order], int]:
        total_result = await self.session.execute(select(func.count(Order.id)))
        orders_result = await self.session.execute(
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.status_history),
                selectinload(Order.company).selectinload(Company.address),
                selectinload(Order.customer_address),
                selectinload(Order.delivery),
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(orders_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def get_active_products_by_ids(self, product_ids: list[int]) -> list[Product]:
        result = await self.session.execute(
            select(Product)
            .where(Product.id.in_(product_ids))
            .where(Product.is_active.is_(True))
        )
        return list(result.scalars().all())
