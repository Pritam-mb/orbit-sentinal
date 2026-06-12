"""
REST API routes for maneuvers, scenarios, and alerts.
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.core.state_cache import get_latest_alerts, get_latest_snapshot, set_latest_alerts, set_latest_snapshot, get_all_kalman_states
from app.core.conjunction import screen_conjunctions
from app.services.cascade_planner import CascadePlanner
from app.services.debris_model import build_debris_alerts
from app.ml.runtime import get_ml_runtime
from app.ml.model_metrics import get_model_metrics

try:
    from app.core.satellite_state_tracker import satellite_tracker
    _TRACKER_AVAILABLE = True
except ImportError:
    satellite_tracker = None
    _TRACKER_AVAILABLE = False

router = APIRouter(prefix="/api")


class ManeuverRequest(BaseModel):
    norad_id: int
    dvx: float  # m/s
    dvy: float
    dvz: float
    frame: str = "RSW"


class ScenarioRequest(BaseModel):
    name: str


class JudgeManipulateRequest(BaseModel):
    """Override a satellite's state and predict downstream effects."""
    norad_id: int
    position_eci_km: list[float] | None = None  # [x, y, z] in km
    velocity_eci_kms: list[float] | None = None  # [vx, vy, vz] in km/s


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


@router.get("/satellites/{norad_id}/telemetry")
async def get_satellite_telemetry(norad_id: int):
    """Get stateful telemetry for a satellite (fuel, battery, temperature, etc.)."""
    if _propagator is None:
        raise HTTPException(status_code=503, detail="Propagator not initialized")

    state = _propagator.propagate_one(norad_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Satellite not found")

    if _TRACKER_AVAILABLE and satellite_tracker is not None:
        telemetry = satellite_tracker.get_telemetry(norad_id, state.name)
    else:
        # Minimal fallback when tracker is unavailable
        import random
        telemetry = {
            "norad_id": norad_id,
            "satellite_name": state.name,
            "fuel_remaining_pct": round(max(0.0, 85.0 + random.uniform(-5, 10)), 2),
            "battery_pct": round(88.0 + random.uniform(-3, 3), 2),
            "temperature_c": round(-10.0 + random.uniform(-8, 8), 2),
            "signal_strength_dbm": round(-65.0 + random.uniform(-5, 5), 2),
            "solar_power_w": round(1200.0 + random.uniform(-100, 100), 1),
            "total_delta_v_used_ms": 0.0,
            "maneuver_count": 0,
        }

    return {
        **telemetry,
        "norad_id": norad_id,
        "epoch_utc": state.epoch_utc,
    }


@router.get("/satellites/{norad_id}/history")
async def get_satellite_maneuver_history(norad_id: int):
    """Get the full maneuver history for a satellite."""
    if _TRACKER_AVAILABLE and satellite_tracker is not None:
        history = satellite_tracker.get_maneuver_history(norad_id)
    else:
        history = []
    return {
        "norad_id": norad_id,
        "maneuver_count": len(history),
        "history": history,
    }


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
        "debris_clouds": alerts_snapshot.get("debris_clouds", []),
    }


@router.get("/anomalies")
async def get_anomalies():
    runtime = get_ml_runtime()
    return {
        "count": len(runtime.get_anomalies()),
        "anomalies": runtime.get_anomalies(),
    }


@router.get("/model-metrics")
async def get_model_metrics_endpoint():
    return get_model_metrics()


