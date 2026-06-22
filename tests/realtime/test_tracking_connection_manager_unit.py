import pytest

from app.services.tracking_connection_manager import TrackingConnectionManager


class FakeWebSocket:
    def __init__(self, should_fail=False):
        self.accepted = False
        self.sent_payloads = []
        self.should_fail = should_fail

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        if self.should_fail:
            raise RuntimeError("socket desconectado")
        self.sent_payloads.append(payload)


@pytest.mark.asyncio
async def test_tracking_manager_connects_and_broadcasts_to_order():
    manager = TrackingConnectionManager()
    first_socket = FakeWebSocket()
    second_socket = FakeWebSocket()

    await manager.connect(100, first_socket)
    await manager.connect(100, second_socket)
    await manager.broadcast_to_order(100, "TRACKING_SNAPSHOT", {"order_id": 100})

    assert first_socket.accepted is True
    assert second_socket.accepted is True
    assert first_socket.sent_payloads == [{"type": "TRACKING_SNAPSHOT", "data": {"order_id": 100}}]
    assert second_socket.sent_payloads == [{"type": "TRACKING_SNAPSHOT", "data": {"order_id": 100}}]


@pytest.mark.asyncio
async def test_tracking_manager_removes_disconnected_socket_after_broadcast_failure():
    manager = TrackingConnectionManager()
    working_socket = FakeWebSocket()
    failing_socket = FakeWebSocket(should_fail=True)

    await manager.connect(200, working_socket)
    await manager.connect(200, failing_socket)
    await manager.broadcast_to_order(200, "DELIVERY_LOCATION_UPDATED", {"order_id": 200})
    await manager.broadcast_to_order(200, "DELIVERY_LOCATION_UPDATED", {"order_id": 200, "again": True})

    assert len(working_socket.sent_payloads) == 2
    assert failing_socket.sent_payloads == []
