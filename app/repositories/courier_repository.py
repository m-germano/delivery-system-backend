from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Courier


class CourierRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: int) -> Courier | None:
        result = await self.session.execute(select(Courier).where(Courier.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create_by_user_id(self, user_id: int) -> Courier:
        courier = await self.get_by_user_id(user_id)
        if courier is not None:
            return courier

        courier = Courier(user_id=user_id)
        self.session.add(courier)
        await self.session.flush()
        return courier
