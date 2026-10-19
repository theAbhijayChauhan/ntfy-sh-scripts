"""
Train Manager - Daily Fuel & Spot Price Tracker + Scheduler
Company: abhijaysinghlimited
Target: https://mgtools.cloud/games/train (API: https://api.mgtools.cloud/v1/fuel-price/train)
Topic: abhijaysinghlimited-train-fuel-alert

Rule:
1. Morning Briefing (6:00 AM IST): Sent ONCE with the Top 4 lowest times for Fuel AND Spot.
2. Exact-Time Alerts:
   - 4 chances for Fuel: Alert sent at the EXACT times of the Top 4 lowest Fuel prices.
   - 4 chances for Spot: Alert sent at the EXACT times of the Top 4 lowest Spot prices.
"""

import requests
import datetime
import time
import sys
from zoneinfo import ZoneInfo

# Ensure UTF-8 output in Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ==========================================
# CONFIGURATION
# ==========================================
NTFY_TOPIC = "abhijaysinghlimited-train-fuel-alert"
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

API_URL = "https://api.mgtools.cloud/v1/fuel-price/train"


def clean_time(time_str: str) -> str:
    """Remove '->' arrow prefix indicating current slot."""
    return time_str.replace("->", "").strip()


def to_12h(time_str: str) -> str:
    """Convert 'HH:MM' (or '-> HH:MM') 24-hour string to 12-hour 'hh:mm AM/PM'."""
    is_current = "->" in time_str
    cleaned = clean_time(time_str)
    dt = datetime.datetime.strptime(cleaned, "%H:%M")
    formatted = dt.strftime("%I:%M %p")
    return f"{formatted} [NOW]" if is_current else formatted


