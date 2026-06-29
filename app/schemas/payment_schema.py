from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PaymentAccountProviderValue = Literal["mercado_pago"]
PaymentProviderValue = Literal["mercado_pago", "manual", "simulated"]
PaymentMethodValue = Literal["pix", "credit_card", "debit_card", "cash", "simulated"]
PaymentStatusValue = Literal["pending", "in_process", "approved", "rejected", "cancelled", "refunded", "failed", "expired"]


class CompanyPaymentAccountCreateRequest(BaseModel):
    provider: PaymentAccountProviderValue = "mercado_pago"
    provider_user_id: str | None = Field(default=None, max_length=120)
    public_key: str | None = None
    access_token: str = Field(min_length=1)
    refresh_token: str | None = None
    token_expires_at: datetime | None = None

    @field_validator("provider_user_id", "public_key", "access_token", "refresh_token", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None


class CompanyPaymentAccountResponse(BaseModel):
    id: int
    company_id: int
    provider: str
    provider_user_id: str | None = None
    public_key: str | None = None
    token_expires_at: datetime | None = None
    is_active: bool
    connected_at: datetime
    disconnected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CompanyPaymentAccountListResponse(BaseModel):
    items: list[CompanyPaymentAccountResponse]
    total: int


class MercadoPagoConnectUrlResponse(BaseModel):
    authorization_url: str


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    company_id: int
    provider: str
    provider_payment_id: str | None = None
    provider_order_id: str | None = None
    idempotency_key: str | None = None
    payment_method: str | None = None
    status: str
    amount: Decimal
    currency: str
    qr_code: str | None = None
    qr_code_base64: str | None = None
    expires_at: datetime | None = None
    paid_at: datetime | None = None
    cancelled_at: datetime | None = None
    refunded_at: datetime | None = None
    failed_at: datetime | None = None
    provider_status: str | None = None
    provider_status_detail: str | None = None
    raw_status: str | None = None
    raw_status_detail: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int


class CompanyPaymentAvailabilityResponse(BaseModel):
    company_id: int
    mercado_pago_connected: bool
    pix_online_available: bool


class PixOrderCreateResponse(BaseModel):
    order_id: int
    payment_id: int
    provider_payment_id: str | None = None
    payment_status: str
    qr_code: str | None = None
    qr_code_base64: str | None = None
    expires_at: datetime | None = None
    amount: Decimal


class OrderPaymentStatusResponse(BaseModel):
    order_id: int
    order_status: str
    payment_status: str | None = None
    payment: PaymentResponse | None = None
    can_cancel_payment: bool = False
    can_regenerate_pix: bool = False
    can_switch_to_delivery: bool = False
    can_cancel_order: bool = False


class MercadoPagoWebhookResponse(BaseModel):
    received: bool = True
