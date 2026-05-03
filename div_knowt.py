"""Knowt study schedule scraper for divAI — persistent browser session, network interception."""

import json, os, re, asyncio
from datetime import datetime, timezone
from pathlib import Path

CLI_DIR     = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(CLI_DIR, ".knowt_session")
CACHE_FILE  = os.path.join(CLI_DIR, "div_knowt_cache.json")

# ──────────────────────────────────────────────
# DEPENDENCY BOOTSTRAP
# ──────────────────────────────────────────────
def _ensure_playwright():
    try:
        import playwright  # noqa
    except ImportError:
        import subprocess, sys
        print("  [KNOWT] Installing Playwright...")
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
        await page.goto("https://knowt.com/login")
        print("\n  [KNOWT SETUP] Browser opened. Log into Knowt, then press ENTER here.")
        input("  ❯ Press ENTER when done > ")
        await ctx.close()
    print("  [KNOWT] Session saved to .knowt_session/")

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
        return {"error": "Not set up. Run /knowt setup first.", "plans": [], "exams": []}

    api_payloads = []

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            SESSION_DIR,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Intercept every JSON API response Knowt makes during page load
        async def capture_response(response):
            if response.status == 200 and "knowt.com" in response.url:
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    try:
                        body = await response.json()
                        api_payloads.append({"url": response.url, "data": body})
                    except Exception:
                        pass

        page.on("response", capture_response)

        try:
            await page.goto("https://knowt.com", wait_until="networkidle", timeout=35000)
            await page.wait_for_timeout(3000)

            # Check still logged in
            if "/login" in page.url:
                await ctx.close()
                return {"error": "Session expired. Run /knowt setup again.", "plans": [], "exams": []}

            # Also hit the study plan / learn page if it exists
            for extra in ["https://knowt.com/home", "https://knowt.com/learn"]:
                try:
                    await page.goto(extra, wait_until="networkidle", timeout=15000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    pass

            # Grab all visible body text as a fallback source
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
# PARSER — mines API payloads + text for study data
# ──────────────────────────────────────────────
def _parse_payloads(payloads: list, body_text: str) -> tuple:
    """Return (plans, exams) lists parsed from intercepted API data + page text."""
    plans = []
    exams = []
    seen  = set()

    # ── 1. Mine JSON payloads from intercepted API calls ──
    for p in payloads:
        url  = p.get("url", "")
        data = p.get("data", {})
        _dig_json(data, url, plans, exams, seen)

    # ── 2. Text-based fallback — parse visible page text ──
    if body_text:
        _parse_body_text(body_text, exams, seen)

    # Deduplicate and sort
    exams.sort(key=lambda x: x.get("exam_date", "9999"))
    plans.sort(key=lambda x: x.get("name", ""))
    return plans, exams

def _dig_json(obj, url, plans, exams, seen, depth=0):
    """Recursively dig through a JSON structure looking for study/exam data."""
    if depth > 6 or obj is None:
        return
    if isinstance(obj, list):
        for item in obj:
            _dig_json(item, url, plans, exams, seen, depth+1)
        return
    if not isinstance(obj, dict):
        return

    keys = {k.lower() for k in obj}

    # Looks like a flashcard set or study plan
    if any(k in keys for k in ("title", "name", "set_name", "setname")):
        name = obj.get("title") or obj.get("name") or obj.get("set_name") or obj.get("setName", "")
        if not name or name in seen:
            pass
        else:
            seen.add(name)
            exam_date  = _extract_date_field(obj, ("exam_date","examDate","exam","due_date","dueDate","test_date"))
            cards_due  = _extract_int_field(obj,  ("cards_due","cardsDue","due","cards_today","cardsToday","due_count"))
            total      = _extract_int_field(obj,  ("total","total_cards","totalCards","count","card_count"))
            progress   = _extract_float_field(obj,("progress","mastered","mastery","percent_mastered"))

            if exam_date:
                entry = {"name": name, "exam_date": exam_date,
                         "cards_due": cards_due, "total": total, "progress": progress}
                exams.append(entry)
            elif cards_due or total:
                plans.append({"name": name, "cards_due": cards_due, "total": total, "progress": progress})

    # Recurse into child values
    for v in obj.values():
        if isinstance(v, (dict, list)):
            _dig_json(v, url, plans, exams, seen, depth+1)

def _parse_body_text(text: str, exams: list, seen: set):
    """Parse visible page text for exam countdown patterns."""
    # e.g. "Calculus Exam · 5 days left", "Biology Test in 3 days", "AP Chemistry — Exam Apr 28"
    patterns = [
        r"([A-Za-z][\w\s]{2,40}?)\s*[·\-–—]\s*(\d+)\s*days?\s*(?:left|until|away)",
        r"([A-Za-z][\w\s]{2,40}?)\s+(?:exam|test|quiz|final)\s+in\s+(\d+)\s*days?",
        r"([A-Za-z][\w\s]{2,40}?)\s+(?:exam|test|quiz|final)\s+(?:on\s+)?([A-Za-z]{3,9}\s+\d{1,2})",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            name = m.group(1).strip()
            if name in seen or len(name) < 3:
                continue
            seen.add(name)
            raw_date = m.group(2)
            # Try to parse as days-away number or date string
            exam_date = _days_to_iso(raw_date) or raw_date
            exams.append({"name": name, "exam_date": exam_date,
                          "cards_due": None, "total": None, "progress": None,
                          "source": "text"})

# ── Field extraction helpers ──
def _extract_date_field(obj, keys):
    for k in keys:
        v = obj.get(k) or obj.get(_camel(k))
        if v and isinstance(v, str) and len(v) >= 8:
            return v[:10]  # ISO date prefix
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
            try: return round(float(v)*100) if float(v)<=1 else round(float(v))
            except: pass
    return None

def _camel(s):
    parts = s.split("_")
    return parts[0] + "".join(w.title() for w in parts[1:])

def _days_to_iso(s):
    try:
        days = int(s)
        from datetime import timedelta
        d = datetime.now(timezone.utc) + timedelta(days=days)
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
        return data.get("error", "Knowt data unavailable.") if data else "Knowt not loaded."

    now   = datetime.now(timezone.utc)
    lines = []

    # Exams with dates
    for ex in data.get("exams", []):
        name  = ex.get("name", "Unknown")
        edate = ex.get("exam_date", "")
        cards = ex.get("cards_due")
        prog  = ex.get("progress")

        urgency = ""
        if edate:
            try:
                dt    = datetime.fromisoformat(edate.replace("Z","+00:00")) if "T" in edate else datetime.fromisoformat(edate + "T00:00:00+00:00")
                days  = (dt - now).days
                if   days < 0:  continue
                elif days == 0: urgency = "⚠️ EXAM TODAY"
                elif days == 1: urgency = "🔴 EXAM TOMORROW"
                elif days <= 3: urgency = f"🟠 exam in {days}d"
                elif days <= 7: urgency = f"🟡 exam in {days}d"
                else:           urgency = f"📅 exam in {days}d"
            except:
                urgency = f"📅 exam {edate}"

        parts = [urgency, name]
        if cards:   parts.append(f"{cards} cards due today")
        if prog:    parts.append(f"{prog}% mastered")
        lines.append("  " + " | ".join(p for p in parts if p))

    # Plans without exam dates
    for pl in data.get("plans", []):
        name  = pl.get("name", "Unknown")
        cards = pl.get("cards_due")
        prog  = pl.get("progress")
        parts = [f"📖 {name}"]
        if cards: parts.append(f"{cards} cards due")
        if prog:  parts.append(f"{prog}% mastered")
        lines.append("  " + " | ".join(parts))

    return "\n".join(lines) if lines else "No active Knowt study plans found."

def format_for_display(data: dict) -> str:
    if not data or data.get("error"):
        return data.get("error", "No Knowt data.") if data else "No Knowt data."

    now   = datetime.now(timezone.utc)
    lines = []

    if data.get("exams"):
        lines.append("── Upcoming Exams ──")
        for ex in data["exams"]:
            name  = ex.get("name","Unknown")
            edate = ex.get("exam_date","")
            cards = ex.get("cards_due")
            prog  = ex.get("progress")
            try:
                dt   = datetime.fromisoformat(edate.replace("Z","+00:00")) if "T" in edate else datetime.fromisoformat(edate+"T00:00:00+00:00")
                days = (dt - now).days
                if   days < 0:  badge = "PAST"
                elif days == 0: badge = "TODAY ⚠️"
                elif days == 1: badge = "TOMORROW 🔴"
                else:           badge = f"in {days} days"
                date_str = dt.strftime("%a %b %#d")
            except:
                badge = ""; date_str = edate
            line = f"  • {name} — {date_str} ({badge})"
            if cards: line += f"\n    {cards} cards due today"
            if prog:  line += f"  ·  {prog}% mastered"
            lines.append(line)

    if data.get("plans"):
        lines.append("\n── Active Study Plans ──")
        for pl in data["plans"]:
            name  = pl.get("name","Unknown")
            cards = pl.get("cards_due")
            prog  = pl.get("progress")
            line  = f"  • {name}"
            if cards: line += f" — {cards} cards due today"
            if prog:  line += f"  ·  {prog}% mastered"
            lines.append(line)

    scraped = data.get("scraped_at","")
    if scraped:
        try:
            dt = datetime.fromisoformat(scraped)
            lines.append(f"\n  (last synced {dt.strftime('%#I:%M %p')})")
        except: pass

    return "\n".join(lines).strip() if lines else "No active study plans found in Knowt."
