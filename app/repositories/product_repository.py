from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Company, Product, ProductCategory


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_product_by_id(self, product_id: int) -> Product | None:
        result = await self.session.execute(
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.id == product_id)
        )
        return result.scalar_one_or_none()

    async def list_products(
        self,
        *,
        company_id: int | None = None,
        only_active: bool = True,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Product], int]:
        statement = select(Product).options(selectinload(Product.category))
        count_statement = select(func.count(Product.id))

        if company_id is not None:
            statement = statement.where(Product.company_id == company_id)
            count_statement = count_statement.where(Product.company_id == company_id)

        if only_active:
            statement = statement.where(Product.is_active.is_(True))
            count_statement = count_statement.where(Product.is_active.is_(True))

        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(Product.name.ilike(pattern))
            count_statement = count_statement.where(Product.name.ilike(pattern))

        statement = statement.order_by(Product.name.asc()).limit(limit).offset(offset)

        products_result = await self.session.execute(statement)
        total_result = await self.session.execute(count_statement)
        return list(products_result.scalars().unique().all()), int(total_result.scalar_one())

    async def list_customer_visible_products(
        self,
        *,
        company_id: int | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Product], int]:
        statement = (
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.is_active.is_(True))
            .where(Product.company.has(Company.is_active.is_(True)))
            .where(Product.company.has(Company.address.has()))
        )
        count_statement = (
            select(func.count(Product.id))
            .where(Product.is_active.is_(True))
            .where(Product.company.has(Company.is_active.is_(True)))
            .where(Product.company.has(Company.address.has()))
        )

        if company_id is not None:
            statement = statement.where(Product.company_id == company_id)
            count_statement = count_statement.where(Product.company_id == company_id)

        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(Product.name.ilike(pattern))
            count_statement = count_statement.where(Product.name.ilike(pattern))

        statement = statement.order_by(Product.name.asc()).limit(limit).offset(offset)

        products_result = await self.session.execute(statement)
        total_result = await self.session.execute(count_statement)
        return list(products_result.scalars().unique().all()), int(total_result.scalar_one())

    async def get_category_by_id(self, category_id: int) -> ProductCategory | None:
        result = await self.session.execute(select(ProductCategory).where(ProductCategory.id == category_id))
        return result.scalar_one_or_none()

    async def list_categories_by_company(self, company_id: int, *, only_active: bool = False) -> list[ProductCategory]:
        statement = select(ProductCategory).where(ProductCategory.company_id == company_id)

        if only_active:
            statement = statement.where(ProductCategory.is_active.is_(True))

        statement = statement.order_by(ProductCategory.display_order.asc(), ProductCategory.name.asc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())
