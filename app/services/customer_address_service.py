from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CustomerAddress, User
from app.repositories.customer_address_repository import CustomerAddressRepository
from app.schemas.customer_address_schema import CustomerAddressCreateRequest, CustomerAddressInput, CustomerAddressUpdateRequest
from app.services.address_service import AddressService


class CustomerAddressService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CustomerAddressRepository(session)
        self.address_service = AddressService()

    async def list_my_addresses(self, current_user: User) -> list[CustomerAddress]:
        return await self.repository.list_by_user_id(current_user.id)

    async def get_location_status(self, current_user: User) -> CustomerAddress | None:
        return await self.repository.get_default_by_user_id(current_user.id)

    async def create_address(self, data: CustomerAddressCreateRequest, current_user: User) -> CustomerAddress:
        completed_address = await self._complete_address(
            data.address,
            auto_fill_address=data.auto_fill_address,
            auto_geocode=data.auto_geocode,
        )

        existing_addresses = await self.repository.list_by_user_id(current_user.id)
        should_be_default = completed_address.is_default or len(existing_addresses) == 0

        if should_be_default:
            await self._clear_default_addresses(current_user.id)

        address = CustomerAddress(
            user_id=current_user.id,
            label=completed_address.label,
            street=str(completed_address.street),
            number=completed_address.number,
            complement=completed_address.complement,
            neighborhood=str(completed_address.neighborhood),
            city=str(completed_address.city),
            state=str(completed_address.state),
            zip_code=completed_address.zip_code,
            latitude=completed_address.latitude,
            longitude=completed_address.longitude,
            is_default=should_be_default,
        )

        self.session.add(address)
        await self.session.commit()
        await self.session.refresh(address)
        return address

    async def update_address(self, address_id: int, data: CustomerAddressUpdateRequest, current_user: User) -> CustomerAddress:
        address = await self._get_owned_address(address_id, current_user.id)
        completed_address = await self._complete_address(
            data.address,
            auto_fill_address=data.auto_fill_address,
            auto_geocode=data.auto_geocode,
        )

        if completed_address.is_default:
            await self._clear_default_addresses(current_user.id)

        address.label = completed_address.label
        address.street = str(completed_address.street)
        address.number = completed_address.number
        address.complement = completed_address.complement
        address.neighborhood = str(completed_address.neighborhood)
        address.city = str(completed_address.city)
        address.state = str(completed_address.state)
        address.zip_code = completed_address.zip_code
        address.latitude = completed_address.latitude
        address.longitude = completed_address.longitude
        address.is_default = completed_address.is_default or address.is_default

        await self.session.commit()
        await self.session.refresh(address)
        return address

    async def set_default_address(self, address_id: int, current_user: User) -> CustomerAddress:
        address = await self._get_owned_address(address_id, current_user.id)
        await self._clear_default_addresses(current_user.id)
        address.is_default = True
        await self.session.commit()
        await self.session.refresh(address)
        return address

    async def delete_address(self, address_id: int, current_user: User) -> None:
        address = await self._get_owned_address(address_id, current_user.id)
        await self.session.delete(address)
        await self.session.commit()

    async def _get_owned_address(self, address_id: int, user_id: int) -> CustomerAddress:
        address = await self.repository.get_by_id(address_id)
        if address is None or address.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endereço não encontrado.")
        return address

    async def _clear_default_addresses(self, user_id: int) -> None:
        addresses = await self.repository.list_by_user_id(user_id)
        for address in addresses:
            address.is_default = False
        await self.session.flush()

    async def _complete_address(
        self,
        address: CustomerAddressInput,
        *,
        auto_fill_address: bool,
        auto_geocode: bool,
    ) -> CustomerAddressInput:
        completed_address = address.model_copy(deep=True)

        missing_address_fields = any(
            value is None
            for value in [
                completed_address.street,
                completed_address.neighborhood,
                completed_address.city,
                completed_address.state,
            ]
        )

        if auto_fill_address and missing_address_fields:
            zip_result = await self.address_service.lookup_zip_code(completed_address.zip_code)
            completed_address.street = completed_address.street or zip_result.street
            completed_address.neighborhood = completed_address.neighborhood or zip_result.neighborhood
            completed_address.city = completed_address.city or zip_result.city
            completed_address.state = completed_address.state or zip_result.state
            completed_address.complement = completed_address.complement or zip_result.complement

        required_fields = {
            "street": completed_address.street,
            "neighborhood": completed_address.neighborhood,
            "city": completed_address.city,
            "state": completed_address.state,
        }
        missing_fields = [field_name for field_name, value in required_fields.items() if not value]
        if missing_fields:
            raise HTTPException(
                status_code=422,
                detail=f"Endereço incompleto. Campos faltando: {', '.join(missing_fields)}.",
            )

        if auto_geocode and (completed_address.latitude is None or completed_address.longitude is None):
            geocode_result = await self.address_service.geocode(
                data=self.address_service_geocode_request(completed_address)
            )
            completed_address.latitude = geocode_result.latitude
            completed_address.longitude = geocode_result.longitude

        if completed_address.latitude is None or completed_address.longitude is None:
            raise HTTPException(
                status_code=422,
                detail="Latitude e longitude são obrigatórias para salvar o endereço do cliente.",
            )

        return completed_address

    @staticmethod
    def address_service_geocode_request(address: CustomerAddressInput):
        from app.schemas.address_schema import GeocodeRequest

        return GeocodeRequest(
            street=str(address.street),
            number=address.number,
            neighborhood=address.neighborhood,
            city=str(address.city),
            state=str(address.state),
            zip_code=address.zip_code,
        )
