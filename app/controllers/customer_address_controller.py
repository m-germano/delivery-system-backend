from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import require_roles
from app.db.session import get_db
from app.schemas.customer_address_schema import (
    CustomerAddressCreateRequest,
    CustomerAddressListResponse,
    CustomerAddressResponse,
    CustomerAddressUpdateRequest,
    CustomerLocationStatusResponse,
)
from app.services.customer_address_service import CustomerAddressService

router = APIRouter(prefix="/customer-addresses", tags=["Customer Addresses"])


@router.get("/me", response_model=CustomerAddressListResponse)
async def list_my_addresses(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    addresses = await CustomerAddressService(db).list_my_addresses(current_user)
    return CustomerAddressListResponse(items=addresses, total=len(addresses))


@router.get("/location-status", response_model=CustomerLocationStatusResponse)
async def get_location_status(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    default_address = await CustomerAddressService(db).get_location_status(current_user)
    return CustomerLocationStatusResponse(
        has_active_location=bool(default_address and default_address.latitude is not None and default_address.longitude is not None),
        default_address=default_address,
    )


@router.post("", response_model=CustomerAddressResponse, status_code=status.HTTP_201_CREATED)
async def create_address(
    data: CustomerAddressCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await CustomerAddressService(db).create_address(data, current_user)


@router.put("/{address_id}", response_model=CustomerAddressResponse)
async def update_address(
    address_id: int,
    data: CustomerAddressUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await CustomerAddressService(db).update_address(address_id, data, current_user)


@router.patch("/{address_id}/default", response_model=CustomerAddressResponse)
async def set_default_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    return await CustomerAddressService(db).set_default_address(address_id, current_user)


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles(RoleId.CUSTOMER)),
):
    await CustomerAddressService(db).delete_address(address_id, current_user)
    return None
