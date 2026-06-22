from datetime import datetime
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize_zip_code(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 8:
        raise ValueError("CEP deve conter exatamente 8 dígitos.")
    return digits


class CustomerAddressInput(BaseModel):
    label: str | None = Field(default=None, max_length=60, examples=["Casa"])
    zip_code: str = Field(min_length=8, max_length=20, examples=["01001000"])
    street: str | None = Field(default=None, max_length=150, examples=["Praça da Sé"])
    number: str = Field(min_length=1, max_length=20, examples=["100"])
    complement: str | None = Field(default=None, max_length=100)
    neighborhood: str | None = Field(default=None, max_length=100, examples=["Sé"])
    city: str | None = Field(default=None, max_length=100, examples=["São Paulo"])
    state: str | None = Field(default=None, min_length=2, max_length=2, examples=["SP"])
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    is_default: bool = False

    @field_validator("zip_code")
    @classmethod
    def validate_zip_code(cls, value: str) -> str:
        return normalize_zip_code(value)

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value

    @field_validator("label", "street", "number", "complement", "neighborhood", "city", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None


class CustomerAddressCreateRequest(BaseModel):
    address: CustomerAddressInput
    auto_fill_address: bool = Field(default=True)
    auto_geocode: bool = Field(default=True)

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


class CustomerAddressUpdateRequest(CustomerAddressCreateRequest):
    pass


class CustomerAddressResponse(BaseModel):
    id: int
    user_id: int
    label: str | None = None
    street: str
    number: str
    complement: str | None = None
    neighborhood: str
    city: str
    state: str
    zip_code: str
    latitude: Decimal
    longitude: Decimal
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerAddressListResponse(BaseModel):
    items: list[CustomerAddressResponse]
    total: int


class CustomerLocationStatusResponse(BaseModel):
    has_active_location: bool
    default_address: CustomerAddressResponse | None = None
