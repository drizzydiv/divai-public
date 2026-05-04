"""
divAI OSINT Investigation Module.
Usage: from div_osint import run_investigation
"""

import re
import json
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────
# SCRAPING LAYER
# ──────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def _clean_html(html: str, limit: int = 8000) -> str:
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:limit]


def _http_get(url: str, timeout: int = 15, json_mode: bool = False):
    import requests
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json() if json_mode else r.text
    except Exception:
        return None


def scrape_wikipedia(case_name: str) -> dict:
    slug = case_name.replace(" ", "_")
    data = _http_get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}", json_mode=True)
    if data:
        full = _http_get(
            f"https://en.wikipedia.org/w/api.php?action=query&titles={slug}&prop=extracts&format=json&exintro=false",
            json_mode=True
        )
        if full:
            pages = full.get("query", {}).get("pages", {})
            for page in pages.values():
                text = re.sub(r'<[^>]+>', ' ', page.get("extract", ""))
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    return {"source": "Wikipedia", "url": f"https://en.wikipedia.org/wiki/{slug}", "content": text[:8000], "found": True}
        extract = data.get("extract", "")
        return {"source": "Wikipedia", "url": f"https://en.wikipedia.org/wiki/{slug}", "content": extract[:8000], "found": bool(extract)}
    return {"source": "Wikipedia", "url": f"https://en.wikipedia.org/wiki/{slug}", "content": "", "found": False}


def scrape_reddit(case_name: str, max_posts: int = 10) -> dict:
    import requests
    query = case_name.replace(" ", "+")
    try:
        r = requests.get(
            f"https://www.reddit.com/r/UnresolvedMysteries/search.json?q={query}&restrict_sr=1&sort=top&limit={max_posts}",
            headers={**_HEADERS, "Accept": "application/json"}, timeout=15
        )
        posts = r.json().get("data", {}).get("children", []) if r.status_code == 200 else []
        texts = [
            f"[POST: {p['data'].get('title','')} (score: {p['data'].get('score',0)})]\n{p['data'].get('selftext','')[:1500]}"
            for p in posts
        ]
        return {
            "source": "Reddit r/UnresolvedMysteries",
            "url": f"https://reddit.com/r/UnresolvedMysteries/search?q={query}",
            "content": "\n\n".join(texts)[:8000],
            "found": bool(posts),
            "count": len(posts)
        }
    except Exception:
        return {"source": "Reddit r/UnresolvedMysteries", "url": "", "content": "", "found": False, "count": 0}


def scrape_news(case_name: str, max_results: int = 10) -> dict:
    try:
        from ddgs import DDGS
        results = DDGS().text(f"{case_name} disappearance missing case", max_results=max_results)
        texts = [
            f"[ARTICLE: {r.get('title','')}]\n{r.get('href','')}\n{r.get('body','')}"
            for r in (results or [])
        ]
        return {
            "source": "News Archives",
            "url": f"https://duckduckgo.com/?q={case_name.replace(' ','+')}",
            "content": "\n\n".join(texts)[:8000],
            "found": bool(texts),
            "count": len(texts)
        }
    except Exception as e:
        return {"source": "News Archives", "url": "", "content": f"[ERROR: {e}]", "found": False, "count": 0}


def scrape_wayback_cdx(case_name: str) -> dict:
    query = case_name.replace(" ", "+")
    data = _http_get(
        f"http://web.archive.org/cdx/search/cdx?url=*{query}*&output=json&limit=30&fl=original,timestamp,statuscode&filter=statuscode:200",
        timeout=20, json_mode=True
    )
    if data and len(data) > 1:
        lines = [f"URL: {row[0]} | Date: {row[1]}" for row in data[1:30]]
        return {
            "source": "Wayback Machine CDX",
            "url": f"https://web.archive.org/web/*/{query}",
            "content": "\n".join(lines),
            "found": True,
            "count": len(data) - 1
        }
    return {"source": "Wayback Machine CDX", "url": "", "content": "", "found": False, "count": 0}


