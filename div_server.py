#!/usr/bin/env python3
"""divAI Mobile Dispatch Server — access divAI from your phone"""

import os, json, re, subprocess, asyncio, tempfile
import requests as http_requests
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from litellm import completion
import uvicorn

# ──────────────────────────────────────────────
# CONFIG  (mirrors divCLI.py)
# ──────────────────────────────────────────────
CLI_DIR      = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(CLI_DIR, "div_config.json")
PERSONA_FILE = os.path.join(CLI_DIR, "div_persona.txt")
MEMORY_FILE  = os.path.join(CLI_DIR, "div_memory.json")

DEFAULT_MODELS = {
    "talk":  {"model": "groq/llama-3.3-70b-versatile",  "key": ""},
    "code":  {"model": "github/gpt-4o",                  "key": ""},
    "brain": {"model": "deepseek/deepseek-reasoner",     "key": ""},
    "full":  {"model": "openai/gpt-4o",                  "key": ""},
}

if os.path.exists(CONFIG_FILE):
    try:
        data         = json.load(open(CONFIG_FILE))
        MODELS       = data.get("models", DEFAULT_MODELS)
        GLOBAL_VAULT = data.get("vault", "")
        CANVAS_URL   = data.get("canvas_url", "")
        CANVAS_TOKEN = data.get("canvas_token", "")
    except:
        MODELS, GLOBAL_VAULT, CANVAS_URL, CANVAS_TOKEN = DEFAULT_MODELS, "", "", ""
else:
    MODELS, GLOBAL_VAULT, CANVAS_URL, CANVAS_TOKEN = DEFAULT_MODELS, "", "", ""

WHISPER_KEY = MODELS.get("talk", {}).get("key", "")

current_mode  = "full"
_canvas_cache = None

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump({"models": MODELS, "vault": GLOBAL_VAULT,
                   "canvas_url": CANVAS_URL, "canvas_token": CANVAS_TOKEN}, f, indent=4)

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

refresh_canvas_cache()

def load_knowt_cache():
    try:
        from div_knowt import load_cache
        return load_cache()
    except Exception:
        return None

_knowt_cache = load_knowt_cache()

def load_fiveable_cache():
    try:
        from div_fiveable import load_cache
        return load_cache()
    except Exception:
        return None

_fiveable_cache = load_fiveable_cache()

