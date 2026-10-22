"""
============================================================
 ⚡ Energy Manager - Hourly Live Market Tracker & Strict Emergency Alerts
 🏢 Company: abhijaysinghlimited
 🎯 Source: https://energymanagergame.com/ (Official Game Web Client)
 🔔 ntfy Topic: abhijaysinghlimited-energy-fuel-alert
============================================================

✨ Features
1. ENABLED switch   — set ENABLED = False to mute everything.
2. Morning Briefing — sent ONCE per day inside a strict 06:30–07:30 IST window.
3. Hourly Live Radar — checks prices every hour; silent unless thresholds breach.
4. Strict Emergency Thresholds (silent unless in range):
     • Oil       < $1.90   →  BUY OIL QUICKLY
     • Coal      < $1.50   →  BUY COAL QUICKLY
     • Hydrogen  > $90.00  →  SELL HYDROGEN QUICKLY
     • CO2       < $20.00  →  BUY CO2 QUICKLY
     • Uranium   ignored.
5. Cooldown dedup  — each commodity alerts at most once every 6 hours per dip.
6. Self-test mode  — run with --test-notify to verify ntfy.sh works.
7. Diagnostic mode — run with --debug to print full HTTP bodies to log file.

Usage
-----
  python energy_fuel_notifier.py                # normal hourly run
  python energy_fuel_notifier.py --briefing     # force a morning briefing now
  python energy_fuel_notifier.py --test-notify  # send a test push to ntfy
  python energy_fuel_notifier.py --debug        # verbose logging
  python energy_fuel_notifier.py --force        # ignore ENABLED flag and briefing window
============================================================
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import time
from typing import Any, Optional

import requests
from zoneinfo import ZoneInfo

# Force UTF-8 stdout (Windows terminals choke on emoji otherwise).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
#  MASTER TOGGLE
# ============================================================
ENABLED = True

# ============================================================
#  CONFIGURATION
# ============================================================
NTFY_TOPIC = "abhijaysinghlimited-energy-fuel-alert"
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "energy_state.json")
LOG_FILE = os.path.join(HERE, "energy_notifier.log")

# Credentials — prefer env vars, fall back to defaults if vacant.
EM_EMAIL = os.getenv("EM_EMAIL") or "abhijaychauhan98@duck.com"
EM_PASSWORD = os.getenv("EM_PASSWORD") or "alok@singh"

# --- Strict Emergency Thresholds ---
OIL_BUY_THRESHOLD = 1.90          # Alert when Oil < $1.90
COAL_BUY_THRESHOLD = 1.50         # Alert when Coal < $1.50
HYDROGEN_SELL_THRESHOLD = 90.00   # Alert when Hydrogen > $90.00
CO2_BUY_THRESHOLD = 20.00         # Alert when CO2 < $20.00

# Daily briefing window (24h IST).
BRIEFING_START = (6, 30)
BRIEFING_END = (7, 30)

# Don't re-alert the same commodity within this window.
ALERT_COOLDOWN_SECONDS = 6 * 3600  # 6 hours

# API endpoints. Adjust ONLY if the site changes.
BASE_URL = "https://energymanagergame.com"
LOGIN_URL = f"{BASE_URL}/weblogin/signin.php"
PRICE_API_URL = f"{BASE_URL}/api/price.history.api.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ============================================================
#  LOGGING
# ============================================================
DEBUG = "--debug" in sys.argv
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("energy")


# ============================================================
#  STATE PERSISTENCE
# ============================================================
DEFAULT_STATE: dict[str, Any] = {
    "oil_alerted_ts": None,
    "coal_alerted_ts": None,
    "hydrogen_alerted_ts": None,
    "co2_alerted_ts": None,
    "last_briefing_date": None,
}


def load_state() -> dict:
    """Load persistent alert state, merging with defaults for forward-compat."""
    state = dict(DEFAULT_STATE)
    # Migrate old boolean keys → new timestamp keys if present.
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k in list(data.keys()):
                if k.endswith("_alerted") and isinstance(data[k], bool):
                    # Old boolean marker → treat as "alerted just now" only if True.
                    new_key = k.replace("_alerted", "_alerted_ts")
                    data[new_key] = time.time() if data[k] else None
                    del data[k]
            state.update(data)
        except Exception as e:
            log.warning(f"State file unreadable ({e}); using defaults.")
    return state


def save_state(state: dict) -> None:
    """Atomic state write via temp file + os.replace."""
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log.error(f"Could not save state: {e}")


# ============================================================
#  TIME HELPERS
# ============================================================
def in_briefing_window(now: datetime.datetime) -> bool:
    """Return True if `now` (local) is inside [06:30, 07:30] inclusive."""
    mins = now.hour * 60 + now.minute
    start = BRIEFING_START[0] * 60 + BRIEFING_START[1]
    end = BRIEFING_END[0] * 60 + BRIEFING_END[1]
    return start <= mins <= end


# ============================================================
#  AUTH
# ============================================================
def create_authenticated_session(retries: int = 3, delay: int = 5) -> Optional[requests.Session]:
    """Log in to energymanagergame.com and STRICTLY verify success.

    Returns a Session with auth cookies, or None on failure.
    The previous version accepted any HTTP 200 as success — that was the
    main bug: a failed-login page also returns 200, so the script thought
    it was logged in while holding no auth cookies.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    login_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/weblogin/",
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    payload = {"mail": EM_EMAIL, "pass": EM_PASSWORD, "remember": "1"}

    for attempt in range(1, retries + 1):
        try:
            res = session.post(LOGIN_URL, data=payload, headers=login_headers, timeout=15)
            body_lower = res.text.lower()

            log.debug(
                f"Login attempt {attempt}/{retries}: status={res.status_code} "
                f"cookies={dict(session.cookies)} body[:200]={res.text[:200]!r}"
            )

            # Hard-fail markers — even with HTTP 200 these mean login failed.
            failure_markers = [
                "incorrect", "invalid", "wrong password", "login failed",
                "unauthorized", "error", "access denied",
            ]
            if any(m in body_lower for m in failure_markers) and "success" not in body_lower:
                log.error(
                    f"Login attempt {attempt} rejected by server. "
                    f"Body snippet: {res.text[:300]!r}"
                )
                time.sleep(delay)
                continue

            # Success criteria — require BOTH a 2xx status AND a session cookie.
            if res.status_code in (200, 302) and session.cookies:
                # Heuristic: a real auth cookie typically named PHPSESSID or similar.
                cookie_names = {c.name.lower() for c in session.cookies}
                auth_like = any(
                    n in cookie_names
                    for n in ("phpsessid", "session", "auth", "user", "token", "remember")
                )
                if auth_like or "success" in body_lower or res.status_code == 302:
                    log.info(f"Login OK (attempt {attempt}, status {res.status_code}).")
                    return session
                log.warning(
                    f"Login attempt {attempt}: 2xx but cookies look non-auth: "
                    f"{cookie_names}"
                )
            else:
                log.warning(
                    f"Login attempt {attempt}: status={res.status_code}, "
                    f"cookies_set={bool(session.cookies)}"
                )
        except requests.RequestException as e:
            log.error(f"Login attempt {attempt} network error: {e}")
        time.sleep(delay)

    log.error("All login attempts failed.")
    return None


