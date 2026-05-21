
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .artifact_paths import get_owner_root


def _default_overwatch_root() -> Path:
    return Path.home() / "Desktop" / ".Overwatch"


def get_overwatch_root() -> Path:
    root = os.environ.get("HAPA_OVERWATCH_ROOT") or os.environ.get("OVERWATCH_ROOT")
    if root:
        return Path(root).expanduser()
    return _default_overwatch_root()


def get_static_docs() -> List[Dict[str, str]]:
    return [
        {
            "doc_id": "status_board",
            "title": "Ecosystem Status Board",
            "rel_path": "ecosystem/STATUS_BOARD.md",
        },
        {
            "doc_id": "task_inbox",
            "title": "Task Inbox",
            "rel_path": "ecosystem/TASK_INBOX.md",
        },
        {
            "doc_id": "ports_and_auth",
            "title": "Ports and Auth",
            "rel_path": "ecosystem/PORTS_AND_AUTH.md",
        },
        {
            "doc_id": "interaction_map",
            "title": "Interaction Map",
            "rel_path": "ecosystem/INTERACTION_MAP.md",
        },
        {
            "doc_id": "topology",
            "title": "Topology",
            "rel_path": "ecosystem/TOPOLOGY.md",
        },
        {
            "doc_id": "workspace_inventory",
            "title": "Workspace Inventory",
            "rel_path": "ecosystem/WORKSPACE_INVENTORY.md",
        },
        {
            "doc_id": "cultivation_checklist",
            "title": "Cultivation Checklist",
            "rel_path": "ecosystem/CULTIVATION_CHECKLIST.md",
        },
        {
            "doc_id": "check_in_protocol",
            "title": "Check-In Protocol",
            "rel_path": "ecosystem/CHECK_IN_PROTOCOL.md",
        },
        {
            "doc_id": "briefing_protocol",
            "title": "Briefing Protocol",
            "rel_path": "ecosystem/BRIEFING_PROTOCOL.md",
        },
        {
            "doc_id": "git_umbrella_protocol",
            "title": "Git Umbrella Protocol",
            "rel_path": "ecosystem/GIT_UMBRELLA_PROTOCOL.md",
        },
        {
            "doc_id": "artifact_vault_protocol",
            "title": "Artifact Vault Protocol",
            "rel_path": "ecosystem/ARTIFACT_VAULT_PROTOCOL.md",
        },
        {
            "doc_id": "test_card_deck",
            "title": "Test Card Deck",
            "rel_path": "ecosystem/TEST_CARD_DECK.md",
        },
        {
            "doc_id": "test_card_deck_items",
            "title": "Test Card Deck Items",
            "rel_path": "ecosystem/TEST_CARD_DECK_ITEMS.json",
        },
        {
            "doc_id": "ui_systems_playbook",
            "title": "UI Systems Playbook",
            "rel_path": "ecosystem/UI_SYSTEMS_PLAYBOOK.md",
        },
        {
            "doc_id": "ui_starter_kit",
            "title": "UI Starter Kit",
            "rel_path": "ecosystem/UI_STARTER_KIT.md",
        },
        {
            "doc_id": "telemetry_protocol",
            "title": "Telemetry Protocol",
            "rel_path": "protocols/TELEMETRY_PROTOCOL.md",
        },
        {
            "doc_id": "node_registry_protocol",
            "title": "Node Registry Protocol",
            "rel_path": "protocols/NODE_REGISTRY_PROTOCOL.md",
        },
        {
            "doc_id": "source_index",
            "title": "Source Index",
            "rel_path": "sources/SOURCE_INDEX.md",
        },
        {
            "doc_id": "overmind",
            "title": "Overwatch Mind",
            "rel_path": ".overMind",
        },
        {
            "doc_id": "overwatch_readme",
            "title": "Overwatch README",
            "rel_path": "README.md",
        },
    ]


def _resolve_under_root(root: Path, rel_path: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root / rel_path).resolve()
    if candidate == root_resolved:
        return candidate
    if root_resolved not in candidate.parents:
        raise ValueError("Path escapes Overwatch root")
    return candidate


