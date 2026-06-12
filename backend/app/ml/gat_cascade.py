from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from .artifacts import artifact_path, load_artifact, save_artifact
from .gnn_cascade import CascadeGNN
from .synthetic_data import build_graph_summary_features, generate_graph_snapshots, sigmoid

logger = logging.getLogger(__name__)

GAT_META = "gat_model.json"
GAT_WEIGHTS = "gat_model.pt"

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader
    from torch_geometric.data import Data
    from torch_geometric.nn import GATConv
    TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    torch = None
    nn = None
    Data = None
    DataLoader = None
    GATConv = None
    TORCH_AVAILABLE = False


@dataclass
class GATArtifact:
    input_mean: np.ndarray
    input_std: np.ndarray
    hidden_dim: int
    heads: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_mean": self.input_mean.tolist(),
            "input_std": self.input_std.tolist(),
            "hidden_dim": int(self.hidden_dim),
            "heads": int(self.heads),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GATArtifact":
        return cls(
            input_mean=np.asarray(payload["input_mean"], dtype=float),
            input_std=np.asarray(payload["input_std"], dtype=float),
            hidden_dim=int(payload["hidden_dim"]),
            heads=int(payload["heads"]),
        )


if TORCH_AVAILABLE:
    class GATNet(nn.Module):
        def __init__(self, input_dim: int, hidden_dim: int, heads: int):
            super().__init__()
            self.gat1 = GATConv(input_dim, hidden_dim, heads=heads, concat=True)
            self.gat2 = GATConv(hidden_dim * heads, hidden_dim, heads=1, concat=False)
            self.out = nn.Linear(hidden_dim, 1)

        def forward(self, data: Data) -> torch.Tensor:
            x, edge_index = data.x, data.edge_index
            x = self.gat1(x, edge_index)
            x = torch.relu(x)
            x = self.gat2(x, edge_index)
            x = torch.relu(x)
            logits = self.out(x).squeeze(-1)
            return logits


def _build_dataset(graphs: list[dict[str, np.ndarray]]) -> tuple[list[Any], np.ndarray, np.ndarray]:
    all_features = np.vstack([graph["node_features"] for graph in graphs])
    input_mean = all_features.mean(axis=0)
    input_std = all_features.std(axis=0) + 1e-6

    dataset = []
    for graph in graphs:
        x = (graph["node_features"] - input_mean) / input_std
        edge_index = graph["edge_index"]
        if edge_index.size == 0:
            edge_index = np.zeros((2, 0), dtype=np.int64)
        y = graph["targets"]
        dataset.append({"x": x.astype(np.float32), "edge_index": edge_index.astype(np.int64), "y": y.astype(np.float32)})

    return dataset, input_mean, input_std


def train_gat_model(
    sample_count: int = 256,
    hidden_dim: int = 32,
    heads: int = 4,
    epochs: int = 30,
    learning_rate: float = 0.001,
    seed: int = 17,
) -> GATArtifact:
    if not TORCH_AVAILABLE:
        raise RuntimeError("PyTorch + torch_geometric are required for GAT training")

    torch.manual_seed(seed)

    graphs = generate_graph_snapshots(sample_count=sample_count, seed=seed)
    dataset, input_mean, input_std = _build_dataset(graphs)

    data_list = []
    for item in dataset:
        data_list.append(
            Data(
                x=torch.tensor(item["x"], dtype=torch.float32),
                edge_index=torch.tensor(item["edge_index"], dtype=torch.long),
                y=torch.tensor(item["y"], dtype=torch.float32),
            )
        )

    loader = DataLoader(data_list, batch_size=8, shuffle=True)

    model = GATNet(input_dim=input_mean.shape[0], hidden_dim=hidden_dim, heads=heads)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()

    model.train()
    for _ in range(epochs):
        for batch in loader:
            optimizer.zero_grad()
            logits = model(batch)
            loss = loss_fn(logits, batch.y)
            loss.backward()
            optimizer.step()

    weights_path = artifact_path(GAT_WEIGHTS)
    torch.save(model.state_dict(), weights_path)

    artifact = GATArtifact(
        input_mean=input_mean.astype(float),
        input_std=input_std.astype(float),
        hidden_dim=hidden_dim,
        heads=heads,
    )
    save_artifact(
        GAT_META,
        {
            "trained_from": "synthetic_graph_snapshots",
            "sample_count": sample_count,
            "epochs": epochs,
            "model": artifact.to_dict(),
        },
    )
    logger.info("Trained GAT cascade model with hidden dim %d", hidden_dim)
    return artifact


def load_gat_artifact() -> tuple[GATArtifact | None, Any | None]:
    if not TORCH_AVAILABLE:
        return None, None

    payload = load_artifact(GAT_META)
    if not payload or "model" not in payload:
        return None, None

    artifact = GATArtifact.from_dict(payload["model"])
    weights_path = artifact_path(GAT_WEIGHTS)
    if not weights_path.exists():
        return None, None

    model = GATNet(input_dim=artifact.input_mean.shape[0], hidden_dim=artifact.hidden_dim, heads=artifact.heads)
    model.load_state_dict(torch.load(weights_path, map_location="cpu"))
    model.eval()
    return artifact, model


class CascadeGAT:
    """Graph attention model with deterministic fallback to the compact GNN."""

    def __init__(self):
        self._fallback = CascadeGNN()
        self.artifact: GATArtifact | None = None
        self.model = None
        self._load_model()

    def _load_model(self):
        try:
            self.artifact, self.model = load_gat_artifact()
        except Exception as error:
            logger.warning("GAT model load failed, using fallback: %s", error)
            self.artifact, self.model = None, None

    def predict(self, node_features, edge_index, edge_attr):
        node_features = np.asarray(node_features, dtype=float)
        edge_index = np.asarray(edge_index, dtype=int)
        edge_attr = np.asarray(edge_attr, dtype=float)

        if self.model is None or self.artifact is None or not TORCH_AVAILABLE:
            return self._fallback.predict(node_features, edge_index, edge_attr)

        x = (node_features - self.artifact.input_mean) / self.artifact.input_std
        edge_index_t = torch.tensor(edge_index, dtype=torch.long)
        data = Data(x=torch.tensor(x, dtype=torch.float32), edge_index=edge_index_t)

        with torch.no_grad():
            logits = self.model(data)
            maneuver_probability = torch.sigmoid(logits).cpu().numpy().astype(float).reshape(-1)

        summary_features = build_graph_summary_features(node_features, edge_index, edge_attr)
        influence = summary_features[:, 9]
        local_risk = summary_features[:, 4]
        speed_bias = np.clip(summary_features[:, 1], 0.0, 1.0)

        cascade_depth = np.clip(np.ceil(maneuver_probability * 4.0 + influence * 1.5), 0.0, 4.0).astype(int)

        delta_v = np.zeros((summary_features.shape[0], 3), dtype=float)
        delta_v[:, 1] = np.clip(
            0.05 + maneuver_probability * 1.35 + local_risk / 12.0 + speed_bias * 0.2,
            0.05,
            5.0,
        )
        delta_v[:, 0] = np.clip((local_risk - 0.5) * 0.25, -1.0, 1.0)
        delta_v[:, 2] = np.clip((influence - 0.35) * 0.22, -1.0, 1.0)

        return {
            "maneuver_probability": maneuver_probability,
            "delta_v_rsw_ms": delta_v,
            "cascade_depth": cascade_depth,
            "graph_influence": influence,
        }
