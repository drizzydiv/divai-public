# divAI

A personal AI CLI with voice, multi-model routing, school integrations, and a persistent memory system backed by Obsidian. Built for Divik — but forkable if you want your own.

---

## What it does

- **Multi-model routing** — automatically picks the right model (fast chat, coding, or deep reasoning) based on your message, or you pin it manually
- **Voice I/O** — push-to-talk input via Groq Whisper + TTS output via Microsoft Neural voices
- **Canvas LMS** — live assignments, announcements, grades, and a full Canvas API proxy
- **Knowt + Fiveable** — study schedules, flashcard progress, AP exam prep
- **Obsidian vault** — reads and writes notes, logs sessions, and loads persistent context into every conversation
- **Context system** — intent-based context routing that injects relevant memory (OSINT, coding, channel, school, planning) into the system prompt automatically
- **Session summarizer** — saves AI-generated session summaries to the vault via GPT-4o-mini

---

## Requirements

- **Python 3.10+** (3.14 works)
- **pip** (comes with Python)
- An internet connection for API calls

No Node.js required. No Docker. No local GPU needed.

---

## Installation

**1. Clone the repo**

```
git clone https://github.com/your-username/divAI.git
cd divAI
```

**2. Install Python dependencies**

```
pip install litellm ddgs requests edge-tts sounddevice soundfile numpy textual python-dotenv pyperclip
```

`sounddevice` and `soundfile` are only needed for voice input (`/v`). `pyperclip` is only needed for `claude_bridge.py`. Everything else is required.

**3. Set the vault path (optional but recommended)**

Copy `.env.template` to `.env` and set your Obsidian vault path:

```
VAULT_PATH=D:\YourVaultName
```