def _file_meta(path: Path) -> Dict[str, Any]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return {
            "exists": False,
            "path": str(path),
            "size_bytes": None,
            "modified_at": None,
        }
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": st.st_size,
        "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),
    }


def _read_text(path: Path, max_bytes: int = 2_000_000) -> str:
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace")


def list_overwatch_dir(rel_path: str = "", max_entries: int = 400) -> Dict[str, Any]:
    root = get_overwatch_root()
    safe_rel = (rel_path or "").lstrip("/")
    base = _resolve_under_root(root, safe_rel)

    if not base.exists():
        raise FileNotFoundError(f"Directory not found: {safe_rel or '.'}")
    if not base.is_dir():
        raise ValueError("Path is not a directory")

    items: List[Dict[str, Any]] = []
    truncated = False

    try:
        children = list(base.iterdir())
    except Exception:
        children = []

    def _sort_key(p: Path):
        try:
            is_dir = p.is_dir()
        except Exception:
            is_dir = False
        return (0 if is_dir else 1, p.name.lower())

    children.sort(key=_sort_key)
    for child in children:
        if len(items) >= max_entries:
            truncated = True
            break

        try:
            rel_child = str(child.resolve().relative_to(root.resolve()))
        except Exception:
            continue

        meta = _file_meta(child)
        try:
            is_dir = child.is_dir()
        except Exception:
            is_dir = False

        items.append(
            {
                "name": child.name,
                "rel_path": rel_child,
                "is_dir": bool(is_dir),
                "exists": meta.get("exists"),
                "size_bytes": meta.get("size_bytes"),
                "modified_at": meta.get("modified_at"),
            }
        )

    return {
        "root": str(root),
        "rel_path": safe_rel,
        "path": str(base),
        "exists": True,
        "is_dir": True,
        "truncated": truncated,
        "items": items,
    }


def read_overwatch_path(rel_path: str, include_content: bool = True, max_bytes: int = 400_000) -> Dict[str, Any]:
    root = get_overwatch_root()
    safe_rel = (rel_path or "").lstrip("/")
    if not safe_rel or safe_rel in {".", "./"}:
        raise ValueError("rel_path is required")

    abs_path = _resolve_under_root(root, safe_rel)
    meta = _file_meta(abs_path)

    out: Dict[str, Any] = {
        "root": str(root),
        "rel_path": safe_rel,
        "name": abs_path.name,
        **meta,
    }

    if not meta.get("exists"):
        return out

    if abs_path.is_dir():
        out["is_dir"] = True
        return out

    out["is_dir"] = False

    if not include_content:
        return out

    suffix = abs_path.suffix.lower()
    if suffix == ".json":
        raw = _read_text(abs_path, max_bytes=max_bytes)
        try:
            out["content"] = json.loads(raw)
            out["content_type"] = "application/json"
        except Exception:
            out["content"] = raw
            out["content_type"] = "text/plain"
        return out

    out["content"] = _read_text(abs_path, max_bytes=max_bytes)
    if suffix in {".md", ".markdown"}:
        out["content_type"] = "text/markdown"
    elif suffix in {".yml", ".yaml"}:
        out["content_type"] = "text/yaml"
    else:
        out["content_type"] = "text/plain"

    return out


def read_doc(doc_id: str, include_content: bool = True) -> Dict[str, Any]:
    root = get_overwatch_root()
    for d in get_static_docs():
        if d["doc_id"] != doc_id:
            continue
        rel_path = d["rel_path"]
        abs_path = _resolve_under_root(root, rel_path)
        meta = _file_meta(abs_path)
        out: Dict[str, Any] = {**d, **meta}
        if include_content and meta["exists"]:
            if rel_path.endswith(".json"):
                out["content"] = json.loads(_read_text(abs_path))
                out["content_type"] = "application/json"
            else:
                out["content"] = _read_text(abs_path)
                out["content_type"] = "text/markdown"
        return out
    raise KeyError(f"Unknown doc_id: {doc_id}")