def scrape_charley_project(case_name: str) -> dict:
    slug = case_name.lower().replace(" ", "_")
    html = _http_get(f"https://charleyproject.org/case/{slug}")
    if html:
        text = _clean_html(html)
        if len(text) > 300:
            return {"source": "Charley Project", "url": f"https://charleyproject.org/case/{slug}", "content": text, "found": True}
    html = _http_get(f"https://charleyproject.org/?s={case_name.replace(' ', '+')}")
    text = _clean_html(html) if html else ""
    return {
        "source": "Charley Project",
        "url": f"https://charleyproject.org/?s={case_name.replace(' ', '+')}",
        "content": text[:4000],
        "found": len(text) > 300
    }


def scrape_namus(case_name: str) -> dict:
    import requests
    try:
        r = requests.post(
            "https://www.namus.gov/api/CaseSets/NamUs/MissingPersons/Search",
            json={"take": 5, "skip": 0, "filters": [], "searchWords": case_name},
            headers={**_HEADERS, "Content-Type": "application/json"},
            timeout=15
        )
        results = r.json().get("results", []) if r.status_code == 200 else []
        texts = [
            f"Case: {res.get('firstName','')} {res.get('lastName','')} | "
            f"State: {res.get('stateOfLastContact','')} | "
            f"Date: {res.get('dateOfLastContact','')} | "
            f"Case#: {res.get('caseNumber','')}"
            for res in results[:3]
        ]
        return {"source": "NamUs", "url": "https://www.namus.gov/MissingPersons", "content": "\n".join(texts), "found": bool(texts)}
    except Exception:
        return {"source": "NamUs", "url": "", "content": "", "found": False}


def scrape_all(case_name: str, progress_cb=None) -> list:
    scrapers = [
        ("Wikipedia", scrape_wikipedia),
        ("Reddit r/UnresolvedMysteries", scrape_reddit),
        ("Charley Project", scrape_charley_project),
        ("NamUs", scrape_namus),
        ("News Archives", scrape_news),
        ("Wayback Machine CDX", scrape_wayback_cdx),
    ]
    results = []
    n = len(scrapers)
    for i, (name, fn) in enumerate(scrapers):
        if progress_cb:
            progress_cb(name, "running", i, n)
        try:
            result = fn(case_name)
            results.append(result)
            status = "found" if result.get("found") else "not found"
        except Exception:
            results.append({"source": name, "content": "", "found": False})
            status = "error"
        if progress_cb:
            progress_cb(name, status, i, n)
    return results


# ──────────────────────────────────────────────────────────
# EXTRACTION LAYER
# ──────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """You are an investigative research assistant. Extract every factual claim from the text below about a missing persons case.

Output a JSON array. Each item must have:
{"claim": "specific statement", "source": "where this came from", "date": "YYYY or YYYY-MM-DD or unknown", "topic": "timeline|evidence|location|witness|suspect|theory|administrative", "confidence": "verified|stated|alleged|rumored"}

Output ONLY the JSON array, nothing else.

