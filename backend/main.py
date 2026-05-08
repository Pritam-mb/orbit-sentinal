"""
Orbital Sentinel — FastAPI Entry Point.
Initializes propagator, sim engine, WebSocket broadcast, and REST routes.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.core.sgp4_propagator import SGP4Propagator
from app.core.conjunction import screen_conjunctions
from app.core.state_cache import (
    get_latest_snapshot,
    set_latest_alerts,
    set_latest_snapshot,
)
from app.data.tle_fetcher import load_local_tles
from app.simulation.sim_engine import SimEngine
from app.api.ws_handler import ConnectionManager, satellite_broadcast_loop
from app.api.routes import router, init_routes
from app.routers.test_mode import router as test_mode_router, init_test_mode

load_dotenv(dotenv_path="../.env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
propagator = SGP4Propagator()
sim_engine = SimEngine(propagator)
ws_manager = ConnectionManager()


def build_snapshot(current_propagator: SGP4Propagator, dt: datetime) -> dict:
    """Compute a serializable snapshot for the latest satellite state."""
    states = current_propagator.propagate_all(dt)

    active_states = [state for state in states if state.error_code == 0]
    satellites = [
        {
            "norad_id": state.norad_id,
            "name": state.name,
            "position": {
                "x": state.x,
                "y": state.y,
                "z": state.z,
            },
        }
        for state in active_states
    ]

    snapshot = {
        "type": "update",
        "timestamp": dt.isoformat(),
        "satellites": satellites,
        "count": len(states),
        "states": active_states,
    }
    snapshot["payload"] = json.dumps({
        "type": snapshot["type"],
        "timestamp": snapshot["timestamp"],
        "satellites": satellites,
        "count": snapshot["count"],
    }, separators=(",", ":"))
    return snapshot


async def refresh_snapshot_loop():
    """Keep the latest propagated satellite snapshot warm in memory."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            snapshot = await asyncio.to_thread(build_snapshot, propagator, now)
            set_latest_snapshot(snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(f"Snapshot refresh error: {error}")

        await asyncio.sleep(1.0)


async def refresh_alerts_loop():
    """Refresh conjunction alerts at a slower cadence to avoid blocking startup."""
    max_alert_states = 250
    while True:
        try:
            snapshot = get_latest_snapshot()
            states = snapshot.get("states", [])
            alerts = []

            if states:
                if len(states) > max_alert_states:
                    step = max(1, len(states) // max_alert_states)
                    sampled_states = states[::step][:max_alert_states]
                else:
                    sampled_states = states

                alerts = await asyncio.to_thread(screen_conjunctions, sampled_states)

            set_latest_alerts({
                "timestamp": snapshot.get("timestamp"),
                "alerts": [a.to_dict() for a in alerts],
                "count": len(alerts),
            })
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(f"Alert refresh error: {error}")

        await asyncio.sleep(30.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: fetch TLEs and begin broadcast loop."""
    logger.info("=== Orbital Sentinel starting ===")

    # Load the bundled snapshot immediately so the API starts fast.
    local_tles = load_local_tles(max_sats=0)
    propagator.load_tles(local_tles)
    logger.info(f"Tracking {propagator.satellite_count} satellites from local snapshot")

    now = datetime.now(timezone.utc)
    set_latest_snapshot(await asyncio.to_thread(build_snapshot, propagator, now))
    set_latest_alerts({"timestamp": now.isoformat(), "alerts": [], "count": 0})

    # Initialize REST routes with shared instances
    init_routes(propagator, sim_engine)
    init_test_mode(propagator)

    # Start 1Hz broadcast background task
    snapshot_task = asyncio.create_task(refresh_snapshot_loop())
    alerts_task = asyncio.create_task(refresh_alerts_loop())
    broadcast_task = asyncio.create_task(satellite_broadcast_loop(ws_manager))

    yield

    # Shutdown
    snapshot_task.cancel()
    alerts_task.cancel()
    broadcast_task.cancel()
    logger.info("=== Orbital Sentinel stopped ===")


app = FastAPI(
    title="Orbital Sentinel API",
    description="Satellite tracking and collision simulation",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST routes
app.include_router(router)
app.include_router(test_mode_router)


@app.get("/")
async def root():
    return {
        "service": "Orbital Sentinel",
        "status": "operational",
        "satellites": propagator.satellite_count,
    }


@app.websocket("/ws/satellites")
async def websocket_satellites(websocket: WebSocket):
    """WebSocket endpoint for real-time satellite position updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await websocket.receive_text()
            # Client can send commands here if needed
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
