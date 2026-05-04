import os
import json
import subprocess
import re
import sys
import shutil
import itertools
import threading
import time
from datetime import datetime, timezone, timedelta, date as _date

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

def completion(*args, **kwargs):
    from litellm import completion as _c
    return _c(*args, **kwargs)

# ── Context system (lazy import — only loads when used) ──
_ctx_loader    = None
_ctx_summarizer = None

def _get_loader():
    global _ctx_loader
    if _ctx_loader is None:
        try:
            import importlib.util, pathlib
            spec = importlib.util.spec_from_file_location(
                "loader", pathlib.Path(__file__).parent / "src" / "context" / "loader.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _ctx_loader = mod
        except Exception as e:
            print(f"\033[91m  ⎿ Context loader unavailable: {e}\033[0m")
    return _ctx_loader

def _get_summarizer():
    global _ctx_summarizer
    if _ctx_summarizer is None:
        try:
            import importlib.util, pathlib
            spec = importlib.util.spec_from_file_location(
                "summarizer", pathlib.Path(__file__).parent / "src" / "context" / "summarizer.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _ctx_summarizer = mod
        except Exception as e:
            print(f"\033[91m  ⎿ Summarizer unavailable: {e}\033[0m")
    return _ctx_summarizer

_active_context_modes: list[str] = []
_last_user_prompt: str = ""

# ==========================================
# 1. THE GRID (Dynamic Config Router)
# ==========================================
CLI_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CLI_DIR, "div_config.json")
PERSONA_FILE = os.path.join(CLI_DIR, "div_persona.txt")
MEMORY_FILE = os.path.join(CLI_DIR, "div_memory.json")

DEFAULT_MODELS = {
    "talk":  {"model": "openai/gpt-4o-mini", "key": ""},
    "code":  {"model": "openai/gpt-4.1",     "key": ""},
    "brain": {"model": "openai/gpt-5.4",     "key": ""},
    "full":  {"model": "openai/gpt-4.1",     "key": ""},
}

# Launch onboarding wizard on first run (no config or no keys set)
def _needs_onboard():
    if not os.path.exists(CONFIG_FILE):
        return True
    try:
        with open(CONFIG_FILE) as _f:
            _d = json.load(_f)
        return not any(_d.get("models", {}).get(m, {}).get("key") for m in ["talk", "code", "brain"])
    except Exception:
        return True

if _needs_onboard():
    print("\033[94m\n[divAI] First run detected — launching setup wizard...\033[0m")
    subprocess.run([sys.executable, os.path.join(CLI_DIR, "div_onboard.py")])

# Auto-fix old schemas and load configuration
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            if "talk" in data:
                MODELS, GLOBAL_VAULT = data, ""
                CANVAS_URL, CANVAS_TOKEN = "", ""
                with open(CONFIG_FILE, "w") as f2: json.dump({"models": MODELS, "vault": GLOBAL_VAULT, "canvas_url": "", "canvas_token": ""}, f2, indent=4)
            else:
                MODELS        = data.get("models", DEFAULT_MODELS)
                GLOBAL_VAULT  = data.get("vault", "")
                CANVAS_URL    = data.get("canvas_url", "")
                CANVAS_TOKEN  = data.get("canvas_token", "")
                LAST_BRIEFING   = data.get("last_briefing", "")
                LAST_SESSION_AT = data.get("last_session_at", "")
                WHISPER_KEY     = data.get("whisper_key", "") or data.get("models", {}).get("talk", {}).get("key", "")
                TTS_VOICE       = data.get("tts_voice", "en-US-AndrewNeural")
                TTS_RATE        = data.get("tts_rate", "+25%")
    except:
        MODELS, GLOBAL_VAULT, CANVAS_URL, CANVAS_TOKEN, LAST_BRIEFING, LAST_SESSION_AT, WHISPER_KEY, TTS_VOICE, TTS_RATE = DEFAULT_MODELS, "", "", "", "", "", "", "en-US-AndrewNeural", "+25%"
else:
    MODELS, GLOBAL_VAULT, CANVAS_URL, CANVAS_TOKEN, LAST_BRIEFING, LAST_SESSION_AT, WHISPER_KEY, TTS_VOICE, TTS_RATE = DEFAULT_MODELS, "", "", "", "", "", "", "en-US-AndrewNeural", "+25%"
    with open(CONFIG_FILE, "w") as f: json.dump({"models": MODELS, "vault": GLOBAL_VAULT, "canvas_url": "", "canvas_token": "", "last_briefing": "", "last_session_at": "", "whisper_key": "", "tts_voice": "en-US-AndrewNeural", "tts_rate": "+25%"}, f, indent=4)

TTS_ENABLED = False  # session toggle — not persisted

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump({"models": MODELS, "vault": GLOBAL_VAULT, "canvas_url": CANVAS_URL,
                   "canvas_token": CANVAS_TOKEN, "last_briefing": LAST_BRIEFING,
                   "last_session_at": LAST_SESSION_AT, "whisper_key": WHISPER_KEY,
                   "tts_voice": TTS_VOICE, "tts_rate": TTS_RATE}, f, indent=4)

# Auto-migrate stale model names to current defaults.
# Catches old providers (groq/deepseek/github) AND previous OpenAI defaults.
_STALE_MODELS = {
    "talk":  {"groq/llama-3.3-70b-versatile"},
    "code":  {"github/gpt-4o", "openai/gpt-4o", "openai/gpt-4"},
    "brain": {"deepseek/deepseek-reasoner", "openai/o4-mini", "openai/gpt-4o"},
    "full":  {"github/gpt-4o", "openai/gpt-4o"},
}
_TARGET_MODELS = {
    "talk":  "openai/gpt-4o-mini",
    "code":  "openai/gpt-4.1",
    "brain": "openai/gpt-5.4",
    "full":  "openai/gpt-4.1",
}
_openai_key = MODELS.get("full", {}).get("key", "")
_migrated = False
for _slot, _stale_set in _STALE_MODELS.items():
    _m = MODELS.get(_slot, {}).get("model", "")
    if _m in _stale_set or any(_m.startswith(p) for p in ("groq/", "deepseek/", "github/", "anthropic/")):
        MODELS[_slot] = {"model": _TARGET_MODELS[_slot], "key": MODELS.get(_slot, {}).get("key", "") or _openai_key}
        _migrated = True
if _migrated:
    save_config()

# ── Session gap tracking ──
_now_dt = datetime.now()
SESSION_GAP_HOURS = 0.0
if LAST_SESSION_AT:
    try:
        SESSION_GAP_HOURS = (_now_dt - datetime.fromisoformat(LAST_SESSION_AT)).total_seconds() / 3600
    except Exception:
        pass
LAST_SESSION_AT = _now_dt.isoformat()
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE) as _sf: _scfg = json.load(_sf)
        _scfg["last_session_at"] = LAST_SESSION_AT
        with open(CONFIG_FILE, "w") as _sf: json.dump(_scfg, _sf, indent=4)
    except Exception:
        pass

_MSG_FIELDS = {"role", "content", "name", "tool_calls", "tool_call_id", "function_call"}

def clean_messages(msgs):
    """Keep only standard OpenAI message fields — strips LiteLLM injected extras."""
    result = []
    for m in msgs:
        clean = {k: v for k, v in m.items() if k in _MSG_FIELDS}
        if isinstance(clean.get("content"), list):
            clean["content"] = [
                {k: v for k, v in p.items() if k in {"type", "text", "image_url"}}
                if isinstance(p, dict) else p
                for p in clean["content"]
            ]
        result.append(clean)
    return result

