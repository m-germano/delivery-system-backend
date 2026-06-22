from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import DeliveryStatus, OrderStatus
from app.models import Company, Delivery, Order

DELIVERY_LOAD_OPTIONS = (
    selectinload(Delivery.order).selectinload(Order.items),
    selectinload(Delivery.order).selectinload(Order.status_history),
    selectinload(Delivery.order).selectinload(Order.company).selectinload(Company.address),
    selectinload(Delivery.order).selectinload(Order.customer_address),
    selectinload(Delivery.status_history),
)


class DeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, delivery_id: int) -> Delivery | None:
        result = await self.session.execute(
            select(Delivery)
            .options(*DELIVERY_LOAD_OPTIONS)
            .where(Delivery.id == delivery_id)
        )
        return result.scalar_one_or_none()

    async def list_available(self, *, limit: int = 50, offset: int = 0) -> tuple[list[Delivery], int]:
        filters = (
            Delivery.status == DeliveryStatus.AVAILABLE.value,
            Delivery.courier_user_id.is_(None),
            Delivery.order.has(Order.status == OrderStatus.WAITING_COURIER.value),
        )
        total_result = await self.session.execute(select(func.count(Delivery.id)).where(*filters))
        deliveries_result = await self.session.execute(
            select(Delivery)
            .options(*DELIVERY_LOAD_OPTIONS)
            .where(*filters)
            .order_by(Delivery.created_at.asc(), Delivery.id.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(deliveries_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def list_by_courier(self, courier_user_id: int, *, limit: int = 50, offset: int = 0) -> tuple[list[Delivery], int]:
        filters = Delivery.courier_user_id == courier_user_id
        total_result = await self.session.execute(select(func.count(Delivery.id)).where(filters))
        deliveries_result = await self.session.execute(
            select(Delivery)
            .options(*DELIVERY_LOAD_OPTIONS)
            .where(filters)
            .order_by(Delivery.created_at.desc(), Delivery.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(deliveries_result.scalars().unique().all()), int(total_result.scalar_one() or 0)

    async def has_active_delivery(self, courier_user_id: int) -> bool:
        active_statuses = [
            DeliveryStatus.ACCEPTED.value,
            DeliveryStatus.PICKED_UP.value,
            DeliveryStatus.ON_ROUTE.value,
        ]
        result = await self.session.execute(
            select(func.count(Delivery.id))
            .where(Delivery.courier_user_id == courier_user_id)
            .where(Delivery.status.in_(active_statuses))
        )
        return int(result.scalar_one() or 0) > 0
