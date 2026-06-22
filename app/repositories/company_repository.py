from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Company


class CompanyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, company_id: int, *, include_inactive: bool = False) -> Company | None:
        statement = (
            select(Company)
            .options(selectinload(Company.address), selectinload(Company.fee_rules))
            .where(Company.id == company_id)
        )

        if not include_inactive:
            statement = statement.where(Company.is_active.is_(True)).where(Company.address.has())

        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_owner_user_id(self, owner_user_id: int) -> Company | None:
        result = await self.session.execute(
            select(Company)
            .options(selectinload(Company.address), selectinload(Company.fee_rules))
            .where(Company.owner_user_id == owner_user_id)
        )
        return result.scalar_one_or_none()

    async def list_active(self, *, limit: int = 50, offset: int = 0) -> list[Company]:
        result = await self.session.execute(
            select(Company)
            .options(selectinload(Company.address), selectinload(Company.fee_rules))
            .where(Company.is_active.is_(True))
            .where(Company.address.has())
            .order_by(Company.name.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().unique().all())
