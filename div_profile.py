"""
divAI Social Profile OSINT Module.
Effective on non-famous people via username correlation, people aggregators, and hint-narrowed dorking.
Only uses publicly available data — no login scraping, no PII databases.

Usage:
  profile John Smith
  profile John Smith --location "Seattle, WA"
  profile John Smith --username johnsmith92
  profile John Smith --company "Amazon" --location "Seattle"
  profile John Smith --email john@gmail.com
"""

import re
import json
import time
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


# ──────────────────────────────────────────────────────────
# HINT PARSING
# ──────────────────────────────────────────────────────────

def parse_profile_args(args_str: str) -> tuple[str, dict]:
    """
    Parse 'John Smith --location "Seattle, WA" --username johnsmith92 --school "FCHS"'
    Returns (name, hints_dict).
    """
    hints = {}
    for flag in ("location", "username", "company", "school", "email"):
        m = re.search(rf'--{flag}\s+"([^"]+)"', args_str)
        if not m:
            m = re.search(rf'--{flag}\s+(\S+)', args_str)
        if m:
            hints[flag] = m.group(1)
            args_str = args_str.replace(m.group(0), "")
    name = re.sub(r'--\w+\s*(?:"[^"]*"|\S+)', '', args_str).replace("--refresh", "").strip()
    return name, hints


# ──────────────────────────────────────────────────────────
# SCRAPING UTILITIES
# ──────────────────────────────────────────────────────────

def _ddg(query: str, max_results: int = 8) -> list:
    try:
        from ddgs import DDGS
        return DDGS().text(query, max_results=max_results) or []
    except Exception:
        return []


def _snippets(results: list, limit: int = 4000) -> str:
    parts = []
    for r in results:
        parts.append(f"[{r.get('title','')}]\n{r.get('href','')}\n{r.get('body','')}")
    return "\n\n".join(parts)[:limit]


def _fetch(url: str, limit: int = 4000) -> str:
    try:
        import requests
        r = requests.get(url, headers=_HEADERS, timeout=12)
        r.raise_for_status()
        text = re.sub(r'<script[^>]*>.*?</script>', '', r.text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:limit]
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────
# PEOPLE AGGREGATORS (most effective for non-famous people)
# ──────────────────────────────────────────────────────────

def scrape_fastpeoplesearch(name: str, location: str = "") -> dict:
    """
    FastPeopleSearch pulls from voter registration, phone databases, public records.
    Works on virtually any US adult. No login required.
    """
    slug = name.lower().replace(" ", "-")
    loc_slug = ""
    if location:
        # extract state abbreviation if possible
        state_m = re.search(r'\b([A-Z]{2})\b', location)
        if state_m:
            loc_slug = "_" + state_m.group(1).lower()

    # Try direct page fetch first
    url = f"https://www.fastpeoplesearch.com/name/{slug}{loc_slug}"
    html = _fetch(url, limit=5000)
    if len(html) > 400:
        return {"source": "FastPeopleSearch", "url": url, "content": html, "found": True}

    # Fallback: DDG snippets (cached, no direct hit)
    query = f'site:fastpeoplesearch.com "{name}"' + (f' "{location}"' if location else "")
    results = _ddg(query, max_results=5)
    content = _snippets(results)
    return {
        "source": "FastPeopleSearch",
        "url": url,
        "content": content,
        "found": bool(content.strip())
    }


def scrape_truepeoplesearch(name: str, location: str = "") -> dict:
    """TruePeopleSearch — free, no login, aggregates public records."""
    loc_param = location.replace(" ", "+").replace(",", "") if location else ""
    url = f"https://www.truepeoplesearch.com/results?name={name.replace(' ', '+')}&citystatezip={loc_param}"
    html = _fetch(url, limit=5000)
    if len(html) > 400:
        return {"source": "TruePeopleSearch", "url": url, "content": html, "found": True}

    query = f'site:truepeoplesearch.com "{name}"' + (f' "{location}"' if location else "")
    results = _ddg(query, max_results=4)
    content = _snippets(results)
    return {
        "source": "TruePeopleSearch",
        "url": url,
        "content": content,
        "found": bool(content.strip())
    }


