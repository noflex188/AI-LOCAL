import os
import sys
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from ddgs import DDGS
import memory as mem

# Répertoire Scripts du venv courant (ex: E:/ai/venv/Scripts)
_VENV_BIN = os.path.dirname(sys.executable)


# ── Path sandboxing ─────────────────────────────────────────────────────────

def _safe_path(path: str) -> str:
    """
    Résout et valide un chemin fichier.
    - Si un workspace est actif : les chemins relatifs y sont résolus,
      les chemins absolus DOIVENT être à l'intérieur.
    - Lève ValueError si le chemin est en dehors du workspace.
    """
    import workspace as ws
    wpath = ws.get_workspace()

    if wpath:
        # Résoudre les chemins relatifs par rapport au workspace
        if not os.path.isabs(path):
            path = os.path.join(wpath, path)
        # Normaliser pour éviter les traversées (../../)
        path = os.path.normpath(os.path.abspath(path))
        wpath_norm = os.path.normpath(os.path.abspath(wpath))
        if not path.startswith(wpath_norm + os.sep) and path != wpath_norm:
            raise ValueError(
                f"Accès refusé : {path} est en dehors du workspace ({wpath_norm}). "
                f"Utilise un chemin relatif au projet."
            )
    else:
        path = os.path.normpath(os.path.abspath(path))

    return path


# ── File tools ───────────────────────────────────────────────────────────────

def _validate_python(content: str, path: str) -> str | None:
    """
    Vérifie la syntaxe Python d'un fichier .py avant de l'écrire.
    Retourne un message d'erreur si invalide, None si OK.
    """
    if not path.endswith(".py"):
        return None
    import ast
    try:
        ast.parse(content)
        return None
    except SyntaxError as e:
        return f"Syntaxe invalide ligne {e.lineno}: {e.msg}"


def _make_diff(old_content: str, new_content: str, path: str) -> str:
    """Compute a unified diff between old and new content."""
    import difflib
    name = os.path.basename(path)
    diff = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{name}",
        tofile=f"b/{name}",
        n=2,
    ))
    return "".join(diff)


def create_file(path: str, content: str) -> str:
    path = _safe_path(path)
    old_content = None
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except Exception:
            pass
    # Validation syntaxe Python avant d'écrire
    syntax_err = _validate_python(content, path)
    if syntax_err:
        return (
            f"REFUSÉ — {syntax_err}. "
            f"Le fichier n'a PAS été modifié. Corrige l'erreur de syntaxe d'abord."
        )

    dir_ = os.path.dirname(path)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if old_content is not None and old_content != content:
        diff = _make_diff(old_content, content, path)
        if diff:
            return f"File updated: {path}\n<<<DIFF>>>\n{diff}\n<<<END_DIFF>>>"
    return f"File created: {path}"


def read_file(path: str) -> str:
    path = _safe_path(path)
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    numbered = "".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines))
    return f"File: {path} ({len(lines)} lines)\n\n{numbered}"


def list_dir(path: str = ".") -> str:
    path = _safe_path(path)
    if not os.path.exists(path):
        return f"Error: path not found: {path}"
    entries = []
    for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name)):
        prefix = "[dir] " if entry.is_dir() else "[file]"
        entries.append(f"{prefix} {entry.name}")
    return "\n".join(entries) if entries else "(empty)"


