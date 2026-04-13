import json
import ollama
from colorama import Fore, Style, init as colorama_init
from tools import TOOL_SCHEMAS, call_tool
import memory as mem
from context import build_context_block
from confirmation import confirm_manager, SENSITIVE_TOOLS

colorama_init(autoreset=True)

MODEL           = "gemma4:26b"
PREFERRED_MODELS = ["gemma4:26b", "gemma4:e4b"]
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
| create_file   | Créer un nouveau fichier ou réécrire entièrement         |
| read_file     | Lire un fichier existant                                 |
| patch_file    | Corriger une portion précise d'un fichier existant       |
| list_dir      | Lister un répertoire                                     |
| delete_file   | Supprimer un fichier                                     |
| run_command   | Exécuter une commande shell (python, pip, git…)          |
| get_datetime  | Obtenir la date et l'heure locale exactes                |
| save_memory   | Mémoriser un fait important sur l'utilisateur ou un projet|

## Règles d'utilisation des outils
- **web_search** : utilise-le dès que tu as un doute, que l'information peut être datée, ou que l'utilisateur te demande quelque chose de factuel. Ne suppose jamais — cherche.
- **fetch_url** : après un web_search, si un résultat semble contenir la réponse précise, lis la page.
- **get_datetime** : obligatoire pour toute question sur l'heure ou la date. Ne devine jamais.
- **run_command** : après avoir créé du code, propose de l'exécuter. Les commandes s'exécutent dans le venv Python du projet — `pip install` fonctionne sans droits admin. Ne jamais utiliser `sudo`, `runas` ou des options qui nécessitent des droits élevés.
- **save_memory** : utilise-le dès que l'utilisateur mentionne son prénom, une préférence, un projet en cours. Fais-le naturellement sans le demander.
- Tu peux enchaîner plusieurs outils dans le même tour si nécessaire.

## Règles absolues pour le code — NE JAMAIS DÉROGER

**RÈGLE N°1 — Tu modifies TOUJOURS les fichiers toi-même.**
Tu n'afficheras JAMAIS du code dans ta réponse en disant "voici la modification" ou "remplace X par Y". Tu utilises les outils. Point.

**RÈGLE N°2 — Workflow obligatoire pour toute modification de fichier existant :**
1. `read_file` — lis le fichier pour avoir le contenu exact
2. `patch_file` — remplace uniquement la portion concernée
3. Confirme à l'utilisateur ce qui a été changé

**RÈGLE N°3 — `create_file` vs `patch_file` :**
- `create_file` : créer un nouveau fichier, ou réécrire entièrement (refactoring complet)
- `patch_file` : toute correction partielle, ajout de fonction, modification de ligne — utilise TOUJOURS `read_file` avant pour obtenir le texte exact

**RÈGLE N°4 — Arborescence complète autorisée.**
Tu peux et dois créer une arborescence de fichiers complète si le projet le demande (ex: `src/`, `components/`, `utils/`, `tests/`, etc.). `create_file` crée automatiquement les dossiers intermédiaires. N'hésite pas à organiser le code proprement dès le départ.

**RÈGLE N°5 — Erreur ou traceback :**
Lis le fichier, identifie la ligne, applique `patch_file`, relance le code pour vérifier.

## Avant d'agir : clarifier si nécessaire
Si une demande manque de contexte (objectif flou, stack non précisée, etc.), **pose d'abord des questions ciblées**.
- Maximum 3 questions à la fois, regroupées en un seul message numéroté.
- Si tu peux déduire depuis le contexte ou la mémoire, déduis — ne demande pas.
- Pour les tâches simples et sans ambiguïté, agis directement.

## Format des réponses
- Pour du code, utilise toujours des blocs markdown avec le langage (```python, ```bash, etc.).
- Pour des listes de choix ou comparatifs, utilise un tableau ou des puces claires.
- Évite les introductions inutiles du type "Bien sûr !" ou "Absolument !".
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
        msg = self._build_user_message(user_message, attachments or [])
        self.history.append(msg)

        while True:
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

                    yield {"type": "tool_start", "name": name, "args": args}
                    result = call_tool(name, args)
                    if name == "save_memory":
                        self.history[0]["content"] = _build_system_prompt()
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
