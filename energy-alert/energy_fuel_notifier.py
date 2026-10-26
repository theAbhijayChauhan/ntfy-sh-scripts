"""
============================================================
 ⚡ Energy Manager - 24/7 Live Market Tracker & Emergency Alerts
 🏢 Company: abhijaysinghlimited
 🎯 Source: https://energymanagergame.com/ (Official Game Web Client)
 🔔 Discord Webhook (via discord_notifier.py → #energy-alerts channel)
============================================================

✨ Features
1. ENABLED switch — set ENABLED = False to mute everything.
2. 24/7 Live Radar — runs every hour at :30 (e.g. 7:30, 8:30, 9:30...).
3. Timing Safety — if triggered at :28 or :29, waits until :30:05 before fetching
   so it never checks old prices before the game refreshes.
4. Strict Emergency Thresholds (strictly silent unless breached):
     • Oil       < $1.50   →  BUY OIL QUICKLY
     • Coal      < $1.50   →  BUY COAL QUICKLY
     • Hydrogen  > $99.00  →  SELL HYDROGEN QUICKLY
     • CO2       < $20.00  →  BUY CO2 QUICKLY
5. Cooldown dedup  — each commodity alerts at most once every 6 hours per dip.
6. Diagnostic mode — run with --debug to print full HTTP bodies to log file.

Usage
-----
  python energy_fuel_notifier.py                # normal hourly radar check
  python energy_fuel_notifier.py --test-notify # send a test push to Discord
  python energy_fuel_notifier.py --debug       # verbose logging
  python energy_fuel_notifier.py --force       # ignore cooldown and check
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

# Add the script's own dir to path so we can import discord_notifier
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
for p in (HERE, PARENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from discord_notifier import send_to_discord  # noqa: E402

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
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

STATE_FILE = os.path.join(HERE, "energy_state.json")
LOG_FILE = os.path.join(HERE, "energy_notifier.log")

# Credentials — prefer env vars, fall back to defaults.
EM_EMAIL = os.getenv("EM_EMAIL", "abhijaychauhan98@duck.com")
EM_PASSWORD = os.getenv("EM_PASSWORD", "alok@singh")

# --- Strict Emergency Thresholds ---
OIL_BUY_THRESHOLD = 1.50          # Alert when Oil < $1.50
COAL_BUY_THRESHOLD = 1.50         # Alert when Coal < $1.50
HYDROGEN_SELL_THRESHOLD = 99.00   # Alert when Hydrogen > $99.00
CO2_BUY_THRESHOLD = 20.00         # Alert when CO2 < $20.00

# Don't re-alert the same commodity within this window.
ALERT_COOLDOWN_SECONDS = 6 * 3600  # 6 hours

# API endpoints.
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
}


def load_state() -> dict:
    """Load persistent alert state, merging with defaults for forward-compat."""
    state = dict(DEFAULT_STATE)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # Clean up legacy keys if present
                for k in list(data.keys()):
                    if k in state:
                        state[k] = data[k]
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
#  AUTH
# ============================================================
def create_authenticated_session(retries: int = 3, delay: int = 5) -> Optional[requests.Session]:
    """Log in to energymanagergame.com and verify success."""
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

            failure_markers = [
                "incorrect", "invalid", "wrong password", "login failed",
                "unauthorized", "error", "access denied",
            ]
            if any(m in body_lower for m in failure_markers) and "success" not in body_lower:
                log.error(
                    f"Login attempt {attempt} rejected by server: {res.text[:300]!r}"
                )
                time.sleep(delay)
                continue

            if res.status_code in (200, 302) and session.cookies:
                cookie_names = {c.name.lower() for c in session.cookies}
                auth_like = any(
                    n in cookie_names
                    for n in ("phpsessid", "session", "auth", "user", "token", "remember")
                )
                if auth_like or "success" in body_lower or res.status_code == 302:
                    log.info(f"Login OK (attempt {attempt}, status {res.status_code}).")
                    return session
                log.warning(
                    f"Login attempt {attempt}: non-auth cookies: {cookie_names}"
                )
            else:
                log.warning(
                    f"Login attempt {attempt}: status={res.status_code}, cookies_set={bool(session.cookies)}"
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
    """Best-effort: pull a list of numeric prices out of an unknown JSON shape."""
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
                    log.error(f"{target}: response is not JSON ({e}). Body[:200]={r.text[:200]!r}")
                    break

                history = _extract_price_series(data)
                if not history:
                    log.warning(f"{target}: couldn't find numeric series in response: {str(data)[:200]}")
                    break

                market[target] = {
                    "current": history[-1],
                    "min": min(history),
                    "max": max(history),
                    "history": history,
                }
                log.info(
                    f"{target:>8}: current=${history[-1]:.2f} "
                    f"(min=${min(history):.2f}, max=${max(history):.2f}, samples={len(history)})"
                )
                break
            except requests.RequestException as e:
                log.error(f"{target}: network error on attempt {attempt}: {e}")
                time.sleep(delay)
    return market


# ============================================================
#  NOTIFICATIONS
# ============================================================
def send_test_notification() -> bool:
    log.info("Sending TEST notification to Discord #energy-alerts webhook...")
    return send_to_discord(
        message=(
            "✅ **Test from Energy Manager 24/7 Live Radar.**\n\n"
            "If you see this in your #energy-alerts channel, your Energy "
            "webhook + script work.\n\n"
            "Thresholds active:\n"
            f"• Oil < ${OIL_BUY_THRESHOLD:.2f}\n"
            f"• Coal < ${COAL_BUY_THRESHOLD:.2f}\n"
            f"• Hydrogen > ${HYDROGEN_SELL_THRESHOLD:.2f}\n"
            f"• CO2 < ${CO2_BUY_THRESHOLD:.2f}"
        ),
        title="Energy Manager: TEST",
        priority="default",
    )


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
    """Send one emergency alert per dip, strictly silent otherwise."""
    alerts_sent = 0

    checks = [
        ("oil",      OIL_BUY_THRESHOLD,       "below", "BUY OIL QUICKLY",        "🛢️", "rotating_light,fuelpump,warning",     "Oil price crashed below your $1.50 buy threshold!"),
        ("coal",     COAL_BUY_THRESHOLD,      "below", "BUY COAL QUICKLY",      "🪨", "rotating_light,fire,warning",       "Coal price crashed below your $1.50 buy threshold!"),
        ("hydrogen", HYDROGEN_SELL_THRESHOLD, "above", "SELL HYDROGEN QUICKLY", "💧", "rotating_light,money_with_wings,zap", "Hydrogen surged past your $99 sell target!"),
        ("co2",      CO2_BUY_THRESHOLD,        "below", "BUY CO2 QUICKLY",       "🍃", "rotating_light,recycle,warning",     "CO2 quota price dropped below your target!"),
    ]

    for key, threshold, direction, action, emoji, tags, summary in checks:
        if key not in market:
            continue
        price = market[key]["current"]
        triggered = (price < threshold) if direction == "below" else (price > threshold)

        if triggered:
            if _within_cooldown(state, key):
                log.info(f"{key}: triggered (${price:.2f}) but in cooldown. Skipping duplicate.")
                continue
            title = f"{action} (${price:.2f})"
            msg = (
                f"🚨 **{emoji} {action}!**\n"
                f"💰 **Current Price:** **${price:.2f}** *(Target: {direction} ${threshold:.2f})*\n"
                f"⏰ **Detected At:** {current_time_12h} IST [LIVE]\n"
                f"🎯 **Action:** {summary}\n"
                f"👉 Open **Energy Manager** and act now!"
            )
            if send_to_discord(message=msg, title=title, tags=tags, priority="urgent"):
                state[f"{key}_alerted_ts"] = time.time()
                alerts_sent += 1
        else:
            if state.get(f"{key}_alerted_ts") is not None:
                log.info(f"{key}: normalized (${price:.2f}). Clearing alert marker.")
                state[f"{key}_alerted_ts"] = None

    return state, alerts_sent


# ============================================================
#  MAIN RUNNER
# ============================================================
def main() -> int:
    if "--test-notify" in sys.argv:
        ok = send_test_notification()
        return 0 if ok else 1

    if not ENABLED and "--force" not in sys.argv:
        log.info("Energy alerts are DISABLED (ENABLED=False). Exiting.")
        return 0

    if not EM_EMAIL or not EM_PASSWORD:
        log.error("EM_EMAIL or EM_PASSWORD is empty. Set env vars.")
        return 2

    # --- TIMING SAFETY GUARD ---
    # Prices in Energy Manager refresh at :30 past the hour (e.g. 7:30, 8:30).
    # If triggered slightly early at :28 or :29, wait until :30:05 before fetching
    # so we never check old/stale prices from the previous hour.
    now = datetime.datetime.now(LOCAL_TZ)
    if now.minute in (28, 29):
        wait_sec = (29 - now.minute) * 60 + (60 - now.second) + 5
        log.info(
            f"Triggered early at {now.strftime('%I:%M:%S %p')} (:28/:29). "
            f"Waiting {wait_sec}s until :30:05 to fetch fresh market prices..."
        )
        time.sleep(wait_sec)
        now = datetime.datetime.now(LOCAL_TZ)

    current_time_12h = now.strftime("%I:%M %p")

    log.info("=" * 60)
    log.info(" ⚡ Energy Manager 24/7 Live Tracker - abhijaysinghlimited")
    log.info(f" Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    log.info(" Mode : Silent Hourly Radar (Notifies ONLY when threshold breaches)")
    log.info(f" Targets: Oil < ${OIL_BUY_THRESHOLD:.2f} | Coal < ${COAL_BUY_THRESHOLD:.2f}")
    log.info(f"          Hydrogen > ${HYDROGEN_SELL_THRESHOLD:.2f} | CO2 < ${CO2_BUY_THRESHOLD:.2f}")
    log.info("=" * 60)

    # 1. Login
    log.info("Logging in to energymanagergame.com...")
    session = create_authenticated_session()
    if not session:
        log.error("Login failed.")
        send_to_discord(
            message=(
                "⚠️ Energy Manager notifier could NOT log in.\n\n"
                f"Account: `{EM_EMAIL}`\n"
                "Please verify your credentials."
            ),
            title="Energy Manager: LOGIN FAILED",
            priority="high",
        )
        return 3

    # 2. Fetch live prices
    log.info("Fetching live commodity prices...")
    market = fetch_live_commodity_prices(session)
    if not market:
        log.error("No market data retrieved.")
        send_to_discord(
            message="⚠️ Energy Manager notifier could not fetch live market prices.",
            title="Energy Manager: NO MARKET DATA",
            priority="high",
        )
        return 4

    # 3. Emergency checks (silent unless breached)
    state = load_state()
    state, alerts_sent = check_emergency_conditions(market, state, current_time_12h)
    save_state(state)

    if alerts_sent == 0:
        log.info("All commodities within normal range or in cooldown. Strictly silent.")

    log.info(f"Run complete. Alerts fired: {alerts_sent}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
