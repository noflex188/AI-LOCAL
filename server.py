import asyncio
import json
import os
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import ollama as _ollama

from agent import Agent
import memory as mem
from context import get_context
from confirmation import confirm_manager
import workspace as ws
import rag
import notes_store

SUGGESTED_MODELS = ["gemma4:26b", "gemma4:e4b"]
CODE_MODELS      = ["qwen2.5-coder:32b", "qwen2.5-coder:14b", "qwen2.5-coder:7b", "qwen2.5-coder:3b"]

_BASE = os.path.dirname(os.path.abspath(__file__))

app   = FastAPI()
agent = Agent()
_stop_event = threading.Event()


@app.on_event("startup")
def _restore_workspace():
    """Restaure le workspace actif au redémarrage du serveur."""
    last = ws.load_state()
    if not last or not os.path.isdir(last):
        return
    try:
        info = ws.set_workspace(last)
        linked = mem.list_conversations_for_workspace(info["path"])
        if linked:
            agent.switch_conversation(linked[0]["id"])
        else:
            agent.new_conversation(title=f"Projet — {info['name']}", workspace=info["path"])
        agent.refresh_system_prompt()
    except Exception:
        ws.clear_state()

app.mount("/static", StaticFiles(directory=os.path.join(_BASE, "static")), name="static")


# ── Page ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(_BASE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


# ── Chat ──────────────────────────────────────────────────────────────────────

class Attachment(BaseModel):
    name: str
    kind: str      # "text" | "image"
    content: str   # texte brut ou base64 (data:image/...;base64,...)

class ChatRequest(BaseModel):
    message: str
    attachments: list[Attachment] = []

@app.post("/chat")
async def chat(body: ChatRequest):
    _stop_event.clear()
    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    def produce():
        """Tourne dans un thread séparé, pousse chaque event dans la queue."""
        try:
            for event in agent.stream_chat(body.message, body.attachments):
                if _stop_event.is_set():
                    loop.call_soon_threadsafe(q.put_nowait, {"type": "stopped"})
                    break
                loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, {"type": "error", "message": str(e)})
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)   # sentinel

    async def generate():
        threading.Thread(target=produce, daemon=True).start()
        try:
            while True:
                event = await q.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/chat/stop")
async def chat_stop():
    _stop_event.set()
    return JSONResponse({"ok": True})

# ── Update check ─────────────────────────────────────────────────────────────

@app.get("/check-update")
def check_update():
    """Compare le HEAD local avec le HEAD distant sur GitHub."""
    import subprocess
    try:
        subprocess.run(
            ["git", "fetch", "--quiet"],
            cwd=_BASE, capture_output=True, timeout=10,
        )
        local = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_BASE, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            cwd=_BASE, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        behind = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..origin/main"],
            cwd=_BASE, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return JSONResponse({
            "update_available": local != remote,
            "commits_behind": int(behind) if behind.isdigit() else 0,
        })
    except Exception as e:
        return JSONResponse({"update_available": False, "error": str(e)})


