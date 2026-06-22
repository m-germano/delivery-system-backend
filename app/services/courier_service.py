from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.models import Courier, User
from app.repositories.courier_repository import CourierRepository
from app.schemas.courier_schema import CourierAvailabilityUpdateRequest, CourierLocationUpdateRequest


class CourierService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.courier_repository = CourierRepository(session)

    async def get_my_profile(self, current_user: User) -> Courier:
        self._ensure_courier(current_user)
        courier = await self.courier_repository.get_or_create_by_user_id(current_user.id)
        await self.session.commit()
        return courier

    async def update_availability(self, data: CourierAvailabilityUpdateRequest, current_user: User) -> Courier:
        self._ensure_courier(current_user)
        courier = await self.courier_repository.get_or_create_by_user_id(current_user.id)

        courier.is_available = data.is_available
        if data.vehicle_type is not None:
            courier.vehicle_type = data.vehicle_type
        if data.vehicle_plate is not None:
            courier.vehicle_plate = data.vehicle_plate
        if data.current_latitude is not None:
            courier.current_latitude = data.current_latitude
        if data.current_longitude is not None:
            courier.current_longitude = data.current_longitude

        await self.session.commit()
        await self.session.refresh(courier)
        return courier

    async def update_location(self, data: CourierLocationUpdateRequest, current_user: User) -> Courier:
        self._ensure_courier(current_user)
        courier = await self.courier_repository.get_or_create_by_user_id(current_user.id)
        courier.current_latitude = data.current_latitude
        courier.current_longitude = data.current_longitude
        await self.session.commit()
        await self.session.refresh(courier)
        return courier

    @staticmethod
    def _ensure_courier(current_user: User) -> None:
        if current_user.role_id != RoleId.COURIER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas entregadores podem executar esta operação.")