# ============================================================
#  PRICE FETCHING
# ============================================================
def _is_number(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _extract_price_series(data: Any) -> list[float]:
    """Best-effort: pull a list of numeric prices out of an unknown JSON shape.

    Handles: [1.2, 1.3] / [{"price":1.2}, ...] / {"history":[...]} /
    {"current":1.2} — anything else returns [].
    """
    if isinstance(data, list):
        if not data:
            return []
        if _is_number(data[0]):
            return [float(x) for x in data if _is_number(x)]
        if isinstance(data[0], dict):
            for key in ("price", "value", "p", "y", "close", "amount"):
                vals = [d.get(key) for d in data if isinstance(d, dict) and key in d]
                if vals and all(_is_number(v) for v in vals):
                    return [float(v) for v in vals]
        return []
    if isinstance(data, dict):
        for key in ("history", "prices", "data", "series", "values"):
            if key in data:
                out = _extract_price_series(data[key])
                if out:
                    return out
        for key in ("current", "price", "value"):
            v = data.get(key)
            if _is_number(v):
                return [float(v)]
    return []


def fetch_live_commodity_prices(session: requests.Session, retries: int = 3, delay: int = 3) -> dict:
    """Fetch live market prices for Oil / Coal / Hydrogen / CO2."""
    market: dict[str, dict] = {}
    for target in ("oil", "coal", "hydrogen", "co2"):
        url = f"{PRICE_API_URL}?target={target}"
        for attempt in range(1, retries + 1):
            try:
                r = session.get(url, timeout=10)
                if r.status_code != 200:
                    log.warning(f"{target}: HTTP {r.status_code} on attempt {attempt}")
                    time.sleep(delay)
                    continue

                try:
                    data = r.json()
                except ValueError as e:
                    log.error(
                        f"{target}: response is not JSON ({e}). "
                        f"Body[:200]={r.text[:200]!r}"
                    )
                    # If the body is HTML, the session isn't actually authenticated.
                    if "<html" in r.text.lower()[:200]:
                        log.error(
                            f"{target}: got HTML, not JSON → session is NOT logged in. "
                            f"Check credentials or login URL."
                        )
                    break

                history = _extract_price_series(data)
                if not history:
                    log.warning(
                        f"{target}: couldn't find numeric series in response "
                        f"(shape: {str(data)[:200]})"
                    )
                    break

                market[target] = {
                    "current": history[-1],
                    "min": min(history),
                    "max": max(history),
                    "history": history,
                }
                log.info(
                    f"{target:>8}: current=${history[-1]:.2f} "
                    f"(min=${min(history):.2f}, max=${max(history):.2f}, "
                    f"samples={len(history)})"
                )
                break
            except requests.RequestException as e:
                log.error(f"{target}: network error on attempt {attempt}: {e}")
                time.sleep(delay)
    return market


# ============================================================
#  NOTIFICATIONS
# ============================================================
def send_to_ntfy(
    topic: str,
    message: str,
    title: str,
    tags: str = "factory,fuelpump",
    priority: str = "default",
) -> bool:
    """Send a push notification to ntfy.sh. Returns True on 200 response."""
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Markdown": "yes",
    }
    try:
        response = requests.post(
            url, data=message.encode("utf-8"), headers=headers, timeout=15
        )
        if response.status_code == 200:
            log.info(f"ntfy OK → {title}")
            return True
        log.error(f"ntfy FAIL: HTTP {response.status_code}: {response.text[:200]}")
        return False
    except requests.RequestException as e:
        log.error(f"ntfy network error: {e}")
        return False


