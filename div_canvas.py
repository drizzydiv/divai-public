"""Canvas LMS integration for divAI — full API access plus assignment context injection."""

import re
import requests
from datetime import datetime, timezone, timedelta

CANVAS_TIMEOUT = 12


def fetch_courses(canvas_url: str, token: str) -> list:
    """Return active courses with id, name, course_code."""
    headers = {"Authorization": f"Bearer {token}"}
    base = canvas_url.rstrip("/")
    try:
        r = requests.get(
            f"{base}/api/v1/courses",
            params={"enrollment_state": "active", "per_page": 50},
            headers=headers, timeout=CANVAS_TIMEOUT
        )
        r.raise_for_status()
        return [{"id": c["id"], "name": c.get("name", ""), "code": c.get("course_code", "")}
                for c in r.json() if isinstance(c, dict) and c.get("id")]
    except Exception as e:
        return [{"error": str(e)}]


def canvas_api(canvas_url: str, token: str, endpoint: str, params: dict = None):
    """Generic GET request to any Canvas API endpoint. Returns parsed JSON."""
    headers = {"Authorization": f"Bearer {token}"}
    base = canvas_url.rstrip("/")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    try:
        r = requests.get(
            f"{base}{endpoint}",
            params=params or {},
            headers=headers, timeout=CANVAS_TIMEOUT
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def fetch_upcoming_assignments(canvas_url: str, token: str, days_ahead: int = 21) -> list:
    """Return a list of upcoming assignment dicts sorted by due date."""
    headers   = {"Authorization": f"Bearer {token}"}
    base      = canvas_url.rstrip("/")
    cutoff    = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    now       = datetime.now(timezone.utc)
    results   = []

    # ── 1. Active courses ──
    try:
        r = requests.get(
            f"{base}/api/v1/courses",
            params={"enrollment_state": "active", "per_page": 30},
            headers=headers, timeout=CANVAS_TIMEOUT
        )
        r.raise_for_status()
        courses = [c for c in r.json() if isinstance(c, dict) and c.get("id")]
    except Exception as e:
        return [{"error": str(e)}]

    # ── 2. Assignments per course ──
    for course in courses:
        cid   = course["id"]
        cname = course.get("name") or course.get("course_code") or f"Course {cid}"
        try:
            ar = requests.get(
                f"{base}/api/v1/courses/{cid}/assignments",
                params={"bucket": "upcoming", "per_page": 50, "order_by": "due_at"},
                headers=headers, timeout=CANVAS_TIMEOUT
            )
            if ar.status_code != 200:
                continue
            for a in ar.json():
                if not isinstance(a, dict):
                    continue
                due_str = a.get("due_at")
                if not due_str:
                    continue
                try:
                    due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if due_dt < now or due_dt > cutoff:
                    continue
                results.append({
                    "course":       cname,
                    "name":         a.get("name", "Assignment"),
                    "due_at":       due_str,
                    "due_dt":       due_dt,
                    "points":       a.get("points_possible"),
                    "submitted":    bool(a.get("has_submitted_submissions")),
                    "url":          a.get("html_url", ""),
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["due_dt"])
    return results


def fetch_announcements(canvas_url: str, token: str, course_ids: list, per_course: int = 3) -> list:
    """Return recent announcements across all courses."""
    headers = {"Authorization": f"Bearer {token}"}
    base = canvas_url.rstrip("/")
    if not course_ids:
        return []
    try:
        params = [("per_page", per_course * len(course_ids))]
        for cid in course_ids:
            params.append(("context_codes[]", f"course_{cid}"))
        r = requests.get(
            f"{base}/api/v1/announcements",
            params=params,
            headers=headers, timeout=CANVAS_TIMEOUT
        )
        r.raise_for_status()
        results = []
        for a in r.json():
            if not isinstance(a, dict):
                continue
            course_code = a.get("context_code", "")
            cid_str = course_code.replace("course_", "")
            results.append({
                "course_id": cid_str,
                "title":     a.get("title", ""),
                "posted":    a.get("posted_at", ""),
                "message":   re.sub(r"<[^>]+>", " ", a.get("message", ""))[:300].strip(),
                "url":       a.get("html_url", ""),
            })
        return results[:per_course * 3]
    except Exception as e:
        return [{"error": str(e)}]


def format_for_prompt(assignments: list) -> str:
    """Format assignment list for injection into the system prompt."""
    if not assignments:
        return "No upcoming assignments in the next 3 weeks."

    if assignments and "error" in assignments[0]:
        return f"Canvas fetch error: {assignments[0]['error']}"

    now = datetime.now(timezone.utc)
    lines = []
    for a in assignments[:25]:
        due_dt  = a["due_dt"]
        delta   = due_dt - now
        days    = delta.days
        hrs     = int(delta.total_seconds() // 3600)

        if hrs < 24:
            urgency = f"⚠️ DUE IN {hrs}h"
        elif days == 1:
            urgency = "🔴 DUE TOMORROW"
        elif days <= 3:
            urgency = f"🟠 {days}d left"
        elif days <= 7:
            urgency = f"🟡 {days}d left"
        else:
            urgency = f"📅 {days}d left"

        due_str  = due_dt.strftime("%a %b %#d, %#I:%M%p").lower()
        pts      = f" ({int(a['points'])} pts)" if a.get("points") else ""
        done     = " ✅" if a.get("submitted") else ""
        lines.append(f"  {urgency} | {a['course']}: {a['name']}{pts} — due {due_str}{done}")

    return "\n".join(lines)


def format_for_display(assignments: list) -> str:
    """Format for readable terminal/UI display."""
    if not assignments:
        return "No upcoming assignments in the next 3 weeks."
    if assignments and "error" in assignments[0]:
        return f"Canvas error: {assignments[0]['error']}"

    now  = datetime.now(timezone.utc)
    out  = []
    prev = None
    for a in assignments[:25]:
        week = a["due_dt"].isocalendar()[1]
        if week != prev:
            label = "This Week" if week == now.isocalendar()[1] else "Next Week" if week == now.isocalendar()[1]+1 else a["due_dt"].strftime("Week of %b %#d")
            out.append(f"\n── {label} ──")
            prev = week
        due  = a["due_dt"].strftime("%a %b %#d @ %#I:%M%p")
        pts  = f" · {int(a['points'])} pts" if a.get("points") else ""
        done = " ✅" if a.get("submitted") else ""
        out.append(f"  • {a['name']}{done}\n    {a['course']}{pts} — {due}")

    return "\n".join(out).strip()