TEXT:
"""


def _chunk_text(text: str, size: int = 3500) -> list:
    words = text.split()
    chunks, cur, cur_len = [], [], 0
    for w in words:
        cur.append(w)
        cur_len += len(w) + 1
        if cur_len >= size:
            chunks.append(" ".join(cur))
            cur, cur_len = [], 0
    if cur:
        chunks.append(" ".join(cur))
    return chunks or [""]


def _extract_chunk(text: str, source_name: str, completion_fn: Callable, model: str, api_key=None, api_base=None) -> list:
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": _EXTRACT_PROMPT + text}],
        "temperature": 0
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    try:
        resp = completion_fn(**kwargs)
        content = resp.choices[0].message.content or ""
        m = re.search(r'\[[\s\S]*\]', content)
        if m:
            claims = json.loads(m.group())
            for c in claims:
                if not c.get("source"):
                    c["source"] = source_name
            return [c for c in claims if isinstance(c, dict) and c.get("claim")]
        return []
    except Exception:
        return []


def extract_all_claims(sources: list, completion_fn: Callable, model: str, api_key=None, api_base=None, progress_cb=None) -> list:
    all_claims = []
    chunk_num = 0
    valid = [s for s in sources if s.get("content") and not s["content"].startswith("[ERROR")]
    total_chunks = sum(max(1, len(_chunk_text(s["content"]))) for s in valid)

    for source in valid:
        for chunk in _chunk_text(source["content"]):
            chunk_num += 1
            if progress_cb:
                progress_cb(chunk_num, total_chunks, source.get("source", ""))
            all_claims.extend(_extract_chunk(chunk, source.get("source", ""), completion_fn, model, api_key, api_base))

    seen, deduped = set(), []
    for c in all_claims:
        key = c.get("claim", "")[:80].lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


# ──────────────────────────────────────────────────────────
# CLASSIFICATION LAYER
# ──────────────────────────────────────────────────────────

_STATUS_MAP = {"verified": "Confirmed", "stated": "Reported", "alleged": "Unconfirmed", "rumored": "Unconfirmed"}


def classify_claims(claims: list) -> dict:
    groups = {"Confirmed": [], "Reported": [], "Unconfirmed": [], "Contradicted": []}
    for c in claims:
        groups[_STATUS_MAP.get(c.get("confidence", "stated"), "Reported")].append(c)
    return groups


def detect_contradictions(claims: list, completion_fn: Callable, model: str, api_key=None, api_base=None) -> list:
    if len(claims) < 3:
        return []
    claims_text = "\n".join(
        f"{i+1}. [{c.get('source','')}] [{c.get('topic','')}] {c.get('claim','')}"
        for i, c in enumerate(claims[:80])
    )
    prompt = f"""Analyze these claims from a missing persons investigation. Find contradictions — where two claims state conflicting facts about the same specific thing (dates, locations, names, sequences of events).

For each contradiction output:
{{"topic": "short name", "description": "what they disagree about", "claim_a": "...", "source_a": "...", "claim_b": "...", "source_b": "...", "priority": "high|medium|low"}}

Output a JSON array. If none found, output [].

