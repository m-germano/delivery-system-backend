from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RoleId
from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal
from app.repositories.company_repository import CompanyRepository
from app.repositories.user_repository import UserRepository
from app.services.realtime_service import company_orders_channel, courier_deliveries_channel, get_redis_client

router = APIRouter(tags=["Realtime"])


async def _get_user_from_token(token: str | None, session: AsyncSession):
    if not token:
        return None

    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        user_id = int(subject)
    except Exception:
        return None

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        return None

    return user


async def _relay_channel(websocket: WebSocket, channel: str, ready_payload: dict) -> None:
    client = await get_redis_client()
    pubsub = client.pubsub()
    receive_task: asyncio.Task | None = None

    try:
        await pubsub.subscribe(channel)
        await websocket.send_json(ready_payload)
        receive_task = asyncio.create_task(websocket.receive_text())

        while True:
            if receive_task.done():
                try:
                    receive_task.result()
                except WebSocketDisconnect:
                    break
                except Exception:
                    break
                receive_task = asyncio.create_task(websocket.receive_text())

            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                raw_data = message.get("data")
                try:
                    payload = json.loads(raw_data)
                    await websocket.send_json(payload)
                except json.JSONDecodeError:
                    await websocket.send_text(str(raw_data))

            await asyncio.sleep(0.05)
    finally:
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
        await pubsub.unsubscribe(channel)
        await pubsub.close()


@router.websocket("/ws/company/orders")
async def company_orders_realtime(websocket: WebSocket):
    await websocket.accept()

    async with AsyncSessionLocal() as session:
        user = await _get_user_from_token(websocket.query_params.get("token"), session)

        if user is None or user.role_id != RoleId.COMPANY:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        company = await CompanyRepository(session).get_by_owner_user_id(user.id)
        if company is None:
            await websocket.send_json({
                "type": "connection.error",
                "message": "Configure sua empresa antes de acompanhar pedidos em tempo real.",
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        channel = company_orders_channel(company.id)

    await _relay_channel(
        websocket,
        channel,
        {
            "type": "connection.ready",
            "scope": "company.orders",
            "company_id": company.id,
        },
    )


@router.websocket("/ws/courier/deliveries")
async def courier_deliveries_realtime(websocket: WebSocket):
    await websocket.accept()

    async with AsyncSessionLocal() as session:
        user = await _get_user_from_token(websocket.query_params.get("token"), session)

        if user is None or user.role_id != RoleId.COURIER:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await _relay_channel(
        websocket,
        courier_deliveries_channel(),
        {
            "type": "connection.ready",
            "scope": "courier.deliveries",
        },
    )
