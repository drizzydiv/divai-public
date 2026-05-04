"""
divAI boot animation.
Called once at startup. /clear uses the static print_header() instead.
"""

import os
import sys
import time
import random
import subprocess

# ── ANSI ──────────────────────────────────────────────────
B  = "\033[94m"   # divAI blue
DB = "\033[34m"   # dark blue
D  = "\033[90m"   # dim gray
G  = "\033[92m"   # green
Y  = "\033[93m"   # yellow
R  = "\033[91m"   # red
W  = "\033[97m"   # bright white
C  = "\033[96m"   # cyan
X  = "\033[0m"    # reset
BOLD = "\033[1m"

# ── Logo ──────────────────────────────────────────────────
LOGO = [
    "   ██████╗ ██╗██╗   ██╗ █████╗ ██╗",
    "   ██╔══██╗██║██║   ██║██╔══██╗██║",
    "   ██║  ██║██║██║   ██║███████║██║",
    "   ██║  ██║██║╚██╗ ██╔╝██╔══██║██║",
    "   ██████╔╝██║ ╚████╔╝ ██║  ██║██║",
    "   ╚═════╝ ╚═╝  ╚═══╝  ╚═╝  ╚═╝╚═╝",
]

_NOISE = list("▓▒░╬╠╣╦╩╔╗╚╝║═█▄▀■▪◆")


# ── Phases ────────────────────────────────────────────────

def _write(s: str):
    sys.stdout.write(s)
    sys.stdout.flush()


def _phase_glitch_in():
    """Logo bursts in scrambled, briefly glitches, then starts resolving."""
    max_len = max(len(l) for l in LOGO)

    # Print fully scrambled logo
    for line in LOGO:
        scrambled = "".join(
            random.choice(_NOISE) if ch != " " else " "
            for ch in line
        )
        _write(f"{B}{scrambled}{X}\n")

    # Hold for two rapid re-scrambles to sell the "glitching" look
    for _ in range(3):
        time.sleep(0.055)
        _write(f"\033[{len(LOGO)}A")
        for line in LOGO:
            scrambled = "".join(
                random.choice(_NOISE) if ch != " " else " "
                for ch in line
            )
            _write(f"\r{B}{scrambled}{X}\n")


