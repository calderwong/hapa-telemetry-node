# Feature Parity — Hapa Telemetry Node

Status: partial verified
Updated: 2026-05-26

This matrix records how core Hapa Telemetry Node capabilities are exposed across API, CLI, and UI. Runtime status still requires live smoke tests; pytest verifies app-level API behavior without requiring a daemon.

| Capability | API | CLI | UI | Data source | Auth | Verification | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Health check | `GET /health` | `make status` / wrapper status paths | Dashboard status surface | FastAPI app + SQLite node count | public | `.venv/bin/python -m pytest -q tests` | verified by tests |
| Capabilities | `GET /v1/capabilities` | `./hapa-telemetry --help` / self-test | Dashboard/API consumers | app metadata + db counts | bearer | `.venv/bin/python -m pytest -q tests` | verified by tests |
| Node discovery/register | `POST /v1/discovery/register`, `POST /v1/discovery/scan` | `make discover`, `make list` | Dashboard | SQLite + discovery engine | bearer | live smoke required for network discovery | partial |
| Telemetry collection | `/v1/telemetry*`, collector polling | `make test` self-test | Dashboard graph/status | SQLite telemetry table | bearer | live daemon/self-test | partial |
| Overwatch read/search bridge | `/v1/overwatch/*` read/search endpoints | n/a | Dashboard/API consumers | `.Overwatch` Markdown/JSON files | bearer | `tests/test_overwatch_api.py` | verified by tests |
| Overwatch guarded writes | `/v1/overwatch/write/*` | n/a | Dashboard/API consumers | `.Overwatch` task/check-in/artifact files | bearer | app tests + manual review before real writes | partial |
| Registry/launcher | `/v1/registry/*`, `/v1/launcher/*` | wrapper/Make targets | Dashboard/API consumers | registry JSON + launcher logs | bearer | live smoke required | partial |
| Janus snapshot bridge | `POST /v1/bridges/janus/push`; optional background loop via `HAPA_TELEMETRY_JANUS_BRIDGE_ENABLED` | `hapa_telemetry_node janus-push`, `make janus-push` | Dashboard panel: Janus base URL + token + Push to Janus status | Telemetry `nodes` + latest telemetry, Janus `/v1/world/node-snapshots` | Telemetry bearer + Janus bearer | `tests/test_janus_bridge.py`; browser smoke at `127.0.0.1:18730` | API+CLI+UI verified |

## Janus bridge notes

The Janus bridge is intentionally opt-in. It does not write to Janus unless either:

1. An authenticated caller invokes `POST /v1/bridges/janus/push`, or
2. The daemon starts with `HAPA_TELEMETRY_JANUS_BRIDGE_ENABLED=1` and a Janus token in `HAPA_JANUS_WORLD_NODE_TOKEN` or `HAPA_JANUS_TOKEN`.

Snapshots are context, not world truth. Janus records them as `node.snapshot.updated` events while preserving the append-only event tape as the truth plane.
