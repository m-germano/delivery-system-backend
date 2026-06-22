from decimal import Decimal
import re
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.schemas.address_schema import (
    AddressByZipCodeResponse,
    AddressResolveRequest,
    AddressResolveResponse,
    GeocodeRequest,
    GeocodeResponse,
)
from app.schemas.company_schema import CompanyAddressInput


class AddressService:
    """Integrações externas para CEP e geocodificação.

    ViaCEP completa dados do endereço pelo CEP.
    Nominatim/OpenStreetMap transforma o endereço em latitude/longitude.
    """

    @staticmethod
    def normalize_zip_code(zip_code: str) -> str:
        digits = re.sub(r"\D", "", zip_code or "")
        if len(digits) != 8:
            raise HTTPException(
                status_code=422,
                detail="CEP deve conter exatamente 8 dígitos.",
            )
        return digits

    async def lookup_zip_code(self, zip_code: str) -> AddressByZipCodeResponse:
        normalized_zip_code = self.normalize_zip_code(zip_code)
        url = f"{settings.VIACEP_BASE_URL.rstrip('/')}/{normalized_zip_code}/json/"

        try:
            async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Não foi possível consultar o CEP no momento.",
            ) from exc

        if response.status_code == status.HTTP_400_BAD_REQUEST:
            raise HTTPException(status_code=422, detail="CEP inválido.")

        if response.status_code >= 500:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço de CEP indisponível no momento.",
            )

        response.raise_for_status()
        payload = response.json()

        if payload.get("erro") is True:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CEP não encontrado.")

        return AddressByZipCodeResponse(
            zip_code=normalized_zip_code,
            street=(payload.get("logradouro") or "").strip(),
            complement=(payload.get("complemento") or None),
            neighborhood=(payload.get("bairro") or "").strip(),
            city=(payload.get("localidade") or "").strip(),
            state=(payload.get("uf") or "").strip().upper(),
            ibge_code=payload.get("ibge") or None,
        )

    async def geocode(self, data: GeocodeRequest) -> GeocodeResponse:
        params: dict[str, Any] = {
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "countrycodes": "br",
            "street": f"{data.number} {data.street}",
            "city": data.city,
            "state": data.state,
            "postalcode": data.zip_code,
        }

        headers = {
            "User-Agent": settings.GEOCODING_USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
        }

        if settings.NOMINATIM_EMAIL:
            params["email"] = settings.NOMINATIM_EMAIL

        try:
            async with httpx.AsyncClient(timeout=settings.EXTERNAL_API_TIMEOUT_SECONDS, headers=headers) as client:
                response = await client.get(f"{settings.NOMINATIM_BASE_URL.rstrip('/')}/search", params=params)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Não foi possível consultar latitude e longitude no momento.",
            ) from exc

        if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Limite de consultas de geocodificação atingido. Tente novamente mais tarde.",
            )

        if response.status_code >= 500:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço de geocodificação indisponível no momento.",
            )

        response.raise_for_status()
        payload = response.json()

        if not payload:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Não foi possível encontrar latitude e longitude para o endereço informado.",
            )

        first_result = payload[0]
        return GeocodeResponse(
            latitude=Decimal(str(first_result["lat"])),
            longitude=Decimal(str(first_result["lon"])),
            display_name=first_result.get("display_name"),
            raw=first_result,
        )

    async def resolve_by_zip_code(self, data: AddressResolveRequest) -> AddressResolveResponse:
        address = await self.lookup_zip_code(data.zip_code)
        geocode = await self.geocode(
            GeocodeRequest(
                street=address.street,
                number=data.number,
                neighborhood=address.neighborhood,
                city=address.city,
                state=address.state,
                zip_code=address.zip_code,
            )
        )

        return AddressResolveResponse(
            zip_code=address.zip_code,
            street=address.street,
            number=data.number,
            complement=data.complement,
            neighborhood=address.neighborhood,
            city=address.city,
            state=address.state,
            latitude=geocode.latitude,
            longitude=geocode.longitude,
            display_name=geocode.display_name,
        )

    async def complete_company_address(
        self,
        address: CompanyAddressInput,
        *,
        auto_fill_address: bool,
        auto_geocode: bool,
    ) -> CompanyAddressInput:
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
            zip_result = await self.lookup_zip_code(completed_address.zip_code)
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
            geocode_result = await self.geocode(
                GeocodeRequest(
                    street=str(completed_address.street),
                    number=completed_address.number,
                    neighborhood=completed_address.neighborhood,
                    city=str(completed_address.city),
                    state=str(completed_address.state),
                    zip_code=completed_address.zip_code,
                )
            )
            completed_address.latitude = geocode_result.latitude
            completed_address.longitude = geocode_result.longitude

        if completed_address.latitude is None or completed_address.longitude is None:
            raise HTTPException(
                status_code=422,
                detail="Latitude e longitude são obrigatórias para salvar o endereço da empresa.",
            )

        return completed_address
