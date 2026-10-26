"""
============================================================
 💬 Discord Webhook notifier — ENERGY MANAGER version
============================================================

Drop-in replacement for ntfy.sh, configured for the Energy Manager
Discord channel.

Same signature as your old send_to_ntfy():
    send_to_discord(message, title, tags, priority, at_timestamp)

IMPORTANT — Discord does NOT support server-side scheduled delivery.
If at_timestamp is in the future, this function falls back to sending
immediately. Energy Manager doesn't need scheduling (all alerts are
immediate), so this is fine.

Required environment variable (or GitHub Secret):
    DISCORD_WEBHOOK_URL_ENERGY  - from the #energy-alerts channel
                                  webhook in your Discord server

NOTE: This is the Energy-Manager-specific copy of discord_notifier.py.
The Train Manager has its own copy in train-alert/ that reads from
DISCORD_WEBHOOK_URL (no _ENERGY suffix). Keep these two files separate
so the two alert channels stay independent.
"""

from __future__ import annotations

import os
import time
import logging
import requests
from typing import Optional

log = logging.getLogger("discord_alerts")

# ★ ENERGY-SPECIFIC: reads from DISCORD_WEBHOOK_URL_ENERGY
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL_ENERGY", "")

# Discord embed colors (decimal RGB) per priority tier.
_PRIORITY_COLOR = {
    "default": 0x3498DB,   # blue
    "low":     0x95A5A6,   # gray
    "high":    0xF39C12,   # orange
    "urgent":  0xE74C3C,   # red
}

# Discord has no priority levels; we prefix the message to convey it.
_PRIORITY_EMOJI = {
    "default": "ℹ️",
    "low":     "·",
    "high":    "⚠️",
    "urgent":  "🚨",
}

# Discord per-webhook rate limits (auto-handled):
#   30 messages per minute sustained, 5 per second burst.


def send_to_discord(
    message: str,
    title: str,
    tags: str = "",
    priority: str = "default",
    at_timestamp: Optional[int] = None,
) -> bool:
    """Send a Discord message via webhook with a colored embed."""
    webhook = os.getenv("DISCORD_WEBHOOK_URL_ENERGY") or WEBHOOK_URL
    if not webhook:
        log.error("DISCORD_WEBHOOK_URL_ENERGY not set.")
        return False

    if at_timestamp:
        now_ts = int(time.time())
        if at_timestamp > now_ts + 10:
            log.warning(
                f"Discord webhook can't schedule future delivery; sending now "
                f"(was scheduled for {time.strftime('%H:%M:%S', time.gmtime(at_timestamp))} UTC)."
            )

    color = _PRIORITY_COLOR.get(priority, _PRIORITY_COLOR["default"])
    emoji = _PRIORITY_EMOJI.get(priority, "ℹ️")

    # Discord embed description limit: 4096 chars. Truncate if needed.
    description = message if len(message) <= 4000 else message[:4000] + " …"

    payload = {
        "username": "⚡ Energy Manager Alerts",
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "footer": {"text": "abhijaysinghlimited • Energy Manager"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
    }

    try:
        r = requests.post(webhook, json=payload, timeout=15)

        # Discord webhooks return 204 No Content on success.
        if r.status_code == 204:
            log.info(f"Discord OK → {title}")
            return True

        # 429 = rate limited; the response tells us how long to wait.
        if r.status_code == 429:
            try:
                retry_after = float(r.json().get("retry_after", 5))
            except ValueError:
                retry_after = 5.0
            log.warning(f"Discord rate-limited; retrying in {retry_after:.1f}s.")
            time.sleep(retry_after)
            r = requests.post(webhook, json=payload, timeout=15)
            if r.status_code == 204:
                log.info(f"Discord OK (after retry) → {title}")
                return True

        log.error(f"Discord FAIL: HTTP {r.status_code} {r.text[:300]}")
        return False

    except requests.RequestException as e:
        log.error(f"Discord network error: {e}")
        return False


# Convenience alias so swapping from ntfy is one line:
#   from discord_notifier import send_to_ntfy
send_to_ntfy = send_to_discord


# --- Self-test ---
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if "--test" in sys.argv:
        ok = send_to_discord(
            message=(
                "✅ Test from Energy Manager notifier.\n\n"
                "If you see this in your #energy-alerts channel, your Energy "
                "webhook + script work. Emergency alerts will appear in RED."
            ),
            title="Energy Manager: TEST",
            priority="default",
        )
        print("OK" if ok else "FAIL")
        sys.exit(0 if ok else 1)

    if "--test-urgent" in sys.argv:
        ok = send_to_discord(
            message=(
                "🚨🚨🚨 This is what an URGENT alert looks like.\n\n"
                "Color: RED.\n"
                "Used for: BUY OIL QUICKLY, BUY COAL QUICKLY, "
                "SELL HYDROGEN QUICKLY, BUY CO2 QUICKLY."
            ),
            title="Energy Manager TEST (URGENT)",
            priority="urgent",
        )
        print("OK" if ok else "FAIL")
        sys.exit(0 if ok else 1)
