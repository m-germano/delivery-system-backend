from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    company_id: UUID
    name: str
    description: str | None = None
    price: Decimal
    is_available: bool = True


class ProductResponse(BaseModel):
    id: UUID
    company_id: UUID
    name: str
    description: str | None
    price: Decimal
    is_available: bool

    model_config = ConfigDict(from_attributes=True)
