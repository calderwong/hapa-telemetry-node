# CAMPFIRE — Hapa Telemetry Node

Campfire purpose: give future humans and agents a quick, grounded orientation before they touch this node.

## One-sentence role

Hapa Telemetry Node is the local observability and discovery lighthouse for the Hapa node ecosystem: it collects health/capability/telemetry signals, bridges Overwatch knowledge, and gives operators a dashboard plus CLI/API surface for shared situational awareness.

## Verified facts from this repository

- Python FastAPI app: `hapa_telemetry_node/app.py`
- CLI wrapper: `./hapa-telemetry`
- Makefile commands: `install`, `start`, `stop`, `status`, `test`, `discover`, `list`, `graph`, `clean`
- Default host/port: `127.0.0.1:8730`
- Public endpoints: `/`, `/health`, `/v1/telemetry/ping`
- Bearer-token auth for most `/v1/*` routes
- Token source: `HAPA_TELEMETRY_TOKEN`, `.node_token`, or generated `.node_token`
- SQLite telemetry state exists as `telemetry.db` in this checkout but should not be committed
- Tests: `tests/test_overwatch_api.py`
- Dashboard asset: `web/index.html`
- Overwatch bridge defaults to `${HAPA_SYSTEM_ROOT}/ops/overwatch/overwatch/SOURCE`
- Global wiki page: `${HAPA_SYSTEM_ROOT}/canon/wiki/hapa-worldbuilding-wiki/SOURCE/Nodes/Existing/hapa-telemetry-node.md`

## Inferred Hapa role

This node is a trust-and-understanding scaffold. It makes local services legible to each other and to the operator, reducing the pain of hidden state, stale assumptions, and repeated manual discovery.

Dao transition:

- Previous state: each node must be remembered, found, and verified manually.
- Current state: node registrations, health, capabilities, Overwatch docs, and relationship graph are queryable from one service.
- Future state: Hapa agents can negotiate work using a shared live map of services, status, runbooks, and provenance.

## Useful commands

```bash
make install
make start
make status
make test
make stop
.venv/bin/python -m pytest -q tests
```

Use `make test` only when a service is running. Use `pytest -q tests` for cheap app-level regression checks; running pytest over the whole repository currently also collects live-service helper functions in `hapa_telemetry_node/self_test.py`.

## Files not to commit

- `.venv/`
- `.node_token`
- `telemetry.db`
- `artifacts/hapa-telemetry-node/runtime/`
- generated self-test result JSON
- local `test_results.json`

## Bananas attribution

Contributors may opt into Bananas work-contribution tracking for attribution and recognition. Bananas is a provenance/credit layer; the project-level license remains MIT under Hapa.ai / Calder Wong.

## Open risks / care points

- Do not expose the service outside loopback without revisiting bearer-token handling and write endpoints.
- Do not overclaim runtime state in docs; use `make status`, `/health`, and tests for live evidence.
- Preserve third-party dependency licenses and generated notices.
- Large local state (`telemetry.db`) can grow quickly and belongs in runtime storage, not source control.
