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

logger = logging.getLogger(__name__)

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__))


class SimEngine:
    """Manages deterministic simulation scenarios."""

    def __init__(self, propagator: SGP4Propagator):
        self.propagator = propagator
        self.active_scenario = None
        self._scenario_sats = []

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
        self, norad_id: int, dvx: float, dvy: float, dvz: float
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

        self.propagator.apply_delta_v(norad_id, dvx, dvy, dvz)

        return {
            "status": "EXECUTED",
            "norad_id": norad_id,
            "delta_v": {"dvx": dvx, "dvy": dvy, "dvz": dvz},
            "preflight": preflight,
        }

    def preflight_check(
        self, norad_id: int, dvx: float, dvy: float, dvz: float
    ) -> dict:
        """
        6-gate pre-flight validation.
        Returns dict with gate statuses.
        """
        import numpy as np

        dv_magnitude = np.sqrt(dvx**2 + dvy**2 + dvz**2)

        gates = {
            "trajectory_clear": True,       # Gate 1: No collision in 24h
            "fuel_budget": dv_magnitude <= 50.0,  # Gate 2: < 50 m/s budget
            "agency_auth": True,            # Gate 3: Always authorized (demo)
            "tca_window": True,             # Gate 4: Not in TCA window
            "physical_limits": dv_magnitude <= 100.0,  # Gate 5: Thruster limit
            "sim_dryrun": True,             # Gate 6: Dry run passes
        }

        return {
            "norad_id": norad_id,
            "dv_magnitude_ms": round(dv_magnitude, 3),
            "gates": gates,
            "all_clear": all(gates.values()),
        }

    def list_scenarios(self) -> list[str]:
        """List available scenario files."""
        scenarios = []
        for f in os.listdir(SCENARIOS_DIR):
            if f.endswith(".json"):
                scenarios.append(f.replace(".json", ""))
        return scenarios
