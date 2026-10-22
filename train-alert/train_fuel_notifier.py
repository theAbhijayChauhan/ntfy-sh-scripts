"""
============================================================
 🚆 Train Manager - Daily Fuel & Spot Price Tracker + Scheduler
 🏢 Company: abhijaysinghlimited
 🎯 Source: https://mgtools.cloud/games/train
 🎯 API:    https://api.mgtools.cloud/v1/fuel-price/train
 🔔 ntfy Topic: abhijaysinghlimited-train-fuel-alert
============================================================

✨ Features
1. ENABLED switch — set ENABLED = False to mute everything.
2. Daily run (one shot): fetch the 24-hour schedule, pick the 4 lowest Fuel
   and 4 lowest Spot price slots, send a morning briefing, and schedule 8
   exact-time push notifications via ntfy.sh's `At` header so the alert
   buzzes your phone at the minute the price is lowest.
3. Strict dedup — once today's run completes successfully, it never re-runs
   the same day (state file). Use `--force` to override.
4. Self-test mode — `--test-notify` sends a test push to verify ntfy.sh.
5. Diagnostic mode — `--debug` writes full HTTP bodies to the log file.
6. Graceful failures — if the API is unreachable or returns junk, you get
   a `FAILURE` push notification instead of a silent crash.

Usage
-----
  python train_fuel_notifier.py                # normal daily run
  python train_fuel_notifier.py --force        # re-run even if already done today
  python train_fuel_notifier.py --test-notify  # send a test push to ntfy
  python train_fuel_notifier.py --debug        # verbose logging
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
NTFY_TOPIC = "abhijaysinghlimited-train-fuel-alert"
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "train_state.json")
LOG_FILE = os.path.join(HERE, "train_notifier.log")

API_URL = "https://api.mgtools.cloud/v1/fuel-price/train"
API_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Briefing window (24h IST). The morning briefing is only sent inside this
# window. Outside the window, the script still schedules alerts for any
# remaining future slots, but skips the briefing. Use --force or --briefing
# to bypass.
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
    "last_run_status": None,            # "ok" | "partial" | "failed"
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
#  TIME HELPERS
# ============================================================
def in_briefing_window(now: datetime.datetime) -> bool:
    mins = now.hour * 60 + now.minute
    start = BRIEFING_START[0] * 60 + BRIEFING_START[1]
    end = BRIEFING_END[0] * 60 + BRIEFING_END[1]
    return start <= mins <= end


def clean_time(time_str: str) -> str:
    """Strip the '->' prefix that marks the current slot."""
    return (time_str or "").replace("->", "").strip()


def to_12h(time_str: str) -> str:
    """Convert 'HH:MM' (optionally '-> HH:MM') to 12-hour 'hh:mm AM/PM'."""
    is_current = "->" in (time_str or "")
    cleaned = clean_time(time_str)
    # Be tolerant of "21:30:00" and "21:30:00.000" too.
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
    """Timezone-aware datetime for a HH:MM slot today; None on parse failure."""
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
    """Coerce to float; return None if impossible."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        # Strip "$", commas, whitespace.
        cleaned = v.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _fmt_money(v: Any) -> str:
    """Format a number with thousands separator; gracefully handle non-numbers."""
    n = _to_number(v)
    if n is None:
        return "N/A"
    return f"${n:,.0f}"


# ============================================================
#  API
# ============================================================
def fetch_train_prices(timezone_name: str = TIMEZONE_NAME, retries: int = 5, delay: int = 5) -> list:
    """Fetch the 24-hour fuel & spot schedule with retries."""
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

            # Be tolerant about response shape: {data: [...]} vs just [...]
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
    """Defensive normalization: ensure every slot has numeric `fuel`, `spot`, `time`, `day`."""
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
#  NOTIFICATIONS
# ============================================================
def send_to_ntfy(
    topic: str,
    message: str,
    title: str,
    tags: str = "train,fuelpump",
    priority: str = "default",
    at_timestamp: Optional[int] = None,
) -> bool:
    """Send (or schedule) a push notification via ntfy.sh.

    If `at_timestamp` (Unix epoch seconds) is in the future, ntfy.sh will
    hold the message server-side until that exact moment.
    """
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Markdown": "yes",
    }
    if at_timestamp:
        headers["At"] = str(at_timestamp)

    try:
        response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=15)
        if response.status_code == 200:
            label = f" (scheduled for {datetime.datetime.fromtimestamp(at_timestamp, LOCAL_TZ).strftime('%I:%M %p')})" if at_timestamp else ""
            log.info(f"ntfy OK → {title}{label}")
            return True
        log.error(f"ntfy FAIL: HTTP {response.status_code}: {response.text[:200]}")
        return False
    except requests.RequestException as e:
        log.error(f"ntfy network error: {e}")
        return False


