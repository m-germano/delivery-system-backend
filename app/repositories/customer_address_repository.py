from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CustomerAddress


class CustomerAddressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, address_id: int) -> CustomerAddress | None:
        result = await self.session.execute(select(CustomerAddress).where(CustomerAddress.id == address_id))
        return result.scalar_one_or_none()

    async def list_by_user_id(self, user_id: int) -> list[CustomerAddress]:
        result = await self.session.execute(
            select(CustomerAddress)
            .where(CustomerAddress.user_id == user_id)
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_default_by_user_id(self, user_id: int) -> CustomerAddress | None:
        result = await self.session.execute(
            select(CustomerAddress)
            .where(CustomerAddress.user_id == user_id)
            .where(CustomerAddress.is_default.is_(True))
            .order_by(CustomerAddress.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
