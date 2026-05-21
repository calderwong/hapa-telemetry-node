"""FastAPI application for telemetry node"""

import os
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import httpx

from .models import (
    NodeInfo, NodeRegistration, NodeTelemetry, NodeGraph,
    GraphNode, GraphEdge, NodeStatus, RelationshipType
)
from .database import Database
from .auth import TokenAuth
from .discovery import NodeDiscovery
from .collector import TelemetryCollector
from .registry import NodeRegistry, NodeState
from . import overwatch_bridge

logger = logging.getLogger(__name__)

# Global instances
db = Database()
auth = TokenAuth()
discovery = None
collector = None
registry = NodeRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global discovery, collector
    disable_bg = os.environ.get("HAPA_TELEMETRY_DISABLE_BG_TASKS", "").strip().lower() in {"1", "true", "yes", "y", "on"}
    
    # Startup
    await db.initialize()
    
    # Register self
    await db.register_node(NodeInfo(
        node_id="telemetry-node",
        service_type="telemetry",
        base_url=f"http://127.0.0.1:{os.environ.get('HAPA_TELEMETRY_PORT', 8730)}",
        display_name="Telemetry Node",
        description="Central monitoring for Hapa ecosystem",
        auth_required=True,
        metadata={"version": "1.0.0"}
    ))
    
    if not disable_bg:
        # Start discovery engine
        discovery = NodeDiscovery(db)
        await discovery.start()

        # Start telemetry collector
        collector = TelemetryCollector(
            db,
            interval=int(os.environ.get("HAPA_TELEMETRY_COLLECT_INTERVAL", 10)),
        )
        asyncio.create_task(collector.start())

        # Run initial discovery
        asyncio.create_task(discovery.discover_all())

        # Schedule periodic discovery
        async def periodic_discovery():
            while True:
                await asyncio.sleep(int(os.environ.get("HAPA_TELEMETRY_SCAN_INTERVAL", 30)))
                await discovery.discover_all()

        asyncio.create_task(periodic_discovery())
    else:
        discovery = None
        collector = None
    
    logger.info("Telemetry node started")
    
    yield
    
    # Shutdown
    if collector:
        await collector.stop()
    if discovery:
        await discovery.stop()
    await db.close()
    logger.info("Telemetry node stopped")


app = FastAPI(
    title="Hapa Telemetry Node",
    version="1.0.0",
    lifespan=lifespan
)