def get_slot_datetime(time_str: str, now: datetime.datetime) -> datetime.datetime:
    """Create a timezone-aware datetime for a given HH:MM slot today."""
    cleaned = clean_time(time_str)
    hour, minute = map(int, cleaned.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def fetch_train_prices(timezone_name=TIMEZONE_NAME):
    """Fetch live 24-hour fuel & spot schedule from mgtools cloud API."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    payload = {"timezone": timezone_name}
    
    response = requests.post(API_URL, json=payload, headers=headers, timeout=15)
    response.raise_for_status()
    result = response.json()
    return result.get("data", [])


def send_to_ntfy(topic: str, message: str, title: str, tags: str = "train,fuelpump", priority: str = "default", at_timestamp: int = None):
    """
    Send push notification to phone via ntfy.sh.
    If at_timestamp is provided, ntfy schedules delivery for that exact Unix epoch time!
    """
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Markdown": "yes"
    }
    if at_timestamp:
        headers["At"] = str(at_timestamp)

    response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
    return response.status_code == 200


def build_morning_briefing(top_4_fuel: list, top_4_spot: list, now: datetime.datetime) -> str:
    """
    Build the Morning Briefing:
    Shows the Top 4 Best Times of the Day to buy Fuel and Top 4 Best Times to buy Spot.
    """
    date_str = now.strftime("%A, %d %B %Y")
    medals = ["🥇", "🥈", "🥉", "4️⃣"]
    
    lines = [
        f"**🚆 Train Manager Daily Briefing**",
        f"📅 *{date_str} (IST)*\n",
        "⛽ **TOP 4 BEST TIMES TO BUY FUEL TODAY:**"
    ]
    
    for i, item in enumerate(top_4_fuel):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        lines.append(f"{m} **{to_12h(item['time'])}**: **${item['fuel']:,}** (Spot: ${item.get('spot', 'N/A'):,})")

    lines.append("\n⚡ **TOP 4 BEST TIMES TO BUY SPOT TODAY:**")
    for i, item in enumerate(top_4_spot):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        lines.append(f"{m} **{to_12h(item['time'])}**: **${item['spot']:,}** (Fuel: ${item.get('fuel', 'N/A'):,})")

    lines.append("\n" + "—" * 28)
    lines.append("⏰ *You will receive alerts at the 4 lowest Fuel times + 4 lowest Spot times.*")

    return "\n".join(lines)


def schedule_alerts(top_4_fuel: list, top_4_spot: list, now: datetime.datetime):
    """
    Schedule exact-time push alerts via ntfy.sh:
    - 4 chances for Fuel: Alert sent at the exact time of the Top 4 lowest fuel prices.
    - 4 chances for Spot: Alert sent at the exact time of the Top 4 lowest spot prices.
    """
    now_ts = int(now.timestamp())
    medals = ["🥇", "🥈", "🥉", "4th"]
    fuel_scheduled = 0
    spot_scheduled = 0

    print("\n[*] Scheduling Alerts for Top 4 Lowest Fuel Drops:")
    for rank, item in enumerate(top_4_fuel, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])
        
        if slot_ts > now_ts:
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank}"
            alert_msg = (
                f"⛽ **CHEAPEST FUEL ALERT! BUY NOW!**\n\n"
                f"• Time: **{time_12h}**\n"
                f"• Fuel Price: **${item['fuel']:,}** ({medal_label} best fuel price today)\n"
                f"• Spot Price: **${item.get('spot', 'N/A'):,}**\n\n"
                f"👉 Open Train Manager and stock up your fuel tanks now!"
            )
            title = f"BUY FUEL NOW: ${item['fuel']:,} at {time_12h}"
            success = send_to_ntfy(
                topic=NTFY_TOPIC,
                message=alert_msg,
                title=title,
                tags="fuelpump,rotating_light,money_with_wings",
                priority="urgent",
                at_timestamp=slot_ts
            )
            if success:
                fuel_scheduled += 1
                print(f"  [OK] Fuel Alert #{rank}: {time_12h} (${item['fuel']:,}) -> scheduled for {slot_dt.strftime('%I:%M %p')}")
        else:
            print(f"  [-] Fuel Alert #{rank}: {time_12h} has already passed today.")

    print("\n[*] Scheduling Alerts for Top 4 Lowest Spot Drops:")
    for rank, item in enumerate(top_4_spot, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])
        
        if slot_ts > now_ts:
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank}"
            alert_msg = (
                f"⚡ **CHEAPEST SPOT ALERT! BUY NOW!**\n\n"
                f"• Time: **{time_12h}**\n"
                f"• Spot Price: **${item['spot']:,}** ({medal_label} best spot price today)\n"
                f"• Fuel Price: **${item.get('fuel', 'N/A'):,}**\n\n"
                f"👉 Open Train Manager and buy spot power now!"
            )
            title = f"BUY SPOT NOW: ${item['spot']:,} at {time_12h}"
            success = send_to_ntfy(
                topic=NTFY_TOPIC,
                message=alert_msg,
                title=title,
                tags="zap,rotating_light,chart_with_downwards_trend",
                priority="urgent",
                at_timestamp=slot_ts
            )
            if success:
                spot_scheduled += 1
                print(f"  [OK] Spot Alert #{rank}: {time_12h} (${item['spot']:,}) -> scheduled for {slot_dt.strftime('%I:%M %p')}")
        else:
            print(f"  [-] Spot Alert #{rank}: {time_12h} has already passed today.")

    print(f"\n[OK] Scheduled {fuel_scheduled} Fuel alerts and {spot_scheduled} Spot alerts (Total: at most 4 each).")


def main():
    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    today_day_str = str(now.day)
    
    print(f"=====================================================")
    print(f" Train Manager Notifier - abhijaysinghlimited")
    print(f" Current Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    print(f" ntfy Topic   : {NTFY_TOPIC}")
    print(f"=====================================================\n")

    print("[*] Fetching schedule from mgtools.cloud...")
    all_data = fetch_train_prices(TIMEZONE_NAME)
    print(f"[OK] Fetched {len(all_data)} raw slots.")

    today_slots = [item for item in all_data if item.get("day") == today_day_str]
    if not today_slots:
        today_slots = all_data

    print(f"[OK] Found {len(today_slots)} slots for today.")

    # Sort strictly by Fuel Price (lowest first)
    by_fuel = sorted(today_slots, key=lambda x: (x["fuel"], clean_time(x["time"])))
    # Sort strictly by Spot Price (lowest first)
    by_spot = sorted(today_slots, key=lambda x: (x["spot"], clean_time(x["time"])))
    
    # Identify Top 4 for Fuel and Top 4 for Spot
    top_4_fuel = by_fuel[:4]
    top_4_spot = by_spot[:4]

    # 1. Send Morning Briefing ONCE
    briefing_msg = build_morning_briefing(top_4_fuel, top_4_spot, now)
    
    print("\n--- BRIEFING PREVIEW (Top 4 Fuel & Spot) ---")
    print(briefing_msg)
    print("--------------------------------------------\n")

    print(f"[*] Sending daily briefing to ntfy.sh/{NTFY_TOPIC}...")
    sent = send_to_ntfy(
        topic=NTFY_TOPIC,
        message=briefing_msg,
        title=f"Train Manager: Top 4 Fuel & Spot Times ({current_time_12h})",
        tags="train,clipboard,fuelpump",
        priority="default"
    )
    if sent:
        print("[OK] Daily Briefing Notification sent successfully!")
    else:
        print("[!] Failed to send briefing notification.")

    # 2. Schedule exact-time alerts: 4 for Fuel + 4 for Spot
    schedule_alerts(top_4_fuel, top_4_spot, now)

    print("\n[OK] Train Manager Notifier completed successfully.")


if __name__ == "__main__":
    main()
