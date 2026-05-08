from __future__ import annotations

from functools import lru_cache
from datetime import datetime
from typing import Iterable

from app.core.sgp4_propagator import SatelliteState

from .lstm_predictor import LSTMPredictor


class MLRuntime:
    def __init__(self):
        self.trajectory = LSTMPredictor()

    def record_snapshot(self, states: Iterable[SatelliteState], timestamp: datetime):
        epoch = timestamp.isoformat()
        for state in states:
            self.trajectory.record(
                state.norad_id,
                epoch,
                float(state.x),
                float(state.y),
                float(state.z),
            )

    def forecast_satellite(self, norad_id: int, steps_ahead: int = 10) -> list[dict]:
        return self.trajectory.predict(norad_id, steps_ahead=steps_ahead)


@lru_cache(maxsize=1)
def get_ml_runtime() -> MLRuntime:
    return MLRuntime()