@app.post("/update")
def do_update():
    """Exécute git pull pour mettre à jour l'application."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=_BASE, capture_output=True, text=True, timeout=30,
        )
        return JSONResponse({
            "ok": result.returncode == 0,
            "output": (result.stdout + result.stderr).strip(),
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/history")
def history():
    return JSONResponse({
        "messages":    agent.get_history(),
        "current_conv": agent.current_conv,
    })


# ── Conversations ─────────────────────────────────────────────────────────────

@app.get("/conversations")
def list_conversations():
    return JSONResponse(mem.list_conversations())

class NewConvRequest(BaseModel):
    workspace: str | None = None

@app.post("/conversations")
def new_conversation(body: NewConvRequest | None = None):
    workspace = body.workspace if body else None
    conv = agent.new_conversation(workspace=workspace)
    return JSONResponse(conv)

@app.post("/conversations/{conv_id}/activate")
def activate_conversation(conv_id: str):
    messages = agent.switch_conversation(conv_id)
    return JSONResponse({"conv": agent.current_conv, "messages": messages})

@app.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    current = agent.delete_conversation(conv_id)
    return JSONResponse({"current_conv": current, "messages": agent.get_history()})

class RenameRequest(BaseModel):
    title: str

@app.patch("/conversations/{conv_id}")
def rename_conversation(conv_id: str, body: RenameRequest):
    agent.rename_conversation(conv_id, body.title)
    return JSONResponse({"ok": True})


# ── Confirmations ────────────────────────────────────────────────────────────

class ConfirmBody(BaseModel):
    approved: bool

@app.post("/confirm/{cid}")
def confirm(cid: str, body: ConfirmBody):
    ok = confirm_manager.resolve(cid, body.approved)
    return JSONResponse({"ok": ok})


# ── Memory ────────────────────────────────────────────────────────────────────

@app.get("/memory")
def get_memory():
    notes = mem.load_notes()
    lines = [l.strip() for l in notes.splitlines() if l.strip()]
    return JSONResponse({"notes": lines})

@app.delete("/memory")
def clear_memory():
    agent.reset_memory()
    return JSONResponse({"ok": True})


# ── Context ───────────────────────────────────────────────────────────────────

@app.get("/context")
def context():
    data = get_context()
    data["model"] = agent.model
    return JSONResponse(data)


# ── Workspace & RAG ──────────────────────────────────────────────────────────

class WorkspaceRequest(BaseModel):
    path: str

@app.get("/workspace/browse")
def workspace_browse():
    """Ouvre le sélecteur de dossier Windows natif via PowerShell."""
    import subprocess
    ps = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description='Choisir un dossier de projet';"
        "$d.UseDescriptionForTitle=$true;"
        "$d.ShowNewFolderButton=$true;"
        "if($d.ShowDialog()-eq'OK'){Write-Output $d.SelectedPath}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=120,
        )
        path = result.stdout.decode("utf-8", errors="replace").strip() or None
        return JSONResponse({"path": path})
    except Exception as e:
        return JSONResponse({"path": None, "error": str(e)})

@app.post("/workspace/set")
def workspace_set(body: WorkspaceRequest):
    try:
        info = ws.set_workspace(body.path)
        ws.save_state(info["path"])

        # Trouver la dernière conversation liée à ce workspace, ou en créer une
        linked = mem.list_conversations_for_workspace(info["path"])
        if linked:
            messages = agent.switch_conversation(linked[0]["id"])
        else:
            agent.new_conversation(
                title=f"Projet — {info['name']}",
                workspace=info["path"],
            )
            messages = []

        agent.refresh_system_prompt()

        return JSONResponse({
            "ok":      True,
            "path":    info["path"],
            "name":    info["name"],
            "indexed": rag.is_indexed(info["path"]),
            "count":   rag.index_count(info["path"]),
            "conv":    agent.current_conv,
            "messages": messages if isinstance(messages, list) else [],
        })
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

@app.post("/workspace/close")
def workspace_close():
    ws.clear_state()
    return JSONResponse({"ok": True})


@app.get("/workspace/tree")
def workspace_tree():
    return JSONResponse(ws.get_tree())

@app.get("/workspace/file")
def workspace_file(path: str):
    return JSONResponse(ws.read_file_preview(path))

@app.get("/workspace/status")
def workspace_status():
    wpath = ws.get_workspace()
    if not wpath:
        return JSONResponse({"active": False})
    linked = mem.list_conversations_for_workspace(wpath)
    return JSONResponse({
        "active":   True,
        "path":     wpath,
        "name":     os.path.basename(wpath),
        "indexed":  rag.is_indexed(wpath),
        "count":    rag.index_count(wpath),
        "conv":     agent.current_conv,
        "convs":    linked,
        "messages": agent.get_history(),
    })

@app.post("/workspace/index")
async def workspace_index():
    wpath = ws.get_workspace()
    if not wpath:
        return JSONResponse({"error": "Aucun workspace ouvert"}, status_code=400)

    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    def produce():
        try:
            for event in rag.index_workspace(wpath):
                loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, {"status": "error", "msg": str(e)})
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    async def generate():
        threading.Thread(target=produce, daemon=True).start()
        while True:
            event = await q.get()
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Correction de transcription ───────────────────────────────────────────────

class NoteRequest(BaseModel):
    text: str

# ── Sessions de notes vocales ─────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    title: str | None = None

class SessionRenameRequest(BaseModel):
    title: str

@app.get("/voice-sessions")
def get_sessions():
    return JSONResponse(notes_store.list_sessions())

@app.post("/voice-sessions")
def create_session(body: SessionCreateRequest | None = None):
    title = body.title if body else None
    return JSONResponse(notes_store.create_session(title))

@app.delete("/voice-sessions/{session_id}")
def delete_session(session_id: str):
    return JSONResponse({"ok": notes_store.delete_session(session_id)})

@app.patch("/voice-sessions/{session_id}")
def rename_session(session_id: str, body: SessionRenameRequest):
    return JSONResponse({"ok": notes_store.rename_session(session_id, body.title)})

@app.post("/voice-sessions/{session_id}/notes")
def add_note(session_id: str, body: NoteRequest):
    note = notes_store.add_note(session_id, body.text)
    if note is None:
        return JSONResponse({"error": "Session introuvable"}, status_code=404)
    return JSONResponse(note)

@app.delete("/voice-sessions/{session_id}/notes/{note_id}")
def delete_note(session_id: str, note_id: str):
    return JSONResponse({"ok": notes_store.delete_note(session_id, note_id)})

@app.post("/voice-sessions/{session_id}/report")
def generate_report(session_id: str):
    try:
        sessions = notes_store.list_sessions()
        session  = next((s for s in sessions if s["id"] == session_id), None)
        if not session:
            return JSONResponse({"error": "Session introuvable"}, status_code=404)
        notes = session.get("notes", [])
        if not notes:
            return JSONResponse({"error": "Aucune note dans cette session"}, status_code=400)
        lines = "\n".join(
            f"- [{n['created_at'][11:16]}] {n['text']}"
            for n in reversed(notes)
        )
        resp = _ollama.chat(
            model=agent.model,
            messages=[{
                "role": "user",
                "content": (
                    f"Titre de la session : {session['title']}\n\n"
                    f"Notes :\n{lines}\n\n"
                    "Génère un rapport structuré en français avec : "
                    "un titre, un résumé, les points clés "
                    "et les actions à faire. Sois concis et pratique. "
                    "Réponds en texte brut uniquement, sans markdown, "
                    "sans astérisques, sans dièses, sans mise en forme spéciale."
                ),
            }],
        )
        try:
            content = resp.message.content
        except AttributeError:
            content = resp["message"]["content"]
        notes_store.save_report(session_id, content)
        return JSONResponse({"report": content})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Modèles ───────────────────────────────────────────────────────────────────

@app.get("/models")
def get_models():
    try:
        installed_list = [m.model for m in _ollama.list().models]
        installed_set  = set(installed_list)
    except Exception:
        installed_list, installed_set = [], set()

    all_suggested = SUGGESTED_MODELS + CODE_MODELS
    result = [{"id": m, "installed": True, "code_only": m in CODE_MODELS} for m in installed_list]
    for s in all_suggested:
        if s not in installed_set:
            result.append({"id": s, "installed": False, "code_only": s in CODE_MODELS})
    return JSONResponse(result)

class ModelSelectRequest(BaseModel):
    model: str

@app.post("/models/select")
def select_model(body: ModelSelectRequest):
    agent.set_model(body.model)
    return JSONResponse({"ok": True, "model": body.model})

@app.post("/models/pull")
def pull_model(body: ModelSelectRequest):

    def generate():
        try:
            for chunk in _ollama.pull(body.model, stream=True):
                data: dict = {"status": chunk.status}
                if getattr(chunk, "completed", None):
                    data["completed"] = chunk.completed
                if getattr(chunk, "total", None):
                    data["total"] = chunk.total
                yield f"data: {json.dumps(data)}\n\n"
            yield f"data: {json.dumps({'status': 'done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
