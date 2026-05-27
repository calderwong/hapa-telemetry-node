# AGENTS.md — Hapa Telemetry Node

## Node identity

Hapa Telemetry Node is the local-first observability, discovery, registry, launcher, Overwatch bridge, and Janus snapshot bridge service for the Hapa.ai node ecosystem.

Default local service URL: `http://127.0.0.1:8730`.

## Protocol standard

Keep API, CLI, UI, tests, and docs in parity for every operator-facing capability.

For a new or changed capability, update these surfaces together unless an exception is explicitly documented:

- API: FastAPI route in `hapa_telemetry_node/app.py`.
- CLI: Click command in `hapa_telemetry_node/cli.py` and Makefile target when useful.
- UI: dashboard surface in `web/index.html` when operator-facing.
- Tests: app/contract tests under `tests/`.
- Docs: `README.md` and `docs/FEATURE_PARITY.md`.

## Current Janus bridge contract

Telemetry can push node snapshots into Janus World Node as context, not canonical truth.

Surfaces:

- API: `POST /v1/bridges/janus/push`.
- CLI: `python -m hapa_telemetry_node janus-push --janus-url http://127.0.0.1:8741 --janus-token ...`.
- Make: `HAPA_JANUS_WORLD_NODE_TOKEN=... make janus-push`.
- UI: dashboard `Janus Snapshot Bridge` panel.
- Background loop: opt-in only with `HAPA_TELEMETRY_JANUS_BRIDGE_ENABLED=1`.

Required auth:

- Telemetry bearer token for the Telemetry API/CLI call.
- Janus bearer token for the receiving Janus node.

Do not persist Janus bearer tokens in the browser. Localhost dashboard persistence may remember only non-secret values like the Janus base URL.

## Verification commands

Use these before claiming protocol parity:

```bash
.venv/bin/python -m pytest -q tests
.venv/bin/python -m py_compile hapa_telemetry_node/app.py hapa_telemetry_node/cli.py hapa_telemetry_node/janus_bridge.py tests/test_janus_bridge.py
.venv/bin/python -m hapa_telemetry_node janus-push --help
```

For live bridge verification, run Janus and Telemetry locally with test tokens, invoke `janus-push`, and verify Janus state contains `node_snapshots.telemetry-node` plus a `node.snapshot.updated` event.

## Safety rules

- Keep local-first loopback defaults unless the operator explicitly opts into wider exposure.
- Treat `.node_token`, SQLite databases, runtime artifacts, logs, generated media, dependency folders, and local secrets as runtime artifacts.
- Do not make cross-node writes automatic by default.
- Label health/capability data as telemetry/context; Janus event tape remains the truth plane.
