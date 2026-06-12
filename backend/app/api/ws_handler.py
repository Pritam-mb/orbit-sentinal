"""
WebSocket connection manager.
<<<<<<< HEAD
Handles multi-client connections and 1Hz satellite broadcast.

Enhanced broadcast payload includes covariance_ellipse for satellites
that are in active conjunction alerts, enabling the frontend to render
uncertainty ellipses around threatened satellites.
"""

import asyncio
import json
=======
Handles multi-client connections and periodic satellite broadcast.
"""

import asyncio
import os
>>>>>>> a807e61320556541bc8c65f9ccd38523da4f391c
import logging
from fastapi import WebSocket
from app.core.state_cache import get_latest_snapshot, get_latest_alerts

logger = logging.getLogger(__name__)

BROADCAST_INTERVAL_SECONDS = float(os.getenv("BROADCAST_INTERVAL_SECONDS", "1"))


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


def _build_covariance_index(alerts: list) -> dict:
    """
    Build a lookup mapping norad_id → covariance_ellipse from active alerts.

    Each alert has sat1 and sat2 fields (both are threatened by the conjunction).
    The ellipse stored is from the Foster integration for that pair.
    """
    index: dict[str, dict | None] = {}
    for alert in alerts:
        ellipse = alert.get("covariance_ellipse")
        # Both satellites in the conjunction get the ellipse
        sat1_id = str(alert.get("sat1", {}).get("id", ""))
        sat2_id = str(alert.get("sat2", {}).get("id", ""))
        if sat1_id:
            # Use highest-severity ellipse if satellite is in multiple alerts
            if sat1_id not in index or ellipse is not None:
                index[sat1_id] = ellipse
        if sat2_id:
            if sat2_id not in index or ellipse is not None:
                index[sat2_id] = ellipse
    return index


async def satellite_broadcast_loop(
    manager: ConnectionManager,
):
    """
<<<<<<< HEAD
    Background task: broadcast the latest cached snapshot at 1Hz.

    Enriches the satellite list with covariance_ellipse fields from active
    conjunction alerts. Field is None for non-threatened satellites and
    contains ellipse parameters {a, b, angle, affection_rate, predicted_fragments}
    for satellites in active conjunctions.
=======
    Background task: broadcast the latest cached snapshot on a slower cadence.
>>>>>>> a807e61320556541bc8c65f9ccd38523da4f391c
    """
    while True:
        try:
            if manager.active_connections:
                snapshot = get_latest_snapshot()

                # ── Build covariance index from active alerts ──────────────
                try:
                    alerts_snapshot = get_latest_alerts()
                    active_alerts = alerts_snapshot.get("alerts", [])
                    covariance_index = _build_covariance_index(active_alerts)
                except Exception:
                    covariance_index = {}

                # ── Build enriched satellite list ──────────────────────────
                satellites = snapshot.get("satellites", [])
                if covariance_index:
                    enriched = []
                    for sat in satellites:
                        norad_str = str(sat.get("norad_id", ""))
                        covariance_ellipse = covariance_index.get(norad_str, None)
                        enriched.append({**sat, "covariance_ellipse": covariance_ellipse})
                    payload_obj = {
                        "type": snapshot.get("type", "update"),
                        "timestamp": snapshot.get("timestamp"),
                        "satellites": enriched,
                        "count": snapshot.get("count", len(satellites)),
                    }
                    payload = json.dumps(payload_obj, separators=(",", ":"))
                else:
                    # No active conjunctions — use cached payload (faster)
                    payload = snapshot.get("payload")

                if payload:
                    await manager.broadcast(payload)

        except Exception as e:
            logger.error(f"Broadcast error: {e}")

        await asyncio.sleep(BROADCAST_INTERVAL_SECONDS)
