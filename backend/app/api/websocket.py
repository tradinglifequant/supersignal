from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from typing import Set

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.security.auth import decode_token, is_jti_revoked

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.active: Set[WebSocket] = set()

    def connect(self, ws: WebSocket) -> None:
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, default=str)
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                logger.warning("WebSocket broadcast failed")
                self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    # Browser clients must have an explicitly allowed Origin. No wildcard.
    if websocket.headers.get("origin") not in get_settings().cors_origin_list:
        await websocket.close(code=4003)
        return
    await websocket.accept()
    jti = None
    try:
        # Authenticate in the first frame, not in a URL that may be logged.
        message = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        if not isinstance(message, dict) or message.get("type") != "authenticate" or not isinstance(message.get("token"), str):
            await websocket.close(code=4001)
            return
        payload = decode_token(message["token"])
        jti = payload.get("jti")
        expires_at = int(payload["exp"])
        if expires_at <= time.time():
            await websocket.close(code=4001)
            return
    except (HTTPException, ValueError, TypeError, KeyError, asyncio.TimeoutError, json.JSONDecodeError):
        await websocket.close(code=4001)
        return
    except WebSocketDisconnect:
        return

    manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "type": "snapshot",
                "payload": {"message": "connected", "timestamp": datetime.now(timezone.utc).isoformat()},
            }
        )
        while True:
            remaining = expires_at - time.time()
            if remaining <= 0 or is_jti_revoked(jti):
                await websocket.close(code=4001)
                break
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=min(remaining, 5.0))
            except asyncio.TimeoutError:
                if expires_at <= time.time() or is_jti_revoked(jti):
                    await websocket.close(code=4001)
                    break
                continue
            if is_jti_revoked(jti):
                await websocket.close(code=4001)
                break
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
            elif isinstance(msg, dict) and msg.get("type") == "subscribe":
                await websocket.send_json({"type": "subscribed", "payload": msg.get("payload")})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("WebSocket session failed")
    finally:
        manager.disconnect(websocket)


async def broadcast_event(event_type: str, payload: dict) -> None:
    await manager.broadcast(
        {"type": event_type, "payload": payload, "timestamp": datetime.now(timezone.utc).isoformat()}
    )
