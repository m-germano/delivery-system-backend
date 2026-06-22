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
