import importlib
import json
from pathlib import Path

from click.testing import CliRunner
from starlette.testclient import TestClient


WEB_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"
MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"
README = Path(__file__).resolve().parents[1] / "README.md"
FEATURE_PARITY = Path(__file__).resolve().parents[1] / "docs" / "FEATURE_PARITY.md"
AGENTS = Path(__file__).resolve().parents[1] / "AGENTS.md"

from hapa_telemetry_node.models import HealthStatus, NodeHealth, NodeInfo, NodeStatus, NodeTelemetry, ServiceType


def test_janus_bridge_protocol_surfaces_are_documented():
    readme = README.read_text(encoding="utf-8")
    parity = FEATURE_PARITY.read_text(encoding="utf-8")
    agents = AGENTS.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert "Hapa Telemetry Node" in agents
    assert "API" in agents and "CLI" in agents and "UI" in agents
    assert "POST /v1/bridges/janus/push" in readme
    assert "Janus Snapshot Bridge panel" in readme
    assert "janus-push" in readme
    assert "Janus snapshot bridge" in parity
    assert "API+CLI+UI verified" in parity
    assert "janus-push:" in makefile


def test_janus_push_cli_posts_to_bridge(monkeypatch):
    import hapa_telemetry_node.cli as cli_module

    calls = {}

    class FakeResponse:
        status_code = 200
        text = json.dumps({"ok": True})

        def json(self):
            return {"ok": True, "attempted": 2, "succeeded": 2, "failed": 0, "results": []}

    def fake_post(url, *, json=None, headers=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        calls["headers"] = headers
        calls["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("HAPA_TELEMETRY_TOKEN", "telemetry-token")
    monkeypatch.setenv("HAPA_TELEMETRY_HOST", "127.0.0.1")
    monkeypatch.setenv("HAPA_TELEMETRY_PORT", "8730")
    monkeypatch.setattr(cli_module.httpx, "post", fake_post)

    result = CliRunner().invoke(
        cli_module.cli,
        [
            "janus-push",
            "--janus-url",
            "http://127.0.0.1:8741",
            "--janus-token",
            "janus-token",
        ],
    )

    assert result.exit_code == 0
    assert "attempted=2" in result.output
    assert calls == {
        "url": "http://127.0.0.1:8730/v1/bridges/janus/push",
        "json": {"janus_base_url": "http://127.0.0.1:8741", "janus_token": "janus-token", "timeout": 5.0},
        "headers": {"Authorization": "Bearer telemetry-token"},
        "timeout": 10.0,
    }


def test_dashboard_exposes_janus_push_controls():
    html = WEB_INDEX.read_text(encoding="utf-8")

    assert "id=\"janus-bridge-panel\"" in html
    assert "id=\"janus-base-url\"" in html
    assert "id=\"janus-token\"" in html
    assert "id=\"janus-push-status\"" in html
    assert "pushJanusSnapshots" in html
    assert "POST /v1/bridges/janus/push" in html
    assert "fetch('/v1/bridges/janus/push'" in html


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