def _trim_messages(msgs, keep=30):
    """System messages + last `keep` convo turns, with orphaned tool-call sequences removed."""
    cleaned = clean_messages(msgs)
    system  = [m for m in cleaned if m.get("role") == "system"]
    convo   = [m for m in cleaned if m.get("role") != "system"]
    trimmed = list(convo[-keep:])

    # drop leading tool messages whose assistant caller was sliced off
    while trimmed and trimmed[0].get("role") == "tool":
        trimmed.pop(0)

    # drop assistant tool_call messages whose responses are missing or incomplete
    result = []
    i = 0
    while i < len(trimmed):
        msg = trimmed[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            expected = {tc["id"] for tc in msg["tool_calls"] if isinstance(tc, dict)}
            j = i + 1
            found = set()
            while j < len(trimmed) and trimmed[j].get("role") == "tool":
                found.add(trimmed[j].get("tool_call_id", ""))
                j += 1
            if expected.issubset(found):
                result.append(msg)
            else:
                i = j  # skip assistant + its dangling tool responses
                continue
        else:
            result.append(msg)
        i += 1

    return system + result

def route_message(text: str) -> str:
    t = text.lower()
    _shared = MODELS.get("full", {}).get("key", "")
    has_code  = bool(MODELS.get("code",  {}).get("key") or _shared)
    has_brain = bool(MODELS.get("brain", {}).get("key") or _shared)
    # Explicit programming task → code model
    if has_code and any(kw in t for kw in [
        "code", "script", "function", "class", "debug", "bug", "error",
        "implement", "refactor", "python", "javascript", "typescript",
        "html", "css", "sql", "```", "def ", "const ", "import ",
    ]):
        return "code"
    # Reasoning / planning / analysis / long messages → brain model
    if has_brain and (len(text) > 150 or any(kw in t for kw in [
        "explain", "why", "how does", "analyze", "compare", "plan",
        "strategy", "difference", "pros", "cons", "should i",
        "review", "essay", "summarize", "evaluate", "gameplan",
        "walkthrough", "step by step", "help me think", "roadmap",
    ])):
        return "brain"
    return "talk"

# ── Canvas integration ──
_canvas_cache   = None   # cached assignment list
_canvas_courses = None   # cached course list with IDs

def refresh_canvas_cache():
    global _canvas_cache
    if CANVAS_URL and CANVAS_TOKEN:
        try:
            from div_canvas import fetch_upcoming_assignments
            _canvas_cache = fetch_upcoming_assignments(CANVAS_URL, CANVAS_TOKEN)
        except Exception as e:
            _canvas_cache = [{"error": str(e)}]
    else:
        _canvas_cache = None

def refresh_canvas_courses():
    global _canvas_courses
    if CANVAS_URL and CANVAS_TOKEN:
        try:
            from div_canvas import fetch_courses
            _canvas_courses = fetch_courses(CANVAS_URL, CANVAS_TOKEN)
        except Exception as e:
            _canvas_courses = None
    else:
        _canvas_courses = None

threading.Thread(target=refresh_canvas_cache, daemon=True).start()
threading.Thread(target=refresh_canvas_courses, daemon=True).start()

# ── Knowt integration ──
def load_knowt_cache():
    try:
        from div_knowt import load_cache
        return load_cache()
    except Exception:
        return None

_knowt_cache = load_knowt_cache()

# ── Fiveable integration ──
def load_fiveable_cache():
    try:
        from div_fiveable import load_cache
        return load_cache()
    except Exception:
        return None

_fiveable_cache = load_fiveable_cache()

# ── Auto-sync stale caches in background ──
def _cache_is_stale(cache_data, hours=12):
    if not cache_data or cache_data.get("error"):
        return False
    try:
        dt = datetime.fromisoformat(cache_data.get("scraped_at", ""))
        return (datetime.now(timezone.utc) - dt) > timedelta(hours=hours)
    except:
        return False

def _bg_sync_knowt():
    global _knowt_cache
    try:
        from div_knowt import scrape, is_configured
        if is_configured():
            _knowt_cache = scrape()
    except Exception:
        pass

def _bg_sync_fiveable():
    global _fiveable_cache
    try:
        from div_fiveable import scrape, is_configured
        if is_configured():
            _fiveable_cache = scrape()
    except Exception:
        pass

if _cache_is_stale(_knowt_cache):
    threading.Thread(target=_bg_sync_knowt, daemon=True).start()

if _cache_is_stale(_fiveable_cache):
    threading.Thread(target=_bg_sync_fiveable, daemon=True).start()

# Create the global persona file if it doesn't exist
if not os.path.exists(PERSONA_FILE):
    with open(PERSONA_FILE, "w", encoding="utf-8") as f:
        f.write("You are divAI, an elite coding agent. You have terminal and file tools. Use them efficiently. Never ask for permission.")

current_mode = "auto"

# ==========================================
# 2. THE TOOLS
# ==========================================
tools = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Executes a powershell command.",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Reads a file.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Writes to a file.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edits a file by replacing an exact string. Always read_file first to get the exact text.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Lists all files in a folder.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": "Searches your Obsidian vault for a keyword.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_vault_note",
            "description": "Reads a specific note from your Obsidian vault.",
            "parameters": {"type": "object", "properties": {"note_name": {"type": "string"}}, "required": ["note_name"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_vault_note",
            "description": "Creates or appends to a note in your Obsidian vault. Auto-syncs to cloud.",
            "parameters": {"type": "object", "properties": {"note_name": {"type": "string"}, "content": {"type": "string"}, "mode": {"type": "string", "enum": ["overwrite", "append"]}}, "required": ["note_name", "content", "mode"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Searches the internet for real-time information.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_canvas_overview",
            "description": "Fetches a FRESH, comprehensive Canvas snapshot: upcoming assignments with due dates AND recent teacher announcements. Call this whenever the user asks what Canvas looks like, what's going on at school, what's due, any announcements, or anything Canvas-related. Always prefer this over get_canvas_assignments for a full picture.",
            "parameters": {"type": "object", "properties": {"days_ahead": {"type": "integer", "description": "Days to look ahead for assignments (default 14)"}}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_canvas_assignments",
            "description": "Fetches only upcoming Canvas assignments (no announcements). Prefer get_canvas_overview for a full picture.",
            "parameters": {"type": "object", "properties": {"days_ahead": {"type": "integer", "description": "How many days ahead to look (default 21)"}}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "canvas_api",
            "description": "Makes a GET request to any Canvas LMS API endpoint. Use for grades, announcements, files, modules, quizzes, submissions, people, rubrics, etc. Check the system prompt for course IDs.",
            "parameters": {"type": "object", "properties": {"endpoint": {"type": "string", "description": "Canvas API path, e.g. /api/v1/courses/123/enrollments"}, "params": {"type": "object", "description": "Optional query parameters"}}, "required": ["endpoint"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_knowt_schedule",
            "description": "Fetches the user's Knowt study schedule — upcoming exams, what to study today, and flashcard progress.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_fiveable_schedule",
            "description": "Fetches the user's Fiveable AP study progress — upcoming AP exams, study guide completion, and daily recommendations.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetches the content of any URL and returns the cleaned text. Use this to read Fiveable study guides, Knowt flashcard sets, or any webpage the user asks about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_fiveable",
            "description": "Searches Fiveable for AP study content (unit overviews, key concepts, practice FRQs, study guides) and returns the page content. Use this whenever the user asks about an AP subject, unit, or topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The AP topic to search for, e.g. 'APES unit 9 overview' or 'AP Calc AB limits'"}
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Sets a timed reminder that fires a notification. Use when the user asks to be reminded about something at a specific time or after a duration. Calculate the minutes from NOW to the target time yourself using the current datetime from the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "How many minutes from now to fire the reminder"},
                    "message": {"type": "string", "description": "What to remind the user about"}
                },
                "required": ["minutes", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "render_cell",
            "description": (
                "Opens a live interactive popup window to visualize something. "
                "ALWAYS prefer render_cell over describing things in plain text when showing: "
                "timers/countdowns, task checklists, progress trackers, day schedules, or data tables. "
                "The user sees a real ticking countdown, real clickable checkboxes, a real schedule — not text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_type": {
                        "type": "string",
                        "enum": ["timer", "checklist", "progress", "schedule", "table"],
                        "description": "Visual component type to open"
                    },
                    "params": {
                        "type": "object",
                        "description": (
                            "timer:{seconds,label} | "
                            "checklist:{title,items:[{text,done}]} | "
                            "progress:{title,items:[{label,value,max}]} | "
                            "schedule:{date,blocks:[{time,label,color}]} | "
                            "table:{title,headers:[],rows:[[]]}"
                        )
                    }
                },
                "required": ["cell_type", "params"]
            }
        }
    }
]

def run_command(command):
    try:
        res = subprocess.run(["powershell", "-Command", command], capture_output=True, text=True, timeout=30)
        return res.stdout if res.stdout else (res.stderr if res.stderr else "Success (no output)")
    except Exception as e: return str(e)

def read_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f: return f.read()
    except Exception as e: return str(e)

def write_file(path, content):
    try:
        with open(path, 'w', encoding='utf-8') as f: f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e: return str(e)

def edit_file(path, old_string, new_string):
    try:
        with open(path, 'r', encoding='utf-8') as f: content = f.read()
        if old_string not in content: return f"Error: Text not found in {path}. Use read_file first to get the exact content."
        with open(path, 'w', encoding='utf-8') as f: f.write(content.replace(old_string, new_string, 1))
        return f"Successfully edited {path}"
    except Exception as e: return str(e)

def list_directory(path):
    try: return "\n".join(os.listdir(path))
    except Exception as e: return str(e)

def search_vault(query):
    if not GLOBAL_VAULT: return "Error: Obsidian vault not linked. Use /vault <path> to link it."
    matches = []
    for root, _, files in os.walk(GLOBAL_VAULT):
        for f in files:
            if f.endswith(".md"):
                try:
                    with open(os.path.join(root, f), 'r', encoding='utf-8') as file:
                        if query.lower() in file.read().lower(): matches.append(f)
                except: pass
    return f"Found '{query}' in notes: {', '.join(matches)}" if matches else "No matching notes found."

def read_vault_note(note_name):
    if not GLOBAL_VAULT: return "Error: Obsidian vault not linked."
    if not note_name.endswith(".md"): note_name += ".md"
    for root, _, files in os.walk(GLOBAL_VAULT):
        if note_name in files:
            try:
                with open(os.path.join(root, note_name), 'r', encoding='utf-8') as file: return file.read()
            except Exception as e: return str(e)
    return "Note not found."

def write_vault_note(note_name, content, mode):
    if not GLOBAL_VAULT: return "Error: Obsidian vault not linked."
    if not note_name.endswith(".md"): note_name += ".md"
    path = os.path.join(GLOBAL_VAULT, note_name)
    try:
        m = 'a' if mode == 'append' else 'w'
        prefix = "\n\n" if mode == 'append' else ""
        with open(path, m, encoding='utf-8') as f: f.write(prefix + content)
        
        if os.path.exists(os.path.join(GLOBAL_VAULT, ".git")):
            subprocess.run(["git", "add", "."], cwd=GLOBAL_VAULT, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"divAI auto-log: {mode}ed {note_name}"], cwd=GLOBAL_VAULT, capture_output=True)
            res = subprocess.run(["git", "push"], cwd=GLOBAL_VAULT, capture_output=True)
            if res.returncode != 0:
                err = res.stderr.decode('utf-8').strip()
                return f"Successfully {mode}ed {note_name} locally. Cloud sync FAILED (Git Error: {err})"
            return f"Successfully {mode}ed {note_name} and pushed to GitHub cloud."
            
        return f"Successfully {mode}ed note: {note_name} (Local only)"
    except Exception as e: return str(e)

def search_web(query):
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=5)
        if not results: return "No results found."
        formatted = []
        for r in results: formatted.append(f"[{r.get('title')}]({r.get('href')}): {r.get('body')}")
        return "\n\n".join(formatted)
    except ImportError:
        return "Error: Library missing. You must use run_command tool to execute 'pip install ddgs', then try searching again."
    except Exception as e:
        return f"Search failed: {str(e)}"

def fetch_url(url):
    try:
        import requests as _req
        r = _req.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}, timeout=15)
        r.raise_for_status()
        text = re.sub(r'<script[^>]*>.*?</script>', '', r.text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:8000]
    except Exception as e:
        return f"Failed to fetch {url}: {str(e)}"

def search_fiveable(topic):
    try:
        from ddgs import DDGS
        query = f"site:fiveable.me {topic}"
        results = DDGS().text(query, max_results=3)
        if not results:
            return f"No Fiveable results found for '{topic}'. Try fetch_url with a direct Fiveable URL."
        top = results[0]
        url = top.get("href", "")
        snippet = top.get("body", "")
        content = fetch_url(url) if url else ""
        if content and not content.startswith("Failed"):
            return f"[Source: {url}]\n\n{content}"
        return f"[{top.get('title')}]({url}): {snippet}"
    except ImportError:
        return "Error: ddgs library missing. Run: pip install ddgs"
    except Exception as e:
        return f"Fiveable search failed: {str(e)}"

