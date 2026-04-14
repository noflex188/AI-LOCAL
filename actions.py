"""
Parseur d'actions texte pour le mode agent.
Détecte créations/modifications de fichiers dans la sortie texte du modèle,
en utilisant un format inspiré d'Aider : blocs de code avec chemin et SEARCH/REPLACE.

Trois niveaux de détection :
1. ```lang:chemin/fichier.ext  →  création / réécriture complète
2. SEARCH/REPLACE blocks      →  édition partielle avec fuzzy matching
3. Blocs de code + contexte   →  auto-détection du fichier cible (fichier récemment lu)
"""
import re
import os
from tools import call_tool

# Pattern pour les chemins de fichiers (Windows absolu + relatif)
_PATH_PAT = r'((?:[A-Za-z]:[/\\])?(?:[\w.\-]+[/\\])*[\w.\-]+\.[\w]+)'

# Extension → langages code block
_EXT_LANG = {
    "py": "python", "js": "javascript", "ts": "typescript", "ps1": "powershell",
    "sh": "bash", "html": "html", "css": "css", "json": "json", "sql": "sql",
    "rs": "rust", "go": "go", "java": "java", "cpp": "cpp", "c": "c",
    "rb": "ruby", "php": "php", "swift": "swift", "yml": "yaml", "yaml": "yaml",
}
_LANG_EXT = {v: k for k, v in _EXT_LANG.items()}
_LANG_EXT.update({"python": "py", "javascript": "js", "typescript": "ts",
                   "powershell": "ps1", "bash": "sh", "shell": "sh"})


def parse_actions(text: str, workspace: str = "", recently_read: list[str] = None) -> list[dict]:
    """
    Parse le texte brut du modèle pour extraire les actions fichier.

    Formats reconnus :

    1. Bloc de code avec chemin :
       ```lang:chemin/fichier.ext
       contenu
       ```

    2. SEARCH/REPLACE (édition partielle) :
       chemin/fichier.ext
       <<<<<<< SEARCH
       ancien code
       =======
       nouveau code
       >>>>>>> REPLACE

    3. Bloc de code sans chemin mais fichier récemment lu :
       → auto-assigné au dernier fichier lu avec la même extension
    """
    actions = []
    used = []  # (start, end) ranges déjà matchées
    recently_read = recently_read or []

    def _overlaps(s, e):
        return any(a < e and s < b for a, b in used)

    def _resolve(path):
        path = path.replace("/", os.sep).replace("\\", os.sep)
        if workspace and not os.path.isabs(path):
            return os.path.join(workspace, path)
        return path

    # ── 1. Code blocks avec chemin dans l'info string ──
    # ```lang:path/file.ext  ou  ```lang path/file.ext
    for m in re.finditer(
        r'```(\w+)[: ]' + _PATH_PAT + r'\s*\n([\s\S]*?)```',
        text
    ):
        if _overlaps(m.start(), m.end()):
            continue
        used.append((m.start(), m.end()))
        actions.append({
            "type": "create",
            "path": _resolve(m.group(2)),
            "content": m.group(3),
        })

    # ── 2. SEARCH/REPLACE blocks (style git merge conflict) ──
    sr_pattern = (
        r'(?:(?:EDIT|FICHIER|MODIFIER)\s*:\s*)?'
        + _PATH_PAT + r'\s*\n'
        r'<{3,7}\s*SEARCH\s*\n'
        r'([\s\S]*?)\n'
        r'={3,7}\n'
        r'([\s\S]*?)\n'
        r'>{3,7}\s*REPLACE'
    )
    for m in re.finditer(sr_pattern, text):
        if _overlaps(m.start(), m.end()):
            continue
        used.append((m.start(), m.end()))
        actions.append({
            "type": "edit",
            "path": _resolve(m.group(1)),
            "search": m.group(2),
            "replace": m.group(3),
        })

    # ── 3. Code blocks sans chemin → auto-détection via fichiers récemment lus ──
    if recently_read:
        for m in re.finditer(r'```(\w+)\n([\s\S]*?)```', text):
            if _overlaps(m.start(), m.end()):
                continue
            lang = m.group(1).lower()
            code = m.group(2)
            # Ignorer les blocs JSON qui sont des faux tool calls
            if lang in ("json", ""):
                continue
            # Ignorer les blocs très courts (probablement des exemples inline)
            if code.count("\n") < 3:
                continue
            # Trouver le fichier récemment lu avec la même extension
            ext = _LANG_EXT.get(lang, lang)
            target = None
            for fpath in reversed(recently_read):
                if fpath.lower().endswith(f".{ext}"):
                    target = fpath
                    break
            if target:
                used.append((m.start(), m.end()))
                actions.append({
                    "type": "create",
                    "path": target,
                    "content": code,
                })

    return actions


def execute_actions(actions: list[dict]) -> list[dict]:
    """Exécute les actions détectées et retourne les résultats."""
    results = []
    for action in actions:
        if action["type"] == "create":
            r = call_tool("create_file", {
                "path": action["path"],
                "content": action["content"],
            })
            results.append({
                "name": "create_file",
                "args": {"path": action["path"]},
                "result": r,
            })
        elif action["type"] == "edit":
            r = call_tool("patch_file", {
                "path": action["path"],
                "old": action["search"],
                "new": action["replace"],
            })
            results.append({
                "name": "patch_file",
                "args": {"path": action["path"]},
                "result": r,
            })
    return results
