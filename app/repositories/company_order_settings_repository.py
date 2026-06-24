from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyOrderSettings


class CompanyOrderSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_company_id(self, company_id: int) -> CompanyOrderSettings | None:
        result = await self.session.execute(
            select(CompanyOrderSettings).where(CompanyOrderSettings.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create_default(self, company_id: int) -> CompanyOrderSettings:
        settings = await self.get_by_company_id(company_id)
        if settings is not None:
            return settings

        settings = CompanyOrderSettings(company_id=company_id)
        self.session.add(settings)
        await self.session.flush()
        return settings
