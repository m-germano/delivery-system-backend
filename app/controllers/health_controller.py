from fastapi import APIRouter

from app.core.config import settings
from app.db.init_db import check_database_connection, get_missing_tables
from app.schemas.health_schema import HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    database_ok = await check_database_connection()
    missing_tables = sorted(await get_missing_tables()) if database_ok else []

    return HealthResponse(
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
        database="ok" if database_ok else "unavailable",
        missing_tables=missing_tables,
    )
