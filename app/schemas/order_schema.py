from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class OrderItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    client_id: UUID
    company_id: UUID
    distance_km: float = Field(ge=0)
    items: list[OrderItemCreate]


class OrderResponse(BaseModel):
    id: UUID | None = None
    status: str
    delivery_fee: Decimal
    total_amount: Decimal