CLAIMS:
{claims_text}"""

    kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    try:
        resp = completion_fn(**kwargs)
        content = resp.choices[0].message.content or ""
        m = re.search(r'\[[\s\S]*\]', content)
        return json.loads(m.group()) if m else []
    except Exception:
        return []


def build_priority_leads(claims: list, contradictions: list) -> dict:
    tier1, tier2, tier3 = [], [], []
    rank = 1
    for c in contradictions:
        lead = {
            "rank": rank, "type": "contradiction",
            "title": c.get("topic", "Contradiction"),
            "description": c.get("description", ""),
            "osint_potential": "Archive verification possible" if c.get("priority") == "high" else "Requires manual digging",
            "data": c
        }
        (tier1 if c.get("priority") == "high" else tier2 if c.get("priority") == "medium" else tier3).append(lead)
        rank += 1

    for c in claims:
        if c.get("topic") in ("evidence", "witness", "location") and c.get("confidence") in ("verified", "stated"):
            tier2.append({"rank": rank, "type": "claim", "title": c.get("claim", "")[:70], "description": f"Source: {c.get('source','')}", "osint_potential": "Cross-reference public databases", "data": c})
            rank += 1

    for c in claims:
        if c.get("topic") in ("theory", "administrative") and c.get("confidence") == "rumored":
            tier3.append({"rank": rank, "type": "claim", "title": c.get("claim", "")[:70], "description": f"Source: {c.get('source','')}", "osint_potential": "Low signal — cold lead", "data": c})
            rank += 1

    return {"tier1": tier1[:5], "tier2": tier2[:5], "tier3": tier3[:5]}


# ──────────────────────────────────────────────────────────
# OBSIDIAN OUTPUT
# ──────────────────────────────────────────────────────────

def _case_slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def write_obsidian(case_name: str, data: dict, vault_path: str) -> str:
    slug = _case_slug(case_name)
    inv_dir = Path(vault_path) / "investigations" / slug
    inv_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    claims = data.get("claims", [])
    contradictions = data.get("contradictions", [])
    leads = data.get("leads", {})
    sources = data.get("sources", [])
    groups = classify_claims(claims)

    (inv_dir / "_index.md").write_text(
        f"# {case_name} Investigation\n\n"
        f"**Status:** Active  \n**Created:** {today}  \n**Method:** divAI OSINT Module v1.0\n\n"
        f"## Quick Stats\n"
        f"- Sources: {len(sources)}  \n- Claims: {len(claims)}  \n"
        f"- Verified: {len(groups.get('Confirmed',[]))}  \n"
        f"- Contradictions: {len(contradictions)}  \n- Tier-1 Leads: {len(leads.get('tier1',[]))}\n\n"
        f"## Links\n[[{slug}/claims]] | [[{slug}/contradictions]] | [[{slug}/leads]] | [[{slug}/sources]]\n",
        encoding="utf-8"
    )

    claims_md = f"# Claims — {case_name}\n\n"
    for status, group in groups.items():
        claims_md += f"## {status} ({len(group)})\n\n"
        for c in group:
            claims_md += f"- **{c.get('claim','')}** *(source: {c.get('source','')}, {c.get('date','unknown')})*\n"
        claims_md += "\n"
    (inv_dir / "claims.md").write_text(claims_md, encoding="utf-8")

    contr_md = f"# Contradictions — {case_name}\n\n"
    for i, c in enumerate(contradictions):
        contr_md += (
            f"## #{i+1}: {c.get('topic','')}\n{c.get('description','')}\n\n"
            f"**A:** {c.get('claim_a','')} *(via {c.get('source_a','')})*\n\n"
            f"**B:** {c.get('claim_b','')} *(via {c.get('source_b','')})*\n\n"
            f"Priority: **{c.get('priority','').upper()}**\n\n---\n\n"
        )
    (inv_dir / "contradictions.md").write_text(contr_md, encoding="utf-8")

    leads_md = f"# Priority Leads — {case_name}\n\n"
    for tier_name, tier_leads in leads.items():
        leads_md += f"## {tier_name.upper()}\n\n"
        for lead in tier_leads:
            leads_md += f"**#{lead.get('rank','')}** {lead.get('title','')}\n- {lead.get('description','')}\n- OSINT: {lead.get('osint_potential','')}\n\n"
    (inv_dir / "leads.md").write_text(leads_md, encoding="utf-8")

    sources_md = f"# Sources — {case_name}\n\n"
    for s in sources:
        sources_md += f"- {'✓' if s.get('found') else '✗'} **{s.get('source','')}** — {s.get('url','')}\n"
    (inv_dir / "sources.md").write_text(sources_md, encoding="utf-8")

    return str(inv_dir)


# ──────────────────────────────────────────────────────────
# CACHE
# ──────────────────────────────────────────────────────────

def _cache_path(cli_dir: str, case_name: str) -> Path:
    d = Path(cli_dir) / "div_osint_cache"
    d.mkdir(exist_ok=True)
    return d / f"{_case_slug(case_name)}.json"


def load_cache(cli_dir: str, case_name: str) -> Optional[dict]:
    path = _cache_path(cli_dir, case_name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_cache(cli_dir: str, case_name: str, data: dict):
    _cache_path(cli_dir, case_name).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def latest_cached_investigation(cli_dir: str) -> Optional[dict]:
    cache_dir = Path(cli_dir) / "div_osint_cache"
    if not cache_dir.is_dir():
        return None
    files = sorted(cache_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return None


# ──────────────────────────────────────────────────────────
# INTERACTIVE CONTRADICTION REVIEW
# ──────────────────────────────────────────────────────────

def interactive_contradiction_review(contradictions: list):
    B = "\033[94m"; Y = "\033[93m"; G = "\033[92m"; D = "\033[90m"; X = "\033[0m"
    for i, c in enumerate(contradictions):
        print(f"\n{B}CONTRADICTION #{i+1}: {c.get('topic','')}{X}")
        print(f"\n{B}📌 WHAT THEY DISAGREE ON:{X}")
        print(f"  {c.get('description','')}")
        print(f"\n{B}SOURCE A:{X} {c.get('claim_a','')}")
        print(f"  {D}via {c.get('source_a','')}{X}")
        print(f"\n{B}SOURCE B:{X} {c.get('claim_b','')}")
        print(f"  {D}via {c.get('source_b','')}{X}")
        print(f"\n  Priority: {Y}{c.get('priority','').upper()}{X}")
        print(f"\n{D}  [n]ext  [m]ark as manual-priority  [q]uit review{X}")
        try:
            key = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if key == "q":
            break
        if key == "m":
            print(f"  {G}✓ Marked for manual investigation.{X}")


# ──────────────────────────────────────────────────────────
# MAIN RUNNER
# ──────────────────────────────────────────────────────────

def run_investigation(
    case_name: str,
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

    print(f"\n{B}🔍 Starting investigation: {case_name}{X}\n")

    cached = None if refresh else load_cache(cli_dir, case_name)

    # ── Step 1: Scraping ──
    if cached and cached.get("sources"):
        print(f"{D}▶ Using cached sources (run with --refresh to re-scrape){X}")
        sources = cached["sources"]
    else:
        print(f"{B}▶ Scraping public sources...{X}")

        def on_scrape(name, status, idx, total):
            if status == "running":
                return
            last = idx == total - 1
            prefix = "  └─" if last else "  ├─"
            icon = f"{G}✓ found{X}" if status == "found" else f"{Y}✗ not found{X}" if status == "not found" else f"{R}✗ error{X}"
            print(f"{prefix} {name} ... {icon}")

        sources = scrape_all(case_name, progress_cb=on_scrape)
        words = sum(len(s.get("content", "").split()) for s in sources if s.get("found"))
        found_n = sum(bool(s.get("found")) for s in sources)
        print(f"\n{D}Collected: ~{words} words from {found_n}/{len(sources)} sources | Time: {time.time()-t0:.0f}s{X}")

    # ── Step 2: Extraction ──
    if cached and cached.get("claims"):
        print(f"\n{D}▶ Using cached claims{X}")
        claims = cached["claims"]
    else:
        print(f"\n{B}▶ Extracting claims and facts...{X}")
        print(f"  {D}Processing with LLM (batch mode){X}")

        def on_extract(chunk_num, total, source_name):
            last = "└─" if chunk_num == total else "├─"
            print(f"  {last} Chunk {chunk_num}/{total} ({source_name}) ...")

        claims = extract_all_claims(sources, completion_fn, model, api_key, api_base, progress_cb=on_extract)
        print(f"\n{D}Extracted: {len(claims)} distinct claims | Time: {time.time()-t0:.0f}s{X}")

    # ── Step 3: Classification ──
    print(f"\n{B}▶ Classifying claims...{X}")
    groups = classify_claims(claims)
    label_map = {
        "Confirmed": "verified across multiple sources",
        "Reported": "stated by sources, not externally verified",
        "Unconfirmed": "mentioned, not verified",
        "Contradicted": "sources disagree"
    }
    for status, group in groups.items():
        dots = "." * max(1, 48 - len(status) - len(label_map[status]) - len(str(len(group))))
        print(f"  ├─ {status} ({label_map[status]}) {dots} {len(group)}")

    # ── Step 4: Contradictions ──
    print(f"\n{B}▶ Detecting contradictions...{X}")
    contradictions = detect_contradictions(claims, completion_fn, model, api_key, api_base)
    if contradictions:
        print(f"\n{Y}⚠️  Contradictions detected:{X}")
        for i, c in enumerate(contradictions[:6]):
            print(f"  {i+1}. {c.get('topic','Contradiction')}")
    else:
        print(f"  └─ {D}No contradictions detected{X}")

    # ── Step 5: Leads ──
    print(f"\n{B}▶ Building lead queue...{X}")
    leads = build_priority_leads(claims, contradictions)

    print(f"\n{B}📋 PRIORITY LEADS (ranked by investigative potential):{X}")
    if leads["tier1"]:
        print(f"\n{R}TIER 1 (High-confidence OSINT targets):{X}")
        for lead in leads["tier1"]:
            print(f"  {lead['rank']}. 🔴 {lead['title']} → {lead['osint_potential']}")
    if leads["tier2"]:
        print(f"\n{Y}TIER 2 (Requires manual digging):{X}")
        for lead in leads["tier2"]:
            print(f"  {lead['rank']}. 🟡 {lead['title']}")
    if leads["tier3"]:
        print(f"\n{D}TIER 3 (Cold/low signal):{X}")
        for lead in leads["tier3"]:
            print(f"  {lead['rank']}. ⚪ {lead['title']}")

    # ── Cache ──
    inv_data = {
        "case_name": case_name,
        "timestamp": datetime.now().isoformat(),
        "sources": sources,
        "claims": claims,
        "contradictions": contradictions,
        "leads": leads,
    }
    save_cache(cli_dir, case_name, inv_data)

    # ── Obsidian ──
    if vault_path and os.path.isdir(vault_path):
        print(f"\n{B}▶ Writing to Obsidian vault...{X}")
        write_obsidian(case_name, inv_data, vault_path)
        print(f"  └─ {G}✓ Saved to /investigations/{_case_slug(case_name)}/{X}")

    print(f"\n{D}Investigation complete | {time.time()-t0:.0f}s total{X}\n")

    # ── Interactive contradiction review ──
    if contradictions:
        print(f"{Y}Press Enter to review contradictions in detail... (or type q to skip){X}")
        try:
            key = input(f"{D}  > {X}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            key = "q"
        if key != "q":
            interactive_contradiction_review(contradictions)

    # ── Voice summary ──
    if speak_fn:
        parts = [f"Investigation complete for {case_name}.", f"I found {len(claims)} distinct claims across public sources."]
        if contradictions:
            parts.append(f"The highest-priority lead is a contradiction about {contradictions[0].get('topic','an unresolved discrepancy')}.")
        if leads["tier1"]:
            parts.append(f"Top tier-one lead: {leads['tier1'][0].get('title','')}.")
        if vault_path:
            parts.append("Full files saved to your Obsidian vault under investigations.")
        speak_fn(" ".join(parts))

    return inv_data


# ──────────────────────────────────────────────────────────
# NARRATIVE SYNTHESIS
# ──────────────────────────────────────────────────────────

NARRATIVE_SYNTHESIS_PROMPT = """You are a documentary filmmaker analyzing cold case OSINT findings. Your job is to synthesize raw investigation data into cinematic narrative beats—moments that create tension, reveal contradictions, and surface investigable leads.

