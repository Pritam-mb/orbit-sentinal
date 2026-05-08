"""
REST API routes for maneuvers, scenarios, and alerts.
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.core.state_cache import get_latest_alerts, get_latest_snapshot, set_latest_alerts, set_latest_snapshot
from app.core.conjunction import screen_conjunctions
from app.services.cascade_planner import CascadePlanner

router = APIRouter(prefix="/api")


class ManeuverRequest(BaseModel):
    norad_id: int
    dvx: float  # m/s
    dvy: float
    dvz: float
    frame: str = "RSW"


class ScenarioRequest(BaseModel):
    name: str


# These will be set by main.py on startup
_propagator = None
_sim_engine = None
_cascade_planner = CascadePlanner()


def init_routes(propagator, sim_engine):
    global _propagator, _sim_engine
    _propagator = propagator
    _sim_engine = sim_engine


def _build_snapshot(current_propagator, dt: datetime) -> dict:
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


@router.get("/satellites")
async def get_satellites():
    """Get current satellite positions."""
    snapshot = get_latest_snapshot()

    payload = snapshot.get("payload")
    if payload:
        return Response(content=payload, media_type="application/json")

    return {
        "satellites": snapshot.get("satellites", []),
        "count": snapshot.get("count", 0),
        "timestamp": snapshot.get("timestamp"),
    }


@router.get("/satellites/{norad_id}")
async def get_satellite_detail(norad_id: int):
    """Get the full state for a single satellite."""
    if _propagator is None:
        raise HTTPException(status_code=503, detail="Propagator not initialized")

    state = _propagator.propagate_one(norad_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Satellite not found")

    return state.to_dict()


@router.get("/alerts")
async def get_alerts():
    """Get current conjunction alerts."""
    alerts_snapshot = get_latest_alerts()
    return {
        "alerts": alerts_snapshot.get("alerts", []),
        "count": alerts_snapshot.get("count", 0),
        "timestamp": alerts_snapshot.get("timestamp"),
        "hotspots": alerts_snapshot.get("hotspots", []),
        "cascade_plan": alerts_snapshot.get("cascade_plan", []),
        "graph": alerts_snapshot.get("graph", {}),
        "cascade_depth": alerts_snapshot.get("cascade_depth", 0),
        "total_delta_v_ms": alerts_snapshot.get("total_delta_v_ms", 0.0),
        "agencies_involved": alerts_snapshot.get("agencies_involved", []),
        "seed_satellites": alerts_snapshot.get("seed_satellites", []),
        "cpi_threshold": alerts_snapshot.get("cpi_threshold", 5.0),
        "node_probabilities": alerts_snapshot.get("node_probabilities", {}),
    }


@router.get("/satellites/{norad_id}/orbit")
async def get_satellite_orbit(
    norad_id: int,
    span_minutes: int = 90,
    step_seconds: int = 60,
):
    """Get a short orbit track for the selected satellite."""
    if _propagator is None:
        raise HTTPException(status_code=503, detail="Propagator not initialized")

    from datetime import timedelta

    span_minutes = max(15, min(span_minutes, 180))
    step_seconds = max(10, min(step_seconds, 300))

    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=span_minutes / 2)
    end = now + timedelta(minutes=span_minutes / 2)

    orbit = []
    current = start
    while current <= end:
      state = _propagator.propagate_one(norad_id, current)
      if state is not None and state.error_code == 0:
          orbit.append(
              {
                  "epoch_utc": state.epoch_utc,
                  "position": {
                      "x": state.x,
                      "y": state.y,
                      "z": state.z,
                  },
              }
          )
      current += timedelta(seconds=step_seconds)

    if not orbit:
        raise HTTPException(status_code=404, detail="Satellite not found")

    return {
        "norad_id": norad_id,
        "generated_at": now.isoformat(),
        "orbit": orbit,
    }


@router.post("/maneuver")
async def execute_maneuver(req: ManeuverRequest):
    """Execute a delta-V maneuver with pre-flight validation."""
    if _sim_engine is None or _propagator is None:
        return {"status": "ERROR", "message": "Sim engine not initialized"}

    result = _sim_engine.apply_maneuver(
        req.norad_id,
        req.dvx,
        req.dvy,
        req.dvz,
        frame=req.frame,
    )

    if result.get("status") == "success":
        snapshot = await asyncio.to_thread(
            _build_snapshot,
            _propagator,
            datetime.now(timezone.utc),
        )
        set_latest_snapshot(snapshot)

        sampled_states = snapshot.get("states", [])
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

        if sampled_states:
            if len(sampled_states) > 250:
                step = max(1, len(sampled_states) // 250)
                sampled_states = sampled_states[::step][:250]

            alerts = await asyncio.to_thread(screen_conjunctions, sampled_states)
            cascade_summary = await asyncio.to_thread(
                _cascade_planner.analyze_snapshot,
                sampled_states,
                [alert.to_dict() for alert in alerts],
                _propagator,
                datetime.fromisoformat(snapshot["timestamp"]),
            )

        result = {
            **result,
            "alerts": cascade_summary.get("alerts", [a.to_dict() for a in alerts]),
                "hotspots": cascade_summary.get("hotspots", []),
            "cascade_plan": cascade_summary.get("cascade_plan", []),
            "graph": cascade_summary.get("graph", {}),
            "cascade_depth": cascade_summary.get("cascade_depth", 0),
            "total_delta_v_ms": cascade_summary.get("total_delta_v_ms", 0.0),
            "agencies_involved": cascade_summary.get("agencies_involved", []),
            "seed_satellites": cascade_summary.get("seed_satellites", []),
            "cpi_threshold": cascade_summary.get("cpi_threshold", 5.0),
            "node_probabilities": cascade_summary.get("node_probabilities", {}),
        }

        set_latest_alerts({
            "timestamp": snapshot.get("timestamp"),
            "alerts": result["alerts"],
            "count": len(result["alerts"]),
            "hotspots": result["hotspots"],
            "graph": result["graph"],
            "cascade_plan": result["cascade_plan"],
            "cascade_depth": result["cascade_depth"],
            "total_delta_v_ms": result["total_delta_v_ms"],
            "agencies_involved": result["agencies_involved"],
            "seed_satellites": result["seed_satellites"],
            "cpi_threshold": result["cpi_threshold"],
            "node_probabilities": result["node_probabilities"],
        })

    return result


@router.post("/simulate")
async def trigger_scenario(req: ScenarioRequest):
    """Load a deterministic simulation scenario."""
    if _sim_engine is None:
        return {"status": "ERROR", "message": "Sim engine not initialized"}

    try:
        result = _sim_engine.load_scenario(req.name)
        return {"status": "LOADED", **result}
    except FileNotFoundError as e:
        return {"status": "ERROR", "message": str(e)}


@router.delete("/simulate")
async def clear_scenario():
    """Clear the active scenario."""
    if _sim_engine:
        _sim_engine.clear_scenario()
    return {"status": "CLEARED"}


@router.get("/scenarios")
async def list_scenarios():
    """List available simulation scenarios."""
    if _sim_engine is None:
        return {"scenarios": []}
    return {"scenarios": _sim_engine.list_scenarios()}


@router.post("/preflight")
async def preflight_check(req: ManeuverRequest):
    """Run pre-flight validation without executing."""
    if _sim_engine is None:
        return {"status": "ERROR"}

    result = _sim_engine.preflight_check(req.norad_id, req.dvx, req.dvy, req.dvz, frame=req.frame)
    return result
