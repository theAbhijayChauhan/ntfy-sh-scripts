"""
============================================================
 🚆 Train Manager - 24/7 Live Fuel & Spot Market Tracker
 🏢 Company: abhijaysinghlimited
 🎯 Source: https://trainmanager.cc/ (Official Game Web Client)
 🔔 Discord Webhook (via discord_notifier.py)
============================================================

✨ Features
1. ENABLED switch     — set ENABLED = False to mute everything.
2. 24/7 Live Radar    — runs every 15 minutes to check real in-game prices.
3. Direct Game Auth   — logs into trainmanager.cc using game credentials.
4. Emergency Alerts (silent unless in range):
     • Fuel  <= $2,800 / 1,000 L    →  BUY FUEL QUICKLY
     • Spot  <= $600   / 1,000 kWh  →  BUY SPOT POWER QUICKLY
5. Cooldown dedup     — alerts once per price dip, prevents repetitive spam.
6. Diagnostic mode    — run with --debug for verbose logging.
7. Test mode          — run with --test-notify to verify Discord delivery.

Usage
-----
  python train_fuel_notifier.py                # normal 15-min radar check
  python train_fuel_notifier.py --test-notify  # send a test push to Discord
  python train_fuel_notifier.py --debug        # verbose logging
  python train_fuel_notifier.py --force        # ignore cooldown and check
============================================================
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
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

from discord_notifier import send_to_discord, upsert_to_discord  # noqa: E402

# Force UTF-8 stdout (Windows terminals choke on emoji otherwise).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ============================================================
#  MASTER SWITCH
# ============================================================
ENABLED = True

# ============================================================
#  CONFIGURATION
# ============================================================
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

STATE_FILE = os.path.join(HERE, "train_state.json")
LOG_FILE = os.path.join(HERE, "train_notifier.log")

# Credentials — prefer env vars, fall back to defaults (same as Energy Manager).
TM_EMAIL = os.getenv("TM_EMAIL") or os.getenv("EM_EMAIL", "abhijaychauhan98@duck.com")
TM_PASSWORD = os.getenv("TM_PASSWORD") or os.getenv("EM_PASSWORD", "alok@singh")

# --- Strict Emergency Buy Thresholds ---
# User targets:
# • Fuel <= $2,800 / 1,000 L
# • Spot <= $600 / 1,000 kWh
FUEL_BUY_THRESHOLD = 2800.0   # Alert when Fuel <= $2,800 / 1,000 L
SPOT_BUY_THRESHOLD = 600.0    # Alert when Spot <= $600 / 1,000 kWh

# Don't re-alert the same commodity within this window while it stays low.
ALERT_COOLDOWN_SECONDS = 30 * 60  # 30 minutes

# API endpoints for Train Manager web client
BASE_URL = "https://trainmanager.cc"
LOGIN_URL = f"{BASE_URL}/weblogin/signin.php"
FUEL_URL = f"{BASE_URL}/fuel.php"
SPOT_URL = f"{BASE_URL}/fuel-spot.php?target=spot"

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
log = logging.getLogger("train")


# ============================================================
#  STATE PERSISTENCE
# ============================================================
DEFAULT_STATE: dict[str, Any] = {
    "fuel_alerted_ts": None,
    "spot_alerted_ts": None,
    "last_run_ts": None,
    "last_fuel_price": None,
    "last_spot_price": None,
    "last_message_id": None,
}


def load_state() -> dict:
    """Load persistent alert state, merging with defaults for forward-compat."""
    state = dict(DEFAULT_STATE)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
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
#  AUTH (Direct login to trainmanager.cc)
# ============================================================
def create_authenticated_session(retries: int = 3, delay: int = 5) -> Optional[requests.Session]:
    """Log in to trainmanager.cc and verify session cookies."""
    session = requests.Session()
    session.headers.update(HEADERS)

    login_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/",
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    payload = {"mail": TM_EMAIL, "pass": TM_PASSWORD, "remember": "1"}

    for attempt in range(1, retries + 1):
        try:
            res = session.post(LOGIN_URL, data=payload, headers=login_headers, timeout=15)
            body_lower = res.text.lower()

            log.debug(
                f"Login attempt {attempt}/{retries}: status={res.status_code} "
                f"cookies={dict(session.cookies)} body[:200]={res.text[:200]!r}"
            )

            # Hard-fail markers
            failure_markers = [
                "incorrect", "invalid", "wrong password", "login failed",
                "unauthorized", "error", "access denied",
            ]
            if any(m in body_lower for m in failure_markers) and "location" not in body_lower:
                log.error(f"Login attempt {attempt} rejected: {res.text[:300]!r}")
                time.sleep(delay)
                continue

            # Success criteria: 200/302 status + game cookies set
            if res.status_code in (200, 302) and session.cookies:
                cookie_names = {c.name.lower() for c in session.cookies}
                has_auth = any(
                    n in cookie_names
                    for n in ("trainmanager_cf_game", "phpsessid", "session", "auth")
                )
                if has_auth or "top.location" in body_lower:
                    log.info(f"Login OK (attempt {attempt}, cookies: {list(cookie_names)}).")
                    return session

            log.warning(f"Login attempt {attempt}: status={res.status_code}, cookies={dict(session.cookies)}")
        except requests.RequestException as e:
            log.error(f"Login attempt {attempt} network error: {e}")
        time.sleep(delay)

    log.error("All login attempts to trainmanager.cc failed.")
    return None


# ============================================================
#  PRICE EXTRACTION
# ============================================================
def fetch_live_train_prices(session: requests.Session, retries: int = 3, delay: int = 3) -> dict:
    """Fetch live Fuel and Spot prices directly from in-game pages."""
    result: dict[str, Any] = {}

    # 1. Fetch Fuel Page
    for attempt in range(1, retries + 1):
        try:
            r_fuel = session.get(FUEL_URL, timeout=15)
            if r_fuel.status_code == 200:
                # Primary regex: <span ...>$2,400/1,000 L</span>
                m_fuel = re.search(r'\$([\d,]+)\s*/\s*1,000\s*L', r_fuel.text, re.I)
                if not m_fuel:
                    m_fuel = re.search(r'var\s+fuelPrice\s*=\s*([\d\.]+);', r_fuel.text)
                    if m_fuel:
                        result["fuel"] = float(m_fuel.group(1)) * 1000
                else:
                    result["fuel"] = float(m_fuel.group(1).replace(",", ""))

                # Extract 20-slot chart history
                m_hist = re.search(r'fuel_startFuelChart\(\s*\[([0-9,\s]+)\]', r_fuel.text)
                if m_hist:
                    hist_vals = [int(x.strip()) for x in m_hist.group(1).split(",") if x.strip()]
                    result["fuel_history"] = hist_vals
                    result["fuel_min"] = min(hist_vals)
                    result["fuel_max"] = max(hist_vals)
                break
            log.warning(f"Fuel page HTTP {r_fuel.status_code} (attempt {attempt})")
        except requests.RequestException as e:
            log.error(f"Fuel fetch error (attempt {attempt}): {e}")
        time.sleep(delay)

    # 2. Fetch Spot Page
    for attempt in range(1, retries + 1):
        try:
            r_spot = session.get(SPOT_URL, timeout=15)
            if r_spot.status_code == 200:
                # Primary regex: <span ...>$800/1,000 kWh</span>
                m_spot = re.search(r'\$([\d,]+)\s*/\s*1,000\s*kWh', r_spot.text, re.I)
                if not m_spot:
                    m_spot = re.search(r'var\s+fuelPrice\s*=\s*([\d\.]+);', r_spot.text)
                    if m_spot:
                        result["spot"] = float(m_spot.group(1)) * 1000
                else:
                    result["spot"] = float(m_spot.group(1).replace(",", ""))

                # Extract 20-slot chart history
                m_spot_hist = re.search(r'fuel_startFuelChart\(\s*\[([0-9,\s]+)\]', r_spot.text)
                if m_spot_hist:
                    hist_vals = [int(x.strip()) for x in m_spot_hist.group(1).split(",") if x.strip()]
                    result["spot_history"] = hist_vals
                    result["spot_min"] = min(hist_vals)
                    result["spot_max"] = max(hist_vals)
                break
            log.warning(f"Spot page HTTP {r_spot.status_code} (attempt {attempt})")
        except requests.RequestException as e:
            log.error(f"Spot fetch error (attempt {attempt}): {e}")
        time.sleep(delay)

    return result


# ============================================================
#  COOLDOWN & EMERGENCY CHECKS
# ============================================================
def _within_cooldown(state: dict, key: str) -> bool:
    ts = state.get(f"{key}_alerted_ts")
    if not ts:
        return False
    return (time.time() - ts) < ALERT_COOLDOWN_SECONDS


def _fmt_price(val: Optional[float]) -> str:
    return f"${val:,.0f}" if val is not None else "N/A"


def check_emergency_conditions(prices: dict, state: dict, current_time_12h: str) -> tuple[dict, int]:
    """Evaluate Fuel & Spot thresholds and maintain 1 single message in #train-alerts.

    - If any item is newly triggered (<= threshold and outside 30-min cooldown):
      deletes old message & POSTs a fresh urgent red alert (buzzes phone).
    - Otherwise (normal prices, or active dip still inside cooldown):
      silently PATCHes the existing single message with the live values (no buzz).
    """
    fuel = prices.get("fuel")
    spot = prices.get("spot")

    fuel_min = prices.get("fuel_min", "N/A")
    fuel_max = prices.get("fuel_max", "N/A")
    spot_min = prices.get("spot_min", "N/A")
    spot_max = prices.get("spot_max", "N/A")

    fuel_str = _fmt_price(fuel)
    spot_str = _fmt_price(spot)

    log.info(
        f"Live In-Game Prices: "
        f"Fuel={fuel_str} (recent min=${fuel_min}, max=${fuel_max}), "
        f"Spot={spot_str} (recent min=${spot_min}, max=${spot_max})"
    )

    newly_triggered: list[str] = []
    in_cooldown: list[str] = []

    checks = [
        ("fuel", fuel, FUEL_BUY_THRESHOLD),
        ("spot", spot, SPOT_BUY_THRESHOLD),
    ]
    for key, val, threshold in checks:
        if val is None:
            continue
        if val <= threshold:
            if _within_cooldown(state, key):
                log.info(f"{key.title()}: triggered ({_fmt_price(val)}) but in 30-min cooldown. Skipping buzz.")
                in_cooldown.append(key)
            else:
                log.info(f"🚨 CRITICAL: {key.title()} price {_fmt_price(val)} <= ${threshold:,.0f} threshold!")
                newly_triggered.append(key)
        else:
            if state.get(f"{key}_alerted_ts") is not None:
                log.info(f"{key.title()} normalized ({_fmt_price(val)} > ${threshold:,.0f}). Resetting cooldown.")
                state[f"{key}_alerted_ts"] = None

    now_unix = int(time.time())
    fuel_in_range = fuel is not None and fuel <= FUEL_BUY_THRESHOLD
    spot_in_range = spot is not None and spot <= SPOT_BUY_THRESHOLD

    def _price_line(icon: str, label: str, val_str: str, threshold: float, in_range: bool, cooldown: bool = False) -> str:
        if in_range:
            suffix = " *(Cooldown)*" if cooldown else ""
            return f"  - {icon} {label}: **{val_str}** 🟩 **`BUY`**{suffix}"
        return f"  - {icon} {label}: **{val_str}** · `<= ${threshold:,.0f}`"

    alerts_sent = 0
    if newly_triggered:
        if set(newly_triggered) == {"fuel", "spot"}:
            title = f"🚨 BUY Fuel ({fuel_str}) & Spot ({spot_str})"
        elif "fuel" in newly_triggered:
            title = f"🚨 BUY Fuel ({fuel_str})"
        else:
            title = f"🚨 BUY Spot ({spot_str})"

        msg = "\n".join([
            "- **Live In-Game Prices**",
            _price_line("⛽", "Fuel", fuel_str, FUEL_BUY_THRESHOLD, fuel_in_range),
            _price_line("⚡", "Spot Power", spot_str, SPOT_BUY_THRESHOLD, spot_in_range),
            "- **Status**",
            f"  - 🕒 Checked <t:{now_unix}:R> ({current_time_12h} IST)",
        ])

        ok, new_id = upsert_to_discord(
            message=msg,
            title=title,
            priority="buy",
            message_id=state.get("last_message_id"),
            notify=True,
        )
        if ok:
            now_ts = time.time()
            for key in newly_triggered:
                state[f"{key}_alerted_ts"] = now_ts
            state["last_message_id"] = new_id
            alerts_sent = len(newly_triggered)
    elif in_cooldown:
        # Still inside buy range during cooldown -> keep green embed, update values silently (zero buzz)
        active_labels = " & ".join(k.title() for k in in_cooldown)
        title = f"🟢 Active Buy Zone • {active_labels}"
        msg = "\n".join([
            "- **Live In-Game Prices**",
            _price_line("⛽", "Fuel", fuel_str, FUEL_BUY_THRESHOLD, fuel_in_range, cooldown="fuel" in in_cooldown),
            _price_line("⚡", "Spot Power", spot_str, SPOT_BUY_THRESHOLD, spot_in_range, cooldown="spot" in in_cooldown),
            "- **Status**",
            f"  - 🕒 Checked <t:{now_unix}:R> ({current_time_12h} IST) · 30m cooldown",
        ])
        ok, new_id = upsert_to_discord(
            message=msg,
            title=title,
            priority="buy",
            message_id=state.get("last_message_id"),
            notify=False,
        )
        if ok and new_id:
            state["last_message_id"] = new_id
    else:
        # Outside buy range -> silently PATCH live status embed (zero buzz)
        title = "🚆 Train Manager • Live Prices"
        msg = "\n".join([
            "- **Live In-Game Prices**",
            _price_line("⛽", "Fuel", fuel_str, FUEL_BUY_THRESHOLD, False),
            _price_line("⚡", "Spot Power", spot_str, SPOT_BUY_THRESHOLD, False),
            "- **Status**",
            f"  - 🕒 Checked <t:{now_unix}:R> ({current_time_12h} IST) · Every 15m",
        ])
        ok, new_id = upsert_to_discord(
            message=msg,
            title=title,
            priority="default",
            message_id=state.get("last_message_id"),
            notify=False,
        )
        if ok and new_id:
            state["last_message_id"] = new_id

    # Record last prices
    state["last_fuel_price"] = fuel
    state["last_spot_price"] = spot
    state["last_run_ts"] = time.time()

    return state, alerts_sent


# ============================================================
#  SELF-TEST
# ============================================================
def send_test_notification() -> bool:
    """Send a test embed to Discord channel to verify webhook."""
    log.info("Sending TEST notification to Discord...")
    return send_to_discord(
        message=(
            "✅ **Train Manager Live Radar TEST**\n\n"
            "If you see this in Discord, your Train Manager live tracker is fully connected!\n\n"
            f"🎯 Active Thresholds:\n"
            f"• ⛽ Fuel: <= ${FUEL_BUY_THRESHOLD:,.0f} / 1,000 L\n"
            f"• ⚡ Spot: <= ${SPOT_BUY_THRESHOLD:,.0f} / 1,000 kWh\n\n"
            "Checks run 24/7 every 15 minutes straight from **trainmanager.cc**."
        ),
        title="Train Manager: Live Radar TEST",
        priority="default",
    )


# ============================================================
#  MAIN RUNNER
# ============================================================
def main() -> int:
    if "--test-notify" in sys.argv:
        ok = send_test_notification()
        return 0 if ok else 1

    if not ENABLED and "--force" not in sys.argv:
        log.info("Train alerts are DISABLED (ENABLED=False). Exiting.")
        return 0

    if not TM_EMAIL or not TM_PASSWORD:
        log.error("TM_EMAIL or TM_PASSWORD is empty. Set env vars.")
        return 2

    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    state = load_state()

    log.info("=" * 60)
    log.info(" 🚆 Train Manager 24/7 Live Radar - abhijaysinghlimited")
    log.info(f" Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    log.info(f" Thresholds: Fuel <= ${FUEL_BUY_THRESHOLD:,.0f} | Spot <= ${SPOT_BUY_THRESHOLD:,.0f}")
    log.info("=" * 60)

    # 1. Login to trainmanager.cc
    log.info(f"Logging in to {BASE_URL} as {TM_EMAIL}...")
    session = create_authenticated_session()
    if not session:
        log.error("Login to trainmanager.cc failed.")
        ok, new_id = upsert_to_discord(
            message=(
                "⚠️ Train Manager notifier could NOT log in to trainmanager.cc.\n\n"
                f"Account: `{TM_EMAIL}`\n"
                "Please verify your email and password."
            ),
            title="Train Manager: LOGIN FAILED",
            priority="high",
            message_id=state.get("last_message_id"),
            notify=True,
        )
        if ok and new_id:
            state["last_message_id"] = new_id
            save_state(state)
        return 3

    # 2. Fetch live in-game prices
    log.info("Fetching real in-game prices from fuel.php & fuel-spot.php...")
    prices = fetch_live_train_prices(session)
    if "fuel" not in prices and "spot" not in prices:
        log.error("Could not parse fuel or spot prices from trainmanager.cc.")
        ok, new_id = upsert_to_discord(
            message=(
                "⚠️ Train Manager could not read fuel/spot prices from trainmanager.cc.\n"
                "Game layout may have changed."
            ),
            title="Train Manager: PARSE ERROR",
            priority="high",
            message_id=state.get("last_message_id"),
            notify=True,
        )
        if ok and new_id:
            state["last_message_id"] = new_id
            save_state(state)
        return 4

    # 3. Check thresholds & sync single Discord message
    state, alerts_sent = check_emergency_conditions(prices, state, current_time_12h)
    save_state(state)

    if alerts_sent == 0:
        log.info("No new alerts needed; status message updated silently.")

    log.info(f"Run complete. Alerts fired: {alerts_sent}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
