"""
Constellation cascade planner.

Builds a proximity graph with KD-tree pruning, scores each conjunction with a
deterministic CPI heuristic, and produces a cascade maneuver plan that can be
shown on the dashboard.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import math
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from app.core.conjunction import classify_severity
from app.core.sgp4_propagator import SatelliteState, rsw_to_eci
from app.ml.gnn_cascade import CascadeGNN
from app.ml.xgboost_scorer import XGBoostScorer

logger = logging.getLogger(__name__)

R_EARTH_KM = 6371.0
DEFAULT_INFLUENCE_RADIUS_KM = 200.0
DEFAULT_CPI_THRESHOLD = 5.0


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


@dataclass
class CascadeNode:
    norad_id: int
    name: str
    position: np.ndarray
    velocity: np.ndarray
    speed_kmh: float
    altitude_km: float
    agency: str


def infer_agency(name: str) -> str:
    upper_name = (name or "").upper()
    for keyword, agency in AGENCY_ALIASES:
        if keyword in upper_name:
            return agency
    return "Unknown"


def _norm(vec: np.ndarray) -> float:
    return float(np.linalg.norm(vec))


def _estimate_linear_tca_minutes(
    pos_a: np.ndarray,
    vel_a: np.ndarray,
    pos_b: np.ndarray,
    vel_b: np.ndarray,
) -> tuple[float, float]:
    relative_position = pos_a - pos_b
    relative_velocity = vel_a - vel_b
    relative_speed_sq = float(np.dot(relative_velocity, relative_velocity))

    if relative_speed_sq <= 1e-12:
        return 0.0, _norm(relative_position)

    t_seconds = -float(np.dot(relative_position, relative_velocity)) / relative_speed_sq
    if t_seconds < 0.0:
        t_seconds = 0.0

    closest_position = relative_position + (relative_velocity * t_seconds)
    return t_seconds / 60.0, _norm(closest_position)


def _build_node(state: SatelliteState) -> CascadeNode:
    speed_kmh = float(np.linalg.norm([state.vx, state.vy, state.vz]) * 3600.0)
    altitude_km = float(np.linalg.norm([state.x, state.y, state.z]) - R_EARTH_KM)
    return CascadeNode(
        norad_id=state.norad_id,
        name=state.name,
        position=np.array([state.x, state.y, state.z], dtype=float),
        velocity=np.array([state.vx, state.vy, state.vz], dtype=float),
        speed_kmh=speed_kmh,
        altitude_km=altitude_km,
        agency=infer_agency(state.name),
    )


class CascadePlanner:
    """KD-tree based proximity graph planner with cascade scoring."""

    def __init__(self):
        self.risk_model = XGBoostScorer()
        self.gnn = CascadeGNN()

    def build_graph(
        self,
        states: list[SatelliteState],
        influence_radius_km: float = DEFAULT_INFLUENCE_RADIUS_KM,
    ) -> dict[str, Any]:
        nodes = [_build_node(state) for state in states if state.error_code == 0]
        if not nodes:
            return {
                "nodes": [],
                "edges": [],
                "adjacency": {},
                "summary": {
                    "node_count": 0,
                    "edge_count": 0,
                    "influence_radius_km": influence_radius_km,
                },
            }

        positions = np.array([node.position for node in nodes], dtype=float)
        velocities = np.array([node.velocity for node in nodes], dtype=float)
        tree = cKDTree(positions)
        candidate_pairs = sorted(tree.query_pairs(r=influence_radius_km))

        edges: list[dict[str, Any]] = []
        adjacency: dict[int, list[dict[str, Any]]] = {node.norad_id: [] for node in nodes}
        node_index = {node.norad_id: idx for idx, node in enumerate(nodes)}

        for idx_a, idx_b in candidate_pairs:
            node_a = nodes[idx_a]
            node_b = nodes[idx_b]
            miss_distance_km = _norm(node_a.position - node_b.position)
            relative_velocity_kms = _norm(node_a.velocity - node_b.velocity)
            tca_minutes, predicted_miss_km = _estimate_linear_tca_minutes(
                node_a.position,
                node_a.velocity,
                node_b.position,
                node_b.velocity,
            )

            risk_features = {
                "miss_distance_km": predicted_miss_km,
                "relative_speed_kmh": relative_velocity_kms * 3600.0,
                "sat1_altitude_km": node_a.altitude_km,
                "sat2_altitude_km": node_b.altitude_km,
                "tca_minutes": tca_minutes,
            }
            p_collision = self.risk_model.score(risk_features)
            cpi_score = self._compute_cpi(predicted_miss_km, relative_velocity_kms, tca_minutes, p_collision)
            severity = classify_severity(predicted_miss_km)
            influence_weight = 1.0 / max(predicted_miss_km, 1.0)

            edge_ab = {
                "source_id": node_a.norad_id,
                "target_id": node_b.norad_id,
                "source_name": node_a.name,
                "target_name": node_b.name,
                "source_index": idx_a,
                "target_index": idx_b,
                "miss_distance_km": round(float(miss_distance_km), 3),
                "predicted_miss_distance_km": round(float(predicted_miss_km), 3),
                "relative_velocity_kmh": round(float(relative_velocity_kms * 3600.0), 2),
                "tca_minutes": round(float(tca_minutes), 2),
                "p_collision": round(float(p_collision), 4),
                "cpi_score": round(float(cpi_score), 2),
                "severity": severity,
                "influence_weight": round(float(influence_weight), 6),
            }
            edge_ba = {**edge_ab, "source_id": node_b.norad_id, "target_id": node_a.norad_id, "source_name": node_b.name, "target_name": node_a.name, "source_index": idx_b, "target_index": idx_a}

            edges.append(edge_ab)
            adjacency[node_a.norad_id].append(edge_ab)
            adjacency[node_b.norad_id].append(edge_ba)

        return {
            "nodes": nodes,
            "edges": edges,
            "adjacency": adjacency,
            "node_index": node_index,
            "positions": positions,
            "velocities": velocities,
            "summary": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "influence_radius_km": influence_radius_km,
            },
        }

    def analyze_snapshot(
        self,
        states: list[SatelliteState],
        alerts: list[dict[str, Any]] | None = None,
        influence_radius_km: float = DEFAULT_INFLUENCE_RADIUS_KM,
        cpi_threshold: float = DEFAULT_CPI_THRESHOLD,
        max_depth: int = 3,
        max_maneuvers: int = 50,
    ) -> dict[str, Any]:
        graph = self.build_graph(states, influence_radius_km=influence_radius_km)
        nodes: list[CascadeNode] = graph["nodes"]
        edges: list[dict[str, Any]] = graph["edges"]
        adjacency: dict[int, list[dict[str, Any]]] = graph["adjacency"]
        node_index: dict[int, int] = graph["node_index"]

        if not nodes:
            return {
                "graph": graph["summary"],
                "alerts": [],
                "cascade_plan": [],
                "total_delta_v_ms": 0.0,
                "cascade_depth": 0,
                "agencies_involved": [],
            }

        try:
            node_features, edge_index, edge_attr = self._build_gnn_inputs(nodes, edges, node_index, adjacency)
            gnn_output = self.gnn.predict(node_features, edge_index, edge_attr)
            maneuver_probability = gnn_output["maneuver_probability"]
            gnn_depth = gnn_output["cascade_depth"]
        except Exception as error:
            logger.warning("GNN cascade scoring failed, using fallback: %s", error)
            maneuver_probability = np.zeros(len(nodes), dtype=float)
            gnn_depth = np.zeros(len(nodes), dtype=int)

        ranked_nodes = sorted(
            nodes,
            key=lambda node: (
                maneuver_probability[node_index[node.norad_id]],
                self._node_peak_cpi(node.norad_id, adjacency),
            ),
            reverse=True,
        )

        if alerts:
            seed_ids = []
            for alert in sorted(alerts, key=lambda item: item.get("cpi_score", 0.0), reverse=True):
                seed_ids.append(alert["sat1"]["id"])
                seed_ids.append(alert["sat2"]["id"])
            seed_ids = list(dict.fromkeys(seed_ids))
        else:
            seed_ids = [node.norad_id for node in ranked_nodes[:3]]

        queue = deque((sat_id, 1, None, "PRIMARY_CONJUNCTION") for sat_id in seed_ids)
        visited: set[int] = set()
        resolved_maneuvers: list[dict[str, Any]] = []

        while queue and len(resolved_maneuvers) < max_maneuvers:
            sat_id, depth, trigger_sat_id, trigger_label = queue.popleft()
            if sat_id in visited or depth > max_depth:
                continue
            visited.add(sat_id)

            threat = self._strongest_threat(sat_id, adjacency)
            if threat is None:
                continue

            node = nodes[node_index[sat_id]]
            threat_node = nodes[node_index[threat["target_id"]]]
            node_prob = float(maneuver_probability[node_index[sat_id]])
            local_cpi = float(threat["cpi_score"])
            cascade_depth_score = int(max(depth, int(gnn_depth[node_index[sat_id]])))

            maneuver_rsw = self._recommend_maneuver_rsw(node, threat_node, local_cpi, node_prob)
            maneuver_eci = rsw_to_eci(maneuver_rsw, node.position, node.velocity)
            total_delta_v_ms = float(np.linalg.norm(maneuver_rsw))
            risk_before = local_cpi
            risk_after = max(0.0, risk_before - (node_prob * 3.0) - (total_delta_v_ms * 0.6))

            resolved_maneuvers.append(
                {
                    "satellite_id": sat_id,
                    "satellite_name": node.name,
                    "agency": node.agency,
                    "cascade_depth": cascade_depth_score,
                    "triggered_by": trigger_sat_id,
                    "trigger_label": trigger_label,
                    "threat": {
                        "satellite_id": threat["target_id"],
                        "satellite_name": threat["target_name"],
                        "miss_distance_km": threat["predicted_miss_distance_km"],
                        "relative_velocity_kmh": threat["relative_velocity_kmh"],
                        "tca_minutes": threat["tca_minutes"],
                        "p_collision": threat["p_collision"],
                        "cpi_score": threat["cpi_score"],
                    },
                    "maneuver": {
                        "frame": "RSW",
                        "dv_r": round(float(maneuver_rsw[0]), 3),
                        "dv_s": round(float(maneuver_rsw[1]), 3),
                        "dv_w": round(float(maneuver_rsw[2]), 3),
                        "delta_v_ms": round(total_delta_v_ms, 3),
                        "eci_ms": [
                            round(float(maneuver_eci[0]), 3),
                            round(float(maneuver_eci[1]), 3),
                            round(float(maneuver_eci[2]), 3),
                        ],
                    },
                    "risk_before": round(risk_before, 2),
                    "risk_after": round(risk_after, 2),
                    "maneuver_probability": round(node_prob, 3),
                }
            )

            for neighbor_edge in sorted(adjacency.get(sat_id, []), key=lambda item: item["cpi_score"], reverse=True):
                if neighbor_edge["target_id"] in visited:
                    continue
                if neighbor_edge["cpi_score"] >= cpi_threshold or maneuver_probability[node_index[neighbor_edge["target_id"]]] >= 0.55:
                    queue.append(
                        (
                            neighbor_edge["target_id"],
                            depth + 1,
                            sat_id,
                            f"CASCADE_FROM_{sat_id}",
                        )
                    )

        agencies_involved = sorted({maneuver["agency"] for maneuver in resolved_maneuvers})
        total_delta_v_ms = round(sum(maneuver["maneuver"]["delta_v_ms"] for maneuver in resolved_maneuvers), 3)
        max_cascade_depth = max([1] + [maneuver["cascade_depth"] for maneuver in resolved_maneuvers])

        return {
            "graph": graph["summary"],
            "alerts": self._serialize_alerts(edges),
            "cascade_plan": resolved_maneuvers,
            "seed_satellites": seed_ids,
            "total_delta_v_ms": total_delta_v_ms,
            "cascade_depth": max_cascade_depth,
            "agencies_involved": agencies_involved,
            "cpi_threshold": cpi_threshold,
            "node_probabilities": {
                str(node.norad_id): round(float(maneuver_probability[node_index[node.norad_id]]), 3)
                for node in nodes
            },
        }

    def _build_gnn_inputs(
        self,
        nodes: list[CascadeNode],
        edges: list[dict[str, Any]],
        node_index: dict[int, int],
        adjacency: dict[int, list[dict[str, Any]]],
    ):
        agency_ids = self._agency_id_map(nodes)
        node_features = []
        for node in nodes:
            node_peak_cpi = self._node_peak_cpi(node.norad_id, adjacency)
            node_features.append(
                [
                    node.position[0],
                    node.position[1],
                    node.position[2],
                    node.velocity[0],
                    node.velocity[1],
                    node.velocity[2],
                    node.speed_kmh,
                    node.altitude_km,
                    agency_ids[node.agency],
                    node_peak_cpi,
                ]
            )

        edge_index = []
        edge_attr = []
        for edge in edges:
            edge_index.append([node_index[edge["source_id"]], node_index[edge["target_id"]]])
            edge_attr.append([
                edge["predicted_miss_distance_km"],
                edge["relative_velocity_kmh"] / 3600.0,
                edge["tca_minutes"],
                edge["p_collision"],
            ])

        if not edge_index:
            edge_index = np.zeros((2, 0), dtype=int)
            edge_attr = np.zeros((0, 4), dtype=float)
        else:
            edge_index = np.array(edge_index, dtype=int).T
            edge_attr = np.array(edge_attr, dtype=float)

        return np.array(node_features, dtype=float), edge_index, edge_attr

    def _agency_id_map(self, nodes: list[CascadeNode]) -> dict[str, int]:
        agencies = sorted({node.agency for node in nodes})
        return {agency: idx + 1 for idx, agency in enumerate(agencies)}

    def _compute_cpi(self, miss_distance_km: float, relative_velocity_kms: float, tca_minutes: float, p_collision: float) -> float:
        miss_component = max(0.0, 10.0 - (miss_distance_km / 5.0))
        velocity_component = min(relative_velocity_kms / 1.5, 10.0)
        time_component = max(0.0, 10.0 - (tca_minutes / 2.4))
        probability_component = max(0.0, min(10.0, p_collision * 10.0))
        return (
            0.40 * probability_component
            + 0.25 * miss_component
            + 0.20 * velocity_component
            + 0.15 * time_component
        )

    def _strongest_threat(self, sat_id: int, adjacency: dict[int, list[dict[str, Any]]]) -> dict[str, Any] | None:
        threats = adjacency.get(sat_id, [])
        if not threats:
            return None
        return max(threats, key=lambda item: item["cpi_score"])

    def _node_peak_cpi(self, sat_id: int, adjacency: dict[int, list[dict[str, Any]]]) -> float:
        threats = adjacency.get(sat_id, [])
        if not threats:
            return 0.0
        return float(max(item["cpi_score"] for item in threats))

    def _recommend_maneuver_rsw(
        self,
        node: CascadeNode,
        threat: CascadeNode,
        local_cpi: float,
        maneuver_probability: float,
    ) -> np.ndarray:
        r_hat = node.position / max(_norm(node.position), 1e-6)
        h_vec = np.cross(node.position, node.velocity)
        h_norm = max(_norm(h_vec), 1e-6)
        w_hat = h_vec / h_norm
        s_hat = np.cross(w_hat, r_hat)

        relative = threat.position - node.position
        radial_sign = -1.0 if float(np.dot(relative, r_hat)) > 0 else 1.0
        along_sign = -1.0 if float(np.dot(relative, s_hat)) > 0 else 1.0
        cross_sign = -1.0 if float(np.dot(relative, w_hat)) > 0 else 1.0

        magnitude = max(0.05, min(2.5, 0.15 + (local_cpi / 10.0) * 1.4 + maneuver_probability * 0.7))
        return np.array([
            radial_sign * magnitude * 0.25,
            along_sign * magnitude * 0.85,
            cross_sign * magnitude * 0.15,
        ], dtype=float)

    def _serialize_alerts(self, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for item in sorted(edges, key=lambda edge: edge["cpi_score"], reverse=True):
            normalized.append(
                {
                    "sat1": {"id": item["source_id"], "name": item["source_name"]},
                    "sat2": {"id": item["target_id"], "name": item["target_name"]},
                    "miss_distance_km": item["predicted_miss_distance_km"],
                    "relative_speed_kmh": item["relative_velocity_kmh"],
                    "tca_utc": None,
                    "severity": item["severity"],
                    "cpi_score": item["cpi_score"],
                    "p_collision": item["p_collision"],
                    "influence_weight": item["influence_weight"],
                }
            )

        return normalized