def _render_cell(cell_type, params):
    try:
        from div_cells import render_cell
        return render_cell(cell_type, params if isinstance(params, dict) else {})
    except Exception as e:
        return f"Cell error: {str(e)}"

def set_reminder(minutes, message):
    try:
        minutes = int(minutes)
        if minutes < 1:
            return "Error: minutes must be at least 1."
        def fire():
            print(f"\n\033[93m\a⏰ REMINDER: {message}\033[0m\n\033[96m❯ \033[0m", end="", flush=True)
            try:
                from div_notify import toast
                toast("divAI Reminder", message)
            except Exception:
                pass
        t = threading.Timer(minutes * 60, fire)
        t.daemon = True
        t.start()
        h, m = divmod(minutes, 60)
        when = (f"{h}h {m}m" if h else f"{m}m").strip()
        return f"Reminder set for {when} from now: \"{message}\""
    except Exception as e:
        return f"Failed to set reminder: {str(e)}"

# ──────────────────────────────────────────────
# SPINNER
# ──────────────────────────────────────────────
_spinner_stop = threading.Event()

def _spinner_loop():
    frames = ['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏']
    for f in itertools.cycle(frames):
        if _spinner_stop.is_set():
            break
        sys.stdout.write(f'\r\033[94m{f} thinking...\033[0m  ')
        sys.stdout.flush()
        time.sleep(0.08)
    sys.stdout.write('\r\033[K')
    sys.stdout.flush()

def _start_spinner():
    _spinner_stop.clear()
    t = threading.Thread(target=_spinner_loop, daemon=True)
    t.start()
    return t

def _stop_spinner(t):
    _spinner_stop.set()
    t.join(timeout=0.3)