def send_test_notification() -> bool:
    """Send a test push so the user can verify ntfy.sh / topic is correct."""
    log.info(f"Sending TEST notification to ntfy.sh/{NTFY_TOPIC} ...")
    return send_to_ntfy(
        NTFY_TOPIC,
        (
            "✅ **Test notification from Energy Manager notifier.**\n\n"
            "If you see this on your phone, your ntfy topic is configured "
            "correctly and the script can reach ntfy.sh.\n\n"
            "Subscribe to this topic in the ntfy mobile app:\n"
            f"`{NTFY_TOPIC}`"
        ),
        title="Energy Manager: TEST",
        tags="white_check_mark,test_tube",
        priority="default",
    )


# ============================================================
#  BRIEFING
# ============================================================
def build_morning_briefing(market: dict, now: datetime.datetime) -> str:
    date_str = now.strftime("%A, %d %B %Y")
    current_time_12h = now.strftime("%I:%M %p")

    lines = [
        "⚡ ━━━━━━━━━━━━━━━━━━━━━━━━━ ⚡",
        "      ENERGY MANAGER • MARKET BRIEFING",
        "             abhijaysinghlimited",
        "⚡ ━━━━━━━━━━━━━━━━━━━━━━━━━ ⚡",
        f"📅 **Date:** {date_str} | ⏰ **Time:** {current_time_12h} IST",
        f"📡 **Account:** `{EM_EMAIL}`",
        "",
        "📊 ━━━ 🌐 LIVE COMMODITY SNAPSHOT ━━━ 📊",
    ]

    if "oil" in market:
        c = market["oil"]["current"]
        status = "🟢 CRITICAL BUY!" if c < OIL_BUY_THRESHOLD else "⏳ NORMAL"
        lines.append(
            f"• 🛢️ **Oil:** **${c:.2f}** *(Target: < ${OIL_BUY_THRESHOLD:.2f})* {status}"
        )
    if "coal" in market:
        c = market["coal"]["current"]
        status = "🟢 CRITICAL BUY!" if c < COAL_BUY_THRESHOLD else "⏳ NORMAL"
        lines.append(
            f"• 🪨 **Coal:** **${c:.2f}** *(Target: < ${COAL_BUY_THRESHOLD:.2f})* {status}"
        )
    if "hydrogen" in market:
        c = market["hydrogen"]["current"]
        status = "🚀 PEAK SELL!" if c > HYDROGEN_SELL_THRESHOLD else "⏳ HOLDING"
        lines.append(
            f"• 💧 **Hydrogen:** **${c:.2f}** *(Target: > ${HYDROGEN_SELL_THRESHOLD:.2f})* {status}"
        )
    if "co2" in market:
        c = market["co2"]["current"]
        status = "🟢 CRITICAL BUY!" if c < CO2_BUY_THRESHOLD else "⏳ NORMAL"
        lines.append(
            f"• 🍃 **CO2 Quota:** **${c:.2f}** *(Target: < ${CO2_BUY_THRESHOLD:.2f})* {status}"
        )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🚨 **STRICT HOURLY RADAR ACTIVE:**")
    lines.append("📱 You'll get an emergency alert only when a price enters your target range.")
    return "\n".join(lines)


