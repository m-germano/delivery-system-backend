from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCategoryCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    display_order: int = Field(default=0, ge=0)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("description", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None


class ProductCategoryUpdateRequest(ProductCategoryCreateRequest):
    is_active: bool = True


class ProductCategoryResponse(BaseModel):
    id: int
    company_id: int
    name: str
    description: str | None = None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductCreateRequest(BaseModel):
    category_id: int | None = None
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    image_url: str | None = None
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("description", "image_url", mode="before")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = str(value).strip()
        return stripped or None


class ProductUpdateRequest(ProductCreateRequest):
    pass


class ProductResponse(BaseModel):
    id: int
    company_id: int
    category_id: int | None = None
    name: str
    description: str | None = None
    price: Decimal
    image_url: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    category: ProductCategoryResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
