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


# ── File tools ───────────────────────────────────────────────────────────────

def create_file(path: str, content: str) -> str:
    dir_ = os.path.dirname(path)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"File created: {path}"


def read_file(path: str) -> str:
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def list_dir(path: str = ".") -> str:
    if not os.path.exists(path):
        return f"Error: path not found: {path}"
    entries = []
    for entry in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name)):
        prefix = "[dir] " if entry.is_dir() else "[file]"
        entries.append(f"{prefix} {entry.name}")
    return "\n".join(entries) if entries else "(empty)"


def patch_file(path: str, old: str, new: str) -> str:
    """Replace the first occurrence of `old` with `new` in a file."""
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if old not in content:
        return f"Error: the text to replace was not found in {path}. Use read_file to check the exact content first."
    updated = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    return f"Patched: {path}"


def delete_file(path: str) -> str:
    if not os.path.exists(path):
        return f"Error: file not found: {path}"
    os.remove(path)
    return f"Deleted: {path}"


# ── Shell tool ────────────────────────────────────────────────────────────────

def run_command(command: str) -> str:
    """Run a shell command and return stdout + stderr (max 4000 chars)."""
    try:
        # Injecter le venv dans PATH pour que pip/python utilisent l'environnement
        # virtuel sans avoir besoin de droits administrateur
        env = os.environ.copy()
        env["PATH"]        = _VENV_BIN + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = os.path.dirname(_VENV_BIN)

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=os.getcwd(),
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
    "create_file":    create_file,
    "read_file":      read_file,
    "patch_file":     patch_file,
    "list_dir":       list_dir,
    "delete_file":    delete_file,
    "run_command":    run_command,
    "get_datetime":   get_datetime,
    "web_search":     web_search,
    "fetch_url":      fetch_url,
    "save_memory":    save_memory,
    "search_project": search_project,
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
                "Use this to run Python scripts, install packages, execute tests, etc."
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
]


def call_tool(name: str, args: dict) -> str:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    try:
        return fn(**args)
    except Exception as e:
        return f"Tool error ({name}): {e}"
