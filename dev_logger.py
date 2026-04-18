"""
Logger de développement — pour analyser le comportement de l'agent de code.

Format : JSON Lines (un objet JSON par ligne) dans logs/agent_YYYY-MM-DD.jsonl
NON poussé en git (logs/ est dans .gitignore).

Usage :
    from dev_logger import log
    log("code_agent.start", {"model": "qwen2.5-coder:14b", "workspace": "/path"})

Analyser les logs :
    python dev_logger.py [--date 2024-01-15] [--event code_agent.action]
"""
import json
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

_BASE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_BASE, "logs")

# ID de session unique (timestamp au démarrage du process)
SESSION_ID = datetime.now().strftime("%Y%m%d_%H%M%S")

# Fichier de log courant (ouvert en lazy)
_log_file = None
_log_path = None


def _open_log():
    global _log_file, _log_path
    if _log_file is None:
        os.makedirs(LOG_DIR, exist_ok=True)
        date_str = date.today().isoformat()
        _log_path = os.path.join(LOG_DIR, f"agent_{date_str}.jsonl")
        _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    return _log_file


# ── API principale ─────────────────────────────────────────────────────────────

def log(event: str, data: dict = None, level: str = "info"):
    """
    Écrit un event structuré dans le fichier de log.

    Paramètres :
        event : identifiant de l'événement, ex: "code_agent.action_result"
        data  : dict avec les données à logger
        level : "info", "warn", "error"
    """
    entry = {
        "ts":      datetime.now().isoformat(timespec="milliseconds"),
        "session": SESSION_ID,
        "level":   level,
        "event":   event,
    }
    if data:
        entry.update(_sanitize(data))
    try:
        f = _open_log()
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # Ne jamais crasher à cause des logs


def _sanitize(data: dict) -> dict:
    """Tronque les champs très longs pour garder les logs lisibles."""
    MAX_STR = 800
    result = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > MAX_STR:
            result[k] = v[:MAX_STR] + f"… [{len(v)} chars total]"
        elif isinstance(v, list):
            result[k] = v[:20]  # Max 20 éléments
        else:
            result[k] = v
    return result


# ── Helpers spécialisés ────────────────────────────────────────────────────────

def log_code_session_start(model: str, workspace: str, user_message: str,
                            context_files: list[str]):
    log("code_agent.session_start", {
        "model":         model,
        "workspace":     os.path.basename(workspace) if workspace else None,
        "user_message":  user_message,
        "context_files": [os.path.basename(f) for f in context_files],
        "n_context":     len(context_files),
    })


def log_llm_call(iteration: int, model: str, n_messages: int,
                  n_tools: int, prompt_chars: int):
    log("code_agent.llm_call", {
        "iteration":    iteration,
        "model":        model,
        "n_messages":   n_messages,
        "n_tools":      n_tools,
        "prompt_chars": prompt_chars,
    })


def log_llm_response(content: str, tool_calls: list | None,
                      duration_ms: int = 0):
    tool_names = []
    tool_args_summary = []
    if tool_calls:
        for tc in tool_calls:
            tool_names.append(tc.function.name)
            args = tc.function.arguments
            if isinstance(args, dict):
                # Résumé des args : clés + valeur courte
                summary = {k: (str(v)[:80] if isinstance(v, str) else v)
                           for k, v in args.items()}
            else:
                summary = str(args)[:120]
            tool_args_summary.append({"name": tc.function.name, "args": summary})

    log("code_agent.llm_response", {
        "content_len":       len(content),
        "content_preview":   content[:300] if content else "",
        "has_tool_calls":    bool(tool_calls),
        "tool_calls":        tool_args_summary,
        "tool_names":        tool_names,
        "duration_ms":       duration_ms,
    })


def log_actions_detected(actions: list[dict], workspace: str = ""):
    summary = []
    for a in actions:
        if a["type"] == "create":
            rel = os.path.relpath(a["path"], workspace) if workspace else a["path"]
            summary.append({"type": "create", "path": rel,
                            "lines": a["content"].count("\n")})
        elif a["type"] == "edit":
            rel = os.path.relpath(a["path"], workspace) if workspace else a["path"]
            summary.append({"type": "edit",   "path": rel,
                            "search_lines": a["search"].count("\n"),
                            "replace_lines": a["replace"].count("\n")})
        elif a["type"] == "run":
            summary.append({"type": "run", "command": a["command"]})
        elif a["type"] == "too_large":
            rel = os.path.relpath(a["path"], workspace) if workspace else a["path"]
            summary.append({"type": "too_large", "path": rel,
                            "lines": a.get("lines", "?")})
    log("code_agent.actions_detected", {
        "n_actions": len(actions),
        "actions":   summary,
    })


def _is_error(result: str) -> bool:
    prefixes = ("Error", "REFUSÉ", "Tool error", "[exit ", "Traceback")
    return any(result.startswith(p) for p in prefixes)


def log_action_result(action_type: str, path_or_cmd: str,
                       result: str, workspace: str = ""):
    success = not _is_error(result)
    if workspace and os.path.isabs(path_or_cmd):
        try:
            path_or_cmd = os.path.relpath(path_or_cmd, workspace)
        except ValueError:
            pass
    log("code_agent.action_result", {
        "action":   action_type,
        "target":   path_or_cmd,
        "success":  success,
        "result":   result[:400],
    }, level="info" if success else "warn")


