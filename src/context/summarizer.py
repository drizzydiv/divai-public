import os
import json
import sys
from pathlib import Path
from datetime import date

_CLI_DIR = Path(__file__).parent.parent.parent

_SUMMARY_PROMPT = """\
Summarize this divAI session. Extract:

1. KEY DECISIONS — any choices made about projects, direction, approach
2. NEW INFORMATION — facts, discoveries, or context that should persist
3. ACTION ITEMS — specific things Divik said he would do
4. ACTIVE CONTEXT — what was being worked on, relevant for next session

Keep it under 400 words. Clean markdown. No preamble.

Session:
{conversation}
"""


def _get_openai_key() -> str:
    config_path = _CLI_DIR / "div_config.json"
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        key = cfg.get("models", {}).get("full", {}).get("key", "")
        if key:
            return key
    except Exception:
        pass
    return os.getenv("OPENAI_API_KEY", "")


def summarize_session(conversation: list[dict]) -> str:
    from litellm import completion

    key = _get_openai_key()
    if not key:
        raise RuntimeError("OpenAI key not found. Set it with /key full sk-... in divAI.")

    turns = [m for m in conversation if m.get("role") in ("user", "assistant")]
    formatted = "\n".join(
        f"{m['role'].upper()}: {str(m.get('content', ''))[:500]}"
        for m in turns[-40:]
    )

    response = completion(
        model="openai/gpt-4o-mini",
        api_key=key,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": _SUMMARY_PROMPT.format(conversation=formatted),
        }],
    )
    return response.choices[0].message.content


def save_session_summary(conversation: list[dict], session_type: str = "cli") -> str:
    output_dir = _CLI_DIR / "sessions" / session_type
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\033[90m  ⎿ Summarizing session with gpt-4o-mini...\033[0m")
    try:
        summary = summarize_session(conversation)
    except Exception as e:
        print(f"\033[91m  ⎿ Summary failed: {e}\033[0m")
        return ""

    filename = output_dir / f"{date.today().isoformat()}.md"
    if filename.exists():
        existing = filename.read_text(encoding="utf-8")
        filename.write_text(existing + "\n\n---\n\n" + summary, encoding="utf-8")
    else:
        filename.write_text(summary, encoding="utf-8")

    print(f"\033[92m  ⎿ Session saved → {filename.name}\033[0m")
    return summary
