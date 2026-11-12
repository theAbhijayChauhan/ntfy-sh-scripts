"""
============================================================
 💬 Discord Webhook notifier — ENERGY MANAGER version
============================================================

Maintains a single live Discord message in #energy-alerts:
  - upsert_to_discord(..., notify=True)  : deletes previous message + posts new alert (buzzes phone)
  - upsert_to_discord(..., notify=False) : silently PATCHes previous message with live prices (no buzz)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

from discord_webhook_client import upsert_discord_message  # noqa: E402

log = logging.getLogger("discord_alerts")

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL_ENERGY", "")
BOT_USERNAME = "⚡ Energy Manager Alerts"
FOOTER_TEXT = "abhijaysinghlimited • Energy Manager"


def _get_webhook() -> str:
    return os.getenv("DISCORD_WEBHOOK_URL_ENERGY") or WEBHOOK_URL


def upsert_to_discord(
    message: str,
    title: str,
    priority: str = "default",
    message_id: Optional[str] = None,
    notify: bool = True,
    content: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Update or replace the single Energy Manager status/alert message."""
    webhook = _get_webhook()
    if not webhook:
        log.error("DISCORD_WEBHOOK_URL_ENERGY not set.")
        return False, message_id
    return upsert_discord_message(
        webhook_url=webhook,
        username=BOT_USERNAME,
        footer_text=FOOTER_TEXT,
        message=message,
        title=title,
        priority=priority,
        message_id=message_id,
        notify=notify,
        content=content,
    )


def send_to_discord(
    message: str,
    title: str,
    tags: str = "",
    priority: str = "default",
    at_timestamp: Optional[int] = None,
) -> bool:
    """Backward-compatible fire-and-forget Discord send."""
    if at_timestamp and at_timestamp > int(time.time()) + 10:
        log.warning(
            "Discord webhook can't schedule future delivery; sending now "
            f"(was scheduled for {time.strftime('%H:%M:%S', time.gmtime(at_timestamp))} UTC)."
        )
    ok, _ = upsert_to_discord(
        message=message,
        title=title,
        priority=priority,
        message_id=None,
        notify=True,
    )
    return ok


send_to_ntfy = send_to_discord


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if "--test" in sys.argv:
        ok = send_to_discord(
            message=(
                "✅ Test from Energy Manager notifier.\n\n"
                "Single-message mode ready."
            ),
            title="Energy Manager: TEST",
            priority="default",
        )
        print("OK" if ok else "FAIL")
        sys.exit(0 if ok else 1)

    if "--test-urgent" in sys.argv:
        ok = send_to_discord(
            message="🚨 This is what an URGENT Energy Manager alert looks like.",
            title="Energy Manager TEST (URGENT)",
            priority="urgent",
        )
        print("OK" if ok else "FAIL")
        sys.exit(0 if ok else 1)
