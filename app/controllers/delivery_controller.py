from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import get_current_user, require_roles
from app.db.session import get_db
from app.schemas.delivery_schema import DeliveryFinishRequest, DeliveryListResponse, DeliveryResponse, DeliveryStatusUpdateRequest
from app.schemas.tracking_schema import DeliveryLocationUpdateRequest, TrackingSnapshotResponse
from app.services.delivery_service import DeliveryService
from app.services.tracking_service import TrackingService

router = APIRouter(prefix="/deliveries", tags=["Deliveries"])


@router.get("/available", response_model=DeliveryListResponse)
async def list_available_deliveries(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    deliveries, total = await DeliveryService(db).list_available(current_user, limit=limit, offset=offset)
    return DeliveryListResponse(items=deliveries, total=total)


@router.get("/my", response_model=DeliveryListResponse)
async def list_my_deliveries(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    deliveries, total = await DeliveryService(db).list_my_deliveries(current_user, limit=limit, offset=offset)
    return DeliveryListResponse(items=deliveries, total=total)


@router.get("/{delivery_id}", response_model=DeliveryResponse)
async def get_delivery(
    delivery_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await DeliveryService(db).get_delivery(delivery_id, current_user)


@router.patch("/{delivery_id}/accept", response_model=DeliveryResponse)
async def accept_delivery(
    delivery_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    return await DeliveryService(db).accept_delivery(delivery_id, current_user)


@router.patch("/{delivery_id}/finish", response_model=DeliveryResponse)
async def finish_delivery(
    delivery_id: int,
    data: DeliveryFinishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    return await DeliveryService(db).finish_delivery(delivery_id, current_user, data.confirmation_code)


@router.patch("/{delivery_id}/location", response_model=TrackingSnapshotResponse)
async def update_delivery_location(
    delivery_id: int,
    data: DeliveryLocationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    return await TrackingService(db).update_delivery_location(delivery_id, data, current_user)


@router.patch("/{delivery_id}/status", response_model=DeliveryResponse)
async def update_delivery_status(
    delivery_id: int,
    data: DeliveryStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.COURIER)),
):
    return await DeliveryService(db).update_status(delivery_id, data.status, current_user)
