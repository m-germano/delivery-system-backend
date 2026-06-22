from collections import defaultdict

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder


class TrackingConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, order_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[order_id].add(websocket)

    def disconnect(self, order_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(order_id)
        if not sockets:
            return

        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(order_id, None)

    async def send_to_socket(self, websocket: WebSocket, event_type: str, data: dict) -> None:
        await websocket.send_json(jsonable_encoder({"type": event_type, "data": data}))

    async def broadcast_to_order(self, order_id: int, event_type: str, data: dict) -> None:
        sockets = list(self._connections.get(order_id, set()))
        disconnected: list[WebSocket] = []

        for websocket in sockets:
            try:
                await self.send_to_socket(websocket, event_type, data)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(order_id, websocket)


tracking_manager = TrackingConnectionManager()
