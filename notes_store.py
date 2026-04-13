"""
Sessions de notes vocales — memory/voice_sessions.json
Chaque session est un rapport indépendant avec ses propres notes.
"""
import json
import os
import uuid
from datetime import datetime

_BASE         = os.path.dirname(os.path.abspath(__file__))
SESSIONS_FILE = os.path.join(_BASE, "memory", "voice_sessions.json")


def _load() -> list:
    if not os.path.exists(SESSIONS_FILE):
        return []
    with open(SESSIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(sessions: list):
    os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
    with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


# ── Sessions ──────────────────────────────────────────────────────────────────

def list_sessions() -> list:
    return _load()


def create_session(title: str | None = None) -> dict:
    now = datetime.now()
    session = {
        "id":         str(uuid.uuid4())[:8],
        "title":      (title.strip()[:80] if title else None) or f"Rapport — {now.strftime('%d/%m %H:%M')}",
        "created_at": now.isoformat(),
        "notes":      [],
        "report":     None,
    }
    sessions = _load()
    sessions.insert(0, session)
    _save(sessions)
    return session


def delete_session(session_id: str) -> bool:
    sessions = _load()
    new = [s for s in sessions if s["id"] != session_id]
    if len(new) == len(sessions):
        return False
    _save(new)
    return True


def rename_session(session_id: str, title: str) -> bool:
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            s["title"] = title.strip()[:80]
            _save(sessions)
            return True
    return False


# ── Notes dans une session ────────────────────────────────────────────────────

def add_note(session_id: str, text: str) -> dict | None:
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            note = {
                "id":         str(uuid.uuid4())[:8],
                "text":       text.strip(),
                "created_at": datetime.now().isoformat(),
            }
            s["notes"].insert(0, note)
            _save(sessions)
            return note
    return None


def delete_note(session_id: str, note_id: str) -> bool:
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            before = len(s["notes"])
            s["notes"] = [n for n in s["notes"] if n["id"] != note_id]
            if len(s["notes"]) < before:
                _save(sessions)
                return True
    return False


# ── Rapport généré ────────────────────────────────────────────────────────────

def save_report(session_id: str, report: str) -> bool:
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            s["report"] = report
            _save(sessions)
            return True
    return False
