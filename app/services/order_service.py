from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DeliveryStatus, FulfillmentType, OrderStatus, PaymentMethod, RoleId
from app.models import Delivery, DeliveryStatusHistory, Order, OrderItem, OrderStatusHistory, User
from app.repositories.company_order_settings_repository import CompanyOrderSettingsRepository
from app.repositories.company_repository import CompanyRepository
from app.repositories.company_review_repository import CompanyReviewRepository
from app.repositories.customer_address_repository import CustomerAddressRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.order_schema import (
    OrderCalculationItemResponse,
    OrderCalculationResponse,
    OrderCreateRequest,
)
from app.schemas.payment_schema import PixOrderCreateResponse
from app.services.delivery_code_service import DeliveryCodeService, PickupCodeService
from app.services.delivery_fee_service import DeliveryFeeCalculator
from app.services.route_service import RouteDistanceService
from app.services.realtime_service import (
    RealtimeEventType,
    publish_company_order_event,
    publish_courier_delivery_event,
)

TERMINAL_ORDER_STATUSES = {
    OrderStatus.DELIVERED.value,
    OrderStatus.PICKED_UP.value,
    OrderStatus.CANCELED.value,
    OrderStatus.REJECTED.value,
}

CANCELABLE_BY_COMPANY_STATUSES = {
    OrderStatus.ACCEPTED.value,
    OrderStatus.IN_PREPARATION.value,
    OrderStatus.READY_FOR_PICKUP.value,
    OrderStatus.WAITING_COURIER.value,
    OrderStatus.OUT_FOR_DELIVERY.value,
}

DELIVERY_COMPANY_STATUS_FLOW = {
    OrderStatus.OPEN.value: {OrderStatus.ACCEPTED.value, OrderStatus.REJECTED.value, OrderStatus.CANCELED.value},
    OrderStatus.ACCEPTED.value: {OrderStatus.IN_PREPARATION.value, OrderStatus.CANCELED.value},
    OrderStatus.IN_PREPARATION.value: {OrderStatus.WAITING_COURIER.value, OrderStatus.CANCELED.value},
    OrderStatus.WAITING_COURIER.value: {OrderStatus.CANCELED.value},
    OrderStatus.OUT_FOR_DELIVERY.value: {OrderStatus.CANCELED.value},
}