Here is the raw OSINT data from the investigation:

CASE: {case_name}
INVESTIGATION DATE: {investigation_date}

RAW CLAIMS DATA:
{claims_data}

CONTRADICTIONS DETECTED:
{contradictions_data}

LEAD QUEUE:
{leads_data}

---

Your task: Generate a "NARRATIVE BRIEF" that a filmmaker would use to decide what story to tell. Output exactly this format, one section per line:

🎬 CINEMATIC HOOK:
[One sentence. The detail that makes someone stop scrolling. What's the visual/narrative that stops people cold? Not "man disappeared" but "walked into building with 47 cameras, left without appearing on a single one"]

⚠️  CORE CONTRADICTION:
[If contradictions exist, state the most investigable one in 1-2 sentences. "Source A says X but Source B says Y, and here's why it matters." If no contradictions, state: "NONE DETECTED - but here's the biggest unanswered question:"]

🔴 TOP TIER 1 LEAD:
[The single most cinematic, immediately investigable lead. One sentence. Include the investigative method.]

🟡 TOP TIER 2 LEAD:
[Second priority. What evidence can you access? One sentence.]

⚪ TOP TIER 3 LEAD:
[Third priority. One sentence.]

❓ THE KNOWLEDGE GAP:
[What's the biggest question that public data CANNOT answer? This is honest. This is where OSINT hits its limit. One sentence.]

🎤 VOICEOVER (15 seconds):
[A short narrative summary that divAI can speak aloud. 3-4 sentences max. Pacing for ~15 seconds of voice. Include: who, what happened, why it matters, what you're investigating. Sound like a true crime doc, not a data dump.]

---

IMPORTANT:
- Be specific, not generic. Cinematic details win over summaries.
- Leads must be INVESTIGABLE with public data. Wayback Machine, Reddit archives, NamUs, news searches — these are in scope. "Find out what really happened" is not.
- The voiceover should sound like it's being spoken, not read.
- If the data doesn't support cinematic framing, say that honestly."""


def _format_claims_for_narrative(claims: list, groups: dict) -> str:
    lines = [f"Total claims extracted: {len(claims)}\n"]
    for status in ("Confirmed", "Reported", "Unconfirmed"):
        group = groups.get(status, [])
        lines.append(f"{status.upper()} ({len(group)}):")
        for c in group[:8]:
            lines.append(f"  • {c.get('claim','')} (source: {c.get('source','')}, date: {c.get('date','unknown')})")
        if len(group) > 8:
            lines.append(f"  ...and {len(group) - 8} more")
        lines.append("")
    return "\n".join(lines)


def _format_contradictions_for_narrative(contradictions: list) -> str:
    if not contradictions:
        return "No contradictions detected."
    lines = [f"{len(contradictions)} contradiction(s) detected:\n"]
    for i, c in enumerate(contradictions):
        lines.append(f"#{i+1} [{c.get('priority','').upper()}] {c.get('topic','')}")
        lines.append(f"  {c.get('description','')}")
        lines.append(f"  A: {c.get('claim_a','')} (via {c.get('source_a','')})")
        lines.append(f"  B: {c.get('claim_b','')} (via {c.get('source_b','')})")
        lines.append("")
    return "\n".join(lines)


def _format_leads_for_narrative(leads: dict) -> str:
    lines = []
    for tier_name, tier_leads in leads.items():
        if tier_leads:
            lines.append(f"{tier_name.upper()}:")
            for lead in tier_leads:
                lines.append(f"  #{lead.get('rank','')} {lead.get('title','')} — {lead.get('osint_potential','')}")
        lines.append("")
    return "\n".join(lines)


def extract_voiceover(narrative_text: str) -> str:
    """Pull the 🎤 VOICEOVER section from the narrative output."""
    m = re.search(r'🎤\s*VOICEOVER[^\n]*\n([\s\S]*?)(?:\n---|\Z)', narrative_text)
    if m:
        return m.group(1).strip().lstrip('[').rstrip(']')
    return ""


def generate_narrative_brief(
    inv_data: dict,
    completion_fn: Callable,
    model: str,
    api_key: str = None,
    api_base: str = None,
) -> str:
    """
    Synthesize investigation data into a cinematic narrative brief.
    Returns the raw narrative text (caller handles display and TTS).
    """
    claims = inv_data.get("claims", [])
    contradictions = inv_data.get("contradictions", [])
    leads = inv_data.get("leads", {})
    groups = classify_claims(claims)

    prompt = NARRATIVE_SYNTHESIS_PROMPT.format(
        case_name=inv_data.get("case_name", "Unknown"),
        investigation_date=inv_data.get("timestamp", datetime.now().isoformat())[:10],
        claims_data=_format_claims_for_narrative(claims, groups),
        contradictions_data=_format_contradictions_for_narrative(contradictions),
        leads_data=_format_leads_for_narrative(leads),
    )

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base

    try:
        resp = completion_fn(**kwargs)
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"[Narrative generation failed: {e}]"
