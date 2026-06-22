from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CourierAvailabilityUpdateRequest(BaseModel):
    is_available: bool
    vehicle_type: str | None = Field(default=None, max_length=50)
    vehicle_plate: str | None = Field(default=None, max_length=20)
    current_latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    current_longitude: Decimal | None = Field(default=None, ge=-180, le=180)

    @field_validator("vehicle_type", "vehicle_plate", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None

    @model_validator(mode="after")
    def normalize_vehicle_plate(self):
        if self.vehicle_plate:
            self.vehicle_plate = self.vehicle_plate.upper()
        return self


class CourierLocationUpdateRequest(BaseModel):
    current_latitude: Decimal = Field(ge=-90, le=90)
    current_longitude: Decimal = Field(ge=-180, le=180)


class CourierResponse(BaseModel):
    id: int
    user_id: int
    vehicle_type: str | None = None
    vehicle_plate: str | None = None
    is_available: bool
    current_latitude: Decimal | None = None
    current_longitude: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
