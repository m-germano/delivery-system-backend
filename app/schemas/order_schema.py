from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import FulfillmentType, OrderStatus, PaymentMethod
from app.schemas.company_schema import CompanyAddressResponse
from app.schemas.customer_address_schema import CustomerAddressResponse


class OrderItemCreateRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=99)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None


class OrderCreateRequest(BaseModel):
    company_id: int = Field(gt=0)
    customer_address_id: int | None = Field(default=None, gt=0)
    fulfillment_type: FulfillmentType = FulfillmentType.DELIVERY
    items: list[OrderItemCreateRequest] = Field(min_length=1)
    payment_method: PaymentMethod = PaymentMethod.PIX
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_single_company_cart(self):
        unique_product_ids = {item.product_id for item in self.items}
        if len(unique_product_ids) != len(self.items):
            raise ValueError("Não envie o mesmo produto mais de uma vez. Some as quantidades no carrinho.")
        return self


class OrderStatusUpdateRequest(BaseModel):
    status: OrderStatus
    confirmation_code: str | None = Field(default=None, min_length=4, max_length=20)


class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    product_id: int
    product_name: str
    unit_price: Decimal
    quantity: int
    total_price: Decimal
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderCompanySummaryResponse(BaseModel):
    id: int
    name: str
    phone: str | None = None
    image_url: str | None = None
    address: CompanyAddressResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderStatusHistoryResponse(BaseModel):
    id: int
    order_id: int
    old_status: str | None = None
    new_status: str
    changed_by_user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderReviewSummaryResponse(BaseModel):
    id: int
    rating: int
    comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(BaseModel):
    id: int
    customer_user_id: int
    company_id: int
    customer_address_id: int | None = None
    fulfillment_type: str
    status: str
    subtotal: Decimal
    discount_amount: Decimal
    pickup_discount_percent: Decimal
    delivery_fee: Decimal
    total: Decimal
    distance_km: Decimal
    payment_method: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse] = Field(default_factory=list)
    status_history: list[OrderStatusHistoryResponse] = Field(default_factory=list)
    company: OrderCompanySummaryResponse | None = None
    customer_address: CustomerAddressResponse | None = None
    delivery_confirmation_code: str | None = None
    pickup_confirmation_code: str | None = None
    can_review: bool = False
    has_review: bool = False
    review: OrderReviewSummaryResponse | None = None
    refund_result: str | None = None
    operation_message: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int


class OrderCalculationItemResponse(BaseModel):
    product_id: int
    product_name: str
    unit_price: Decimal
    quantity: int
    total_price: Decimal


class OrderCalculationResponse(BaseModel):
    company_id: int
    customer_address_id: int | None = None
    fulfillment_type: str
    distance_km: Decimal
    subtotal: Decimal
    discount_amount: Decimal
    pickup_discount_percent: Decimal
    minimum_order_value: Decimal
    delivery_fee: Decimal
    total: Decimal
    items: list[OrderCalculationItemResponse]
