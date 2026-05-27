.PHONY: help start stop status test install clean discover list graph janus-push

help:
	@echo "Hapa Telemetry Node - Makefile Commands"
	@echo "======================================="
	@echo "  make install   - Install dependencies"
	@echo "  make start     - Start telemetry node"
	@echo "  make stop      - Stop telemetry node"
	@echo "  make status    - Show node status"
	@echo "  make test      - Run self-test"
	@echo "  make discover  - Scan for nodes"
	@echo "  make list      - List discovered nodes"
	@echo "  make graph     - Show node relationships"
	@echo "  make janus-push - Push snapshots to Janus (requires JANUS_TOKEN or HAPA_JANUS_WORLD_NODE_TOKEN)"
	@echo "  make clean     - Clean up generated files"

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

start:
	.venv/bin/python -m hapa_telemetry_node start --daemon

stop:
	.venv/bin/python -m hapa_telemetry_node stop

status:
	.venv/bin/python -m hapa_telemetry_node status

test:
	.venv/bin/python -m hapa_telemetry_node test

discover:
	.venv/bin/python -m hapa_telemetry_node discover

list:
	.venv/bin/python -m hapa_telemetry_node list

graph:
	.venv/bin/python -m hapa_telemetry_node graph

janus-push:
	.venv/bin/python -m hapa_telemetry_node janus-push --janus-url "$${JANUS_URL:-http://127.0.0.1:8741}" --janus-token "$${JANUS_TOKEN:-$${HAPA_JANUS_WORLD_NODE_TOKEN:-$${HAPA_JANUS_TOKEN}}}"

clean:
	rm -f .node_token
	rm -rf __pycache__ hapa_telemetry_node/__pycache__
	rm -f artifacts/hapa-telemetry-node/runtime/telemetry_runtime.json