def log_tool_call(name: str, args: dict, result: str, duration_ms: int = 0):
    """Log un appel d'outil API (run_command, pip_install, etc.)."""
    success = not _is_error(result) and not result.startswith("Unknown tool")
    # Ne logger que les clés non-sensibles (pas le contenu de fichier)
    safe_args = {k: v for k, v in args.items() if k != "content"}
    log("tool.call", {
        "tool":        name,
        "args":        safe_args,
        "success":     success,
        "result":      result[:300],
        "duration_ms": duration_ms,
    }, level="info" if success else "warn")


def log_error(context: str, error: str, extra: dict = None):
    data = {"context": context, "error": str(error)[:500]}
    if extra:
        data.update(extra)
    log("error", data, level="error")


# ── Analyseur de logs (CLI) ────────────────────────────────────────────────────

def _print_summary(log_file: str, event_filter: str = None,
                   level_filter: str = None, last_n: int = None):
    """Affiche un résumé lisible des logs."""
    try:
        with open(log_file, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Pas de log pour aujourd'hui : {log_file}")
        return

    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Filtres
    if event_filter:
        entries = [e for e in entries if event_filter in e.get("event", "")]
    if level_filter:
        entries = [e for e in entries if e.get("level") == level_filter]
    if last_n:
        entries = entries[-last_n:]

    if not entries:
        print("Aucun log correspondant.")
        return

    # Stats globales
    sessions = {e["session"] for e in entries}
    events = {}
    errors = []
    for e in entries:
        ev = e["event"]
        events[ev] = events.get(ev, 0) + 1
        if e.get("level") == "error":
            errors.append(e)

    print(f"\n{'='*60}")
    print(f"  Fichier : {os.path.basename(log_file)}")
    print(f"  Entrées : {len(entries)}  |  Sessions : {len(sessions)}")
    print(f"{'='*60}")

    print("\n── Événements ──")
    for ev, count in sorted(events.items(), key=lambda x: -x[1]):
        print(f"  {count:4d}x  {ev}")

    if errors:
        print(f"\n── Erreurs ({len(errors)}) ──")
        for e in errors[-10:]:
            print(f"  [{e['ts']}] {e.get('context','?')} : {e.get('error','?')[:100]}")

    # Dernières sessions de code
    code_starts = [e for e in entries if e["event"] == "code_agent.session_start"]
    if code_starts:
        print(f"\n── Dernières sessions code ({len(code_starts)}) ──")
        for e in code_starts[-5:]:
            print(f"  [{e['ts'][11:19]}] model={e.get('model','?')}"
                  f"  files={e.get('context_files',[])}"
                  f"  msg={e.get('user_message','')[:60]}")

    # Actions détectées
    action_events = [e for e in entries if e["event"] == "code_agent.actions_detected"]
    if action_events:
        print(f"\n── Actions détectées ({len(action_events)} batches) ──")
        for e in action_events[-10:]:
            for a in e.get("actions", []):
                t = a.get("type")
                if t == "create":
                    print(f"  [{e['ts'][11:19]}] CREATE {a.get('path')}  ({a.get('lines')} lignes)")
                elif t == "edit":
                    print(f"  [{e['ts'][11:19]}] EDIT   {a.get('path')}"
                          f"  search={a.get('search_lines')}L → replace={a.get('replace_lines')}L")
                elif t == "run":
                    print(f"  [{e['ts'][11:19]}] RUN    {a.get('command')}")
                elif t == "too_large":
                    print(f"  [{e['ts'][11:19]}] REFUSÉ {a.get('path')}  ({a.get('lines')} lignes)")

    # Résultats d'actions
    result_events = [e for e in entries if e["event"] == "code_agent.action_result"]
    fails = [e for e in result_events if not e.get("success")]
    if fails:
        print(f"\n── Actions échouées ({len(fails)}) ──")
        for e in fails[-10:]:
            print(f"  [{e['ts'][11:19]}] {e.get('action')} {e.get('target')}")
            print(f"    → {e.get('result','')[:120]}")

    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Analyseur de logs de l'agent de code")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Date YYYY-MM-DD (défaut: aujourd'hui)")
    parser.add_argument("--event", default=None, help="Filtrer par événement")
    parser.add_argument("--level", default=None, help="Filtrer par level (error/warn/info)")
    parser.add_argument("--last",  type=int, default=None, help="N dernières entrées")
    parser.add_argument("--raw",   action="store_true", help="Afficher le JSON brut")
    args = parser.parse_args()

    log_file = os.path.join(LOG_DIR, f"agent_{args.date}.jsonl")

    if args.raw:
        try:
            with open(log_file) as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        if args.event and args.event not in obj.get("event", ""):
                            continue
                        if args.level and obj.get("level") != args.level:
                            continue
                        print(json.dumps(obj, ensure_ascii=False, indent=2))
                    except Exception:
                        pass
        except FileNotFoundError:
            print(f"Pas de log : {log_file}")
    else:
        _print_summary(log_file, args.event, args.level, args.last)
