"""
Mémoire persistante — deux niveaux :
  memory/notes.md                   — notes long-terme (shared)
  memory/conversations/index.json   — liste des conversations
  memory/conversations/{id}.json    — messages de chaque conversation
"""
import json
import os
import uuid
from datetime import datetime

_BASE      = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(_BASE, "memory")
NOTES_FILE = os.path.join(MEMORY_DIR, "notes.md")
CONV_DIR   = os.path.join(MEMORY_DIR, "conversations")
CONV_INDEX = os.path.join(CONV_DIR, "index.json")
MAX_SAVED  = 100


def _ensure(path):
    os.makedirs(path, exist_ok=True)


# ── Notes long-terme ──────────────────────────────────────────────────────────

def load_notes() -> str:
    if not os.path.exists(NOTES_FILE):
        return ""
    with open(NOTES_FILE, encoding="utf-8") as f:
        return f.read().strip()


def append_note(note: str):
    _ensure(MEMORY_DIR)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(f"- [{ts}] {note.strip()}\n")


def clear_notes():
    if os.path.exists(NOTES_FILE):
        os.remove(NOTES_FILE)


# ── Conversations ─────────────────────────────────────────────────────────────

def list_conversations() -> list[dict]:
    if not os.path.exists(CONV_INDEX):
        return []
    with open(CONV_INDEX, encoding="utf-8") as f:
        return json.load(f)


def _save_index(convs: list[dict]):
    _ensure(CONV_DIR)
    with open(CONV_INDEX, "w", encoding="utf-8") as f:
        json.dump(convs, f, ensure_ascii=False, indent=2)


def create_conversation(title: str = "Nouvelle conversation", workspace: str | None = None) -> dict:
    _ensure(CONV_DIR)
    conv = {
        "id":         str(uuid.uuid4())[:8],
        "title":      title,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    if workspace:
        conv["workspace"] = workspace
    convs = list_conversations()
    convs.insert(0, conv)
    _save_index(convs)
    return conv


def list_conversations_for_workspace(workspace_path: str) -> list[dict]:
    return [c for c in list_conversations() if c.get("workspace") == workspace_path]


def save_conversation(conv_id: str, messages: list[dict]):
    """Save messages and auto-update title from first user message."""
    _ensure(CONV_DIR)
    saveable = [
        m for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ][-MAX_SAVED:]
    with open(os.path.join(CONV_DIR, f"{conv_id}.json"), "w", encoding="utf-8") as f:
        json.dump(saveable, f, ensure_ascii=False, indent=2)
    convs = list_conversations()
    for c in convs:
        if c["id"] == conv_id:
            c["updated_at"] = datetime.now().isoformat()
            if c["title"] == "Nouvelle conversation" and saveable:
                first = next((m["content"] for m in saveable if m["role"] == "user"), None)
                if first:
                    t = first.strip().replace("\n", " ")
                    c["title"] = t[:50] + ("…" if len(t) > 50 else "")
            break
    _save_index(convs)


def load_conversation(conv_id: str) -> list[dict]:
    path = os.path.join(CONV_DIR, f"{conv_id}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def delete_conversation(conv_id: str):
    path = os.path.join(CONV_DIR, f"{conv_id}.json")
    if os.path.exists(path):
        os.remove(path)
    _save_index([c for c in list_conversations() if c["id"] != conv_id])


def update_title(conv_id: str, title: str):
    convs = list_conversations()
    for c in convs:
        if c["id"] == conv_id:
            c["title"] = title[:60]
            break
    _save_index(convs)


# ── Migration depuis l'ancien history.json ────────────────────────────────────

def migrate_if_needed() -> str | None:
    legacy = os.path.join(MEMORY_DIR, "history.json")
    if not os.path.exists(legacy):
        return None
    if list_conversations():
        os.remove(legacy)
        return None
    with open(legacy, encoding="utf-8") as f:
        messages = json.load(f)
    os.remove(legacy)
    if not messages:
        return None
    conv = create_conversation("Conversation importée")
    save_conversation(conv["id"], messages)
    return conv["id"]
