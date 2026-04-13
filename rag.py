"""
RAG local — embeddings via Ollama (nomic-embed-text), similarité cosinus pure Python.
Stockage JSON dans memory/rag/{workspace_hash}/
"""
import hashlib
import json
import os
from pathlib import Path

import ollama

EMBED_MODEL = "nomic-embed-text"
RAG_BASE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory", "rag")
CHUNK_SIZE  = 1200
OVERLAP     = 150

TEXT_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
    ".md", ".txt", ".yaml", ".yml", ".xml", ".sh", ".bat", ".c",
    ".cpp", ".h", ".java", ".rs", ".go", ".php", ".rb", ".sql",
    ".toml", ".ini", ".env", ".vue", ".svelte", ".astro",
}
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", ".next", "target", "coverage",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rag_dir(workspace: str) -> str:
    h = hashlib.md5(workspace.encode()).hexdigest()[:8]
    d = os.path.join(RAG_BASE, h)
    os.makedirs(d, exist_ok=True)
    return d

def _file_hash(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""

def _chunks(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text]
    parts, start = [], 0
    while start < len(text):
        parts.append(text[start:start + CHUNK_SIZE])
        start += CHUNK_SIZE - OVERLAP
    return parts

def _embed(text: str) -> list[float]:
    return ollama.embeddings(model=EMBED_MODEL, prompt=text[:4000])["embedding"]

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-9)

def _load(path: str) -> dict:
    return json.loads(open(path).read()) if os.path.exists(path) else {}

def _save(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ── Public API ────────────────────────────────────────────────────────────────

def is_indexed(workspace: str) -> bool:
    return os.path.exists(os.path.join(_rag_dir(workspace), "chunks.json"))

def index_count(workspace: str) -> int:
    p = os.path.join(_rag_dir(workspace), "meta.json")
    return len(_load(p))


def index_workspace(workspace: str):
    """
    Générateur — yield des événements de progression pendant l'indexation.
    {"status": "file",  "path": rel}
    {"status": "error", "path": rel, "msg": str}
    {"status": "done",  "indexed": n, "skipped": n, "total": n}
    """
    rag_dir     = _rag_dir(workspace)
    meta_path   = os.path.join(rag_dir, "meta.json")
    chunks_path = os.path.join(rag_dir, "chunks.json")

    meta   = _load(meta_path)
    chunks = _load(chunks_path)
    indexed = skipped = 0

    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if Path(fname).suffix.lower() not in TEXT_EXTS:
                continue
            fpath = os.path.join(root, fname)
            rel   = os.path.relpath(fpath, workspace)
            fhash = _file_hash(fpath)

            if rel in meta and meta[rel].get("hash") == fhash:
                skipped += 1
                continue
            try:
                text = open(fpath, encoding="utf-8", errors="ignore").read().strip()
                if not text:
                    continue
                # Supprimer les anciens chunks de ce fichier
                chunks = {k: v for k, v in chunks.items() if v.get("file") != rel}
                for i, chunk in enumerate(_chunks(text)):
                    chunks[f"{rel}::{i}"] = {"file": rel, "text": chunk, "emb": _embed(chunk)}
                meta[rel] = {"hash": fhash}
                indexed += 1
                yield {"status": "file", "path": rel}
                # Persistance après chaque fichier (résistant aux crashes)
                _save(meta_path, meta)
                _save(chunks_path, chunks)
            except Exception as e:
                yield {"status": "error", "path": rel, "msg": str(e)}

    yield {"status": "done", "indexed": indexed, "skipped": skipped, "total": len(meta)}


def search(workspace: str, query: str, top_k: int = 6) -> list[dict]:
    chunks_path = os.path.join(_rag_dir(workspace), "chunks.json")
    if not os.path.exists(chunks_path):
        return []
    chunks = _load(chunks_path)
    if not chunks:
        return []

    q_emb  = _embed(query)
    scores = [(_cosine(q_emb, c["emb"]), c["file"], c["text"]) for c in chunks.values()]
    scores.sort(reverse=True)

    seen, results = set(), []
    for score, fpath, text in scores:
        if score < 0.25:
            break
        key = fpath + text[:40]
        if key in seen:
            continue
        seen.add(key)
        results.append({"file": fpath, "score": round(score, 3), "content": text[:600]})
        if len(results) >= top_k:
            break
    return results
