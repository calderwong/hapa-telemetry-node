"""Self-test harness for telemetry node"""

import asyncio
import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

import httpx
try:
    from rich.console import Console
except Exception:
    class Console:
        def print(self, *args, **kwargs):
            print(*args)

from .artifact_paths import get_self_test_results_path

console = Console()


async def run_self_test() -> int:
    """Run comprehensive self-test"""
    console.print("[bold cyan]Hapa Telemetry Node Self-Test[/bold cyan]\n")
    
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "tests": [],
        "passed": 0,
        "failed": 0
    }
    
    # Test configuration
    host = os.environ.get("HAPA_TELEMETRY_HOST", "127.0.0.1")
    port = int(os.environ.get("HAPA_TELEMETRY_PORT", 8730))
    base_url = f"http://{host}:{port}"
    
    # Get token
    from .auth import TokenAuth
    auth = TokenAuth()
    token = auth.get_token()
    
    console.print(f"Base URL: {base_url}")
    console.print(f"Token: {token[:8]}...\n")
    
    # Test suite
    tests = [
        ("Health Check", test_health, (base_url,)),
        ("Authentication", test_auth, (base_url, token)),
        ("Capabilities", test_capabilities, (base_url, token)),
        ("Node Registration", test_registration, (base_url, token)),
        ("Node Discovery", test_discovery, (base_url, token)),
        ("Telemetry Collection", test_telemetry, (base_url, token)),
        ("Graph Generation", test_graph, (base_url, token)),
        ("Overwatch Bridge", test_overwatch_bridge, (base_url, token)),
        ("Dashboard UI", test_ui, (base_url,)),
    ]
    
    # Run tests
    for test_name, test_func, args in tests:
        console.print(f"Testing: {test_name}...", end=" ")
        try:
            start_time = time.time()
            await test_func(*args)
            duration = time.time() - start_time
            
            console.print(f"[green]✓ PASSED[/green] ({duration:.2f}s)")
            results["tests"].append({
                "name": test_name,
                "status": "passed",
                "duration": duration
            })
            results["passed"] += 1
        except Exception as e:
            msg = str(e)
            if not msg:
                msg = f"{type(e).__name__}: {repr(e)}"
            console.print(f"[red]✗ FAILED[/red] - {msg}")
            results["tests"].append({
                "name": test_name,
                "status": "failed",
                "error": msg
            })
            results["failed"] += 1
    
    # Summary
    console.print(f"\n[bold]Test Summary:[/bold]")
    console.print(f"  Passed: [green]{results['passed']}[/green]")
    console.print(f"  Failed: [red]{results['failed']}[/red]")
    console.print(f"  Total: {results['passed'] + results['failed']}")
    
    # Save results
    results_file = get_self_test_results_path()
    results_file.write_text(json.dumps(results, indent=2))
    console.print(f"\nResults saved to: {results_file}")
    
    # Return exit code
    return 0 if results["failed"] == 0 else 1


async def test_health(base_url: str):
    """Test health endpoint"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{base_url}/health")
        assert response.status_code == 200, f"Status code: {response.status_code}"
        data = response.json()
        assert "status" in data, "Missing status field"
        assert data["status"] == "healthy", f"Status: {data['status']}"


async def test_auth(base_url: str, token: str):
    """Test authentication"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Test without token
        response = await client.get(f"{base_url}/v1/capabilities")
        assert response.status_code == 401, "Should require auth"
        
        # Test with token
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(f"{base_url}/v1/capabilities", headers=headers)
        assert response.status_code == 200, f"Auth failed: {response.status_code}"


async def test_capabilities(base_url: str, token: str):
    """Test capabilities endpoint"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(f"{base_url}/v1/capabilities", headers=headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "service" in data
        assert "api_version" in data
        assert "discovery_methods" in data
        assert data["service"] == "telemetry-node"


async def test_registration(base_url: str, token: str):
    """Test node registration"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Register dummy node
        dummy_node = {
            "node_id": "test-node-001",
            "service_type": "api",
            "base_url": "http://127.0.0.1:9999",
            "display_name": "Test Node",
            "description": "Self-test dummy node"
        }
        
        response = await client.post(
            f"{base_url}/v1/discovery/register",
            json=dummy_node,
            headers=headers
        )
        assert response.status_code == 200
        
        # Verify registration
        response = await client.get(f"{base_url}/v1/nodes", headers=headers)
        assert response.status_code == 200
        nodes = response.json()
        
        found = any(n["node_id"] == "test-node-001" for n in nodes)
        assert found, "Dummy node not found after registration"


