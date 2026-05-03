"""Fiveable AP study scraper for divAI — persistent browser session, network interception."""

import json, os, re, asyncio
from datetime import datetime, timezone
from pathlib import Path

CLI_DIR     = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(CLI_DIR, ".fiveable_session")
CACHE_FILE  = os.path.join(CLI_DIR, "div_fiveable_cache.json")

# ──────────────────────────────────────────────
# DEPENDENCY BOOTSTRAP
# ──────────────────────────────────────────────
def _ensure_playwright():
    try:
        import playwright  # noqa
    except ImportError:
        import subprocess, sys
        print("  [FIVEABLE] Installing Playwright...")
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright", "-q"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
                       capture_output=True)

# ──────────────────────────────────────────────
# SESSION SETUP  (headed, manual login)
# ──────────────────────────────────────────────
async def _setup_async():
    from playwright.async_api import async_playwright
    Path(SESSION_DIR).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            SESSION_DIR,
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://fiveable.me/login")
        print("\n  [FIVEABLE SETUP] Browser opened. Log into Fiveable, then press ENTER here.")
        input("  ❯ Press ENTER when done > ")
        await ctx.close()
    print("  [FIVEABLE] Session saved to .fiveable_session/")

def setup_session():
    _ensure_playwright()
    asyncio.run(_setup_async())

def is_configured():
    return Path(SESSION_DIR).exists() and any(Path(SESSION_DIR).iterdir())

