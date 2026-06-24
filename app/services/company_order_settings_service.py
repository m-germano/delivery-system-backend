from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.models import CompanyOrderSettings, User
from app.repositories.company_order_settings_repository import CompanyOrderSettingsRepository
from app.repositories.company_repository import CompanyRepository
from app.schemas.company_order_settings_schema import CompanyOrderSettingsUpdateRequest


class CompanyOrderSettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.company_repository = CompanyRepository(session)
        self.settings_repository = CompanyOrderSettingsRepository(session)

    async def get_public_settings(self, company_id: int) -> CompanyOrderSettings:
        company = await self.company_repository.get_by_id(company_id)
        if company is None or not company.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada.")

        settings = await self.settings_repository.get_or_create_default(company.id)
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    async def get_my_settings(self, current_user: User) -> CompanyOrderSettings:
        company = await self._get_company_for_owner(current_user)
        settings = await self.settings_repository.get_or_create_default(company.id)
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    async def update_my_settings(self, data: CompanyOrderSettingsUpdateRequest, current_user: User) -> CompanyOrderSettings:
        company = await self._get_company_for_owner(current_user)
        settings = await self.settings_repository.get_or_create_default(company.id)

        settings.accepts_delivery = data.accepts_delivery
        settings.accepts_pickup = data.accepts_pickup
        settings.pickup_discount_percent = data.pickup_discount_percent
        settings.minimum_order_value = data.minimum_order_value

        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    async def _get_company_for_owner(self, current_user: User):
        if current_user.role_id != RoleId.COMPANY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas empresas podem executar esta operação.")

        company = await self.company_repository.get_by_owner_user_id(current_user.id)
        if company is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa ainda não configurada para este usuário.")
        return company
