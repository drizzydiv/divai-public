import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass  # .env values won't load but VAULT_PATH can still be set as a real env var

_CLI_DIR = Path(__file__).parent.parent.parent
VAULT = Path(os.getenv("VAULT_PATH", str(_CLI_DIR / "memory")))

ALWAYS_LOAD = [
    "core-identity.md",
    "user-context.md",
]

CONTEXT_MAP = {
    "osint":    "contexts/osint.md",
    "coding":   "contexts/coding.md",
    "channel":  "contexts/channel.md",
    "school":   "contexts/school.md",
    "planning": "contexts/planning.md",
}

_OSINT_KW    = ["investigate", "osint", "case", "missing", "shaffer",
                "brief", "source", "archive", "wayback", "lead", "suspect",
                "witness", "forensic", "evidence", "crime", "cold case"]
_CODING_KW   = ["build", "code", "bug", "function", "api", "repo",
                "github", "deploy", "error", "debug", "script", "class",
                "import", "def ", "const ", "typescript", "python",
                "javascript", "refactor", "implement", "fix"]
_CHANNEL_KW  = ["video", "youtube", "div.", "channel", "title",
                "thumbnail", "film", "edit", "script", "upload", "fern",
                "cinematography", "narration", "b-roll"]
_SCHOOL_KW   = ["assignment", "homework", "due", "class", "exam",
                "grade", "school", "test", "project", "deadline",
                "canvas", "knowt", "fiveable", "ap ", "quiz", "study"]
_PLANNING_KW = ["college", "georgia tech", "application", "goal",
                "future", "career", "plan", "tedx", "long term",
                "portfolio", "uga", "junior", "senior", "clubs"]


def classify_intent(prompt: str) -> list[str]:
    p = prompt.lower()
    contexts = []
    if any(k in p for k in _OSINT_KW):    contexts.append("osint")
    if any(k in p for k in _CODING_KW):   contexts.append("coding")
    if any(k in p for k in _CHANNEL_KW):  contexts.append("channel")
    if any(k in p for k in _SCHOOL_KW):   contexts.append("school")
    if any(k in p for k in _PLANNING_KW): contexts.append("planning")
    return contexts


def _load_file(relative_path: str) -> str:
    full = VAULT / relative_path
    if full.exists():
        try:
            return full.read_text(encoding="utf-8")
        except Exception:
            return ""
    return ""


def build_context(prompt: str, explicit_mode: str = None) -> str:
    blocks = []

    for f in ALWAYS_LOAD:
        content = _load_file(f)
        if content:
            blocks.append(content)

    # last 3 CLI session summaries
    session_dir = _CLI_DIR / "sessions" / "cli"
    if session_dir.exists():
        sessions = sorted(session_dir.glob("*.md"), reverse=True)[:3]
        for s in sessions:
            try:
                blocks.append(f"[Recent session — {s.stem}]\n{s.read_text(encoding='utf-8')}")
            except Exception:
                pass

    modes = [explicit_mode] if explicit_mode else classify_intent(prompt)
    for mode in modes:
        if mode in CONTEXT_MAP:
            content = _load_file(CONTEXT_MAP[mode])
            if content:
                blocks.append(f"[Context: {mode}]\n{content}")

    return "\n\n---\n\n".join(blocks)
