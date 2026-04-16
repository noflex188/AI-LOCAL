"""
Agent de code local — inspiré de Claude Code / Aider.
Actif automatiquement quand un workspace est ouvert.

Architecture :
- Injection automatique des fichiers pertinents dans le contexte
- Pas de tool calling API pour create/patch/read → format texte uniquement
- Petits fichiers (≤ 150 lignes) : réécriture complète tolérée (plus fiable)
- Grands fichiers : SEARCH/REPLACE avec max 40 lignes
- Validation syntaxe Python avant écriture
"""
import json
import os
import re
import ollama

from tools import TOOL_SCHEMAS, call_tool
from actions import parse_actions, execute_actions
from confirmation import confirm_manager, SENSITIVE_TOOLS
import memory as mem

# ── Outils autorisés en mode code agent (pas de file tools → format texte) ──

CODE_TOOL_NAMES = {
    "run_command",
    "pip_install",
    "grep_files",
    "list_dir",
    "read_file",      # autorisé : lecture des grands fichiers hors contexte
    "delete_file",
    "get_datetime",
    "web_search",
    "fetch_url",
    "save_memory",
    "search_project",
}

CODE_TOOL_SCHEMAS = [
    schema for schema in TOOL_SCHEMAS
    if schema.get("function", {}).get("name") in CODE_TOOL_NAMES
]

# ── Constantes ────────────────────────────────────────────────────────────────

MAX_CONTEXT_FILES = 8
MAX_CONTEXT_CHARS = 50_000
MAX_ITERATIONS    = 12

# Extensions de fichiers considérées comme "code"
CODE_EXTENSIONS = {
    "py", "js", "ts", "jsx", "tsx", "html", "css", "json", "md", "txt",
    "yaml", "yml", "toml", "rs", "go", "java", "cpp", "c", "sh", "rb",
    "php", "swift", "sql", "xml", "env", "ini", "cfg",
}

# Répertoires à ignorer lors du scan
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", ".next", ".nuxt", ".cache", "target",
    ".idea", ".vscode", "coverage", ".pytest_cache", ".mypy_cache",
}


# ── Arbre de projet ───────────────────────────────────────────────────────────

def _tree_to_lines(tree: list, prefix: str = "") -> list[str]:
    """
    Convertit la liste renvoyée par workspace.get_tree() en lignes
    style ├── / └── (arbre ASCII).
    """
    lines = []
    for i, entry in enumerate(tree):
        is_last = (i == len(tree) - 1)
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + entry["name"])
        if entry.get("type") == "dir" and entry.get("children"):
            extension = "    " if is_last else "│   "
            lines.extend(_tree_to_lines(entry["children"], prefix + extension))
    return lines


# ── Sélection des fichiers de contexte ───────────────────────────────────────

def _collect_all_code_files(wpath: str) -> list[str]:
    """Retourne tous les fichiers de code du projet (hors répertoires ignorés)."""
    result = []
    for root, dirs, files in os.walk(wpath):
        # Filtrer les répertoires ignorés en place pour éviter leur descente
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in CODE_EXTENSIONS:
                result.append(os.path.join(root, fname))
    return result


