"""
Conjunction solver for test mode.
Propagates two injected satellites and finds the minimum separation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np
from scipy.integrate import solve_ivp

MU_EARTH_KM3_S2 = 398600.4418
R_EARTH_KM = 6378.137
J2_EARTH = 1.08262668e-3
COLLISION_THRESHOLD_M = 1.0


@dataclass
class EciState:
    position_km: np.ndarray
    velocity_kms: np.ndarray
    epoch_utc: datetime


@dataclass
class TcaResult:
    tca_utc: str
    miss_distance_m: float
    relative_velocity_kms: float
    position_a_eci: list[float]
    position_b_eci: list[float]
    velocity_a_eci: list[float]
    velocity_b_eci: list[float]
    collision_detected: bool
    trajectory_a: list[list]
    trajectory_b: list[list]


def _accel_two_body(
    position_km: np.ndarray,
    use_j2: bool = True,
) -> np.ndarray:
    r2 = float(np.dot(position_km, position_km))
    r = np.sqrt(r2)
    if r == 0.0:
        return np.zeros(3)

    accel = -MU_EARTH_KM3_S2 * position_km / (r**3)

    if use_j2:
        z2 = position_km[2] ** 2
        factor = 1.5 * J2_EARTH * MU_EARTH_KM3_S2 * (R_EARTH_KM**2) / (r**5)
        scale = (5.0 * z2 / r2) - 1.0
        accel_j2 = np.array([
            position_km[0] * scale,
            position_km[1] * scale,
            position_km[2] * ((5.0 * z2 / r2) - 3.0),
        ])
        accel = accel + factor * accel_j2

    return accel


def _rk45_propagate(
    state: EciState,
    t_eval: np.ndarray,
    use_j2: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    if len(t_eval) == 1:
        positions = np.array([state.position_km])
        velocities = np.array([state.velocity_kms])
        return positions, velocities

    def dynamics(_t: float, y: np.ndarray) -> np.ndarray:
        position = y[:3]
        velocity = y[3:]
        accel = _accel_two_body(position, use_j2=use_j2)
        return np.concatenate((velocity, accel))

    y0 = np.concatenate((state.position_km, state.velocity_kms))
    solution = solve_ivp(
        dynamics,
        (float(t_eval[0]), float(t_eval[-1])),
        y0,
        method="RK45",
        t_eval=t_eval,
        rtol=1e-8,
        atol=1e-8,
    )

    if not solution.success or solution.y.shape[1] != len(t_eval):
        # Fallback: linear propagation for robustness
        dt = t_eval - t_eval[0]
        positions = state.position_km + np.outer(dt, state.velocity_kms)
        velocities = np.repeat(state.velocity_kms[None, :], len(t_eval), axis=0)
        return positions, velocities

    positions = solution.y[:3].T
    velocities = solution.y[3:].T
    return positions, velocities


def run_to_tca(
    state_a: EciState,
    state_b: EciState,
    target_utc: datetime,
    step_seconds: float,
    max_steps: int,
    use_j2: bool = True,
) -> TcaResult:
    start = state_a.epoch_utc
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    total_seconds = max(0.0, (target_utc - start).total_seconds())
    if step_seconds <= 0:
        step_seconds = 1.0

    max_steps = max(1, int(max_steps))
    if total_seconds == 0.0:
        t_eval = np.array([0.0])
    else:
        steps = max(1, int(np.ceil(total_seconds / step_seconds)))
        steps = min(steps, max_steps)
        t_eval = np.linspace(0.0, steps * step_seconds, steps + 1)

    positions_a, velocities_a = _rk45_propagate(state_a, t_eval, use_j2=use_j2)
    positions_b, velocities_b = _rk45_propagate(state_b, t_eval, use_j2=use_j2)

    deltas = positions_a - positions_b
    distances_km = np.linalg.norm(deltas, axis=1)
    min_index = int(np.argmin(distances_km))

    min_distance_km = float(distances_km[min_index])
    rel_velocity = velocities_a[min_index] - velocities_b[min_index]
    rel_velocity_kms = float(np.linalg.norm(rel_velocity))

    tca_time = start + timedelta(seconds=float(t_eval[min_index]))
    tca_utc = tca_time.replace(tzinfo=timezone.utc).isoformat()

    trajectory_a = []
    trajectory_b = []
    for i, t_offset in enumerate(t_eval):
        ts = start + timedelta(seconds=float(t_offset))
        iso = ts.replace(tzinfo=timezone.utc).isoformat()
        trajectory_a.append([iso, float(positions_a[i][0]), float(positions_a[i][1]), float(positions_a[i][2])])
        trajectory_b.append([iso, float(positions_b[i][0]), float(positions_b[i][1]), float(positions_b[i][2])])

    collision_detected = (min_distance_km * 1000.0) <= COLLISION_THRESHOLD_M

    return TcaResult(
        tca_utc=tca_utc,
        miss_distance_m=round(min_distance_km * 1000.0, 3),
        relative_velocity_kms=round(rel_velocity_kms, 5),
        position_a_eci=[float(x) for x in positions_a[min_index]],
        position_b_eci=[float(x) for x in positions_b[min_index]],
        velocity_a_eci=[float(x) for x in velocities_a[min_index]],
        velocity_b_eci=[float(x) for x in velocities_b[min_index]],
        collision_detected=collision_detected,
        trajectory_a=trajectory_a,
        trajectory_b=trajectory_b,
    )


def parse_eci_state(
    position_eci_km: Iterable[float],
    velocity_eci_kms: Iterable[float],
    epoch_utc: datetime,
) -> EciState:
    return EciState(
        position_km=np.array(list(position_eci_km), dtype=float),
        velocity_kms=np.array(list(velocity_eci_kms), dtype=float),
        epoch_utc=epoch_utc,
    )
