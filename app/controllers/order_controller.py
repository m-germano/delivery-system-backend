from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.order_repository import OrderRepository
from app.schemas.order_schema import OrderCreate, OrderResponse
from app.services.delivery_fee_strategy import BasicDistanceFeeStrategy
from app.services.order_service import OrderService

router = APIRouter()


@router.post("", response_model=OrderResponse)
async def create_order(data: OrderCreate, db: AsyncSession = Depends(get_db)):
    repository = OrderRepository(db)
    fee_strategy = BasicDistanceFeeStrategy()
    service = OrderService(repository, fee_strategy)
    return await service.create_order(data)
