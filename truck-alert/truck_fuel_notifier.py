"""
Truck Manager - Daily Fuel (Diesel, CO2, kWh) Price Tracker + Scheduler
Company: abhijaysinghlimited
Target: https://mgtools.cloud/games/truck (API: https://api.mgtools.cloud/v1/fuel-price/truck)
Topic: abhijaysinghlimited-truck-fuel-alert

Rule:
1. Morning Briefing (6:00 AM IST): Sent ONCE with the Top 4 lowest times for Diesel, CO2, and kWh.
2. Exact-Time Alerts:
   - 4 chances for Diesel: Alert sent at the EXACT times of the Top 4 lowest Diesel prices.
   - 4 chances for CO2: Alert sent at the EXACT times of the Top 4 lowest CO2 prices.
   - 4 chances for kWh: Alert sent at the EXACT times of the Top 4 lowest kWh prices.
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
NTFY_TOPIC = "abhijaysinghlimited-truck-fuel-alert"
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

API_URL = "https://api.mgtools.cloud/v1/fuel-price/truck"


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


def fetch_truck_prices(timezone_name=TIMEZONE_NAME):
    """Fetch live 24-hour diesel, kwh, and CO2 schedule from mgtools cloud API."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    payload = {"timezone": timezone_name}
    
    response = requests.post(API_URL, json=payload, headers=headers, timeout=15)
    response.raise_for_status()
    result = response.json()
    return result.get("data", [])


def send_to_ntfy(topic: str, message: str, title: str, tags: str = "truck,fuelpump", priority: str = "default", at_timestamp: int = None):
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


def build_morning_briefing(top_4_diesel: list, top_4_co2: list, top_4_kwh: list, now: datetime.datetime) -> str:
    """
    Build the Morning Briefing:
    Shows Top 4 Best Times for Diesel, CO2, and kWh.
    """
    date_str = now.strftime("%A, %d %B %Y")
    medals = ["🥇", "🥈", "🥉", "4️⃣"]
    
    lines = [
        f"**🚛 Truck Manager Daily Briefing**",
        f"📅 *{date_str} (IST)*\n",
        "⛽ **TOP 4 BEST TIMES TO BUY DIESEL TODAY:**"
    ]
    for i, item in enumerate(top_4_diesel):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        lines.append(f"{m} **{to_12h(item['time'])}**: **${item['diesel']}** (CO2: ${item.get('co2', 'N/A')}, kWh: ${item.get('kwh', 'N/A')})")

    lines.append("\n🍃 **TOP 4 BEST TIMES TO BUY CO2 TODAY:**")
    for i, item in enumerate(top_4_co2):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        lines.append(f"{m} **{to_12h(item['time'])}**: **${item['co2']}**")

    lines.append("\n⚡ **TOP 4 BEST TIMES TO CHARGE KWH TODAY:**")
    for i, item in enumerate(top_4_kwh):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        lines.append(f"{m} **{to_12h(item['time'])}**: **${item['kwh']}**")

    lines.append("\n" + "—" * 28)
    lines.append("⏰ *You will receive alerts at the 4 lowest Diesel + 4 lowest CO2 + 4 lowest kWh times.*")

    return "\n".join(lines)


