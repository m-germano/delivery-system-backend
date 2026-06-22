from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schemas.address_schema import (
    AddressByZipCodeResponse,
    AddressResolveRequest,
    AddressResolveResponse,
    GeocodeRequest,
    GeocodeResponse,
)
from app.services.address_service import AddressService

router = APIRouter(prefix="/address", tags=["Address"])


@router.get("/zip-code/{zip_code}", response_model=AddressByZipCodeResponse)
async def lookup_zip_code(zip_code: str, _current_user=Depends(get_current_user)):
    return await AddressService().lookup_zip_code(zip_code)


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode_address(data: GeocodeRequest, _current_user=Depends(get_current_user)):
    return await AddressService().geocode(data)


@router.post("/resolve", response_model=AddressResolveResponse)
async def resolve_address(data: AddressResolveRequest, _current_user=Depends(get_current_user)):
    return await AddressService().resolve_by_zip_code(data)
