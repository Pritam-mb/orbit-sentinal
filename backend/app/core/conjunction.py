"""
Conjunction assessment engine.
Computes pairwise miss distances and identifies close approaches.
"""

import numpy as np
import logging
from datetime import datetime, timedelta, timezone
from app.core.sgp4_propagator import SGP4Propagator, SatelliteState

logger = logging.getLogger(__name__)

# Thresholds
ALERT_DISTANCE_KM = 50.0       # Red alert
WARNING_DISTANCE_KM = 200.0    # Yellow warning
WATCH_DISTANCE_KM = 500.0      # Green watch


class ConjunctionEvent:
    """Represents a potential collision between two objects."""

    __slots__ = [
        "sat1_id", "sat1_name",
        "sat2_id", "sat2_name",
        "miss_distance_km",
        "relative_speed_kmh",
        "tca_utc",
        "severity",
    ]

    def __init__(self):
        self.sat1_id = 0
        self.sat1_name = ""
        self.sat2_id = 0
        self.sat2_name = ""
        self.miss_distance_km = 0.0
        self.relative_speed_kmh = 0.0
        self.tca_utc = ""
        self.severity = "green"

    def to_dict(self) -> dict:
        return {
            "sat1": {"id": self.sat1_id, "name": self.sat1_name},
            "sat2": {"id": self.sat2_id, "name": self.sat2_name},
            "miss_distance_km": round(self.miss_distance_km, 3),
            "relative_speed_kmh": round(self.relative_speed_kmh, 2),
            "tca_utc": self.tca_utc,
            "severity": self.severity,
        }


def classify_severity(distance_km: float) -> str:
    if distance_km <= ALERT_DISTANCE_KM:
        return "red"
    elif distance_km <= WARNING_DISTANCE_KM:
        return "yellow"
    elif distance_km <= WATCH_DISTANCE_KM:
        return "green"
    return "none"


def compute_miss_distance(s1: SatelliteState, s2: SatelliteState) -> float:
    """Euclidean distance between two satellite positions in km."""
    dx = s1.x - s2.x
    dy = s1.y - s2.y
    dz = s1.z - s2.z
    return np.sqrt(dx * dx + dy * dy + dz * dz)


def compute_relative_speed(s1: SatelliteState, s2: SatelliteState) -> float:
    """Relative speed in km/h."""
    dvx = s1.vx - s2.vx
    dvy = s1.vy - s2.vy
    dvz = s1.vz - s2.vz
    return np.sqrt(dvx * dvx + dvy * dvy + dvz * dvz) * 3600


def screen_conjunctions(
    states: list[SatelliteState],
    threshold_km: float = WATCH_DISTANCE_KM,
) -> list[ConjunctionEvent]:
    """
    Pairwise conjunction screening.
    Returns events where miss distance < threshold.
    """
    events = []
    n = len(states)

    for i in range(n):
        for j in range(i + 1, n):
            s1, s2 = states[i], states[j]

            # Skip if either had propagation errors
            if s1.error_code != 0 or s2.error_code != 0:
                continue

            dist = compute_miss_distance(s1, s2)
            severity = classify_severity(dist)

            if severity == "none":
                continue

            event = ConjunctionEvent()
            event.sat1_id = s1.norad_id
            event.sat1_name = s1.name
            event.sat2_id = s2.norad_id
            event.sat2_name = s2.name
            event.miss_distance_km = dist
            event.relative_speed_kmh = compute_relative_speed(s1, s2)
            event.tca_utc = s1.epoch_utc
            event.severity = severity

            events.append(event)

    # Sort by miss distance ascending (most critical first)
    events.sort(key=lambda e: e.miss_distance_km)
    return events


def find_tca(
    propagator: SGP4Propagator,
    id1: int,
    id2: int,
    start: datetime = None,
    hours_ahead: float = 24.0,
    steps: int = 240,
) -> ConjunctionEvent | None:
    """
    Find Time of Closest Approach between two satellites
    over the next `hours_ahead` hours using iterative search.
    """
    if start is None:
        start = datetime.now(timezone.utc)

    dt_step = timedelta(hours=hours_ahead) / steps
    min_dist = float("inf")
    best_event = None

    for i in range(steps):
        t = start + dt_step * i
        s1 = propagator.propagate_one(id1, t)
        s2 = propagator.propagate_one(id2, t)

        if s1 is None or s2 is None:
            continue
        if s1.error_code != 0 or s2.error_code != 0:
            continue

        dist = compute_miss_distance(s1, s2)

        if dist < min_dist:
            min_dist = dist
            severity = classify_severity(dist)

            event = ConjunctionEvent()
            event.sat1_id = s1.norad_id
            event.sat1_name = s1.name
            event.sat2_id = s2.norad_id
            event.sat2_name = s2.name
            event.miss_distance_km = dist
            event.relative_speed_kmh = compute_relative_speed(s1, s2)
            event.tca_utc = t.isoformat()
            event.severity = severity
            best_event = event

    return best_event