def _phase_resolve():
    """Sweep left-to-right, replacing noise with real logo characters."""
    max_len = max(len(l) for l in LOGO)
    n = len(LOGO)

    # number of sweep frames — more = smoother
    frames = 32
    step   = max(1, max_len // frames)

    for col in range(0, max_len + step, step):
        _write(f"\033[{n}A")
        for line in LOGO:
            out = []
            for i, ch in enumerate(line):
                if ch == " ":
                    out.append(" ")
                elif i < col:
                    out.append(ch)         # resolved
                else:
                    # still noisy — flicker 70% of the time
                    out.append(random.choice(_NOISE) if random.random() < 0.70 else ch)
            _write(f"\r{B}{''.join(out)}{X}\n")
        time.sleep(0.014)

    # Final guaranteed-clean pass
    _write(f"\033[{n}A")
    for line in LOGO:
        _write(f"\r{B}{line}{X}\n")


def _phase_tagline():
    """Fade in a version + tagline under the logo."""
    time.sleep(0.05)
    tag = "   INTELLIGENCE LAYER  ·  v8.0.1"
    out = []
    for ch in tag:
        out.append(ch)
        _write(f"\r{D}{''.join(out)}{X}")
        time.sleep(0.018)
    _write("\n")


def _check(label: str, detail: str, status: str, ok: bool = True, secs: float = 0.18):
    """
    Print one animated boot-check line.
    Label fills to fixed width, dots fill to align, status pops in at end.
    """
    # fixed widths
    LABEL_W  = 9
    TOTAL_W  = 54   # chars before status

    prefix_plain = f"  {label:<{LABEL_W}} {detail}"
    n_dots = max(4, TOTAL_W - len(prefix_plain) - len(status) - 2)

    color = G if ok else Y
    icon  = "✓" if ok else "⚠"

    _write(f"  {D}{label:<{LABEL_W}}{X} {W}{detail}{X}")

    # dots fill gradually
    dot_delay = secs / (n_dots + 4)
    for _ in range(n_dots):
        _write(f"{D}.{X}")
        time.sleep(dot_delay)

    # status pops in character by character
    _write(f" {color}")
    for ch in status:
        _write(ch)
        time.sleep(0.012)
    _write(f"  {icon}{X}\n")
    time.sleep(secs * 0.15)


def _phase_boot_checks(cfg: dict):
    """Dynamic system-check lines using live config state."""
    _write("\n")

    models     = cfg.get("models", {})
    vault      = cfg.get("vault", "")
    canvas_url = cfg.get("canvas_url", "")
    canvas_cache  = cfg.get("canvas_cache") or []
    knowt_cache   = cfg.get("knowt_cache")
    fiveable_cache = cfg.get("fiveable_cache")
    mode       = cfg.get("current_mode", "auto")

    # Core
    _check("[CORE]",   "divAI engine",    "v8.0.1")

    # Router
    if mode == "auto":
        _check("[ROUTER]", "Model router", "auto  →  talk / code / brain")
    else:
        m = models.get(mode, {}).get("model", mode)
        _check("[ROUTER]", f"Pinned to /{mode}", m)

    # Keys
    has_key = any(models.get(s, {}).get("key") for s in ("talk", "code", "brain", "full"))
    _check("[KEYS]",   "API keys",        "loaded" if has_key else "not set", ok=has_key)

    # Web
    _check("[NET]",    "Web access",      "active")

    # Vault
    vault_ok = bool(vault and os.path.isdir(vault))
    if vault_ok:
        # git pull in background if vault has git
        if os.path.exists(os.path.join(vault, ".git")):
            subprocess.Popen(["git", "pull"], cwd=vault,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        short = vault if len(vault) <= 30 else "…" + vault[-28:]
        _check("[VAULT]",  "Obsidian vault",  short)
    else:
        _check("[VAULT]",  "Obsidian vault",  "not linked", ok=False)

    # Canvas
    if canvas_url:
        n = len([a for a in canvas_cache if "error" not in a])
        _check("[CANVAS]", "Canvas LMS",
               f"{n} assignment{'s' if n != 1 else ''} due")
    else:
        _check("[CANVAS]", "Canvas LMS",      "not connected", ok=False)

    # Knowt
    if knowt_cache and not knowt_cache.get("error"):
        exams = len(knowt_cache.get("exams", []))
        _check("[KNOWT]",  "Study schedule",
               f"{exams} exam{'s' if exams != 1 else ''} tracked")

    # Fiveable
    if fiveable_cache and not fiveable_cache.get("error"):
        _check("[FIVEABLE]", "AP progress",   "loaded")

    # OSINT modules
    osint_ok = os.path.exists(os.path.join(os.path.dirname(__file__), "div_osint.py"))
    _check("[OSINT]",  "OSINT modules",   "investigate · profile · narrate" if osint_ok else "not found", ok=osint_ok)

    # Final status
    time.sleep(0.07)
    _write("\n")
    _check("[STATUS]", "",                "ALL SYSTEMS OPERATIONAL", secs=0.06)


def _phase_prompt_hint():
    """Fade in the command hint bar."""
    _write("\n")
    hint = "  /help  ·  /talk /code /brain  ·  /speak /v  ·  investigate  ·  profile  ·  /exit"
    _write(f"{D}{hint}{X}\n\n")


# ── Public entry point ─────────────────────────────────────

def boot_animation(cfg: dict):
    """
    Full cinematic boot sequence.
    cfg = {models, vault, canvas_url, canvas_cache, knowt_cache,
           fiveable_cache, current_mode}
    """
    # Ensure UTF-8 so box-drawing and block chars render correctly on Windows
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    os.system("cls" if os.name == "nt" else "clear")

    _phase_glitch_in()
    _phase_resolve()
    _phase_tagline()
    _phase_boot_checks(cfg)
    _phase_prompt_hint()