def get_context_files(wpath: str, user_message: str, history: list) -> list[str]:
    """
    Retourne la liste des fichiers pertinents à injecter dans le contexte.

    Stratégie :
    1. Cherche des noms de fichiers dans le message utilisateur + les 4 derniers
       messages de l'historique (via regex).
    2. Résout ces noms contre le workspace.
    3. Si aucun trouvé ou si le projet est petit, renvoie TOUS les fichiers de code.
    4. Limite à MAX_CONTEXT_FILES.
    """
    filename_pattern = re.compile(
        r'\b([\w\-]+\.(?:py|js|ts|jsx|tsx|html|css|json|md|txt|yaml|yml|toml'
        r'|rs|go|java|cpp|c|sh|rb|php|swift|sql|xml|ini|cfg|env))\b'
    )

    # Textes à analyser : message actuel + 4 derniers messages history
    texts_to_scan = [user_message]
    for msg in history[-4:]:
        content = msg.get("content", "")
        if isinstance(content, str):
            texts_to_scan.append(content)

    # Trouver tous les noms de fichiers mentionnés
    mentioned_names: list[str] = []
    seen: set[str] = set()
    for text in texts_to_scan:
        for m in filename_pattern.finditer(text):
            fname = m.group(1)
            if fname not in seen:
                seen.add(fname)
                mentioned_names.append(fname)

    # Résoudre contre le workspace
    resolved: list[str] = []
    for fname in mentioned_names:
        # Chercher récursivement dans le workspace
        for root, dirs, files in os.walk(wpath):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            if fname in files:
                full = os.path.join(root, fname)
                if full not in resolved:
                    resolved.append(full)
                break

    # Collecter tous les fichiers du projet
    all_files = _collect_all_code_files(wpath)

    # Si aucun fichier mentionné trouvé ou projet assez petit → tout retourner
    if not resolved or len(all_files) <= MAX_CONTEXT_FILES:
        return all_files[:MAX_CONTEXT_FILES]

    # Sinon : fichiers mentionnés en priorité, compléter si de la place
    result = resolved[:MAX_CONTEXT_FILES]
    if len(result) < MAX_CONTEXT_FILES:
        for f in all_files:
            if f not in result:
                result.append(f)
            if len(result) >= MAX_CONTEXT_FILES:
                break

    return result


# ── Formatage du contexte fichiers ────────────────────────────────────────────

def format_file_context(files: list[str], wpath: str) -> str:
    """
    Lit les fichiers listés et construit le bloc de contexte à injecter
    dans le system prompt.

    - Fichier ≤ 150 lignes       : contenu complet avec numéros de ligne
    - Fichier 151–400 lignes     : contenu complet avec numéros + note SEARCH/REPLACE
    - Fichier > 400 lignes       : 30 premières lignes + message de troncature
    - Budget total : MAX_CONTEXT_CHARS (stop early si dépassé)
    """
    if not files:
        return ""

    parts = ["\n\n═══ FICHIERS DU PROJET ═══\n"]
    total_chars = len(parts[0])

    for fpath in files:
        if total_chars >= MAX_CONTEXT_CHARS:
            break

        rel_path = os.path.relpath(fpath, wpath).replace("\\", "/")

        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()
        except Exception as e:
            parts.append(f"\n### {rel_path}\n(Erreur de lecture : {e})\n")
            continue

        total_lines = len(raw_lines)
        # Détecter l'extension pour le bloc de code
        ext = fpath.rsplit(".", 1)[-1].lower() if "." in fpath else "txt"

        header = f"\n### {rel_path}\n"

        if total_lines <= 150:
            # Fichier petit : contenu complet avec numéros de ligne
            numbered = "".join(f"{i+1:4d} | {line}" for i, line in enumerate(raw_lines))
            block = f"{header}```{ext}\n{numbered}```\n"
        elif total_lines <= 400:
            # Fichier moyen : contenu complet + note
            numbered = "".join(f"{i+1:4d} | {line}" for i, line in enumerate(raw_lines))
            block = (
                f"{header}"
                f"_(Grand fichier — utilise SEARCH/REPLACE pour modifier)_\n"
                f"```{ext}\n{numbered}```\n"
            )
        else:
            # Grand fichier : 30 premières lignes seulement
            numbered = "".join(f"{i+1:4d} | {line}" for i, line in enumerate(raw_lines[:30]))
            block = (
                f"{header}"
                f"_(Fichier trop grand [{total_lines} lignes] — utilise `grep_files` pour localiser le code)_\n"
                f"```{ext}\n{numbered}\n... ({total_lines - 30} lignes supplémentaires non affichées)\n```\n"
            )

        # Budget check
        if total_chars + len(block) > MAX_CONTEXT_CHARS:
            # Inclure quand même l'en-tête avec un message de troncature
            truncated = (
                f"{header}"
                f"_(Tronqué — budget de contexte atteint. Utilise `grep_files` ou `search_project`.)_\n"
            )
            parts.append(truncated)
            total_chars += len(truncated)
            break

        parts.append(block)
        total_chars += len(block)

    return "".join(parts)