def send_test_notification() -> bool:
    log.info(f"Sending TEST notification to ntfy.sh/{NTFY_TOPIC} ...")
    return send_to_ntfy(
        NTFY_TOPIC,
        (
            "✅ **Test notification from Train Manager notifier.**\n\n"
            "If you see this on your phone, your ntfy topic is configured "
            "correctly and the script can reach ntfy.sh.\n\n"
            "Subscribe to this topic in the ntfy mobile app:\n"
            f"`{NTFY_TOPIC}`"
        ),
        title="Train Manager: TEST",
        tags="white_check_mark,test_tube,train",
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
    lines.append("🔔 **AUTO-ALERTS SCHEDULED:**")
    lines.append("📱 You'll receive **4 Fuel + 4 Spot** live push alerts at the exact minutes above!")
    lines.append("🎮 *Open Train Manager when the alert buzzes to maximize profit!*")
    return "\n".join(lines)


# ============================================================
#  ALERT SCHEDULER
# ============================================================
def schedule_alerts(top_4_fuel: list, top_4_spot: list, now: datetime.datetime) -> tuple[int, int, int]:
    """Schedule exact-time pushes via ntfy.sh `At` header.

    Returns (fuel_scheduled, spot_scheduled, skipped_past) so the caller can
    report partial failures.
    """
    now_ts = int(now.timestamp())
    medals = ["🥇 #1 Lowest Today!", "🥈 #2 Lowest Today!", "🥉 #3 Lowest Today!", "4️⃣ #4 Lowest Today!"]
    fuel_scheduled = 0
    spot_scheduled = 0
    skipped_past = 0

    def _medal(rank: int) -> str:
        return medals[rank - 1] if 1 <= rank <= len(medals) else f"#{rank} Rank"

    log.info("Scheduling alerts for Top 4 lowest Fuel drops...")
    for rank, item in enumerate(top_4_fuel, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        if slot_dt is None:
            log.warning(f"Fuel #{rank}: couldn't parse time {item['time']!r}. Skipping.")
            skipped_past += 1
            continue
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])

        if slot_ts <= now_ts:
            log.info(f"Fuel #{rank}: slot {time_12h} already passed today. Skipping.")
            skipped_past += 1
            continue

        medal_label = _medal(rank)
        alert_msg = (
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"       ⛔ BUY FUEL QUICKLY • CHEAPEST NOW!\n"
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"⏰ **Exact Time:** {time_12h} [RIGHT NOW]\n"
            f"💰 **Fuel Price:** **{_fmt_money(item['fuel'])}** ({medal_label})\n"
            f"⚡ **Spot Price:** {_fmt_money(item['spot'])}\n"
            f"🏢 **Company:** abhijaysinghlimited\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
            f"Fuel price has hit its rock-bottom window!\n"
            f"👉 Open **Train Manager** right now and stock up your train tanks!"
        )
        title = f"BUY FUEL QUICKLY: {_fmt_money(item['fuel'])} at {time_12h}"
        if send_to_ntfy(
            topic=NTFY_TOPIC,
            message=alert_msg,
            title=title,
            tags="fuelpump,rotating_light,money_with_wings",
            priority="urgent",
            at_timestamp=slot_ts,
        ):
            fuel_scheduled += 1

    log.info("Scheduling alerts for Top 4 lowest Spot drops...")
    for rank, item in enumerate(top_4_spot, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        if slot_dt is None:
            log.warning(f"Spot #{rank}: couldn't parse time {item['time']!r}. Skipping.")
            skipped_past += 1
            continue
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])

        if slot_ts <= now_ts:
            log.info(f"Spot #{rank}: slot {time_12h} already passed today. Skipping.")
            skipped_past += 1
            continue

        medal_label = _medal(rank)
        alert_msg = (
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"       ⚡ BUY SPOT POWER QUICKLY!\n"
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"⏰ **Exact Time:** {time_12h} [RIGHT NOW]\n"
            f"⚡ **Spot Price:** **{_fmt_money(item['spot'])}** ({medal_label})\n"
            f"⛽ **Fuel Price:** {_fmt_money(item['fuel'])}\n"
            f"🏢 **Company:** abhijaysinghlimited\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
            f"Spot electricity is at its cheapest rate today!\n"
            f"👉 Open **Train Manager** right now and buy spot power!"
        )
        title = f"BUY SPOT QUICKLY: {_fmt_money(item['spot'])} at {time_12h}"
        if send_to_ntfy(
            topic=NTFY_TOPIC,
            message=alert_msg,
            title=title,
            tags="zap,rotating_light,chart_with_downwards_trend",
            priority="urgent",
            at_timestamp=slot_ts,
        ):
            spot_scheduled += 1

    return fuel_scheduled, spot_scheduled, skipped_past


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
            f"Train Manager for today ({today_str}) already processed. "
            f"Skipping. (Use --force to override.)"
        )
        return 0

    # Decide whether to send the morning briefing (strict window) or just schedule.
    send_briefing = (
        "--force" in sys.argv
        or "--briefing" in sys.argv
        or in_briefing_window(now)
    )

    log.info("=" * 60)
    log.info(" 🚆 Train Manager Notifier - abhijaysinghlimited")
    log.info(f" Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    log.info(f" Topic: {NTFY_TOPIC}")
    log.info(f" Mode : {'Briefing + Scheduler' if send_briefing else 'Scheduler only (outside briefing window)'}")
    log.info("=" * 60)

    # --- Fetch schedule ---
    log.info(f"Fetching schedule from {API_URL} ...")
    try:
        raw_slots = fetch_train_prices(TIMEZONE_NAME)
    except Exception as e:
        log.error(f"Failed to fetch schedule: {e}")
        send_to_ntfy(
            NTFY_TOPIC,
            (
                "⚠️ Train Manager notifier could NOT fetch the daily schedule.\n\n"
                f"Error: `{e!s}`\n\n"
                "Likely causes:\n"
                "• mgtools.cloud API is down or under maintenance\n"
                "• Network / DNS problem on this host\n"
                "• API response shape changed (run with --debug)\n\n"
                "No alerts were scheduled for today."
            ),
            title="Train Manager: API FETCH FAILED",
            tags="warning,cloud,rain",
            priority="high",
        )
        return 3

    log.info(f"Fetched {len(raw_slots)} raw slots.")
    if not raw_slots:
        log.error("API returned zero slots. Notifying & exiting.")
        send_to_ntfy(
            NTFY_TOPIC,
            "⚠️ Train Manager API returned an empty schedule for today.\n"
            "Either mgtools.cloud is broken or the API contract changed.\n"
            "Run with --debug and inspect train_notifier.log.",
            title="Train Manager: EMPTY SCHEDULE",
            tags="warning,empty_nest",
            priority="high",
        )
        return 4

    # --- Normalize & filter today's slots ---
    all_slots = normalize_slots(raw_slots)
    today_slots = [s for s in all_slots if s.get("day") == today_day_str]
    if not today_slots:
        today_slots = all_slots  # fall back to whatever the API gave us
        log.warning("No `day` field matched today; using all returned slots.")
    log.info(f"Working with {len(today_slots)} slots for today.")

    # --- Sort by price ---
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
    briefing_sent = False
    if send_briefing:
        briefing_msg = build_morning_briefing(top_4_fuel, top_4_spot, now)
        log.info("Sending morning briefing...")
        briefing_sent = send_to_ntfy(
            topic=NTFY_TOPIC,
            message=briefing_msg,
            title=f"Train Manager: Daily Fuel & Spot Briefing ({current_time_12h})",
            tags="train,clipboard,fuelpump,sparkles",
            priority="default",
        )
        if not briefing_sent:
            log.warning("Briefing failed to send — continuing to scheduling anyway.")
    else:
        log.info(
            f"Outside briefing window ({BRIEFING_START[0]:02d}:{BRIEFING_START[1]:02d}–"
            f"{BRIEFING_END[0]:02d}:{BRIEFING_END[1]:02d} IST). Skipping briefing."
        )

    # --- Schedule exact-time alerts (BEFORE saving state) ---
    fuel_n, spot_n, skipped = schedule_alerts(top_4_fuel, top_4_spot, now)
    log.info(f"Scheduled: {fuel_n} fuel, {spot_n} spot, {skipped} skipped (past or unparseable).")

    # --- Save state AFTER everything (so a crash here doesn't lose the work) ---
    state["last_processed_date"] = today_str
    state["last_run_status"] = "ok" if (fuel_n + spot_n) > 0 else "partial"
    state["last_scheduled_fuel"] = fuel_n
    state["last_scheduled_spot"] = spot_n
    state["last_skipped_past"] = skipped
    save_state(state)

    # --- Final summary push if everything was skipped (e.g., script ran late) ---
    if fuel_n + spot_n == 0:
        send_to_ntfy(
            NTFY_TOPIC,
            (
                "⚠️ Train Manager ran today but **scheduled ZERO alerts**.\n\n"
                f"Skipped {skipped} slots (all past or unparseable).\n"
                "Did you run the script late in the day? Run earlier tomorrow "
                "(ideally inside the 06:00–07:00 IST window)."
            ),
            title="Train Manager: NO ALERTS SCHEDULED TODAY",
            tags="warning,calendar",
            priority="default",
        )

    log.info("Run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