def list_check_ins(limit: int = 30) -> List[Dict[str, Any]]:
    root = get_overwatch_root()
    if not root.exists():
        return []

    checkins = sorted(root.glob("CHECK_IN_*.md"), key=lambda p: p.name, reverse=True)
    if limit and limit > 0:
        checkins = checkins[:limit]

    result: List[Dict[str, Any]] = []
    for p in checkins:
        meta = _file_meta(p)
        result.append(
            {
                "name": p.name,
                **meta,
            }
        )
    return result


def read_check_in(name: str, include_content: bool = True) -> Dict[str, Any]:
    root = get_overwatch_root()
    candidate = _resolve_under_root(root, name)
    if candidate.parent != root.resolve():
        raise ValueError("Check-in must be a root-level file")
    meta = _file_meta(candidate)
    out: Dict[str, Any] = {
        "name": name,
        **meta,
    }
    if include_content and meta["exists"]:
        out["content"] = _read_text(candidate)
        out["content_type"] = "text/markdown"
    return out


def _split_markdown_rows(line: str) -> List[str]:
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return [p for p in parts]


def _parse_markdown_table(lines: Sequence[str], start_index: int) -> Tuple[List[str], List[Dict[str, str]], int]:
    header = _split_markdown_rows(lines[start_index])
    i = start_index + 1
    if i < len(lines) and lines[i].lstrip().startswith("|"):
        i += 1

    rows: List[Dict[str, str]] = []
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = _split_markdown_rows(lines[i])
        row: Dict[str, str] = {}
        for idx, col in enumerate(header):
            row[col] = cells[idx] if idx < len(cells) else ""
        rows.append(row)
        i += 1
    return header, rows, i