# ── Prompt système pour le mode code ─────────────────────────────────────────

def build_code_system_prompt(wpath: str, file_context: str) -> str:
    """
    Construit le system prompt complet pour le mode agent de code.
    Inclut : instructions de format, arbre du projet, contenu des fichiers,
    mémoire utilisateur et règles.
    """
    import workspace as ws
    from context import build_context_block

    # Arbre du projet
    tree = ws.get_tree()
    tree_lines = _tree_to_lines(tree)
    project_name = os.path.basename(wpath)
    tree_str = f"{project_name}/\n" + "\n".join(tree_lines) if tree_lines else f"{project_name}/ (vide)"

    # Info RAG
    rag_info = ""
    try:
        import rag
        if rag.is_indexed(wpath):
            count = rag.index_count(wpath)
            rag_info = f"\n- {count} fichiers indexés — utilise `search_project` pour chercher avant de modifier."
        else:
            rag_info = "\n- Projet non indexé (RAG non disponible)."
    except Exception:
        pass

    # Mémoire utilisateur
    notes = mem.load_notes()
    memory_section = ""
    if notes:
        memory_section = f"\n\n## Ce que tu sais de l'utilisateur\n{notes}\n"

    # Contexte système (OS, langue, etc.)
    ctx_block = build_context_block()

    prompt = f"""Tu es un agent de développement qui agit directement sur le projet.
Tu as accès au contenu des fichiers ci-dessous — lis-les attentivement avant d'agir.

━━━ FORMAT OBLIGATOIRE ━━━

▌ NOUVEAU FICHIER ou PETIT FICHIER (≤ 150 lignes) — écris le fichier complet :
```python:snake.py
# code complet ici
```

▌ MODIFIER UN GRAND FICHIER (> 150 lignes) — SEARCH/REPLACE :
snake.py
<<<<<<< SEARCH
texte EXACT à remplacer (max 40 lignes)
=======
nouveau texte
>>>>>>> REPLACE

▌ COMMANDE :
```bash
pip install pygame
python snake.py
```

━━━ RÈGLES ━━━
• Tout code doit avoir un en-tête avec le chemin — code brut sans en-tête = ignoré
• SEARCH : copie le texte EXACTEMENT depuis les fichiers fournis (numéros de ligne pour référence uniquement, ne les inclus pas dans SEARCH)
• SEARCH max 40 lignes — plusieurs petits blocs valent mieux qu'un gros
• Réponds dans la langue de l'utilisateur
• AGIS directement — ne demande pas de confirmation sauf si la demande est vraiment ambiguë
• Pas de "voici le code" suivi d'un bloc — écris le fichier directement
• Ne ré-explique jamais ce que tu viens de faire ligne par ligne
• Pour les commandes shell, utilise le format ```bash sans chemin (pas de bash:quelquechose)

━━━ SÉCURITÉ ━━━
• Tous les chemins sont RELATIFS au dossier du projet (`{project_name}/`)
• Écris `script.py`, jamais `C:/Users/.../script.py`
• Tu n'as accès qu'au dossier ouvert, rien d'autre

━━━ PROJET : {project_name} ━━━
Workspace : `{wpath}`{rag_info}

```
{tree_str}
```
{ctx_block}{memory_section}{file_context}"""

    return prompt


# ── Helper ────────────────────────────────────────────────────────────────────

def _tool_args(tc, i: int) -> dict:
    """Extrait les arguments d'un tool call Ollama (dict ou JSON string)."""
    return (
        tc.function.arguments
        if isinstance(tc.function.arguments, dict)
        else json.loads(tc.function.arguments)
    )


def _trimmed_history(history: list, max_history: int = 40) -> list[dict]:
    """Garde le message système + les max_history derniers messages."""
    system = history[:1]
    rest   = history[1:]
    return system + (rest[-max_history:] if len(rest) > max_history else rest)


# ── Générateur principal ──────────────────────────────────────────────────────

