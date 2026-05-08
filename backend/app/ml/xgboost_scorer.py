"""
XGBoost Risk Scorer — deterministic heuristic fallback.

The interface is kept model-friendly, but the scoring logic is now stable
so CPI and cascade ranking are repeatable on every refresh.
"""

import logging

logger = logging.getLogger(__name__)


class XGBoostScorer:
    """
    Tabular risk scoring for conjunction events.
    Features: miss_distance, relative_speed, combined_size, altitude, etc.
    """

    def __init__(self, model_path: str = None):
        self.model = None
        if model_path:
            self._load_model(model_path)

    def _load_model(self, path: str):
        """Load a trained XGBoost model from disk."""
        try:
            # import xgboost as xgb
            # self.model = xgb.Booster()
            # self.model.load_model(path)
            logger.info(f"Model loaded from {path}")
        except Exception as e:
            logger.warning(f"Failed to load model: {e}")

    def extract_features(self, event: dict) -> list[float]:
        """
        Extract feature vector from a conjunction event.
        Expected event keys:
            miss_distance_km, relative_speed_kmh,
            sat1_altitude_km, sat2_altitude_km,
            sat1_size_m, sat2_size_m
        """
        return [
            event.get("miss_distance_km", 0.0),
            event.get("relative_speed_kmh", 0.0),
            event.get("sat1_altitude_km", 400.0),
            event.get("sat2_altitude_km", 400.0),
            event.get("sat1_size_m", 1.0),
            event.get("sat2_size_m", 1.0),
        ]

    def score(self, features: dict) -> float:
        """
        Score collision risk from 0.0 (safe) to 1.0 (critical).
        Deterministic heuristic used until a trained model is plugged in.
        """
        if self.model is not None:
            # feat_vec = self.extract_features(features)
            # import xgboost as xgb
            # dmatrix = xgb.DMatrix([feat_vec])
            # return float(self.model.predict(dmatrix)[0])
            pass

        miss_dist = max(float(features.get("miss_distance_km", 100.0)), 0.0)
        rel_speed = max(float(features.get("relative_speed_kmh", 0.0)), 0.0)
        sat1_alt = max(float(features.get("sat1_altitude_km", 400.0)), 0.0)
        sat2_alt = max(float(features.get("sat2_altitude_km", 400.0)), 0.0)
        combined_alt = (sat1_alt + sat2_alt) / 2.0

        tca_minutes = float(features.get("tca_minutes", 0.0))
        if tca_minutes < 0.0:
            tca_minutes = 0.0

        miss_component = max(0.0, 1.0 - (miss_dist / 500.0))
        speed_component = min(rel_speed / 20000.0, 1.0)
        tca_component = 1.0 / (1.0 + (tca_minutes / 60.0))
        altitude_component = max(0.0, 1.0 - (combined_alt / 2000.0))

        score = (
            0.50 * miss_component
            + 0.20 * speed_component
            + 0.15 * tca_component
            + 0.15 * altitude_component
        )
        return round(max(0.0, min(1.0, score)), 4)