def schedule_alerts(top_4_diesel: list, top_4_co2: list, top_4_kwh: list, now: datetime.datetime):
    """
    Schedule exact-time push alerts via ntfy.sh:
    - 4 chances for Diesel: Alert sent at the exact time of Top 4 lowest Diesel prices.
    - 4 chances for CO2: Alert sent at the exact time of Top 4 lowest CO2 prices.
    - 4 chances for kWh: Alert sent at the exact time of Top 4 lowest kWh prices.
    """
    now_ts = int(now.timestamp())
    medals = ["🥇", "🥈", "🥉", "4th"]
    d_count, c_count, k_count = 0, 0, 0

    print("\n[*] Scheduling Alerts for Top 4 Lowest Diesel Drops:")
    for rank, item in enumerate(top_4_diesel, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])
        
        if slot_ts > now_ts:
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank}"
            alert_msg = (
                f"⛽ **CHEAPEST DIESEL ALERT! BUY NOW!**\n\n"
                f"• Time: **{time_12h}**\n"
                f"• Diesel Price: **${item['diesel']}** ({medal_label} best diesel price today)\n"
                f"• CO2: **${item.get('co2', 'N/A')}** | kWh: **${item.get('kwh', 'N/A')}**\n\n"
                f"👉 Open Truck Manager and fuel your fleet now!"
            )
            title = f"BUY DIESEL NOW: ${item['diesel']} at {time_12h}"
            success = send_to_ntfy(
                topic=NTFY_TOPIC,
                message=alert_msg,
                title=title,
                tags="truck,fuelpump,rotating_light",
                priority="urgent",
                at_timestamp=slot_ts
            )
            if success:
                d_count += 1
                print(f"  [OK] Diesel Alert #{rank}: {time_12h} (${item['diesel']}) -> scheduled for {slot_dt.strftime('%I:%M %p')}")
        else:
            print(f"  [-] Diesel Alert #{rank}: {time_12h} has already passed today.")

    print("\n[*] Scheduling Alerts for Top 4 Lowest CO2 Drops:")
    for rank, item in enumerate(top_4_co2, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])
        
        if slot_ts > now_ts:
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank}"
            alert_msg = (
                f"🍃 **CHEAPEST CO2 QUOTA ALERT! BUY NOW!**\n\n"
                f"• Time: **{time_12h}**\n"
                f"• CO2 Price: **${item['co2']}** ({medal_label} best CO2 price today)\n\n"
                f"👉 Open Truck Manager and stock up CO2 quotas now!"
            )
            title = f"BUY CO2 NOW: ${item['co2']} at {time_12h}"
            success = send_to_ntfy(
                topic=NTFY_TOPIC,
                message=alert_msg,
                title=title,
                tags="recycle,rotating_light,money_with_wings",
                priority="urgent",
                at_timestamp=slot_ts
            )
            if success:
                c_count += 1
                print(f"  [OK] CO2 Alert #{rank}: {time_12h} (${item['co2']}) -> scheduled for {slot_dt.strftime('%I:%M %p')}")
        else:
            print(f"  [-] CO2 Alert #{rank}: {time_12h} has already passed today.")

    print("\n[*] Scheduling Alerts for Top 4 Lowest kWh Drops:")
    for rank, item in enumerate(top_4_kwh, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])
        
        if slot_ts > now_ts:
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank}"
            alert_msg = (
                f"⚡ **CHEAPEST KWH ELECTRICITY ALERT! CHARGE NOW!**\n\n"
                f"• Time: **{time_12h}**\n"
                f"• kWh Price: **${item['kwh']}** ({medal_label} best electricity rate today)\n\n"
                f"👉 Open Truck Manager and charge your electric fleet now!"
            )
            title = f"BUY KWH NOW: ${item['kwh']} at {time_12h}"
            success = send_to_ntfy(
                topic=NTFY_TOPIC,
                message=alert_msg,
                title=title,
                tags="zap,battery,rotating_light",
                priority="urgent",
                at_timestamp=slot_ts
            )
            if success:
                k_count += 1
                print(f"  [OK] kWh Alert #{rank}: {time_12h} (${item['kwh']}) -> scheduled for {slot_dt.strftime('%I:%M %p')}")
        else:
            print(f"  [-] kWh Alert #{rank}: {time_12h} has already passed today.")

    print(f"\n[OK] Scheduled: {d_count} Diesel, {c_count} CO2, {k_count} kWh alerts (Total: at most 4 each).")


def main():
    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    today_day_str = str(now.day)
    
    print(f"=====================================================")
    print(f" Truck Manager Notifier - abhijaysinghlimited")
    print(f" Current Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    print(f" ntfy Topic   : {NTFY_TOPIC}")
    print(f"=====================================================\n")

    print("[*] Fetching schedule from mgtools.cloud...")
    all_data = fetch_truck_prices(TIMEZONE_NAME)
    print(f"[OK] Fetched {len(all_data)} raw slots.")

    today_slots = [item for item in all_data if item.get("day") == today_day_str]
    if not today_slots:
        today_slots = all_data

    print(f"[OK] Found {len(today_slots)} slots for today.")

    # Sort strictly by each commodity price (lowest first)
    by_diesel = sorted(today_slots, key=lambda x: (float(x.get("diesel", 999)), clean_time(x["time"])))
    by_co2 = sorted(today_slots, key=lambda x: (float(x.get("co2", 999)), clean_time(x["time"])))
    by_kwh = sorted(today_slots, key=lambda x: (float(x.get("kwh", 999)), clean_time(x["time"])))
    
    # Identify Top 4 for each commodity
    top_4_diesel = by_diesel[:4]
    top_4_co2 = by_co2[:4]
    top_4_kwh = by_kwh[:4]

    # 1. Send Morning Briefing ONCE
    briefing_msg = build_morning_briefing(top_4_diesel, top_4_co2, top_4_kwh, now)
    
    print("\n--- BRIEFING PREVIEW (Top 4 for Diesel, CO2, kWh) ---")
    print(briefing_msg)
    print("----------------------------------------------------\n")

    print(f"[*] Sending daily briefing to ntfy.sh/{NTFY_TOPIC}...")
    sent = send_to_ntfy(
        topic=NTFY_TOPIC,
        message=briefing_msg,
        title=f"Truck Manager: Top 4 Times for Diesel, CO2, kWh ({current_time_12h})",
        tags="truck,clipboard,fuelpump",
        priority="default"
    )
    if sent:
        print("[OK] Daily Briefing Notification sent successfully!")
    else:
        print("[!] Failed to send briefing notification.")

    # 2. Schedule exact-time alerts: 4 for Diesel + 4 for CO2 + 4 for kWh
    schedule_alerts(top_4_diesel, top_4_co2, top_4_kwh, now)

    print("\n[OK] Truck Manager Notifier completed successfully.")


if __name__ == "__main__":
    main()
