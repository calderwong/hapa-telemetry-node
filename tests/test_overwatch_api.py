import importlib
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ow_root = tmp_path / "overwatch"
    _write(
        ow_root / "ecosystem" / "STATUS_BOARD.md",
        """# Status Board

| Service | Role | URL | Auth | Status | Runbook |
|---|---|---|---|---|---|
| Telemetry Node | Monitor | http://127.0.0.1:8730 | bearer | VERIFIED | nodes/MAC_HAPA_TELEMETRY_NODE.md |

| Project / node | Role | URL | Auth | Status | Runbook |
|---|---|---|---|---|---|
| LLaDA Node | Local LLM | http://127.0.0.1:8085 | bearer | UNVERIFIED | nodes/MAC_HAPA_LLADA_NODE.md |
""",
    )

    _write(
        ow_root / "ecosystem" / "TASK_INBOX.md",
        """# Task Inbox

## Active tasks

### OT-2026-01-01-0001 — Example task

- **Target agent:** ANY
- **Status:** OPEN
- **Requested by:** TEST
- **Timebox:** 10m
- **Goal:** Verify Overwatch API
- **Repo:** /tmp
- **Files:** n/a
- **Definition of done:** Tests pass
- **Validation:** pytest

## Completed tasks
""",
    )

    _write(
        ow_root / "CHECK_IN_2026-01-01_TEST.md",
        """# Check In — 2026-01-01 — TEST

## Tracking

- **Agent:** TEST
- **LLM Model:** none
- **Task:** smoke
- **Environment:** test
- **Location:** test
""",
    )

    _write(ow_root / "README.md", "# Overwatch\n")
    _write(ow_root / ".overMind", "# Mind\n")

    llada_root = tmp_path / "llada"
    llada_root.mkdir(parents=True, exist_ok=True)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "nodes": {
                    "llada-node": {
                        "node_type": "llada-node",
                        "display_name": "Test LLaDA",
                        "description": "",
                        "launch_config": {"command": "", "cwd": str(llada_root), "env": {}},
                        "default_port": 8085,
                        "auth_type": "bearer",
                        "capabilities": [],
                        "auto_start": False,
                        "requirements": {},
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HAPA_TELEMETRY_TOKEN", "testtoken")
    monkeypatch.setenv("HAPA_TELEMETRY_DB_PATH", str(tmp_path / "telemetry_test.db"))
    monkeypatch.setenv("HAPA_TELEMETRY_DISABLE_BG_TASKS", "1")
    monkeypatch.setenv("HAPA_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("HAPA_LAUNCHER_LOG_DIR", str(tmp_path / "launcher_logs"))
    monkeypatch.setenv("HAPA_OVERWATCH_ROOT", str(ow_root))

    monkeypatch.delenv("HAPA_LLADA_NODE_TOKEN", raising=False)
    monkeypatch.delenv("HAPA_LLADA_TOKEN", raising=False)
    monkeypatch.delenv("HAPA_LLADA_NODE_BASE_URL", raising=False)
    monkeypatch.delenv("HAPA_LLADA_BASE_URL", raising=False)
    monkeypatch.delenv("HAPA_LLADA_URL", raising=False)

    import hapa_telemetry_node.app as app_module

    importlib.reload(app_module)

    with TestClient(app_module.app) as c:
        yield c


def _headers() -> dict:
    return {"Authorization": "Bearer testtoken"}


def test_overwatch_summary_requires_auth(client: TestClient):
    resp = client.get("/v1/overwatch/summary")
    assert resp.status_code == 401


def test_overwatch_summary_ok(client: TestClient):
    resp = client.get("/v1/overwatch/summary", headers=_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["root_exists"] is True
    assert "docs" in data
    assert "tasks" in data
    assert data["tasks"]["total"] == 1


def test_overwatch_activity_ok(client: TestClient):
    resp = client.get("/v1/overwatch/activity", params={"limit": 10}, headers=_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) <= 10


def test_overwatch_protocol_scorecards_ok(client: TestClient):
    resp = client.get(
        "/v1/overwatch/protocol_scorecards", params={"max_files": 50}, headers=_headers()
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "counts" in data
    assert data["counts"]["total"] >= 4
    assert isinstance(data.get("items"), list)


def test_overwatch_chat_no_token_ok(client: TestClient):
    resp = client.post(
        "/v1/overwatch/chat",
        json={"prompt": "Status board"},
        headers=_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("answer") is None
    assert isinstance(data.get("citations"), list)
    llada = data.get("llada")
    assert isinstance(llada, dict)
    assert llada.get("used") is False
    assert "token" in str(llada.get("error") or "")
