from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaymentOAuthState


class PaymentOAuthStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, oauth_state: PaymentOAuthState) -> PaymentOAuthState:
        self.session.add(oauth_state)
        await self.session.flush()
        return oauth_state

    async def get_by_state(self, state: str) -> PaymentOAuthState | None:
        result = await self.session.execute(select(PaymentOAuthState).where(PaymentOAuthState.state == state))
        return result.scalar_one_or_none()

    async def mark_consumed(self, oauth_state: PaymentOAuthState, *, consumed_at: datetime) -> PaymentOAuthState:
        oauth_state.consumed_at = consumed_at
        await self.session.flush()
        return oauth_state