async def test_discovery(base_url: str, token: str):
    """Test discovery scanning"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Trigger scan
        response = await client.post(
            f"{base_url}/v1/discovery/scan",
            headers=headers
        )
        assert response.status_code == 200
        
        result = response.json()
        assert "status" in result
        assert "discovered" in result
        assert result["status"] == "completed"


async def test_telemetry(base_url: str, token: str):
    """Test telemetry collection"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Get self telemetry
        response = await client.get(f"{base_url}/v1/telemetry", headers=headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "metrics" in data or "relationships" in data
        
        # Get telemetry for a specific node (self)
        response = await client.get(
            f"{base_url}/v1/telemetry/telemetry-node",
            headers=headers
        )
        # May be 404 if no telemetry collected yet
        assert response.status_code in [200, 404]


async def test_graph(base_url: str, token: str):
    """Test graph generation"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        headers = {"Authorization": f"Bearer {token}"}
        
        response = await client.get(f"{base_url}/v1/graph", headers=headers)
        assert response.status_code == 200
        
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)


async def test_ui(base_url: str):
    """Test dashboard UI availability"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(base_url)
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "Hapa Telemetry" in response.text


async def test_overwatch_bridge(base_url: str, token: str):
    """Test Overwatch bridge endpoints"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get(f"{base_url}/v1/overwatch/health", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "root" in data
        assert "docs" in data
        root_ok = bool(data.get("ok"))

        response = await client.get(f"{base_url}/v1/overwatch/status_board", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "doc" in data
        assert "tables" in data

        response = await client.get(f"{base_url}/v1/overwatch/task_inbox", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "doc" in data
        assert "tasks" in data

        response = await client.get(f"{base_url}/v1/overwatch/test_cards", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "deck" in data
        assert "items" in data

        response = await client.get(f"{base_url}/v1/overwatch/check_ins?limit=5", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        response = await client.get(
            f"{base_url}/v1/overwatch/search",
            params={"q": "telemetry", "max_results": 5},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "results" in data

        response = await client.get(f"{base_url}/v1/overwatch/summary", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "root" in data
        assert "docs" in data
        assert "tasks" in data

        response = await client.get(f"{base_url}/v1/overwatch/activity", params={"limit": 5}, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data

        response = await client.get(
            f"{base_url}/v1/overwatch/protocol_scorecards",
            params={"max_files": 25},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "counts" in data
        assert "items" in data

        response = await client.post(
            f"{base_url}/v1/overwatch/chat",
            json={"prompt": "Status board", "max_tokens": 64, "temperature": 0.2},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "citations" in data
        assert "llada" in data

        # Filesystem browse endpoints
        response = await client.get(
            f"{base_url}/v1/overwatch/fs/read",
            params={"rel_path": "README.md", "include_content": "false", "max_bytes": 5000},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("rel_path") == "README.md"
        assert "path" in data

        response = await client.get(
            f"{base_url}/v1/overwatch/fs/ls",
            params={"rel_path": "", "max_entries": 50},
            headers=headers,
        )
        if root_ok:
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data.get("items"), list)
        else:
            assert response.status_code == 404

        # Path traversal / escaping must be rejected
        response = await client.get(
            f"{base_url}/v1/overwatch/fs/read",
            params={"rel_path": "../.ssh/id_rsa", "include_content": "false"},
            headers=headers,
        )
        assert response.status_code == 400

        response = await client.get(
            f"{base_url}/v1/overwatch/fs/ls",
            params={"rel_path": "..", "max_entries": 10},
            headers=headers,
        )
        assert response.status_code == 400

        # Full tree search (bounded)
        response = await client.get(
            f"{base_url}/v1/overwatch/search_tree",
            params={"q": "telemetry", "max_results": 5, "max_files": 200, "rel_path": ""},
            headers=headers,
        )
        if root_ok:
            assert response.status_code == 200
            data = response.json()
            assert "query" in data
            assert "results" in data
            assert isinstance(data.get("results"), list)
        else:
            assert response.status_code == 404

        response = await client.get(
            f"{base_url}/v1/overwatch/search_tree",
            params={"q": "telemetry", "max_results": 5, "max_files": 50, "rel_path": ".."},
            headers=headers,
        )
        assert response.status_code == 400


if __name__ == "__main__":
    sys.exit(asyncio.run(run_self_test()))