def parse_status_board(markdown: str) -> Dict[str, Any]:
    lines = markdown.splitlines()
    core: List[Dict[str, str]] = []
    prototypes: List[Dict[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("| Service | Role"):
            _, rows, i = _parse_markdown_table(lines, i)
            core = rows
            continue
        if line.strip().startswith("| Project / node | Role"):
            _, rows, i = _parse_markdown_table(lines, i)
            prototypes = rows
            continue
        i += 1
    return {
        "core_services": core,
        "prototypes": prototypes,
    }


_TASK_HEADER_RE = re.compile(r"^###\s+(OT-\d{4}-\d{2}-\d{2}-\d{4})\s+—\s+(.+?)\s*$")
_FIELD_RE = re.compile(r"^-\s+\*\*([^*]+)\*\*:\s*(.*)\s*$")


def parse_task_inbox(markdown: str) -> List[Dict[str, Any]]:
    lines = markdown.splitlines()
    tasks: List[Dict[str, Any]] = []
    i = 0
    while i < len(lines):
        m = _TASK_HEADER_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue

        task_id, title = m.group(1), m.group(2)
        block_lines = [lines[i]]
        i += 1
        while i < len(lines) and not _TASK_HEADER_RE.match(lines[i].strip()):
            if lines[i].strip().startswith("## Completed tasks"):
                break
            block_lines.append(lines[i])
            i += 1

        fields: Dict[str, str] = {}
        j = 0
        while j < len(block_lines):
            fm = _FIELD_RE.match(block_lines[j].strip())
            if not fm:
                j += 1
                continue
            key = fm.group(1).strip()
            value_lines: List[str] = [fm.group(2).rstrip()]
            j += 1
            while j < len(block_lines):
                next_line = block_lines[j]
                if _FIELD_RE.match(next_line.strip()):
                    break
                if _TASK_HEADER_RE.match(next_line.strip()):
                    break
                if next_line.strip().startswith("### "):
                    break
                if next_line.strip() == "":
                    value_lines.append("")
                    j += 1
                    continue
                if next_line.startswith("  ") or next_line.startswith("\t"):
                    value_lines.append(next_line.rstrip())
                    j += 1
                    continue
                break
            fields[key] = "\n".join(value_lines).strip()

        status = fields.get("Status")
        tasks.append(
            {
                "task_id": task_id,
                "title": title,
                "status": status,
                "fields": fields,
                "raw": "\n".join(block_lines).strip(),
            }
        )

    return tasks


def get_task_inbox_data() -> Dict[str, Any]:
    doc = read_doc("task_inbox", include_content=True)
    markdown = doc.get("content") if isinstance(doc.get("content"), str) else ""
    return {
        "doc": {k: v for k, v in doc.items() if k not in {"content"}},
        "tasks": parse_task_inbox(markdown),
        "raw_markdown": markdown,
    }


def get_status_board_data() -> Dict[str, Any]:
    doc = read_doc("status_board", include_content=True)
    markdown = doc.get("content") if isinstance(doc.get("content"), str) else ""
    return {
        "doc": {k: v for k, v in doc.items() if k not in {"content"}},
        "tables": parse_status_board(markdown),
        "raw_markdown": markdown,
    }


def get_test_cards_data() -> Dict[str, Any]:
    deck = read_doc("test_card_deck", include_content=True)
    items = read_doc("test_card_deck_items", include_content=True)
    return {
        "deck": deck,
        "items": items,
    }


def get_overwatch_summary() -> Dict[str, Any]:
    root = get_overwatch_root()
    docs: List[Dict[str, Any]] = []
    for d in get_static_docs():
        try:
            docs.append(read_doc(d["doc_id"], include_content=False))
        except Exception:
            abs_path = (root / d["rel_path"]).expanduser()
            docs.append({**d, **_file_meta(abs_path)})

    tasks_data = {}
    try:
        tasks_data = get_task_inbox_data()
    except Exception:
        tasks_data = {}

    tasks = tasks_data.get("tasks") if isinstance(tasks_data, dict) else None
    statuses: Dict[str, int] = {}
    if isinstance(tasks, list):
        for t in tasks:
            if not isinstance(t, dict):
                continue
            status = t.get("status") or "UNKNOWN"
            statuses[str(status)] = statuses.get(str(status), 0) + 1

    check_ins_total = 0
    try:
        if root.exists():
            check_ins_total = len(list(root.glob("CHECK_IN_*.md")))
    except Exception:
        check_ins_total = 0

    newest_check_in = None
    try:
        recent = list_check_ins(limit=1)
        if recent:
            newest_check_in = recent[0]
    except Exception:
        newest_check_in = None

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "root": str(root),
        "root_exists": root.exists(),
        "docs": {
            "total": len(docs),
            "available": len([d for d in docs if d.get("exists")]),
            "items": docs,
        },
        "tasks": {
            "total": len(tasks) if isinstance(tasks, list) else None,
            "by_status": statuses,
        },
        "check_ins": {
            "total": check_ins_total,
            "latest": newest_check_in,
        },
        "writes": get_write_capabilities(),
    }


_CHECK_IN_NAME_RE = re.compile(r"^CHECK_IN_(\d{4}-\d{2}-\d{2})_")


def _parse_task_id_date(task_id: str) -> Optional[datetime]:
    parts = (task_id or "").split("-")
    if len(parts) < 5:
        return None
    date_str = "-".join(parts[1:4])
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def get_activity_feed(limit: int = 50) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    try:
        check_ins = list_check_ins(limit=limit)
        for ci in check_ins:
            if not isinstance(ci, dict):
                continue
            ts = ci.get("modified_at")
            name = ci.get("name")
            fields: Dict[str, Any] = {}
            try:
                if isinstance(name, str) and name:
                    content = read_check_in(name, include_content=True).get("content")
                    if isinstance(content, str):
                        for line in content.splitlines():
                            fm = _FIELD_RE.match(line.strip())
                            if fm:
                                fields[fm.group(1).strip()] = fm.group(2).strip()
            except Exception:
                fields = {}

            items.append(
                {
                    "type": "check_in",
                    "ts": ts,
                    "name": name,
                    "path": ci.get("path"),
                    "exists": ci.get("exists"),
                    "tracking": fields,
                }
            )
    except Exception:
        pass

    try:
        task_inbox = get_task_inbox_data()
        tasks = task_inbox.get("tasks") if isinstance(task_inbox, dict) else None
        if isinstance(tasks, list):
            for t in tasks[:limit]:
                if not isinstance(t, dict):
                    continue
                task_id = t.get("task_id")
                dt = _parse_task_id_date(str(task_id) if task_id else "")
                ts = dt.date().isoformat() if dt else None
                items.append(
                    {
                        "type": "task",
                        "ts": ts,
                        "task_id": t.get("task_id"),
                        "title": t.get("title"),
                        "status": t.get("status"),
                    }
                )
    except Exception:
        pass

    def _sort_key(item: Dict[str, Any]) -> str:
        ts = item.get("ts")
        return str(ts or "")

    items_sorted = sorted(items, key=_sort_key, reverse=True)
    if limit and limit > 0:
        items_sorted = items_sorted[:limit]

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "items": items_sorted,
    }


