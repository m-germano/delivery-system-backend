from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserResponse(BaseModel):
    id: int
    role_id: int
    name: str
    email: EmailStr
    phone: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserRegisterRequest(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role_id: int = Field(ge=2, le=4, description="2=COMPANY, 3=COURIER, 4=CUSTOMER. Admin não é criado pelo cadastro público.")
    phone: str | None = Field(default=None, max_length=30)


class UserCompletionResponse(BaseModel):
    role_id: int
    role_key: str
    is_complete: bool
    next_path: str | None = None
    message: str | None = None
    missing_steps: list[str] = Field(default_factory=list)
