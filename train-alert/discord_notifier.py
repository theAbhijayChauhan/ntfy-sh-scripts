"""
============================================================
 💬 Discord Webhook notifier — drop-in replacement for ntfy.sh
============================================================

Same signature as your existing send_to_ntfy():
    send_to_discord(message, title, tags, priority, at_timestamp)

IMPORTANT — Discord does NOT support server-side scheduled delivery.
If at_timestamp is in the future, this function falls back to sending
immediately. For Train Manager's "alert me at 14:30 when fuel is
cheapest" use case, use the poll-and-fire pattern (see poll_fire.py).

Required environment variable (or GitHub Secret):
    DISCORD_WEBHOOK_URL  - from Discord channel settings → Integrations → Webhooks

Usage in any notifier script (one-line swap from ntfy):
    from discord_notifier import send_to_discord as send_to_ntfy
    # All your existing send_to_ntfy(...) calls now route to Discord.
"""

from __future__ import annotations

import os
import time
import logging
import requests
from typing import Optional

log = logging.getLogger("discord_alerts")

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

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
#   We get back HTTP 429 with a `retry_after` field when we hit it.


def send_to_discord(
    message: str,
    title: str,
    tags: str = "",
    priority: str = "default",
    at_timestamp: Optional[int] = None,
) -> bool:
    """Send a Discord message via webhook with a colored embed.

    Returns True on success (HTTP 204 from webhook), False otherwise.
    The `tags` and `at_timestamp` arguments are accepted for signature
    compatibility with the old ntfy function — `tags` is ignored and
    `at_timestamp` (if in the future) triggers a fallback warning since
    Discord webhooks cannot schedule future delivery.
    """
    if not WEBHOOK_URL:
        log.error("DISCORD_WEBHOOK_URL not set.")
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
        "username": "abhijaysinghlimited alerts",
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "footer": {"text": "abhijaysinghlimited alerts"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
    }

    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)

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
            r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
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
                "✅ Test from your notifier script.\n\n"
                "If you see this in Discord, your webhook URL is correct and "
                "delivery works end-to-end. Emergency alerts will appear in "
                "RED, high-priority in ORANGE, normal in BLUE."
            ),
            title="Notifier TEST",
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
                "SELL HYDROGEN QUICKLY, BUY FUEL QUICKLY, etc."
            ),
            title="Notifier TEST (URGENT)",
            priority="urgent",
        )
        print("OK" if ok else "FAIL")
        sys.exit(0 if ok else 1)
