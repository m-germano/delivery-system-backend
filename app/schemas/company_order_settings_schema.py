from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CompanyOrderSettingsUpdateRequest(BaseModel):
    accepts_delivery: bool = True
    accepts_pickup: bool = False
    pickup_discount_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)
    minimum_order_value: Decimal = Field(default=Decimal("0.00"), ge=0)

    @model_validator(mode="after")
    def validate_at_least_one_fulfillment_mode(self):
        if not self.accepts_delivery and not self.accepts_pickup:
            raise ValueError("A empresa deve aceitar delivery, retirada ou ambos.")
        return self


class CompanyOrderSettingsResponse(BaseModel):
    id: int
    company_id: int
    accepts_delivery: bool
    accepts_pickup: bool
    pickup_discount_percent: Decimal
    minimum_order_value: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
