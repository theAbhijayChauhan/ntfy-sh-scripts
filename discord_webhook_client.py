"""
Shared Discord Webhook client supporting single-message upsert:
  - notify=True  : DELETE previous message (if any) + POST new message (?wait=true)
                   -> Triggers a real push notification while keeping only 1 message.
  - notify=False : PATCH previous message silently (no push notification),
                   falling back to POST (?wait=true) if no message exists yet (or 404).
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

log = logging.getLogger("discord_alerts")

PRIORITY_COLOR = {
    "default": 0x3498DB,  # blue
    "low": 0x95A5A6,      # gray
    "high": 0xF39C12,     # orange
    "buy": 0x00FF7F,      # glowing neon green
    "sell": 0xFF1744,     # glowing neon red
    "urgent": 0xFF1744,   # glowing neon red
}


def _build_post_url(webhook_url: str) -> str:
    """Append wait=true so Discord returns the created message JSON (with id)."""
    parsed = urlparse(webhook_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunparse(parsed._replace(query=urlencode(query)))


def _build_message_url(webhook_url: str, message_id: str) -> str:
    """Build /webhooks/{id}/{token}/messages/{message_id} URL preserving thread_id."""
    parsed = urlparse(webhook_url)
    base_path = parsed.path.rstrip("/")
    query = {
        k: v
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k != "wait"
    }
    return urlunparse(
        parsed._replace(
            path=f"{base_path}/messages/{message_id}",
            query=urlencode(query),
        )
    )


def _request_with_rate_limit(
    method: str,
    url: str,
    json_payload: Optional[dict] = None,
) -> Optional[requests.Response]:
    """Perform an HTTP request, automatically retrying once on Discord 429."""
    try:
        resp = requests.request(method, url, json=json_payload, timeout=15)
        if resp.status_code == 429:
            try:
                retry_after = float(resp.json().get("retry_after", 5))
            except ValueError:
                retry_after = 5.0
            log.warning(f"Discord rate-limited on {method}; retrying in {retry_after:.1f}s.")
            time.sleep(retry_after)
            resp = requests.request(method, url, json=json_payload, timeout=15)
        return resp
    except requests.RequestException as e:
        log.error(f"Discord {method} network error: {e}")
        return None


def _delete_message(webhook_url: str, message_id: str) -> None:
    """Best-effort delete of an existing webhook message."""
    url = _build_message_url(webhook_url, message_id)
    resp = _request_with_rate_limit("DELETE", url)
    if resp is None:
        return
    if resp.status_code in (200, 204):
        log.debug(f"Deleted previous Discord message {message_id}.")
    elif resp.status_code == 404:
        log.debug(f"Previous Discord message {message_id} already absent (404).")
    else:
        log.warning(
            f"Could not delete previous Discord message {message_id}: "
            f"HTTP {resp.status_code} {resp.text[:200]}"
        )


def _build_embed(message: str, title: str, priority: str, footer_text: str) -> dict:
    color = PRIORITY_COLOR.get(priority, PRIORITY_COLOR["default"])
    description = message if len(message) <= 4000 else message[:4000] + " …"
    return {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": footer_text},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def upsert_discord_message(
    webhook_url: str,
    username: str,
    footer_text: str,
    message: str,
    title: str,
    priority: str = "default",
    message_id: Optional[str] = None,
    notify: bool = True,
    content: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Keep a single live message in Discord per channel.

    Returns (success, latest_message_id):
    - notify=True : deletes previous message (if known) and POSTs a new one
                    with an @everyone ping so Discord triggers a mobile push.
    - notify=False: PATCHes previous message in place (silent, zero push),
                    clearing any stale @everyone banner and posting only if none exists / 404.
    """
    if not webhook_url:
        log.error("Discord webhook URL not set.")
        return False, message_id

    embed = _build_embed(message, title, priority, footer_text)

    if not notify and message_id:
        patch_url = _build_message_url(webhook_url, message_id)
        resp = _request_with_rate_limit("PATCH", patch_url, {"content": "", "embeds": [embed]})
        if resp is None:
            # Preserve message_id on transient network errors so next run retries PATCH.
            return False, message_id
        if resp.status_code == 200:
            log.info(f"Discord PATCH OK (silent update) → {title}")
            return True, message_id
        if resp.status_code != 404:
            log.error(
                f"Discord PATCH FAIL: HTTP {resp.status_code} {resp.text[:300]}"
            )
            return False, message_id
        log.info(f"Previous message {message_id} was deleted (404); creating a new one.")

    if notify and message_id:
        _delete_message(webhook_url, message_id)
        time.sleep(0.3)

    post_url = _build_post_url(webhook_url)
    if notify:
        ping_text = content if content is not None else f"@everyone 🚨 **{title}**"
        payload = {
            "username": username,
            "content": ping_text,
            "allowed_mentions": {"parse": ["everyone"]},
            "embeds": [embed],
        }
    else:
        payload = {"username": username, "embeds": [embed]}
    resp = _request_with_rate_limit("POST", post_url, payload)
    if resp is None:
        return False, None if notify else message_id

    if resp.status_code in (200, 204):
        new_id: Optional[str] = None
        if resp.status_code == 200:
            try:
                new_id = resp.json().get("id")
            except ValueError:
                new_id = None
        mode = "alert POST" if notify else "initial POST"
        log.info(f"Discord {mode} OK (id={new_id}) → {title}")
        return True, new_id

    log.error(f"Discord POST FAIL: HTTP {resp.status_code} {resp.text[:300]}")
    return False, None