def _smart_replace(content: str, old: str, new: str) -> tuple:
    """
    Remplace old par new dans content avec 3 niveaux de matching.
    Retourne (nouveau_contenu, méthode) en cas de succès, ou (None, hint) en échec.
    """
    # ── Niveau 1 : correspondance exacte ──
    if old in content:
        return content.replace(old, new, 1), "exact"

    old_lines = old.splitlines()
    content_lines = content.splitlines()
    trail_nl = content.endswith("\n")

    def _rebuild(before, replacement, after):
        r = "\n".join(before + replacement.splitlines() + after)
        return r + "\n" if trail_nl else r

    # ── Niveau 2 : correspondance avec normalisation des espaces ──
    old_stripped = [l.strip() for l in old_lines]
    for i in range(len(content_lines) - len(old_lines) + 1):
        window = [l.strip() for l in content_lines[i:i + len(old_lines)]]
        if window == old_stripped:
            return _rebuild(content_lines[:i], new, content_lines[i + len(old_lines):]), "whitespace"

    # ── Niveau 3 : correspondance floue (SequenceMatcher) ──
    from difflib import SequenceMatcher
    best_ratio, best_start, best_len = 0, -1, len(old_lines)
    min_win = max(1, len(old_lines) - 3)
    max_win = min(len(content_lines) + 1, len(old_lines) + 4)
    for wlen in range(min_win, max_win):
        for i in range(len(content_lines) - wlen + 1):
            candidate = "\n".join(content_lines[i:i + wlen])
            ratio = SequenceMatcher(None, old, candidate).ratio()
            if ratio > best_ratio:
                best_ratio, best_start, best_len = ratio, i, wlen

    if best_ratio >= 0.6 and best_start >= 0:
        return _rebuild(content_lines[:best_start], new, content_lines[best_start + best_len:]), f"fuzzy ({best_ratio:.0%})"

    # ── Échec : fournir un indice utile ──
    hint = ""
    if best_start >= 0:
        hint = f"Contenu le plus similaire à la ligne ~{best_start + 1} (similarité {best_ratio:.0%})"
    else:
        first_line = old_lines[0].strip() if old_lines else ""
        candidates = [i + 1 for i, l in enumerate(content_lines) if l.strip() == first_line]
        if candidates:
            hint = f"La première ligne correspond aux lignes {candidates[:5]}, vérifier le contexte"
    return None, hint


def patch_file(path: str, old: str, new: str) -> str:
    """Replace text in a file with smart matching (exact → whitespace → fuzzy)."""
    path = _safe_path(path)
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    result, info = _smart_replace(content, old, new)
    if result is not None:
        # Validation syntaxe Python avant d'écrire
        syntax_err = _validate_python(result, path)
        if syntax_err:
            return (
                f"REFUSÉ — {syntax_err}. "
                f"Le patch n'a PAS été appliqué. Corrige l'erreur de syntaxe dans ton bloc REPLACE."
            )
        with open(path, "w", encoding="utf-8") as f:
            f.write(result)
        diff = _make_diff(content, result, path)
        status = f"Patched: {path}" + (f" ({info})" if info != "exact" else "")
        if diff:
            return f"{status}\n<<<DIFF>>>\n{diff}\n<<<END_DIFF>>>"
        return status

    return (
        f"Error: text to replace not found in {path}. {info}. "
        f"Call read_file('{path}') first to see the exact content."
    )


def patch_file_lines(path: str, start_line: int, end_line: int, new_content: str) -> str:
    """Replace lines start_line to end_line (1-indexed, inclusive) with new_content."""
    path = _safe_path(path)
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    total = len(lines)
    if start_line < 1 or end_line > total or start_line > end_line:
        return f"Error: invalid line range {start_line}-{end_line} (file has {total} lines)."
    new_lines = new_content if new_content.endswith("\n") else new_content + "\n"
    lines[start_line - 1:end_line] = [new_lines]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return f"Patched lines {start_line}-{end_line} in {path}"


def grep_files(pattern: str, path: str = ".", file_glob: str = "*") -> str:
    """Search for a pattern in files. Returns matching lines with file:line context."""
    path = _safe_path(path)
    import re, fnmatch
    from pathlib import Path
    results = []
    search_path = Path(path)
    if not search_path.exists():
        return f"Error: path not found: {path}"
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex: {e}"
    skip_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv', 'dist', 'build'}
    for f in search_path.rglob(file_glob):
        if any(p in f.parts for p in skip_dirs):
            continue
        if not f.is_file():
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    results.append(f"{f}:{i}: {line.rstrip()}")
                    if len(results) >= 50:
                        results.append("... (truncated at 50 results)")
                        return "\n".join(results)
        except Exception:
            continue
    return "\n".join(results) if results else "No matches found."