# ──────────────────────────────────────────────
# MARKDOWN RENDERER
# ──────────────────────────────────────────────
def _inline_fmt(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\033[1m\1\033[22m', text)
    text = re.sub(r'`([^`]+)`', r'\033[96m\1\033[94m', text)
    return text

def render_response(text):
    sep = f'\033[90m{"─" * 44}\033[0m'
    lines = text.split('\n')
    out = []
    in_code = False

    for line in lines:
        if line.strip().startswith('```'):
            in_code = not in_code
            out.append(sep)
            continue
        if in_code:
            out.append(f'\033[96m  {line}\033[0m')
            continue
        if re.match(r'^#{1,3} ', line):
            htext = re.sub(r'^#{1,3} ', '', line)
            out.append(f'\033[1m\033[94m{htext}\033[0m')
            continue
        if re.match(r'^-{3,}$', line.strip()):
            out.append(f'\033[90m{"─" * 44}\033[0m')
            continue
        m_bullet = re.match(r'^(\s*)[\-\*] (.*)', line)
        if m_bullet:
            out.append(f'{m_bullet.group(1)}  \033[94m•\033[0m {_inline_fmt(m_bullet.group(2))}')
            continue
        m_num = re.match(r'^(\s*)(\d+)\. (.*)', line)
        if m_num:
            out.append(f'{m_num.group(1)}  \033[94m{m_num.group(2)}.\033[0m {_inline_fmt(m_num.group(3))}')
            continue
        out.append(f'\033[94m{_inline_fmt(line)}\033[0m')

    return '\n'.join(out)

def strip_for_speech(text):
    text = re.sub(r'```[\s\S]*?```', '[code block]', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'^\s*[-*•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # strip punctuation that causes long TTS pauses
    text = re.sub(r'[,;:]', '', text)
    text = re.sub(r'[—–]', ' ', text)
    return text.strip()

def speak(text):
    if not text or not text.strip():
        return

    # edge-tts via src/voice/tts.py — free, no API key, Microsoft Neural voices
    try:
        import pathlib as _pl
        _vdir = str(_pl.Path(__file__).parent)
        if _vdir not in sys.path:
            sys.path.insert(0, _vdir)
        from src.voice.tts import speak as _tts_speak
        _tts_speak(text, voice=TTS_VOICE, rate=TTS_RATE)
        return
    except Exception:
        pass

    # pyttsx3 last resort
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 220)
        engine.say(strip_for_speech(text)[:1500])
        engine.runAndWait()
    except Exception:
        pass

def _speak_async(text):
    threading.Thread(target=speak, args=(text,), daemon=True).start()

def canvas_api_call(endpoint, params=None):
    if not CANVAS_URL or not CANVAS_TOKEN:
        return "Canvas not configured."
    try:
        from div_canvas import canvas_api
        result = canvas_api(CANVAS_URL, CANVAS_TOKEN, endpoint, params)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Canvas API error: {str(e)}"

def get_canvas_overview(days_ahead=14):
    global _canvas_cache
    if not CANVAS_URL or not CANVAS_TOKEN:
        return "Canvas not configured."
    try:
        from div_canvas import fetch_upcoming_assignments, fetch_announcements, format_for_display
        assignments = fetch_upcoming_assignments(CANVAS_URL, CANVAS_TOKEN, days_ahead)
        _canvas_cache = assignments
        out = ["── Upcoming Assignments ──", format_for_display(assignments)]
        if _canvas_courses:
            ids = [c["id"] for c in _canvas_courses if "error" not in c]
            if ids:
                announcements = fetch_announcements(CANVAS_URL, CANVAS_TOKEN, ids)
                if announcements and "error" not in announcements[0]:
                    out.append("\n── Recent Announcements ──")
                    for ann in announcements:
                        posted = ann.get("posted", "")[:10]
                        out.append(f"  [{posted}] Course {ann.get('course_id','')}: {ann['title']}")
                        if ann.get("message"):
                            out.append(f"    {ann['message'][:200]}")
        return "\n".join(out)
    except Exception as e:
        return f"Canvas error: {str(e)}"

def get_canvas_assignments(days_ahead=21):
    if not CANVAS_URL or not CANVAS_TOKEN:
        return "Canvas not configured. Use /canvas setup <url> <token> to connect."
    try:
        from div_canvas import fetch_upcoming_assignments, format_for_display
        assignments = fetch_upcoming_assignments(CANVAS_URL, CANVAS_TOKEN, days_ahead)
        return format_for_display(assignments)
    except Exception as e:
        return f"Canvas error: {str(e)}"

def get_knowt_schedule():
    global _knowt_cache
    _knowt_cache = load_knowt_cache()
    if not _knowt_cache:
        return "Knowt not configured. Use /knowt setup to connect."
    try:
        from div_knowt import format_for_display
        return format_for_display(_knowt_cache)
    except Exception as e:
        return f"Knowt error: {str(e)}"

def get_fiveable_schedule():
    global _fiveable_cache
    _fiveable_cache = load_fiveable_cache()
    if not _fiveable_cache:
        return "Fiveable not configured. Use /fiveable setup to connect."
    try:
        from div_fiveable import format_for_display
        return format_for_display(_fiveable_cache)
    except Exception as e:
        return f"Fiveable error: {str(e)}"

def morning_briefing():
    global LAST_BRIEFING
    today = _date.today().isoformat()
    if LAST_BRIEFING == today:
        return
    LAST_BRIEFING = today
    save_config()

    sections = []
    if _canvas_cache and not (len(_canvas_cache) == 1 and "error" in _canvas_cache[0]):
        from div_canvas import format_for_display as cfmt
        sections.append(cfmt(_canvas_cache))
    if _knowt_cache and not _knowt_cache.get("error"):
        from div_knowt import format_for_display as kfmt
        sections.append(kfmt(_knowt_cache))
    if _fiveable_cache and not _fiveable_cache.get("error"):
        from div_fiveable import format_for_display as ffmt
        sections.append(ffmt(_fiveable_cache))

    if not sections:
        return

    print("\033[94m── Morning Briefing ──────────────────────────\033[0m")
    for s in sections:
        print(f"\033[94m{s}\033[0m")
    print("\033[94m──────────────────────────────────────────────\033[0m\n")

    try:
        from div_notify import toast
        parts = []
        if _canvas_cache:
            n = len([a for a in _canvas_cache if "error" not in a])
            if n: parts.append(f"{n} assignment{'s' if n!=1 else ''} due")
        if _knowt_cache:
            n = len(_knowt_cache.get("exams", []))
            if n: parts.append(f"{n} exam{'s' if n!=1 else ''} upcoming")
        if parts:
            toast("divAI · Morning Briefing", " · ".join(parts))
    except Exception:
        pass

# ==========================================
# 3. MEMORY ARCHITECTURE (Auto-Context & Session)
# ==========================================
def build_system_prompt():
    try:
        with open(PERSONA_FILE, "r", encoding="utf-8") as f: prompt = f.read()
    except: prompt = "You are divAI."
    
    prompt += """\n\n[CRITICAL DIRECTIVE - TOOL EXECUTION]
You have FULL unrestricted access to the user's computer, local files, and the LIVE INTERNET.
NEVER say "I don't have access to the internet" or "I cannot search the web". YOU CAN.
To perform actions, you MUST output EXACTLY this XML block:
<function=tool_name>{"arg1": "value"}</function>
Do not use markdown code blocks around the tag.

1. run_command: {"command": "powershell string"}
2. read_file: {"path": "string"}
3. write_file: {"path": "string", "content": "string"}
4. edit_file: {"path": "string", "old_string": "exact text to replace", "new_string": "replacement"}
5. list_directory: {"path": "string"}
6. search_vault: {"query": "string"}
7. read_vault_note: {"note_name": "string"}
8. write_vault_note: {"note_name": "string", "content": "string", "mode": "overwrite|append"}
9. search_web: {"query": "search term"}
10. fetch_url: {"url": "https://..."}
11. search_fiveable: {"topic": "APES unit 9 overview"}
12. set_reminder: {"minutes": 45, "message": "submit the CS homework"}
13. get_canvas_overview: {"days_ahead": 14}
14. canvas_api: {"endpoint": "/api/v1/courses/ID/enrollments", "params": {}}
15. render_cell: {"cell_type": "timer", "params": {"seconds": 600, "label": "Pomodoro"}}

If the user asks a question about recent events or unknown concepts, IMMEDIATELY use <function=search_web>. DO NOT REFUSE.

[REMINDERS]
Current local datetime: {NOW}
When the user asks to be reminded about something (at a time, after a duration, or before an event):
- Calculate how many minutes from NOW to the target time.
- IMMEDIATELY call set_reminder with that many minutes and the reminder message.
- Confirm with the exact time it will fire (e.g. "Reminder set for 5:00 AM — that's 214 minutes from now").
- Examples: "remind me at 5am" → calculate minutes until 5am · "remind me in 2 hours" → 120 minutes · "remind me tomorrow morning" → minutes until 8am tomorrow.

[STUDY PLATFORM INTELLIGENCE]
You have LIVE access to Fiveable and Knowt content via your tools. NEVER say you can't access these sites.
- When the user asks about an AP subject, unit overview, key concepts, study guide, FRQ practice, or ANY educational content: IMMEDIATELY call search_fiveable with the topic.
- When the user says "pull X", "show me X", "give me X" about a study topic: fetch it right away without asking.
- Use fetch_url to read any specific Fiveable or Knowt URL the user provides or that appears in search results.
- Use search_web("site:knowt.com {topic}") for Knowt flashcard sets specifically.
You are an active study assistant — go get the content, don't wait to be asked twice.

[TTS] This CLI has text-to-speech output. When TTS is active, your responses are spoken aloud via Microsoft Neural voices. Never say you cannot output voice or sound — you can. Respond naturally; do not break the fourth wall about your environment.

[DIVAI SELF-AWARENESS — YOUR OWN CAPABILITIES]
You ARE divAI. You run as a Python CLI (divCLI.py). When the user asks what you can do, how to use a command, or what a feature is, answer from this exact list — do not guess or make things up.

MODELS & ROUTING
- /auto       — Default. Auto-routes each message to the best model: talk (gpt-4o-mini, fast/cheap), code (gpt-4.1, programming), brain (gpt-5.4, deep reasoning). Routing is keyword-based. All three use the same OpenAI key.
- /talk        — Pin to gpt-4o-mini (fastest, cheapest)
- /code        — Pin to gpt-4.1 (best for coding tasks)
- /brain       — Pin to gpt-5.4 (most capable — best for analysis, essays, planning)
- /divfull     — Pin to gpt-4.1 (same as /code, explicit full-power mode)

VOICE & TTS
- /v (or /voice) — Push-to-talk voice input. Records mic until ENTER, transcribes via Groq Whisper, sends as your prompt.
- /speak         — Toggle text-to-speech output on/off. Reads bot replies aloud using Microsoft Neural TTS (edge-tts).
- /speak-voice <name> — Change TTS voice, e.g. /speak-voice en-US-JennyNeural. Default: en-US-AndrewNeural.
- /speak-rate <rate>  — Set speech speed, e.g. /speak-rate +50% for faster, /speak-rate -10% for slower. Blank to check current.

SESSION
- /clear   — Wipe the conversation history and start fresh (keeps config/keys).
- /restart — Fully restart divAI (re-runs the script).
- /exit    — Exit. If a vault is linked, auto-logs the session to divAI_Session_Logs.md.

CONFIG
- /key openai <api_key>    — Set OpenAI key for all slots at once. This is all you need.
- /key <engine> <api_key>  — Set key for one slot. Engines: talk, code, brain, full, whisper.
- /key whisper <groq_key>  — Set the Groq key used for voice transcription (/v).
- /persona                  — Opens the system persona file in Notepad. Edit it to change your personality/instructions.
- /vault <path>             — Link an Obsidian vault folder. Enables note reading/writing and session logging. Example: /vault D:\\MyVault

REMINDERS
- /remind <minutes> <message> — Sets a timed reminder. Fires a terminal bell + Windows toast notification. Example: /remind 30 submit CS homework
- You (the AI) can also call set_reminder directly when the user asks for a reminder by time or duration.

CANVAS (School LMS)
- /canvas                        — Show cached upcoming assignments.
- /canvas url <url>              — Set Canvas school URL, e.g. /canvas url myschool.instructure.com
- /canvas setup <token>          — Connect Canvas with an API token (Canvas → Account → Settings → New Access Token).
- /canvas setup <url> <token>    — Set URL and token in one step.
- You (the AI) can call get_canvas_overview, get_canvas_assignments, and canvas_api for live data.

KNOWT (Flashcard study scheduler)
- /knowt         — Show cached Knowt study schedule (upcoming exams, flashcard progress).
- /knowt setup   — Opens a browser to log into Knowt via Playwright scraping (no official API).
- /knowt sync    — Re-scrapes Knowt to refresh the schedule.

FIVEABLE (AP study guides)
- /fiveable         — Show cached AP exam progress.
- /fiveable setup   — Opens a browser to log into Fiveable.
- /fiveable sync    — Re-scrapes Fiveable AP data.
- You (the AI) can call search_fiveable or fetch_url to pull live Fiveable study content instantly.

OSINT INVESTIGATION MODULE
- investigate <case name>            — Full investigation (missing persons): Wikipedia, Reddit, NamUs, Charley Project, news, Wayback CDX
- investigate <case name> --refresh  — Force re-scrape
- show contradictions                — Interactive review of contradictions from last investigation
- show leads                         — Display priority lead queue (Tier 1/2/3)
- read investigation brief           — Speak/display the investigation summary
- narrate [case name]                — Cinematic narrative brief: hook, contradiction, leads, voiceover

PROFILE COMMAND — for living people (social media, public records, username correlation)
Syntax: profile <name> [hints] [--refresh]

Hints narrow the search and are CRITICAL for non-famous people with common names:
  --location "City, ST"    Narrows people-aggregator and social queries by geography
  --username handle         Enables Sherlock (checks 300+ sites for that username) — most powerful hint
  --company "Employer"      Narrows LinkedIn and news queries by employer
  --school "School Name"    Narrows for students/faculty (treated like company in searches)
  --email addr@domain.com   Enables holehe (checks 120+ sites for email registration)
  --refresh                 Re-scrapes all sources, ignores cache

Examples:
  profile John Smith
  profile John Smith --location "Seattle, WA"
  profile John Smith --username johnsmith92 --location "Austin, TX"
  profile Divik Srivastava --school "FCHS" --username clippedby.div
  profile Jane Doe --company "Amazon" --location "New York"
  profile Jane Doe --email jane.doe@gmail.com

REFINEMENT STRATEGY — when the user says they learned something new from a profile run (a school, a handle, a company), ALWAYS respond by showing them the exact refined command to run next. Do not give generic advice. Example: if a first run found school "FCHS" and Instagram handle "clippedby.div", the next command is:
  profile Divik Srivastava --school "FCHS" --username clippedby.div
Feed every new discovery back as a hint in the next profile call. Sherlock (--username) is the single most powerful tool — if you ever find a handle, immediately suggest running it with that hint.

CONTEXT SYSTEM (force-load focused context from vault)
- mode: coding   — Load coding-specific context
- mode: school   — Load school/study context
- mode: osint    — Load OSINT/research context
- mode: channel  — Load channel context
- mode: planning — Load planning context
- context status      — Show which context modes are currently active
- summarize session   — AI summarizes the current conversation and saves it to sessions/cli/

BUILT-IN TOOLS (you call these automatically, user doesn't need to invoke them directly)
- run_command(command)              — Runs a PowerShell command on the user's PC
- read_file / write_file / edit_file / list_directory — Local filesystem access
- search_web(query)                 — DuckDuckGo internet search
- fetch_url(url)                    — Fetches and cleans any webpage
- search_fiveable(topic)            — Searches Fiveable for AP study content
- search_vault / read_vault_note / write_vault_note — Obsidian vault read/write
- get_canvas_overview / get_canvas_assignments / canvas_api — Canvas LMS live data
- get_knowt_schedule / get_fiveable_schedule — Study platform schedules
- set_reminder(minutes, message)    — Timed reminder with toast notification
- render_cell(cell_type, params)    — Opens a live GUI popup: timer, checklist, progress tracker, schedule, or table

When the user asks "what can you do", "how do I use X", or "do you have a command for Y" — answer from the above list precisely."""

    now_str = datetime.now().strftime("%A, %B %#d %Y at %#I:%M %p")
    prompt = prompt.replace("{NOW}", now_str)

    if SESSION_GAP_HOURS >= 4:
        if SESSION_GAP_HOURS < 24:
            _gap = f"about {int(SESSION_GAP_HOURS)} hours"
        elif SESSION_GAP_HOURS < 48:
            _gap = "about 1 day"
        else:
            _gap = f"about {int(SESSION_GAP_HOURS / 24)} days"
        prompt += (
            f"\n\n[SESSION AWARENESS] {_gap} have passed since the last conversation. "
            f"Time-sensitive things the user mentioned (tasks due 'tonight', 'tomorrow', "
            f"'this week', assignments, plans) may have already happened. "
            f"When they first message you this session, naturally check in — "
            f"ask how those things went. Don't robotically list them; weave it into the reply."
        )

    if GLOBAL_VAULT: prompt += f"\n\n[OBSIDIAN VAULT]: Connected to {GLOBAL_VAULT}. You can read, write, and search the user's personal notes."
    if os.path.exists("CLAUDE.md"): prompt += "\n\n[User Context - CLAUDE.md]:\n" + read_file("CLAUDE.md")

    if _canvas_courses:
        course_lines = [f"  - {c['name']} (ID: {c['id']}, code: {c['code']})" for c in _canvas_courses if "error" not in c]
        if course_lines:
            prompt += f"\n\n[CANVAS COURSES]:\n" + "\n".join(course_lines)
            prompt += "\nCall get_canvas_overview for a fresh full picture (assignments + announcements). Use canvas_api with these IDs for specific queries like grades, files, modules, quizzes, submissions."

    if _canvas_cache is not None:
        from div_canvas import format_for_prompt as canvas_fmt
        prompt += f"\n\n[CANVAS LMS — UPCOMING ASSIGNMENTS (cached at startup — call get_canvas_overview for a live refresh)]:\n{canvas_fmt(_canvas_cache)}"
        prompt += "\nRemind the user proactively when assignments are due soon."

    if _knowt_cache is not None:
        from div_knowt import format_for_prompt as knowt_fmt
        prompt += f"\n\n[KNOWT STUDY SCHEDULE]:\n{knowt_fmt(_knowt_cache)}"
        prompt += "\nRemind the user about upcoming exams and what they should study today based on their Knowt schedule."

    if _fiveable_cache is not None:
        from div_fiveable import format_for_prompt as fiveable_fmt
        prompt += f"\n\n[FIVEABLE AP PROGRESS]:\n{fiveable_fmt(_fiveable_cache)}"
        prompt += "\nRemind the user about upcoming AP exams and their study guide progress."

    return prompt

def save_memory(msgs):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f: json.dump(msgs, f, indent=4)

def _gap_notice() -> str:
    if SESSION_GAP_HOURS < 4:
        return ""
    h = int(SESSION_GAP_HOURS)
    m = int((SESSION_GAP_HOURS % 1) * 60)
    if SESSION_GAP_HOURS < 24:
        gap = f"{h}h {m}m"
    elif SESSION_GAP_HOURS < 48:
        gap = "about 1 day"
    else:
        gap = f"about {int(SESSION_GAP_HOURS / 24)} days"
    now = datetime.now().strftime("%A, %B %#d %Y at %#I:%M %p")
    return (
        f"[SESSION RESUMED — {gap} since last conversation | now: {now}]\n"
        f"Scan the history above for any tasks, assignments, deadlines, or plans the user "
        f"mentioned. When they send their first message, naturally ask how those things went "
        f"— especially anything framed as upcoming, due soon, or time-sensitive."
    )

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                msgs = json.load(f)
                if msgs and len(msgs) > 0:
                    msgs[0] = {"role": "system", "content": build_system_prompt()}
                    notice = _gap_notice()
                    if notice and len(msgs) > 1:
                        msgs.append({"role": "system", "content": notice})
                    return msgs
        except: pass
    return [{"role": "system", "content": build_system_prompt()}]

messages = load_memory()
os.system('color')

def print_header():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\033[94m   ██████╗ ██╗██╗   ██╗ █████╗ ██╗\n   ██╔══██╗██║██║   ██║██╔══██╗██║\n   ██║  ██║██║██║   ██║███████║██║\n   ██║  ██║██║╚██╗ ██╔╝██╔══██║██║\n   ██████╔╝██║ ╚████╔╝ ██║  ██║██║\n   ╚═════╝ ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝\033[0m")
    print(f"\n\033[90m[SYSTEM] divCLI v8.0.1 Operational.\033[0m")
    if GLOBAL_VAULT: 
        print(f"\033[90m[VAULT] Linked: {GLOBAL_VAULT}\033[0m")
        if os.path.exists(os.path.join(GLOBAL_VAULT, ".git")):
            print(f"\033[90m[VAULT] Pulling latest cloud memory...\033[0m")
            subprocess.run(["git", "pull"], cwd=GLOBAL_VAULT, capture_output=True)
    if current_mode == "auto":
        print(f"\033[90m[ROUTER] \033[92mauto-routing\033[90m  (picks talk / code / brain per message)\033[0m")
    else:
        print(f"\033[90m[ROUTER] Pinned to \033[92m/{current_mode}\033[90m ({MODELS[current_mode]['model']})  — /auto to re-enable routing\033[0m")
    if "ollama" in MODELS.get("talk", {}).get("model", ""):
        try:
            import urllib.request as _ur
            _ur.urlopen("http://localhost:11434", timeout=1)
            print(f"\033[90m[OLLAMA] Running  ✓\033[0m")
        except Exception:
            print(f"\033[91m[OLLAMA] Not running — start Ollama or run: ollama serve\033[0m")
    if CANVAS_URL:
        count = len([a for a in (_canvas_cache or []) if "error" not in a])
        print(f"\033[90m[CANVAS] {CANVAS_URL} — {count} upcoming assignments\033[0m")
    if _knowt_cache and not _knowt_cache.get("error"):
        exams = len(_knowt_cache.get("exams", []))
        print(f"\033[90m[KNOWT] {exams} upcoming exam(s) tracked\033[0m")
    print("\033[90m[COMMANDS] /help for full list  |  /talk /code /brain /divfull  |  /canvas /knowt /fiveable  |  /remind /v /clear /exit\033[0m\n")

try:
    from div_boot import boot_animation as _boot_animation
    _boot_animation({
        "models":          MODELS,
        "vault":           GLOBAL_VAULT,
        "canvas_url":      CANVAS_URL,
        "canvas_cache":    _canvas_cache,
        "knowt_cache":     _knowt_cache,
        "fiveable_cache":  _fiveable_cache,
        "current_mode":    current_mode,
    })
except Exception:
    print_header()
morning_briefing()

# ==========================================
# 4. THE AGENT LOOP
# ==========================================
import sys
first_run = True

while True:
    try:
        if first_run and len(sys.argv) > 1 and sys.argv[1] == "--voice":
            user_input = "/v"
            TTS_ENABLED = True
        else:
            user_input = input("\033[96m❯ \033[0m").strip()
            
        first_run = False
        if not user_input: continue
        
        cmd_lower = user_input.lower()
        
        # IVR / Voice Dictation Feature
        if cmd_lower in ['/v', '/voice']:
            try:
                import sounddevice as sd
                import soundfile as sf
                import numpy as np
                import requests
            except ImportError:
                print("\033[91m  ⎿ Missing audio libraries. Auto-installing dependencies to your current environment...\033[0m")
                import sys
                subprocess.run([sys.executable, "-m", "pip", "install", "sounddevice", "soundfile", "numpy", "requests"], capture_output=True)
                print("\033[92m  ⎿ Installed. Please type /v again.\033[0m\n")
                continue
                
            print("\033[91m  ⎿ [MIC ACTIVE] Speak your prompt. Press ENTER to stop recording.\033[0m")
            fs = 16000
            recording = []
            is_recording = True
            
            def callback(indata, frames, time, status):
                if is_recording: recording.append(indata.copy())
                
            stream = sd.InputStream(samplerate=fs, channels=1, callback=callback)
            with stream:
                input() # Block until Enter is pressed
                is_recording = False
                
            print("\033[90m  ⎿ Transcribing via Groq Whisper...\033[0m")
            audio_data = np.concatenate(recording, axis=0)
            temp_file = os.path.join(CLI_DIR, "temp_voice.wav")
            sf.write(temp_file, audio_data, fs)
            
            try:
                url = "https://api.groq.com/openai/v1/audio/transcriptions"
                whisper_key = WHISPER_KEY
                headers = {"Authorization": f"Bearer {whisper_key}"}
                with open(temp_file, 'rb') as f:
                    files = {'file': ('temp_voice.wav', f, 'audio/wav'), 'model': (None, 'whisper-large-v3')}
                    resp = requests.post(url, headers=headers, files=files)
                
                text = resp.json().get('text', '')
                if not text:
                    print("\033[91m  ⎿ Transcription failed or no speech detected.\033[0m\n")
                    continue
                    
                print(f"\033[96m❯ [DICTATED]: {text}\033[0m")
                user_input = text
            except Exception as e:
                print(f"\033[91m  ⎿ Transcription Error: {str(e)}\033[0m\n")
                continue
        if cmd_lower == '/restart':
            print(f"\033[90m  ⎿ Restarting divAI...\033[0m")
            os.execv(sys.executable, [sys.executable] + sys.argv)

        if cmd_lower in ['/exit', '/quit']:
            if GLOBAL_VAULT and len(messages) > 2:
                print(f"\033[90m  ⎿ Logging session to Vault...\033[0m")
                try:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    user_turns = [str(m.get("content", ""))[:200] for m in messages[1:] if m.get("role") == "user"]
                    summary = "\n".join(f"- {t}" for t in user_turns[:20])
                    note_name = "divAI_Session_Logs.md"
                    path = os.path.join(GLOBAL_VAULT, note_name)
                    log_entry = f"\n\n## Session: {timestamp}\n{summary}\n---\n"
                    with open(path, 'a', encoding='utf-8') as f: f.write(log_entry)
                    if os.path.exists(os.path.join(GLOBAL_VAULT, ".git")):
                        subprocess.run(
                            f'git add . && git commit -m "divAI: Auto-logged session" && git push',
                            cwd=GLOBAL_VAULT, capture_output=True, shell=True
                        )
                    print(f"\033[92m  ⎿ Session logged to {note_name}.\033[0m")
                except Exception as e:
                    print(f"\033[91m  ⎿ Failed to log session: {str(e)}\033[0m")
            break
        
        if cmd_lower == '/help':
            W = "\033[97m"; B = "\033[94m"; G = "\033[90m"; X = "\033[0m"
            print(f"\n{B}── divAI Commands ───────────────────────────────────────{X}")
            cmds = [
                ("MODELS",      None),
                ("/auto",        "Auto-route each message to the best model (default)"),
                ("/talk",        "Pin to gpt-4o-mini (fast, cheap)"),
                ("/code",        "Pin to gpt-4.1 (coding)"),
                ("/brain",       "Pin to gpt-5.4 (most capable)"),
                ("/divfull",     "Pin to gpt-4.1 (full power)"),
                ("",             None),
                ("TOOLS",       None),
                ("/v",           "Push-to-talk voice input (Groq Whisper)"),
                ("/speak",       "Toggle TTS voice output on/off"),
                ("/speak-voice <name>", "Set TTS voice (e.g. en-US-AndrewNeural)"),
                ("/speak-rate <rate>", "Set TTS speed (e.g. +25%, +50%, -10%) — blank to check current"),
                ("/remind <min> <msg>", "Set a timed reminder (fires toast + bell)"),
                ("",             None),
                ("SESSION",     None),
                ("/clear",       "Wipe conversation history"),
                ("/restart",     "Restart divAI fresh"),
                ("/exit",        "Exit (auto-logs session to vault if linked)"),
                ("",             None),
                ("CONFIG",      None),
                ("/key openai <key>",     "Set OpenAI key for all slots at once (recommended)"),
                ("/key <engine> <key>",   f"Set key for one slot  |  engines: {', '.join(MODELS.keys())}"),
                ("/persona",     "Edit the system persona in Notepad"),
                ("/vault <path>","Link Obsidian vault for notes + session logging"),
                ("",             None),
                ("INTEGRATIONS",None),
                ("/canvas",              "Show upcoming Canvas assignments"),
                ("/canvas url <url>",    "Set Canvas school URL (one-time)"),
                ("/canvas setup <token>","Connect Canvas API token"),
                ("/knowt",               "Show Knowt study schedule"),
                ("/knowt setup",         "Log into Knowt (opens browser)"),
                ("/knowt sync",          "Re-scrape Knowt study data"),
                ("/fiveable",            "Show Fiveable AP progress"),
                ("/fiveable setup",      "Log into Fiveable (opens browser)"),
                ("/fiveable sync",       "Re-scrape Fiveable AP data"),
                ("",             None),
                ("/key whisper <groq_key>", "Set Groq key used for voice transcription"),
                ("",             None),
                ("OSINT",        None),
                ("investigate <name>",         "Run full OSINT investigation on a case (missing persons)"),
                ("investigate <name> --refresh","Re-scrape all sources and re-extract claims"),
                ("show contradictions",         "Review contradictions from last investigation"),
                ("show leads",                  "Show priority lead queue from last investigation"),
                ("show leads tier 1",           "Show only Tier 1 leads"),
                ("read investigation brief",    "Speak/display the investigation summary"),
                ("narrate",                     "Generate cinematic narrative brief from last investigation"),
                ("narrate <case name>",         "Generate narrative brief for a specific cached case"),
                ("profile <name>",                        "Build public digital footprint (people aggregators, social, Sherlock, holehe)"),
                ("profile <name> --location \"City, ST\"", "Narrow by geography"),
                ("profile <name> --username handle",       "Enable Sherlock — checks 300+ sites for that username"),
                ("profile <name> --school \"School\"",     "Narrow for students/faculty"),
                ("profile <name> --company \"Co\"",        "Narrow by employer"),
                ("profile <name> --email addr",            "Enable holehe — checks 120+ sites for email"),
                ("profile <name> --refresh",               "Re-scrape all sources"),
                ("",             None),
                ("CONTEXT SYSTEM", None),
                ("mode: osint",   "Force-load OSINT context into session"),
                ("mode: coding",  "Force-load coding context"),
                ("mode: channel", "Force-load channel context"),
                ("mode: school",  "Force-load school context"),
                ("mode: planning","Force-load planning context"),
                ("summarize session", "Save AI summary of this session to sessions/cli/"),
                ("context status",   "Show what context modes are currently active"),
            ]
            for cmd, desc in cmds:
                if desc is None:
                    if cmd:
                        print(f"\n{G}  {cmd}{X}")
                else:
                    print(f"  {W}{cmd:<30}{G}{desc}{X}")
            print(f"\n{B}─────────────────────────────────────────────────────────{X}\n")
            continue

        if cmd_lower == '/clear':
            messages = [{"role": "system", "content": build_system_prompt()}]
            save_memory(messages)
            print_header()
            continue
            
        if cmd_lower == '/auto':
            current_mode = "auto"
            print(f"\033[92m  ⎿ Auto-routing enabled\033[0m\n")
            continue

        if cmd_lower in ['/code', '/talk', '/brain']:
            current_mode = cmd_lower[1:]
            print(f"\033[92m  ⎿ Pinned to {MODELS[current_mode]['model']}  (type /auto to restore routing)\033[0m\n")
            continue

        if cmd_lower == '/divfull':
            if not MODELS.get("full", {}).get("key"):
                print(f"\033[91m  ⎿ OpenAI key not set. Run: /key full sk-...\033[0m\n")
            else:
                current_mode = "full"
                print(f"\033[92m  ⎿ Routing locked to {MODELS['full']['model']}\033[0m\n")
            continue
            
        if cmd_lower.startswith('/key'):
            parts = user_input.split(" ", 2)
            engines = ", ".join(MODELS.keys())
            if len(parts) < 3:
                print(f"\033[91m  ⎿ Usage: /key <engine> <api_key>\033[0m")
                print(f"\033[90m       Engines: {engines}\033[0m")
                print(f"\033[90m       Example: /key full sk-proj-...\033[0m\n")
            else:
                engine, new_key = parts[1].lower(), parts[2]
                if engine == "whisper":
                    WHISPER_KEY = new_key
                    save_config()
                    print(f"\033[92m  ⎿ Whisper (voice) key updated\033[0m\n")
                elif engine == "openai":
                    for _s in ("talk", "code", "brain", "full"):
                        MODELS[_s]["key"] = new_key
                    save_config()
                    print(f"\033[92m  ⎿ OpenAI key set for all slots (talk / code / brain / full)\033[0m\n")
                elif engine not in MODELS:
                    print(f"\033[91m  ⎿ Unknown engine '{engine}'. Available: {engines}, openai, whisper\033[0m\n")
                else:
                    MODELS[engine]["key"] = new_key
                    save_config()
                    print(f"\033[92m  ⎿ API key updated for /{engine}\033[0m\n")
            continue
            
        if cmd_lower == '/persona':
            print(f"\033[92m  ⎿ Opening Persona File in Notepad...\033[0m\n")
            subprocess.run(["notepad", PERSONA_FILE])
            messages[0]["content"] = build_system_prompt()
            save_memory(messages)
            continue
            
        if cmd_lower.startswith('/vault'):
            parts = user_input.split(" ", 1)
            if len(parts) < 2 or not parts[1].strip():
                current = GLOBAL_VAULT or "not linked"
                print(f"\033[91m  ⎿ Usage: /vault <path_to_vault>\033[0m")
                print(f"\033[90m       Current: {current}\033[0m")
                print(f"\033[90m       Example: /vault D:\\MyVault\033[0m\n")
            else:
                GLOBAL_VAULT = parts[1].strip('"').strip("'")
                save_config()
                messages[0]["content"] = build_system_prompt()
                save_memory(messages)
                print(f"\033[92m  ⎿ Obsidian Vault Linked: {GLOBAL_VAULT}\033[0m\n")
            continue

        if cmd_lower.startswith('/remind'):
            parts = user_input.split(None, 2)
            if len(parts) >= 3:
                try:
                    minutes = int(parts[1])
                    msg = parts[2]
                    def _fire(m=msg):
                        print(f"\n\033[93m  ⏰ REMINDER: {m}\033[0m\n\a")
                        try:
                            from div_notify import toast
                            toast("divAI · Reminder", m)
                        except Exception: pass
                    t = threading.Timer(minutes * 60, _fire)
                    t.daemon = True
                    t.start()
                    print(f"\033[92m  ⎿ Reminder set for {minutes} min: \"{msg}\"\033[0m\n")
                except ValueError:
                    print(f"\033[91m  ⎿ Usage: /remind <minutes> <message>\033[0m\n")
            else:
                print(f"\033[91m  ⎿ Usage: /remind <minutes> <message>\033[0m\n")
            continue

        if cmd_lower.startswith('/fiveable'):
            parts = user_input.split(None, 2)
            sub   = parts[1].lower() if len(parts) > 1 else ""

            if sub == "setup":
                from div_fiveable import setup_session
                setup_session()
                _fiveable_cache = load_fiveable_cache()
                messages[0]["content"] = build_system_prompt()
                save_memory(messages)
                print(f"\033[92m  ⎿ Fiveable connected. Run /fiveable to see your AP progress.\033[0m\n")
            elif sub == "sync":
                print(f"\033[90m  ⎿ Syncing Fiveable AP data...\033[0m")
                from div_fiveable import scrape
                _fiveable_cache = scrape()
                messages[0]["content"] = build_system_prompt()
                save_memory(messages)
                from div_fiveable import format_for_display
                print(f"\n\033[94m{format_for_display(_fiveable_cache)}\033[0m\n")
            else:
                if not _fiveable_cache:
                    print(f"\033[91m  ⎿ Fiveable not set up. Run:\033[0m")
                    print(f"\033[90m       /fiveable setup   ← opens browser to log in\033[0m")
                    print(f"\033[90m       /fiveable sync    ← scrapes your AP progress\033[0m\n")
                else:
                    from div_fiveable import format_for_display
                    print(f"\n\033[94m{format_for_display(_fiveable_cache)}\033[0m\n")
            continue

        if cmd_lower.startswith('/knowt'):
            parts = user_input.split(None, 2)
            sub   = parts[1].lower() if len(parts) > 1 else ""

            if sub == "setup":
                from div_knowt import setup_session
                setup_session()
                _knowt_cache = load_knowt_cache()
                messages[0]["content"] = build_system_prompt()
                save_memory(messages)
                print(f"\033[92m  ⎿ Knowt connected. Run /knowt to see your study schedule.\033[0m\n")
            elif sub == "sync":
                print(f"\033[90m  ⎿ Syncing Knowt study schedule...\033[0m")
                from div_knowt import scrape
                _knowt_cache = scrape()
                messages[0]["content"] = build_system_prompt()
                save_memory(messages)
                from div_knowt import format_for_display
                print(f"\n\033[94m{format_for_display(_knowt_cache)}\033[0m\n")
            else:
                # /knowt — display cached schedule
                if not _knowt_cache:
                    print(f"\033[91m  ⎿ Knowt not set up. Run:\033[0m")
                    print(f"\033[90m       /knowt setup   ← opens browser to log in\033[0m")
                    print(f"\033[90m       /knowt sync    ← scrapes your schedule\033[0m\n")
                else:
                    from div_knowt import format_for_display
                    print(f"\n\033[94m{format_for_display(_knowt_cache)}\033[0m\n")
            continue

        if cmd_lower.startswith('/canvas'):
            parts = user_input.split(None, 3)
            sub   = parts[1].lower() if len(parts) > 1 else ""

            if sub == "url":
                if len(parts) < 3:
                    current = CANVAS_URL or "not set"
                    print(f"\033[91m  ⎿ Usage: /canvas url <school-url>\033[0m")
                    print(f"\033[90m       Current: {current}\033[0m")
                    print(f"\033[90m       Example: /canvas url myschool.instructure.com\033[0m\n")
                else:
                    CANVAS_URL = parts[2].rstrip('/')
                    save_config()
                    print(f"\033[92m  ⎿ Canvas URL set: {CANVAS_URL}\033[0m\n")

            elif sub == "setup":
                if len(parts) < 3:
                    print(f"\033[91m  ⎿ Usage: /canvas setup <api-token>\033[0m")
                    print(f"\033[90m       Get your token: Canvas → Account → Settings → New Access Token\033[0m\n")
                elif len(parts) == 4:
                    CANVAS_URL, CANVAS_TOKEN = parts[2].rstrip('/'), parts[3]
                else:
                    if not CANVAS_URL:
                        print(f"\033[91m  ⎿ No URL set yet. Run: /canvas url <your-school.instructure.com>\033[0m\n")
                        continue
                    CANVAS_TOKEN = parts[2]
                save_config()
                print(f"\033[90m  ⎿ Connecting to Canvas at {CANVAS_URL}...\033[0m")
                refresh_canvas_cache()
                refresh_canvas_courses()
                if _canvas_cache and "error" in _canvas_cache[0]:
                    print(f"\033[91m  ⎿ Canvas error: {_canvas_cache[0]['error']}\033[0m\n")
                else:
                    count = len(_canvas_cache) if _canvas_cache else 0
                    print(f"\033[92m  ⎿ Canvas linked — {count} upcoming assignments found.\033[0m")
                messages[0]["content"] = build_system_prompt()
                save_memory(messages)

            else:
                if not CANVAS_URL or not CANVAS_TOKEN:
                    print(f"\033[91m  ⎿ Canvas not configured. Run:\033[0m")
                    if not CANVAS_URL:
                        print(f"\033[90m       /canvas url <your-school.instructure.com>\033[0m")
                    print(f"\033[90m       /canvas setup <api-token>\033[0m")
                    print(f"\033[90m     Get your token: Canvas → Account → Settings → New Access Token\033[0m\n")
                else:
                    print(f"\033[90m  ⎿ Refreshing Canvas assignments...\033[0m")
                    refresh_canvas_cache()
                    from div_canvas import format_for_display
                    print(f"\n\033[94m{format_for_display(_canvas_cache)}\033[0m\n")
            continue

        if cmd_lower == '/speak':
            TTS_ENABLED = not TTS_ENABLED
            state = "\033[92mON\033[0m" if TTS_ENABLED else "\033[91mOFF\033[0m"
            print(f"\033[92m  ⎿ TTS {state}  (voice: {TTS_VOICE})\033[0m\n")
            continue

        if cmd_lower.startswith('/speak-voice '):
            TTS_VOICE = user_input.split(None, 1)[1].strip()
            save_config()
            print(f"\033[92m  ⎿ Voice set to: {TTS_VOICE}\033[0m\n")
            continue

        if cmd_lower.startswith('/speak-rate'):
            parts = user_input.split(None, 1)
            if len(parts) < 2:
                print(f"\033[94m  ⎿ Current rate: {TTS_RATE}  (e.g. +0%, +25%, +50%, -10%)\033[0m\n")
            else:
                import re as _re
                raw = parts[1].strip()
                # auto-prefix + if no sign given (e.g. "25%" → "+25%")
                if raw and raw[0].isdigit():
                    raw = "+" + raw
                if not _re.match(r'^[+-]\d+%$', raw):
                    print(f"\033[91m  ⎿ Invalid rate '{raw}' — use format like +25%, -10%, +0%\033[0m\n")
                else:
                    TTS_RATE = raw
                    save_config()
                    print(f"\033[92m  ⎿ TTS rate set to: {TTS_RATE}\033[0m\n")
            continue

        # ── OSINT: investigate <case name> [--refresh] ──
        if cmd_lower.startswith('investigate'):
            _parts = user_input.split(None, 1)
            _rest = _parts[1].strip() if len(_parts) > 1 else ""
            _refresh_flag = "--refresh" in _rest
            _case_name = _rest.replace("--refresh", "").strip()
            if not _case_name:
                print(f"\033[91m  ⎿ Usage: investigate <case name> [--refresh]\033[0m\n")
                continue
            try:
                from div_osint import run_investigation as _run_osint
                _shared_key = MODELS.get("full", {}).get("key", "")
                _osint_slot = "brain" if (MODELS.get("brain", {}).get("key") or _shared_key) else "code"
                _osint_model = MODELS.get(_osint_slot, MODELS.get("full", {}))
                _osint_model_name = _osint_model.get("model", "")
                _osint_key = _osint_model.get("key") or _shared_key
                if _osint_key:
                    os.environ["OPENAI_API_KEY"] = _osint_key
                _run_osint(
                    case_name=_case_name,
                    cli_dir=CLI_DIR,
                    completion_fn=completion,
                    model=_osint_model_name,
                    api_key=_osint_key or None,
                    vault_path=GLOBAL_VAULT or None,
                    refresh=_refresh_flag,
                    speak_fn=speak if TTS_ENABLED else None,
                )
            except ImportError:
                print(f"\033[91m  ⎿ OSINT module not found. Ensure div_osint.py is in the divAI directory.\033[0m\n")
            except Exception as _e:
                print(f"\033[91m  ⎿ Investigation error: {_e}\033[0m\n")
            continue

        # ── OSINT: show contradictions / show leads ──
        if cmd_lower.startswith('show contradictions') or cmd_lower.startswith('show leads'):
            try:
                from div_osint import latest_cached_investigation as _osint_latest, interactive_contradiction_review as _osint_review
                _latest = _osint_latest(CLI_DIR)
                if not _latest:
                    print(f"\033[91m  ⎿ No cached investigation. Run: investigate <case name>\033[0m\n")
                    continue
                _case = _latest.get("case_name", "Unknown")
                if "contradictions" in cmd_lower:
                    _contrs = _latest.get("contradictions", [])
                    if not _contrs:
                        print(f"\033[94m  ⎿ No contradictions found in: {_case}\033[0m\n")
                    else:
                        print(f"\n\033[93m⚠️  Contradictions for: {_case}\033[0m")
                        _osint_review(_contrs)
                else:
                    _leads = _latest.get("leads", {})
                    # optional tier filter: "show leads tier 1" → only tier1
                    _tier_filter = None
                    for _t in ("1", "2", "3"):
                        if f"tier {_t}" in cmd_lower:
                            _tier_filter = f"tier{_t}"
                    print(f"\n\033[94m📋 Priority Leads for: {_case}\033[0m")
                    for _tier, _tier_leads in _leads.items():
                        if _tier_filter and _tier != _tier_filter:
                            continue
                        if _tier_leads:
                            print(f"\n  {_tier.upper()}:")
                            for _lead in _tier_leads:
                                print(f"    {_lead.get('rank','')}. {_lead.get('title','')} — {_lead.get('osint_potential','')}")
                    print()
            except Exception as _e:
                print(f"\033[91m  ⎿ Error: {_e}\033[0m\n")
            continue

        # ── OSINT: read investigation brief ──
        if cmd_lower.startswith('read investigation') or cmd_lower == 'read investigation brief':
            try:
                from div_osint import latest_cached_investigation as _osint_latest
                _latest = _osint_latest(CLI_DIR)
                if not _latest:
                    print(f"\033[91m  ⎿ No cached investigation. Run: investigate <case name>\033[0m\n")
                    continue
                _case = _latest.get("case_name", "Unknown")
                _claims = _latest.get("claims", [])
                _contrs = _latest.get("contradictions", [])
                _leads = _latest.get("leads", {})
                parts = [f"I found {len(_claims)} claims about {_case} across all public sources."]
                if _contrs:
                    parts.append(f"I detected {len(_contrs)} contradiction{'s' if len(_contrs)!=1 else ''} in the public record.")
                    parts.append(f"The highest-priority is: {_contrs[0].get('topic','an unresolved discrepancy')}.")
                if _leads.get("tier1"):
                    parts.append(f"Top lead: {_leads['tier1'][0].get('title','')}.")
                if GLOBAL_VAULT:
                    parts.append(f"Full investigation files are in your Obsidian vault at /investigations/.")
                _brief = " ".join(parts)
                print(f"\n\033[94m●\033[0m\n{render_response(_brief)}\n")
                speak(_brief)
            except Exception as _e:
                print(f"\033[91m  ⎿ Error: {_e}\033[0m\n")
            continue

        # ── Social Profile OSINT: profile <name> [--refresh] ──
        if re.match(r'^profile(\s|$)', cmd_lower):
            _parts = user_input.split(None, 1)
            _raw_args = _parts[1].strip() if len(_parts) > 1 else ""
            _refresh_flag = "--refresh" in _raw_args
            _raw_args_clean = _raw_args.replace("--refresh", "").strip()
            if not _raw_args_clean:
                print(f"\033[91m  ⎿ Usage: profile <name> [--location \"City, ST\"] [--username handle] [--company \"Co\"] [--email addr]\033[0m\n")
                continue
            try:
                from div_profile import run_profile as _run_profile, parse_profile_args as _parse_profile_args
                _p_name, _p_hints = _parse_profile_args(_raw_args_clean)
                if not _p_name:
                    print(f"\033[91m  ⎿ Name required. Usage: profile <name> [--location \"City, ST\"] [--username handle]\033[0m\n")
                    continue
                _shared_key = MODELS.get("full", {}).get("key", "")
                _p_slot = "brain" if (MODELS.get("brain", {}).get("key") or _shared_key) else "code"
                _p_model = MODELS.get(_p_slot, MODELS.get("full", {}))
                _p_key = _p_model.get("key") or _shared_key
                if _p_key:
                    os.environ["OPENAI_API_KEY"] = _p_key
                _run_profile(
                    name=_p_name,
                    hints=_p_hints,
                    cli_dir=CLI_DIR,
                    completion_fn=completion,
                    model=_p_model.get("model", ""),
                    api_key=_p_key or None,
                    vault_path=GLOBAL_VAULT or None,
                    refresh=_refresh_flag,
                    speak_fn=speak if TTS_ENABLED else None,
                )
            except ImportError:
                print(f"\033[91m  ⎿ Profile module not found. Ensure div_profile.py is in the divAI directory.\033[0m\n")
            except Exception as _e:
                print(f"\033[91m  ⎿ Profile error: {_e}\033[0m\n")
            continue

        # ── OSINT: narrate [case name] ──
        if cmd_lower == 'narrate' or cmd_lower.startswith('narrate '):
            try:
                from div_osint import (
                    latest_cached_investigation as _osint_latest,
                    load_cache as _osint_load,
                    generate_narrative_brief as _osint_narrate,
                    extract_voiceover as _osint_voiceover,
                )
                _parts = user_input.split(None, 1)
                _narrate_case = _parts[1].strip() if len(_parts) > 1 else ""
                _inv = _osint_load(CLI_DIR, _narrate_case) if _narrate_case else _osint_latest(CLI_DIR)
                if not _inv:
                    hint = f"investigate {_narrate_case}" if _narrate_case else "investigate <case name>"
                    print(f"\033[91m  ⎿ No cached investigation{' for '+_narrate_case if _narrate_case else ''}. Run: {hint}\033[0m\n")
                    continue
                _case_display = _inv.get("case_name", _narrate_case or "Unknown")
                print(f"\n\033[94m🎬 Generating narrative brief for: {_case_display}...\033[0m")
                _sp = _start_spinner()
                try:
                    _shared_key = MODELS.get("full", {}).get("key", "")
                    _n_slot = "brain" if (MODELS.get("brain", {}).get("key") or _shared_key) else "code"
                    _n_model = MODELS.get(_n_slot, MODELS.get("full", {}))
                    _n_model_name = _n_model.get("model", "")
                    _n_key = _n_model.get("key") or _shared_key
                    if _n_key:
                        os.environ["OPENAI_API_KEY"] = _n_key
                    _narrative = _osint_narrate(
                        inv_data=_inv,
                        completion_fn=completion,
                        model=_n_model_name,
                        api_key=_n_key or None,
                    )
                finally:
                    _stop_spinner(_sp)
                # ── Render narrative with section-aware coloring ──
                _section_colors = {
                    "🎬": "\033[94m",   # blue
                    "⚠": "\033[93m",    # yellow
                    "🔴": "\033[91m",   # red
                    "🟡": "\033[93m",   # yellow
                    "⚪": "\033[90m",   # gray
                    "❓": "\033[96m",   # cyan
                    "🎤": "\033[92m",   # green
                }
                print()
                _in_content = False
                for _line in _narrative.splitlines():
                    _stripped = _line.strip()
                    _matched_color = None
                    for _emoji, _color in _section_colors.items():
                        if _stripped.startswith(_emoji):
                            _matched_color = _color
                            break
                    if _matched_color:
                        print(f"\n{_matched_color}{_stripped}\033[0m")
                        _in_content = True
                    elif _stripped == "---":
                        print(f"\033[90m{'─' * 44}\033[0m")
                        _in_content = False
                    elif _in_content and _stripped:
                        print(f"\033[97m  {_stripped}\033[0m")
                print()
                # ── Speak the voiceover ──
                _vo = _osint_voiceover(_narrative)
                if _vo:
                    if TTS_ENABLED:
                        print(f"\033[90m[Speaking voiceover...]\033[0m")
                        _speak_async(_vo)
                    else:
                        print(f"\033[90m[Tip: toggle /speak to hear the voiceover aloud]\033[0m\n")
            except Exception as _e:
                print(f"\033[91m  ⎿ Narration error: {_e}\033[0m\n")
            continue

        # ── Context system commands ──
        if user_input.lower().startswith("mode:"):
            _explicit_mode = user_input.split("mode:", 1)[1].strip().lower()
            loader = _get_loader()
            if loader:
                if _explicit_mode not in loader.CONTEXT_MAP:
                    valid = ", ".join(loader.CONTEXT_MAP.keys())
                    print(f"\033[91m  ⎿ Unknown mode '{_explicit_mode}'. Valid: {valid}\033[0m\n")
                else:
                    _active_context_modes[:] = [_explicit_mode]
                    ctx = loader.build_context("", explicit_mode=_explicit_mode)
                    messages.append({"role": "system", "content": f"[Context loaded: {_explicit_mode}]\n\n{ctx}"})
                    save_memory(messages)
                    print(f"\033[92m  ⎿ Context loaded: {_explicit_mode}\033[0m\n")
            continue

        if user_input.lower() == "summarize session":
            summarizer = _get_summarizer()
            if summarizer:
                summarizer.save_session_summary(messages)
            continue

        if user_input.lower() == "context status":
            loader = _get_loader()
            if loader and _last_user_prompt:
                detected = loader.classify_intent(_last_user_prompt)
                active = _active_context_modes or detected or ["core only"]
                print(f"\033[94m  ⎿ Active contexts: {', '.join(active)}\033[0m\n")
            else:
                active = _active_context_modes or ["core only"]
                print(f"\033[94m  ⎿ Active contexts: {', '.join(active)}\033[0m\n")
            continue

        _last_user_prompt = user_input

        # auto-inject context block for the first message of a session if vault has content
        if len(messages) == 1:  # only system prompt so far
            loader = _get_loader()
            if loader:
                _active_context_modes[:] = loader.classify_intent(user_input)
                if _active_context_modes:
                    ctx = loader.build_context(user_input)
                    if ctx.strip():
                        messages.append({"role": "system", "content": f"[divAI context — auto-loaded]\n\n{ctx}"})

        messages.append({"role": "user", "content": user_input})
        save_memory(messages)
        
        effective_mode = route_message(user_input) if current_mode == "auto" else current_mode
        if current_mode == "auto":
            if effective_mode == "brain":
                try:
                    confirm = input(f"\033[90m  ⎿ [auto → brain: {MODELS['brain']['model']}]  use it? [y/N] \033[0m").strip().lower()
                except EOFError:
                    confirm = "n"
                if confirm != "y":
                    effective_mode = "talk"
            print(f"\033[90m  ⎿ [auto → {effective_mode}: {MODELS[effective_mode]['model']}]\033[0m")

        _active_key = MODELS[effective_mode].get("key", "") or MODELS.get("full", {}).get("key", "")
        if _active_key:
            os.environ["OPENAI_API_KEY"] = _active_key

        while True:
            api_kwargs = {"model": MODELS[effective_mode]["model"], "messages": _trim_messages(messages)}
            if _active_key:
                api_kwargs["api_key"] = _active_key
            if MODELS[effective_mode].get("api_base"):
                api_kwargs["api_base"] = MODELS[effective_mode]["api_base"]
            _model = MODELS[effective_mode]["model"]
            if "groq" not in _model and "deepseek" not in _model and "ollama" not in _model:
                api_kwargs["tools"] = tools
                api_kwargs["tool_choice"] = "auto"
                
            _sp = _start_spinner()
            try:
                response = completion(**api_kwargs)
            finally:
                _stop_spinner(_sp)
            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_none=True)) 
            save_memory(messages)
            
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool in msg.tool_calls:
                    func = tool.function.name
                    args = json.loads(tool.function.arguments)
                    print(f"\033[90m  ⎿ Executing: {func}(...)\033[0m")
                    
                    if func == "run_command": out = run_command(args.get("command", ""))
                    elif func == "read_file": out = read_file(args.get("path", ""))
                    elif func == "write_file": out = write_file(args.get("path", ""), args.get("content", ""))
                    elif func == "edit_file": out = edit_file(args.get("path", ""), args.get("old_string", ""), args.get("new_string", ""))
                    elif func == "list_directory": out = list_directory(args.get("path", ""))
                    elif func == "search_vault": out = search_vault(args.get("query", ""))
                    elif func == "read_vault_note": out = read_vault_note(args.get("note_name", ""))
                    elif func == "write_vault_note": out = write_vault_note(args.get("note_name", ""), args.get("content", ""), args.get("mode", "append"))
                    elif func == "search_web": out = search_web(args.get("query", ""))
                    elif func == "get_canvas_overview": out = get_canvas_overview(args.get("days_ahead", 14))
                    elif func == "get_canvas_assignments": out = get_canvas_assignments(args.get("days_ahead", 21))
                    elif func == "canvas_api": out = canvas_api_call(args.get("endpoint", ""), args.get("params"))
                    elif func == "get_knowt_schedule": out = get_knowt_schedule()
                    elif func == "get_fiveable_schedule": out = get_fiveable_schedule()
                    elif func == "fetch_url": out = fetch_url(args.get("url", ""))
                    elif func == "search_fiveable": out = search_fiveable(args.get("topic", ""))
                    elif func == "set_reminder": out = set_reminder(args.get("minutes", 1), args.get("message", ""))
                    elif func == "render_cell": out = _render_cell(args.get("cell_type", ""), args.get("params", {}))
                    else: out = "Unknown tool"

                    if len(out) > 6000: out = out[:6000] + "... [TRUNCATED]"
                    messages.append({"role": "tool", "tool_call_id": tool.id, "name": func, "content": out})
                save_memory(messages)
                continue

            elif msg.content and "<function" in msg.content:
                match = re.search(r'<function[=/\\(]*\s*(\w+)[>\\)]*\s*(\{.*?\})\s*</function>', msg.content, re.DOTALL)
                if match:
                    func = match.group(1)
                    args_str = match.group(2)
                    try: args = json.loads(args_str)
                    except: args = {"command": args_str}

                    print(f"\033[90m  ⎿ Executing (XML mode): {func}(...)\033[0m")

                    if func == "run_command": out = run_command(args.get("command", ""))
                    elif func == "read_file": out = read_file(args.get("path", ""))
                    elif func == "write_file": out = write_file(args.get("path", ""), args.get("content", ""))
                    elif func == "edit_file": out = edit_file(args.get("path", ""), args.get("old_string", ""), args.get("new_string", ""))
                    elif func == "list_directory": out = list_directory(args.get("path", ""))
                    elif func == "search_vault": out = search_vault(args.get("query", ""))
                    elif func == "read_vault_note": out = read_vault_note(args.get("note_name", ""))
                    elif func == "write_vault_note": out = write_vault_note(args.get("note_name", ""), args.get("content", ""), args.get("mode", "append"))
                    elif func == "search_web": out = search_web(args.get("query", ""))
                    elif func == "get_canvas_overview": out = get_canvas_overview(args.get("days_ahead", 14))
                    elif func == "get_canvas_assignments": out = get_canvas_assignments(args.get("days_ahead", 21))
                    elif func == "canvas_api": out = canvas_api_call(args.get("endpoint", ""), args.get("params"))
                    elif func == "get_knowt_schedule": out = get_knowt_schedule()
                    elif func == "get_fiveable_schedule": out = get_fiveable_schedule()
                    elif func == "fetch_url": out = fetch_url(args.get("url", ""))
                    elif func == "search_fiveable": out = search_fiveable(args.get("topic", ""))
                    elif func == "set_reminder": out = set_reminder(args.get("minutes", 1), args.get("message", ""))
                    elif func == "render_cell": out = _render_cell(args.get("cell_type", ""), args.get("params", {}))
                    else: out = "Unknown tool"

                    if len(out) > 6000: out = out[:6000] + "... [TRUNCATED]"
                    messages.append({"role": "system", "content": f"Tool '{func}' execution result:\n{out}"})
                    save_memory(messages)
                    continue
                
            clean_msg = msg.content if msg.content else ""
            clean_msg = re.sub(r'<function.*?</function>', '', clean_msg, flags=re.DOTALL)
            if clean_msg.strip():
                _clean = clean_msg.strip()
                if TTS_ENABLED:
                    _speak_async(_clean)  # start generating before print — overlaps with render time
                print(f"\n\033[94m●\033[0m\n{render_response(_clean)}\n")
            break
                
    except Exception as e:
        print(f"\033[91mAPI Error: {str(e)}\033[0m\n")
        if len(messages) > 1: 
            messages.pop()
            save_memory(messages)
