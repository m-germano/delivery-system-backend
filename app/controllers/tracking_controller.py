from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import AsyncSessionLocal, get_db
from app.schemas.tracking_schema import TrackingSnapshotResponse
from app.services.tracking_connection_manager import tracking_manager
from app.services.tracking_service import TrackingService

router = APIRouter(tags=["Tracking"])
http_router = APIRouter(tags=["Tracking"])


@http_router.get("/orders/{order_id}/tracking", response_model=TrackingSnapshotResponse)
async def get_order_tracking_snapshot(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await TrackingService(db).get_tracking_snapshot(order_id, current_user)


@router.websocket("/ws/orders/{order_id}/tracking")
async def order_tracking_socket(
    websocket: WebSocket,
    order_id: int,
    token: str | None = Query(default=None),
):
    async with AsyncSessionLocal() as db:
        service = TrackingService(db)
        current_user = await service.authenticate_websocket_user(token, websocket)
        if current_user is None:
            return

        try:
            snapshot = await service.get_tracking_snapshot(order_id, current_user)
        except Exception:
            await websocket.close(code=1008, reason="Acompanhamento não encontrado.")
            return

        await tracking_manager.connect(order_id, websocket)
        await tracking_manager.send_to_socket(websocket, "TRACKING_SNAPSHOT", snapshot.model_dump())

        try:
            while True:
                # Mantém a conexão aberta. O cliente pode enviar ping textual se quiser.
                await websocket.receive_text()
        except WebSocketDisconnect:
            tracking_manager.disconnect(order_id, websocket)
        except Exception:
            tracking_manager.disconnect(order_id, websocket)
            await websocket.close()