_LAST_UPDATED_RE = re.compile(r"\bLast updated\b", re.IGNORECASE)
_VALIDATION_RE = re.compile(r"\b(self-test|self test|validation|runbook)\b", re.IGNORECASE)


def get_protocol_scorecards(max_files: int = 250) -> Dict[str, Any]:
    root = get_overwatch_root()
    paths: List[Path] = []
    for rel in ["ecosystem", "protocols", "nodes", "sources"]:
        d = root / rel
        if not d.exists() or not d.is_dir():
            continue
        try:
            paths.extend(list(d.rglob("*.md")))
        except Exception:
            continue

    for extra in [root / ".overMind", root / "README.md"]:
        if extra.exists():
            paths.append(extra)

    seen: set[str] = set()
    unique: List[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except Exception:
            return 0.0

    unique.sort(key=_mtime, reverse=True)
    if max_files and max_files > 0:
        unique = unique[:max_files]

    static_map = {}
    for d in get_static_docs():
        static_map[d["rel_path"]] = d

    now = datetime.utcnow()
    items: List[Dict[str, Any]] = []
    buckets: Dict[str, int] = {"fresh": 0, "recent": 0, "stale": 0, "ancient": 0}
    for p in unique:
        try:
            rel_path = str(p.resolve().relative_to(root.resolve()))
        except Exception:
            rel_path = str(p)

        meta = _file_meta(p)
        modified_at = meta.get("modified_at")
        age_days = None
        if isinstance(modified_at, str):
            try:
                dt = datetime.fromisoformat(modified_at)
                age_days = (now - dt).days
            except Exception:
                age_days = None

        freshness = "unknown"
        if isinstance(age_days, int):
            if age_days <= 7:
                freshness = "fresh"
            elif age_days <= 30:
                freshness = "recent"
            elif age_days <= 90:
                freshness = "stale"
            else:
                freshness = "ancient"
            buckets[freshness] = buckets.get(freshness, 0) + 1

        content = ""
        has_last_updated = False
        has_validation = False
        title = p.stem
        try:
            content = _read_text(p, max_bytes=200_000)
            has_last_updated = bool(_LAST_UPDATED_RE.search(content))
            has_validation = bool(_VALIDATION_RE.search(content))
            for line in content.splitlines()[:30]:
                if line.lstrip().startswith("#"):
                    title = line.lstrip("#").strip() or title
                    break
        except Exception:
            pass

        static = static_map.get(rel_path)
        doc_id = static.get("doc_id") if isinstance(static, dict) else None
        items.append(
            {
                "doc_id": doc_id,
                "title": title,
                "rel_path": rel_path,
                "exists": meta.get("exists"),
                "size_bytes": meta.get("size_bytes"),
                "modified_at": modified_at,
                "age_days": age_days,
                "freshness": freshness,
                "signals": {
                    "has_last_updated": has_last_updated,
                    "has_validation": has_validation,
                },
            }
        )

    return {
        "generated_at": now.isoformat(),
        "root": str(root),
        "counts": {
            "total": len(items),
            "fresh": buckets.get("fresh", 0),
            "recent": buckets.get("recent", 0),
            "stale": buckets.get("stale", 0),
            "ancient": buckets.get("ancient", 0),
        },
        "items": items,
    }


def search_overwatch(query: str, max_results: int = 50) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"query": query, "results": []}

    docs: List[Tuple[str, str, str]] = []
    for d in get_static_docs():
        try:
            content = read_doc(d["doc_id"], include_content=True).get("content")
        except Exception:
            continue
        text = json.dumps(content, indent=2) if not isinstance(content, str) else content
        docs.append((d["doc_id"], d["title"], text))

    for ci in list_check_ins(limit=50):
        name = ci.get("name")
        if not name:
            continue
        try:
            content = read_check_in(name, include_content=True).get("content")
        except Exception:
            continue
        if isinstance(content, str):
            docs.append((f"check_in:{name}", name, content))

    q_re = re.compile(re.escape(q), re.IGNORECASE)
    results: List[Dict[str, Any]] = []
    for doc_id, title, text in docs:
        for idx, line in enumerate(text.splitlines(), start=1):
            if not q_re.search(line):
                continue
            results.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "line": idx,
                    "text": line,
                }
            )
            if len(results) >= max_results:
                return {"query": q, "results": results}

    return {"query": q, "results": results}


