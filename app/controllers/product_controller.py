from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.schemas.product_schema import (
    ProductCategoryCreateRequest,
    ProductCategoryResponse,
    ProductCategoryUpdateRequest,
    ProductCreateRequest,
    ProductListResponse,
    ProductResponse,
    ProductUpdateRequest,
)
from app.services.product_service import ProductService

router = APIRouter(tags=["Products"])


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    company_id: int | None = Query(default=None, ge=1),
    include_inactive: bool = Query(default=False),
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    products, total = await ProductService(db).list_products_for_user(
        current_user=current_user,
        company_id=company_id,
        include_inactive=include_inactive,
        search=search,
        limit=limit,
        offset=offset,
    )
    return ProductListResponse(items=products, total=total)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await ProductService(db).get_product_for_user(product_id, current_user)


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await ProductService(db).create_product(data, current_user)


@router.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    data: ProductUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await ProductService(db).update_product(product_id, data, current_user)


@router.delete("/products/{product_id}", response_model=ProductResponse)
async def deactivate_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await ProductService(db).deactivate_product(product_id, current_user)


@router.get("/product-categories/me", response_model=list[ProductCategoryResponse])
async def list_my_categories(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await ProductService(db).list_my_categories(current_user)


@router.post("/product-categories", response_model=ProductCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    data: ProductCategoryCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await ProductService(db).create_category(data, current_user)


@router.put("/product-categories/{category_id}", response_model=ProductCategoryResponse)
async def update_category(
    category_id: int,
    data: ProductCategoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await ProductService(db).update_category(category_id, data, current_user)


@router.delete("/product-categories/{category_id}", response_model=ProductCategoryResponse)
async def deactivate_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COMPANY)),
):
    return await ProductService(db).deactivate_category(category_id, current_user)
