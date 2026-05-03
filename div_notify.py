"""divAI Notification Engine — Windows toast alerts for study reminders."""

import os, json, subprocess
from datetime import datetime, timezone, timedelta

CLI_DIR       = os.path.dirname(os.path.abspath(__file__))
NOTIFIED_FILE = os.path.join(CLI_DIR, "div_notified.json")


def toast(title: str, message: str):
    """Fire a Windows toast notification via PowerShell WinRT (no extra deps)."""
    t = title.replace("'", "''").replace('"', '`"')
    m = message.replace("'", "''").replace('"', '`"')
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument,"
        "Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
        "$xml=[Windows.UI.Notifications.ToastNotificationManager]::"
        "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$xml.GetElementsByTagName('text')[0].InnerText='{t}';"
        f"$xml.GetElementsByTagName('text')[1].InnerText='{m}';"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($xml);"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier('divAI').Show($toast)"
    )
    subprocess.Popen(
        ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _load_notified() -> dict:
    try:
        return json.load(open(NOTIFIED_FILE, encoding="utf-8"))
    except:
        return {}

def _save_notified(data: dict):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    cleaned = {k: v for k, v in data.items() if v > cutoff}
    with open(NOTIFIED_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f)


def check_and_notify():
    """Check Canvas + Knowt + Fiveable for urgent items, fire a toast if needed."""
    notified = _load_notified()
    now      = datetime.now(timezone.utc)
    alerts   = []

    # ── Canvas assignments ──
    try:
        config = json.load(open(os.path.join(CLI_DIR, "div_config.json"), encoding="utf-8"))
        curl   = config.get("canvas_url", "")
        ctoken = config.get("canvas_token", "")
        if curl and ctoken:
            from div_canvas import fetch_upcoming_assignments
            for a in fetch_upcoming_assignments(curl, ctoken, days_ahead=3):
                due_dt = a.get("due_dt")
                if not due_dt:
                    continue
                hrs = (due_dt - now).total_seconds() / 3600
                key = f"canvas:{a['name']}:{a['course']}"
                if key not in notified:
                    if hrs <= 3:
                        alerts.append(f"⚠️ Due in {int(hrs)}h: {a['name']} ({a['course']})")
                        notified[key] = now.isoformat()
                    elif hrs <= 24:
                        alerts.append(f"📋 Due tomorrow: {a['name']} ({a['course']})")
                        notified[key] = now.isoformat()
    except Exception:
        pass

    # ── Knowt exams ──
    try:
        kpath = os.path.join(CLI_DIR, "div_knowt_cache.json")
        if os.path.exists(kpath):
            data = json.load(open(kpath, encoding="utf-8"))
            for ex in data.get("exams", []):
                edate = ex.get("exam_date", "")
                if not edate:
                    continue
                try:
                    dt   = datetime.fromisoformat(edate + "T00:00:00+00:00") if "T" not in edate else datetime.fromisoformat(edate)
                    days = (dt - now).days
                    key  = f"knowt:{ex['name']}:{edate}"
                    if key not in notified and 0 <= days <= 1:
                        cards = ex.get("cards_due")
                        suffix = f" · {cards} cards due" if cards else ""
                        label  = "TODAY ⚠️" if days == 0 else "tomorrow 🔴"
                        alerts.append(f"Knowt exam {label}: {ex['name']}{suffix}")
                        notified[key] = now.isoformat()
                except Exception:
                    pass
    except Exception:
        pass

    # ── Fiveable exams ──
    try:
        fpath = os.path.join(CLI_DIR, "div_fiveable_cache.json")
        if os.path.exists(fpath):
            data = json.load(open(fpath, encoding="utf-8"))
            for ex in data.get("exams", []):
                edate = ex.get("exam_date", "")
                if not edate:
                    continue
                try:
                    dt   = datetime.fromisoformat(edate + "T00:00:00+00:00") if "T" not in edate else datetime.fromisoformat(edate)
                    days = (dt - now).days
                    key  = f"fiveable:{ex['name']}:{edate}"
                    if key not in notified and 0 <= days <= 1:
                        label = "TODAY ⚠️" if days == 0 else "tomorrow 🔴"
                        alerts.append(f"Fiveable AP exam {label}: {ex['name']}")
                        notified[key] = now.isoformat()
                except Exception:
                    pass
    except Exception:
        pass

    _save_notified(notified)

    if alerts:
        title   = "divAI · Study Alert"
        message = alerts[0] if len(alerts) == 1 else f"{alerts[0]}  (+{len(alerts)-1} more)"
        toast(title, message)

    return alerts


if __name__ == "__main__":
    print("Testing divAI notification system...")
    toast("divAI", "Notification system active ✓")
    print("Toast sent — check your notification area.")
