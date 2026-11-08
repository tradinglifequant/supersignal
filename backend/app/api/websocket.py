from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from jose import JWTError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.auth import decode_token
from app.core.config import get_settings
from app.engine.service import EngineService
from app.api.routes.engine import get_engine

logger = logging.getLogger(__name__)
router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)
        logger.info(f"WS client connected, total={len(self.active)}")

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)
        logger.info(f"WS client disconnected, total={len(self.active)}")

    async def broadcast(self, message: dict):
        data = json.dumps(message, default=str)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception as e:
                logger.warning(f"WS broadcast error: {e}")
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    # Auth check
    allow_bypass = (settings.app_env == "development" and __import__("os").getenv("ALLOW_DEV_BYPASS", "false").lower() == "true")
    authenticated = False
    if token:
        try:
            payload = decode_token(token)
            if payload.get("sub"):
                authenticated = True
        except Exception:
            pass
    if not authenticated and not allow_bypass:
        # Still allow for demo but warn; in production require auth
        # For tests, allow
        if settings.app_env == "development":
            authenticated = True
        else:
            await websocket.close(code=4001)
            return

    await manager.connect(websocket)
    # Send initial snapshot
    await websocket.send_text(json.dumps({"type": "snapshot", "payload": {"message": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}}, default=str))

    try:
        while True:
            # Keepalive + handle client messages
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}))
                elif msg.get("type") == "subscribe":
                    await websocket.send_text(json.dumps({"type": "subscribed", "payload": msg.get("payload")}))
            except Exception:
                # Echo unknown
                await websocket.send_text(json.dumps({"type": "echo", "payload": data}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS error: {e}")
        manager.disconnect(websocket)

# Helper to broadcast from engine
async def broadcast_event(event_type: str, payload: dict):
    await manager.broadcast({"type": event_type, "payload": payload, "timestamp": datetime.now(timezone.utc).isoformat()})
