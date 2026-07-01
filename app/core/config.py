from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Delivery System API"
    APP_ENV: Literal["development", "test", "production"] = "development"
    APP_VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"

    DATABASE_URL: str = "postgresql+asyncpg://delivery_user:delivery_pass@localhost:5432/delivery_db"
    DATABASE_ECHO: bool = False

    REDIS_URL: str = "redis://localhost:6379/0"

    AUTO_CREATE_TABLES: bool = True
    VERIFY_TABLES_ON_STARTUP: bool = True

    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])

    SECRET_KEY: str = "change-me-in-development"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    JWT_ALGORITHM: str = "HS256"
    TOKEN_ENCRYPTION_KEY: str | None = None

    BACKEND_PUBLIC_URL: str | None = None
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    MERCADO_PAGO_CLIENT_ID: str | None = None
    MERCADO_PAGO_CLIENT_SECRET: str | None = None
    MERCADO_PAGO_USE_PKCE: bool = True
    MERCADO_PAGO_REDIRECT_URI: str | None = None
    MERCADO_PAGO_OAUTH_AUTHORIZE_URL: str = "https://auth.mercadopago.com.br/authorization"
    MERCADO_PAGO_OAUTH_TOKEN_URL: str = "https://api.mercadopago.com/oauth/token"
    MERCADO_PAGO_PAYMENTS_URL: str = "https://api.mercadopago.com/v1/payments"
    MERCADO_PAGO_CHECKOUT_PREFERENCES_URL: str = "https://api.mercadopago.com/checkout/preferences"
    MERCADO_PAGO_WEBHOOK_URL: str | None = None
    MERCADO_PAGO_WEBHOOK_SECRET: str | None = None
    MERCADO_PAGO_WEBHOOK_TOLERANCE_SECONDS: int = 600
    MERCADO_PAGO_PIX_EXPIRATION_MINUTES: int = 30
    MERCADO_PAGO_CHECKOUT_EXPIRATION_MINUTES: int | None = None
    MERCADO_PAGO_CHECKOUT_SUCCESS_URL: str | None = None
    MERCADO_PAGO_CHECKOUT_PENDING_URL: str | None = None
    MERCADO_PAGO_CHECKOUT_FAILURE_URL: str | None = None

    FRONTEND_MERCADO_PAGO_SUCCESS_URL: str = "http://localhost:5173/company/mercado-pago?connected=true"
    FRONTEND_MERCADO_PAGO_ERROR_URL: str = "http://localhost:5173/company/mercado-pago?connected=false"

    VIACEP_BASE_URL: str = "https://viacep.com.br/ws"
    NOMINATIM_BASE_URL: str = "https://nominatim.openstreetmap.org"
    OSRM_BASE_URL: str = "https://router.project-osrm.org"
    USE_REAL_ROUTE_DISTANCE: bool = True
    GEOCODING_USER_AGENT: str = "DeliverySystemAPI/0.1.0"
    NOMINATIM_EMAIL: str | None = None
    EXTERNAL_API_TIMEOUT_SECONDS: float = 8.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