# ──────────────────────────────────────────────
# TOOLS  (identical to divCLI.py)
# ──────────────────────────────────────────────
tools = [
    {"type":"function","function":{"name":"run_command","description":"Executes a powershell command.","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}},
    {"type":"function","function":{"name":"read_file","description":"Reads a file.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"write_file","description":"Writes to a file.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
    {"type":"function","function":{"name":"edit_file","description":"Edits a file by replacing an exact string. Always read_file first.","parameters":{"type":"object","properties":{"path":{"type":"string"},"old_string":{"type":"string"},"new_string":{"type":"string"}},"required":["path","old_string","new_string"]}}},
    {"type":"function","function":{"name":"list_directory","description":"Lists all files in a folder.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"search_vault","description":"Searches Obsidian vault for a keyword.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"read_vault_note","description":"Reads a specific Obsidian note.","parameters":{"type":"object","properties":{"note_name":{"type":"string"}},"required":["note_name"]}}},
    {"type":"function","function":{"name":"write_vault_note","description":"Creates or appends to an Obsidian note.","parameters":{"type":"object","properties":{"note_name":{"type":"string"},"content":{"type":"string"},"mode":{"type":"string","enum":["overwrite","append"]}},"required":["note_name","content","mode"]}}},
    {"type":"function","function":{"name":"search_web","description":"Searches the internet for real-time information.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"get_canvas_overview","description":"Fetches a FRESH, comprehensive Canvas snapshot: upcoming assignments AND recent teacher announcements. Call this whenever the user asks what Canvas looks like, what's due, any announcements, or anything Canvas-related.","parameters":{"type":"object","properties":{"days_ahead":{"type":"integer","description":"Days ahead to look (default 14)"}},"required":[]}}},
    {"type":"function","function":{"name":"get_canvas_assignments","description":"Fetches only upcoming Canvas assignments (no announcements). Prefer get_canvas_overview for a full picture.","parameters":{"type":"object","properties":{"days_ahead":{"type":"integer","description":"Days ahead to look (default 21)"}},"required":[]}}},
    {"type":"function","function":{"name":"canvas_api","description":"Makes a GET request to any Canvas LMS API endpoint. Use for grades, announcements, files, modules, quizzes, submissions, etc.","parameters":{"type":"object","properties":{"endpoint":{"type":"string"},"params":{"type":"object"}},"required":["endpoint"]}}},
    {"type":"function","function":{"name":"get_knowt_schedule","description":"Fetches the user's Knowt study schedule — upcoming exams, what to study today, flashcard progress.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"get_fiveable_schedule","description":"Fetches the user's Fiveable AP study progress — upcoming AP exams, study guide completion, daily recommendations.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"fetch_url","description":"Fetches the content of any URL and returns cleaned text. Use for Fiveable study guides, Knowt sets, or any webpage.","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}},
    {"type":"function","function":{"name":"search_fiveable","description":"Searches Fiveable for AP study content (unit overviews, key concepts, practice FRQs). Use whenever user asks about an AP topic.","parameters":{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"]}}},
    {"type":"function","function":{"name":"set_reminder","description":"Sets a timed reminder. Calculate minutes from NOW to the target time, then call this. Use when user asks to be reminded at a time or after a duration.","parameters":{"type":"object","properties":{"minutes":{"type":"integer"},"message":{"type":"string"}},"required":["minutes","message"]}}},
]

def run_command(command):
    try:
        r = subprocess.run(["powershell","-Command",command], capture_output=True, text=True, timeout=30)
        return r.stdout or r.stderr or "Success (no output)"
    except Exception as e: return str(e)

def read_file(path):
    try:
        with open(path,'r',encoding='utf-8') as f: return f.read()
    except Exception as e: return str(e)

def write_file(path, content):
    try:
        with open(path,'w',encoding='utf-8') as f: f.write(content)
        return f"Wrote to {path}"
    except Exception as e: return str(e)

def edit_file(path, old_string, new_string):
    try:
        with open(path,'r',encoding='utf-8') as f: content = f.read()
        if old_string not in content: return f"Error: Text not found in {path}. Use read_file first."
        with open(path,'w',encoding='utf-8') as f: f.write(content.replace(old_string, new_string, 1))
        return f"Successfully edited {path}"
    except Exception as e: return str(e)

def list_directory(path):
    try: return "\n".join(os.listdir(path))
    except Exception as e: return str(e)

def search_vault(query):
    if not GLOBAL_VAULT: return "Vault not linked."
    matches = []
    for root,_,files in os.walk(GLOBAL_VAULT):
        for fn in files:
            if fn.endswith(".md"):
                try:
                    with open(os.path.join(root,fn),'r',encoding='utf-8') as f:
                        if query.lower() in f.read().lower(): matches.append(fn)
                except: pass
    return f"Found in: {', '.join(matches)}" if matches else "No matches."

def read_vault_note(note_name):
    if not GLOBAL_VAULT: return "Vault not linked."
    if not note_name.endswith(".md"): note_name += ".md"
    for root,_,files in os.walk(GLOBAL_VAULT):
        if note_name in files:
            try:
                with open(os.path.join(root,note_name),'r',encoding='utf-8') as f: return f.read()
            except Exception as e: return str(e)
    return "Note not found."

def write_vault_note(note_name, content, mode):
    if not GLOBAL_VAULT: return "Vault not linked."
    if not note_name.endswith(".md"): note_name += ".md"
    path = os.path.join(GLOBAL_VAULT, note_name)
    try:
        m = 'a' if mode == 'append' else 'w'
        with open(path, m, encoding='utf-8') as f: f.write(("\n\n" if mode=='append' else "") + content)
        if os.path.exists(os.path.join(GLOBAL_VAULT,".git")):
            subprocess.run(["git","add","."], cwd=GLOBAL_VAULT, capture_output=True)
            subprocess.run(["git","commit","-m",f"divAI: {mode}ed {note_name}"], cwd=GLOBAL_VAULT, capture_output=True)
            subprocess.run(["git","push"], cwd=GLOBAL_VAULT, capture_output=True)
        return f"{mode.capitalize()}d {note_name}"
    except Exception as e: return str(e)

def search_web(query):
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=5)
        if not results: return "No results."
        return "\n\n".join(f"[{r['title']}]({r['href']}): {r['body']}" for r in results)
    except ImportError:
        return "ddgs not installed. Run: pip install ddgs"
    except Exception as e:
        return f"Search failed: {e}"

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
        results = DDGS().text(f"site:fiveable.me {topic}", max_results=3)
        if not results:
            return f"No Fiveable results for '{topic}'."
        top = results[0]
        url = top.get("href", "")
        content = fetch_url(url) if url else ""
        if content and not content.startswith("Failed"):
            return f"[Source: {url}]\n\n{content}"
        return f"[{top.get('title')}]({url}): {top.get('body','')}"
    except ImportError:
        return "ddgs not installed. Run: pip install ddgs"
    except Exception as e:
        return f"Fiveable search failed: {e}"

def set_reminder(minutes, message):
    try:
        minutes = int(minutes)
        if minutes < 1:
            return "Error: minutes must be at least 1."
        def fire():
            try:
                from div_notify import toast
                toast("divAI Reminder", message)
            except Exception:
                pass
        import threading as _th
        t = _th.Timer(minutes * 60, fire)
        t.daemon = True
        t.start()
        h, m = divmod(minutes, 60)
        when = (f"{h}h {m}m" if h else f"{m}m").strip()
        return f"Reminder set for {when} from now: \"{message}\""
    except Exception as e:
        return f"Failed to set reminder: {str(e)}"

def canvas_api_call(endpoint, params=None):
    if not CANVAS_URL or not CANVAS_TOKEN:
        return "Canvas not configured."
    try:
        from div_canvas import canvas_api
        result = canvas_api(CANVAS_URL, CANVAS_TOKEN, endpoint, params)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Canvas API error: {str(e)}"

def execute_tool(func: str, args: dict) -> str:
    def _canvas_overview():
        if not CANVAS_URL or not CANVAS_TOKEN:
            return "Canvas not configured. Use /canvas setup in the CLI."
        from div_canvas import fetch_upcoming_assignments, fetch_announcements, format_for_display
        assignments = fetch_upcoming_assignments(CANVAS_URL, CANVAS_TOKEN, args.get("days_ahead", 14))
        out = ["── Upcoming Assignments ──", format_for_display(assignments)]
        from div_canvas import fetch_courses
        courses = fetch_courses(CANVAS_URL, CANVAS_TOKEN) if CANVAS_URL and CANVAS_TOKEN else []
        if courses:
            ids = [c["id"] for c in courses if "error" not in c]
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

    def _canvas():
        if not CANVAS_URL or not CANVAS_TOKEN:
            return "Canvas not configured. Use /canvas setup in the CLI."
        from div_canvas import fetch_upcoming_assignments, format_for_display
        return format_for_display(fetch_upcoming_assignments(CANVAS_URL, CANVAS_TOKEN, args.get("days_ahead", 21)))

    def _knowt():
        data = load_knowt_cache()
        if not data:
            return "Knowt not set up. Use /knowt setup in the CLI first, then /knowt sync."
        from div_knowt import format_for_display
        return format_for_display(data)

    dispatch = {
        "run_command":    lambda: run_command(args.get("command","")),
        "read_file":      lambda: read_file(args.get("path","")),
        "write_file":     lambda: write_file(args.get("path",""), args.get("content","")),
        "edit_file":      lambda: edit_file(args.get("path",""), args.get("old_string",""), args.get("new_string","")),
        "list_directory": lambda: list_directory(args.get("path","")),
        "search_vault":   lambda: search_vault(args.get("query","")),
        "read_vault_note":  lambda: read_vault_note(args.get("note_name","")),
        "write_vault_note": lambda: write_vault_note(args.get("note_name",""), args.get("content",""), args.get("mode","append")),
        "search_web":     lambda: search_web(args.get("query","")),
        "get_canvas_overview":    _canvas_overview,
        "get_canvas_assignments": _canvas,
        "canvas_api":     lambda: canvas_api_call(args.get("endpoint",""), args.get("params")),
        "get_knowt_schedule":     _knowt,
        "get_fiveable_schedule":  lambda: (load_fiveable_cache() and __import__('div_fiveable').format_for_display(load_fiveable_cache())) or "Fiveable not configured.",
        "fetch_url":              lambda: fetch_url(args.get("url","")),
        "search_fiveable":        lambda: search_fiveable(args.get("topic","")),
        "set_reminder":           lambda: set_reminder(args.get("minutes", 1), args.get("message", "")),
    }
    return dispatch.get(func, lambda: "Unknown tool")()

# ──────────────────────────────────────────────
# MEMORY
# ──────────────────────────────────────────────
def build_system_prompt():
    try:
        with open(PERSONA_FILE,"r",encoding="utf-8") as f: prompt = f.read()
    except: prompt = "You are divAI."

    prompt += """\n\n[CRITICAL DIRECTIVE - TOOL EXECUTION]
You have FULL unrestricted access to the user's computer, local files, and the LIVE INTERNET.
NEVER say "I don't have access to the internet" or "I cannot search the web". YOU CAN.
To perform actions, you MUST output EXACTLY this XML block:
<function=tool_name>{"arg1": "value"}</function>

1. run_command: {"command": "powershell string"}
2. read_file: {"path": "string"}
3. write_file: {"path": "string", "content": "string"}
4. list_directory: {"path": "string"}
5. search_vault: {"query": "string"}
6. read_vault_note: {"note_name": "string"}
7. write_vault_note: {"note_name": "string", "content": "string", "mode": "overwrite|append"}
8. search_web: {"query": "search term"}
9. fetch_url: {"url": "https://..."}
10. search_fiveable: {"topic": "APES unit 9 overview"}
11. set_reminder: {"minutes": 45, "message": "submit the CS homework"}

If the user asks about recent events or unknown concepts, IMMEDIATELY use search_web.

[REMINDERS]
Current local datetime: {NOW}
When the user asks to be reminded about something (at a time, after a duration, or before an event):
- Calculate how many minutes from NOW to the target time.
- IMMEDIATELY call set_reminder with that many minutes and the reminder message.
- Confirm with the exact time it will fire (e.g. "Reminder set for 5:00 AM — that's 214 minutes from now").

[STUDY PLATFORM INTELLIGENCE]
You have LIVE access to Fiveable and Knowt content via your tools. NEVER say you can't access these sites.
- When the user asks about an AP subject, unit overview, key concepts, study guide, FRQ practice, or ANY educational content: IMMEDIATELY call search_fiveable with the topic.
- When the user says "pull X", "show me X", "give me X" about a study topic: fetch it right away without asking.
- Use fetch_url to read any specific Fiveable or Knowt URL provided or found in search results.
- Use search_web("site:knowt.com {topic}") for Knowt flashcard sets specifically.
You are an active study assistant — go get the content, don't wait to be asked twice."""

    from datetime import datetime as _dt
    now_str = _dt.now().strftime("%A, %B %#d %Y at %#I:%M %p")
    prompt = prompt.replace("{NOW}", now_str)

    if GLOBAL_VAULT: prompt += f"\n\n[OBSIDIAN VAULT]: Connected to {GLOBAL_VAULT}."
    claude_md = os.path.join(CLI_DIR, "CLAUDE.md")
    if os.path.exists(claude_md): prompt += "\n\n[CLAUDE.md]:\n" + read_file(claude_md)
    if _canvas_cache is not None:
        from div_canvas import format_for_prompt as canvas_fmt
        prompt += f"\n\n[CANVAS LMS — UPCOMING ASSIGNMENTS]:\n{canvas_fmt(_canvas_cache)}"
        prompt += "\nRemind the user proactively when assignments are due soon."
    if _knowt_cache is not None:
        from div_knowt import format_for_prompt as knowt_fmt
        prompt += f"\n\n[KNOWT STUDY SCHEDULE]:\n{knowt_fmt(_knowt_cache)}"
        prompt += "\nRemind the user about upcoming exams and today's study plan."
    if _fiveable_cache is not None:
        from div_fiveable import format_for_prompt as fiveable_fmt
        prompt += f"\n\n[FIVEABLE AP PROGRESS]:\n{fiveable_fmt(_fiveable_cache)}"
        prompt += "\nRemind the user about upcoming AP exams and their study guide progress."
    return prompt

_MSG_FIELDS = {"role", "content", "name", "tool_calls", "tool_call_id", "function_call"}

def clean_messages(msgs):
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

def save_memory(msgs):
    with open(MEMORY_FILE,"w",encoding="utf-8") as f: json.dump(msgs, f, indent=4)

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            msgs = json.load(open(MEMORY_FILE))
            if msgs:
                msgs[0] = {"role":"system","content":build_system_prompt()}
                return msgs
        except: pass
    return [{"role":"system","content":build_system_prompt()}]

messages = load_memory()

# ──────────────────────────────────────────────
# FASTAPI APP
# ──────────────────────────────────────────────
app = FastAPI(title="divAI Dispatch")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ChatRequest(BaseModel):
    message: str

class CommandRequest(BaseModel):
    command: str
    arg: str = ""

class RemindReq(BaseModel):
    minutes: int
    message: str

def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"

# ──────────────────────────────────────────────
# AGENT LOOP (async SSE generator)
# ──────────────────────────────────────────────
async def agent_stream(user_input: str):
    global messages
    loop = asyncio.get_event_loop()

    messages.append({"role":"user","content":user_input})
    save_memory(messages)

    yield sse({"type":"status","text":"Thinking..."})

    _active_key = MODELS[current_mode].get("key", "")
    for _ in range(12):  # max tool-call iterations
        api_kwargs = {
            "model":   MODELS[current_mode]["model"],
            "messages": clean_messages(messages),
        }
        if _active_key:
            api_kwargs["api_key"] = _active_key
        if MODELS[current_mode].get("api_base"):
            api_kwargs["api_base"] = MODELS[current_mode]["api_base"]
        _model = MODELS[current_mode]["model"]
        if "groq" not in _model and "deepseek" not in _model and "ollama" not in _model:
            api_kwargs["tools"] = tools
            api_kwargs["tool_choice"] = "auto"

        try:
            response = await loop.run_in_executor(None, lambda: completion(**api_kwargs))
        except Exception as e:
            yield sse({"type":"error","text":str(e)})
            return

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        save_memory(messages)

        # ── Native tool calls (OpenAI-style) ──
        if hasattr(msg,'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                func = tc.function.name
                try:   args = json.loads(tc.function.arguments)
                except: args = {}

                yield sse({"type":"tool_start","name":func})
                out = await loop.run_in_executor(None, lambda f=func, a=args: execute_tool(f, a))
                if len(out) > 3000: out = out[:3000] + "…[truncated]"
                yield sse({"type":"tool_done","name":func,"result":out[:300]})

                messages.append({"role":"tool","tool_call_id":tc.id,"name":func,"content":out})
            save_memory(messages)
            continue

        # ── XML tool fallback (Groq/Llama style) ──
        if msg.content and "<function" in msg.content:
            match = re.search(r'<function[=/\\(]*\s*(\w+)[>\\)]*\s*(\{.*?\})\s*</function>', msg.content, re.DOTALL)
            if match:
                func = match.group(1)
                try:   args = json.loads(match.group(2))
                except: args = {"command": match.group(2)}

                yield sse({"type":"tool_start","name":func})
                out = await loop.run_in_executor(None, lambda f=func, a=args: execute_tool(f, a))
                if len(out) > 3000: out = out[:3000] + "…[truncated]"
                yield sse({"type":"tool_done","name":func,"result":out[:300]})

                messages.append({"role":"system","content":f"Tool '{func}' result:\n{out}"})
                save_memory(messages)
                continue

        # ── Final text response ──
        clean = msg.content or ""
        clean = re.sub(r'<function.*?</function>', '', clean, flags=re.DOTALL).strip()
        yield sse({"type":"response","content":clean})
        yield sse({"type":"done"})
        return

    yield sse({"type":"error","text":"Max iterations reached."})
    yield sse({"type":"done"})

# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────
@app.get("/")
async def serve_ui():
    html_path = os.path.join(CLI_DIR, "div_mobile.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/status")
def get_status():
    return {
        "mode":         current_mode,
        "model":        MODELS[current_mode]["model"],
        "messages":     max(0, len(messages)-1),
        "vault":        bool(GLOBAL_VAULT),
        "canvas":       bool(CANVAS_URL),
        "canvas_url":   CANVAS_URL,
        "assignments":  len([a for a in (_canvas_cache or []) if "error" not in a]),
        "knowt":          bool(_knowt_cache and not _knowt_cache.get("error")),
        "knowt_exams":    len((_knowt_cache or {}).get("exams", [])),
        "fiveable":       bool(_fiveable_cache and not _fiveable_cache.get("error")),
        "fiveable_exams": len((_fiveable_cache or {}).get("exams", [])),
    }

@app.get("/fiveable")
def get_fiveable():
    data = load_fiveable_cache()
    if not data:
        return {"ok": False, "error": "Fiveable not set up. Run /fiveable setup then /fiveable sync in the CLI."}
    from div_fiveable import format_for_display
    return {"ok": True, "formatted": format_for_display(data),
            "exams": data.get("exams", []), "plans": data.get("plans", []),
            "scraped_at": data.get("scraped_at", "")}

@app.get("/knowt")
def get_knowt():
    data = load_knowt_cache()
    if not data:
        return {"ok":False,"error":"Knowt not set up. Run /knowt setup then /knowt sync in the CLI."}
    from div_knowt import format_for_display
    return {"ok":True,"formatted":format_for_display(data),
            "exams":data.get("exams",[]),"plans":data.get("plans",[]),
            "scraped_at":data.get("scraped_at","")}

@app.get("/canvas")
def get_canvas():
    if not CANVAS_URL or not CANVAS_TOKEN:
        return {"ok":False,"error":"Canvas not configured","assignments":[]}
    refresh_canvas_cache()
    from div_canvas import format_for_display
    return {
        "ok":          True,
        "formatted":   format_for_display(_canvas_cache),
        "assignments": [
            {k:v for k,v in a.items() if k != "due_dt"}
            for a in (_canvas_cache or []) if "error" not in a
        ],
    }

@app.get("/history")
def get_history():
    out = []
    for m in messages[1:]:
        role    = m.get("role","")
        content = m.get("content","")
        if role in ("user","assistant") and content:
            out.append({"role":role,"content":str(content)})
    return {"messages": out}

@app.post("/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        agent_stream(req.message),
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"},
    )

@app.post("/voice")
async def voice(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    ext = ".webm" if "webm" in (file.content_type or "") else ".wav"

    async def stream():
        loop = asyncio.get_event_loop()

        # Write temp file
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            # Transcribe with Groq Whisper
            def transcribe():
                url     = "https://api.groq.com/openai/v1/audio/transcriptions"
                headers = {"Authorization": f"Bearer {WHISPER_KEY}"}
                with open(tmp_path,"rb") as f:
                    files = {"file":(file.filename or f"audio{ext}", f, file.content_type or "audio/webm"),
                             "model":(None,"whisper-large-v3")}
                    r = http_requests.post(url, headers=headers, files=files)
                return r.json().get("text","")

            text = await loop.run_in_executor(None, transcribe)

            if not text:
                yield sse({"type":"error","text":"No speech detected"})
                yield sse({"type":"done"})
                return

            yield sse({"type":"transcription","text":text})

            async for event in agent_stream(text):
                yield event
        finally:
            try: os.unlink(tmp_path)
            except: pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.post("/remind")
async def post_remind(req: RemindReq):
    import threading
    def fire():
        try:
            from div_notify import toast
            toast("divAI Reminder", req.message)
        except Exception:
            pass
    t = threading.Timer(req.minutes * 60, fire)
    t.daemon = True
    t.start()
    return {"ok": True, "minutes": req.minutes, "message": req.message}

@app.post("/command")
def run_command_endpoint(req: CommandRequest):
    global current_mode, GLOBAL_VAULT, messages
    cmd = req.command.lower()

    if cmd in ("talk","code","brain","full"):
        current_mode = cmd
        return {"ok":True,"mode":current_mode,"model":MODELS[current_mode]["model"]}

    if cmd == "clear":
        messages = [{"role":"system","content":build_system_prompt()}]
        save_memory(messages)
        return {"ok":True,"messages":0}

    if cmd == "vault":
        GLOBAL_VAULT = req.arg
        save_config()
        messages[0]["content"] = build_system_prompt()
        save_memory(messages)
        return {"ok":True,"vault":GLOBAL_VAULT}

    if cmd == "canvas_setup":
        global CANVAS_URL, CANVAS_TOKEN
        parts = req.arg.split(" ", 1)
        if len(parts) == 2:
            CANVAS_URL, CANVAS_TOKEN = parts[0].rstrip("/"), parts[1]
            save_config()
            refresh_canvas_cache()
            messages[0]["content"] = build_system_prompt()
            save_memory(messages)
            count = len([a for a in (_canvas_cache or []) if "error" not in a])
            return {"ok":True,"canvas_url":CANVAS_URL,"assignments":count}
        raise HTTPException(400,"Expected arg: '<url> <token>'")

    if cmd == "key":
        parts = req.arg.split(" ",1)
        if len(parts)==2:
            engine,key = parts[0].lower(), parts[1]
            if engine in MODELS:
                MODELS[engine]["key"] = key
                save_config()
                return {"ok":True}
    raise HTTPException(400,"Unknown command")

# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "localhost"

    print("\n\033[94m  ██████╗ ██╗██╗   ██╗ █████╗ ██╗\033[0m")
    print("\033[94m  ██╔══██╗██║██║   ██║██╔══██╗██║\033[0m")
    print("\033[94m  ██║  ██║██║██║   ██║███████║██║\033[0m")
    print("\033[94m  ██║  ██║██║╚██╗ ██╔╝██╔══██║██║\033[0m")
    print("\033[94m  ██████╔╝██║ ╚████╔╝ ██║  ██║██║\033[0m")
    print("\033[94m  ╚═════╝ ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝\033[0m")
    print(f"\n\033[90m[DISPATCH] Mobile server starting...\033[0m")
    print(f"\033[92m  Local:   http://localhost:8080\033[0m")
    print(f"\033[92m  Network: http://{local_ip}:8080  ← open this on your phone\033[0m\n")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