def scrape_radaris(name: str, location: str = "") -> dict:
    """Radaris public records aggregator — free previews."""
    query = f'site:radaris.com "{name}"' + (f' "{location}"' if location else "")
    results = _ddg(query, max_results=4)
    content = _snippets(results)
    return {
        "source": "Radaris",
        "url": f"https://radaris.com/p/{name.replace(' ','+')}",
        "content": content,
        "found": bool(content.strip())
    }


# ──────────────────────────────────────────────────────────
# SOCIAL MEDIA (hint-narrowed)
# ──────────────────────────────────────────────────────────

def scrape_linkedin(name: str, location: str = "", company: str = "") -> dict:
    base = f'"{name}" site:linkedin.com/in'
    if location:
        base += f' "{location}"'
    if company:
        base += f' "{company}"'
    results = _ddg(base, max_results=5)
    if not results:
        results = _ddg(f'{name} linkedin', max_results=4)
    url = next((r.get("href", "") for r in results if "linkedin.com/in/" in r.get("href", "")), "")
    return {
        "source": "LinkedIn",
        "url": url,
        "content": _snippets(results),
        "found": bool(results)
    }


def scrape_facebook(name: str, location: str = "") -> dict:
    query = f'"{name}" site:facebook.com'
    if location:
        query += f' "{location}"'
    results = _ddg(query, max_results=5)
    url = next((r.get("href", "") for r in results if "facebook.com/" in r.get("href", "")), "")
    content = _snippets(results)
    return {"source": "Facebook", "url": url, "content": content, "found": bool(results)}


def scrape_twitter(name: str, username: str = "") -> dict:
    if username:
        results = _ddg(f'site:twitter.com/{username} OR site:x.com/{username}', max_results=4)
    else:
        results = _ddg(f'"{name}" site:twitter.com OR site:x.com', max_results=5)
    url = next((r.get("href", "") for r in results if "twitter.com/" in r.get("href", "") or "x.com/" in r.get("href", "")), "")
    return {"source": "Twitter/X", "url": url, "content": _snippets(results), "found": bool(results)}


def scrape_instagram(name: str, username: str = "") -> dict:
    if username:
        results = _ddg(f'site:instagram.com/{username}', max_results=4)
    else:
        results = _ddg(f'"{name}" site:instagram.com', max_results=4)
    url = next((r.get("href", "") for r in results if "instagram.com/" in r.get("href", "")), "")
    return {"source": "Instagram", "url": url, "content": _snippets(results), "found": bool(results)}


def scrape_reddit(name: str, username: str = "") -> dict:
    if username:
        # Fetch public Reddit profile directly via JSON API
        try:
            import requests
            r = requests.get(
                f"https://www.reddit.com/user/{username}/about.json",
                headers={**_HEADERS, "Accept": "application/json"}, timeout=10
            )
            if r.status_code == 200:
                d = r.json().get("data", {})
                content = (
                    f"Username: {d.get('name','')}\n"
                    f"Link karma: {d.get('link_karma','')}\n"
                    f"Comment karma: {d.get('comment_karma','')}\n"
                    f"Account created: {datetime.fromtimestamp(d.get('created_utc', 0)).strftime('%Y-%m-%d')}\n"
                    f"Verified email: {d.get('has_verified_email','')}\n"
                )
                return {
                    "source": "Reddit",
                    "url": f"https://reddit.com/u/{username}",
                    "content": content,
                    "found": True
                }
        except Exception:
            pass
    results = _ddg(f'"{name}" site:reddit.com', max_results=5)
    return {"source": "Reddit", "url": "", "content": _snippets(results), "found": bool(results)}


