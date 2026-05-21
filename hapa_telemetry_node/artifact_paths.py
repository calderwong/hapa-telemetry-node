import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return Path.cwd()


def _safe_mkdir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def get_artifact_root() -> Path:
    root = (
        os.environ.get("HAPA_ARTIFACT_ROOT")
        or os.environ.get("HAPA_ARTIFACT_VAULT_ROOT")
        or "/hapa_artifacts"
    )
    return Path(root).expanduser()


def get_artifact_owner() -> str:
    return (
        os.environ.get("HAPA_TELEMETRY_ARTIFACT_OWNER")
        or os.environ.get("HAPA_ARTIFACT_OWNER")
        or "hapa-telemetry-node"
    )


def get_owner_root() -> Path:
    root = get_artifact_root() / get_artifact_owner()
    if _safe_mkdir(root):
        return root

    fallback = _repo_root() / "artifacts" / get_artifact_owner()
    _safe_mkdir(fallback)
    return fallback


def _dir(rel: str) -> Path:
    p = get_owner_root() / rel
    _safe_mkdir(p)
    return p


def get_data_dir() -> Path:
    return _dir("data")


def get_runtime_dir() -> Path:
    return _dir("runtime")


def get_runs_dir() -> Path:
    return _dir("runs")


def get_logs_dir() -> Path:
    return _dir("logs")


def _expand_path(p: str) -> Path:
    path = Path(p).expanduser()
    if path.parent:
        _safe_mkdir(path.parent)
    return path


def get_db_path() -> Path:
    override = os.environ.get("HAPA_TELEMETRY_DB_PATH")
    if override:
        return _expand_path(override)
    return get_data_dir() / "telemetry.db"


def get_runtime_file() -> Path:
    override = os.environ.get("HAPA_TELEMETRY_RUNTIME_PATH")
    if override:
        return _expand_path(override)
    return get_runtime_dir() / "telemetry_runtime.json"


def get_self_test_results_path() -> Path:
    override = os.environ.get("HAPA_TELEMETRY_SELF_TEST_OUT")
    if override:
        return _expand_path(override)

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = get_runs_dir() / "self_test"
    _safe_mkdir(out_dir)
    return out_dir / f"test_results__{ts}.json"
