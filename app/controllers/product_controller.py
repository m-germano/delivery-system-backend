from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.product_repository import ProductRepository
from app.schemas.product_schema import ProductResponse
from app.services.product_service import ProductService

router = APIRouter()


@router.get("", response_model=list[ProductResponse])
async def list_products(db: AsyncSession = Depends(get_db)):
    repository = ProductRepository(db)
    service = ProductService(repository)
    return await service.list_available()