def scrape_github(name: str, username: str = "") -> dict:
    import requests
    if username:
        try:
            r = requests.get(
                f"https://api.github.com/users/{username}",
                headers={"Accept": "application/vnd.github.v3+json"}, timeout=10
            )
            if r.status_code == 200:
                p = r.json()
                content = (
                    f"Username: {p.get('login','')}\nName: {p.get('name','')}\n"
                    f"Bio: {p.get('bio','')}\nCompany: {p.get('company','')}\n"
                    f"Location: {p.get('location','')}\nBlog: {p.get('blog','')}\n"
                    f"Followers: {p.get('followers','')}\nPublic repos: {p.get('public_repos','')}\n"
                    f"Twitter: {p.get('twitter_username','')}\n"
                )
                return {"source": "GitHub", "url": p.get("html_url", ""), "content": content, "found": True}
        except Exception:
            pass
    # Search by name
    try:
        r = requests.get(
            f"https://api.github.com/search/users?q={name.replace(' ', '+')}+in:name&per_page=3",
            headers={"Accept": "application/vnd.github.v3+json"}, timeout=10
        )
        if r.status_code == 200:
            items = r.json().get("items", [])
            if items:
                login = items[0].get("login", "")
                r2 = requests.get(f"https://api.github.com/users/{login}",
                                   headers={"Accept": "application/vnd.github.v3+json"}, timeout=10)
                if r2.status_code == 200:
                    p = r2.json()
                    content = (
                        f"Username: {p.get('login','')}\nName: {p.get('name','')}\n"
                        f"Bio: {p.get('bio','')}\nCompany: {p.get('company','')}\n"
                        f"Location: {p.get('location','')}\nBlog: {p.get('blog','')}\n"
                        f"Followers: {p.get('followers','')}\nPublic repos: {p.get('public_repos','')}\n"
                    )
                    return {"source": "GitHub", "url": p.get("html_url", ""), "content": content, "found": True}
    except Exception:
        pass
    return {"source": "GitHub", "url": "", "content": "", "found": False}


def scrape_tiktok(name: str, username: str = "") -> dict:
    query = f'site:tiktok.com/@{username}' if username else f'"{name}" site:tiktok.com'
    results = _ddg(query, max_results=4)
    url = next((r.get("href", "") for r in results if "tiktok.com/@" in r.get("href", "")), "")
    return {"source": "TikTok", "url": url, "content": _snippets(results), "found": bool(results)}


def scrape_news(name: str, location: str = "", company: str = "") -> dict:
    query = f'"{name}"'
    if company:
        query += f' "{company}"'
    if location:
        query += f' "{location}"'
    results = _ddg(query, max_results=10)
    social = {"linkedin.com", "twitter.com", "x.com", "instagram.com", "facebook.com",
              "tiktok.com", "reddit.com", "fastpeoplesearch", "truepeoplesearch", "radaris"}
    filtered = [r for r in results if not any(s in r.get("href", "") for s in social)]
    return {"source": "News / Web", "url": "", "content": _snippets(filtered), "found": bool(filtered)}


# ──────────────────────────────────────────────────────────
# TOOL INTEGRATIONS (Sherlock, holehe)
# ──────────────────────────────────────────────────────────

