"""
claude_bridge.py — generate a context block for Claude.ai sessions.

Usage:
    python claude_bridge.py              # auto-detect context
    python claude_bridge.py osint        # force osint context
    python claude_bridge.py channel      # force channel context
    python claude_bridge.py coding school  # multiple modes

Copies result to clipboard. Paste at the start of a Claude.ai session.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.context.loader import build_context, classify_intent, CONTEXT_MAP

_VALID_MODES = set(CONTEXT_MAP.keys())


def generate_claude_context(modes: list[str] = None) -> str:
    if modes:
        invalid = [m for m in modes if m not in _VALID_MODES]
        if invalid:
            print(f"\033[91mUnknown mode(s): {', '.join(invalid)}")
            print(f"Valid: {', '.join(sorted(_VALID_MODES))}\033[0m")
            sys.exit(1)
        # build context by using a prompt that triggers each mode
        prompt = " ".join(modes)
        context = "\n\n---\n\n".join(
            [build_context("", explicit_mode=m) for m in modes]
        )
    else:
        prompt = "general session"
        context = build_context(prompt)

    block = f"""[divAI CONTEXT LOAD — paste at start of Claude.ai session]

{context}

[END CONTEXT — begin session normally]
"""

    try:
        import pyperclip
        pyperclip.copy(block)
        mode_label = ", ".join(modes) if modes else "auto"
        print(f"\033[92m  ⎿ Context ({mode_label}) copied to clipboard — paste into Claude.ai\033[0m")
    except ImportError:
        print("\033[93m  ⎿ pyperclip not installed (pip install pyperclip) — printing context instead:\033[0m\n")
        print(block)

    return block


if __name__ == "__main__":
    requested = sys.argv[1:] if len(sys.argv) > 1 else None
    generate_claude_context(requested)