def delete_file(path: str) -> str:
    path = _safe_path(path)
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    os.remove(path)
    return f"Deleted: {path}"


# ── Shell tool ────────────────────────────────────────────────────────────────

def pip_install(packages) -> str:
    """Install Python packages via pip into the current virtual environment."""
    if not packages:
        return "Error: no packages specified. Provide a list of package names, e.g. ['pygame', 'numpy']."
    if isinstance(packages, str):
        pkg_str = packages
    elif isinstance(packages, list):
        pkg_str = " ".join(str(p) for p in packages if p)
    else:
        pkg_str = str(packages)
    if not pkg_str.strip():
        return "Error: no packages specified."
    return run_command(f"pip install {pkg_str}")


def run_command(command: str) -> str:
    """Run a shell command and return stdout + stderr (max 4000 chars)."""
    try:
        # Injecter le venv dans PATH pour que pip/python utilisent l'environnement
        # virtuel sans avoir besoin de droits administrateur
        env = os.environ.copy()
        env["PATH"]        = _VENV_BIN + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = os.path.dirname(_VENV_BIN)

        # Exécuter dans le workspace si actif, sinon cwd
        import workspace as ws
        cwd = ws.get_workspace() or os.getcwd()

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=cwd,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += result.stderr
        output = output.strip()
        if not output:
            output = f"(exit code {result.returncode}, no output)"
        elif len(output) > 4000:
            output = output[:4000] + "\n... (truncated)"
        return output
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30s"
    except Exception as e:
        return f"Error: {e}"


# ── Date/time tool ────────────────────────────────────────────────────────────

def get_datetime() -> str:
    now = datetime.now()
    return now.strftime("Date : %A %d %B %Y  —  Heure : %H:%M:%S")


# ── Web tools ─────────────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> str:
    """Search the web with DuckDuckGo."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r['title']}\n    {r['href']}\n    {r['body']}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"


def fetch_url(url: str) -> str:
    """Fetch the text content of a webpage (stripped of HTML tags, max 5000 chars)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Strip HTML tags simply
        import re
        text = re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"
        return text
    except urllib.error.URLError as e:
        return f"Fetch error: {e}"
    except Exception as e:
        return f"Fetch error: {e}"


# ── Memory tool ──────────────────────────────────────────────────────────────

def save_memory(note: str) -> str:
    """Save an important fact or preference to long-term memory."""
    mem.append_note(note)
    return f"Mémorisé : {note}"


# ── RAG tool ──────────────────────────────────────────────────────────────────

def search_project(query: str) -> str:
    """Search indexed project files by semantic similarity."""
    import rag, workspace as ws
    wpath = ws.get_workspace()
    if not wpath:
        return "Aucun workspace ouvert. Ouvre d'abord un dossier de projet."
    if not rag.is_indexed(wpath):
        return "Le projet n'est pas encore indexé. Clique sur 'Indexer' dans l'onglet Projet."
    results = rag.search(wpath, query)
    if not results:
        return "Aucun résultat pertinent trouvé."
    lines = []
    for r in results:
        lines.append(f"[{r['file']}] (score: {r['score']})\n{r['content']}")
    return "\n\n---\n".join(lines)