# Public endpoints

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve dashboard UI"""
    ui_path = Path(__file__).parent.parent / "web" / "index.html"
    if ui_path.exists():
        return ui_path.read_text()
    return "<h1>Telemetry Node Dashboard</h1><p>UI not found</p>"


@app.get("/health")
async def health():
    """Health check"""
    nodes = await db.list_nodes(active_only=True)
    return {
        "status": "healthy",
        "service": "telemetry-node",
        "monitored_nodes": len(nodes),
        "timestamp": datetime.utcnow().isoformat()
    }


# Authenticated endpoints

@app.get("/v1/capabilities", dependencies=[Depends(auth.verify_token)])
async def capabilities():
    """Get telemetry node capabilities"""
    overwatch_root = str(overwatch_bridge.get_overwatch_root())
    return {
        "service": "telemetry-node",
        "api_version": "1.0.0",
        "node_id": "telemetry-node",
        "discovery_methods": ["mdns", "port_scan", "registry", "manual"],
        "telemetry_interval": int(os.environ.get("HAPA_TELEMETRY_COLLECT_INTERVAL", 10)),
        "supported_operations": [
            "discover",
            "monitor",
            "graph",
            "query",
            "register",
            "overwatch_bridge"
        ],
        "overwatch": {
            "root": overwatch_root,
            "docs": [
                {
                    "doc_id": d["doc_id"],
                    "title": d["title"],
                    "rel_path": d["rel_path"],
                }
                for d in overwatch_bridge.get_static_docs()
            ],
            "writes": overwatch_bridge.get_write_capabilities(),
        },
        "metrics": {
            "node_count": len(await db.list_nodes()),
            "active_nodes": len(await db.list_nodes(active_only=True))
        }
    }


@app.get("/v1/overwatch/health", dependencies=[Depends(auth.verify_token)])
async def overwatch_health() -> Dict[str, Any]:
    root = overwatch_bridge.get_overwatch_root()
    return {
        "ok": root.exists(),
        "root": str(root),
        "docs": overwatch_bridge.get_static_docs(),
        "check_ins": len(overwatch_bridge.list_check_ins(limit=500)),
        "writes": overwatch_bridge.get_write_capabilities(),
    }


@app.get("/v1/overwatch/write/capabilities", dependencies=[Depends(auth.verify_token)])
async def overwatch_write_capabilities() -> Dict[str, Any]:
    return overwatch_bridge.get_write_capabilities()


@app.post("/v1/overwatch/write/task_inbox", dependencies=[Depends(auth.verify_token)])
async def overwatch_write_task_inbox(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return overwatch_bridge.create_task_inbox_entry(
            title=str(payload.get("title", "")),
            target_agent=str(payload.get("target_agent", "ANY")),
            requested_by=str(payload.get("requested_by", "")),
            timebox=str(payload.get("timebox", "")),
            goal=str(payload.get("goal", "")),
            repo=str(payload.get("repo", "")),
            files=str(payload.get("files", "n/a")),
            definition_of_done=str(payload.get("definition_of_done", "")),
            validation=str(payload.get("validation", "n/a")),
            notes=None if payload.get("notes") is None else str(payload.get("notes")),
            task_id=None if payload.get("task_id") is None else str(payload.get("task_id")),
            dry_run=bool(payload.get("dry_run", False)),
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write task inbox: {e}")


@app.post("/v1/overwatch/write/check_in_stub", dependencies=[Depends(auth.verify_token)])
async def overwatch_write_check_in_stub(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        topic = str(payload.get("topic", ""))
        return overwatch_bridge.create_check_in_stub(topic=topic, dry_run=bool(payload.get("dry_run", False)))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create check-in stub: {e}")


@app.post("/v1/overwatch/write/briefing_stub", dependencies=[Depends(auth.verify_token)])
async def overwatch_write_briefing_stub(payload: Dict[str, Any]) -> Dict[str, Any]:
    return await overwatch_write_check_in_stub(payload)


@app.post("/v1/overwatch/write/artifact", dependencies=[Depends(auth.verify_token)])
async def overwatch_write_artifact(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        rel_path = str(payload.get("rel_path", "")).strip()
        if not rel_path:
            raise ValueError("rel_path is required")
        content = payload.get("content")
        return overwatch_bridge.write_artifact(
            rel_path=rel_path,
            content=content,
            dry_run=bool(payload.get("dry_run", False)),
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write artifact: {e}")


@app.get("/v1/overwatch/docs", dependencies=[Depends(auth.verify_token)])
async def overwatch_docs() -> List[Dict[str, Any]]:
    root = overwatch_bridge.get_overwatch_root()
    out: List[Dict[str, Any]] = []
    for d in overwatch_bridge.get_static_docs():
        try:
            doc = overwatch_bridge.read_doc(d["doc_id"], include_content=False)
        except Exception:
            abs_path = (root / d["rel_path"]).expanduser()
            doc = {**d, "exists": abs_path.exists(), "path": str(abs_path)}
        out.append(doc)
    return out


@app.get("/v1/overwatch/docs/{doc_id}", dependencies=[Depends(auth.verify_token)])
async def overwatch_doc(doc_id: str, include_content: bool = True) -> Dict[str, Any]:
    try:
        return overwatch_bridge.read_doc(doc_id, include_content=include_content)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/overwatch/status_board", dependencies=[Depends(auth.verify_token)])
async def overwatch_status_board() -> Dict[str, Any]:
    try:
        return overwatch_bridge.get_status_board_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read status board: {e}")


@app.get("/v1/overwatch/task_inbox", dependencies=[Depends(auth.verify_token)])
async def overwatch_task_inbox() -> Dict[str, Any]:
    try:
        return overwatch_bridge.get_task_inbox_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read task inbox: {e}")


@app.get("/v1/overwatch/test_cards", dependencies=[Depends(auth.verify_token)])
async def overwatch_test_cards() -> Dict[str, Any]:
    try:
        return overwatch_bridge.get_test_cards_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read test cards: {e}")


@app.get("/v1/overwatch/check_ins", dependencies=[Depends(auth.verify_token)])
async def overwatch_check_ins(limit: int = 30) -> List[Dict[str, Any]]:
    try:
        return overwatch_bridge.list_check_ins(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list check-ins: {e}")


@app.get("/v1/overwatch/check_ins/{name}", dependencies=[Depends(auth.verify_token)])
async def overwatch_check_in(name: str, include_content: bool = True) -> Dict[str, Any]:
    try:
        return overwatch_bridge.read_check_in(name, include_content=include_content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read check-in: {e}")


@app.get("/v1/overwatch/search", dependencies=[Depends(auth.verify_token)])
async def overwatch_search(q: str, max_results: int = 50) -> Dict[str, Any]:
    try:
        return overwatch_bridge.search_overwatch(q, max_results=max_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")


def _clamp_int(value: Any, default: int, min_v: int, max_v: int) -> int:
    try:
        v = int(value)
    except Exception:
        v = int(default)
    if v < int(min_v):
        return int(min_v)
    if v > int(max_v):
        return int(max_v)
    return int(v)


@app.get("/v1/overwatch/fs/ls", dependencies=[Depends(auth.verify_token)])
async def overwatch_fs_ls(rel_path: str = "", max_entries: int = 400) -> Dict[str, Any]:
    try:
        max_entries_clamped = _clamp_int(max_entries, default=400, min_v=1, max_v=2000)
        return overwatch_bridge.list_overwatch_dir(rel_path=rel_path, max_entries=max_entries_clamped)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list path: {e}")


@app.get("/v1/overwatch/fs/read", dependencies=[Depends(auth.verify_token)])
async def overwatch_fs_read(rel_path: str, include_content: bool = True, max_bytes: int = 400_000) -> Dict[str, Any]:
    try:
        max_bytes_clamped = _clamp_int(max_bytes, default=400_000, min_v=1_000, max_v=2_000_000)
        return overwatch_bridge.read_overwatch_path(
            rel_path=rel_path,
            include_content=bool(include_content),
            max_bytes=max_bytes_clamped,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read path: {e}")


@app.get("/v1/overwatch/search_tree", dependencies=[Depends(auth.verify_token)])
async def overwatch_search_tree(
    q: str,
    max_results: int = 100,
    max_files: int = 500,
    rel_path: str = "",
) -> Dict[str, Any]:
    try:
        max_results_clamped = _clamp_int(max_results, default=100, min_v=1, max_v=400)
        max_files_clamped = _clamp_int(max_files, default=500, min_v=1, max_v=5000)
        return overwatch_bridge.search_overwatch_tree(
            query=q,
            max_results=max_results_clamped,
            max_files=max_files_clamped,
            rel_path=rel_path,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search tree failed: {e}")


@app.get("/v1/overwatch/summary", dependencies=[Depends(auth.verify_token)])
async def overwatch_summary() -> Dict[str, Any]:
    try:
        return overwatch_bridge.get_overwatch_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build summary: {e}")


@app.get("/v1/overwatch/activity", dependencies=[Depends(auth.verify_token)])
async def overwatch_activity(limit: int = 50) -> Dict[str, Any]:
    try:
        return overwatch_bridge.get_activity_feed(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build activity feed: {e}")


@app.get("/v1/overwatch/protocol_scorecards", dependencies=[Depends(auth.verify_token)])
async def overwatch_protocol_scorecards(max_files: int = 250) -> Dict[str, Any]:
    try:
        return overwatch_bridge.get_protocol_scorecards(max_files=max_files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build protocol scorecards: {e}")


def _llada_default_root() -> Optional[Path]:
    try:
        defn = registry.get_node_definition("llada-node")
        if defn and isinstance(defn.launch_config, dict):
            cwd = defn.launch_config.get("cwd")
            if isinstance(cwd, str) and cwd.strip():
                return Path(cwd).expanduser()
    except Exception:
        pass

    default = Path.home() / "Desktop" / "hapa-llada-node"
    return default


def _llada_runtime_path(llada_root: Path) -> Path:
    return llada_root / "artifacts" / "runtime" / "hapa_llada_node_runtime.json"


def _load_llada_runtime(llada_root: Path) -> Optional[Dict[str, Any]]:
    p = _llada_runtime_path(llada_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_llada_token(llada_root: Path, runtime: Optional[Dict[str, Any]]) -> Optional[str]:
    tok = os.environ.get("HAPA_LLADA_NODE_TOKEN") or os.environ.get("HAPA_LLADA_TOKEN")
    if tok and tok.strip():
        return tok.strip()

    token_path_value = runtime.get("token_path") if isinstance(runtime, dict) else None
    candidates: List[Path] = []

    if isinstance(token_path_value, str) and token_path_value.strip():
        p = Path(token_path_value)
        if not p.is_absolute():
            p = llada_root / p
        candidates.append(p)

    candidates.append(llada_root / ".node_token")

    for p in candidates:
        try:
            if p.exists():
                value = p.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except Exception:
            continue

    return None


def _resolve_llada_base_url(llada_root: Path, runtime: Optional[Dict[str, Any]]) -> Optional[str]:
    env_url = (
        os.environ.get("HAPA_LLADA_NODE_BASE_URL")
        or os.environ.get("HAPA_LLADA_BASE_URL")
        or os.environ.get("HAPA_LLADA_URL")
    )
    if env_url and env_url.strip():
        return env_url.strip().rstrip("/")

    if isinstance(runtime, dict):
        base_url = runtime.get("base_url")
        if isinstance(base_url, str) and base_url.strip():
            return base_url.strip().rstrip("/")

    return "http://127.0.0.1:8085"


def _extract_keywords(text: str, max_terms: int = 4) -> List[str]:
    words = re.findall(r"[A-Za-z0-9_\-]{4,}", text or "")
    stop = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "your",
        "what",
        "when",
        "where",
        "will",
        "should",
        "could",
        "would",
        "about",
        "into",
        "overwatch",
        "telemetry",
        "node",
        "nodes",
        "protocol",
        "protocols",
    }
    out: List[str] = []
    seen: set[str] = set()
    for w in words:
        lw = w.lower()
        if lw in stop:
            continue
        if lw in seen:
            continue
        seen.add(lw)
        out.append(w)
        if len(out) >= max_terms:
            break
    return out


def _build_citations(prompt: str, max_citations: int = 24) -> List[Dict[str, Any]]:
    keywords = _extract_keywords(prompt, max_terms=4)
    if not keywords:
        return []

    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for kw in keywords:
        try:
            data = overwatch_bridge.search_overwatch(kw, max_results=10)
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                continue
            for r in results:
                if not isinstance(r, dict):
                    continue
                key = f"{r.get('doc_id')}::{r.get('line')}::{r.get('text')}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(r)
                if len(merged) >= max_citations:
                    return merged
        except Exception:
            continue
    return merged


def _render_citations_for_prompt(citations: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for idx, c in enumerate(citations, start=1):
        doc_id = c.get("doc_id")
        line = c.get("line")
        text = c.get("text")
        title = c.get("title")
        ref = f"{doc_id}:{line}" if doc_id is not None and line is not None else str(doc_id or "")
        hdr = f"[{idx}] {ref}"
        if title:
            hdr += f" — {title}"
        body = str(text or "").strip()
        lines.append(hdr)
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


@app.post("/v1/overwatch/chat", dependencies=[Depends(auth.verify_token)])
async def overwatch_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    max_tokens = payload.get("max_tokens")
    temperature = payload.get("temperature")
    try:
        max_tokens = int(max_tokens) if max_tokens is not None else 300
    except Exception:
        max_tokens = 300
    try:
        temperature = float(temperature) if temperature is not None else 0.2
    except Exception:
        temperature = 0.2

    citations = _build_citations(prompt, max_citations=24)
    citations_block = _render_citations_for_prompt(citations)

    llada_root = _llada_default_root()
    runtime = None
    if llada_root:
        runtime = _load_llada_runtime(llada_root)

    base_url = _resolve_llada_base_url(llada_root or Path.cwd(), runtime)
    token_value = _resolve_llada_token(llada_root or Path.cwd(), runtime)

    if not token_value:
        return {
            "prompt": prompt,
            "answer": None,
            "citations": citations,
            "llada": {"used": False, "base_url": base_url, "error": "llada token not found"},
        }

    system = (
        "You are Overwatch, an operator-grade assistant for the local Hapa ecosystem. "
        "Use only the evidence in the citations when possible. "
        "If the citations are insufficient, say you do not know and suggest what to check next."
    )
    assembled = "\n\n".join(
        [
            system,
            "CITATIONS:\n" + (citations_block or "(none)"),
            "USER QUESTION:\n" + prompt,
            "ANSWER:",
        ]
    )

    req = {
        "prompt": assembled,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    headers = {"Authorization": f"Bearer {token_value}"}
    url = f"{base_url}/v1/completions"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=req, headers=headers)
            if resp.status_code != 200:
                return {
                    "prompt": prompt,
                    "answer": None,
                    "citations": citations,
                    "llada": {
                        "used": False,
                        "base_url": base_url,
                        "status_code": resp.status_code,
                        "error": resp.text,
                    },
                }
            data = resp.json()
            choices = data.get("choices") if isinstance(data, dict) else None
            text = None
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    text = first.get("text")
            return {
                "prompt": prompt,
                "answer": text,
                "citations": citations,
                "llada": {"used": True, "base_url": base_url},
            }
    except Exception as e:
        return {
            "prompt": prompt,
            "answer": None,
            "citations": citations,
            "llada": {"used": False, "base_url": base_url, "error": str(e)},
        }


@app.get("/v1/nodes", dependencies=[Depends(auth.verify_token)])
async def list_nodes(active_only: bool = False) -> List[Dict[str, Any]]:
    """List all discovered nodes"""
    nodes = await db.list_nodes(active_only=active_only)
    
    # Enrich with latest telemetry
    result = []
    for node in nodes:
        telemetry = await db.get_latest_telemetry(node.node_id)
        node_dict = node.model_dump()
        
        if telemetry:
            node_dict["status"] = telemetry.status.value
            node_dict["health"] = telemetry.health.model_dump()
            node_dict["metrics"] = telemetry.metrics.model_dump()
            node_dict["last_telemetry"] = telemetry.timestamp.isoformat()
        else:
            node_dict["status"] = NodeStatus.UNKNOWN.value
        
        result.append(node_dict)
    
    return result


@app.get("/v1/nodes/{node_id}", dependencies=[Depends(auth.verify_token)])
async def get_node(node_id: str) -> Dict[str, Any]:
    """Get node details"""
    node = await db.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    node_dict = node.model_dump()
    
    # Add latest telemetry
    telemetry = await db.get_latest_telemetry(node_id)
    if telemetry:
        node_dict["telemetry"] = telemetry.model_dump()
    
    # Add telemetry history
    history = await db.get_telemetry_history(node_id, hours=1)
    node_dict["history"] = history
    
    return node_dict


@app.get("/v1/telemetry/{node_id}", dependencies=[Depends(auth.verify_token)])
async def get_telemetry(node_id: str, hours: int = 1) -> Dict[str, Any]:
    """Get node telemetry"""
    node = await db.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    latest = await db.get_latest_telemetry(node_id)
    history = await db.get_telemetry_history(node_id, hours=hours)
    
    return {
        "node_id": node_id,
        "latest": latest.model_dump() if latest else None,
        "history": history
    }


@app.post("/v1/discovery/register", dependencies=[Depends(auth.verify_token)])
async def register_node(registration: NodeRegistration) -> Dict[str, Any]:
    """Register a node manually"""
    node_info = NodeInfo(
        node_id=registration.node_id,
        service_type=registration.service_type,
        base_url=registration.base_url,
        display_name=registration.display_name,
        description=registration.description,
        auth_required=registration.auth_required,
        token=registration.token,
        metadata=registration.metadata
    )
    
    await db.register_node(node_info)
    
    # Try to collect initial telemetry
    if collector:
        await collector._collect_node_telemetry(node_info)
    
    return {"status": "registered", "node_id": registration.node_id}


@app.post("/v1/discovery/scan", dependencies=[Depends(auth.verify_token)])
async def trigger_scan() -> Dict[str, Any]:
    """Trigger discovery scan"""
    if discovery:
        nodes = await discovery.discover_all()
        return {
            "status": "completed",
            "discovered": len(nodes),
            "nodes": [n.node_id for n in nodes]
        }
    raise HTTPException(status_code=503, detail="Discovery is not initialized")


@app.get("/v1/graph", dependencies=[Depends(auth.verify_token)])
async def get_graph() -> NodeGraph:
    """Get node relationship graph"""
    nodes = await db.list_nodes()
    graph_nodes = []
    graph_edges = []
    
    # Create graph nodes
    for i, node in enumerate(nodes):
        telemetry = await db.get_latest_telemetry(node.node_id)
        
        graph_nodes.append(GraphNode(
            id=node.node_id,
            label=node.display_name or node.node_id,
            service_type=node.service_type,
            status=telemetry.status if telemetry else NodeStatus.UNKNOWN,
            x=float(i * 150),
            y=float((i % 3) * 150)
        ))
        
        # Add edges from relationships
        if telemetry and telemetry.relationships:
            for dep in telemetry.relationships.depends_on:
                graph_edges.append(GraphEdge(
                    source=node.node_id,
                    target=dep,
                    relationship=RelationshipType.DEPENDS_ON
                ))
            
            for provides in telemetry.relationships.provides_to:
                graph_edges.append(GraphEdge(
                    source=node.node_id,
                    target=provides,
                    relationship=RelationshipType.PROVIDES_TO
                ))
            
            for peer in telemetry.relationships.peers:
                graph_edges.append(GraphEdge(
                    source=node.node_id,
                    target=peer,
                    relationship=RelationshipType.PEERS
                ))
    
    # Add telemetry node monitoring edges
    telemetry_node = "telemetry-node"
    for node in nodes:
        if node.node_id != telemetry_node:
            graph_edges.append(GraphEdge(
                source=telemetry_node,
                target=node.node_id,
                relationship=RelationshipType.MONITORS,
                label="monitors"
            ))
    
    return NodeGraph(
        nodes=graph_nodes,
        edges=graph_edges,
        metadata={"generated_at": datetime.utcnow().isoformat()}
    )


@app.get("/v1/telemetry", dependencies=[Depends(auth.verify_token)])
async def get_self_telemetry() -> Dict[str, Any]:
    """Get telemetry for this telemetry node"""
    if collector:
        telemetry = await collector.collect_local_telemetry()
        if telemetry:
            return telemetry.model_dump()
    
    return {
        "status": "healthy",
        "metrics": {},
        "relationships": {}
    }


@app.post("/v1/telemetry/ping")
async def telemetry_ping(node_id: str, base_url: Optional[str] = None) -> Dict[str, Any]:
    """Accept telemetry ping from nodes"""
    # Register or update node
    if base_url:
        node = await db.get_node(node_id)
        if not node:
            await db.register_node(NodeInfo(
                node_id=node_id,
                base_url=base_url,
                service_type="unknown"
            ))
        else:
            # Update last seen
            await db.register_node(node)
    
    return {"status": "acknowledged", "timestamp": datetime.utcnow().isoformat()}


@app.delete("/v1/nodes/{node_id}", dependencies=[Depends(auth.verify_token)])
async def delete_node(node_id: str) -> Dict[str, Any]:
    """Remove a node from monitoring"""
    node = await db.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # Mark as offline
    await db.mark_node_offline(node_id)
    
    return {"status": "removed", "node_id": node_id}


# Registry and launcher endpoints

@app.get("/v1/registry/nodes", dependencies=[Depends(auth.verify_token)])
async def list_registry() -> List[Dict[str, Any]]:
    """List all registered node types"""
    return [defn.to_dict() for defn in registry.list_definitions()]


@app.post("/v1/registry/nodes", dependencies=[Depends(auth.verify_token)])
async def register_node_type(node_data: Dict[str, Any]) -> Dict[str, Any]:
    """Register a new node type in the registry"""
    try:
        defn = registry.register_node(node_data)
        return {"status": "registered", "node_type": defn.node_type}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/registry/nodes/{node_type}", dependencies=[Depends(auth.verify_token)])
async def get_node_type(node_type: str) -> Dict[str, Any]:
    """Get details of a registered node type"""
    defn = registry.get_node_definition(node_type)
    if not defn:
        raise HTTPException(status_code=404, detail="Node type not found")
    return defn.to_dict()


@app.post("/v1/launcher/start", dependencies=[Depends(auth.verify_token)])
async def launch_node(request: Dict[str, Any]) -> Dict[str, Any]:
    """Launch a node instance"""
    try:
        instance = await registry.launch_node(
            node_type=request["node_type"],
            instance_id=request.get("instance_id"),
            port=request.get("port"),
            env_overrides=request.get("env")
        )
        return instance.to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/launcher/stop", dependencies=[Depends(auth.verify_token)])
async def stop_instance(request: Dict[str, Any]) -> Dict[str, Any]:
    """Stop a node instance"""
    try:
        await registry.stop_node(request["instance_id"])
        return {"status": "stopped", "instance_id": request["instance_id"]}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/launcher/instances", dependencies=[Depends(auth.verify_token)])
async def list_instances() -> List[Dict[str, Any]]:
    """List all running node instances"""
    return [inst.to_dict() for inst in registry.list_instances()]


@app.get("/v1/launcher/instances/{instance_id}", dependencies=[Depends(auth.verify_token)])
async def get_instance(instance_id: str) -> Dict[str, Any]:
    """Get details of a running instance"""
    instance = registry.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instance.to_dict()


@app.get("/v1/launcher/instances/{instance_id}/logs", dependencies=[Depends(auth.verify_token)])
async def get_instance_logs(instance_id: str, lines: int = 100) -> Dict[str, Any]:
    """Get logs from a running instance"""
    instance = registry.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    try:
        with open(instance.logs_path, "r") as f:
            # Read last N lines
            all_lines = f.readlines()
            log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return {
                "instance_id": instance_id,
                "logs": "".join(log_lines),
                "lines": len(log_lines)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")


# Error handlers

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )
