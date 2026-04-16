import json
import ollama
from colorama import Fore, Style, init as colorama_init
from tools import TOOL_SCHEMAS, call_tool
import memory as mem
from context import build_context_block
from confirmation import confirm_manager, SENSITIVE_TOOLS

colorama_init(autoreset=True)

MODEL           = "gemma4:26b"
PREFERRED_MODELS = ["gemma4:26b", "qwen2.5-coder:32b", "qwen2.5-coder:14b", "qwen2.5-coder:7b", "gemma4:e4b"]
MAX_HISTORY      = 40


def _detect_model() -> str:
    """Retourne le premier modèle de la liste préférée qui est installé."""
    try:
        import ollama as _ol
        installed = {m.model for m in _ol.list().models}
        for m in PREFERRED_MODELS:
            if m in installed:
                return m
        # Fallback : premier modèle installé
        if installed:
            return next(iter(installed))
    except Exception:
        pass
    return MODEL

SYSTEM_PROMPT_BASE = """Tu es un assistant IA personnel, intelligent, direct et fiable. Tu tournes entièrement en local sur la machine de l'utilisateur grâce à Ollama.

## Personnalité
- Ton naturel, humain, sans être familier ni robotique.
- Concis quand la réponse est simple, détaillé quand le sujet le demande.
- Tu n'hésites pas à donner un avis ou une recommandation claire plutôt que de lister des options sans fin.
- Tu ne te répètes pas, tu ne te justifies pas inutilement.
- Tu réponds toujours dans la langue de l'utilisateur.

## Outils disponibles
| Outil         | Utilisation                                              |
|---------------|----------------------------------------------------------|
| web_search    | Recherche DuckDuckGo — info récente, produits, docs      |
| fetch_url     | Lire le contenu complet d'une page web                   |
| create_file      | Créer un nouveau fichier ou réécrire entièrement      |
| read_file        | Lire un fichier existant                              |
| patch_file       | Remplacer un bloc de texte exact dans un fichier      |
| patch_file_lines | Remplacer des lignes par numéro (plus fiable)         |
| grep_files       | Chercher un pattern dans les fichiers (regex)         |
| list_dir         | Lister un répertoire                                  |
| delete_file   | Supprimer un fichier                                     |
| run_command   | Exécuter une commande shell (python, git, etc.)          |
| pip_install   | Installer des packages Python (ex: ['pygame', 'numpy'])  |
| get_datetime  | Obtenir la date et l'heure locale exactes                |
| save_memory   | Mémoriser un fait important sur l'utilisateur ou un projet|

## Règles d'utilisation des outils
- **web_search** : utilise-le dès que tu as un doute, que l'information peut être datée, ou que l'utilisateur te demande quelque chose de factuel. Ne suppose jamais — cherche.
- **fetch_url** : après un web_search, si un résultat semble contenir la réponse précise, lis la page.
- **get_datetime** : obligatoire pour toute question sur l'heure ou la date. Ne devine jamais.
- **pip_install** : pour installer des dépendances Python, utilise cet outil — pas `run_command` avec pip. Exemple : `pip_install(packages=["pygame", "requests"])`.
- **run_command** : après avoir créé du code, propose de l'exécuter. Les commandes s'exécutent dans le venv Python du projet. Ne jamais utiliser `sudo`, `runas` ou des options qui nécessitent des droits élevés.
- **save_memory** : utilise-le dès que l'utilisateur mentionne son prénom, une préférence, un projet en cours. Fais-le naturellement sans le demander.
- Tu peux enchaîner plusieurs outils dans le même tour si nécessaire.

## Tu es un agent de développement — MODE AGENT ACTIF

Quand un workspace est ouvert, tu AGIS directement sur les fichiers. Tu ne montres jamais du code sans l'appliquer.

### ⚠️ SÉCURITÉ : tous les chemins de fichiers sont RELATIFS au dossier du projet.
- Écris `script.py`, pas `C:/Users/.../script.py`
- Écris `src/app.py`, pas un chemin absolu
- Tu n'as accès qu'au dossier du projet ouvert, rien d'autre.

### CRÉER UN NOUVEAU FICHIER
Écris un bloc de code avec le langage ET le chemin (relatif) séparés par `:` :

```python:script.py
print("hello")
```

### MODIFIER UN FICHIER EXISTANT (OBLIGATOIRE : SEARCH/REPLACE)
**Ne JAMAIS réécrire un fichier entier pour changer quelques lignes.**
1. Lis d'abord le fichier avec `read_file` (obligatoire si tu ne connais pas le contenu exact)
2. Utilise SEARCH/REPLACE pour changer UNIQUEMENT ce qui doit l'être :

fichier.py
<<<<<<< SEARCH
    code_existant_exact()
=======
    nouveau_code()
>>>>>>> REPLACE

### ⚠️ RÈGLES STRICTES — SEARCH/REPLACE
- **MAX 40 lignes par bloc SEARCH** — si c'est plus grand, découpe en plusieurs petits blocs ciblés
- **Un bloc = une modification précise** : une fonction, un paramètre, une ligne — pas une section entière du fichier
- **NE MODIFIE QUE CE QUI EST DEMANDÉ** — n'optimise pas, ne réorganise pas, ne renomme pas le code non concerné
- **Plusieurs petits SEARCH/REPLACE > un gros** : préfère 3 blocs de 10 lignes à un seul de 30
- Le matching tolère les légères différences d'indentation

**Quand utiliser ```lang:fichier pour un fichier existant ?**
→ UNIQUEMENT si le fichier fait moins de 50 lignes au total ET que tu dois tout réécrire.

### SUPPRIMER UN FICHIER → `delete_file`
### EXÉCUTER UNE COMMANDE → `run_command`
### CHERCHER DANS LE CODE → `grep_files` puis `read_file`

### EXEMPLES

❌ MAUVAIS — réécrire tout un fichier pour changer 2 lignes :
> ```python:app.py
> # ... 200 lignes copiées juste pour changer une ligne ...
> ```

✅ BON — modifier seulement ce qui change :
> app.py
> <<<<<<< SEARCH
>     return x
> =======
>     return x * 2
> >>>>>>> REPLACE

❌ MAUVAIS — chemin absolu :
> ```python:C:/Users/test/script.py

✅ BON — chemin relatif :
> ```python:script.py

### RÈGLE ABSOLUE
- Ne montre JAMAIS du code brut sans le format `lang:chemin` ou SEARCH/REPLACE
- AGIS directement : crée, modifie, exécute
- **Seule exception** : si l'utilisateur dit "montre-moi", "explique-moi" ou demande un exemple théorique
- Un bloc de code sans `lang:chemin` ne sera PAS appliqué automatiquement — utilise TOUJOURS le format avec chemin

## Avant d'agir : clarifier si nécessaire
Si une demande manque de contexte (objectif flou, stack non précisée, etc.), **pose d'abord des questions ciblées**.
- Maximum 3 questions à la fois, regroupées en un seul message numéroté.
- Si tu peux déduire depuis le contexte ou la mémoire, déduis — ne demande pas.
- Pour les tâches simples et sans ambiguïté, agis directement.

## Format des réponses
- Pour des listes de choix ou comparatifs, utilise un tableau ou des puces claires.
- Évite les introductions inutiles du type "Bien sûr !" ou "Absolument !".
- En mode agent : utilise toujours les formats d'action ci-dessus pour agir sur les fichiers.
"""


def _build_system_prompt() -> str:
    import workspace as ws
    prompt = SYSTEM_PROMPT_BASE + build_context_block()
    wpath = ws.get_workspace()
    if wpath:
        import rag, os
        indexed = rag.is_indexed(wpath)
        count   = rag.index_count(wpath) if indexed else 0
        prompt += f"\n## Workspace actif\n- Dossier : `{wpath}`\n"
        if indexed:
            prompt += f"- {count} fichiers indexés — utilise `search_project` pour chercher dans le code avant de lire ou modifier des fichiers.\n"
        else:
            prompt += "- Pas encore indexé (le RAG n'est pas disponible).\n"
    notes = mem.load_notes()
    if notes:
        prompt += f"\n## Ce que tu sais déjà sur l'utilisateur et ses projets\n{notes}\n"
    return prompt


def _has_code_block(text: str) -> bool:
    """Détecte si la réponse contient un bloc de code (``` ... ```)."""
    import re
    return bool(re.search(r"```[\w]*\n[\s\S]+?```", text))


def _extract_code_blocks(text: str) -> list[dict]:
    """Extrait les blocs de code avec leur langage."""
    import re
    blocks = []
    for m in re.finditer(r"```([\w]*)\n([\s\S]+?)```", text):
        lang = m.group(1).strip()
        code = m.group(2)
        blocks.append({"lang": lang, "code": code})
    return blocks


