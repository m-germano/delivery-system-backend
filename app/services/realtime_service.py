from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import redis.asyncio as redis
from fastapi.encoders import jsonable_encoder

from app.core.config import settings


_REDIS_CLIENT: redis.Redis | None = None


class RealtimeEventType:
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_CANCELLED = "order.cancelled"
    DELIVERY_AVAILABLE = "delivery.available"
    DELIVERY_CLAIMED = "delivery.claimed"
    DELIVERY_CANCELLED = "delivery.cancelled"
    DELIVERY_UPDATED = "delivery.updated"


def company_orders_channel(company_id: int) -> str:
    return f"company:{company_id}:orders"


def courier_deliveries_channel() -> str:
    return "courier:deliveries"


async def get_redis_client() -> redis.Redis:
    global _REDIS_CLIENT

    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )

    return _REDIS_CLIENT


async def close_redis_client() -> None:
    global _REDIS_CLIENT

    if _REDIS_CLIENT is not None:
        await _REDIS_CLIENT.aclose()
        _REDIS_CLIENT = None


def _safe_json_dumps(payload: dict[str, Any]) -> str:
    def fallback(value: Any) -> str:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    encoded_payload = jsonable_encoder(payload)
    return json.dumps(encoded_payload, ensure_ascii=False, default=fallback)


async def publish_realtime_event(channel: str, payload: dict[str, Any]) -> None:
    """Publica evento no Redis Pub/Sub sem quebrar a operação principal.

    O PostgreSQL continua sendo a fonte oficial. Se o Redis estiver fora do ar,
    o pedido/entrega continua sendo salvo normalmente; apenas o aviso em tempo
    real deixa de ser entregue.
    """

    try:
        client = await get_redis_client()
        await client.publish(channel, _safe_json_dumps(payload))
    except Exception:
        return


async def publish_company_order_event(company_id: int, payload: dict[str, Any]) -> None:
    await publish_realtime_event(company_orders_channel(company_id), payload)


async def publish_courier_delivery_event(payload: dict[str, Any]) -> None:
    await publish_realtime_event(courier_deliveries_channel(), payload)
