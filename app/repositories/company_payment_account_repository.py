from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CompanyPaymentAccount


class CompanyPaymentAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_account(self, account: CompanyPaymentAccount) -> CompanyPaymentAccount:
        self.session.add(account)
        await self.session.flush()
        return account

    async def list_by_company(self, company_id: int) -> list[CompanyPaymentAccount]:
        result = await self.session.execute(
            select(CompanyPaymentAccount)
            .where(CompanyPaymentAccount.company_id == company_id)
            .order_by(CompanyPaymentAccount.created_at.desc(), CompanyPaymentAccount.id.desc())
        )
        return list(result.scalars().all())

    async def list_active_by_provider(self, provider: str) -> list[CompanyPaymentAccount]:
        result = await self.session.execute(
            select(CompanyPaymentAccount)
            .where(CompanyPaymentAccount.provider == provider)
            .where(CompanyPaymentAccount.is_active.is_(True))
            .order_by(CompanyPaymentAccount.created_at.desc(), CompanyPaymentAccount.id.desc())
        )
        return list(result.scalars().all())

    async def get_by_id_and_company(self, account_id: int, company_id: int) -> CompanyPaymentAccount | None:
        result = await self.session.execute(
            select(CompanyPaymentAccount)
            .where(CompanyPaymentAccount.id == account_id)
            .where(CompanyPaymentAccount.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_company_and_provider(self, company_id: int, provider: str) -> CompanyPaymentAccount | None:
        result = await self.session.execute(
            select(CompanyPaymentAccount)
            .where(CompanyPaymentAccount.company_id == company_id)
            .where(CompanyPaymentAccount.provider == provider)
            .where(CompanyPaymentAccount.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def deactivate_account(self, account: CompanyPaymentAccount, *, disconnected_at: datetime) -> CompanyPaymentAccount:
        account.is_active = False
        account.disconnected_at = disconnected_at
        await self.session.flush()
        return account