If you skip this, the context system falls back to a local `memory/` folder (which won't exist after a fresh clone — it lives in your vault).

---

## First run

Run divAI:

```
python divCLI.py
```

On first run, a TUI onboarding wizard launches automatically. It walks you through:

1. **Picking a tier** — determines which API keys you need
2. **Entering your API keys** — pasted directly into the wizard with format validation and live testing
3. **Optional integrations** — Canvas LMS and Obsidian vault path

The wizard writes `div_config.json` when you finish. You never edit that file manually.

### Tiers

| Tier | Models | Cost | Keys needed |
|---|---|---|---|
| Free | Groq Llama 3.3 70B | $0 | Groq |
| Balanced | Groq + DeepSeek Reasoner | ~$1–5/mo | Groq, DeepSeek |
| Full Power | Groq + GitHub GPT-4o + DeepSeek + OpenAI | Pay-per-use | Groq, GitHub PAT, DeepSeek, OpenAI |

### Where to get each key

| Provider | URL | Format |
|---|---|---|
| Groq (required) | console.groq.com/keys | `gsk_...` |
| GitHub PAT (free GPT-4o) | github.com/settings/tokens → Models Read scope | `github_pat_...` |
| DeepSeek | platform.deepseek.com/api_keys | `sk-...` |
| OpenAI | platform.openai.com/api-keys | `sk-proj-...` |

The **Groq key** doubles as your voice transcription key. Start there if you want the free tier.

---

## Running divAI

```
python divCLI.py
```

Or with voice mode pre-enabled:

```
python divCLI.py --voice
```

You'll see the divAI header, current router status, and a `❯` prompt. Type or speak.

---

## Commands

### Models

| Command | What it does |
|---|---|
| `/auto` | Auto-route each message to the best model (default) |
| `/talk` | Pin to Groq Llama 3.3 70B (fast, free) |
| `/code` | Pin to GitHub GPT-4o (coding tasks) |
| `/brain` | Pin to DeepSeek Reasoner (deep reasoning, long analysis) |
| `/divfull` | Pin to OpenAI GPT-4o (requires OpenAI key) |

**Auto-routing logic:**
- Messages with code keywords (`bug`, `function`, `script`, `refactor`, etc.) → `/code`
- Messages with reasoning keywords (`explain`, `analyze`, `plan`, `compare`, etc.) or messages over 150 chars → `/brain`
- Everything else → `/talk`

### Voice

| Command | What it does |
|---|---|
| `/v` | Push-to-talk — records mic until you press Enter, transcribes via Groq Whisper |
| `/speak` | Toggle TTS output on/off |
| `/speak-voice <name>` | Set the TTS voice (e.g. `en-GB-RyanNeural`, `en-US-AndrewNeural`) |
| `/speak-rate <rate>` | Set TTS speed (e.g. `+25%`, `+50%`, `-10%`, `+0%`) — run with no arg to check current |

TTS uses Microsoft Neural voices via `edge-tts`. Rate must include a sign: `+25%` not `25%`. Practical range is `+0%` to `+50%` before it sounds weird.

### School integrations

| Command | What it does |
|---|---|
| `/canvas` | Refresh and display upcoming Canvas assignments |
| `/canvas url <url>` | Set your school's Canvas URL (e.g. `myschool.instructure.com`) |
| `/canvas setup <token>` | Connect your Canvas API token |
| `/canvas setup <url> <token>` | Set URL and token in one command |
| `/knowt` | Show Knowt study schedule and upcoming exams |
| `/knowt setup` | Open browser to log into Knowt (Playwright scraper) |
| `/knowt sync` | Re-scrape Knowt data |
| `/fiveable` | Show Fiveable AP exam progress |
| `/fiveable setup` | Open browser to log into Fiveable |
| `/fiveable sync` | Re-scrape Fiveable data |

**Getting your Canvas token:**
Canvas → Account (top-left) → Settings → scroll to Approved Integrations → New Access Token → copy it → `/canvas setup <token>`

Canvas assignments and announcements are fetched at startup and cached. The AI proactively reminds you about things due soon.

### Obsidian vault

| Command | What it does |
|---|---|
| `/vault <path>` | Link your Obsidian vault (e.g. `/vault D:\MyVault`) |

Once linked, the AI can read notes (`read_vault_note`), search across all notes (`search_vault`), and write/append to notes (`write_vault_note`). Session logs are auto-saved on `/exit` if a vault is linked.

### Context system

The context system injects relevant memory into the session based on what you're talking about.

| Command | What it does |
|---|---|
| `mode: osint` | Force-load OSINT context (investigations, methods, active cases) |
| `mode: coding` | Force-load coding context (active projects, stack, preferences) |
| `mode: channel` | Force-load channel context (div. YouTube strategy, pipeline) |
| `mode: school` | Force-load school context (schedule, AP classes, study tools) |
| `mode: planning` | Force-load planning context (college apps, long-term goals) |
| `summarize session` | Generate an AI summary of the current session and save it to `sessions/cli/YYYY-MM-DD.md` |
| `context status` | Show which context modes are currently active |

**Auto-injection:** On the first message of a new session, if keywords are detected in your message (e.g. "shaffer", "osint", "investigate" → OSINT mode), the relevant context file is automatically injected into the system prompt. You don't have to run `mode:` manually unless you want to override it.

**Context files live in your Obsidian vault:**

```
YourVault/
├── core-identity.md       ← divAI's personality and voice (always loaded)
├── user-context.md        ← who you are, your goals, constraints (always loaded)
├── contexts/
│   ├── osint.md
│   ├── coding.md
│   ├── channel.md
│   ├── school.md
│   └── planning.md
├── investigations/
│   └── brian-shaffer/
│       ├── brief.md
│       ├── leads.md
│       └── timeline.md
└── knowledge/
    ├── osint-methods.md
    └── comp-criminology.md
```

Edit any of these directly in Obsidian. Changes are picked up on the next session.

**Session summaries** are saved locally to `sessions/cli/YYYY-MM-DD.md` inside the divAI project folder (not the vault). The last 3 summaries are automatically injected into new sessions so the AI has continuity across days.

### Session management

| Command | What it does |
|---|---|
| `/clear` | Wipe conversation history |
| `/restart` | Hard restart divAI (re-runs the full startup) |
| `/exit` | Exit — auto-logs session turns to `divAI_Session_Logs.md` in the vault if linked |

### Config

| Command | What it does |
|---|---|
| `/key <engine> <key>` | Update an API key — engines: `talk`, `code`, `brain`, `full`, `whisper` |
| `/persona` | Open `div_persona.txt` in Notepad to edit the AI's personality |

Keys are saved to `div_config.json` immediately. Changes to the persona take effect in the current session.

### Reminders

```
/remind 45 submit the CS homework
```

Or tell the AI naturally: "remind me at 6pm to review the essay" — it calculates the minutes automatically and calls `set_reminder`.

Fires a terminal bell + Windows toast notification.

---

## Claude bridge (Claude.ai context loader)

If you also use Claude.ai directly and want the same divAI context loaded there:

```
python src/context/claude_bridge.py              # auto-detect context
python src/context/claude_bridge.py osint        # force OSINT context
python src/context/claude_bridge.py coding       # force coding context
python src/context/claude_bridge.py osint coding # multiple modes
```

Copies a formatted context block to your clipboard. Paste it at the start of any Claude.ai conversation.

Requires `pip install pyperclip`. On Windows this works out of the box.

---

## Tools the AI can use

The AI has direct access to these without you asking:

| Tool | What it does |
|---|---|
| `run_command` | Runs PowerShell commands on your machine |
| `read_file` / `write_file` / `edit_file` | Full file system access |
| `search_web` | DuckDuckGo web search (live results) |
| `fetch_url` | Fetches and cleans any webpage |
| `search_fiveable` | Searches Fiveable for AP study content |
| `search_vault` / `read_vault_note` / `write_vault_note` | Obsidian vault access |
| `get_canvas_overview` | Fresh Canvas snapshot (assignments + announcements) |
| `canvas_api` | Raw Canvas API proxy — any endpoint |
| `get_knowt_schedule` | Knowt study schedule |
| `get_fiveable_schedule` | Fiveable AP progress |
| `set_reminder` | Timed notification |
| `render_cell` | Opens a live popup (timer, checklist, schedule, table, progress bar) |

---

## Adding or changing models

After onboarding, use `/key` to update any key:

```
/key talk gsk_...        # update Groq key
/key code github_pat_... # update GitHub PAT
/key brain sk-...        # update DeepSeek key
/key full sk-proj-...    # update OpenAI key
/key whisper gsk_...     # update voice transcription key (defaults to Groq key)
```

To change which model a slot uses, edit `div_config.json` directly — the `model` field under any engine accepts any LiteLLM model string (e.g. `groq/llama-3.3-70b-versatile`, `openai/gpt-4o-mini`, `ollama/qwen3:8b`).

---

## Common issues

**"First run detected" on every launch**

`div_config.json` is missing, has no keys set, or was written with a UTF-8 BOM (happens if edited with PowerShell). Fix:

```
python -c "
import json
path = 'div_config.json'
with open(path, encoding='utf-8-sig') as f: data = json.load(f)
with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
"
```

Or just re-run the onboarding wizard and re-enter your keys.

**Rate limit error (tokens per minute)**

Your conversation history got too long. Run `/clear` to reset. The rolling window is set to 30 messages — if you're regularly hitting limits, note that the CLI automatically trims history before each API call.

**Tool call error: "assistant message with tool_calls must be followed by tool messages"**

A previous API error cut off mid-tool-call and left a broken entry in `div_memory.json`. Run `/clear` to fix it. The CLI also strips these automatically going forward.

**TTS rate error: "Invalid rate '25%'"**

The rate value requires an explicit sign. Use `/speak-rate +25%` not `/speak-rate 25%`. The CLI now auto-fixes this, but if your `div_config.json` has a bad value, run `/speak-rate +25%` once to overwrite it.

**Voice not working (`/v`)**

Missing audio libraries. The CLI will auto-install them on first use. If it fails:

```
pip install sounddevice soundfile numpy
```

Also requires a Groq key set for Whisper transcription (`/key whisper gsk_...`).

---

## File structure

```
divAI/
├── divCLI.py                  ← main CLI
├── div_config.json            ← your config (auto-generated, gitignored)
├── div_memory.json            ← conversation history (auto-generated, gitignored)
├── div_persona.txt            ← AI personality (edit with /persona)
├── div_onboard.py             ← first-run setup wizard
├── div_canvas.py              ← Canvas LMS integration
├── div_knowt.py               ← Knowt scraper
├── div_fiveable.py            ← Fiveable scraper
├── div_cells.py               ← popup cell renderer
├── div_notify.py              ← Windows toast notifications
├── div_listener.py            ← ambient wake word listener (--voice flag)
├── .env                       ← VAULT_PATH (gitignored)
├── .env.template              ← copy this to .env
├── src/
│   └── context/
│       ├── loader.py          ← intent classifier + context builder
│       ├── summarizer.py      ← session summarizer (GPT-4o-mini)
│       └── claude_bridge.py   ← context exporter for Claude.ai
└── sessions/
    └── cli/                   ← auto-saved session summaries (gitignored)
        └── YYYY-MM-DD.md
```

Context files and investigation notes live in your Obsidian vault, not here.
