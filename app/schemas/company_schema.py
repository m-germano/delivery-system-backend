from datetime import datetime
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_zip_code(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 8:
        raise ValueError("CEP deve conter exatamente 8 dígitos.")
    return digits


class CompanyAddressInput(BaseModel):
    zip_code: str = Field(min_length=8, max_length=20, examples=["01001000"])
    street: str | None = Field(default=None, max_length=150, examples=["Praça da Sé"])
    number: str = Field(min_length=1, max_length=20, examples=["100"])
    complement: str | None = Field(default=None, max_length=100)
    neighborhood: str | None = Field(default=None, max_length=100, examples=["Sé"])
    city: str | None = Field(default=None, max_length=100, examples=["São Paulo"])
    state: str | None = Field(default=None, min_length=2, max_length=2, examples=["SP"])
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)

    @field_validator("zip_code")
    @classmethod
    def validate_zip_code(cls, value: str) -> str:
        return normalize_zip_code(value)

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value

    @field_validator("street", "number", "complement", "neighborhood", "city", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None


class CompanyCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None
    phone: str | None = Field(default=None, max_length=30)
    document: str | None = Field(default=None, max_length=30)
    image_url: str | None = None
    address: CompanyAddressInput
    auto_fill_address: bool = Field(default=True, description="Quando true, completa rua/bairro/cidade/UF pelo CEP se algum campo estiver faltando.")
    auto_geocode: bool = Field(default=True, description="Quando true, busca latitude/longitude se as coordenadas não forem enviadas.")

    @field_validator("name", "phone", "document", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_address_completion_strategy(self):
        required_address_fields = [
            self.address.street,
            self.address.neighborhood,
            self.address.city,
            self.address.state,
        ]
        if not self.auto_fill_address and any(value is None for value in required_address_fields):
            raise ValueError("Endereço incompleto. Envie rua, bairro, cidade e UF ou use auto_fill_address=true.")

        if not self.auto_geocode and (self.address.latitude is None or self.address.longitude is None):
            raise ValueError("Latitude e longitude são obrigatórias quando auto_geocode=false.")

        return self


class CompanyUpdateRequest(CompanyCreateRequest):
    pass


class CompanyAddressResponse(BaseModel):
    id: int
    street: str
    number: str
    complement: str | None = None
    neighborhood: str
    city: str
    state: str
    zip_code: str
    latitude: Decimal
    longitude: Decimal

    model_config = ConfigDict(from_attributes=True)


class CompanyResponse(BaseModel):
    id: int
    owner_user_id: int
    name: str
    description: str | None = None
    phone: str | None = None
    document: str | None = None
    image_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    address: CompanyAddressResponse
    average_rating: Decimal | None = None
    reviews_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class CompanyListResponse(BaseModel):
    items: list[CompanyResponse]
    total: int


class CompanyNearbyResponse(CompanyResponse):
    distance_km: Decimal
    delivery_fee: Decimal


class CompanyNearbyListResponse(BaseModel):
    items: list[CompanyNearbyResponse]
    total: int
