import json
from datetime import datetime
from decimal import Decimal

import pytest

from app.services import realtime_service
from app.services.realtime_service import (
    RealtimeEventType,
    company_orders_channel,
    courier_deliveries_channel,
    publish_company_order_event,
    publish_courier_delivery_event,
    publish_realtime_event,
)


class FakeRedisClient:
    def __init__(self):
        self.messages = []

    async def publish(self, channel, payload):
        self.messages.append((channel, payload))
        return 1


class FailingRedisClient:
    async def publish(self, channel, payload):
        raise RuntimeError("Redis fora do ar")


@pytest.mark.asyncio
async def test_publish_realtime_event_serializes_decimal_and_datetime(monkeypatch):
    fake_client = FakeRedisClient()

    async def fake_get_redis_client():
        return fake_client

    monkeypatch.setattr(realtime_service, "get_redis_client", fake_get_redis_client)

    await publish_realtime_event(
        "test:channel",
        {
            "type": RealtimeEventType.ORDER_CREATED,
            "delivery_fee": Decimal("7.50"),
            "created_at": datetime(2026, 6, 21, 10, 15, 0),
        },
    )

    assert len(fake_client.messages) == 1
    channel, payload = fake_client.messages[0]
    decoded_payload = json.loads(payload)

    assert channel == "test:channel"
    assert decoded_payload["type"] == "order.created"
    assert decoded_payload["delivery_fee"] == 7.5
    assert decoded_payload["created_at"] == "2026-06-21T10:15:00"


@pytest.mark.asyncio
async def test_publish_realtime_event_does_not_break_when_redis_fails(monkeypatch):
    async def fake_get_redis_client():
        return FailingRedisClient()

    monkeypatch.setattr(realtime_service, "get_redis_client", fake_get_redis_client)

    await publish_realtime_event("test:channel", {"type": "test"})


@pytest.mark.asyncio
async def test_publish_company_and_courier_helpers_use_expected_channels(monkeypatch):
    fake_client = FakeRedisClient()

    async def fake_get_redis_client():
        return fake_client

    monkeypatch.setattr(realtime_service, "get_redis_client", fake_get_redis_client)

    await publish_company_order_event(15, {"type": RealtimeEventType.ORDER_UPDATED})
    await publish_courier_delivery_event({"type": RealtimeEventType.DELIVERY_AVAILABLE})

    assert fake_client.messages[0][0] == company_orders_channel(15)
    assert fake_client.messages[1][0] == courier_deliveries_channel()
