from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.models import Company, Product, ProductCategory, User
from app.repositories.company_repository import CompanyRepository
from app.repositories.customer_address_repository import CustomerAddressRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.product_schema import (
    ProductCategoryCreateRequest,
    ProductCategoryUpdateRequest,
    ProductCreateRequest,
    ProductUpdateRequest,
)


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.product_repository = ProductRepository(session)
        self.company_repository = CompanyRepository(session)
        self.customer_address_repository = CustomerAddressRepository(session)

    @staticmethod
    def _company_has_active_location(company: Company | None) -> bool:
        return bool(
            company
            and company.is_active
            and company.address
            and company.address.latitude is not None
            and company.address.longitude is not None
        )

    async def _get_ready_company_for_user(self, current_user: User) -> Company:
        company = await self.company_repository.get_by_owner_user_id(current_user.id)

        if company is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cadastre a empresa e seu endereço antes de gerenciar produtos.",
            )

        if not self._company_has_active_location(company):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A empresa precisa estar ativa e possuir endereço com latitude e longitude para gerenciar produtos.",
            )

        return company

    async def _ensure_customer_has_active_location(self, current_user: User) -> None:
        default_address = await self.customer_address_repository.get_default_by_user_id(current_user.id)
        if default_address is None or default_address.latitude is None or default_address.longitude is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cadastre um endereço padrão com latitude e longitude para visualizar produtos disponíveis.",
            )

    async def list_products_for_user(
        self,
        *,
        current_user: User,
        company_id: int | None = None,
        include_inactive: bool = False,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Product], int]:
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)
        safe_search = search.strip() if search and search.strip() else None
        role_id = RoleId(current_user.role_id)

        if role_id == RoleId.COMPANY:
            company = await self._get_ready_company_for_user(current_user)
            return await self.product_repository.list_products(
                company_id=company.id,
                only_active=not include_inactive,
                search=safe_search,
                limit=safe_limit,
                offset=safe_offset,
            )

        if role_id == RoleId.CUSTOMER:
            await self._ensure_customer_has_active_location(current_user)
            return await self.product_repository.list_customer_visible_products(
                company_id=company_id,
                search=safe_search,
                limit=safe_limit,
                offset=safe_offset,
            )

        if role_id == RoleId.ADMIN:
            return await self.product_repository.list_products(
                company_id=company_id,
                only_active=not include_inactive,
                search=safe_search,
                limit=safe_limit,
                offset=safe_offset,
            )

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Perfil não autorizado para consultar produtos.")

    async def get_product_for_user(self, product_id: int, current_user: User) -> Product:
        product = await self.product_repository.get_product_by_id(product_id)
        if product is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado.")

        role_id = RoleId(current_user.role_id)

        if role_id == RoleId.COMPANY:
            company = await self._get_ready_company_for_user(current_user)
            if product.company_id != company.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado.")
            return product

        if role_id == RoleId.CUSTOMER:
            await self._ensure_customer_has_active_location(current_user)
            if not product.is_active:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado.")
            return product

        if role_id == RoleId.ADMIN:
            return product

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Perfil não autorizado para consultar produtos.")

    async def create_product(self, data: ProductCreateRequest, current_user: User) -> Product:
        company = await self._get_ready_company_for_user(current_user)
        category = await self._validate_category_for_company(data.category_id, company.id)

        product = Product(
            company_id=company.id,
            category_id=category.id if category else None,
            name=data.name.strip(),
            description=data.description,
            price=data.price,
            image_url=data.image_url,
            is_active=data.is_active,
        )
        self.session.add(product)
        await self.session.commit()
        return await self.get_product_for_user(product.id, current_user)

    async def update_product(self, product_id: int, data: ProductUpdateRequest, current_user: User) -> Product:
        company = await self._get_ready_company_for_user(current_user)
        product = await self.product_repository.get_product_by_id(product_id)

        if product is None or product.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado.")

        category = await self._validate_category_for_company(data.category_id, company.id)
        product.category_id = category.id if category else None
        product.name = data.name.strip()
        product.description = data.description
        product.price = data.price
        product.image_url = data.image_url
        product.is_active = data.is_active

        await self.session.commit()
        return await self.get_product_for_user(product.id, current_user)

    async def deactivate_product(self, product_id: int, current_user: User) -> Product:
        company = await self._get_ready_company_for_user(current_user)
        product = await self.product_repository.get_product_by_id(product_id)

        if product is None or product.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado.")

        product.is_active = False
        await self.session.commit()
        return await self.get_product_for_user(product.id, current_user)

    async def list_my_categories(self, current_user: User) -> list[ProductCategory]:
        company = await self._get_ready_company_for_user(current_user)
        return await self.product_repository.list_categories_by_company(company.id)

    async def create_category(self, data: ProductCategoryCreateRequest, current_user: User) -> ProductCategory:
        company = await self._get_ready_company_for_user(current_user)
        category = ProductCategory(
            company_id=company.id,
            name=data.name.strip(),
            description=data.description,
            display_order=data.display_order,
            is_active=True,
        )
        self.session.add(category)
        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def update_category(self, category_id: int, data: ProductCategoryUpdateRequest, current_user: User) -> ProductCategory:
        company = await self._get_ready_company_for_user(current_user)
        category = await self.product_repository.get_category_by_id(category_id)

        if category is None or category.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria não encontrada.")

        category.name = data.name.strip()
        category.description = data.description
        category.display_order = data.display_order
        category.is_active = data.is_active

        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def deactivate_category(self, category_id: int, current_user: User) -> ProductCategory:
        company = await self._get_ready_company_for_user(current_user)
        category = await self.product_repository.get_category_by_id(category_id)

        if category is None or category.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria não encontrada.")

        category.is_active = False
        await self.session.commit()
        await self.session.refresh(category)
        return category

    async def _validate_category_for_company(self, category_id: int | None, company_id: int) -> ProductCategory | None:
        if category_id is None:
            return None

        category = await self.product_repository.get_category_by_id(category_id)
        if category is None or category.company_id != company_id or not category.is_active:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Categoria inválida para esta empresa.")

        return category