# ── Registry ──────────────────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "create_file":      create_file,
    "read_file":        read_file,
    "patch_file":       patch_file,
    "patch_file_lines": patch_file_lines,
    "grep_files":       grep_files,
    "list_dir":         list_dir,
    "delete_file":      delete_file,
    "run_command":      run_command,
    "pip_install":      pip_install,
    "get_datetime":     get_datetime,
    "web_search":       web_search,
    "fetch_url":        fetch_url,
    "save_memory":      save_memory,
    "search_project":   search_project,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create or overwrite a file with the given content. Use this to write any code or text file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string", "description": "File path, e.g. 'src/app.py'"},
                    "content": {"type": "string", "description": "Full content of the file"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file to read"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and subdirectories in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '.')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": (
                "Edit a file by replacing an exact block of text with new content. "
                "Use this to fix bugs or make targeted changes without rewriting the whole file. "
                "Always use read_file first to get the exact text to replace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file to patch"},
                    "old":  {"type": "string", "description": "Exact text to replace (must match the file exactly, including indentation and newlines)"},
                    "new":  {"type": "string", "description": "New text to put in its place"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file from disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path of the file to delete"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell command and return its output. "
                "Use this to run Python scripts, execute tests, git commands, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute, e.g. 'python app.py'"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pip_install",
            "description": (
                "Install one or more Python packages into the current virtual environment using pip. "
                "Use this instead of run_command when you need to install dependencies."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of package names to install, e.g. ['pygame', 'numpy']",
                    },
                },
                "required": ["packages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_datetime",
            "description": "Get the current local date and time. Use this whenever the user asks what time or date it is.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web with DuckDuckGo. Use when you need up-to-date info, "
                "documentation, or are unsure about something."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query":       {"type": "string",  "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Number of results (default 5, max 10)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Save an important fact, user preference, or project detail to long-term memory. "
                "Use this proactively when the user shares something worth remembering across sessions "
                "(name, language preference, project info, habits, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "The fact or information to remember"},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_project",
            "description": (
                "Search the indexed project files by semantic similarity. "
                "Use this to find relevant code, functions, classes, or documentation "
                "in the current workspace before reading or modifying files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for, e.g. 'authentication middleware' or 'database connection'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Fetch and read the text content of a specific webpage URL. "
                "Use this after web_search to read a page in detail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch, e.g. 'https://docs.python.org/...'"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file_lines",
            "description": (
                "Replace a range of lines in a file with new content. "
                "Use this as an alternative to patch_file when you know the line numbers. "
                "First use read_file to see line numbers, then replace the exact range."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":        {"type": "string",  "description": "Path of the file to edit"},
                    "start_line":  {"type": "integer", "description": "First line to replace (1-indexed)"},
                    "end_line":    {"type": "integer", "description": "Last line to replace (1-indexed, inclusive)"},
                    "new_content": {"type": "string",  "description": "New content to put in place of those lines"},
                },
                "required": ["path", "start_line", "end_line", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_files",
            "description": (
                "Search for a text pattern (regex) across files in a directory. "
                "Returns matching lines with file path and line number. "
                "Use this to find where a function is defined, where a variable is used, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern":   {"type": "string", "description": "Regex or text to search for, e.g. 'def login' or 'import os'"},
                    "path":      {"type": "string", "description": "Directory to search in (default '.')"},
                    "file_glob": {"type": "string", "description": "File filter glob, e.g. '*.py', '*.js' (default '*')"},
                },
                "required": ["pattern"],
            },
        },
    },
]


def call_tool(name: str, args: dict) -> str:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        # Suggestions pour les noms d'outils courants mal orthographiés
        aliases = {
            "pip_install": "pip_install",
            "install_packages": "pip_install",
            "install_package": "pip_install",
            "write_file": "create_file",
            "save_file": "create_file",
            "edit_file": "patch_file",
            "modify_file": "patch_file",
            "execute_command": "run_command",
            "shell_command": "run_command",
        }
        suggestion = aliases.get(name)
        if suggestion:
            return call_tool(suggestion, args)
        return f"Unknown tool: {name}. Available: {', '.join(TOOL_FUNCTIONS.keys())}"
    try:
        return fn(**args)
    except TypeError as e:
        # Message d'erreur utile pour les arguments manquants
        import inspect
        sig = inspect.signature(fn)
        required = [
            p for p, v in sig.parameters.items()
            if v.default is inspect.Parameter.empty and v.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        missing = [p for p in required if p not in args]
        if missing:
            return (
                f"Tool error ({name}): missing required argument(s): {', '.join(missing)}. "
                f"Provided: {list(args.keys())}. "
                f"Required: {required}."
            )
        return f"Tool error ({name}): {e}"
    except Exception as e:
        return f"Tool error ({name}): {e}"