def search_overwatch_tree(
    query: str,
    max_results: int = 100,
    max_files: int = 500,
    rel_path: str = "",
    max_file_bytes: int = 400_000,
    max_read_bytes: int = 200_000,
) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"query": query, "results": []}

    root = get_overwatch_root()
    start = _resolve_under_root(root, (rel_path or "").lstrip("/"))
    if not start.exists() or not start.is_dir():
        raise FileNotFoundError(f"Search root not found: {rel_path or '.'}")

    q_re = re.compile(re.escape(q), re.IGNORECASE)
    allowed_ext = {
        ".md",
        ".txt",
        ".json",
        ".yml",
        ".yaml",
        ".py",
        ".toml",
        ".ini",
        ".rtf",
    }

    results: List[Dict[str, Any]] = []
    files_scanned = 0
    files_skipped = 0
    truncated = False

    for p in start.rglob("*"):
        if files_scanned >= max_files:
            truncated = True
            break

        if not p.is_file():
            continue

        name = p.name
        if name == ".DS_Store":
            continue

        suffix = p.suffix.lower()
        if suffix and suffix not in allowed_ext:
            files_skipped += 1
            continue

        meta = _file_meta(p)
        size_bytes = meta.get("size_bytes")
        if isinstance(size_bytes, int) and size_bytes > max_file_bytes:
            files_skipped += 1
            continue

        try:
            text = _read_text(p, max_bytes=max_read_bytes)
        except Exception:
            files_skipped += 1
            continue

        files_scanned += 1
        for idx, line in enumerate(text.splitlines(), start=1):
            if not q_re.search(line):
                continue

            try:
                rel_found = str(p.resolve().relative_to(root.resolve()))
            except Exception:
                rel_found = str(p)

            results.append(
                {
                    "rel_path": rel_found,
                    "path": str(p),
                    "line": idx,
                    "text": line,
                    "modified_at": meta.get("modified_at"),
                    "size_bytes": size_bytes,
                }
            )
            if len(results) >= max_results:
                return {
                    "query": q,
                    "root": str(root),
                    "rel_path": str(rel_path or ""),
                    "results": results,
                    "truncated": True,
                    "files_scanned": files_scanned,
                    "files_skipped": files_skipped,
                    "max_files": max_files,
                }

    return {
        "query": q,
        "root": str(root),
        "rel_path": str(rel_path or ""),
        "results": results,
        "truncated": bool(truncated),
        "files_scanned": files_scanned,
        "files_skipped": files_skipped,
        "max_files": max_files,
    }


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name)
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def overwatch_writes_enabled() -> bool:
    return _env_truthy("HAPA_OVERWATCH_ENABLE_WRITES") or _env_truthy("HAPA_OVERWATCH_ALLOW_WRITES")


def task_inbox_writes_enabled() -> bool:
    if _env_truthy("HAPA_OVERWATCH_ENABLE_TASK_INBOX_WRITES"):
        return True
    if _env_truthy("HAPA_OVERWATCH_DISABLE_TASK_INBOX_WRITES"):
        return False
    return overwatch_writes_enabled()


def check_in_writes_enabled() -> bool:
    if _env_truthy("HAPA_OVERWATCH_ENABLE_CHECKIN_WRITES"):
        return True
    if _env_truthy("HAPA_OVERWATCH_DISABLE_CHECKIN_WRITES"):
        return False
    return overwatch_writes_enabled()


