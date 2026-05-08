"""
In-memory snapshot cache for the latest propagated satellite state.
"""

from typing import Any

_latest_snapshot: dict[str, Any] = {
    "type": "update",
    "timestamp": None,
    "satellites": [],
    "count": 0,
    "states": [],
    "payload": None,
}

_latest_alerts: dict[str, Any] = {
    "timestamp": None,
    "alerts": [],
    "count": 0,
}


def set_latest_snapshot(snapshot: dict[str, Any]):
    global _latest_snapshot
    _latest_snapshot = snapshot


def get_latest_snapshot() -> dict[str, Any]:
    return _latest_snapshot


def set_latest_alerts(alerts_snapshot: dict[str, Any]):
    global _latest_alerts
    _latest_alerts = alerts_snapshot


def get_latest_alerts() -> dict[str, Any]:
    return _latest_alerts