"""Bridge telemetry snapshots into Hapa Janus World Node.

This module is intentionally opt-in. It never starts network writes unless the
app lifespan is configured with the Janus bridge env vars or a caller invokes
the one-shot push endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

from .database import Database
from .models import HealthStatus, NodeInfo, NodeStatus, NodeTelemetry

logger = logging.getLogger(__name__)


def _model_dump(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}


def build_janus_snapshot(node: NodeInfo, telemetry: Optional[NodeTelemetry]) -> Dict[str, Any]:
    """Build a Janus-compatible node snapshot from Telemetry state."""
    health = _model_dump(telemetry.health if telemetry else None)
    capabilities = _model_dump(telemetry.capabilities if telemetry else None)
    node_service_type = node.service_type.value if hasattr(node.service_type, "value") else str(node.service_type)
    if not capabilities or capabilities.get("service_type") in {None, "unknown"}:
        capabilities = {**capabilities, "service_type": node_service_type}
    metrics = _model_dump(telemetry.metrics if telemetry else None)
    relationships = _model_dump(telemetry.relationships if telemetry else None)

    health_status = None
    if telemetry and telemetry.health and telemetry.health.status:
        health_status = telemetry.health.status.value if hasattr(telemetry.health.status, "value") else str(telemetry.health.status)

    status = telemetry.status if telemetry else NodeStatus.UNKNOWN
    ok = bool(status == NodeStatus.ONLINE and health_status == HealthStatus.HEALTHY.value)

    error = None
    if telemetry is None:
        error = "No telemetry has been collected for this node yet"
    elif not ok:
        error = f"Telemetry status={status.value if hasattr(status, 'value') else status}, health={health_status or 'unknown'}"

    return {
        "node_id": node.node_id,
        "base_url": node.base_url,
        "ok": ok,
        "health": health or {"status": "unknown"},
        "capabilities": capabilities,
        "error": error,
        "metadata": {
            "display_name": node.display_name,
            "description": node.description,
            "service_type": node.service_type.value if hasattr(node.service_type, "value") else str(node.service_type),
            "auth_required": node.auth_required,
            "last_seen": node.last_seen.isoformat() if node.last_seen else None,
            "node_metadata": node.metadata,
        },
        "telemetry": {
            "timestamp": telemetry.timestamp.isoformat() if telemetry and telemetry.timestamp else None,
            "status": status.value if hasattr(status, "value") else str(status),
            "metrics": metrics,
            "relationships": relationships,
        },
    }


async def push_snapshots_once(
    *,
    db: Database,
    janus_base_url: str,
    janus_token: str,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Push one snapshot per registered Telemetry node into Janus."""
    base_url = str(janus_base_url or "").rstrip("/")
    if not base_url:
        raise ValueError("janus_base_url is required")
    if not janus_token:
        raise ValueError("janus_token is required")

    nodes = await db.list_nodes()
    headers = {
        "Authorization": f"Bearer {janus_token}",
        "X-Hapa-Actor": "hapa-telemetry-node",
    }
    results = []

    async with httpx.AsyncClient(timeout=timeout) as client:
        for node in nodes:
            telemetry = await db.get_latest_telemetry(node.node_id)
            snapshot = build_janus_snapshot(node, telemetry)
            try:
                resp = await client.post(
                    f"{base_url}/v1/world/node-snapshots",
                    json=snapshot,
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results.append({
                        "node_id": node.node_id,
                        "ok": True,
                        "status_code": resp.status_code,
                        "janus": data,
                    })
                else:
                    results.append({
                        "node_id": node.node_id,
                        "ok": False,
                        "status_code": resp.status_code,
                        "error": resp.text[:1000],
                    })
            except Exception as e:
                results.append({"node_id": node.node_id, "ok": False, "error": str(e)})

    succeeded = sum(1 for r in results if r.get("ok") is True)
    failed = len(results) - succeeded
    return {
        "ok": failed == 0,
        "janus_base_url": base_url,
        "attempted": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


async def janus_bridge_loop(
    *,
    db: Database,
    janus_base_url: str,
    janus_token: str,
    interval: int = 30,
    timeout: float = 5.0,
) -> None:
    """Periodically push snapshots to Janus until cancelled."""
    logger.info("Starting Janus bridge loop (interval: %ss, target: %s)", interval, janus_base_url)
    while True:
        try:
            result = await push_snapshots_once(
                db=db,
                janus_base_url=janus_base_url,
                janus_token=janus_token,
                timeout=timeout,
            )
            logger.info(
                "Janus bridge push attempted=%s succeeded=%s failed=%s",
                result.get("attempted"),
                result.get("succeeded"),
                result.get("failed"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Janus bridge push failed: %s", e)
        await asyncio.sleep(interval)
