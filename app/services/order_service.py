from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DeliveryStatus, OrderStatus, RoleId
from app.models import Delivery, DeliveryStatusHistory, Order, OrderItem, OrderStatusHistory, User
from app.repositories.company_repository import CompanyRepository
from app.repositories.customer_address_repository import CustomerAddressRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.order_schema import (
    OrderCalculationItemResponse,
    OrderCalculationResponse,
    OrderCreateRequest,
)
from app.services.delivery_code_service import DeliveryCodeService
from app.services.delivery_fee_service import DeliveryFeeCalculator
from app.services.route_service import RouteDistanceService
from app.services.realtime_service import (
    RealtimeEventType,
    publish_company_order_event,
    publish_courier_delivery_event,
)

TERMINAL_ORDER_STATUSES = {
    OrderStatus.DELIVERED.value,
    OrderStatus.CANCELED.value,
    OrderStatus.REJECTED.value,
}

COMPANY_STATUS_FLOW = {
    OrderStatus.OPEN.value: {OrderStatus.ACCEPTED.value, OrderStatus.REJECTED.value, OrderStatus.CANCELED.value},
    OrderStatus.ACCEPTED.value: {OrderStatus.IN_PREPARATION.value, OrderStatus.CANCELED.value},
    OrderStatus.IN_PREPARATION.value: {OrderStatus.WAITING_COURIER.value, OrderStatus.CANCELED.value},
    OrderStatus.WAITING_COURIER.value: {OrderStatus.CANCELED.value},
    OrderStatus.OUT_FOR_DELIVERY.value: {OrderStatus.CANCELED.value},
}


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repository = OrderRepository(session)
        self.company_repository = CompanyRepository(session)
        self.customer_address_repository = CustomerAddressRepository(session)
        self.delivery_fee_calculator = DeliveryFeeCalculator()
        self.route_distance_service = RouteDistanceService()

    async def calculate_order(self, data: OrderCreateRequest, current_user: User) -> OrderCalculationResponse:
        self._ensure_customer(current_user)
        company = await self._get_active_company_with_location(data.company_id)
        customer_address = await self._get_customer_address_for_order(data.customer_address_id, current_user.id)
        product_map = await self._get_products_for_order(data)

        if any(product.company_id != company.id for product in product_map.values()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Todos os produtos do pedido devem pertencer à mesma empresa selecionada.",
            )

        route_distance = await self.route_distance_service.get_delivery_distance(
            origin_latitude=company.address.latitude,
            origin_longitude=company.address.longitude,
            destination_latitude=customer_address.latitude,
            destination_longitude=customer_address.longitude,
        )
        distance_km = route_distance.distance_km
        delivery_fee = self.delivery_fee_calculator.calculate_for_company(company, distance_km)

        subtotal = Decimal("0.00")
        items: list[OrderCalculationItemResponse] = []
        for item in data.items:
            product = product_map[item.product_id]
            total_price = (Decimal(product.price) * item.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            subtotal += total_price
            items.append(
                OrderCalculationItemResponse(
                    product_id=product.id,
                    product_name=product.name,
                    unit_price=product.price,
                    quantity=item.quantity,
                    total_price=total_price,
                )
            )

        subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = (subtotal + delivery_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return OrderCalculationResponse(
            company_id=company.id,
            customer_address_id=customer_address.id,
            distance_km=distance_km,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            total=total,
            items=items,
        )

    async def create_order(self, data: OrderCreateRequest, current_user: User) -> Order:
        calculation = await self.calculate_order(data, current_user)
        product_map = await self._get_products_for_order(data)

        order = Order(
            customer_user_id=current_user.id,
            company_id=calculation.company_id,
            customer_address_id=calculation.customer_address_id,
            status=OrderStatus.OPEN.value,
            subtotal=calculation.subtotal,
            delivery_fee=calculation.delivery_fee,
            total=calculation.total,
            distance_km=calculation.distance_km,
            payment_method=data.payment_method.value,
            notes=data.notes,
        )
        self.session.add(order)
        await self.session.flush()

        for item in data.items:
            product = product_map[item.product_id]
            total_price = (Decimal(product.price) * item.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            self.session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    product_name=product.name,
                    unit_price=product.price,
                    quantity=item.quantity,
                    total_price=total_price,
                    notes=item.notes,
                )
            )

        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=None,
                new_status=OrderStatus.OPEN.value,
                changed_by_user_id=current_user.id,
            )
        )

        await self.session.commit()

        await publish_company_order_event(
            order.company_id,
            {
                "type": RealtimeEventType.ORDER_CREATED,
                "order_id": order.id,
                "company_id": order.company_id,
                "status": OrderStatus.OPEN.value,
                "message": f"Novo pedido #{order.id} recebido.",
            },
        )

        return await self._get_visible_order(order.id, current_user)

    async def list_my_orders(self, current_user: User, *, limit: int = 50, offset: int = 0) -> tuple[list[Order], int]:
        self._ensure_customer(current_user)
        orders, total = await self.order_repository.list_by_customer(current_user.id, limit=limit, offset=offset)
        self._attach_customer_delivery_codes(orders)
        return orders, total

    async def list_company_orders(self, current_user: User, *, limit: int = 50, offset: int = 0) -> tuple[list[Order], int]:
        self._ensure_company(current_user)
        company = await self.company_repository.get_by_owner_user_id(current_user.id)
        if company is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Configure sua empresa antes de consultar pedidos.")
        return await self.order_repository.list_by_company(company.id, limit=limit, offset=offset)

    async def list_all_orders(self, current_user: User, *, limit: int = 50, offset: int = 0) -> tuple[list[Order], int]:
        self._ensure_admin(current_user)
        return await self.order_repository.list_all(limit=limit, offset=offset)

    async def get_order(self, order_id: int, current_user: User) -> Order:
        return await self._get_visible_order(order_id, current_user)

    async def accept_order(self, order_id: int, current_user: User) -> Order:
        return await self._change_company_order_status(order_id, OrderStatus.ACCEPTED.value, current_user)

    async def reject_order(self, order_id: int, current_user: User) -> Order:
        return await self._change_company_order_status(order_id, OrderStatus.REJECTED.value, current_user)

    async def cancel_order_by_company(self, order_id: int, current_user: User) -> Order:
        return await self._change_company_order_status(order_id, OrderStatus.CANCELED.value, current_user, company_cancel=True)

    async def cancel_order_by_customer(self, order_id: int, current_user: User) -> Order:
        self._ensure_customer(current_user)
        order = await self._get_order_or_404(order_id)

        if order.customer_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        if order.status != OrderStatus.OPEN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O cliente só pode cancelar o pedido antes da confirmação pelo estabelecimento.",
            )

        await self._apply_order_status(order, OrderStatus.CANCELED.value, current_user.id)
        await self.session.commit()

        await publish_company_order_event(
            order.company_id,
            {
                "type": RealtimeEventType.ORDER_CANCELLED,
                "order_id": order.id,
                "company_id": order.company_id,
                "status": OrderStatus.CANCELED.value,
                "message": f"Pedido #{order.id} cancelado pelo cliente.",
            },
        )
        await self._broadcast_tracking_snapshot(order.id, "ORDER_STATUS_UPDATED")

        return await self._get_visible_order(order.id, current_user)

    async def confirm_received_by_customer(self, order_id: int, current_user: User) -> Order:
        self._ensure_customer(current_user)
        order = await self._get_order_or_404(order_id)

        if order.customer_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        from app.services.delivery_service import DeliveryService

        await DeliveryService(self.session).confirm_received_by_customer(order, current_user)
        await self.session.commit()

        await publish_company_order_event(
            order.company_id,
            {
                "type": RealtimeEventType.ORDER_UPDATED,
                "order_id": order.id,
                "company_id": order.company_id,
                "status": OrderStatus.DELIVERED.value,
                "message": f"Pedido #{order.id} entregue.",
            },
        )
        await self._broadcast_tracking_snapshot(order.id, "ORDER_STATUS_UPDATED")

        return await self._get_visible_order(order.id, current_user)

    async def update_company_status(self, order_id: int, new_status: OrderStatus, current_user: User) -> Order:
        if new_status in {OrderStatus.ACCEPTED, OrderStatus.REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Use as rotas específicas de aceitar ou recusar para esta transição.",
            )
        return await self._change_company_order_status(order_id, new_status.value, current_user)

    async def _change_company_order_status(
        self,
        order_id: int,
        new_status: str,
        current_user: User,
        *,
        company_cancel: bool = False,
    ) -> Order:
        self._ensure_company(current_user)
        order = await self._get_order_or_404(order_id)
        company = await self.company_repository.get_by_owner_user_id(current_user.id)

        if company is None or order.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        if order.status in TERMINAL_ORDER_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido já está em status final.")

        if company_cancel and new_status == OrderStatus.CANCELED.value:
            await self._apply_order_status(order, new_status, current_user.id)
            cancelled_delivery = await self._cancel_delivery_if_exists(order, current_user.id)
            await self.session.commit()

            await publish_company_order_event(
                order.company_id,
                {
                    "type": RealtimeEventType.ORDER_CANCELLED,
                    "order_id": order.id,
                    "company_id": order.company_id,
                    "status": new_status,
                    "message": f"Pedido #{order.id} cancelado pela empresa.",
                },
            )

            if cancelled_delivery is not None:
                await publish_courier_delivery_event(
                    {
                        "type": RealtimeEventType.DELIVERY_CANCELLED,
                        "delivery_id": cancelled_delivery.id,
                        "order_id": order.id,
                        "status": DeliveryStatus.CANCELED.value,
                        "message": f"Entrega #{cancelled_delivery.id} cancelada.",
                    }
                )

            await self._broadcast_tracking_snapshot(order.id, "ORDER_STATUS_UPDATED")
            return await self._get_visible_order(order.id, current_user)

        allowed_statuses = COMPANY_STATUS_FLOW.get(order.status, set())
        if new_status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transição inválida: {order.status} -> {new_status}.",
            )

        await self._apply_order_status(order, new_status, current_user.id)

        created_delivery = None
        cancelled_delivery = None

        if new_status == OrderStatus.WAITING_COURIER.value:
            created_delivery = await self._create_delivery_if_missing(order, current_user.id)

        if new_status == OrderStatus.CANCELED.value:
            cancelled_delivery = await self._cancel_delivery_if_exists(order, current_user.id)

        await self.session.commit()

        event_type = RealtimeEventType.ORDER_UPDATED
        if new_status == OrderStatus.CANCELED.value:
            event_type = RealtimeEventType.ORDER_CANCELLED

        await publish_company_order_event(
            order.company_id,
            {
                "type": event_type,
                "order_id": order.id,
                "company_id": order.company_id,
                "status": new_status,
                "message": f"Pedido #{order.id} atualizado para {new_status}.",
            },
        )

        if created_delivery is not None:
            await publish_courier_delivery_event(
                {
                    "type": RealtimeEventType.DELIVERY_AVAILABLE,
                    "delivery_id": created_delivery.id,
                    "order_id": order.id,
                    "status": DeliveryStatus.AVAILABLE.value,
                    "message": f"Nova entrega #{created_delivery.id} disponível.",
                }
            )

        if cancelled_delivery is not None:
            await publish_courier_delivery_event(
                {
                    "type": RealtimeEventType.DELIVERY_CANCELLED,
                    "delivery_id": cancelled_delivery.id,
                    "order_id": order.id,
                    "status": DeliveryStatus.CANCELED.value,
                    "message": f"Entrega #{cancelled_delivery.id} cancelada.",
                }
            )

        await self._broadcast_tracking_snapshot(order.id, "ORDER_STATUS_UPDATED")
        return await self._get_visible_order(order.id, current_user)

    async def _broadcast_tracking_snapshot(self, order_id: int, event_type: str = "TRACKING_SNAPSHOT") -> None:
        try:
            from app.services.tracking_service import TrackingService

            await TrackingService(self.session).broadcast_order_snapshot(order_id, event_type)
        except Exception:
            return

    async def _apply_order_status(self, order: Order, new_status: str, changed_by_user_id: int) -> None:
        old_status = order.status
        order.status = new_status
        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_user_id=changed_by_user_id,
            )
        )
        await self.session.flush()

    async def _create_delivery_if_missing(self, order: Order, changed_by_user_id: int) -> Delivery | None:
        if order.delivery is not None:
            return None

        company = await self._get_active_company_with_location(order.company_id)
        customer_address = await self.customer_address_repository.get_by_id(order.customer_address_id)
        if customer_address is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Endereço do cliente não encontrado.")

        delivery = Delivery(
            order_id=order.id,
            courier_user_id=None,
            status=DeliveryStatus.AVAILABLE.value,
            pickup_latitude=company.address.latitude,
            pickup_longitude=company.address.longitude,
            destination_latitude=customer_address.latitude,
            destination_longitude=customer_address.longitude,
            distance_km=order.distance_km,
            delivery_fee=order.delivery_fee,
        )
        self.session.add(delivery)
        await self.session.flush()
        self.session.add(
            DeliveryStatusHistory(
                delivery_id=delivery.id,
                old_status=None,
                new_status=DeliveryStatus.AVAILABLE.value,
                changed_by_user_id=changed_by_user_id,
            )
        )

        return delivery

    async def _cancel_delivery_if_exists(self, order: Order, changed_by_user_id: int) -> Delivery | None:
        if order.delivery is None or order.delivery.status in {DeliveryStatus.FINISHED.value, DeliveryStatus.CANCELED.value}:
            return None

        old_status = order.delivery.status
        order.delivery.status = DeliveryStatus.CANCELED.value
        self.session.add(
            DeliveryStatusHistory(
                delivery_id=order.delivery.id,
                old_status=old_status,
                new_status=DeliveryStatus.CANCELED.value,
                changed_by_user_id=changed_by_user_id,
            )
        )

        return order.delivery

    async def _get_visible_order(self, order_id: int, current_user: User) -> Order:
        order = await self._get_order_or_404(order_id)
        role_id = RoleId(current_user.role_id)

        if role_id == RoleId.ADMIN:
            return order

        if role_id == RoleId.CUSTOMER and order.customer_user_id == current_user.id:
            self._attach_customer_delivery_code(order)
            return order

        if role_id == RoleId.COMPANY:
            company = await self.company_repository.get_by_owner_user_id(current_user.id)
            if company and order.company_id == company.id:
                return order

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")


    def _attach_customer_delivery_codes(self, orders: list[Order]) -> None:
        for order in orders:
            self._attach_customer_delivery_code(order)

    @staticmethod
    def _attach_customer_delivery_code(order: Order) -> None:
        code = None

        if order.status == OrderStatus.OUT_FOR_DELIVERY.value and order.delivery is not None:
            code = DeliveryCodeService.generate_code(order.delivery)

        setattr(order, "delivery_confirmation_code", code)

    async def _get_order_or_404(self, order_id: int) -> Order:
        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")
        return order

    async def _get_active_company_with_location(self, company_id: int):
        company = await self.company_repository.get_by_id(company_id)
        if company is None or not company.is_active or company.address is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa não encontrada ou sem endereço ativo.")

        if company.address.latitude is None or company.address.longitude is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Empresa sem latitude/longitude configurada.")

        return company

    async def _get_customer_address_for_order(self, customer_address_id: int | None, customer_user_id: int):
        if customer_address_id:
            address = await self.customer_address_repository.get_by_id(customer_address_id)
            if address is None or address.user_id != customer_user_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endereço do cliente não encontrado.")
        else:
            address = await self.customer_address_repository.get_default_by_user_id(customer_user_id)

        if address is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cadastre um endereço padrão com latitude e longitude antes de fazer pedidos.",
            )

        if address.latitude is None or address.longitude is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Endereço do cliente sem latitude/longitude configurada.",
            )

        return address

    async def _get_products_for_order(self, data: OrderCreateRequest):
        product_ids = [item.product_id for item in data.items]
        products = await self.order_repository.get_active_products_by_ids(product_ids)
        product_map = {product.id: product for product in products}
        missing_product_ids = [product_id for product_id in product_ids if product_id not in product_map]

        if missing_product_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Produtos inválidos ou indisponíveis: {missing_product_ids}.",
            )

        return product_map

    @staticmethod
    def _ensure_customer(current_user: User) -> None:
        if current_user.role_id != RoleId.CUSTOMER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas clientes podem executar esta operação.")

    @staticmethod
    def _ensure_company(current_user: User) -> None:
        if current_user.role_id != RoleId.COMPANY:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas empresas podem executar esta operação.")

    @staticmethod
    def _ensure_admin(current_user: User) -> None:
        if current_user.role_id != RoleId.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas administradores podem executar esta operação.")