PICKUP_COMPANY_STATUS_FLOW = {
    OrderStatus.OPEN.value: {OrderStatus.ACCEPTED.value, OrderStatus.REJECTED.value, OrderStatus.CANCELED.value},
    OrderStatus.ACCEPTED.value: {OrderStatus.IN_PREPARATION.value, OrderStatus.CANCELED.value},
    OrderStatus.IN_PREPARATION.value: {OrderStatus.READY_FOR_PICKUP.value, OrderStatus.CANCELED.value},
    OrderStatus.READY_FOR_PICKUP.value: {OrderStatus.PICKED_UP.value, OrderStatus.CANCELED.value},
}


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repository = OrderRepository(session)
        self.company_repository = CompanyRepository(session)
        self.company_review_repository = CompanyReviewRepository(session)
        self.company_order_settings_repository = CompanyOrderSettingsRepository(session)
        self.customer_address_repository = CustomerAddressRepository(session)
        self.delivery_fee_calculator = DeliveryFeeCalculator()
        self.route_distance_service = RouteDistanceService()

    async def calculate_order(self, data: OrderCreateRequest, current_user: User) -> OrderCalculationResponse:
        self._ensure_customer(current_user)
        company = await self._get_active_company_with_location(data.company_id)
        self._ensure_company_is_open_for_orders(company)
        order_settings = await self.company_order_settings_repository.get_or_create_default(company.id)
        product_map = await self._get_products_for_order(data)

        if any(product.company_id != company.id for product in product_map.values()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Todos os produtos do pedido devem pertencer à mesma empresa selecionada.",
            )

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
        minimum_order_value = Decimal(order_settings.minimum_order_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if subtotal < minimum_order_value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Pedido mínimo desta empresa é de R$ {minimum_order_value}.",
            )

        if data.fulfillment_type == FulfillmentType.PICKUP:
            if not order_settings.accepts_pickup:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Esta empresa não aceita retirada na loja.")

            pickup_discount_percent = Decimal(order_settings.pickup_discount_percent).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            discount_amount = (subtotal * pickup_discount_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            delivery_fee = Decimal("0.00")
            distance_km = Decimal("0.00")
            total = (subtotal - discount_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            return OrderCalculationResponse(
                company_id=company.id,
                customer_address_id=None,
                fulfillment_type=FulfillmentType.PICKUP.value,
                distance_km=distance_km,
                subtotal=subtotal,
                discount_amount=discount_amount,
                pickup_discount_percent=pickup_discount_percent,
                minimum_order_value=minimum_order_value,
                delivery_fee=delivery_fee,
                total=total,
                items=items,
            )

        if not order_settings.accepts_delivery:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Esta empresa não aceita delivery.")

        customer_address = await self._get_customer_address_for_order(data.customer_address_id, current_user.id)
        route_distance = await self.route_distance_service.get_delivery_distance(
            origin_latitude=company.address.latitude,
            origin_longitude=company.address.longitude,
            destination_latitude=customer_address.latitude,
            destination_longitude=customer_address.longitude,
        )
        distance_km = route_distance.distance_km
        delivery_fee = self.delivery_fee_calculator.calculate_for_company(company, distance_km)
        discount_amount = Decimal("0.00")
        pickup_discount_percent = Decimal("0.00")
        total = (subtotal + delivery_fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return OrderCalculationResponse(
            company_id=company.id,
            customer_address_id=customer_address.id,
            fulfillment_type=FulfillmentType.DELIVERY.value,
            distance_km=distance_km,
            subtotal=subtotal,
            discount_amount=discount_amount,
            pickup_discount_percent=pickup_discount_percent,
            minimum_order_value=minimum_order_value,
            delivery_fee=delivery_fee,
            total=total,
            items=items,
        )

    async def create_order(self, data: OrderCreateRequest, current_user: User) -> Order:
        if data.payment_method == PaymentMethod.PIX_ONLINE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Use a rota /orders/pix para criar pedidos com Pix online.",
            )

        order = await self._create_order_with_status(data, current_user, OrderStatus.OPEN.value)
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

    async def create_pix_online_order(self, data: OrderCreateRequest, current_user: User) -> PixOrderCreateResponse:
        # Alias legado: a rota /orders/pix continua existindo para não quebrar o frontend,
        # mas o fluxo atual cria uma preferência de Checkout Pro no Mercado Pago.
        return await self.create_checkout_pro_order(data, current_user)

    async def create_checkout_pro_order(self, data: OrderCreateRequest, current_user: User) -> PixOrderCreateResponse:
        from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService

        data.payment_method = PaymentMethod.PIX_ONLINE
        payment_service = MercadoPagoPixPaymentService(self.session)

        calculation = await self.calculate_order(data, current_user)
        if not await payment_service.is_checkout_pro_available_for_company(calculation.company_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Empresa não possui Mercado Pago conectado.")

        order = await self._create_order_with_status(data, current_user, OrderStatus.PENDING_PAYMENT.value)

        try:
            payment = await payment_service.create_checkout_pro_payment_for_order(order, current_user)
        except HTTPException:
            await self.session.rollback()
            raise
        except Exception:
            await self.session.rollback()
            raise

        return PixOrderCreateResponse(
            order_id=order.id,
            payment_id=payment.id,
            provider_payment_id=payment.provider_payment_id,
            provider_order_id=payment.provider_order_id,
            checkout_preference_id=payment.checkout_preference_id,
            checkout_url=payment.checkout_url,
            sandbox_checkout_url=payment.sandbox_checkout_url,
            payment_status=payment.status,
            qr_code=payment.qr_code,
            qr_code_base64=payment.qr_code_base64,
            expires_at=payment.expires_at,
            amount=payment.amount,
        )

    async def _create_order_with_status(self, data: OrderCreateRequest, current_user: User, initial_status: str) -> Order:
        calculation = await self.calculate_order(data, current_user)
        product_map = await self._get_products_for_order(data)

        order = Order(
            customer_user_id=current_user.id,
            company_id=calculation.company_id,
            customer_address_id=calculation.customer_address_id,
            fulfillment_type=calculation.fulfillment_type,
            status=initial_status,
            subtotal=calculation.subtotal,
            discount_amount=calculation.discount_amount,
            pickup_discount_percent=calculation.pickup_discount_percent,
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
                new_status=initial_status,
                changed_by_user_id=current_user.id,
            )
        )

        await self.session.flush()
        return order

    async def list_my_orders(self, current_user: User, *, limit: int = 50, offset: int = 0) -> tuple[list[Order], int]:
        self._ensure_customer(current_user)
        orders, total = await self.order_repository.list_by_customer(current_user.id, limit=limit, offset=offset)
        self._attach_customer_delivery_codes(orders)
        await self._attach_order_review_flags(orders)
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
        self._ensure_company(current_user)
        order = await self._get_order_or_404(order_id)
        company = await self.company_repository.get_by_owner_user_id(current_user.id)

        if company is None or order.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        if order.status == OrderStatus.REJECTED.value:
            return await self._get_visible_order(order.id, current_user)

        if order.status in TERMINAL_ORDER_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido já está em status final.")

        if order.status != OrderStatus.OPEN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pedido já foi aceito. Use a opção de cancelar.",
            )

        refund_result = None
        if order.payment_method == PaymentMethod.PIX_ONLINE.value:
            from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService

            try:
                refund_result = await MercadoPagoPixPaymentService(self.session).handle_order_rejected_by_company(order)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Pedido pago online, mas houve problema ao processar o reembolso. Tente novamente.",
                )
            setattr(order, "refund_result", refund_result)

        rejected_order = await self._change_company_order_status(order_id, OrderStatus.REJECTED.value, current_user)
        self._attach_company_close_message(rejected_order, action="recusado", refund_result=refund_result)
        return rejected_order

    async def cancel_order_by_company(self, order_id: int, current_user: User) -> Order:
        self._ensure_company(current_user)
        order = await self._get_order_or_404(order_id)
        company = await self.company_repository.get_by_owner_user_id(current_user.id)

        if company is None or order.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        if order.status == OrderStatus.CANCELED.value:
            return await self._get_visible_order(order.id, current_user)

        if order.status in {OrderStatus.DELIVERED.value, OrderStatus.PICKED_UP.value, OrderStatus.REJECTED.value}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido já está em status final.")

        if order.status in {OrderStatus.OPEN.value, OrderStatus.PENDING_PAYMENT.value}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pedido ainda não foi aceito. Use a opção de recusar.",
            )

        if order.status not in CANCELABLE_BY_COMPANY_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Pedido não pode ser cancelado no status atual: {order.status}.",
            )

        refund_result = None
        if order.payment_method == PaymentMethod.PIX_ONLINE.value:
            from app.services.mercado_pago_pix_payment_service import MercadoPagoPixPaymentService

            try:
                refund_result = await MercadoPagoPixPaymentService(self.session).handle_order_cancelled_by_company(order)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Pedido pago online, mas houve problema ao processar o reembolso. Tente novamente.",
                )
            setattr(order, "refund_result", refund_result)

        await self._apply_order_status(order, OrderStatus.CANCELED.value, current_user.id)
        cancelled_delivery = await self._cancel_delivery_if_exists(order, current_user.id)
        await self.session.commit()

        await publish_company_order_event(
            order.company_id,
            {
                "type": RealtimeEventType.ORDER_CANCELLED,
                "order_id": order.id,
                "company_id": order.company_id,
                "status": OrderStatus.CANCELED.value,
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
        cancelled_order = await self._get_visible_order(order.id, current_user)
        self._attach_company_close_message(cancelled_order, action="cancelado", refund_result=refund_result)
        return cancelled_order

    async def cancel_order_by_customer(self, order_id: int, current_user: User) -> Order:
        self._ensure_customer(current_user)
        order = await self._get_order_or_404(order_id)

        if order.customer_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        if order.status not in {OrderStatus.OPEN.value, OrderStatus.PENDING_PAYMENT.value}:
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

    async def update_company_status(
        self,
        order_id: int,
        new_status: OrderStatus,
        current_user: User,
        confirmation_code: str | None = None,
    ) -> Order:
        if new_status in {OrderStatus.ACCEPTED, OrderStatus.REJECTED, OrderStatus.CANCELED}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Use as rotas específicas de aceitar, recusar ou cancelar para esta transição.",
            )
        return await self._change_company_order_status(
            order_id,
            new_status.value,
            current_user,
            confirmation_code=confirmation_code,
        )

    async def _change_company_order_status(
        self,
        order_id: int,
        new_status: str,
        current_user: User,
        *,
        company_cancel: bool = False,
        confirmation_code: str | None = None,
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

        status_flow = PICKUP_COMPANY_STATUS_FLOW if order.fulfillment_type == FulfillmentType.PICKUP.value else DELIVERY_COMPANY_STATUS_FLOW
        allowed_statuses = status_flow.get(order.status, set())
        if new_status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transição inválida: {order.status} -> {new_status}.",
            )

        if order.fulfillment_type == FulfillmentType.PICKUP.value and new_status == OrderStatus.PICKED_UP.value:
            self._validate_pickup_confirmation(order, confirmation_code)

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
        if order.fulfillment_type != FulfillmentType.DELIVERY.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pedidos de retirada não podem ser enviados para entregador.",
            )

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

    @staticmethod
    def _validate_pickup_confirmation(order: Order, confirmation_code: str | None) -> None:
        if order.fulfillment_type != FulfillmentType.PICKUP.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido não é de retirada.")

        if order.status == OrderStatus.PICKED_UP.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido já foi retirado.")

        if order.status != OrderStatus.READY_FOR_PICKUP.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido não está pronto para retirada.")

        if not PickupCodeService.is_valid_code(order, confirmation_code):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Código de retirada inválido.")

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
            await self._attach_order_review_flag(order)
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
        delivery_code = None
        pickup_code = None

        if order.status == OrderStatus.OUT_FOR_DELIVERY.value and order.delivery is not None:
            delivery_code = DeliveryCodeService.generate_code(order.delivery)

        if order.fulfillment_type == FulfillmentType.PICKUP.value and order.status == OrderStatus.READY_FOR_PICKUP.value:
            pickup_code = PickupCodeService.generate_code(order)

        setattr(order, "delivery_confirmation_code", delivery_code)
        setattr(order, "pickup_confirmation_code", pickup_code)

    @staticmethod
    def _attach_company_close_message(order: Order, *, action: str, refund_result: str | None) -> None:
        message = f"Pedido {action}."
        if refund_result in {"refunded", "already_refunded"}:
            message = f"Pedido {action} e reembolso solicitado/realizado."
        elif refund_result == "cancelled_pending":
            message = f"Pedido {action} e cobrança Pix pendente cancelada."

        setattr(order, "refund_result", refund_result)
        setattr(order, "operation_message", message)

    async def _attach_order_review_flags(self, orders: list[Order]) -> None:
        reviews_by_order_id = await self.company_review_repository.list_by_order_ids([order.id for order in orders])
        for order in orders:
            self._set_order_review_flags(order, reviews_by_order_id.get(order.id))

    async def _attach_order_review_flag(self, order: Order) -> None:
        review = await self.company_review_repository.get_by_order_id(order.id)
        self._set_order_review_flags(order, review)

    @staticmethod
    def _set_order_review_flags(order: Order, review) -> None:
        has_review = review is not None
        can_review = order.status in {OrderStatus.DELIVERED.value, OrderStatus.PICKED_UP.value} and not has_review
        setattr(order, "has_review", has_review)
        setattr(order, "can_review", can_review)
        setattr(order, "review", review)

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

    @staticmethod
    def _ensure_company_is_open_for_orders(company) -> None:
        if not getattr(company, "is_open", False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A loja está fechada no momento.",
            )

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
