from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException, WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DeliveryStatus, RoleId
from app.core.security import decode_access_token
from app.models import CompanyAddress, CustomerAddress, Delivery, Order, User
from app.repositories.company_repository import CompanyRepository
from app.repositories.courier_repository import CourierRepository
from app.repositories.delivery_repository import DeliveryRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.user_repository import UserRepository
from app.schemas.tracking_schema import DeliveryLocationUpdateRequest, TrackingSnapshotResponse
from app.services.tracking_connection_manager import tracking_manager


class TrackingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repository = OrderRepository(session)
        self.delivery_repository = DeliveryRepository(session)
        self.company_repository = CompanyRepository(session)
        self.courier_repository = CourierRepository(session)
        self.user_repository = UserRepository(session)

    async def authenticate_websocket_user(self, token: str | None, websocket: WebSocket) -> User | None:
        if not token:
            await websocket.close(code=1008, reason="Token obrigatório.")
            return None

        try:
            payload = decode_access_token(token)
            user_id = int(payload.get("sub"))
        except Exception:
            await websocket.close(code=1008, reason="Token inválido.")
            return None

        user = await self.user_repository.get_by_id(user_id)
        if user is None or not user.is_active:
            await websocket.close(code=1008, reason="Usuário inválido.")
            return None

        return user

    async def get_tracking_snapshot(self, order_id: int, current_user: User) -> TrackingSnapshotResponse:
        order = await self._get_visible_order_or_404(order_id, current_user)
        return await self._build_snapshot(order)

    async def update_delivery_location(
        self,
        delivery_id: int,
        data: DeliveryLocationUpdateRequest,
        current_user: User,
    ) -> TrackingSnapshotResponse:
        if current_user.role_id != RoleId.COURIER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas entregadores podem atualizar localização.")

        delivery = await self.delivery_repository.get_by_id(delivery_id)
        if delivery is None or delivery.courier_user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrega não encontrada.")

        if delivery.status in {DeliveryStatus.FINISHED.value, DeliveryStatus.CANCELED.value}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Entrega finalizada ou cancelada não recebe localização.")

        if delivery.status not in {DeliveryStatus.ACCEPTED.value, DeliveryStatus.PICKED_UP.value, DeliveryStatus.ON_ROUTE.value}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A localização só pode ser enviada durante uma entrega aceita.")

        courier = await self.courier_repository.get_or_create_by_user_id(current_user.id)
        courier.current_latitude = data.latitude
        courier.current_longitude = data.longitude
        courier.updated_at = datetime.utcnow()

        await self.session.commit()

        snapshot = await self._build_snapshot(await self._get_order_by_id_or_404(delivery.order_id))
        await tracking_manager.broadcast_to_order(
            delivery.order_id,
            "DELIVERY_LOCATION_UPDATED",
            {
                "order_id": snapshot.order_id,
                "delivery_id": delivery.id,
                "courier_location": snapshot.courier_location.model_dump() if snapshot.courier_location else None,
                "order_status": snapshot.order_status,
                "delivery_status": snapshot.delivery.status if snapshot.delivery else None,
            },
        )
        return snapshot

    async def broadcast_order_snapshot(self, order_id: int, event_type: str = "TRACKING_SNAPSHOT") -> None:
        order = await self._get_order_by_id_or_404(order_id)
        snapshot = await self._build_snapshot(order)
        await tracking_manager.broadcast_to_order(order_id, event_type, snapshot.model_dump())

    async def _get_visible_order_or_404(self, order_id: int, current_user: User) -> Order:
        order = await self._get_order_by_id_or_404(order_id)
        role_id = RoleId(current_user.role_id)

        if role_id == RoleId.ADMIN:
            return order

        if role_id == RoleId.CUSTOMER and order.customer_user_id == current_user.id:
            return order

        if role_id == RoleId.COMPANY:
            company = await self.company_repository.get_by_owner_user_id(current_user.id)
            if company and order.company_id == company.id:
                return order

        if role_id == RoleId.COURIER and order.delivery and order.delivery.courier_user_id == current_user.id:
            return order

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acompanhamento não encontrado.")

    async def _get_order_by_id_or_404(self, order_id: int) -> Order:
        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido não encontrado.")
        return order

    async def _build_snapshot(self, order: Order) -> TrackingSnapshotResponse:
        company = order.company
        company_address = company.address if company else None
        customer_address = order.customer_address

        if company is None or company_address is None or customer_address is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pedido sem dados suficientes para acompanhamento.")

        delivery = order.delivery
        courier_location = None
        if delivery and delivery.courier_user_id:
            courier = await self.courier_repository.get_by_user_id(delivery.courier_user_id)
            if courier and courier.current_latitude is not None and courier.current_longitude is not None:
                courier_location = {
                    "latitude": courier.current_latitude,
                    "longitude": courier.current_longitude,
                    "accuracy": None,
                    "speed": None,
                    "heading": None,
                    "updated_at": courier.updated_at,
                }

        return TrackingSnapshotResponse(
            order_id=order.id,
            order_status=order.status,
            delivery=(
                {
                    "id": delivery.id,
                    "status": delivery.status,
                    "courier_user_id": delivery.courier_user_id,
                    "distance_km": delivery.distance_km,
                    "delivery_fee": delivery.delivery_fee,
                    "accepted_at": delivery.accepted_at,
                    "delivered_at": delivery.delivered_at,
                }
                if delivery
                else None
            ),
            company={
                "id": company.id,
                "name": company.name,
                "address": self._format_company_address(company_address),
                "latitude": company_address.latitude,
                "longitude": company_address.longitude,
            },
            customer={
                "address": self._format_customer_address(customer_address),
                "latitude": customer_address.latitude,
                "longitude": customer_address.longitude,
            },
            courier_location=courier_location,
            updated_at=datetime.utcnow(),
        )

    @staticmethod
    def _format_company_address(address: CompanyAddress) -> str:
        return ", ".join(
            part
            for part in [
                f"{address.street}, {address.number}",
                address.neighborhood,
                f"{address.city}/{address.state}",
                address.zip_code,
            ]
            if part
        )

    @staticmethod
    def _format_customer_address(address: CustomerAddress) -> str:
        return ", ".join(
            part
            for part in [
                f"{address.street}, {address.number}",
                address.neighborhood,
                f"{address.city}/{address.state}",
                address.zip_code,
            ]
            if part
        )
