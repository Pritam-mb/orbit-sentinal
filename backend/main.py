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
    get_all_kalman_states,
)
from app.data.tle_fetcher import fetch_tles
from app.simulation.sim_engine import SimEngine
from app.services.cascade_planner import CascadePlanner
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
cascade_planner = CascadePlanner()


def build_snapshot(current_propagator: SGP4Propagator, dt: datetime) -> dict:
    """Compute a serializable snapshot for the latest satellite state."""
    from app.core.state_cache import set_kalman_state
    
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
            "velocity": {
                "vx": state.vx,
                "vy": state.vy,
                "vz": state.vz,
            },
            "speed_kmh": round(float((state.vx**2 + state.vy**2 + state.vz**2) ** 0.5 * 3600.0), 2),
            "altitude_km": round(float(((state.x**2 + state.y**2 + state.z**2) ** 0.5) - 6371.0), 2),
            "epoch_utc": state.epoch_utc,
        }
        for state in active_states
    ]

    # Capture Kalman covariance per satellite
    covariances = {}
    for state in active_states:
        kal_state = current_propagator._kalman_states.get(state.norad_id)
        if kal_state is not None:
            kal_dict = kal_state.to_dict()
            covariances[state.norad_id] = kal_dict.get("covariance_6x6")
            set_kalman_state(state.norad_id, kal_dict)

    snapshot = {
        "type": "update",
        "timestamp": dt.isoformat(),
        "satellites": satellites,
        "count": len(states),
        "states": active_states,
        "covariances": covariances,
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
            cascade_summary = {
                "graph": {"node_count": 0, "edge_count": 0, "influence_radius_km": 200.0},
                "alerts": [],
                "cascade_plan": [],
                "total_delta_v_ms": 0.0,
                "cascade_depth": 0,
                "agencies_involved": [],
                "seed_satellites": [],
                "cpi_threshold": 5.0,
                "node_probabilities": {},
            }

            if states:
                if len(states) > max_alert_states:
                    step = max(1, len(states) // max_alert_states)
                    sampled_states = states[::step][:max_alert_states]
                else:
                    sampled_states = states

                kalman_states = get_all_kalman_states()
                alerts = await asyncio.to_thread(screen_conjunctions, sampled_states, kalman_states=kalman_states)
                cascade_summary = await asyncio.to_thread(
                    cascade_planner.analyze_snapshot,
                    sampled_states,
                    [alert.to_dict() for alert in alerts],
                    propagator,
                    snapshot.get("timestamp") and datetime.fromisoformat(snapshot["timestamp"]),
                )

            set_latest_alerts({
                "timestamp": snapshot.get("timestamp"),
                "alerts": cascade_summary.get("alerts", [a.to_dict() for a in alerts]),
                "count": len(alerts),
                "hotspots": cascade_summary.get("hotspots", []),
                "graph": cascade_summary.get("graph", {}),
                "cascade_plan": cascade_summary.get("cascade_plan", []),
                "cascade_depth": cascade_summary.get("cascade_depth", 0),
                "total_delta_v_ms": cascade_summary.get("total_delta_v_ms", 0.0),
                "agencies_involved": cascade_summary.get("agencies_involved", []),
                "seed_satellites": cascade_summary.get("seed_satellites", []),
                "cpi_threshold": cascade_summary.get("cpi_threshold", 5.0),
                "node_probabilities": cascade_summary.get("node_probabilities", {}),
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

    # ── Model initialization sequence ─────────────────────────────────────────
    print("=== Orbital Sentinel Startup ===")

    print("Initializing Foster B-plane physics engine...")
    try:
        from app.core import analytics as _analytics_module  # noqa: F401
        print("  Foster B-plane analytics ready")
    except Exception as _analytics_err:
        print(f"  WARNING: analytics.py failed to load: {_analytics_err}")

    print("Initializing satellite state tracker...")
    try:
        from app.core.satellite_state_tracker import satellite_tracker as _tracker
        print(f"  State tracker ready (tracking 0 satellites at startup)")
    except Exception as _tracker_err:
        print(f"  WARNING: satellite_state_tracker failed: {_tracker_err}")

    print("Initializing agency authority model...")
    try:
        from app.core.agency_authority import authority_manager as _auth
        # Create default sessions for each known agency
        for _agency in [
            "SpaceX", "ESA", "ISRO", "ROSCOSMOS",
            "ISS/NASA", "CNSA", "US Space Force",
            "NOAA", "NASA",
        ]:
            _auth.create_session(_agency)
        print(f"  Authority model ready with {len(_auth.sessions)} sessions (DEMO_SESSION + {len(_auth.sessions)-1} agency sessions)")
    except Exception as _auth_err:
        print(f"  WARNING: agency_authority failed: {_auth_err}")

    print("Initializing XGBoost risk classifier (may train on first run — ~1-3 min)...")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: __import__("app.ml.xgboost_scorer", fromlist=["_trained_model"]),
        )
        print("  XGBoost risk classifier ready")
    except Exception as _xgb_err:
        print(f"  WARNING: XGBoost init failed: {_xgb_err}")

    print("=== Model initialization complete ===")

    # Load live TLEs when Space-Track credentials are configured, otherwise fall back.
    tles = await fetch_tles(max_sats=0)
    propagator.load_tles(tles)
    logger.info(f"Tracking {propagator.satellite_count} satellites from current TLE source")

    now = datetime.now(timezone.utc)
    set_latest_snapshot(await asyncio.to_thread(build_snapshot, propagator, now))
    set_latest_alerts({"timestamp": now.isoformat(), "alerts": [], "count": 0, "hotspots": []})

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
