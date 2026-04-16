"""
Gestion du workspace de code (dossier de projet actif).
"""
import os
from pathlib import Path

IGNORE_DIRS  = {'.git', '__pycache__', 'node_modules', 'venv', '.venv',
                'dist', 'build', '.next', '.nuxt', '.cache', 'target',
                '.idea', '.vscode', 'coverage', '.pytest_cache', '.mypy_cache'}
IGNORE_FILES = {'.DS_Store', 'Thumbs.db', '.gitkeep'}

_workspace: str | None = None
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "state.json")


def _read_state() -> dict:
    import json
    if not os.path.exists(_STATE_FILE):
        return {}
    try:
        with open(_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(data: dict):
    import json
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def save_state(path: str):
    state = _read_state()
    state["workspace"] = path
    _write_state(state)


def load_state() -> str | None:
    return _read_state().get("workspace")


def save_model(model: str):
    state = _read_state()
    state["model"] = model
    _write_state(state)


def load_model() -> str | None:
    return _read_state().get("model")


def clear_state():
    if os.path.exists(_STATE_FILE):
        os.remove(_STATE_FILE)


def set_workspace(path: str) -> dict:
    global _workspace
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise ValueError(f"Dossier introuvable : {path}")
    _workspace = path
    os.chdir(path)
    return {"path": path, "name": os.path.basename(path)}


def get_workspace() -> str | None:
    return _workspace


def get_tree(max_depth: int = 5) -> list:
    if not _workspace:
        return []
    return _scan(_workspace, _workspace, 0, max_depth)


def _scan(root: str, base: str, depth: int, max_depth: int) -> list:
    if depth > max_depth:
        return []
    try:
        items = sorted(os.scandir(root), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return []
    entries = []
    for item in items:
        if item.name in IGNORE_FILES or item.name.startswith('.'):
            continue
        if item.is_dir():
            if item.name in IGNORE_DIRS:
                continue
            entries.append({
                "name":     item.name,
                "path":     item.path,
                "rel":      os.path.relpath(item.path, base),
                "type":     "dir",
                "children": _scan(item.path, base, depth + 1, max_depth),
            })
        else:
            entries.append({
                "name": item.name,
                "path": item.path,
                "rel":  os.path.relpath(item.path, base),
                "type": "file",
                "ext":  Path(item.name).suffix.lstrip('.').lower(),
                "size": item.stat().st_size,
            })
    return entries


def read_file_preview(path: str, max_bytes: int = 60_000) -> dict:
    try:
        size = os.path.getsize(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(max_bytes)
        return {
            "content":   content,
            "truncated": size > max_bytes,
            "size":      size,
            "ext":       Path(path).suffix.lstrip('.').lower(),
        }
    except Exception as e:
        return {"error": str(e)}
