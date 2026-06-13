"""
Test mode router for manual conjunction validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from types import SimpleNamespace
from threading import RLock
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.core.sgp4_propagator import SGP4Propagator, SatelliteState
from app.core.state_cache import set_latest_alerts
from app.services.conjunction_solver import parse_eci_state, run_to_tca
from app.services.debris_model import build_debris_alerts
from app.services.cascade_planner import CascadePlanner
from app.core.analytics import compute_collision_probability

_cascade_planner = CascadePlanner()

router = APIRouter(prefix="/api/test")


class SatelliteInput(BaseModel):
    name: Optional[str] = None
    norad_id: Optional[str] = None
    use_real_tle: bool = True
    position_eci_km: Optional[list[float]] = None
    velocity_eci_kms: Optional[list[float]] = None
    epoch_utc: Optional[str] = None

    @model_validator(mode="after")
    def validate_override(self):
        if self.position_eci_km and self.velocity_eci_kms and self.use_real_tle:
            self.use_real_tle = False

        if not self.use_real_tle:
            if not self.position_eci_km or not self.velocity_eci_kms:
                raise ValueError("Override requires position_eci_km and velocity_eci_kms")
            if len(self.position_eci_km) != 3 or len(self.velocity_eci_kms) != 3:
                raise ValueError("Override vectors must have 3 elements")

        return self


class TestSetupRequest(BaseModel):
    satellite_a: SatelliteInput
    satellite_b: SatelliteInput
    epoch_utc: Optional[str] = None


class RunToTcaRequest(BaseModel):
    target_utc: str
    step_seconds: float = Field(default=10.0, gt=0.0)
    max_steps: int = Field(default=3600, ge=1)


@dataclass
class TestSatellite:
    name: str
    norad_id: str
    position_eci_km: list[float]
    velocity_eci_kms: list[float]
    epoch_utc: datetime
    use_real_tle: bool


@dataclass
class TestSession:
    active: bool = False
    satellite_a: Optional[TestSatellite] = None
    satellite_b: Optional[TestSatellite] = None


_session = TestSession()
_session_lock = RLock()
_propagator: Optional[SGP4Propagator] = None


def init_test_mode(propagator: SGP4Propagator):
    global _propagator
    _propagator = propagator


def _parse_epoch(value: Optional[str], fallback: Optional[datetime] = None) -> datetime:
    if not value:
        return fallback or datetime.now(timezone.utc)

    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_norad_id(value: Optional[str]) -> int:
    if value is None:
        raise HTTPException(status_code=400, detail="NORAD ID is required")

    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="NORAD ID must be numeric")


def _load_state_from_propagator(norad_id: int, epoch: datetime):
    if _propagator is None:
        raise HTTPException(status_code=503, detail="Propagator not initialized")

    state = _propagator.propagate_one(norad_id, epoch)
    if state is None:
        raise HTTPException(status_code=404, detail="Satellite not found")
    if state.error_code != 0:
        raise HTTPException(status_code=500, detail="Propagation failed")
    return state


def _resolve_satellite_state(satellite: TestSatellite, now: datetime):
    if satellite.use_real_tle:
        norad_id = _normalize_norad_id(satellite.norad_id)
        state = _load_state_from_propagator(norad_id, now)
        position = [state.x, state.y, state.z]
        velocity = [state.vx, state.vy, state.vz]
        return position, velocity

    dt = (now - satellite.epoch_utc).total_seconds()
    position = [
        satellite.position_eci_km[0] + satellite.velocity_eci_kms[0] * dt,
        satellite.position_eci_km[1] + satellite.velocity_eci_kms[1] * dt,
        satellite.position_eci_km[2] + satellite.velocity_eci_kms[2] * dt,
    ]
    velocity = list(satellite.velocity_eci_kms)
    return position, velocity


def _build_satellite(input_data: SatelliteInput, epoch: datetime) -> TestSatellite:
    if input_data.use_real_tle:
        epoch = _parse_epoch(input_data.epoch_utc, epoch)
        norad_id = _normalize_norad_id(input_data.norad_id)
        state = _load_state_from_propagator(norad_id, epoch)
        name = input_data.name or state.name or "UNKNOWN"
        return TestSatellite(
            name=name,
            norad_id=str(state.norad_id),
            position_eci_km=[float(state.x), float(state.y), float(state.z)],
            velocity_eci_kms=[float(state.vx), float(state.vy), float(state.vz)],
            epoch_utc=epoch,
            use_real_tle=True,
        )

    name = input_data.name or "UNKNOWN"
    norad_id = str(input_data.norad_id or "0")
    return TestSatellite(
        name=name,
        norad_id=norad_id,
        position_eci_km=[float(x) for x in input_data.position_eci_km or []],
        velocity_eci_kms=[float(x) for x in input_data.velocity_eci_kms or []],
        epoch_utc=epoch,
        use_real_tle=False,
    )


def _to_test_state(satellite: TestSatellite) -> SimpleNamespace:
    return SimpleNamespace(
        error_code=0,
        norad_id=_normalize_norad_id(satellite.norad_id),
        name=satellite.name,
        x=float(satellite.position_eci_km[0]),
        y=float(satellite.position_eci_km[1]),
        z=float(satellite.position_eci_km[2]),
        vx=float(satellite.velocity_eci_kms[0]),
        vy=float(satellite.velocity_eci_kms[1]),
        vz=float(satellite.velocity_eci_kms[2]),
        epoch_utc=satellite.epoch_utc,
    )


def _publish_collision_alerts(sat_a: TestSatellite, sat_b: TestSatellite, result) -> dict:
    tca_time = _parse_epoch(result.tca_utc, sat_a.epoch_utc)
    sat1_id = _normalize_norad_id(sat_a.norad_id)
    sat2_id = _normalize_norad_id(sat_b.norad_id)

    # Propagate a sampled set of constellation satellites to the TCA epoch to avoid blocking the event loop
    active_states = []
    if _propagator is not None:
        ids = _propagator.norad_ids
        if len(ids) > 250:
            step = max(1, len(ids) // 250)
            sampled_ids = ids[::step][:250]
        else:
            sampled_ids = ids

        for norad_id in sampled_ids:
            state = _propagator.propagate_one(norad_id, tca_time)
            if state is not None and state.error_code == 0:
                active_states.append(state)

    # Build the SatelliteState containers for manual test satellites at TCA
    state_a_tca = SatelliteState(norad_id=sat1_id, name=sat_a.name)
    state_a_tca.x = result.position_a_eci[0]
    state_a_tca.y = result.position_a_eci[1]
    state_a_tca.z = result.position_a_eci[2]
    state_a_tca.vx = result.velocity_a_eci[0]
    state_a_tca.vy = result.velocity_a_eci[1]
    state_a_tca.vz = result.velocity_a_eci[2]
    state_a_tca.epoch_utc = result.tca_utc
    state_a_tca.error_code = 0

    state_b_tca = SatelliteState(norad_id=sat2_id, name=sat_b.name)
    state_b_tca.x = result.position_b_eci[0]
    state_b_tca.y = result.position_b_eci[1]
    state_b_tca.z = result.position_b_eci[2]
    state_b_tca.vx = result.velocity_b_eci[0]
    state_b_tca.vy = result.velocity_b_eci[1]
    state_b_tca.vz = result.velocity_b_eci[2]
    state_b_tca.epoch_utc = result.tca_utc
    state_b_tca.error_code = 0

    # Combine all states (constellation + manual test satellites)
    all_states = active_states + [state_a_tca, state_b_tca]

    # Dynamically compute collision probability and B-plane parameters using foster_integrate
    state_a_dict = {
        "x": state_a_tca.x, "y": state_a_tca.y, "z": state_a_tca.z,
        "vx": state_a_tca.vx, "vy": state_a_tca.vy, "vz": state_a_tca.vz
    }
    state_b_dict = {
        "x": state_b_tca.x, "y": state_b_tca.y, "z": state_b_tca.z,
        "vx": state_b_tca.vx, "vy": state_b_tca.vy, "vz": state_b_tca.vz
    }

    try:
        prob_res = compute_collision_probability(state_a_dict, state_b_dict)
        p_col = prob_res.get("p_collision", 0.0)
        bt_km = prob_res.get("b_t_km", 0.0)
        bn_km = prob_res.get("b_n_km", 0.0)
        covariance_ellipse = prob_res.get("covariance_ellipse") or {}
    except Exception as exc:
        logger.warning("compute_collision_probability failed for test satellites: %s", exc)
        miss_km = result.miss_distance_m / 1000.0
        p_col = math.exp(-0.5 * (miss_km / 0.5)**2)
        bt_km = 0.0
        bn_km = 0.0
        covariance_ellipse = {
            "a": 3000.0,
            "b": 1000.0,
            "angle": 0.5,
            "affection_rate": p_col * 100.0,
            "predicted_fragments": 150
        }

    miss_km = result.miss_distance_m / 1000.0
    cpi = max(1.0, min(10.0, 10.0 - 1.8 * miss_km))  # scales down to 1.0 at 5km
    severity = "critical" if cpi >= 8.0 else "warning" if cpi >= 5.0 else "watch"

    primary_alert = {
        "sat1": {"id": sat1_id, "name": sat_a.name},
        "sat2": {"id": sat2_id, "name": sat_b.name},
        "miss_distance_km": round(miss_km, 6),
        "relative_speed_kmh": round(float(result.relative_velocity_kms) * 3600.0, 3),
        "p_collision": p_col,
        "cpi_score": cpi,
        "hotspot_score": cpi,
        "severity": severity,
        "tca_minutes": 0.0,
        "tca_hours": 0.0,
        "tca_utc": result.tca_utc,
        "bt_km": bt_km,
        "bn_km": bn_km,
        "b_plane_bt_km": bt_km,
        "b_plane_bn_km": bn_km,
        "hotspot_position": {
            "x": round(float(state_a_tca.x + state_b_tca.x) / 2.0, 3),
            "y": round(float(state_a_tca.y + state_b_tca.y) / 2.0, 3),
            "z": round(float(state_a_tca.z + state_b_tca.z) / 2.0, 3),
        },
        "zone_radius_km": 100.0,
        "covariance_ellipse": covariance_ellipse
    }

    # Run the CascadePlanner to score risks, predict GNN probabilities, and construct the cascade plan
    cascade_summary = _cascade_planner.analyze_snapshot(
        states=all_states,
        alerts=[primary_alert],
        propagator=_propagator,
        reference_time=tca_time,
        cpi_threshold=5.0
    )

    planner_alerts = cascade_summary.get("alerts", [])
    has_primary = any(
        (a["sat1"]["id"] == sat1_id and a["sat2"]["id"] == sat2_id) or
        (a["sat1"]["id"] == sat2_id and a["sat2"]["id"] == sat1_id)
        for a in planner_alerts
    )
    if not has_primary:
        planner_alerts.insert(0, primary_alert)
    else:
        for a in planner_alerts:
            if (a["sat1"]["id"] == sat1_id and a["sat2"]["id"] == sat2_id) or (a["sat1"]["id"] == sat2_id and a["sat2"]["id"] == sat1_id):
                if "covariance_ellipse" not in a or not a["covariance_ellipse"]:
                    a["covariance_ellipse"] = primary_alert["covariance_ellipse"]
                a["bt_km"] = bt_km
                a["bn_km"] = bn_km
                a["b_plane_bt_km"] = bt_km
                a["b_plane_bn_km"] = bn_km

    # Inject default covariance ellipse fields for other alerts if they are missing
    for a in planner_alerts:
        if "covariance_ellipse" not in a or not a["covariance_ellipse"]:
            a_miss_km = a.get("miss_distance_km", 1.0)
            a_p_col = a.get("p_collision", 0.01)
            a["covariance_ellipse"] = {
                "a": max(100.0, a_miss_km * 400.0),
                "b": max(50.0, a_miss_km * 150.0),
                "angle": 0.5,
                "affection_rate": round(a_p_col * 100.0, 2),
                "predicted_fragments": 150
            }

    hotspots = cascade_summary.get("hotspots", [])
    primary_hotspot = {
        "sat1": {"id": sat1_id, "name": sat_a.name},
        "sat2": {"id": sat2_id, "name": sat_b.name},
        "miss_distance_km": round(miss_km, 6),
        "relative_velocity_kmh": round(float(result.relative_velocity_kms) * 3600.0, 3),
        "p_collision": p_col,
        "cpi_score": cpi,
        "hotspot_score": cpi,
        "severity": severity,
        "tca_minutes": 0.0,
        "tca_hours": 0.0,
        "tca_utc": result.tca_utc,
        "position": primary_alert["hotspot_position"],
        "zone_radius_km": 100.0,
    }
    has_primary_hotspot = any(
        (h["sat1"]["id"] == sat1_id and h["sat2"]["id"] == sat2_id) or
        (h["sat1"]["id"] == sat2_id and h["sat2"]["id"] == sat1_id)
        for h in hotspots
    )
    if not has_primary_hotspot:
        hotspots.insert(0, primary_hotspot)

    # Build debris alerts dynamically with all states
    debris_clouds = build_debris_alerts(
        hotspots,
        all_states,
        tca_time.isoformat(),
        alerts=planner_alerts,
        cpi_threshold=5.0
    )

    payload = {
        "timestamp": tca_time.isoformat(),
        "alerts": planner_alerts,
        "count": len(planner_alerts),
        "hotspots": hotspots,
        "graph": cascade_summary.get("graph", {}),
        "cascade_plan": cascade_summary.get("cascade_plan", []),
        "cascade_depth": cascade_summary.get("cascade_depth", 1),
        "total_delta_v_ms": cascade_summary.get("total_delta_v_ms", 0.0),
        "agencies_involved": cascade_summary.get("agencies_involved", []),
        "seed_satellites": cascade_summary.get("seed_satellites", [sat_a.name, sat_b.name]),
        "cpi_threshold": 5.0,
        "node_probabilities": cascade_summary.get("node_probabilities", {}),
        "debris_clouds": debris_clouds,
    }

    set_latest_alerts(payload)
    return payload



@router.post("/setup")
async def setup_test(req: TestSetupRequest):
    epoch = _parse_epoch(req.epoch_utc)
    epoch_a = _parse_epoch(req.satellite_a.epoch_utc, epoch)
    epoch_b = _parse_epoch(req.satellite_b.epoch_utc, epoch)

    if abs((epoch_a - epoch_b).total_seconds()) > 1.0:
        # Force both satellites onto the same epoch for deterministic run-to-tca
        epoch_b = epoch_a

    sat_a = _build_satellite(req.satellite_a, epoch_a)
    sat_b = _build_satellite(req.satellite_b, epoch_b)

    with _session_lock:
        _session.active = True
        _session.satellite_a = sat_a
        _session.satellite_b = sat_b

    return {
        "success": True,
        "satellite_a_id": sat_a.norad_id,
        "satellite_b_id": sat_b.norad_id,
    }


@router.post("/run-to-tca")
async def run_to_tca_endpoint(req: RunToTcaRequest):
    with _session_lock:
        if not _session.active or _session.satellite_a is None or _session.satellite_b is None:
            raise HTTPException(status_code=400, detail="Test mode is not initialized")

        sat_a = _session.satellite_a
        sat_b = _session.satellite_b

    target_utc = _parse_epoch(req.target_utc, sat_a.epoch_utc)

    state_a = parse_eci_state(sat_a.position_eci_km, sat_a.velocity_eci_kms, sat_a.epoch_utc)
    state_b = parse_eci_state(sat_b.position_eci_km, sat_b.velocity_eci_kms, sat_b.epoch_utc)

    result = run_to_tca(
        state_a=state_a,
        state_b=state_b,
        target_utc=target_utc,
        step_seconds=req.step_seconds,
        max_steps=req.max_steps,
        use_j2=True,
    )

    alert_payload = {
        "timestamp": result.tca_utc,
        "alerts": [],
        "count": 0,
        "hotspots": [],
        "graph": {},
        "cascade_plan": [],
        "cascade_depth": 0,
        "total_delta_v_ms": 0.0,
        "agencies_involved": [],
        "seed_satellites": [],
        "cpi_threshold": 7.0,
        "node_probabilities": {},
        "debris_clouds": [],
    }

    if result.collision_detected or result.miss_distance_m <= 5000.0:
        alert_payload = _publish_collision_alerts(sat_a, sat_b, result)
    else:
        set_latest_alerts(alert_payload)

    return {
        "tca_utc": result.tca_utc,
        "miss_distance_m": result.miss_distance_m,
        "relative_velocity_kms": result.relative_velocity_kms,
        "position_a_eci": result.position_a_eci,
        "position_b_eci": result.position_b_eci,
        "collision_detected": result.collision_detected,
        "trajectory_a": result.trajectory_a,
        "trajectory_b": result.trajectory_b,
        "alerts": alert_payload.get("alerts", []),
        "hotspots": alert_payload.get("hotspots", []),
        "cascade_plan": alert_payload.get("cascade_plan", []),
        "graph": alert_payload.get("graph", {}),
        "cascade_depth": alert_payload.get("cascade_depth", 0),
        "total_delta_v_ms": alert_payload.get("total_delta_v_ms", 0.0),
        "agencies_involved": alert_payload.get("agencies_involved", []),
        "seed_satellites": alert_payload.get("seed_satellites", []),
        "cpi_threshold": alert_payload.get("cpi_threshold", 7.0),
        "node_probabilities": alert_payload.get("node_probabilities", {}),
        "debris_clouds": alert_payload.get("debris_clouds", []),
    }


@router.get("/separation")
async def get_separation():
    with _session_lock:
        if not _session.active or _session.satellite_a is None or _session.satellite_b is None:
            raise HTTPException(status_code=400, detail="Test mode is not initialized")

        sat_a = _session.satellite_a
        sat_b = _session.satellite_b

    now = datetime.now(timezone.utc)
    pos_a, vel_a = _resolve_satellite_state(sat_a, now)
    pos_b, vel_b = _resolve_satellite_state(sat_b, now)

    rx = pos_a[0] - pos_b[0]
    ry = pos_a[1] - pos_b[1]
    rz = pos_a[2] - pos_b[2]
    separation_km = math.sqrt(rx * rx + ry * ry + rz * rz)

    rvx = vel_a[0] - vel_b[0]
    rvy = vel_a[1] - vel_b[1]
    rvz = vel_a[2] - vel_b[2]
    rel_speed_sq = rvx * rvx + rvy * rvy + rvz * rvz

    if separation_km > 0:
        closing_rate_kms = (rx * rvx + ry * rvy + rz * rvz) / separation_km
    else:
        closing_rate_kms = 0.0

    if rel_speed_sq > 0:
        time_to_tca_s = -((rx * rvx + ry * rvy + rz * rvz) / rel_speed_sq)
    else:
        time_to_tca_s = 0.0

    return {
        "separation_km": round(separation_km, 6),
        "closing_rate_kms": round(closing_rate_kms, 6),
        "time_to_tca_s": round(max(time_to_tca_s, 0.0), 3),
        "epoch_utc": now.isoformat(),
    }