def artifact_writes_enabled() -> bool:
    if _env_truthy("HAPA_OVERWATCH_ENABLE_ARTIFACT_WRITES"):
        return True
    if _env_truthy("HAPA_OVERWATCH_DISABLE_ARTIFACT_WRITES"):
        return False
    return overwatch_writes_enabled()


def get_write_capabilities() -> Dict[str, Any]:
    return {
        "enabled": overwatch_writes_enabled(),
        "task_inbox": task_inbox_writes_enabled(),
        "check_ins": check_in_writes_enabled(),
        "artifacts": artifact_writes_enabled(),
        "env": {
            "enable_writes": "HAPA_OVERWATCH_ENABLE_WRITES",
            "enable_task_inbox_writes": "HAPA_OVERWATCH_ENABLE_TASK_INBOX_WRITES",
            "enable_checkin_writes": "HAPA_OVERWATCH_ENABLE_CHECKIN_WRITES",
            "enable_artifact_writes": "HAPA_OVERWATCH_ENABLE_ARTIFACT_WRITES",
        },
    }


_TASK_ID_RE = re.compile(r"\bOT-(\d{4}-\d{2}-\d{2})-(\d{4})\b")


def _next_task_id(markdown: str, date_str: str) -> str:
    max_n = 0
    for m in _TASK_ID_RE.finditer(markdown):
        if m.group(1) != date_str:
            continue
        try:
            n = int(m.group(2))
        except ValueError:
            continue
        max_n = max(max_n, n)
    return f"OT-{date_str}-{max_n + 1:04d}"


def _clean_one_line(value: str) -> str:
    return " ".join((value or "").strip().splitlines()).strip()


def _sanitize_topic_slug(value: str) -> str:
    raw = (value or "").strip()
    raw = re.sub(r"\.[a-zA-Z0-9]+$", "", raw)
    raw = raw.replace("-", "_")
    raw = re.sub(r"[^A-Za-z0-9_\s]", "", raw)
    raw = re.sub(r"\s+", "_", raw)
    raw = raw.strip("_")
    if not raw:
        return "UNTITLED"
    return raw.upper()