_LANG_EXT = {
    "python":"py","javascript":"js","typescript":"ts","powershell":"ps1",
    "bash":"sh","shell":"sh","html":"html","css":"css","json":"json",
    "sql":"sql","rust":"rs","go":"go","java":"java","cpp":"cpp","c":"c",
    "yaml":"yml","toml":"toml","xml":"xml","php":"php","ruby":"rb","swift":"swift",
}

def _guess_filename(history: list, lang: str, index: int = 0) -> str:
    """Tente de trouver un nom de fichier dans l'historique récent, sinon en génère un."""
    import re
    ext = _LANG_EXT.get(lang.lower(), lang or "txt")
    # Cherche un nom de fichier explicite dans les derniers messages
    for msg in reversed(history[-6:]):
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        # Pattern : quelque chose.ext
        matches = re.findall(r'\b([\w\-]+\.' + re.escape(ext) + r')\b', content, re.IGNORECASE)
        if matches:
            return matches[0]
        # Pattern : nom entre backticks
        matches = re.findall(r'`([\w\-/]+\.' + re.escape(ext) + r')`', content, re.IGNORECASE)
        if matches:
            return matches[0]
    suffix = f"_{index+1}" if index > 0 else ""
    return f"script{suffix}.{ext}"


def _smart_infer_path(history: list, code_content: str, ext: str,
                      model_text: str = "") -> str:
    """
    Infère le nom du fichier cible quand le modèle oublie de passer 'path'.

    Ordre de priorité :
    1. Texte récent du modèle  → il a dit "Je vais créer `snake.py`"
    2. Messages récents (assistant + user)  → "snake.py" mentionné quelque part
    3. Commentaire de fichier dans le code  → # snake.py en tête de fichier
    4. Nom de classe dans le code  → class SnakeGame → snake_game.py
    5. Titre de fenêtre dans le code  → set_caption("Snake") → snake.py
    6. Fallback  → script.ext
    """
    import re

    _pat_filename = r'([\w][\w\-]*\.' + re.escape(ext) + r')'

    def _first_filename(text: str):
        """Extrait le premier nom de fichier .ext trouvé dans un texte."""
        # backtick : `snake.py`
        m = re.search(r'`' + _pat_filename + r'`', text, re.IGNORECASE)
        if m:
            return m.group(1)
        # quotes : "snake.py" ou 'snake.py'
        m = re.search(r'["\']' + _pat_filename + r'["\']', text, re.IGNORECASE)
        if m:
            return m.group(1)
        # mot isolé : snake.py (pas en milieu d'une URL)
        m = re.search(r'(?<![/\\])' + _pat_filename + r'\b', text, re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    # ── 1. Texte que le modèle vient de produire ──────────────────────────────
    if model_text:
        found = _first_filename(model_text)
        if found:
            return found

    # ── 2. Historique récent (les 15 derniers messages) ──────────────────────
    for msg in reversed(history[-15:]):
        text = msg.get("content", "")
        if not isinstance(text, str):
            continue
        found = _first_filename(text)
        if found:
            return found

    # ── 3. Commentaire de nom de fichier dans les premières lignes du code ───
    for line in code_content.split('\n')[:8]:
        m = re.search(r'[#/]{1,2}\s*' + _pat_filename, line)
        if m:
            return m.group(1)

    # ── 4. Nom de classe principal → snake_case ───────────────────────────────
    for line in code_content.split('\n')[:40]:
        m = re.match(r'\s*class\s+([A-Z]\w+)', line)
        if m:
            snake = re.sub(r'(?<!^)(?=[A-Z])', '_', m.group(1)).lower()
            return f"{snake}.{ext}"

    # ── 5. Titre de fenêtre (pygame / tkinter / etc.) ─────────────────────────
    for line in code_content.split('\n'):
        for pat in [
            r'set_caption\s*\(\s*["\']([^"\']{2,30})["\']',
            r'\.title\s*\(\s*["\']([^"\']{2,30})["\']',
        ]:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                name = re.sub(r'[^a-z0-9]+', '_', m.group(1).lower()).strip('_')
                if name:
                    return f"{name}.{ext}"

    return f"script.{ext}"


def _looks_like_tool_call(code: str) -> bool:
    """Vérifie si une chaîne est un appel d'outil JSON {"name": ..., "arguments": ...}."""
    try:
        parsed = json.loads(code.strip())
        return isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed
    except Exception:
        return False


def _extract_fake_tool_calls(text: str) -> list[dict]:
    """
    Extrait les appels d'outils JSON écrits en texte libre (hors blocs de code).
    Retourne une liste de dicts {"name": ..., "args": ...}.
    """
    import re
    results = []
    seen_starts = set()
    for m in re.finditer(r'"name"\s*:\s*"([^"]+)"', text):
        start = text.rfind('{', 0, m.start())
        if start == -1 or start in seen_starts:
            continue
        seen_starts.add(start)
        depth, end = 0, start
        for idx, ch in enumerate(text[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        if end > start:
            try:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
                    results.append({
                        "name": parsed["name"],
                        "args": parsed["arguments"] if isinstance(parsed["arguments"], dict) else {},
                    })
            except Exception:
                pass
    return results


def _already_applied(history: list) -> bool:
    """Vérifie si des outils fichiers ont déjà été appelés depuis le dernier message user original."""
    file_tools = {"create_file", "patch_file"}
    # On cherche en remontant jusqu'au 2ème message user (le premier = message original)
    user_count = 0
    for msg in reversed(history):
        if msg.get("role") == "user":
            user_count += 1
            if user_count >= 2:
                break
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("function", {}).get("name") in file_tools:
                    return True
    return False


def _tool_args(tc, i: int) -> dict:
    return tc.function.arguments if isinstance(tc.function.arguments, dict) \
           else json.loads(tc.function.arguments)


class Agent:
    def __init__(self, model: str = None):
        self.model        = model or _detect_model()
        self.current_conv = None   # dict with id, title, …
        self.history: list[dict] = []
        self._startup()

    # ── Startup ───────────────────────────────────────────────────────────────

    def _startup(self):
        migrated = mem.migrate_if_needed()
        convs    = mem.list_conversations()
        if migrated:
            self._load_conv(migrated)
        elif convs:
            self._load_conv(convs[0]["id"])
        else:
            self._new_conv_internal()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _new_conv_internal(self, title: str = "Nouvelle conversation", workspace: str | None = None) -> str:
        conv = mem.create_conversation(title=title, workspace=workspace)
        self.current_conv = conv
        self.history = [{"role": "system", "content": _build_system_prompt()}]
        return conv["id"]

    def _load_conv(self, conv_id: str):
        convs = mem.list_conversations()
        self.current_conv = next((c for c in convs if c["id"] == conv_id), None)
        self.history = [{"role": "system", "content": _build_system_prompt()}]
        past = mem.load_conversation(conv_id)
        if past:
            self.history.extend(past)

    def _save(self):
        if self.current_conv:
            mem.save_conversation(self.current_conv["id"], self.history)
            # Refresh local meta (title may have been auto-updated)
            convs = mem.list_conversations()
            self.current_conv = next(
                (c for c in convs if c["id"] == self.current_conv["id"]),
                self.current_conv
            )

    def _build_user_message(self, text: str, attachments: list) -> dict:
        """Assemble un message user avec pièces jointes (texte injecté, images en base64)."""
        MAX_TEXT = 80_000   # chars max par fichier texte
        images   = []
        parts    = []

        for att in attachments:
            if att.kind == "image":
                # Extraire le base64 pur (sans le préfixe data:…;base64,)
                b64 = att.content.split(",", 1)[-1] if "," in att.content else att.content
                images.append(b64)
                parts.append(f"[Image jointe : {att.name}]")
            else:
                content = att.content[:MAX_TEXT]
                if len(att.content) > MAX_TEXT:
                    content += "\n… (tronqué)"
                ext = att.name.rsplit(".", 1)[-1].lower() if "." in att.name else "txt"
                parts.append(f"**Fichier joint : `{att.name}`**\n```{ext}\n{content}\n```")

        full_content = "\n\n".join(parts + [text]) if parts else text
        msg = {"role": "user", "content": full_content}
        if images:
            msg["images"] = images
        return msg

    def _trimmed_history(self) -> list[dict]:
        system = self.history[:1]
        rest   = self.history[1:]
        return system + (rest[-MAX_HISTORY:] if len(rest) > MAX_HISTORY else rest)

    # ── Conversation management ───────────────────────────────────────────────

    def new_conversation(self, title: str = "Nouvelle conversation", workspace: str | None = None) -> dict:
        """Save current and create a brand-new conversation."""
        self._save()
        self._new_conv_internal(title=title, workspace=workspace)
        return self.current_conv

    def switch_conversation(self, conv_id: str) -> list[dict]:
        """Save current and switch to another conversation."""
        self._save()
        self._load_conv(conv_id)
        return self.get_history()

    def delete_conversation(self, conv_id: str) -> dict:
        """Delete a conversation; switch to most recent or create new."""
        mem.delete_conversation(conv_id)
        if self.current_conv and self.current_conv["id"] == conv_id:
            convs = mem.list_conversations()
            if convs:
                self._load_conv(convs[0]["id"])
            else:
                self._new_conv_internal()
        return self.current_conv

    def rename_conversation(self, conv_id: str, title: str):
        mem.update_title(conv_id, title)
        if self.current_conv and self.current_conv["id"] == conv_id:
            self.current_conv["title"] = title[:60]

    # ── Stream chat (web) ─────────────────────────────────────────────────────

    def stream_chat(self, user_message: str, attachments=None):
        import workspace as ws
        msg = self._build_user_message(user_message, attachments or [])
        self.history.append(msg)

        loop_iterations = 0
        MAX_ITERATIONS = 12
        read_counts: dict[str, int] = {}   # chemin → nombre de read_file consécutifs
        recently_read: list[str] = []      # fichiers lus dans cette session (pour auto-détection)

        while True:
            loop_iterations += 1
            if loop_iterations > MAX_ITERATIONS:
                yield {"type": "token", "content": "\n\n⚠️ Limite d'itérations atteinte — arrêt automatique.\n"}
                self._save()
                yield {"type": "conv_meta", "conv": self.current_conv}
                return
            stream = ollama.chat(
                model    = self.model,
                messages = self._trimmed_history(),
                tools    = TOOL_SCHEMAS,
                stream   = True,
            )
            content    = ""
            tool_calls = None

            for chunk in stream:
                msg = chunk.message
                if msg.tool_calls:
                    tool_calls = msg.tool_calls
                if msg.content:
                    yield {"type": "token", "content": msg.content}
                    content += msg.content

            if not tool_calls:
                self.history.append({"role": "assistant", "content": content})

                # Workspace actif + pas de vrai tool call = détecter et exécuter les actions
                if ws.get_workspace() and not _already_applied(self.history):
                    from actions import parse_actions, execute_actions
                    handled = False

                    # ── Priorité 1 : actions texte (```lang:path, SEARCH/REPLACE, auto-détection) ──
                    text_actions = parse_actions(content, ws.get_workspace(), recently_read)
                    if text_actions:
                        handled = True
                        yield {"type": "token", "content": "\n\n> ⚙️ Application des modifications…\n\n"}
                        results = execute_actions(text_actions)
                        for i, r in enumerate(results):
                            yield {"type": "tool_start", "name": r["name"], "args": r["args"]}
                            yield {"type": "tool_end", "name": r["name"], "result": r["result"]}
                            self.history.append({"role": "tool", "tool_call_id": f"action_{i}", "content": r["result"]})
                        paths = [r["args"]["path"] for r in results if "path" in r["args"]]
                        if paths:
                            names = ", ".join(f"`{p}`" for p in paths)
                            yield {"type": "token", "content": f"\n\n📝 {names}\n"}

                    # ── Priorité 2 : faux tool calls JSON ──
                    if not handled:
                        blocks = _extract_code_blocks(content) if _has_code_block(content) else []
                        fake_calls: list[dict] = []
                        regular_blocks: list[dict] = []
                        for b in blocks:
                            if b["lang"].lower() in ("json", "") and _looks_like_tool_call(b["code"]):
                                try:
                                    parsed = json.loads(b["code"].strip())
                                    fake_calls.append({
                                        "name": parsed["name"],
                                        "args": parsed["arguments"] if isinstance(parsed["arguments"], dict) else {},
                                    })
                                except Exception:
                                    regular_blocks.append(b)
                            else:
                                regular_blocks.append(b)
                        fake_calls += _extract_fake_tool_calls(content)

                        if fake_calls:
                            handled = True
                            yield {"type": "token", "content": "\n\n> ⚙️ Exécution des actions détectées…\n\n"}
                            created = []
                            for i, fc in enumerate(fake_calls):
                                yield {"type": "tool_start", "name": fc["name"], "args": fc["args"]}
                                try:
                                    result = call_tool(fc["name"], fc["args"])
                                except Exception as e:
                                    result = f"Erreur : {e}"
                                self.history.append({"role": "tool", "tool_call_id": f"fake_{i}", "content": result})
                                yield {"type": "tool_end", "name": fc["name"], "result": result}
                                if "path" in fc["args"]:
                                    created.append(fc["args"]["path"])
                            if created:
                                names = ", ".join(f"`{n}`" for n in created)
                                yield {"type": "token", "content": f"\n\n📝 Fichier(s) créé(s) : {names}\n"}

                        # Priorité 3 supprimée : les blocs de code sans ``lang:chemin`` ne sont
                        # plus auto-appliqués — cela causait des écrasements de fichiers accidentels
                        # quand le modèle donnait un "exemple" ou une "version finale".

                self._save()
                yield {"type": "conv_meta", "conv": self.current_conv}
                return

            self.history.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": [
                    {
                        "id": getattr(tc, "id", f"call_{i}"),
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
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

                    # ── Demande de confirmation pour les actions sensibles ────
                    if name in SENSITIVE_TOOLS:
                        cid, event = confirm_manager.request(name, args)
                        yield {"type": "confirm", "id": cid, "tool": name, "args": args}
                        event.wait(timeout=120)   # bloque jusqu'à réponse utilisateur
                        approved = confirm_manager.get_result(cid)
                        if not approved:
                            result = "Action refusée par l'utilisateur."
                            yield {"type": "tool_denied", "name": name}
                            self.history.append({
                                "role": "tool", "tool_call_id": call_id, "content": result,
                            })
                            continue

                    # ── Auto-inférence du chemin si create_file appelé sans path ──
                    if name == "create_file" and "path" not in args and "content" in args:
                        import os as _os
                        code = args["content"]
                        code_low = code[:400].lower()
                        # Déduire l'extension depuis le contenu
                        if any(kw in code_low for kw in ("import pygame", "pygame.init", "pygame.display")):
                            _ext = "py"
                        elif any(kw in code_low for kw in ("from flask", "import flask", "from fastapi", "import fastapi")):
                            _ext = "py"
                        elif "<!doctype html" in code_low or "<html" in code_low:
                            _ext = "html"
                        elif code_low.strip().startswith("{") or code_low.strip().startswith("["):
                            _ext = "json"
                        elif "import " in code_low or "def " in code_low or "class " in code_low:
                            _ext = "py"
                        else:
                            _ext = "py"
                        # Inférence intelligente du nom de fichier
                        # On passe aussi le texte courant du modèle (il y a dit le nom)
                        guessed = _smart_infer_path(self.history, code, _ext, model_text=content)
                        wpath = ws.get_workspace()
                        if wpath:
                            guessed = _os.path.join(wpath, guessed)
                        args["path"] = guessed
                        yield {"type": "token", "content": f"\n> 📁 Chemin inféré : `{_os.path.basename(guessed)}`\n"}

                    yield {"type": "tool_start", "name": name, "args": args}
                    result = call_tool(name, args)
                    if name == "save_memory":
                        self.history[0]["content"] = _build_system_prompt()

                    # Tracking des fichiers lus (pour auto-détection des modifications)
                    if name == "read_file":
                        fpath = args.get("path", "")
                        if fpath not in recently_read:
                            recently_read.append(fpath)
                        read_counts[fpath] = read_counts.get(fpath, 0) + 1
                        if read_counts[fpath] >= 2:
                            # Le modèle relit le même fichier sans le modifier → l'inciter à agir
                            hint = (
                                "\n\n⚠️ [SYSTÈME] Tu as lu ce fichier plusieurs fois sans le modifier. "
                                "Applique maintenant les changements avec des blocs SEARCH/REPLACE ciblés "
                                f"(max {40} lignes par bloc SEARCH). Ne réécris PAS le fichier entier."
                            )
                            result = result + hint
                            read_counts[fpath] = 0  # reset pour éviter une boucle infinie

                    elif name in ("patch_file", "patch_file_lines", "create_file"):
                        read_counts.clear()   # reset après une modification

                    yield {"type": "tool_end", "name": name, "result": result[:600]}
                except Exception as e:
                    result = f"Tool error: {e}"
                    yield {"type": "tool_end", "name": name, "result": result}
                self.history.append({
                    "role": "tool", "tool_call_id": call_id, "content": result,
                })

    # ── Sync chat (CLI) ───────────────────────────────────────────────────────

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})
        while True:
            stream = ollama.chat(
                model=self.model, messages=self._trimmed_history(),
                tools=TOOL_SCHEMAS, stream=True,
            )
            content, tool_calls, first = "", None, True
            for chunk in stream:
                msg = chunk.message
                if msg.tool_calls: tool_calls = msg.tool_calls
                if msg.content:
                    if first: print(Fore.GREEN, end="", flush=True); first = False
                    print(msg.content, end="", flush=True)
                    content += msg.content
            if content: print(Style.RESET_ALL)
            if not tool_calls:
                self.history.append({"role": "assistant", "content": content})
                self._save()
                return content
            self.history.append({"role": "assistant", "content": content or "", "tool_calls": [
                {"id": getattr(tc, "id", f"call_{i}"), "type": "function",
                 "function": {"name": tc.function.name, "arguments": _tool_args(tc, i)}}
                for i, tc in enumerate(tool_calls)
            ]})
            for i, tc in enumerate(tool_calls):
                name, args, call_id = tc.function.name, _tool_args(tc, i), getattr(tc, "id", f"call_{i}")
                print(Fore.YELLOW + f"\n  [outil] {name}({args})" + Style.RESET_ALL)
                result = call_tool(name, args)
                if name == "save_memory": self.history[0]["content"] = _build_system_prompt()
                print(Fore.CYAN + f"  [résultat] {result[:300]}" + Style.RESET_ALL)
                self.history.append({"role": "tool", "tool_call_id": call_id, "content": result})

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_history(self) -> list[dict]:
        return [m for m in self.history[1:]
                if m.get("role") in ("user", "assistant") and m.get("content")]

    def show_memory(self):
        notes = mem.load_notes()
        print(Fore.CYAN + "\n── Notes ──\n" + Style.RESET_ALL + (notes or "(aucune)"))

    def reset_memory(self):
        mem.clear_notes()
        self.history[0]["content"] = _build_system_prompt()
        print(Fore.YELLOW + "Notes long-terme effacées." + Style.RESET_ALL)

    def refresh_system_prompt(self):
        if self.history:
            self.history[0]["content"] = _build_system_prompt()

    def set_model(self, model: str):
        self.model = model