# ──────────────────────────────────────────────
# SCRAPER
# ──────────────────────────────────────────────
async def _scrape_async():
    from playwright.async_api import async_playwright

    if not is_configured():
        return {"error": "Not set up. Run /fiveable setup first.", "plans": [], "exams": []}

    api_payloads = []

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            SESSION_DIR,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def capture_response(response):
            if response.status == 200 and "fiveable.me" in response.url:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        body = await response.json()
                        api_payloads.append({"url": response.url, "data": body})
                    except Exception:
                        pass

        page.on("response", capture_response)

        try:
            await page.goto("https://fiveable.me", wait_until="networkidle", timeout=35000)
            await page.wait_for_timeout(3000)

            if "/login" in page.url or "/signin" in page.url:
                await ctx.close()
                return {"error": "Session expired. Run /fiveable setup again.", "plans": [], "exams": []}

            for extra in ["https://fiveable.me/dashboard", "https://fiveable.me/classes"]:
                try:
                    await page.goto(extra, wait_until="networkidle", timeout=15000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass

            try:
                body_text = await page.inner_text("body")
            except Exception:
                body_text = ""

        finally:
            await ctx.close()

    plans, exams = _parse_payloads(api_payloads, body_text)
    result = {
        "plans":      plans,
        "exams":      exams,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "error":      None,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result

def scrape():
    _ensure_playwright()
    return asyncio.run(_scrape_async())

# ──────────────────────────────────────────────
# PARSER
# ──────────────────────────────────────────────
def _parse_payloads(payloads: list, body_text: str) -> tuple:
    plans = []
    exams = []
    seen  = set()

    for p in payloads:
        _dig_json(p.get("data", {}), p.get("url", ""), plans, exams, seen)

    if body_text:
        _parse_body_text(body_text, exams, seen)

    exams.sort(key=lambda x: x.get("exam_date", "9999"))
    plans.sort(key=lambda x: x.get("name", ""))
    return plans, exams

def _dig_json(obj, url, plans, exams, seen, depth=0):
    if depth > 6 or obj is None:
        return
    if isinstance(obj, list):
        for item in obj:
            _dig_json(item, url, plans, exams, seen, depth+1)
        return
    if not isinstance(obj, dict):
        return

    keys = {k.lower() for k in obj}

    if any(k in keys for k in ("title", "name", "subject", "course_name", "coursename")):
        name = (obj.get("subject") or obj.get("title") or obj.get("name") or
                obj.get("course_name") or obj.get("courseName") or "")
        if name and name not in seen:
            seen.add(name)
            exam_date = _extract_date_field(obj, ("ap_exam_date","apExamDate","exam_date","examDate",
                                                   "exam","due_date","dueDate","test_date","date"))
            progress  = _extract_float_field(obj, ("progress","completion","percent_complete",
                                                    "percentComplete","mastery","score","grade"))
            total     = _extract_int_field(obj, ("total","total_lessons","totalLessons","total_cards",
                                                  "totalCards","count","lesson_count"))
            cards_due = _extract_int_field(obj, ("cards_due","cardsDue","due","practice_due",
                                                  "practiceDue","reviews_due","reviewsDue"))

            if exam_date:
                exams.append({"name": name, "exam_date": exam_date,
                              "progress": progress, "total": total, "cards_due": cards_due})
            elif progress is not None or total:
                plans.append({"name": name, "progress": progress, "total": total, "cards_due": cards_due})

    for v in obj.values():
        if isinstance(v, (dict, list)):
            _dig_json(v, url, plans, exams, seen, depth+1)

def _parse_body_text(text: str, exams: list, seen: set):
    patterns = [
        r"(AP\s+[\w\s]{2,30}?)\s*[·\-–—]\s*(\d+)\s*days?\s*(?:left|until|away)",
        r"(AP\s+[\w\s]{2,30}?)\s+exam\s+in\s+(\d+)\s*days?",
        r"(AP\s+[\w\s]{2,30}?)\s+exam\s+(?:on\s+)?([A-Za-z]{3,9}\s+\d{1,2})",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            name = m.group(1).strip()
            if name in seen or len(name) < 3:
                continue
            seen.add(name)
            exam_date = _days_to_iso(m.group(2)) or m.group(2)
            exams.append({"name": name, "exam_date": exam_date,
                          "progress": None, "total": None, "cards_due": None, "source": "text"})

# ── Field extraction helpers ──
def _extract_date_field(obj, keys):
    for k in keys:
        v = obj.get(k) or obj.get(_camel(k))
        if v and isinstance(v, str) and len(v) >= 8:
            return v[:10]
    return None

def _extract_int_field(obj, keys):
    for k in keys:
        v = obj.get(k) or obj.get(_camel(k))
        if v is not None:
            try: return int(v)
            except: pass
    return None

def _extract_float_field(obj, keys):
    for k in keys:
        v = obj.get(k) or obj.get(_camel(k))
        if v is not None:
            try: return round(float(v)*100) if float(v) <= 1 else round(float(v))
            except: pass
    return None

def _camel(s):
    parts = s.split("_")
    return parts[0] + "".join(w.title() for w in parts[1:])

def _days_to_iso(s):
    try:
        from datetime import timedelta
        d = datetime.now(timezone.utc) + timedelta(days=int(s))
        return d.strftime("%Y-%m-%d")
    except:
        return None

# ──────────────────────────────────────────────
# CACHE LOADER
# ──────────────────────────────────────────────
def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            return json.load(open(CACHE_FILE, encoding="utf-8"))
        except:
            pass
    return None

# ──────────────────────────────────────────────
# FORMATTERS
# ──────────────────────────────────────────────
def format_for_prompt(data: dict) -> str:
    if not data or data.get("error"):
        return data.get("error", "Fiveable data unavailable.") if data else "Fiveable not loaded."

    now   = datetime.now(timezone.utc)
    lines = []

    for ex in data.get("exams", []):
        name  = ex.get("name", "Unknown")
        edate = ex.get("exam_date", "")
        prog  = ex.get("progress")
        urgency = ""
        if edate:
            try:
                dt   = datetime.fromisoformat(edate.replace("Z","+00:00")) if "T" in edate else datetime.fromisoformat(edate + "T00:00:00+00:00")
                days = (dt - now).days
                if   days < 0:  continue
                elif days == 0: urgency = "⚠️ EXAM TODAY"
                elif days == 1: urgency = "🔴 EXAM TOMORROW"
                elif days <= 3: urgency = f"🟠 exam in {days}d"
                elif days <= 7: urgency = f"🟡 exam in {days}d"
                else:           urgency = f"📅 exam in {days}d"
            except:
                urgency = f"📅 exam {edate}"
        parts = [urgency, name]
        if prog: parts.append(f"{prog}% complete")
        lines.append("  " + " | ".join(p for p in parts if p))

    for pl in data.get("plans", []):
        name = pl.get("name", "Unknown")
        prog = pl.get("progress")
        parts = [f"📗 {name}"]
        if prog: parts.append(f"{prog}% complete")
        lines.append("  " + " | ".join(parts))

    return "\n".join(lines) if lines else "No active Fiveable study plans found."


def format_for_display(data: dict) -> str:
    if not data or data.get("error"):
        return data.get("error", "No Fiveable data.") if data else "No Fiveable data."

    now   = datetime.now(timezone.utc)
    lines = []

    if data.get("exams"):
        lines.append("── AP Exams (Fiveable) ──")
        for ex in data["exams"]:
            name  = ex.get("name", "Unknown")
            edate = ex.get("exam_date", "")
            prog  = ex.get("progress")
            try:
                dt   = datetime.fromisoformat(edate.replace("Z","+00:00")) if "T" in edate else datetime.fromisoformat(edate+"T00:00:00+00:00")
                days = (dt - now).days
                badge    = "TODAY ⚠️" if days == 0 else ("TOMORROW 🔴" if days == 1 else (f"in {days} days" if days > 0 else "PAST"))
                date_str = dt.strftime("%a %b %#d")
            except:
                badge = ""; date_str = edate
            line = f"  • {name} — {date_str} ({badge})"
            if prog: line += f"  ·  {prog}% complete"
            lines.append(line)

    if data.get("plans"):
        lines.append("\n── Study Progress ──")
        for pl in data["plans"]:
            name = pl.get("name", "Unknown")
            prog = pl.get("progress")
            line = f"  • {name}"
            if prog: line += f" — {prog}% complete"
            lines.append(line)

    scraped = data.get("scraped_at", "")
    if scraped:
        try:
            dt = datetime.fromisoformat(scraped)
            lines.append(f"\n  (last synced {dt.strftime('%#I:%M %p')})")
        except:
            pass

    return "\n".join(lines).strip() if lines else "No active Fiveable data found."