def _tool_installed(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def run_sherlock(username: str) -> dict:
    """
    Sherlock checks 300+ sites for a username. Install: pip install sherlock-project
    This is the most effective tool for non-famous people when you have a username.
    """
    if not username:
        return {"source": "Sherlock", "content": "", "found": False, "not_run": True}

    # Try sherlock or python -m sherlock
    for cmd in (["sherlock"], [sys.executable, "-m", "sherlock"]):
        try:
            result = subprocess.run(
                cmd + [username, "--print-found", "--no-color", "--timeout", "10"],
                capture_output=True, text=True, timeout=90
            )
            output = result.stdout + result.stderr
            found_urls = re.findall(r'\[\+\]\s+(https?://\S+)', output)
            if found_urls:
                content = f"Username '{username}' found on {len(found_urls)} sites:\n"
                content += "\n".join(found_urls[:50])
                return {"source": "Sherlock", "content": content, "found": True, "sites": found_urls}
            if "not found" in output.lower() or result.returncode == 0:
                return {"source": "Sherlock", "content": f"Username '{username}' not found on checked platforms.", "found": False, "sites": []}
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    return {"source": "Sherlock", "content": "", "found": False, "not_installed": True}


def run_holehe(email: str) -> dict:
    """
    holehe checks 120+ sites for email registration (pip install holehe).
    Calls holehe's internal API directly — no PATH dependency.
    """
    if not email:
        return {"source": "holehe", "content": "", "found": False, "not_run": True}
    try:
        import trio
        import httpx
        import holehe.core as _hc

        modules = _hc.import_submodules("holehe.modules")

        class _Args:
            onlyused = False
            nopasswordrecovery = False
            csvoutput = False
            nocolor = True
            noclear = True
            timeout = 15

        websites = _hc.get_functions(modules, _Args())
        out = []

        async def _run():
            client = httpx.AsyncClient(timeout=15)
            try:
                async with trio.open_nursery() as nursery:
                    for website in websites:
                        nursery.start_soon(_hc.launch_module, website, email, client, out)
            finally:
                await client.aclose()

        trio.run(_run)

        found = [r["name"] for r in out if r.get("exists")]
        content = (
            f"Email '{email}' is registered on {len(found)} service(s):\n"
            + (", ".join(found) if found else "none found")
        )
        return {"source": "holehe", "content": content, "found": bool(found), "registered_on": found}

    except ImportError:
        return {"source": "holehe", "content": "", "found": False, "not_installed": True}
    except Exception as e:
        return {"source": "holehe", "content": f"[ERROR: {e}]", "found": False}


# ──────────────────────────────────────────────────────────
# ORCHESTRATOR
# ──────────────────────────────────────────────────────────

def scrape_all(name: str, hints: dict, progress_cb=None) -> list:
    location = hints.get("location", "")
    # school is treated like company — narrows LinkedIn, Facebook, and news searches
    company = hints.get("company", "") or hints.get("school", "")
    username = hints.get("username", "")
    email = hints.get("email", "")

    scrapers = [
        # People aggregators first — most effective for non-famous people
        ("FastPeopleSearch", lambda: scrape_fastpeoplesearch(name, location)),
        ("TruePeopleSearch", lambda: scrape_truepeoplesearch(name, location)),
        ("Radaris",          lambda: scrape_radaris(name, location)),
        # Social platforms
        ("LinkedIn",         lambda: scrape_linkedin(name, location, company)),
        ("Facebook",         lambda: scrape_facebook(name, location)),
        ("Twitter/X",        lambda: scrape_twitter(name, username)),
        ("Instagram",        lambda: scrape_instagram(name, username)),
        ("Reddit",           lambda: scrape_reddit(name, username)),
        ("GitHub",           lambda: scrape_github(name, username)),
        ("TikTok",           lambda: scrape_tiktok(name, username)),
        ("News / Web",       lambda: scrape_news(name, location, company)),
    ]

    # Add Sherlock if username provided
    if username:
        scrapers.insert(0, ("Sherlock (username search)", lambda: run_sherlock(username)))

    # Add holehe if email provided
    if email:
        scrapers.insert(0, ("holehe (email check)", lambda: run_holehe(email)))

    results = []
    n = len(scrapers)
    for i, (src_name, fn) in enumerate(scrapers):
        if progress_cb:
            progress_cb(src_name, "running", i, n)
        try:
            result = fn()
            result["source"] = result.get("source") or src_name
            results.append(result)
            if result.get("not_installed"):
                status = "not installed"
            elif result.get("not_run"):
                status = "skipped"
            else:
                status = "found" if result.get("found") else "not found"
        except Exception:
            results.append({"source": src_name, "content": "", "found": False})
            status = "error"
        if progress_cb:
            progress_cb(src_name, status, i, n)
    return results


# ──────────────────────────────────────────────────────────
# EXTRACTION LAYER
# ──────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """You are analyzing public OSINT data to build a profile of a person.

Extract everything into this JSON object:
{
  "name": "Full name (as confirmed by sources)",
  "confidence": "high|medium|low — how sure are we this is the right person given the search hints?",
  "role": "Current job title or occupation",
  "company": "Current employer",
  "location": "City, state/country",
  "age_range": "Approximate age range if found (e.g. '30s', 'mid-40s') — null if not found",
  "platforms": [
    {"platform": "name", "handle": "@handle", "url": "...", "followers": "...", "bio": "..."}
  ],
  "platform_sites_found": ["list of sites sherlock found this username on — empty if sherlock not run"],
  "email_registered_on": ["list of services holehe found this email on — empty if holehe not run"],
  "professional_history": ["Previous roles"],
  "education": ["Education history"],
  "relatives": ["Relatives or associates mentioned in public records — first name + last initial only"],
  "addresses_mentioned": ["Cities or regions only — no street addresses"],
  "recent_activity": ["Recent public posts, events, publications"],
  "affiliations": ["Organizations, groups, memberships"],
  "websites": ["Personal sites, blogs"],
  "public_email": "Only if explicitly listed publicly — null otherwise",
  "phone_type": "Mobile|Landline|Unknown — type only if mentioned, no actual number",
  "summary": "2-3 sentence factual overview of what the public data reveals"
}

STRICT RULES:
- Only include what the sources explicitly state. Do not guess.
- NEVER include full phone numbers or full street addresses — city/region only.
- If a field has no data: null for strings, [] for arrays.
- Flag low confidence when name is common and hints don't narrow it down.
- Output ONLY the JSON object.

SEARCH HINTS USED: {hints}

SOURCE DATA:
"""


def extract_profile(sources: list, name: str, hints: dict, completion_fn: Callable, model: str, api_key=None, api_base=None) -> dict:
    combined = f"PERSON: {name}\nHINTS: {json.dumps(hints)}\n\n"
    for s in sources:
        content = s.get("content", "")
        if content and content.strip() and not s.get("not_installed") and not s.get("not_run"):
            combined += f"--- {s['source']} ---\n{content[:3000]}\n\n"
    combined = combined[:14000]

    prompt = _EXTRACT_PROMPT.replace("{hints}", json.dumps(hints)) + combined
    kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    try:
        resp = completion_fn(**kwargs)
        content = resp.choices[0].message.content or ""
        m = re.search(r'\{[\s\S]*\}', content)
        if m:
            return json.loads(m.group())
        return {}
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────
# DISPLAY
# ──────────────────────────────────────────────────────────

_CONF_COLORS = {"high": "\033[92m", "medium": "\033[93m", "low": "\033[91m"}


def display_profile(profile: dict, hints: dict, sources: list):
    B = "\033[94m"; G = "\033[92m"; Y = "\033[93m"; D = "\033[90m"; W = "\033[97m"; R = "\033[91m"; X = "\033[0m"
    sep = f"\033[90m{'━' * 48}\033[0m"
    name = profile.get("name", "Unknown")
    conf = profile.get("confidence", "low")
    conf_color = _CONF_COLORS.get(conf, Y)

    print(f"\n{sep}")
    print(f"{B}  PROFILE: {name}{X}  {conf_color}[{conf.upper()} CONFIDENCE]{X}")
    print(sep)

    # Hints used
    if hints:
        hint_str = "  ".join(f"{k}: {v}" for k, v in hints.items())
        print(f"  {D}Hints: {hint_str}{X}")

    # Source summary
    found = [s["source"] for s in sources if s.get("found")]
    missing = [s["source"] for s in sources if not s.get("found") and not s.get("not_installed") and not s.get("not_run")]
    not_inst = [s["source"] for s in sources if s.get("not_installed")]
    print(f"  {D}Sources hit: {', '.join(found) if found else 'none'}{X}")
    if not_inst:
        print(f"  {Y}Not installed: {', '.join(not_inst)} — see tip below{X}")
    print()

    # Professional
    role = profile.get("role") or ""
    company = profile.get("company") or ""
    loc = profile.get("location") or ""
    age = profile.get("age_range") or ""
    if any([role, company, loc, age]):
        print(f"{B}PROFESSIONAL{X}")
        if role:    print(f"  {D}Role{X}         {W}{role}{X}")
        if company: print(f"  {D}Company{X}      {W}{company}{X}")
        if loc:     print(f"  {D}Location{X}     {W}{loc}{X}")
        if age:     print(f"  {D}Age range{X}    {W}{age}{X}")
        print()

    # History
    hist = profile.get("professional_history") or []
    edu  = profile.get("education") or []
    if hist:
        print(f"{B}CAREER HISTORY{X}")
        for h in hist[:6]: print(f"  {D}•{X} {W}{h}{X}")
        print()
    if edu:
        print(f"{B}EDUCATION{X}")
        for e in edu[:4]: print(f"  {D}•{X} {W}{e}{X}")
        print()

    # Platforms
    platforms = profile.get("platforms") or []
    if platforms:
        print(f"{B}PLATFORMS CONFIRMED{X}")
        for p in platforms:
            follow = f"  {D}({p.get('followers','')} followers){X}" if p.get("followers") else ""
            print(f"  {G}✓{X} {W}{p.get('platform',''):<14}{X}{D}{p.get('handle','') or p.get('url','')}{X}{follow}")
            if p.get("bio"):
                print(f"               {D}{p['bio'][:80]}{X}")
        print()

    # Sherlock sites
    sites = profile.get("platform_sites_found") or []
    if sites:
        print(f"{B}SHERLOCK — USERNAME FOUND ON{X}")
        for s in sites[:15]:
            print(f"  {G}•{X} {D}{s}{X}")
        if len(sites) > 15:
            print(f"  {D}...and {len(sites)-15} more{X}")
        print()

    # holehe
    email_sites = profile.get("email_registered_on") or []
    if email_sites:
        print(f"{B}HOLEHE — EMAIL REGISTERED ON{X}")
        print(f"  {W}{', '.join(email_sites)}{X}\n")

    # Public records
    relatives = profile.get("relatives") or []
    addresses = profile.get("addresses_mentioned") or []
    if relatives or addresses:
        print(f"{B}PUBLIC RECORDS{X}")
        if relatives:
            print(f"  {D}Associates:{X}  {W}{', '.join(relatives[:6])}{X}")
        if addresses:
            print(f"  {D}Areas:{X}       {W}{', '.join(addresses[:4])}{X}")
        print()

    # Activity
    activity = profile.get("recent_activity") or []
    if activity:
        print(f"{B}RECENT PUBLIC ACTIVITY{X}")
        for a in activity[:5]: print(f"  {D}•{X} {W}{a}{X}")
        print()

    # Affiliations + websites
    affiliations = profile.get("affiliations") or []
    websites = profile.get("websites") or []
    pub_email = profile.get("public_email")
    if affiliations:
        print(f"{B}AFFILIATIONS{X}")
        for a in affiliations[:5]: print(f"  {D}•{X} {W}{a}{X}")
        print()
    if websites or pub_email:
        print(f"{B}ONLINE PRESENCE{X}")
        for w in websites[:4]: print(f"  {D}•{X} {W}{w}{X}")
        if pub_email: print(f"  {D}•{X} {W}{pub_email}{X}")
        print()

    # Summary
    summary = profile.get("summary") or ""
    if summary:
        print(f"{B}SUMMARY{X}")
        words = summary.split()
        line, lines = [], []
        for w in words:
            line.append(w)
            if sum(len(x)+1 for x in line) > 64:
                lines.append(" ".join(line)); line = []
        if line: lines.append(" ".join(line))
        for l in lines: print(f"  {W}{l}{X}")
        print()

    # Confidence warning
    if conf == "low":
        print(f"{Y}⚠  Low confidence — name may be common. Add hints to narrow down:{X}")
        print(f"{D}   profile {name} --location \"City, ST\" --company \"Employer\" --username handle{X}")
    elif conf == "medium":
        print(f"{Y}ℹ  Medium confidence — verify key details manually.{X}")

    # Tool tips
    not_inst = [s["source"] for s in sources if s.get("not_installed")]
    if not_inst:
        print(f"\n{D}── INSTALL FOR BETTER COVERAGE ────────────────────{X}")
        if any("Sherlock" in s for s in not_inst):
            print(f"  {Y}pip install sherlock-project{X}  — scans 300+ sites for a username")
        if any("holehe" in s for s in not_inst):
            print(f"  {Y}pip install holehe{X}            — checks 120+ sites for email registration")

    print(f"\n{sep}\n")


# ──────────────────────────────────────────────────────────
# OBSIDIAN OUTPUT
# ──────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def write_obsidian_profile(profile: dict, hints: dict, vault_path: str) -> str:
    name = profile.get("name", "unknown")
    note_path = Path(vault_path) / "profiles" / f"{_slug(name)}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# {name}",
        f"\n**Profiled:** {today}  \n**Confidence:** {profile.get('confidence','unknown')}  ",
        f"**Hints used:** {json.dumps(hints)}\n",
    ]
    for section, key in [("Professional", None), ("Role", "role"), ("Company", "company"), ("Location", "location")]:
        if key and profile.get(key):
            lines.append(f"- **{section}:** {profile[key]}")
    for section, key in [("Career History", "professional_history"), ("Education", "education"),
                          ("Affiliations", "affiliations"), ("Websites", "websites")]:
        items = profile.get(key) or []
        if items:
            lines.append(f"\n## {section}")
            for item in items: lines.append(f"- {item}")
    platforms = profile.get("platforms") or []
    if platforms:
        lines.append("\n## Platforms")
        for p in platforms:
            follow = f" ({p.get('followers','')} followers)" if p.get("followers") else ""
            lines.append(f"- **{p.get('platform','')}** {p.get('handle','')} — {p.get('url','')}{follow}")
    sherlock_sites = profile.get("platform_sites_found") or []
    if sherlock_sites:
        lines.append("\n## Sherlock Results")
        for s in sherlock_sites: lines.append(f"- {s}")
    if profile.get("summary"):
        lines.append(f"\n## Summary\n{profile['summary']}")

    note_path.write_text("\n".join(lines), encoding="utf-8")
    return str(note_path)


# ──────────────────────────────────────────────────────────
# CACHE
# ──────────────────────────────────────────────────────────

def _cache_path(cli_dir: str, name: str) -> Path:
    d = Path(cli_dir) / "div_profile_cache"
    d.mkdir(exist_ok=True)
    return d / f"{_slug(name)}.json"


def load_cache(cli_dir: str, name: str) -> Optional[dict]:
    try:
        return json.loads(_cache_path(cli_dir, name).read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cache(cli_dir: str, name: str, data: dict):
    _cache_path(cli_dir, name).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# ──────────────────────────────────────────────────────────
# MAIN RUNNER
# ──────────────────────────────────────────────────────────

def run_profile(
    name: str,
    hints: dict,
    cli_dir: str,
    completion_fn: Callable,
    model: str,
    api_key: str = None,
    api_base: str = None,
    vault_path: str = None,
    refresh: bool = False,
    speak_fn: Callable = None,
) -> dict:
    B = "\033[94m"; G = "\033[92m"; Y = "\033[93m"; D = "\033[90m"; R = "\033[91m"; X = "\033[0m"
    t0 = time.time()

    print(f"\n{B}🔍 Profiling: {name}{X}")
    if hints:
        hint_str = "  ".join(f"{k}={v}" for k, v in hints.items())
        print(f"  {D}Hints: {hint_str}{X}")
    print(f"  {D}Public data only — people aggregators, social, username correlation.{X}\n")

    cached = None if refresh else load_cache(cli_dir, name)

    if cached and cached.get("sources"):
        print(f"{D}▶ Using cached data (run with --refresh to re-scrape){X}")
        sources = cached["sources"]
        profile = cached.get("profile", {})
    else:
        # ── Scraping ──
        print(f"{B}▶ Scanning sources...{X}")

        def on_scrape(src_name, status, idx, total):
            if status == "running":
                return
            last = idx == total - 1
            prefix = "  └─" if last else "  ├─"
            icons = {
                "found": f"{G}✓ found{X}",
                "not found": f"{D}✗ not found{X}",
                "not installed": f"{Y}⚠ not installed{X}",
                "skipped": f"{D}— skipped{X}",
                "error": f"{R}✗ error{X}",
            }
            icon = icons.get(status, status)
            print(f"{prefix} {src_name:<30} {icon}")

        sources = scrape_all(name, hints, progress_cb=on_scrape)
        found_n = sum(bool(s.get("found")) for s in sources)
        print(f"\n{D}Scanned {len(sources)} sources — {found_n} returned data | Time: {time.time()-t0:.0f}s{X}")

        # ── Extraction ──
        print(f"\n{B}▶ Extracting profile from sources...{X}")
        profile = extract_profile(sources, name, hints, completion_fn, model, api_key, api_base)
        if not profile:
            profile = {"name": name, "confidence": "low", "summary": "Insufficient public data found."}
        print(f"  {D}Done | Time: {time.time()-t0:.0f}s{X}")

    # ── Display ──
    display_profile(profile, hints, sources)

    # ── Cache ──
    cache_data = {"name": name, "hints": hints, "timestamp": datetime.now().isoformat(), "sources": sources, "profile": profile}
    save_cache(cli_dir, name, cache_data)

    # ── Obsidian ──
    if vault_path and os.path.isdir(vault_path):
        write_obsidian_profile(profile, hints, vault_path)
        print(f"{G}✓ Saved to Obsidian: /profiles/{_slug(name)}.md{X}\n")

    print(f"{D}Profile complete | {time.time()-t0:.0f}s total{X}\n")

    if speak_fn:
        summary = profile.get("summary", "")
        role = profile.get("role", "")
        company = profile.get("company", "")
        spoken = f"Profile complete for {name}."
        if role and company:
            spoken += f" Publicly appears to be a {role} at {company}."
        elif summary:
            spoken += f" {summary}"
        speak_fn(spoken)

    return cache_data
