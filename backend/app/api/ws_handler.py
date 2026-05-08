"""
WebSocket connection manager.
Handles multi-client connections and 1Hz satellite broadcast.
"""

import asyncio
import logging
from fastapi import WebSocket
from app.core.state_cache import get_latest_snapshot

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"Client connected. Total: {len(self.active_connections)}"
        )

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(
            f"Client disconnected. Total: {len(self.active_connections)}"
        )

    async def broadcast(self, message: str):
        """Send message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)


async def satellite_broadcast_loop(
    manager: ConnectionManager,
):
    """
    Background task: broadcast the latest cached snapshot at 1Hz.
    """
    while True:
        try:
            if manager.active_connections:
                snapshot = get_latest_snapshot()
                payload = snapshot.get("payload")
                if payload:
                    await manager.broadcast(payload)

        except Exception as e:
            logger.error(f"Broadcast error: {e}")

        await asyncio.sleep(1.0)