def stream_code(agent_self, user_message: str, attachments: list):
    """
    Générateur principal du mode agent de code.
    Remplace stream_chat() quand un workspace est actif.

    Reçoit l'instance Agent pour accéder à :
    - agent_self.model
    - agent_self.history  (partagé avec agent.py, mis à jour ici)
    - agent_self.current_conv
    - agent_self._save()
    - agent_self._build_user_message()
    """
    import workspace as ws

    wpath = ws.get_workspace()
    if not wpath:
        # Sécurité : ne devrait pas arriver, mais on délègue quand même
        return

    # ── 1. Construire le message utilisateur (avec pièces jointes) ────────────
    msg = agent_self._build_user_message(user_message, attachments or [])
    agent_self.history.append(msg)

    # ── 2. Construire le contexte fichiers et mettre à jour le system prompt ──
    ctx_files  = get_context_files(wpath, user_message, agent_self.history)
    file_ctx   = format_file_context(ctx_files, wpath)
    sys_prompt = build_code_system_prompt(wpath, file_ctx)

    # On injecte dans le premier message (system) de l'historique
    if agent_self.history and agent_self.history[0].get("role") == "system":
        agent_self.history[0]["content"] = sys_prompt
    else:
        agent_self.history.insert(0, {"role": "system", "content": sys_prompt})

    # ── 3. Boucle agent ───────────────────────────────────────────────────────
    loop_iterations = 0
    recently_read: list[str] = []
    read_counts: dict[str, int] = {}

    while True:
        loop_iterations += 1
        if loop_iterations > MAX_ITERATIONS:
            yield {"type": "token", "content": "\n\n⚠️ Limite d'itérations atteinte — arrêt automatique.\n"}
            agent_self._save()
            yield {"type": "conv_meta", "conv": agent_self.current_conv}
            return

        # ── Appel Ollama ──────────────────────────────────────────────────────
        stream = ollama.chat(
            model    = agent_self.model,
            messages = _trimmed_history(agent_self.history),
            tools    = CODE_TOOL_SCHEMAS,
            stream   = True,
        )

        content    = ""
        tool_calls = None

        for chunk in stream:
            chunk_msg = chunk.message
            if chunk_msg.tool_calls:
                tool_calls = chunk_msg.tool_calls
            if chunk_msg.content:
                yield {"type": "token", "content": chunk_msg.content}
                content += chunk_msg.content

        # ── Pas de tool call API → actions texte ─────────────────────────────
        if not tool_calls:
            agent_self.history.append({"role": "assistant", "content": content})

            # Détecter et exécuter les actions texte (```lang:path + SEARCH/REPLACE)
            text_actions = parse_actions(content, wpath, recently_read)
            if text_actions:
                yield {"type": "token", "content": "\n\n> ⚙️ Application des modifications…\n\n"}
                results = execute_actions(text_actions)
                for i, r in enumerate(results):
                    yield {"type": "tool_start", "name": r["name"], "args": r["args"]}
                    yield {"type": "tool_end",   "name": r["name"], "result": r["result"]}
                    agent_self.history.append({
                        "role": "tool",
                        "tool_call_id": f"action_{i}",
                        "content": r["result"],
                    })
                paths = [r["args"]["path"] for r in results if "path" in r["args"]]
                if paths:
                    names = ", ".join(f"`{os.path.relpath(p, wpath).replace(chr(92), '/')}`" for p in paths)
                    yield {"type": "token", "content": f"\n\n📝 {names}\n"}

                # Si des actions ont échoué, relancer pour laisser le modèle corriger
                failed = [r for r in results if r["result"].startswith(("Error", "REFUSÉ"))]
                if failed and loop_iterations < MAX_ITERATIONS:
                    # Ajouter un hint et relancer
                    hint_lines = []
                    for r in failed:
                        hint_lines.append(f"- `{r['name']}` : {r['result'][:200]}")
                    hint = (
                        "\n\n[SYSTÈME] Certaines modifications ont échoué. "
                        "Corrige les erreurs indiquées :\n" + "\n".join(hint_lines)
                    )
                    agent_self.history.append({
                        "role": "user",
                        "content": hint,
                    })
                    continue

            agent_self._save()
            yield {"type": "conv_meta", "conv": agent_self.current_conv}
            return

        # ── Tool calls API ────────────────────────────────────────────────────
        agent_self.history.append({
            "role":    "assistant",
            "content": content or "",
            "tool_calls": [
                {
                    "id":   getattr(tc, "id", f"call_{i}"),
                    "type": "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": _tool_args(tc, i),
                    },
                }
                for i, tc in enumerate(tool_calls)
            ],
        })

        for i, tc in enumerate(tool_calls):
            result  = ""
            call_id = getattr(tc, "id", f"call_{i}")

            try:
                name = tc.function.name
                args = _tool_args(tc, i)

                # Rediriger les outils d'écriture fichier vers le format texte
                if name == "create_file":
                    result = (
                        "ERREUR : utilise le format texte pour créer des fichiers :\n"
                        "```python:nom_fichier.py\n# contenu complet ici\n```\n"
                        "Ne passe jamais par l'API pour les opérations de fichiers."
                    )
                    yield {"type": "tool_start", "name": name, "args": args}
                    yield {"type": "tool_end",   "name": name, "result": result}
                    agent_self.history.append({
                        "role": "tool", "tool_call_id": call_id, "content": result,
                    })
                    continue
                elif name in ("patch_file", "patch_file_lines"):
                    result = (
                        "ERREUR : utilise le format SEARCH/REPLACE pour modifier des fichiers :\n"
                        "fichier.py\n<<<<<<< SEARCH\ntexte exact\n=======\nnouvel texte\n>>>>>>> REPLACE"
                    )
                    yield {"type": "tool_start", "name": name, "args": args}
                    yield {"type": "tool_end",   "name": name, "result": result}
                    agent_self.history.append({
                        "role": "tool", "tool_call_id": call_id, "content": result,
                    })
                    continue

                # Vérifier si l'outil est dans la liste autorisée
                if name not in CODE_TOOL_NAMES:
                    result = (
                        f"Outil `{name}` non disponible en mode code. "
                        f"Outils disponibles : {', '.join(sorted(CODE_TOOL_NAMES))}."
                    )
                    yield {"type": "tool_start", "name": name, "args": args}
                    yield {"type": "tool_end",   "name": name, "result": result}
                    agent_self.history.append({
                        "role": "tool", "tool_call_id": call_id, "content": result,
                    })
                    continue

                # ── Confirmation pour outils sensibles ────────────────────────
                if name in SENSITIVE_TOOLS:
                    cid, event = confirm_manager.request(name, args)
                    yield {"type": "confirm", "id": cid, "tool": name, "args": args}
                    event.wait(timeout=120)
                    approved = confirm_manager.get_result(cid)
                    if not approved:
                        result = "Action refusée par l'utilisateur."
                        yield {"type": "tool_denied", "name": name}
                        agent_self.history.append({
                            "role": "tool", "tool_call_id": call_id, "content": result,
                        })
                        continue

                yield {"type": "tool_start", "name": name, "args": args}
                result = call_tool(name, args)

                # Mise à jour du system prompt si save_memory
                if name == "save_memory":
                    ctx_files_new = get_context_files(wpath, user_message, agent_self.history)
                    file_ctx_new  = format_file_context(ctx_files_new, wpath)
                    agent_self.history[0]["content"] = build_code_system_prompt(wpath, file_ctx_new)

                # Tracking des fichiers lus
                if name == "read_file":
                    fpath = args.get("path", "")
                    if fpath not in recently_read:
                        recently_read.append(fpath)
                    read_counts[fpath] = read_counts.get(fpath, 0) + 1
                    if read_counts[fpath] >= 2:
                        hint = (
                            "\n\n⚠️ [SYSTÈME] Tu as lu ce fichier plusieurs fois sans le modifier. "
                            "Applique maintenant les changements avec des blocs SEARCH/REPLACE ciblés "
                            "(max 40 lignes par bloc SEARCH). Ne réécris PAS le fichier entier."
                        )
                        result = result + hint
                        read_counts[fpath] = 0

                yield {"type": "tool_end", "name": name, "result": result[:600]}

            except Exception as e:
                result = f"Tool error: {e}"
                yield {"type": "tool_end", "name": name, "result": result}

            agent_self.history.append({
                "role": "tool", "tool_call_id": call_id, "content": result,
            })