@router.get("/cascade/status")
async def get_cascade_status():
    """Get the current cascade prediction status."""
    alerts_snapshot = get_latest_alerts()
    plan = alerts_snapshot.get("cascade_plan", [])
    
    predictions = len(plan)
    depth = alerts_snapshot.get("cascade_depth", 0)
    
    return {
        "cascade_predictions": predictions,
        "mean_cascade_depth": depth,
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
        # ── Record maneuver in state tracker (fuel depletion) ─────────────
        import math as _math
        delta_v_ms = _math.sqrt(req.dvx**2 + req.dvy**2 + req.dvz**2)
        if _TRACKER_AVAILABLE and satellite_tracker is not None:
            try:
                state = _propagator.propagate_one(req.norad_id)
                sat_name = state.name if state is not None else f"SAT-{req.norad_id}"
                satellite_tracker.record_maneuver(
                    req.norad_id, delta_v_ms, req.frame, sat_name
                )
            except Exception as tracker_err:
                import logging as _log
                _log.getLogger(__name__).warning("Tracker record_maneuver failed: %s", tracker_err)
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

            kalman_states = get_all_kalman_states()
            alerts = await asyncio.to_thread(screen_conjunctions, sampled_states, kalman_states=kalman_states)
            cascade_summary = await asyncio.to_thread(
                _cascade_planner.analyze_snapshot,
                sampled_states,
                [alert.to_dict() for alert in alerts],
                _propagator,
                datetime.fromisoformat(snapshot["timestamp"]),
            )

        debris_clouds = build_debris_alerts(
            cascade_summary.get("hotspots", []),
            sampled_states if sampled_states else [],
            snapshot.get("timestamp"),
            alerts=cascade_summary.get("alerts", [a.to_dict() for a in alerts]),
            cpi_threshold=cascade_summary.get("cpi_threshold", 5.0),
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
            "debris_clouds": debris_clouds,
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
            "debris_clouds": result["debris_clouds"],
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


@router.post("/judge/manipulate-satellite")
async def judge_manipulate_satellite(req: JudgeManipulateRequest):
    """
    Judge manipulation mode: override a satellite's state and immediately predict
    downstream effects, neighbor risks, and cascade implications.
    Returns: overridden state, KD-tree neighbors within 200km, CPI scores, and alerts.
    """
    if _propagator is None:
        raise HTTPException(status_code=503, detail="Propagator not initialized")

    now = datetime.now(timezone.utc)
    
    # Build base snapshot from current constellation
    snapshot = await asyncio.to_thread(_build_snapshot, _propagator, now)
    states = snapshot.get("states", [])
    
    # Find and override the target satellite
    target_idx = None
    target_state = None
    for idx, state in enumerate(states):
        if state.norad_id == req.norad_id:
            target_idx = idx
            target_state = state
            break
    
    if target_state is None:
        raise HTTPException(status_code=404, detail=f"Satellite {req.norad_id} not found")
    
    # Apply override if provided
    if req.position_eci_km is not None and len(req.position_eci_km) == 3:
        target_state.x, target_state.y, target_state.z = req.position_eci_km
    
    if req.velocity_eci_kms is not None and len(req.velocity_eci_kms) == 3:
        target_state.vx, target_state.vy, target_state.vz = req.velocity_eci_kms
    
    # Rebuild satellite list with override
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
        for state in states
    ]
    
    # Recompute alerts and cascade plan with the overridden state
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
    
    sampled_states = []
    if states:
        if len(states) > 250:
            step = max(1, len(states) // 250)
            sampled_states = states[::step][:250]
        else:
            sampled_states = states
        
        kalman_states = get_all_kalman_states()
        alerts = await asyncio.to_thread(screen_conjunctions, sampled_states, kalman_states=kalman_states)
        cascade_summary = await asyncio.to_thread(
            _cascade_planner.analyze_snapshot,
            sampled_states,
            [alert.to_dict() for alert in alerts],
        )

    debris_clouds = build_debris_alerts(
        cascade_summary.get("hotspots", []),
        sampled_states if states else [],
        snapshot.get("timestamp"),
        alerts=cascade_summary.get("alerts", []),
        cpi_threshold=cascade_summary.get("cpi_threshold", 5.0),
    )
    
    # Build a neighbor map: all satellites within 200 km of the target
    target_pos = [target_state.x, target_state.y, target_state.z]
    neighbors = []
    
    for state in states:
        if state.norad_id == req.norad_id:
            continue
        
        other_pos = [state.x, state.y, state.z]
        distance_km = ((other_pos[0] - target_pos[0])**2 + 
                       (other_pos[1] - target_pos[1])**2 + 
                       (other_pos[2] - target_pos[2])**2) ** 0.5
        
        if distance_km <= 200.0:
            # Find CPI score for this pair in the alerts
            cpi_score = 0.0
            for alert in cascade_summary.get("alerts", []):
                if ((alert["sat1"]["id"] == req.norad_id and alert["sat2"]["id"] == state.norad_id) or
                    (alert["sat1"]["id"] == state.norad_id and alert["sat2"]["id"] == req.norad_id)):
                    cpi_score = alert.get("cpi_score", 0.0)
                    break
            
            neighbors.append({
                "satellite_id": state.norad_id,
                "satellite_name": state.name,
                "distance_km": round(distance_km, 3),
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
                "cpi_score": round(cpi_score, 2),
                "collision_risk": "high" if cpi_score >= 7.0 else "medium" if cpi_score >= 5.0 else "low",
            })
    
    # Sort neighbors by distance
    neighbors.sort(key=lambda n: n["distance_km"])
    
    return {
        "status": "success",
        "manipulated_satellite": {
            "norad_id": req.norad_id,
            "name": target_state.name,
            "position": {
                "x": target_state.x,
                "y": target_state.y,
                "z": target_state.z,
            },
            "velocity": {
                "vx": target_state.vx,
                "vy": target_state.vy,
                "vz": target_state.vz,
            },
            "speed_kmh": round(float((target_state.vx**2 + target_state.vy**2 + target_state.vz**2) ** 0.5 * 3600.0), 2),
            "altitude_km": round(float(((target_state.x**2 + target_state.y**2 + target_state.z**2) ** 0.5) - 6371.0), 2),
        },
        "neighbors_within_200km": neighbors,
        "neighbor_count": len(neighbors),
        "alerts": cascade_summary.get("alerts", []),
        "cascade_plan": cascade_summary.get("cascade_plan", []),
        "graph": cascade_summary.get("graph", {}),
        "cascade_depth": cascade_summary.get("cascade_depth", 0),
        "total_delta_v_ms": cascade_summary.get("total_delta_v_ms", 0.0),
        "agencies_involved": cascade_summary.get("agencies_involved", []),
        "debris_clouds": debris_clouds,
    }
