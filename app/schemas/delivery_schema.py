from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DeliveryStatus
from app.schemas.order_schema import OrderResponse


class DeliveryStatusUpdateRequest(BaseModel):
    status: DeliveryStatus


class DeliveryFinishRequest(BaseModel):
    confirmation_code: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$")


class DeliveryStatusHistoryResponse(BaseModel):
    id: int
    delivery_id: int
    old_status: str | None = None
    new_status: str
    changed_by_user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliveryResponse(BaseModel):
    id: int
    order_id: int
    courier_user_id: int | None = None
    status: str
    pickup_latitude: Decimal
    pickup_longitude: Decimal
    destination_latitude: Decimal
    destination_longitude: Decimal
    distance_km: Decimal
    delivery_fee: Decimal
    accepted_at: datetime | None = None
    picked_up_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    order: OrderResponse | None = None
    status_history: list[DeliveryStatusHistoryResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class DeliveryListResponse(BaseModel):
    items: list[DeliveryResponse]
    total: int
