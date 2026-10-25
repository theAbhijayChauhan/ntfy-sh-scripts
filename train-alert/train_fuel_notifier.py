"""
============================================================
 🚆 Train Manager - Daily Fuel & Spot Price Tracker
 🏢 Company: abhijaysinghlimited
 🎯 Source: https://mgtools.cloud/games/train
 🎯 API:    https://api.mgtools.cloud/v1/fuel-price/train
 🔔 Discord Webhook (via discord_notifier.py)
============================================================

Architecture
------------
This script is run ONCE per day (cron 06:00–07:00 IST, retries
every 10 min until success). It does three things:

  1. Fetch today's 24-slot fuel/spot schedule from mgtools API.
  2. Send a morning briefing to Discord (immediate webhook)
     listing the top-4 cheapest fuel + top-4 cheapest spot times.
  3. Write scheduled_alerts.json with the 8 future-time alerts.

A SEPARATE workflow (`train_alert_poll.yml`) polls every 5 min,
loads scheduled_alerts.json, and fires a Discord webhook at the
exact scheduled minute of each cheapest-price slot. This is the
"Option B: poll-and-fire" pattern — fully free on GitHub Actions,
no bot account, no scheduled-delivery server needed.

Usage
-----
  python train_fuel_notifier.py                 # normal daily run
  python train_fuel_notifier.py --force         # re-run even if done today
  python train_fuel_notifier.py --debug         # verbose logging
  python train_fuel_notifier.py --test-notify   # test Discord webhook
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
# (whether it lives in this folder or one level up at repo root).
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
NTFY_TOPIC = "abhijaysinghlimited-train-fuel-alert"  # kept for backward-compat
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

STATE_FILE = os.path.join(HERE, "train_state.json")
SCHEDULED_ALERTS_FILE = os.path.join(HERE, "scheduled_alerts.json")
LOG_FILE = os.path.join(HERE, "train_notifier.log")

API_URL = "https://api.mgtools.cloud/v1/fuel-price/train"
API_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Briefing window (24h IST). The morning briefing is sent inside
# this window. Outside the window, only scheduling runs. --force
# or --briefing bypass.
BRIEFING_START = (6, 0)   # 06:00
BRIEFING_END = (7, 0)     # 07:00

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
    "last_processed_date": None,
    "last_run_status": None,
    "last_scheduled_fuel": 0,
    "last_scheduled_spot": 0,
    "last_skipped_past": 0,
}


def load_state() -> dict:
    state = dict(DEFAULT_STATE)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state.update(json.load(f))
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
#  SCHEDULED-ALERTS FILE (for the poll-and-fire workflow)
# ============================================================
def write_scheduled_alerts(top_4_fuel: list, top_4_spot: list, now: datetime.datetime) -> None:
    """Write the 8 future-time alerts to scheduled_alerts.json.

    The poll-and-fire workflow reads this file every 5 minutes and
    fires a Discord webhook when now >= scheduled_ts for any unfired
    alert. We mark alerts whose time has already passed as `fired=True`
    so the poller skips them.
    """
    today_str = now.strftime("%Y-%m-%d")
    now_ts = int(now.timestamp())

    alerts: list[dict] = []

    medals = ["🥇 #1 Lowest Today!", "🥈 #2 Lowest Today!", "🥉 #3 Lowest Today!", "4️⃣ #4 Lowest Today!"]
    for rank, item in enumerate(top_4_fuel, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        if slot_dt is None:
            continue
        slot_ts = int(slot_dt.timestamp())
        alerts.append({
            "id": f"fuel-{rank}",
            "type": "fuel",
            "rank": rank,
            "time_24h": clean_time(item["time"]),
            "time_12h": to_12h(item["time"]),
            "scheduled_ts": slot_ts,
            "price": item["fuel"],
            "other_price": item["spot"],
            "medal": medals[rank - 1] if rank <= len(medals) else f"#{rank}",
            "fired": slot_ts <= now_ts,  # auto-mark past slots as fired
            "fired_ts": slot_ts if slot_ts <= now_ts else None,
        })

    for rank, item in enumerate(top_4_spot, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        if slot_dt is None:
            continue
        slot_ts = int(slot_dt.timestamp())
        alerts.append({
            "id": f"spot-{rank}",
            "type": "spot",
            "rank": rank,
            "time_24h": clean_time(item["time"]),
            "time_12h": to_12h(item["time"]),
            "scheduled_ts": slot_ts,
            "price": item["spot"],
            "other_price": item["fuel"],
            "medal": medals[rank - 1] if rank <= len(medals) else f"#{rank}",
            "fired": slot_ts <= now_ts,
            "fired_ts": slot_ts if slot_ts <= now_ts else None,
        })

    state = {
        "date": today_str,
        "generated_at": now_ts,
        "alert_count": len(alerts),
        "alerts": alerts,
    }

    tmp = SCHEDULED_ALERTS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, SCHEDULED_ALERTS_FILE)
        log.info(f"Wrote {len(alerts)} scheduled alerts to {SCHEDULED_ALERTS_FILE}")
    except Exception as e:
        log.error(f"Could not write scheduled alerts: {e}")


# ============================================================
#  TIME HELPERS
# ============================================================
def in_briefing_window(now: datetime.datetime) -> bool:
    mins = now.hour * 60 + now.minute
    start = BRIEFING_START[0] * 60 + BRIEFING_START[1]
    end = BRIEFING_END[0] * 60 + BRIEFING_END[1]
    return start <= mins <= end


def clean_time(time_str: str) -> str:
    return (time_str or "").replace("->", "").strip()


def to_12h(time_str: str) -> str:
    is_current = "->" in (time_str or "")
    cleaned = clean_time(time_str)
    if ":" in cleaned:
        parts = cleaned.split(":")
        hh = parts[0].zfill(2)
        mm = parts[1].zfill(2)
        cleaned = f"{hh}:{mm}"
    try:
        dt = datetime.datetime.strptime(cleaned, "%H:%M")
    except ValueError as e:
        log.warning(f"Could not parse time {time_str!r}: {e}; falling back to raw.")
        return cleaned
    formatted = dt.strftime("%I:%M %p")
    return f"{formatted} ⚡[NOW]" if is_current else formatted


def get_slot_datetime(time_str: str, now: datetime.datetime) -> Optional[datetime.datetime]:
    cleaned = clean_time(time_str)
    if ":" not in cleaned:
        return None
    try:
        hh, mm = cleaned.split(":")[0], cleaned.split(":")[1]
        return now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except (ValueError, IndexError) as e:
        log.warning(f"Bad slot time {time_str!r}: {e}")
        return None


def _to_number(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        cleaned = v.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _fmt_money(v: Any) -> str:
    n = _to_number(v)
    if n is None:
        return "N/A"
    return f"${n:,.0f}"


# ============================================================
#  API
# ============================================================
def fetch_train_prices(timezone_name: str = TIMEZONE_NAME, retries: int = 5, delay: int = 5) -> list:
    payload = {"timezone": timezone_name}
    last_err: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(API_URL, json=payload, headers=API_HEADERS, timeout=15)
            log.debug(
                f"Fetch attempt {attempt}/{retries}: status={response.status_code} "
                f"body[:300]={response.text[:300]!r}"
            )
            response.raise_for_status()
            result = response.json()

            if isinstance(result, list):
                data = result
            elif isinstance(result, dict):
                data = result.get("data") or result.get("schedule") or result.get("slots") or []
            else:
                data = []

            if data:
                return data
            log.warning(f"Fetch attempt {attempt}: empty data array.")
        except requests.RequestException as e:
            last_err = e
            log.error(f"Fetch attempt {attempt}/{retries} network error: {e}")
        except ValueError as e:
            last_err = e
            log.error(f"Fetch attempt {attempt}/{retries} JSON parse error: {e}")
        time.sleep(delay)

    if last_err:
        raise last_err
    return []


def normalize_slots(raw_slots: list) -> list[dict]:
    out: list[dict] = []
    for raw in raw_slots:
        if not isinstance(raw, dict):
            continue
        fuel = _to_number(raw.get("fuel"))
        spot = _to_number(raw.get("spot"))
        time_str = raw.get("time") or raw.get("slot") or raw.get("hour")
        day = raw.get("day")
        if time_str is None or (fuel is None and spot is None):
            log.debug(f"Skipping slot (missing fields): {raw}")
            continue
        out.append({
            "time": str(time_str),
            "fuel": fuel,
            "spot": spot,
            "day": str(day) if day is not None else None,
        })
    return out


# ============================================================
#  DISCORD HELPERS
# ============================================================
def send_test_notification() -> bool:
    log.info("Sending TEST notification to Discord webhook...")
    return send_to_discord(
        message=(
            "✅ **Test from Train Manager notifier.**\n\n"
            "If you see this in Discord, your webhook + script work.\n\n"
            "Scheduled price-time alerts will appear in RED when their "
            "minute arrives (handled by the poll-and-fire workflow)."
        ),
        title="Train Manager: TEST",
        priority="default",
    )


# ============================================================
#  BRIEFING
# ============================================================
def build_morning_briefing(top_4_fuel: list, top_4_spot: list, now: datetime.datetime) -> str:
    date_str = now.strftime("%A, %d %B %Y")
    current_time_12h = now.strftime("%I:%M %p")
    medals = ["🥇", "🥈", "🥉", "4️⃣"]
    badges_fuel = ["🟢 BEST DEAL", "⭐ GREAT PRICE", "💰 LOW DROP", "📉 GOOD TIME"]
    badges_spot = ["🟢 BEST SPOT", "⭐ GREAT RATE", "⚡ LOW PEAK", "📉 GOOD SPOT"]

    lines = [
        "🚆 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚆",
        "       TRAIN MANAGER • DAILY BRIEFING",
        "             abhijaysinghlimited",
        "🚆 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚆",
        f"📅 **Date:** {date_str} | ⏰ **Time:** {current_time_12h} IST",
        "🎯 **Radar:** 24-Hour Automated Price Forecaster",
        "",
        "⛽ ━━━ 🏆 TOP 4 LOWEST FUEL DROPS ━━━ ⛽",
    ]

    for i, item in enumerate(top_4_fuel):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        b = badges_fuel[i] if i < len(badges_fuel) else "🏷️ DISCOUNT"
        lines.append(
            f"{m} **{to_12h(item['time'])}** ➜ **{_fmt_money(item['fuel'])}** "
            f"*(Spot: {_fmt_money(item['spot'])})* {b}"
        )

    lines.append("")
    lines.append("⚡ ━━━ ⚡ TOP 4 LOWEST SPOT DROPS ━━━ ⚡")
    for i, item in enumerate(top_4_spot):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        b = badges_spot[i] if i < len(badges_spot) else "🏷️ DISCOUNT"
        lines.append(
            f"{m} **{to_12h(item['time'])}** ➜ **{_fmt_money(item['spot'])}** "
            f"*(Fuel: {_fmt_money(item['fuel'])})* {b}"
        )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔔 **AUTO-ALERTS QUEUED:**")
    lines.append("📱 The poll-and-fire workflow will buzz this channel at the exact minute of each cheapest slot above!")
    lines.append("🎮 *Open Train Manager when the red alert lands!*")
    return "\n".join(lines)


# ============================================================
#  MAIN
# ============================================================
def main() -> int:
    # --- Special: self-test ---
    if "--test-notify" in sys.argv:
        ok = send_test_notification()
        return 0 if ok else 1

    if not ENABLED and "--force" not in sys.argv:
        log.info("Train alerts are DISABLED (ENABLED=False). Exiting.")
        return 0

    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    today_str = now.strftime("%Y-%m-%d")
    today_day_str = str(now.day)

    state = load_state()

    # --- Deduplication check ---
    if state.get("last_processed_date") == today_str and "--force" not in sys.argv:
        log.info(
            f"Train Manager for today ({today_str}) already processed. Skipping. (Use --force.)"
        )
        return 0

    send_briefing = (
        "--force" in sys.argv
        or "--briefing" in sys.argv
        or in_briefing_window(now)
    )

    log.info("=" * 60)
    log.info(" 🚆 Train Manager Notifier - abhijaysinghlimited")
    log.info(f" Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    log.info(f" Mode : {'Briefing + Scheduler' if send_briefing else 'Scheduler only'}")
    log.info("=" * 60)

    # --- Fetch schedule ---
    log.info(f"Fetching schedule from {API_URL} ...")
    try:
        raw_slots = fetch_train_prices(TIMEZONE_NAME)
    except Exception as e:
        log.error(f"Failed to fetch schedule: {e}")
        send_to_discord(
            message=(
                "⚠️ Train Manager notifier could NOT fetch the daily schedule.\n\n"
                f"Error: `{e!s}`\n\n"
                "Likely causes:\n"
                "• mgtools.cloud API is down or under maintenance\n"
                "• Network / DNS problem\n"
                "• API response shape changed (run with --debug)\n\n"
                "No alerts were scheduled for today."
            ),
            title="Train Manager: API FETCH FAILED",
            priority="high",
        )
        return 3

    log.info(f"Fetched {len(raw_slots)} raw slots.")
    if not raw_slots:
        log.error("API returned zero slots. Notifying & exiting.")
        send_to_discord(
            message=(
                "⚠️ Train Manager API returned an empty schedule for today.\n"
                "Either mgtools.cloud is broken or the API contract changed.\n"
                "Run with --debug and inspect train_notifier.log."
            ),
            title="Train Manager: EMPTY SCHEDULE",
            priority="high",
        )
        return 4

    all_slots = normalize_slots(raw_slots)
    today_slots = [s for s in all_slots if s.get("day") == today_day_str]
    if not today_slots:
        today_slots = all_slots
        log.warning("No `day` field matched today; using all returned slots.")
    log.info(f"Working with {len(today_slots)} slots for today.")

    by_fuel = sorted(
        today_slots,
        key=lambda x: (
            x["fuel"] if x["fuel"] is not None else float("inf"),
            clean_time(x["time"]),
        ),
    )
    by_spot = sorted(
        today_slots,
        key=lambda x: (
            x["spot"] if x["spot"] is not None else float("inf"),
            clean_time(x["time"]),
        ),
    )
    top_4_fuel = by_fuel[:4]
    top_4_spot = by_spot[:4]

    # --- Morning briefing ---
    if send_briefing:
        briefing_msg = build_morning_briefing(top_4_fuel, top_4_spot, now)
        log.info("Sending morning briefing to Discord...")
        briefing_sent = send_to_discord(
            message=briefing_msg,
            title=f"Train Manager: Daily Fuel & Spot Briefing ({current_time_12h})",
            priority="default",
        )
        if not briefing_sent:
            log.warning("Briefing failed to send — continuing to scheduling anyway.")
    else:
        log.info(f"Outside briefing window. Skipping briefing.")

    # --- Write scheduled_alerts.json (the poll-and-fire workflow reads this) ---
    write_scheduled_alerts(top_4_fuel, top_4_spot, now)

    # --- Save state AFTER everything (so a crash doesn't lose work) ---
    state["last_processed_date"] = today_str
    state["last_run_status"] = "ok"
    state["last_scheduled_fuel"] = len(top_4_fuel)
    state["last_scheduled_spot"] = len(top_4_spot)
    save_state(state)

    log.info("Run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
