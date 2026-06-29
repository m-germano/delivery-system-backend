from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompanyReviewCreateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment", mode="before")
    @classmethod
    def strip_optional_comment(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None


class CompanyReviewCustomerResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class CompanyReviewOrderResponse(BaseModel):
    id: int
    status: str
    fulfillment_type: str
    total: Decimal

    model_config = ConfigDict(from_attributes=True)


class CompanyReviewResponse(BaseModel):
    id: int
    company_id: int
    customer_user_id: int
    order_id: int
    rating: int
    comment: str | None = None
    created_at: datetime
    updated_at: datetime
    customer: CompanyReviewCustomerResponse | None = None
    order: CompanyReviewOrderResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class CompanyReviewListResponse(BaseModel):
    items: list[CompanyReviewResponse]
    total: int
    page: int
    limit: int
    total_pages: int
    average_rating: Decimal | None = None
    reviews_count: int


class CompanyReviewSummaryResponse(BaseModel):
    company_id: int
    average_rating: Decimal | None = None
    reviews_count: int
