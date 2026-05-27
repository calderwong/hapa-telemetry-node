import importlib
from pathlib import Path

from starlette.testclient import TestClient

from hapa_telemetry_node.models import HealthStatus, NodeHealth, NodeInfo, NodeStatus, NodeTelemetry, ServiceType


def test_build_janus_snapshot_marks_online_node_ok():
    from hapa_telemetry_node.janus_bridge import build_janus_snapshot

    node = NodeInfo(
        node_id="llada-node",
        service_type=ServiceType.LLM,
        base_url="http://127.0.0.1:8085",
        display_name="LLaDA Node",
        auth_required=True,
        metadata={"role": "local llm"},
    )
    telemetry = NodeTelemetry(
        node_id="llada-node",
        status=NodeStatus.ONLINE,
        health=NodeHealth(status=HealthStatus.HEALTHY, message="ready"),
    )

    snapshot = build_janus_snapshot(node, telemetry)

    assert snapshot["node_id"] == "llada-node"
    assert snapshot["base_url"] == "http://127.0.0.1:8085"
    assert snapshot["ok"] is True
    assert snapshot["health"]["status"] == "healthy"
    assert snapshot["capabilities"]["service_type"] == "llm"
    assert snapshot["metadata"]["display_name"] == "LLaDA Node"


def test_build_janus_snapshot_marks_missing_telemetry_unknown_not_ok():
    from hapa_telemetry_node.janus_bridge import build_janus_snapshot

    node = NodeInfo(
        node_id="unknown-node",
        service_type=ServiceType.UNKNOWN,
        base_url="http://127.0.0.1:8999",
        auth_required=False,
    )

    snapshot = build_janus_snapshot(node, None)

    assert snapshot["node_id"] == "unknown-node"
    assert snapshot["ok"] is False
    assert snapshot["health"]["status"] == "unknown"
    assert "No telemetry" in snapshot["error"]


def test_janus_push_endpoint_calls_bridge(tmp_path: Path, monkeypatch):
    ow_root = tmp_path / "overwatch"
    (ow_root / "ecosystem").mkdir(parents=True)
    (ow_root / "ecosystem" / "STATUS_BOARD.md").write_text("# Status\n", encoding="utf-8")
    (ow_root / "ecosystem" / "TASK_INBOX.md").write_text("# Tasks\n", encoding="utf-8")
    (ow_root / "README.md").write_text("# Overwatch\n", encoding="utf-8")
    (ow_root / ".overMind").write_text("# Mind\n", encoding="utf-8")

    monkeypatch.setenv("HAPA_TELEMETRY_TOKEN", "testtoken")
    monkeypatch.setenv("HAPA_TELEMETRY_DB_PATH", str(tmp_path / "telemetry_test.db"))
    monkeypatch.setenv("HAPA_TELEMETRY_DISABLE_BG_TASKS", "1")
    monkeypatch.setenv("HAPA_OVERWATCH_ROOT", str(ow_root))

    import hapa_telemetry_node.app as app_module

    importlib.reload(app_module)
    called = {}

    async def fake_push_snapshots_once(*, db, janus_base_url, janus_token, timeout=5.0):
        called["janus_base_url"] = janus_base_url
        called["janus_token"] = janus_token
        called["timeout"] = timeout
        return {
            "ok": True,
            "janus_base_url": janus_base_url,
            "attempted": 1,
            "succeeded": 1,
            "failed": 0,
            "results": [{"node_id": "telemetry-node", "ok": True}],
        }

    monkeypatch.setattr(app_module.janus_bridge, "push_snapshots_once", fake_push_snapshots_once)

    with TestClient(app_module.app) as client:
        resp = client.post(
            "/v1/bridges/janus/push",
            json={"janus_base_url": "http://127.0.0.1:8741", "janus_token": "janus-token"},
            headers={"Authorization": "Bearer testtoken"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["succeeded"] == 1
    assert called == {
        "janus_base_url": "http://127.0.0.1:8741",
        "janus_token": "janus-token",
        "timeout": 5.0,
    }
