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

# Taille maximale d'un bloc SEARCH (lignes). Au-delà = quasi-réécriture → refusé.
MAX_SEARCH_LINES = 40

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
        search_text = m.group(2)
        search_lines = search_text.count('\n') + 1
        used.append((m.start(), m.end()))
        if search_lines > MAX_SEARCH_LINES:
            # Bloc SEARCH trop grand = réécriture déguisée → on le rejette
            actions.append({
                "type": "too_large",
                "path": _resolve(m.group(1)),
                "lines": search_lines,
            })
            continue
        actions.append({
            "type": "edit",
            "path": _resolve(m.group(1)),
            "search": search_text,
            "replace": m.group(3),
        })

    # Note : l'auto-détection des blocs sans chemin (ancienne priorité 3) a été
    # supprimée — elle causait des écrasements accidentels de fichiers quand le
    # modèle produisait un "exemple de code" ou une "version finale" sans
    # spécifier explicitement de fichier cible.
    # Le modèle DOIT utiliser ```lang:chemin``` pour créer/réécrire un fichier.

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
        elif action["type"] == "too_large":
            name = os.path.basename(action["path"])
            r = (
                f"REFUSÉ — bloc SEARCH trop grand ({action['lines']} lignes, max {MAX_SEARCH_LINES}). "
                f"Découpe la modification en plusieurs petits blocs SEARCH/REPLACE ciblés "
                f"(une fonction ou une section à la fois), ou utilise ```lang:{name} si tu dois "
                f"réécrire le fichier entièrement (fichier court uniquement)."
            )
            results.append({
                "name": "patch_file",
                "args": {"path": action["path"]},
                "result": r,
            })
    return results
