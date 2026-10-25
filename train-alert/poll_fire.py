"""
============================================================
 🚆 Train Alert Poll-and-Fire (Option B)
============================================================

Reads train-alert/scheduled_alerts.json (written by
train_fuel_notifier.py during the morning briefing). For each
alert where now >= scheduled_ts AND not yet fired, this script:

  1. Sends an URGENT Discord webhook (red embed).
  2. Marks the alert as fired and records the fired timestamp.
  3. Saves state back to scheduled_alerts.json.

This is run on a 5-minute cron by `train_alert_poll.yml`. With
GitHub Actions, scheduled workflows can be delayed by a few
minutes during peak load — but since fuel/spot prices change
hourly, a 5-minute polling cadence is well within tolerance.

Usage
-----
  python poll_fire.py             # normal poll-and-fire run
  python poll_fire.py --debug     # verbose logging
  python poll_fire.py --test      # send a test webhook and exit
============================================================
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import time
from zoneinfo import ZoneInfo

# Add script dir + parent to path so discord_notifier can live
# either in train-alert/ (same folder) OR at repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
for p in (HERE, PARENT):
    if p not in sys.path:
        sys.path.insert(0, p)

from discord_notifier import send_to_discord  # noqa: E402

# ============================================================
#  CONFIGURATION
# ============================================================
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

SCHEDULED_ALERTS_FILE = os.path.join(HERE, "scheduled_alerts.json")
LOG_FILE = os.path.join(HERE, "poll_fire.log")

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
log = logging.getLogger("train_poll")


# ============================================================
#  STATE FILE I/O (atomic)
# ============================================================
def load_state() -> dict | None:
    if not os.path.exists(SCHEDULED_ALERTS_FILE):
        return None
    try:
        with open(SCHEDULED_ALERTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"State file unreadable: {e}")
        return None


def save_state(state: dict) -> None:
    tmp = SCHEDULED_ALERTS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, SCHEDULED_ALERTS_FILE)
    except Exception as e:
        log.error(f"Could not save state: {e}")


# ============================================================
#  ALERT FIRING
# ============================================================
def fire_alert(alert: dict) -> bool:
    """Send an urgent Discord webhook for one scheduled alert."""
    alert_type = alert.get("type", "unknown")
    rank = alert.get("rank", 0)
    time_12h = alert.get("time_12h", "??:??")
    price = alert.get("price", "N/A")
    other_price = alert.get("other_price", "N/A")
    medal = alert.get("medal", f"#{rank}")

    if alert_type == "fuel":
        title = f"BUY FUEL QUICKLY: ${price:,} at {time_12h}"
        msg = (
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"       ⛽ BUY FUEL QUICKLY • CHEAPEST NOW!\n"
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"⏰ **Exact Time:** {time_12h} [RIGHT NOW]\n"
            f"💰 **Fuel Price:** **${price:,}** ({medal})\n"
            f"⚡ **Spot Price:** ${other_price:,}\n"
            f"🏢 **Company:** abhijaysinghlimited\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
            f"Fuel price is at its rock-bottom window for the hour!\n"
            f"👉 Open **Train Manager** and stock up your tanks!"
        )
    elif alert_type == "spot":
        title = f"BUY SPOT QUICKLY: ${price:,} at {time_12h}"
        msg = (
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"       ⚡ BUY SPOT POWER QUICKLY!\n"
            f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
            f"⏰ **Exact Time:** {time_12h} [RIGHT NOW]\n"
            f"⚡ **Spot Price:** **${price:,}** ({medal})\n"
            f"⛽ **Fuel Price:** ${other_price:,}\n"
            f"🏢 **Company:** abhijaysinghlimited\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
            f"Spot electricity is at its cheapest rate of the day!\n"
            f"👉 Open **Train Manager** and buy spot power now!"
        )
    else:
        log.warning(f"Unknown alert type: {alert_type}")
        return False

    return send_to_discord(
        message=msg,
        title=title,
        priority="urgent",
    )


# ============================================================
#  MAIN
# ============================================================
def main() -> int:
    # --- Self-test mode ---
    if "--test" in sys.argv:
        log.info("Sending test webhook...")
        ok = send_to_discord(
            message=(
                "✅ Test from poll_fire.py.\n\n"
                "If you see this, your webhook + polling pipeline works end-to-end. "
                "Scheduled price-time alerts will appear in RED when their minute arrives."
            ),
            title="Train Poll-Fire TEST",
            priority="default",
        )
        return 0 if ok else 1

    now = datetime.datetime.now(LOCAL_TZ)
    today_str = now.strftime("%Y-%m-%d")
    now_ts = int(now.timestamp())

    log.info(f"Poll-fire run at {now.strftime('%Y-%m-%d %I:%M:%S %p')} IST")

    state = load_state()
    if state is None:
        log.info("No scheduled_alerts.json. Exiting (morning briefing hasn't run yet).")
        return 0

    state_date = state.get("date")
    if state_date != today_str:
        log.info(f"State file is from {state_date}, not today ({today_str}). Exiting.")
        return 0

    alerts = state.get("alerts", [])
    if not alerts:
        log.info("No alerts in state file. Exiting.")
        return 0

    unfired = [a for a in alerts if not a.get("fired")]
    log.info(f"State has {len(alerts)} alerts ({len(unfired)} unfired). Checking for due...")

    fired_count = 0
    failed_count = 0
    for alert in alerts:
        if alert.get("fired"):
            continue
        scheduled_ts = alert.get("scheduled_ts")
        if scheduled_ts is None:
            log.warning(f"Alert missing scheduled_ts: {alert}")
            continue
        if now_ts >= scheduled_ts:
            log.info(
                f"Firing {alert.get('type')} #{alert.get('rank')} "
                f"at {alert.get('time_12h')} (${alert.get('price'):,})"
            )
            if fire_alert(alert):
                alert["fired"] = True
                alert["fired_ts"] = now_ts
                fired_count += 1
            else:
                failed_count += 1
                log.error(f"Failed to fire alert {alert.get('id')}; will retry next poll.")

    save_state(state)

    log.info(f"Done. Fired {fired_count}, failed {failed_count}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