# ============================================================
#  EMERGENCY CHECKS
# ============================================================
def _within_cooldown(state: dict, key: str) -> bool:
    ts = state.get(f"{key}_alerted_ts")
    if not ts:
        return False
    age = time.time() - ts
    if age < ALERT_COOLDOWN_SECONDS:
        log.debug(f"{key}: in cooldown ({age/60:.1f} min since last alert).")
        return True
    return False


def check_emergency_conditions(market: dict, state: dict, current_time_12h: str) -> tuple[dict, int]:
    """Send one emergency alert per dip, with a cooldown so we don't spam you."""
    alerts_sent = 0

    # (key, threshold, direction, action, emoji, tags, summary)
    checks = [
        ("oil",       OIL_BUY_THRESHOLD,      "below", "BUY OIL QUICKLY",       "🛢️", "rotating_light,fuelpump,warning",   "Oil price crashed below your buy threshold!"),
        ("coal",      COAL_BUY_THRESHOLD,     "below", "BUY COAL QUICKLY",     "🪨", "rotating_light,fire,warning",      "Coal price crashed below your buy threshold!"),
        ("hydrogen",  HYDROGEN_SELL_THRESHOLD, "above", "SELL HYDROGEN QUICKLY", "💧", "rotating_light,money_with_wings,zap", "Hydrogen surged past your sell target!"),
        ("co2",       CO2_BUY_THRESHOLD,      "below", "BUY CO2 QUICKLY",      "🍃", "rotating_light,recycle,warning",   "CO2 quota price dropped below your target!"),
    ]

    for key, threshold, direction, action, emoji, tags, summary in checks:
        if key not in market:
            continue
        price = market[key]["current"]
        triggered = (price < threshold) if direction == "below" else (price > threshold)

        if triggered:
            if _within_cooldown(state, key):
                log.info(f"{key}: triggered (${price:.2f}) but in cooldown. Skipping.")
                continue
            title = f"{action} (${price:.2f})"
            msg = (
                f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                f"          {emoji} {action}!\n"
                f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                f"⏰ **Detected At:** {current_time_12h} IST [LIVE]\n"
                f"💰 **Current Price:** **${price:.2f}** "
                f"*(Target: {direction} ${threshold:.2f})*\n"
                f"🏢 **Account:** `{EM_EMAIL}`\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                f"{summary}\n"
                f"👉 Open **Energy Manager** and act now!"
            )
            if send_to_ntfy(NTFY_TOPIC, msg, title, tags=tags, priority="urgent"):
                state[f"{key}_alerted_ts"] = time.time()
                alerts_sent += 1
        else:
            # Price normalized — clear the marker so the NEXT dip alerts fresh.
            if state.get(f"{key}_alerted_ts") is not None:
                log.info(f"{key}: normalized (${price:.2f}). Clearing alert marker.")
                state[f"{key}_alerted_ts"] = None

    return state, alerts_sent


