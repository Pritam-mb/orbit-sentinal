"""
Graph-based cascade ranker.

This is a lightweight, deterministic graph-attention style scorer that keeps
the project self-contained. It is structured so a real torch_geometric GNN can
replace it later without changing the planner API.
"""

from __future__ import annotations

import numpy as np


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return 1.0 / (1.0 + np.exp(-values))


class CascadeGNN:
    """Deterministic graph scorer for cascade planning."""

    def predict(self, node_features, edge_index, edge_attr):
        node_features = np.asarray(node_features, dtype=float)
        edge_index = np.asarray(edge_index, dtype=int)
        edge_attr = np.asarray(edge_attr, dtype=float)

        if node_features.ndim != 2:
            raise ValueError("node_features must be a 2D array")

        node_count = node_features.shape[0]
        influence = np.zeros(node_count, dtype=float)

        if edge_index.size and edge_index.ndim == 2 and edge_index.shape[0] == 2:
            for idx in range(edge_index.shape[1]):
                src = int(edge_index[0, idx])
                dst = int(edge_index[1, idx])
                if src < 0 or dst < 0 or src >= node_count or dst >= node_count:
                    continue

                miss_distance_km = float(edge_attr[idx, 0]) if edge_attr.shape[0] > idx else 0.0
                relative_velocity_kms = float(edge_attr[idx, 1]) if edge_attr.shape[0] > idx else 0.0
                tca_minutes = float(edge_attr[idx, 2]) if edge_attr.shape[0] > idx else 0.0
                p_collision = float(edge_attr[idx, 3]) if edge_attr.shape[0] > idx else 0.0

                attention = (
                    0.45 * p_collision
                    + 0.25 * np.exp(-miss_distance_km / 120.0)
                    + 0.15 * min(relative_velocity_kms / 18.0, 1.0)
                    + 0.15 * np.exp(-max(tca_minutes, 0.0) / 180.0)
                )

                influence[src] += attention * 0.75
                influence[dst] += attention

        local_risk = node_features[:, 9] if node_features.shape[1] > 9 else np.zeros(node_count)
        altitude_term = 1.0 - np.clip(node_features[:, 7] / 2000.0, 0.0, 1.0) if node_features.shape[1] > 7 else np.zeros(node_count)

        logits = (1.35 * influence) + (0.25 * local_risk) + (0.10 * altitude_term)
        maneuver_probability = _sigmoid(logits - 0.75)

        cascade_depth = np.clip(np.ceil(maneuver_probability * 4.0), 0.0, 4.0).astype(int)

        delta_v = np.zeros((node_count, 3), dtype=float)
        if node_features.shape[1] >= 6:
            speed_bias = np.clip(node_features[:, 6] / 30000.0, 0.0, 1.0)
        else:
            speed_bias = np.zeros(node_count)

        delta_v[:, 1] = np.clip(0.05 + maneuver_probability * 1.4 + local_risk / 12.0 + speed_bias * 0.2, 0.05, 5.0)
        delta_v[:, 0] = np.clip((local_risk - 0.5) * 0.3, -1.0, 1.0)
        delta_v[:, 2] = np.clip((influence - 0.35) * 0.2, -1.0, 1.0)

        return {
            "maneuver_probability": maneuver_probability,
            "delta_v_rsw_ms": delta_v,
            "cascade_depth": cascade_depth,
            "graph_influence": influence,
        }