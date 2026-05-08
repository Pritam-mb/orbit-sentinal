"""
LSTM Trajectory Predictor — Hackathon Placeholder.
Ingests ring buffer of satellite positions for time-series forecasting.
Currently returns linear extrapolation as mock.
"""

import numpy as np
import logging
from collections import deque

logger = logging.getLogger(__name__)


class RingBuffer:
    """
    Fixed-size circular buffer for satellite position history.
    Stores (timestamp, x, y, z) tuples.
    """

    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self._buffer: deque = deque(maxlen=capacity)

    def push(self, timestamp: str, x: float, y: float, z: float):
        self._buffer.append((timestamp, x, y, z))

    def get_positions(self) -> np.ndarray:
        """Return positions as Nx3 numpy array."""
        if len(self._buffer) == 0:
            return np.array([]).reshape(0, 3)
        return np.array([(x, y, z) for _, x, y, z in self._buffer])

    def get_all(self) -> list[tuple]:
        return list(self._buffer)

    @property
    def size(self) -> int:
        return len(self._buffer)

    @property
    def is_full(self) -> bool:
        return len(self._buffer) == self.capacity


class LSTMPredictor:
    """
    Time-series trajectory forecaster.
    Structured for real LSTM/transformer model drop-in.
    Currently uses linear extrapolation.
    """

    def __init__(self, model_path: str = None):
        self.model = None
        self._buffers: dict[int, RingBuffer] = {}

        if model_path:
            self._load_model(model_path)

    def _load_model(self, path: str):
        """Load a trained LSTM model."""
        try:
            # import tensorflow as tf
            # self.model = tf.keras.models.load_model(path)
            logger.info(f"LSTM model loaded from {path}")
        except Exception as e:
            logger.warning(f"Failed to load LSTM model: {e}")

    def get_buffer(self, norad_id: int) -> RingBuffer:
        """Get or create ring buffer for a satellite."""
        if norad_id not in self._buffers:
            self._buffers[norad_id] = RingBuffer(capacity=100)
        return self._buffers[norad_id]

    def record(self, norad_id: int, timestamp: str, x: float, y: float, z: float):
        """Record a position snapshot into the ring buffer."""
        buf = self.get_buffer(norad_id)
        buf.push(timestamp, x, y, z)

    def predict(self, norad_id: int, steps_ahead: int = 10) -> list[dict]:
        """
        Predict future positions for a satellite.
        Returns list of {step, x, y, z} dicts.
        Currently uses linear extrapolation as mock.
        """
        buf = self.get_buffer(norad_id)
        positions = buf.get_positions()

        if len(positions) < 2:
            return []

        if self.model is not None:
            # Normalize input
            # seq = positions[-self.sequence_length:]
            # seq_normalized = (seq - self.mean) / self.std
            # prediction = self.model.predict(seq_normalized.reshape(1, -1, 3))
            # return denormalized prediction
            pass

        # Mock: linear extrapolation from last two points
        p1 = positions[-2]
        p2 = positions[-1]
        velocity = p2 - p1  # km per time step

        predictions = []
        for i in range(1, steps_ahead + 1):
            future = p2 + velocity * i
            predictions.append({
                "step": i,
                "x": round(float(future[0]), 3),
                "y": round(float(future[1]), 3),
                "z": round(float(future[2]), 3),
            })

        return predictions