def create_task_inbox_entry(
    title: str,
    target_agent: str = "ANY",
    requested_by: str = "",
    timebox: str = "",
    goal: str = "",
    repo: str = "",
    files: str = "n/a",
    definition_of_done: str = "",
    validation: str = "n/a",
    notes: Optional[str] = None,
    task_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if not task_inbox_writes_enabled():
        raise PermissionError("Overwatch task inbox writes are disabled")

    title_clean = _clean_one_line(title)
    if not title_clean:
        raise ValueError("title is required")

    root = get_overwatch_root()
    inbox_path = _resolve_under_root(root, "ecosystem/TASK_INBOX.md")
    if not inbox_path.exists():
        raise FileNotFoundError(f"Task inbox not found: {inbox_path}")

    markdown = _read_text(inbox_path)
    date_str = datetime.now().strftime("%Y-%m-%d")
    resolved_task_id = task_id or _next_task_id(markdown, date_str)

    entry_lines: List[str] = []
    entry_lines.append(f"### {resolved_task_id} — {title_clean}")
    entry_lines.append("")
    entry_lines.append(f"- **Target agent:** {_clean_one_line(target_agent) or 'ANY'}")
    entry_lines.append("- **Status:** OPEN")
    entry_lines.append(f"- **Requested by:** {_clean_one_line(requested_by) or '<agent_id>'}")
    entry_lines.append(f"- **Timebox:** {_clean_one_line(timebox) or '<e.g. 30 minutes>'}")
    entry_lines.append(f"- **Goal:** {_clean_one_line(goal) or '<one sentence>'}")
    entry_lines.append(f"- **Repo:** {_clean_one_line(repo) or '<absolute path>'}")
    entry_lines.append(f"- **Files:** {_clean_one_line(files) or 'n/a'}")
    entry_lines.append(f"- **Definition of done:** {_clean_one_line(definition_of_done) or '<what “done” means>'}")
    entry_lines.append(f"- **Validation:** {_clean_one_line(validation) or 'n/a'}")
    if notes is not None:
        entry_lines.append(f"- **Notes:** {_clean_one_line(notes) or '<optional>'}")
    entry_lines.append("")
    entry_markdown = "\n".join(entry_lines).strip()

    lines = markdown.splitlines()
    out: List[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.strip() == "## Active tasks":
            out.append("")
            out.extend(entry_lines)
            inserted = True

    if not inserted:
        raise ValueError("Could not locate '## Active tasks' section")

    updated_markdown = "\n".join(out).rstrip() + "\n"
    if not dry_run:
        inbox_path.write_text(updated_markdown, encoding="utf-8")

    return {
        "task_id": resolved_task_id,
        "title": title_clean,
        "path": str(inbox_path),
        "inserted": True,
        "created": not dry_run,
        "dry_run": dry_run,
        "entry_markdown": entry_markdown,
    }


def create_check_in_stub(topic: str, dry_run: bool = False) -> Dict[str, Any]:
    if not check_in_writes_enabled():
        raise PermissionError("Overwatch check-in writes are disabled")

    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = _sanitize_topic_slug(topic)
    name = f"CHECK_IN_{date_str}_{slug}.md"

    root = get_overwatch_root()
    path = _resolve_under_root(root, name)
    if path.parent != root.resolve():
        raise ValueError("Check-in must be created at Overwatch root")
    if path.exists():
        raise FileExistsError(f"Check-in already exists: {path}")

    local_now = datetime.now().astimezone()
    utc_now = datetime.utcnow()

    content = "\n".join(
        [
            f"# Check In — {date_str} — {slug}",
            "",
            f"**Date (local):** {local_now.strftime('%Y-%m-%d %H:%M %Z')}",
            f"**Date (UTC):** {utc_now.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Tracking",
            "",
            "- **Agent:** <name>",
            "- **LLM Model:** <e.g. Cascade / none>",
            "- **Task:** <what you set out to do>",
            "- **Environment:** <OS + hardware + key runtimes>",
            "- **Location:** <paths, hosts, ports, node IDs>",
            "",
            "## Repo State",
            "",
            "- **Repo:** <repo_root>",
            "  - `branch`: <...>",
            "  - `commit`: <...>",
            "  - `dirty_files`: <N>",
            "  - `remote_origin`: <... or n/a>",
            "",
            "## Status",
            "",
            "- **What works now:**",
            "- **What is broken / unknown:**",
            "- **Next actions:**",
            "",
            "## Executive Summary",
            "",
            "- ",
            "",
            "## Interfaces / Contracts (authoritative)",
            "",
            "- ",
            "",
            "## Validation Runbook (copy/paste)",
            "",
            "- **Commands run:**",
            "- **Expected signals:**",
            "- **Observed signals:**",
            "",
            "## Evidence / Validation",
            "",
            "- **Artifacts produced:** <owner + absolute path(s) under /hapa_artifacts>",
            "",
            "## Source pointers",
            "",
            "- ",
            "",
        ]
    )

    if dry_run:
        meta = _file_meta(path)
        return {
            "name": name,
            **meta,
            "created": False,
            "dry_run": True,
            "content": content,
            "content_type": "text/markdown",
        }

    path.write_text(content, encoding="utf-8")
    meta = _file_meta(path)
    return {
        "name": name,
        **meta,
        "created": True,
        "dry_run": False,
    }


def write_artifact(rel_path: str, content: Any, dry_run: bool = False) -> Dict[str, Any]:
    if not artifact_writes_enabled():
        raise PermissionError("Artifact writes are disabled")

    base = (get_owner_root() / "overwatch_bridge").resolve()
    base.mkdir(parents=True, exist_ok=True)

    candidate = (base / rel_path).resolve()
    if candidate == base:
        raise ValueError("Artifact path must not be the artifact root")
    if base not in candidate.parents:
        raise ValueError("Artifact path escapes artifact root")

    candidate.parent.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        if isinstance(content, (dict, list)):
            candidate.write_text(json.dumps(content, indent=2), encoding="utf-8")
        else:
            candidate.write_text(str(content), encoding="utf-8")

    meta = _file_meta(candidate)
    return {
        "path": str(candidate),
        **meta,
        "created": not dry_run,
        "dry_run": dry_run,
    }

