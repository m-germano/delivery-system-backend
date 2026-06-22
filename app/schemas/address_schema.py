from decimal import Decimal
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_zip_code(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 8:
        raise ValueError("CEP deve conter exatamente 8 dígitos.")
    return digits


class AddressByZipCodeResponse(BaseModel):
    zip_code: str
    street: str
    complement: str | None = None
    neighborhood: str
    city: str
    state: str
    ibge_code: str | None = None
    provider: str = "ViaCEP"


class GeocodeRequest(BaseModel):
    street: str = Field(min_length=2, max_length=150)
    number: str = Field(min_length=1, max_length=20)
    neighborhood: str | None = Field(default=None, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=2)
    zip_code: str = Field(min_length=8, max_length=20)

    @field_validator("zip_code")
    @classmethod
    def validate_zip_code(cls, value: str) -> str:
        return normalize_zip_code(value)

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str) -> str:
        return value.strip().upper()


class GeocodeResponse(BaseModel):
    latitude: Decimal
    longitude: Decimal
    display_name: str | None = None
    provider: str = "Nominatim/OpenStreetMap"
    raw: dict[str, Any] | None = None


class AddressResolveRequest(BaseModel):
    zip_code: str = Field(min_length=8, max_length=20)
    number: str = Field(min_length=1, max_length=20)
    complement: str | None = Field(default=None, max_length=100)

    @field_validator("zip_code")
    @classmethod
    def validate_zip_code(cls, value: str) -> str:
        return normalize_zip_code(value)


class AddressResolveResponse(BaseModel):
    zip_code: str
    street: str
    number: str
    complement: str | None = None
    neighborhood: str
    city: str
    state: str
    latitude: Decimal
    longitude: Decimal
    display_name: str | None = None
    provider: str = "ViaCEP + Nominatim/OpenStreetMap"


class AddressErrorResponse(BaseModel):
    detail: str

    model_config = ConfigDict(json_schema_extra={"example": {"detail": "CEP não encontrado."}})
