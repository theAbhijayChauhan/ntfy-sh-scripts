"""
============================================================
 ⚡ Energy Manager - 24/7 Live Market Tracker & Emergency Alerts
 🏢 Company: abhijaysinghlimited
 🎯 Source: https://energymanagergame.com/ (Official Game Web Client)
 🔔 Discord Webhook (via discord_notifier.py → #energy-alerts channel)
============================================================

✨ Features
1. ENABLED switch   — set ENABLED = False to mute everything.
2. 24/7 Live Radar  — runs every hour at :30 (e.g. 7:30, 8:30, 9:30...).
3. Timing Safety    — if triggered at :28 or :29, waits until :30:05 before fetching
   so it never checks old prices before the game refreshes.
4. No Cooldown      — notifies EVERY time any commodity is in target range:
     • Oil       <  $2.00   →  BUY OIL QUICKLY
     • Coal      <  $1.50   →  BUY COAL QUICKLY
     • Hydrogen  >  $99.00  →  SELL HYDROGEN QUICKLY
     • CO2       <= $15.00  →  BUY CO2 QUICKLY
5. Single Message   — maintains 1 message in #energy-alerts:
     • Normal prices → silently edits (PATCH) the message with latest prices (no buzz)
     • In-range      → deletes old message & posts new urgent alert (buzzes phone)
6. Diagnostic mode  — run with --debug to print full HTTP bodies to log file.

Usage
-----
  python energy_fuel_notifier.py                # normal hourly radar check
  python energy_fuel_notifier.py --test-notify # send a test push to Discord
  python energy_fuel_notifier.py --debug       # verbose logging
  python energy_fuel_notifier.py --force       # run even if ENABLED=False
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

# Add the script's own dir and repo root to path
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

# --- Strict Emergency Thresholds (NO COOLDOWN: alerts every time in range) ---
OIL_BUY_THRESHOLD = 2.00          # Alert when Oil < $2.00
COAL_BUY_THRESHOLD = 1.50         # Alert when Coal < $1.50
HYDROGEN_SELL_THRESHOLD = 99.00   # Alert when Hydrogen > $99.00
CO2_BUY_THRESHOLD = 15.00         # Alert when CO2 <= $15.00

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
    "last_message_id": None,
}


def load_state() -> dict:
    """Load persistent state, merging with defaults."""
    state = dict(DEFAULT_STATE)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in state:
                    if k in data:
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
#  NOTIFICATIONS & SINGLE-MESSAGE SYNC
# ============================================================
def send_test_notification() -> bool:
    log.info("Sending TEST notification to Discord #energy-alerts webhook...")
    return send_to_discord(
        message=(
            "✅ **Test from Energy Manager 24/7 Live Radar.**\n\n"
            "If you see this in your #energy-alerts channel, your Energy "
            "webhook + script work.\n\n"
            "Thresholds active (no cooldown — alerts every time in range):\n"
            f"• Oil < ${OIL_BUY_THRESHOLD:.2f}\n"
            f"• Coal < ${COAL_BUY_THRESHOLD:.2f}\n"
            f"• Hydrogen > ${HYDROGEN_SELL_THRESHOLD:.2f}\n"
            f"• CO2 <= ${CO2_BUY_THRESHOLD:.2f}"
        ),
        title="Energy Manager: TEST",
        priority="default",
    )


COMMODITY_SPECS = [
    ("oil",      "Oil",      OIL_BUY_THRESHOLD,       "<",  "BUY",  "🛢️"),
    ("coal",     "Coal",     COAL_BUY_THRESHOLD,      "<",  "BUY",  "🪨"),
    ("hydrogen", "Hydrogen", HYDROGEN_SELL_THRESHOLD, ">",  "SELL", "💧"),
    ("co2",      "CO2",      CO2_BUY_THRESHOLD,       "<=", "BUY",  "🍃"),
]


def _matches_target(price: float, op: str, threshold: float) -> bool:
    if op == "<":
        return price < threshold
    if op == "<=":
        return price <= threshold
    if op == ">":
        return price > threshold
    if op == ">=":
        return price >= threshold
    raise ValueError(f"Unsupported operator: {op}")


def _format_commodity_line(
    key: str,
    label: str,
    threshold: float,
    op: str,
    action: str,
    emoji: str,
    price: float,
    is_hit: bool,
) -> str:
    if is_hit:
        badge = "✨ **`BUY NOW`**" if action == "BUY" else "🔥 **`SELL NOW`**"
        return f"  - {emoji} **{label}:** **`${price:.2f}`** {badge}"
    return f"  - {emoji} {label}: **${price:.2f}** · `{op} ${threshold:.2f}`"


def _build_clean_sections(market: dict, triggered_keys: set[str]) -> list[str]:
    by_key = {}
    for key, label, threshold, op, action, emoji in COMMODITY_SPECS:
        if key not in market:
            continue
        price = market[key]["current"]
        by_key[key] = _format_commodity_line(
            key, label, threshold, op, action, emoji, price, key in triggered_keys
        )

    lines: list[str] = []
    if "hydrogen" in by_key:
        lines.append("- **Selling Prices**")
        lines.append(by_key["hydrogen"])

    fuel_keys = [k for k in ("oil", "coal", "co2") if k in by_key]
    if fuel_keys:
        lines.append("- **Fuel & Quota Prices**")
        for k in fuel_keys:
            lines.append(by_key[k])
    return lines


def sync_energy_message(market: dict, state: dict, current_time_12h: str) -> tuple[dict, int]:
    """Update the single Discord message in #energy-alerts.

    - If any commodity is in target range (NO cooldown): deletes old message and
      POSTs a fresh @everyone glowing alert (green BUY / red SELL) so your phone buzzes every time.
    - If all commodities are normal: silently PATCHes the single message with
      clean live prices (zero push notification).
    """
    triggered = []
    for key, label, threshold, op, action, emoji in COMMODITY_SPECS:
        if key not in market:
            continue
        price = market[key]["current"]
        if _matches_target(price, op, threshold):
            triggered.append((key, label, threshold, op, action, emoji, price))

    triggered_keys = {t[0] for t in triggered}
    body_lines = _build_clean_sections(market, triggered_keys)
    now_unix = int(time.time())

    if triggered:
        if len(triggered) == 1:
            _, label, _, _, action, _, price = triggered[0]
            summary = f"{action} {label.upper()} NOW • ${price:.2f}"
        else:
            summary = " & ".join(f"{t[4]} {t[1]} (${t[6]:.2f})" for t in triggered)

        title = f"⚡ {summary}"
        ping_content = f"@everyone 🚨 **{summary}** — open Energy Manager!"

        diff_lines = []
        for _, label, threshold, op, action, _, price in triggered:
            prefix = "+" if action == "BUY" else "-"
            diff_lines.append(
                f"{prefix} >>> {action} {label.upper()} NOW: ${price:.2f} (Target {op} ${threshold:.2f}) <<<"
            )
        banner = "```diff\n" + "\n".join(diff_lines) + "\n```"

        has_sell = any(t[4] == "SELL" for t in triggered)
        priority = "sell" if has_sell else "buy"

        msg = "\n".join(
            [
                banner,
                "> 🔥 **Market target hit — open Energy Manager and act now!**",
                "",
            ]
            + body_lines
            + [
                "- **Status**",
                f"  - 🕒 Checked <t:{now_unix}:R> ({current_time_12h} IST)",
            ]
        )
        ok, new_id = upsert_to_discord(
            message=msg,
            title=title,
            priority=priority,
            message_id=state.get("last_message_id"),
            notify=True,
            content=ping_content,
        )
        if ok:
            state["last_message_id"] = new_id
            return state, len(triggered)
        return state, 0

    # All commodities outside range -> silently PATCH live status (zero buzz)
    title = f"⚡ Energy Manager • Live Prices"
    msg = "\n".join(
        body_lines
        + [
            "- **Status**",
            f"  - 🕒 Checked <t:{now_unix}:R> ({current_time_12h} IST) · Hourly at `:30`",
        ]
    )
    ok, new_id = upsert_to_discord(
        message=msg,
        title=title,
        priority="default",
        message_id=state.get("last_message_id"),
        notify=False,
    )
    if ok and new_id:
        state["last_message_id"] = new_id

    return state, 0


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
    state = load_state()

    log.info("=" * 60)
    log.info(" ⚡ Energy Manager 24/7 Live Tracker - abhijaysinghlimited")
    log.info(f" Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    log.info(" Mode : Single-Message Live Status + Alerts (NO Cooldown)")
    log.info(f" Targets: Oil < ${OIL_BUY_THRESHOLD:.2f} | Coal < ${COAL_BUY_THRESHOLD:.2f}")
    log.info(f"          Hydrogen > ${HYDROGEN_SELL_THRESHOLD:.2f} | CO2 <= ${CO2_BUY_THRESHOLD:.2f}")
    log.info("=" * 60)

    # 1. Login
    log.info("Logging in to energymanagergame.com...")
    session = create_authenticated_session()
    if not session:
        log.error("Login failed.")
        ok, new_id = upsert_to_discord(
            message=(
                "⚠️ Energy Manager notifier could NOT log in.\n\n"
                f"Account: `{EM_EMAIL}`\n"
                "Please verify your credentials."
            ),
            title="Energy Manager: LOGIN FAILED",
            priority="high",
            message_id=state.get("last_message_id"),
            notify=True,
        )
        if ok and new_id:
            state["last_message_id"] = new_id
            save_state(state)
        return 3

    # 2. Fetch live prices
    log.info("Fetching live commodity prices...")
    market = fetch_live_commodity_prices(session)
    if not market:
        log.error("No market data retrieved.")
        ok, new_id = upsert_to_discord(
            message="⚠️ Energy Manager notifier could not fetch live market prices.",
            title="Energy Manager: NO MARKET DATA",
            priority="high",
            message_id=state.get("last_message_id"),
            notify=True,
        )
        if ok and new_id:
            state["last_message_id"] = new_id
            save_state(state)
        return 4

    # 3. Single-message update / alert (NO cooldown)
    state, alerts_sent = sync_energy_message(market, state, current_time_12h)
    save_state(state)

    if alerts_sent == 0:
        log.info("All commodities outside target range. Status message updated silently.")

    log.info(f"Run complete. Triggered items notified: {alerts_sent}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
