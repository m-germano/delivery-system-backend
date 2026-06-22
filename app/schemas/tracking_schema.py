from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CoordinateResponse(BaseModel):
    latitude: Decimal
    longitude: Decimal


class TrackingCompanyResponse(BaseModel):
    id: int
    name: str
    address: str | None = None
    latitude: Decimal
    longitude: Decimal


class TrackingCustomerResponse(BaseModel):
    address: str | None = None
    latitude: Decimal
    longitude: Decimal


class TrackingCourierLocationResponse(BaseModel):
    latitude: Decimal
    longitude: Decimal
    accuracy: float | None = None
    speed: float | None = None
    heading: float | None = None
    updated_at: datetime | None = None


class TrackingDeliveryResponse(BaseModel):
    id: int
    status: str
    courier_user_id: int | None = None
    distance_km: Decimal
    delivery_fee: Decimal
    accepted_at: datetime | None = None
    delivered_at: datetime | None = None


class TrackingSnapshotResponse(BaseModel):
    order_id: int
    order_status: str
    delivery: TrackingDeliveryResponse | None = None
    company: TrackingCompanyResponse
    customer: TrackingCustomerResponse
    courier_location: TrackingCourierLocationResponse | None = None
    updated_at: datetime


class TrackingEventResponse(BaseModel):
    type: Literal[
        "TRACKING_SNAPSHOT",
        "DELIVERY_LOCATION_UPDATED",
        "ORDER_STATUS_UPDATED",
        "DELIVERY_STATUS_UPDATED",
        "TRACKING_ERROR",
    ]
    data: dict


class DeliveryLocationUpdateRequest(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = Field(default=None, ge=0)
    heading: float | None = Field(default=None, ge=0, le=360)
