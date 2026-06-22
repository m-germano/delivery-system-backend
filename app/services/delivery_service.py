from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DeliveryStatus, OrderStatus, RoleId
from app.models import Delivery, DeliveryStatusHistory, Order, OrderStatusHistory, User
from app.repositories.courier_repository import CourierRepository
from app.repositories.delivery_repository import DeliveryRepository
from app.services.delivery_code_service import DeliveryCodeService
from app.services.realtime_service import (
    RealtimeEventType,
    publish_company_order_event,
    publish_courier_delivery_event,
)

TERMINAL_DELIVERY_STATUSES = {
    DeliveryStatus.FINISHED.value,
    DeliveryStatus.CANCELED.value,
}

ACTIVE_DELIVERY_STATUSES = {
    DeliveryStatus.ACCEPTED.value,
    DeliveryStatus.PICKED_UP.value,
    DeliveryStatus.ON_ROUTE.value,
}


class DeliveryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.delivery_repository = DeliveryRepository(session)
        self.courier_repository = CourierRepository(session)

    async def list_available(self, current_user: User, *, limit: int = 50, offset: int = 0) -> tuple[list[Delivery], int]:
        self._ensure_courier(current_user)
        await self.courier_repository.get_or_create_by_user_id(current_user.id)
        await self.session.commit()
        return await self.delivery_repository.list_available(limit=limit, offset=offset)

    async def list_my_deliveries(self, current_user: User, *, limit: int = 50, offset: int = 0) -> tuple[list[Delivery], int]:
        self._ensure_courier(current_user)
        await self.courier_repository.get_or_create_by_user_id(current_user.id)
        await self.session.commit()
        return await self.delivery_repository.list_by_courier(current_user.id, limit=limit, offset=offset)

    async def get_delivery(self, delivery_id: int, current_user: User) -> Delivery:
        delivery = await self._get_delivery_or_404(delivery_id)
        role_id = RoleId(current_user.role_id)

        if role_id == RoleId.ADMIN:
            return delivery

        if role_id == RoleId.COURIER and delivery.courier_user_id == current_user.id:
            return delivery

        if role_id == RoleId.COURIER and delivery.status == DeliveryStatus.AVAILABLE.value and delivery.courier_user_id is None:
            return delivery

        if role_id == RoleId.CUSTOMER and delivery.order.customer_user_id == current_user.id:
            return delivery

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrega não encontrada.")

    async def accept_delivery(self, delivery_id: int, current_user: User) -> Delivery:
        self._ensure_courier(current_user)
        courier = await self.courier_repository.get_or_create_by_user_id(current_user.id)

        if not courier.is_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Marque seu status como disponível antes de aceitar entregas.",
            )

        if await self.delivery_repository.has_active_delivery(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Finalize sua entrega em andamento antes de aceitar outra.",
            )

        delivery = await self._get_delivery_or_404(delivery_id)
        if delivery.courier_user_id is not None or delivery.status != DeliveryStatus.AVAILABLE.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta entrega não está mais disponível.")

        if delivery.order.status != OrderStatus.WAITING_COURIER.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O pedido não está aguardando entregador.")

        now = datetime.utcnow()
        delivery.courier_user_id = current_user.id
        delivery.accepted_at = now
        await self._apply_delivery_status(delivery, DeliveryStatus.ON_ROUTE.value, current_user.id)
        await self._apply_order_status(delivery.order, OrderStatus.OUT_FOR_DELIVERY.value, current_user.id)
        courier.is_available = False

        await self.session.commit()

        await publish_courier_delivery_event(
            {
                "type": RealtimeEventType.DELIVERY_CLAIMED,
                "delivery_id": delivery.id,
                "order_id": delivery.order_id,
                "courier_user_id": current_user.id,
                "status": DeliveryStatus.ON_ROUTE.value,
                "message": f"Entrega #{delivery.id} aceita por outro entregador.",
            }
        )
        await publish_company_order_event(
            delivery.order.company_id,
            {
                "type": RealtimeEventType.ORDER_UPDATED,
                "order_id": delivery.order_id,
                "company_id": delivery.order.company_id,
                "status": OrderStatus.OUT_FOR_DELIVERY.value,
                "message": f"Pedido #{delivery.order_id} saiu para entrega.",
            },
        )
        await self._broadcast_tracking_snapshot(delivery.order_id, "ORDER_STATUS_UPDATED")

        return await self._get_delivery_or_404(delivery.id)

    async def finish_delivery(self, delivery_id: int, current_user: User, confirmation_code: str) -> Delivery:
        self._ensure_courier(current_user)
        delivery = await self._get_delivery_or_404(delivery_id)

        if delivery.courier_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrega não encontrada.")

        if not DeliveryCodeService.is_valid_code(delivery, confirmation_code):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Código de confirmação inválido. Peça o código de 4 dígitos ao cliente.",
            )

        await self._finish_delivery_and_order(delivery, current_user.id)
        await self.session.commit()

        await publish_company_order_event(
            delivery.order.company_id,
            {
                "type": RealtimeEventType.ORDER_UPDATED,
                "order_id": delivery.order_id,
                "company_id": delivery.order.company_id,
                "status": OrderStatus.DELIVERED.value,
                "message": f"Pedido #{delivery.order_id} entregue.",
            },
        )
        await publish_courier_delivery_event(
            {
                "type": RealtimeEventType.DELIVERY_UPDATED,
                "delivery_id": delivery.id,
                "order_id": delivery.order_id,
                "status": DeliveryStatus.FINISHED.value,
                "message": f"Entrega #{delivery.id} finalizada.",
            }
        )
        await self._broadcast_tracking_snapshot(delivery.order_id, "ORDER_STATUS_UPDATED")

        return await self._get_delivery_or_404(delivery.id)

    async def update_status(self, delivery_id: int, new_status: DeliveryStatus, current_user: User) -> Delivery:
        self._ensure_courier(current_user)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Use a rota de finalizar entrega informando o código de 4 dígitos do cliente.",
        )

    async def confirm_received_by_customer(self, order: Order, current_user: User) -> None:
        if current_user.role_id != RoleId.CUSTOMER or order.customer_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A entrega deve ser finalizada pelo entregador usando o código de 4 dígitos exibido para o cliente.",
        )

    async def _finish_delivery_and_order(self, delivery: Delivery, changed_by_user_id: int) -> None:
        if delivery.status in TERMINAL_DELIVERY_STATUSES or delivery.order.status == OrderStatus.DELIVERED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta entrega já foi finalizada.")

        if delivery.order.status != OrderStatus.OUT_FOR_DELIVERY.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A entrega só pode ser finalizada quando o pedido estiver em entrega.",
            )

        if delivery.status not in ACTIVE_DELIVERY_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entrega não está em andamento.")

        now = datetime.utcnow()
        delivery.delivered_at = now
        await self._apply_delivery_status(delivery, DeliveryStatus.FINISHED.value, changed_by_user_id)
        await self._apply_order_status(delivery.order, OrderStatus.DELIVERED.value, changed_by_user_id)

        if delivery.courier_user_id:
            courier = await self.courier_repository.get_by_user_id(delivery.courier_user_id)
            if courier is not None:
                courier.is_available = True

    async def _broadcast_tracking_snapshot(self, order_id: int, event_type: str = "TRACKING_SNAPSHOT") -> None:
        try:
            from app.services.tracking_service import TrackingService

            await TrackingService(self.session).broadcast_order_snapshot(order_id, event_type)
        except Exception:
            return

    async def _apply_delivery_status(self, delivery: Delivery, new_status: str, changed_by_user_id: int) -> None:
        old_status = delivery.status
        delivery.status = new_status
        self.session.add(
            DeliveryStatusHistory(
                delivery_id=delivery.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_user_id=changed_by_user_id,
            )
        )
        await self.session.flush()

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

    async def _get_delivery_or_404(self, delivery_id: int) -> Delivery:
        delivery = await self.delivery_repository.get_by_id(delivery_id)
        if delivery is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrega não encontrada.")
        return delivery

    @staticmethod
    def _ensure_courier(current_user: User) -> None:
        if current_user.role_id != RoleId.COURIER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas entregadores podem executar esta operação.")
