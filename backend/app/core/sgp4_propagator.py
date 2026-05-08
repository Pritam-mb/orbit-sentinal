"""
SGP4 orbit propagator.
Parses TLE lines and propagates to arbitrary epoch.
Returns ECI position (km) and velocity (km/s).
SGP4 inherently models J2 oblateness and BSTAR atmospheric drag.
"""

from datetime import datetime, timezone
from threading import RLock
from sgp4.api import Satrec, WGS72
from sgp4.api import jday
import numpy as np
import logging

logger = logging.getLogger(__name__)


class SatelliteState:
    """Container for a satellite's propagated state."""

    __slots__ = [
        "norad_id", "name",
        "x", "y", "z",
        "vx", "vy", "vz",
        "epoch_utc", "error_code",
    ]

    def __init__(self, norad_id: int, name: str):
        self.norad_id = norad_id
        self.name = name
        self.x = self.y = self.z = 0.0
        self.vx = self.vy = self.vz = 0.0
        self.epoch_utc = ""
        self.error_code = 0

    def to_dict(self) -> dict:
        speed_kmh = np.sqrt(self.vx**2 + self.vy**2 + self.vz**2) * 3600
        alt_km = np.sqrt(self.x**2 + self.y**2 + self.z**2) - 6371.0
        return {
            "norad_id": self.norad_id,
            "name": self.name,
            "position": {"x": self.x, "y": self.y, "z": self.z},
            "velocity": {"vx": self.vx, "vy": self.vy, "vz": self.vz},
            "speed_kmh": round(speed_kmh, 2),
            "altitude_km": round(alt_km, 2),
            "epoch_utc": self.epoch_utc,
        }


class SGP4Propagator:
    """Batch SGP4 propagator for multiple satellites."""

    def __init__(self):
        self._satellites: dict[int, tuple[Satrec, str]] = {}
        self._lock = RLock()

    def load_tles(self, tle_list: list[dict]):
        """
        Load TLEs into the propagator.
        Each entry: {name, norad_id, line1, line2}
        """
        with self._lock:
            self._satellites.clear()
            for tle in tle_list:
                try:
                    sat = Satrec.twoline2rv(tle["line1"], tle["line2"], WGS72)
                    self._satellites[tle["norad_id"]] = (sat, tle["name"])
                except Exception as e:
                    logger.warning(
                        f"Failed to parse TLE for {tle.get('name', '?')}: {e}"
                    )

        logger.info(f"Loaded {len(self._satellites)} satellites into propagator")

    def propagate_all(self, dt: datetime = None) -> list[SatelliteState]:
        """
        Propagate all loaded satellites to the given datetime.
        Returns list of SatelliteState objects.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)

        jd, fr = jday(
            dt.year, dt.month, dt.day,
            dt.hour, dt.minute, dt.second + dt.microsecond / 1e6,
        )

        results = []
        with self._lock:
            satellites = list(self._satellites.items())

        for norad_id, (sat, name) in satellites:
            state = SatelliteState(norad_id, name)
            state.epoch_utc = dt.isoformat()

            e, r, v = sat.sgp4(jd, fr)
            state.error_code = e

            if e == 0:
                state.x, state.y, state.z = r
                state.vx, state.vy, state.vz = v
            else:
                logger.debug(f"SGP4 error {e} for {name} (NORAD {norad_id})")

            results.append(state)

        return results

    def propagate_one(
        self, norad_id: int, dt: datetime = None
    ) -> SatelliteState | None:
        """Propagate a single satellite."""
        with self._lock:
            if norad_id not in self._satellites:
                return None

            sat, name = self._satellites[norad_id]

        if dt is None:
            dt = datetime.now(timezone.utc)

        state = SatelliteState(norad_id, name)
        state.epoch_utc = dt.isoformat()

        jd, fr = jday(
            dt.year, dt.month, dt.day,
            dt.hour, dt.minute, dt.second + dt.microsecond / 1e6,
        )

        e, r, v = sat.sgp4(jd, fr)
        state.error_code = e

        if e == 0:
            state.x, state.y, state.z = r
            state.vx, state.vy, state.vz = v

        return state

    def apply_delta_v(self, norad_id: int, dvx: float, dvy: float, dvz: float):
        """
        Apply a delta-V maneuver to a satellite's velocity.
        This is a simplified impulse burn model.
        Note: modifies the internal TLE-derived orbit, so further
        propagation won't be physically accurate. For demo purposes.
        """
        # Store maneuver for sim_engine to apply during propagation
        with self._lock:
            if norad_id in self._satellites:
                sat, name = self._satellites[norad_id]
                # We'll track maneuvers separately since SGP4 is TLE-based
                if not hasattr(self, '_maneuvers'):
                    self._maneuvers = {}
                self._maneuvers[norad_id] = (dvx, dvy, dvz)

    def get_maneuver(self, norad_id: int) -> tuple | None:
        with self._lock:
            if hasattr(self, '_maneuvers') and norad_id in self._maneuvers:
                return self._maneuvers.pop(norad_id)
        return None

    @property
    def satellite_count(self) -> int:
        with self._lock:
            return len(self._satellites)

    @property
    def norad_ids(self) -> list[int]:
        with self._lock:
            return list(self._satellites.keys())