# ============================================================
#  MAIN
# ============================================================
def main() -> int:
    # --- Special: self-test ---
    if "--test-notify" in sys.argv:
        ok = send_test_notification()
        return 0 if ok else 1

    if not ENABLED and "--force" not in sys.argv:
        log.info("Energy alerts are DISABLED (ENABLED=False). Exiting.")
        return 0

    # --- Validate config ---
    if not EM_EMAIL or not EM_PASSWORD:
        log.error("EM_EMAIL or EM_PASSWORD is empty. Set env vars or update script defaults.")
        return 2

    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    today_str = now.strftime("%Y-%m-%d")

    state = load_state()

    # --- Briefing decision (FIXED — strict window, once per day) ---
    should_send_briefing = (
        "--briefing" in sys.argv
        or "--force" in sys.argv
        or (in_briefing_window(now) and state.get("last_briefing_date") != today_str)
    )

    log.info("=" * 60)
    log.info(" ⚡ Energy Manager Live Tracker - abhijaysinghlimited")
    log.info(f" Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    log.info(f" Topic: {NTFY_TOPIC}")
    log.info(f" Mode : {'Daily Briefing + Radar' if should_send_briefing else 'Silent Hourly Radar'}")
    log.info("=" * 60)

    # --- Login ---
    log.info("Logging in to energymanagergame.com...")
    session = create_authenticated_session()
    if not session:
        log.error("Login failed. Sending a failure notification and exiting.")
        send_to_ntfy(
            NTFY_TOPIC,
            (
                "⚠️ Energy Manager notifier could NOT log in.\n\n"
                "Likely causes:\n"
                "• Wrong EM_EMAIL / EM_PASSWORD\n"
                "• Login endpoint changed (`weblogin/signin.php`)\n"
                "• Account locked / captcha required\n\n"
                f"Account: `{EM_EMAIL}`\n"
                "No price checks were performed."
            ),
            title="Energy Manager: LOGIN FAILED",
            tags="warning,lock",
            priority="high",
        )
        return 3

    # --- Fetch prices ---
    log.info("Fetching live commodity prices...")
    market = fetch_live_commodity_prices(session)

    if not market:
        log.error("No market data retrieved. Sending a failure notification and exiting.")
        send_to_ntfy(
            NTFY_TOPIC,
            (
                "⚠️ Energy Manager notifier could not fetch ANY market data.\n\n"
                "Likely causes:\n"
                "• Price API endpoint changed (`api/price.history.api.php`)\n"
                "• Session authenticated but API returns different JSON shape\n"
                "• Site under maintenance\n\n"
                "Run with --debug and inspect energy_notifier.log to see the "
                "raw HTTP responses."
            ),
            title="Energy Manager: NO MARKET DATA",
            tags="warning,chart_decreasing",
            priority="high",
        )
        return 4

    # --- Briefing ---
    if should_send_briefing:
        briefing_msg = build_morning_briefing(market, now)
        log.info("Sending morning briefing...")
        if send_to_ntfy(
            NTFY_TOPIC,
            briefing_msg,
            title=f"Energy Manager: Daily Market Briefing ({current_time_12h})",
            tags="factory,clipboard,zap,sparkles",
            priority="default",
        ):
            state["last_briefing_date"] = today_str
            save_state(state)
    else:
        log.info(
            f"Briefing not sent — outside 06:30–07:30 window or already sent today ({today_str})."
        )

    # --- Emergency checks ---
    log.info("Checking emergency thresholds...")
    state, alerts_sent = check_emergency_conditions(market, state, current_time_12h)
    if alerts_sent == 0:
        log.info("All commodities outside emergency range. Zero alerts sent.")
    else:
        log.info(f"Total emergency alerts sent: {alerts_sent}")

    save_state(state)
    log.info("Run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
