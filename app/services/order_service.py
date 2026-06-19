from decimal import Decimal

from app.models.order import Order, OrderStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.order_schema import OrderCreate, OrderResponse
from app.services.delivery_fee_strategy import DeliveryFeeStrategy


class OrderService:
    def __init__(self, repository: OrderRepository, fee_strategy: DeliveryFeeStrategy):
        self.repository = repository
        self.fee_strategy = fee_strategy

    async def create_order(self, data: OrderCreate) -> OrderResponse:
        delivery_fee = self.fee_strategy.calculate(data.distance_km)

        # MVP: cálculo real dos produtos será implementado quando o repositório de produtos estiver completo.
        products_total = Decimal("0.00")
        total_amount = products_total + delivery_fee

        order = Order(
            client_id=data.client_id,
            company_id=data.company_id,
            status=OrderStatus.CREATED,
            delivery_fee=delivery_fee,
            total_amount=total_amount,
        )
        created = await self.repository.create(order)

        return OrderResponse(
            id=created.id,
            status=created.status.value,
            delivery_fee=created.delivery_fee,
            total_amount=created.total_amount,
        )
