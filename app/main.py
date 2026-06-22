from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.controllers import (
    address_controller,
    auth_controller,
    company_controller,
    courier_controller,
    customer_address_controller,
    delivery_controller,
    health_controller,
    order_controller,
    product_controller,
    realtime_controller,
    tracking_controller,
)
from app.core.config import settings
from app.db.init_db import create_database_schema, ensure_schema_compatibility, seed_initial_roles, verify_required_tables
from app.services.realtime_service import close_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.AUTO_CREATE_TABLES:
        await create_database_schema()
        await seed_initial_roles()

    await ensure_schema_compatibility()

    if settings.VERIFY_TABLES_ON_STARTUP:
        await verify_required_tables()

    yield

    await close_redis_client()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="API REST do MVP acadêmico de um sistema de delivery.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_controller.router, prefix=settings.API_PREFIX)
app.include_router(auth_controller.router, prefix=settings.API_PREFIX)
app.include_router(address_controller.router, prefix=settings.API_PREFIX)
app.include_router(company_controller.router, prefix=settings.API_PREFIX)
app.include_router(customer_address_controller.router, prefix=settings.API_PREFIX)
app.include_router(courier_controller.router, prefix=settings.API_PREFIX)
app.include_router(product_controller.router, prefix=settings.API_PREFIX)
app.include_router(order_controller.router, prefix=settings.API_PREFIX)
app.include_router(delivery_controller.router, prefix=settings.API_PREFIX)
app.include_router(tracking_controller.http_router, prefix=settings.API_PREFIX)
app.include_router(realtime_controller.router)
app.include_router(tracking_controller.router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": f"{settings.API_PREFIX}/health",
    }
