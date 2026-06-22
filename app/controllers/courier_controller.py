from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import require_roles
from app.db.session import get_db
from app.schemas.courier_schema import CourierAvailabilityUpdateRequest, CourierLocationUpdateRequest, CourierResponse
from app.services.courier_service import CourierService

router = APIRouter(prefix="/couriers", tags=["Couriers"])


@router.get("/me", response_model=CourierResponse)
async def get_my_courier_profile(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    return await CourierService(db).get_my_profile(current_user)


@router.patch("/me/availability", response_model=CourierResponse)
async def update_my_availability(
    data: CourierAvailabilityUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    return await CourierService(db).update_availability(data, current_user)


@router.patch("/me/location", response_model=CourierResponse)
async def update_my_location(
    data: CourierLocationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    return await CourierService(db).update_location(data, current_user)
