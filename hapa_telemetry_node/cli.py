"""CLI for telemetry node"""

import os
import sys
import json
import asyncio
import subprocess
import signal
import time
from pathlib import Path
from typing import Optional, Dict, Any
import logging

import click
import httpx
try:
    from rich.console import Console
    from rich.table import Table
    from rich.tree import Tree
    from rich import print as rprint
except Exception:
    def rprint(*args, **kwargs):
        print(*args)

    class Console:
        def print(self, *args, **kwargs):
            print(*args)

    class Table:
        def __init__(self, title: str = ""):
            self.title = title
            self.columns = []
            self.rows = []

        def add_column(self, name, **kwargs):
            self.columns.append(str(name))

        def add_row(self, *values):
            self.rows.append([str(v) for v in values])

        def __str__(self) -> str:
            lines = []
            if self.title:
                lines.append(str(self.title))
            if self.columns:
                lines.append("\t".join(self.columns))
            for row in self.rows:
                lines.append("\t".join(row))
            return "\n".join(lines)

    class Tree:
        def __init__(self, label: str):
            self.label = label
            self.children = []

        def add(self, label: str):
            child = Tree(label)
            self.children.append(child)
            return child

        def __str__(self) -> str:
            lines = [str(self.label)]

            def walk(node, prefix: str):
                for idx, child in enumerate(node.children):
                    last = idx == len(node.children) - 1
                    branch = "└─ " if last else "├─ "
                    lines.append(prefix + branch + str(child.label))
                    walk(child, prefix + ("   " if last else "│  "))

            walk(self, "")
            return "\n".join(lines)

from .auth import TokenAuth
from .artifact_paths import get_runtime_file as _get_runtime_file

console = Console()
logger = logging.getLogger(__name__)

LEGACY_RUNTIME_FILE = Path.home() / ".hapa_telemetry_runtime.json"


def get_base_url():
    """Get base URL for telemetry node"""
    host = os.environ.get("HAPA_TELEMETRY_HOST", "127.0.0.1")
    port = os.environ.get("HAPA_TELEMETRY_PORT", "8730")
    return f"http://{host}:{port}"


def get_token():
    """Get authentication token"""
    auth = TokenAuth()
    return auth.get_token()


def get_runtime_file():
    """Get runtime file path"""
    return _get_runtime_file()


def save_runtime(pid: int, port: int):
    """Save runtime information"""
    runtime = {
        "pid": pid,
        "port": port,
        "base_url": f"http://127.0.0.1:{port}",
        "started_at": time.time()
    }
    get_runtime_file().write_text(json.dumps(runtime, indent=2))


def load_runtime() -> Optional[Dict[str, Any]]:
    """Load runtime information"""
    for runtime_file in [get_runtime_file(), LEGACY_RUNTIME_FILE]:
        if not runtime_file.exists():
            continue
        try:
            return json.loads(runtime_file.read_text())
        except Exception:
            continue
    return None


