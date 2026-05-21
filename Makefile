.PHONY: help start stop status test install clean discover list graph

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

clean:
	rm -f .node_token
	rm -rf __pycache__ hapa_telemetry_node/__pycache__
	rm -f artifacts/hapa-telemetry-node/runtime/telemetry_runtime.json
