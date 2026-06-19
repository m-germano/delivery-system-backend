from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_available(self) -> list[Product]:
        result = await self.db.execute(select(Product).where(Product.is_available.is_(True)))
        return list(result.scalars().all())