def is_process_running(pid: int) -> bool:
    """Check if process is running"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@click.group()
def cli():
    """Hapa Telemetry Node CLI"""
    pass


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8730, type=int, help="Bind port")
@click.option("--daemon", is_flag=True, help="Run as daemon")
def start(host: str, port: int, daemon: bool):
    """Start telemetry node service"""
    # Check if already running
    runtime = load_runtime()
    if runtime and is_process_running(runtime["pid"]):
        console.print(f"[yellow]Telemetry node already running (PID: {runtime['pid']})[/yellow]")
        return
    
    if daemon:
        # Start as daemon
        env = os.environ.copy()
        env["HAPA_TELEMETRY_HOST"] = host
        env["HAPA_TELEMETRY_PORT"] = str(port)
        
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "hapa_telemetry_node.app:app",
             "--host", host, "--port", str(port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        save_runtime(process.pid, port)
        console.print(f"[green]Telemetry node started (PID: {process.pid})[/green]")
        console.print(f"Dashboard: http://{host}:{port}")
        console.print(f"Token: {get_token()}")
    else:
        # Run in foreground
        import uvicorn
        os.environ["HAPA_TELEMETRY_HOST"] = host
        os.environ["HAPA_TELEMETRY_PORT"] = str(port)
        
        console.print(f"[green]Starting telemetry node...[/green]")
        console.print(f"Dashboard: http://{host}:{port}")
        console.print(f"Token: {get_token()}")
        
        uvicorn.run(
            "hapa_telemetry_node.app:app",
            host=host,
            port=port,
            log_level="info"
        )


@cli.command()
def stop():
    """Stop telemetry node service"""
    runtime = load_runtime()
    if not runtime:
        console.print("[yellow]No running telemetry node found[/yellow]")
        return
    
    pid = runtime["pid"]
    if is_process_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            console.print(f"[green]Telemetry node stopped (PID: {pid})[/green]")
            for p in [get_runtime_file(), LEGACY_RUNTIME_FILE]:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
        except Exception as e:
            console.print(f"[red]Failed to stop telemetry node: {e}[/red]")
    else:
        console.print("[yellow]Telemetry node not running[/yellow]")
        for p in [get_runtime_file(), LEGACY_RUNTIME_FILE]:
            try:
                p.unlink()
            except FileNotFoundError:
                pass


@cli.command()
def status():
    """Show telemetry node status"""
    runtime = load_runtime()
    if runtime and is_process_running(runtime["pid"]):
        console.print(f"[green]● Telemetry node running[/green]")
        console.print(f"  PID: {runtime['pid']}")
        console.print(f"  URL: {runtime['base_url']}")
        
        # Try to get health
        try:
            response = httpx.get(f"{runtime['base_url']}/health", timeout=2.0)
            if response.status_code == 200:
                health = response.json()
                console.print(f"  Monitored nodes: {health.get('monitored_nodes', 0)}")
        except:
            pass
    else:
        console.print("[red]○ Telemetry node not running[/red]")


@cli.command()
@click.option("--active", is_flag=True, help="Show only active nodes")
def list(active: bool):
    """List discovered nodes"""
    asyncio.run(_list_nodes(active))


async def _list_nodes(active_only: bool):
    """List nodes async"""
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {get_token()}"}
            response = await client.get(
                f"{get_base_url()}/v1/nodes",
                params={"active_only": active_only},
                headers=headers,
                timeout=5.0
            )
            
            if response.status_code == 200:
                nodes = response.json()
                
                if not nodes:
                    console.print("[yellow]No nodes discovered yet[/yellow]")
                    return
                
                table = Table(title="Discovered Nodes")
                table.add_column("Node ID", style="cyan")
                table.add_column("Type", style="magenta")
                table.add_column("Status", style="green")
                table.add_column("URL")
                table.add_column("Health")
                table.add_column("Metrics")
                
                for node in nodes:
                    status_color = {
                        "online": "green",
                        "degraded": "yellow",
                        "offline": "red",
                        "unknown": "dim"
                    }.get(node.get("status", "unknown"), "white")
                    
                    metrics = node.get("metrics", {})
                    metrics_str = ""
                    if metrics.get("cpu_percent"):
                        metrics_str += f"CPU: {metrics['cpu_percent']:.1f}% "
                    if metrics.get("queue_depth") is not None:
                        metrics_str += f"Queue: {metrics['queue_depth']}"
                    
                    table.add_row(
                        node["node_id"],
                        node.get("service_type", "unknown"),
                        f"[{status_color}]{node.get('status', 'unknown')}[/{status_color}]",
                        node["base_url"],
                        node.get("health", {}).get("status", "-"),
                        metrics_str or "-"
                    )
                
                console.print(table)
            else:
                console.print(f"[red]Failed to get nodes: {response.status_code}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def _print_json(data: Any):
    try:
        console.print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        console.print(str(data))


def _require_ok(response: httpx.Response) -> Any:
    if response.status_code != 200:
        raise click.ClickException(f"HTTP {response.status_code}: {response.text}")
    try:
        return response.json()
    except Exception:
        return response.text


def _ow_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_token()}"}


def _ow_url(path: str) -> str:
    return f"{get_base_url()}{path}"


@cli.group()
def overwatch():
    """Overwatch Bridge commands"""
    pass


@overwatch.command("health")
def overwatch_health():
    """Show Overwatch Bridge health"""
    resp = httpx.get(_ow_url("/v1/overwatch/health"), headers=_ow_headers(), timeout=10.0)
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("summary")
def overwatch_summary():
    """Show Overwatch summary (docs/tasks/check-ins/writes)"""
    resp = httpx.get(_ow_url("/v1/overwatch/summary"), headers=_ow_headers(), timeout=15.0)
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("docs")
def overwatch_docs():
    """List curated Overwatch docs"""
    resp = httpx.get(_ow_url("/v1/overwatch/docs"), headers=_ow_headers(), timeout=15.0)
    data = _require_ok(resp)
    if not isinstance(data, list):
        _print_json(data)
        return

    table = Table(title="Overwatch Docs")
    table.add_column("doc_id", style="cyan", no_wrap=True)
    table.add_column("title", style="magenta")
    table.add_column("exists", style="green")
    table.add_column("path")
    for d in data:
        if not isinstance(d, dict):
            continue
        table.add_row(
            str(d.get("doc_id", "")),
            str(d.get("title", "")),
            "✓" if d.get("exists") else "-",
            str(d.get("path") or d.get("rel_path") or ""),
        )
    console.print(table)


@overwatch.command("doc")
@click.argument("doc_id")
@click.option("--include-content/--no-content", default=True, help="Include file content")
def overwatch_doc(doc_id: str, include_content: bool):
    """Read a single Overwatch doc by doc_id"""
    resp = httpx.get(
        _ow_url(f"/v1/overwatch/docs/{doc_id}"),
        params={"include_content": "true" if include_content else "false"},
        headers=_ow_headers(),
        timeout=15.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("status-board")
def overwatch_status_board():
    """Get parsed status board"""
    resp = httpx.get(_ow_url("/v1/overwatch/status_board"), headers=_ow_headers(), timeout=15.0)
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("task-inbox")
def overwatch_task_inbox():
    """Get parsed task inbox"""
    resp = httpx.get(_ow_url("/v1/overwatch/task_inbox"), headers=_ow_headers(), timeout=15.0)
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("test-cards")
def overwatch_test_cards():
    """Get test card deck and items"""
    resp = httpx.get(_ow_url("/v1/overwatch/test_cards"), headers=_ow_headers(), timeout=15.0)
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("check-ins")
@click.option("--limit", default=30, type=int, help="Max check-ins")
def overwatch_check_ins(limit: int):
    """List check-ins"""
    resp = httpx.get(
        _ow_url("/v1/overwatch/check_ins"),
        params={"limit": limit},
        headers=_ow_headers(),
        timeout=15.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("check-in")
@click.argument("name")
@click.option("--include-content/--no-content", default=True, help="Include markdown content")
def overwatch_check_in(name: str, include_content: bool):
    """Read a single check-in"""
    resp = httpx.get(
        _ow_url(f"/v1/overwatch/check_ins/{name}"),
        params={"include_content": "true" if include_content else "false"},
        headers=_ow_headers(),
        timeout=15.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("search")
@click.argument("query")
@click.option("--max-results", default=50, type=int, help="Max results")
def overwatch_search(query: str, max_results: int):
    """Search Overwatch docs and check-ins"""
    resp = httpx.get(
        _ow_url("/v1/overwatch/search"),
        params={"q": query, "max_results": max_results},
        headers=_ow_headers(),
        timeout=20.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("search-tree")
@click.argument("query")
@click.option("--scope", default="", help="Rel path under .Overwatch (e.g. ecosystem)")
@click.option("--max-results", default=80, type=int, help="Max results")
@click.option("--max-files", default=1200, type=int, help="Max files scanned")
def overwatch_search_tree(query: str, scope: str, max_results: int, max_files: int):
    """Search full Overwatch filesystem tree"""
    resp = httpx.get(
        _ow_url("/v1/overwatch/search_tree"),
        params={
            "q": query,
            "max_results": max_results,
            "max_files": max_files,
            "rel_path": scope,
        },
        headers=_ow_headers(),
        timeout=60.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("ls")
@click.argument("rel_path", required=False, default="")
@click.option("--max-entries", default=400, type=int, help="Max directory entries")
def overwatch_ls(rel_path: str, max_entries: int):
    """List a directory under the Overwatch root"""
    resp = httpx.get(
        _ow_url("/v1/overwatch/fs/ls"),
        params={"rel_path": rel_path, "max_entries": max_entries},
        headers=_ow_headers(),
        timeout=20.0,
    )
    data = _require_ok(resp)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        _print_json(data)
        return

    table = Table(title=f"Overwatch ls: {data.get('rel_path') or '.'}")
    table.add_column("type", style="cyan", no_wrap=True)
    table.add_column("name", style="magenta")
    table.add_column("size", style="green")
    table.add_column("modified")
    table.add_column("rel_path")
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        is_dir = bool(item.get("is_dir"))
        size = item.get("size_bytes")
        mod = item.get("modified_at")
        table.add_row(
            "DIR" if is_dir else "FILE",
            str(item.get("name") or ""),
            "—" if size is None else str(size),
            "—" if not mod else str(mod)[:19],
            str(item.get("rel_path") or ""),
        )
    console.print(table)
    if data.get("truncated"):
        console.print("[yellow]Warning:[/yellow] listing truncated")


@overwatch.command("read")
@click.argument("rel_path")
@click.option("--include-content/--no-content", default=True, help="Include file content")
@click.option("--max-bytes", default=400000, type=int, help="Max bytes to read")
def overwatch_read(rel_path: str, include_content: bool, max_bytes: int):
    """Read a file under the Overwatch root (safe)"""
    resp = httpx.get(
        _ow_url("/v1/overwatch/fs/read"),
        params={
            "rel_path": rel_path,
            "include_content": "true" if include_content else "false",
            "max_bytes": max_bytes,
        },
        headers=_ow_headers(),
        timeout=30.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("activity")
@click.option("--limit", default=50, type=int, help="Max items")
def overwatch_activity(limit: int):
    """Get Overwatch activity feed"""
    resp = httpx.get(
        _ow_url("/v1/overwatch/activity"),
        params={"limit": limit},
        headers=_ow_headers(),
        timeout=20.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("protocol-scorecards")
@click.option("--max-files", default=250, type=int, help="Max files scanned")
def overwatch_protocol_scorecards(max_files: int):
    """Get protocol/doc freshness scorecards"""
    resp = httpx.get(
        _ow_url("/v1/overwatch/protocol_scorecards"),
        params={"max_files": max_files},
        headers=_ow_headers(),
        timeout=30.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.command("chat")
@click.option("--prompt", required=True, help="Prompt/question to ask")
@click.option("--max-tokens", default=300, type=int, help="Max tokens")
@click.option("--temperature", default=0.2, type=float, help="Sampling temperature")
def overwatch_chat(prompt: str, max_tokens: int, temperature: float):
    """Query Overwatch Chat (uses citations + local LLaDA if available)"""
    resp = httpx.post(
        _ow_url("/v1/overwatch/chat"),
        json={"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature},
        headers=_ow_headers(),
        timeout=60.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch.group("write")
def overwatch_write():
    """Write helpers (env-gated by server)"""
    pass


@overwatch_write.command("task")
@click.option("--title", required=True, help="Task title")
@click.option("--target-agent", default="ANY", help="Target agent")
@click.option("--requested-by", default="", help="Requested by")
@click.option("--timebox", default="", help="Timebox")
@click.option("--goal", default="", help="Goal")
@click.option("--repo", default="", help="Repo path")
@click.option("--files", default="n/a", help="Files")
@click.option("--definition-of-done", default="", help="Definition of done")
@click.option("--validation", default="n/a", help="Validation")
@click.option("--notes", default=None, help="Optional notes")
@click.option("--task-id", default=None, help="Optional explicit task id")
@click.option("--dry-run/--create", default=True, help="Preview only (default) or create")
def overwatch_write_task(
    title: str,
    target_agent: str,
    requested_by: str,
    timebox: str,
    goal: str,
    repo: str,
    files: str,
    definition_of_done: str,
    validation: str,
    notes: Optional[str],
    task_id: Optional[str],
    dry_run: bool,
):
    """Create a TASK_INBOX entry"""
    payload = {
        "title": title,
        "target_agent": target_agent,
        "requested_by": requested_by,
        "timebox": timebox,
        "goal": goal,
        "repo": repo,
        "files": files,
        "definition_of_done": definition_of_done,
        "validation": validation,
        "dry_run": dry_run,
    }
    if notes is not None:
        payload["notes"] = notes
    if task_id is not None:
        payload["task_id"] = task_id

    resp = httpx.post(
        _ow_url("/v1/overwatch/write/task_inbox"),
        json=payload,
        headers=_ow_headers(),
        timeout=30.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch_write.command("check-in-stub")
@click.option("--topic", required=True, help="Topic slug")
@click.option("--dry-run/--create", default=True, help="Preview only (default) or create")
def overwatch_write_check_in_stub(topic: str, dry_run: bool):
    """Create a new check-in stub at Overwatch root"""
    resp = httpx.post(
        _ow_url("/v1/overwatch/write/check_in_stub"),
        json={"topic": topic, "dry_run": dry_run},
        headers=_ow_headers(),
        timeout=30.0,
    )
    data = _require_ok(resp)
    _print_json(data)


@overwatch_write.command("artifact")
@click.option("--rel-path", required=True, help="Relative path under Overwatch Bridge artifact root")
@click.option("--content", default=None, help="Raw string content")
@click.option("--json-content", default=None, help="JSON string content")
@click.option("--from-file", default=None, type=click.Path(exists=True, dir_okay=False), help="Read content from a local file")
@click.option("--dry-run/--create", default=True, help="Preview only (default) or create")
def overwatch_write_artifact(
    rel_path: str,
    content: Optional[str],
    json_content: Optional[str],
    from_file: Optional[str],
    dry_run: bool,
):
    """Write an artifact (e.g. snapshot) via Overwatch Bridge"""
    sources = [content is not None, json_content is not None, from_file is not None]
    if sum(1 for v in sources if v) != 1:
        raise click.ClickException("Specify exactly one of --content, --json-content, or --from-file")

    resolved: Any
    if json_content is not None:
        try:
            resolved = json.loads(json_content)
        except Exception as e:
            raise click.ClickException(f"Invalid --json-content: {e}")
    elif from_file is not None:
        p = Path(from_file)
        raw = p.read_text(encoding="utf-8", errors="replace")
        if p.suffix.lower() == ".json":
            try:
                resolved = json.loads(raw)
            except Exception:
                resolved = raw
        else:
            resolved = raw
    else:
        resolved = content

    resp = httpx.post(
        _ow_url("/v1/overwatch/write/artifact"),
        json={"rel_path": rel_path, "content": resolved, "dry_run": dry_run},
        headers=_ow_headers(),
        timeout=30.0,
    )
    data = _require_ok(resp)
    _print_json(data)



@cli.command()
def discover():
    """Trigger discovery scan"""
    asyncio.run(_discover())


async def _discover():
    """Run discovery async"""
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {get_token()}"}
            
            console.print("[yellow]Scanning for nodes...[/yellow]")
            response = await client.post(
                f"{get_base_url()}/v1/discovery/scan",
                headers=headers,
                timeout=30.0
            )
            
            if response.status_code == 200:
                result = response.json()
                console.print(f"[green]Discovered {result['discovered']} nodes[/green]")
                if result.get("nodes"):
                    for node_id in result["nodes"]:
                        console.print(f"  • {node_id}")
            else:
                console.print(f"[red]Failed to scan: {response.status_code}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument("node_id")
def info(node_id: str):
    """Get detailed node information"""
    asyncio.run(_get_node_info(node_id))


async def _get_node_info(node_id: str):
    """Get node info async"""
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {get_token()}"}
            response = await client.get(
                f"{get_base_url()}/v1/nodes/{node_id}",
                headers=headers,
                timeout=5.0
            )
            
            if response.status_code == 200:
                node = response.json()
                
                console.print(f"\n[bold cyan]Node: {node_id}[/bold cyan]")
                console.print(f"Type: {node.get('service_type', 'unknown')}")
                console.print(f"URL: {node['base_url']}")
                console.print(f"Status: {node.get('status', 'unknown')}")
                
                if node.get("telemetry"):
                    telem = node["telemetry"]
                    console.print("\n[bold]Latest Telemetry:[/bold]")
                    console.print(f"  Timestamp: {telem['timestamp']}")
                    
                    if telem.get("health"):
                        console.print(f"  Health: {telem['health']['status']}")
                    
                    if telem.get("metrics"):
                        console.print("\n[bold]Metrics:[/bold]")
                        metrics = telem["metrics"]
                        for key, value in metrics.items():
                            if value is not None and key != "custom":
                                console.print(f"  {key}: {value}")
                    
                    if telem.get("capabilities"):
                        console.print("\n[bold]Capabilities:[/bold]")
                        caps = telem["capabilities"]
                        if caps.get("api_version"):
                            console.print(f"  API Version: {caps['api_version']}")
                        if caps.get("supported_operations"):
                            console.print(f"  Operations: {', '.join(caps['supported_operations'])}")
            else:
                console.print(f"[red]Node not found[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
def graph():
    """Show node relationship graph"""
    asyncio.run(_show_graph())


async def _show_graph():
    """Show graph async"""
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {get_token()}"}
            response = await client.get(
                f"{get_base_url()}/v1/graph",
                headers=headers,
                timeout=5.0
            )
            
            if response.status_code == 200:
                graph = response.json()
                
                # Build tree visualization
                tree = Tree("[bold cyan]Node Relationships[/bold cyan]")
                
                # Group nodes by type
                nodes_by_type = {}
                for node in graph["nodes"]:
                    node_type = node["service_type"]
                    if node_type not in nodes_by_type:
                        nodes_by_type[node_type] = []
                    nodes_by_type[node_type].append(node)
                
                # Add nodes to tree
                for node_type, nodes in nodes_by_type.items():
                    type_branch = tree.add(f"[magenta]{node_type}[/magenta]")
                    for node in nodes:
                        status_color = {
                            "online": "green",
                            "degraded": "yellow",
                            "offline": "red",
                            "unknown": "dim"
                        }.get(node["status"], "white")
                        type_branch.add(f"[{status_color}]{node['label']}[/{status_color}]")
                
                console.print(tree)
                
                # Show edges
                if graph["edges"]:
                    console.print("\n[bold]Relationships:[/bold]")
                    for edge in graph["edges"]:
                        rel_symbol = {
                            "depends_on": "→",
                            "provides_to": "⇒",
                            "peers": "↔",
                            "manages": "⊃",
                            "monitors": "👁"
                        }.get(edge["relationship"], "-")
                        
                        console.print(f"  {edge['source']} {rel_symbol} {edge['target']} ({edge['relationship']})")
            else:
                console.print(f"[red]Failed to get graph: {response.status_code}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument('base_url')
@click.option('--node-id', help='Node ID')
@click.option('--service-type', default='api', help='Service type')
@click.option('--display-name', help='Display name')
def register(base_url, node_id, service_type, display_name):
    """Register a node manually"""
    import httpx
    
    if not base_url.startswith('http'):
        base_url = f'http://{base_url}'
    
    if not node_id:
        # Extract from URL
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        node_id = f"{parsed.hostname}_{parsed.port or 80}"
    
    token = get_token()
    
    console.print(f"Registering node: {node_id}")
    
    payload = {
        "node_id": node_id,
        "service_type": service_type,
        "base_url": base_url,
        "display_name": display_name or node_id
    }
    
    try:
        response = httpx.post(
            f"{get_base_url()}/v1/discovery/register",
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            console.print(f"[green]✓[/green] Node registered: {node_id}")
        else:
            console.print(f"[red]✗[/red] Registration failed: {response.text}")
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")


@cli.command()
def registry():
    """List registered node types"""
    import httpx
    
    token = get_token()
    
    try:
        response = httpx.get(
            f"{get_base_url()}/v1/registry/nodes",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            node_types = response.json()
            
            table = Table(title="Registered Node Types")
            table.add_column("Type", style="cyan", no_wrap=True)
            table.add_column("Name", style="magenta")
            table.add_column("Port", style="green")
            table.add_column("Auth", style="yellow")
            table.add_column("Auto-start", style="blue")
            
            for nt in node_types:
                table.add_row(
                    nt["node_type"],
                    nt["display_name"],
                    str(nt.get("default_port", "-")),
                    nt.get("auth_type", "none"),
                    "✓" if nt.get("auto_start") else "-"
                )
            
            console.print(table)
        else:
            console.print(f"[red]Failed to get registry: {response.text}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument('node_type')
@click.option('--port', type=int, help='Port to use')
@click.option('--instance-id', help='Instance identifier')
@click.option('--env', multiple=True, help='Environment variables (KEY=VALUE)')
def launch(node_type, port, instance_id, env):
    """Launch a node instance"""
    import httpx
    
    token = get_token()
    
    console.print(f"Launching {node_type}...")
    
    payload = {
        "node_type": node_type
    }
    
    if port:
        payload["port"] = port
    if instance_id:
        payload["instance_id"] = instance_id
    if env:
        env_dict = {}
        for e in env:
            if '=' in e:
                key, value = e.split('=', 1)
                env_dict[key] = value
        payload["env"] = env_dict
    
    try:
        response = httpx.post(
            f"{get_base_url()}/v1/launcher/start",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            result = response.json()
            console.print(f"[green]✓[/green] Launched: {result['instance_id']}")
            console.print(f"  PID: {result['pid']}")
            console.print(f"  Port: {result['port']}")
            console.print(f"  Logs: {result['logs_path']}")
        else:
            console.print(f"[red]✗[/red] Launch failed: {response.text}")
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")


@cli.command()
@click.argument('instance_id')
def stop_instance(instance_id):
    """Stop a running instance"""
    import httpx
    
    token = get_token()
    
    console.print(f"Stopping {instance_id}...")
    
    try:
        response = httpx.post(
            f"{get_base_url()}/v1/launcher/stop",
            json={"instance_id": instance_id},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            console.print(f"[green]✓[/green] Stopped: {instance_id}")
        else:
            console.print(f"[red]✗[/red] Stop failed: {response.text}")
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")


@cli.command()
def instances():
    """List running instances"""
    import httpx
    
    token = get_token()
    
    try:
        response = httpx.get(
            f"{get_base_url()}/v1/launcher/instances",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            instances = response.json()
            
            if not instances:
                console.print("No running instances")
                return
            
            table = Table(title="Running Instances")
            table.add_column("Instance", style="cyan", no_wrap=True)
            table.add_column("Type", style="magenta")
            table.add_column("PID", style="green")
            table.add_column("Port", style="yellow")
            table.add_column("Status", style="blue")
            table.add_column("Started", style="white")
            
            for inst in instances:
                table.add_row(
                    inst["instance_id"],
                    inst["node_type"],
                    str(inst["pid"]),
                    str(inst["port"]),
                    inst["status"],
                    inst["started_at"][:19]
                )
            
            console.print(table)
        else:
            console.print(f"[red]Failed to get instances: {response.text}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.argument('instance_id')
@click.option('--lines', '-n', default=50, help='Number of lines to show')
def logs(instance_id, lines):
    """Show logs for an instance"""
    import httpx
    
    token = get_token()
    
    try:
        response = httpx.get(
            f"{get_base_url()}/v1/launcher/instances/{instance_id}/logs",
            params={"lines": lines},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code == 200:
            result = response.json()
            console.print(f"[bold]Logs for {instance_id}:[/bold]\n")
            console.print(result["logs"])
        else:
            console.print(f"[red]Failed to get logs: {response.text}[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command("janus-push")
@click.option("--janus-url", default=None, help="Janus World Node base URL")
@click.option("--janus-token", default=None, help="Janus World Node bearer token")
@click.option("--timeout", default=5.0, type=float, help="Janus request timeout passed through to bridge")
def janus_push(janus_url: Optional[str], janus_token: Optional[str], timeout: float):
    """Push current node snapshots into Janus World Node."""
    target_url = (janus_url or os.environ.get("HAPA_JANUS_WORLD_NODE_BASE_URL") or "http://127.0.0.1:8741").rstrip("/")
    target_token = janus_token or os.environ.get("HAPA_JANUS_WORLD_NODE_TOKEN") or os.environ.get("HAPA_JANUS_TOKEN")
    if not target_token:
        console.print("[red]Missing Janus token. Pass --janus-token or set HAPA_JANUS_WORLD_NODE_TOKEN/HAPA_JANUS_TOKEN.[/red]")
        raise click.ClickException("janus token required")

    payload = {"janus_base_url": target_url, "janus_token": target_token, "timeout": float(timeout)}
    response = httpx.post(
        f"{get_base_url()}/v1/bridges/janus/push",
        json=payload,
        headers={"Authorization": f"Bearer {get_token()}"},
        timeout=10.0,
    )

    if response.status_code != 200:
        raise click.ClickException(f"Janus push failed: HTTP {response.status_code}: {response.text}")

    data = response.json()
    ok = "✓" if data.get("ok") else "!"
    console.print(
        f"[green]{ok}[/green] Janus push: attempted={data.get('attempted', 0)} "
        f"succeeded={data.get('succeeded', 0)} failed={data.get('failed', 0)}"
    )
    for item in data.get("results") or []:
        node_id = item.get("node_id", "unknown")
        if item.get("ok"):
            console.print(f"  [green]✓[/green] {node_id}")
        else:
            console.print(f"  [yellow]![/yellow] {node_id}: {item.get('error') or item.get('status_code') or 'failed'}")


@cli.command()
def test():
    """Run self-test"""
    from .self_test import run_self_test
    raise SystemExit(asyncio.run(run_self_test()))


def main():
    """Main CLI entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return 1
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
