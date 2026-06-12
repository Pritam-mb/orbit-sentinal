"""
Simulation engine.
Loads deterministic scenario JSONs and overrides satellite states.
Applies delta-V maneuvers for demo purposes.
"""

import json
import os
import logging
from datetime import datetime, timezone
from app.core.sgp4_propagator import SGP4Propagator
from app.core.conjunction import WARNING_DISTANCE_KM, find_tca

try:
    from app.core.agency_authority import authority_manager
    _AUTHORITY_AVAILABLE = True
except ImportError:
    authority_manager = None
    _AUTHORITY_AVAILABLE = False

logger = logging.getLogger(__name__)

AGENCY_ALIASES = [
    ("STARLINK", "SpaceX"),
    ("SPACEX", "SpaceX"),
    ("ISS", "ISS"),
    ("COSMOS", "Roscosmos"),
    ("RESURS", "Roscosmos"),
    ("FENGYUN", "CNSA"),
    ("YAOGAN", "CNSA"),
    ("NOAA", "NOAA"),
    ("HUBBLE", "NASA"),
    ("IRIDIUM", "Iridium"),
]

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__))


class SimEngine:
    """Manages deterministic simulation scenarios."""

    def __init__(self, propagator: SGP4Propagator):
        self.propagator = propagator
        self.active_scenario = None
        self._scenario_sats = []

    def _infer_agency(self, name: str) -> str:
        upper_name = (name or "").upper()
        for keyword, agency in AGENCY_ALIASES:
            if keyword in upper_name:
                return agency
        return "Unknown"

    def _clone_propagator(self) -> SGP4Propagator:
        clone = SGP4Propagator()
        with self.propagator._lock:
            clone._satellites = dict(self.propagator._satellites)
            clone._maneuvers = dict(self.propagator._maneuvers)
        return clone

    def _assess_future_conjunctions(self, propagator: SGP4Propagator, target_id: int, start_time: datetime) -> dict:
        nearest = None

        for other_id in propagator.norad_ids:
            if other_id == target_id:
                continue

            event = find_tca(
                propagator,
                target_id,
                other_id,
                start=start_time,
                hours_ahead=24.0,
                steps=120,
            )
            if event is None:
                continue

            try:
                event_time = datetime.fromisoformat(event.tca_utc)
            except Exception:
                event_time = start_time

            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)

            event_minutes = max(0.0, (event_time - start_time).total_seconds() / 60.0)
            if nearest is None or event.miss_distance_km < nearest["min_miss_distance_km"]:
                nearest = {
                    "other_id": other_id,
                    "other_name": event.sat2_name if event.sat1_id == target_id else event.sat1_name,
                    "min_miss_distance_km": float(event.miss_distance_km),
                    "closest_tca_minutes": float(event_minutes),
                    "tca_utc": event_time.isoformat(),
                    "severity": event.severity,
                }

        return nearest or {
            "other_id": None,
            "other_name": None,
            "min_miss_distance_km": None,
            "closest_tca_minutes": None,
            "tca_utc": None,
            "severity": None,
        }

    def load_scenario(self, scenario_name: str) -> dict:
        """
        Load a scenario JSON and inject its satellites into the propagator.
        Returns the scenario metadata.
        """
        path = os.path.join(SCENARIOS_DIR, f"{scenario_name}.json")

        if not os.path.exists(path):
            raise FileNotFoundError(f"Scenario not found: {scenario_name}")

        with open(path, "r") as f:
            scenario = json.load(f)

        # Inject scenario satellites into the propagator
        tle_list = scenario.get("satellites", [])
        if tle_list:
            self.propagator.load_tles(
                self.propagator._satellites
                and [
                    {
                        "name": name,
                        "norad_id": nid,
                        "line1": sat.tle_line1 if hasattr(sat, 'tle_line1') else "",
                        "line2": sat.tle_line2 if hasattr(sat, 'tle_line2') else "",
                    }
                    for nid, (sat, name) in self.propagator._satellites.items()
                ]
                or []
            )
            # Add scenario sats on top
            for tle in tle_list:
                from sgp4.api import Satrec, WGS72
                try:
                    sat = Satrec.twoline2rv(tle["line1"], tle["line2"], WGS72)
                    self.propagator._satellites[tle["norad_id"]] = (sat, tle["name"])
                    self._scenario_sats.append(tle["norad_id"])
                except Exception as e:
                    logger.warning(f"Failed to load scenario sat: {e}")

        self.active_scenario = scenario
        logger.info(f"Loaded scenario: {scenario.get('name', scenario_name)}")

        return {
            "name": scenario.get("name", scenario_name),
            "description": scenario.get("description", ""),
            "tca_minutes": scenario.get("tca_minutes_from_trigger", 0),
            "satellites_injected": len(tle_list),
        }

    def clear_scenario(self):
        """Remove scenario satellites from the propagator."""
        for nid in self._scenario_sats:
            self.propagator._satellites.pop(nid, None)
        self._scenario_sats.clear()
        self.active_scenario = None
        logger.info("Scenario cleared")

    def apply_maneuver(
        self,
        norad_id: int,
        dvx: float,
        dvy: float,
        dvz: float,
        frame: str = "RSW",
    ) -> dict:
        """
        Apply a delta-V impulse maneuver.
        Returns validation results.
        """
        preflight = self.preflight_check(norad_id, dvx, dvy, dvz)

        if not all(preflight["gates"].values()):
            return {
                "status": "BLOCKED",
                "preflight": preflight,
            }

        result = self.propagator.apply_delta_v(norad_id, dvx, dvy, dvz, frame=frame)
        if result.get("status") != "success":
            return {"status": "ERROR", "preflight": preflight, **result}

        return {**result, "preflight": preflight}

    def preflight_check(
        self,
        norad_id: int,
        dvx: float,
        dvy: float,
        dvz: float,
        frame: str = "RSW",
        session_id: str = "DEMO_SESSION",
    ) -> dict:
        """
        6-gate pre-flight validation based on cloned orbit simulation.
        Returns dict with gate statuses and the nearest future encounter.

        Gate: agency_auth
            Checked via AgencyAuthorityManager.check_authority.
            DEMO_SESSION always passes. Named agency sessions enforce ownership.
        """
        import numpy as np

        dv_magnitude = np.sqrt(dvx**2 + dvy**2 + dvz**2)
        now = datetime.now(timezone.utc)
        current_state = self.propagator.propagate_one(norad_id, now)
        target_name = current_state.name if current_state is not None else f"NORAD-{norad_id}"
        agency = self._infer_agency(target_name)

        # ── Real agency authority check (replaces hardcoded True) ────────────
        if _AUTHORITY_AVAILABLE and authority_manager is not None:
            try:
                agency_auth = authority_manager.check_authority(
                    session_id, norad_id, target_name
                )
            except Exception as auth_err:
                logger.warning("Authority check failed: %s — defaulting to DEMO_SESSION allow", auth_err)
                agency_auth = (session_id == "DEMO_SESSION")
        else:
            # Fallback: DEMO_SESSION is always allowed
            agency_auth = (session_id == "DEMO_SESSION")

        cloned_propagator = self._clone_propagator()
        burn_result = cloned_propagator.apply_delta_v(norad_id, dvx, dvy, dvz, frame=frame)

        future_risk = None
        gates = {
            "trajectory_clear": False,
            "fuel_budget": dv_magnitude <= 50.0,
            "agency_auth": agency_auth,
            "tca_window": False,
            "physical_limits": False,
            "sim_dryrun": False,
        }

        if burn_result.get("status") == "success":
            future_risk = self._assess_future_conjunctions(cloned_propagator, norad_id, now)
            min_miss = future_risk.get("min_miss_distance_km")
            tca_minutes = future_risk.get("closest_tca_minutes")

            gates.update({
                "trajectory_clear": min_miss is None or min_miss > WARNING_DISTANCE_KM,
                "tca_window": tca_minutes is None or tca_minutes > 60.0,
                "physical_limits": burn_result.get("new_perigee_km", 0.0) >= 100.0 and dv_magnitude <= 100.0,
                "sim_dryrun": True,
            })

        all_clear = all(gates.values())

        return {
            "norad_id": norad_id,
            "satellite_name": target_name,
            "agency": agency,
            "frame": frame,
            "dv_magnitude_ms": round(dv_magnitude, 3),
            "gates": gates,
            "all_clear": all_clear,
            "trajectory": future_risk,
            "burn": burn_result,
        }

    def list_scenarios(self) -> list[str]:
        """List available scenario files."""
        scenarios = []
        for f in os.listdir(SCENARIOS_DIR):
            if f.endswith(".json"):
                scenarios.append(f.replace(".json", ""))
        return scenarios
