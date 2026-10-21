"""
🚛 Truck Manager - Daily Fuel (Diesel, CO2, kWh) Price Tracker + Scheduler
🏢 Company: abhijaysinghlimited
🎯 Target: https://mgtools.cloud/games/truck (API: https://api.mgtools.cloud/v1/fuel-price/truck)
🔔 Topic: abhijaysinghlimited-truck-fuel-alert

✨ Features:
1. ENABLED Switch: Set ENABLED = False to completely disable Truck alerts anytime!
2. Morning Briefing: Tries continuously from 6:00 AM to 7:00 AM IST until sent once.
3. Exact-Time Alerts: Pre-scheduled via ntfy.sh to buzz phone at the 4 lowest Diesel + 4 lowest CO2 + 4 lowest kWh times.
4. Deduplication: Briefing & scheduler run once per day (zero spam).
"""

import requests
import datetime
import time
import sys
import os
import json
from zoneinfo import ZoneInfo

# Ensure UTF-8 output in Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ==========================================
# MASTER TOGGLE (Set to False to turn OFF alerts)
# ==========================================
ENABLED = True

# ==========================================
# CONFIGURATION
# ==========================================
NTFY_TOPIC = "abhijaysinghlimited-truck-fuel-alert"
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

STATE_FILE = os.path.join(os.path.dirname(__file__), "truck_state.json")
API_URL = "https://api.mgtools.cloud/v1/fuel-price/truck"


def load_state() -> dict:
    """Load persistent state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_processed_date": None}


def save_state(state: dict):
    """Save persistent state."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[!] Warning: Could not save state: {e}")


def clean_time(time_str: str) -> str:
    """Remove '->' arrow prefix indicating current slot."""
    return time_str.replace("->", "").strip()


def to_12h(time_str: str) -> str:
    """Convert 'HH:MM' (or '-> HH:MM') 24-hour string to 12-hour 'hh:mm AM/PM'."""
    is_current = "->" in time_str
    cleaned = clean_time(time_str)
    dt = datetime.datetime.strptime(cleaned, "%H:%M")
    formatted = dt.strftime("%I:%M %p")
    return f"{formatted} ⚡[NOW]" if is_current else formatted


def get_slot_datetime(time_str: str, now: datetime.datetime) -> datetime.datetime:
    """Create a timezone-aware datetime for a given HH:MM slot today."""
    cleaned = clean_time(time_str)
    hour, minute = map(int, cleaned.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def fetch_truck_prices(timezone_name=TIMEZONE_NAME, retries=5, delay=5):
    """Fetch live 24-hour diesel, kwh, and CO2 schedule from mgtools cloud API with retries."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    payload = {"timezone": timezone_name}
    
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(API_URL, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            result = response.json()
            data = result.get("data", [])
            if data:
                return data
        except Exception as e:
            last_err = e
            print(f"  [!] Fetch attempt {attempt}/{retries} failed: {e}. Retrying in {delay}s...")
            time.sleep(delay)
            
    if last_err:
        raise last_err
    return []


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
    Stunning emoji layout showing Top 4 Best Times for Diesel, CO2, and kWh.
    """
    date_str = now.strftime("%A, %d %B %Y")
    current_time_12h = now.strftime("%I:%M %p")
    medals = ["🥇", "🥈", "🥉", "4️⃣"]
    badges_diesel = ["🟢 BEST DIESEL", "⭐ GREAT PRICE", "💰 LOW DIP", "📉 GOOD TIME"]
    badges_co2 = ["🟢 LOWEST CO2", "⭐ GREAT RATE", "🌿 CHEAP QUOTA", "📉 FAIR RATE"]
    badges_kwh = ["🟢 LOWEST RATE", "⚡ OFF-PEAK", "🔋 MID-DAY DIP", "🔌 GOOD CHARGE"]

    lines = [
        "🚛 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚛",
        "       TRUCK MANAGER • DAILY BRIEFING",
        "             abhijaysinghlimited",
        "🚛 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚛",
        f"📅 **Date:** {date_str} | ⏰ **Time:** {current_time_12h} IST",
        "🎯 **Radar:** 24-Hour Automated Fleet Forecaster",
        "",
        "⛽ ━━━ 🏆 TOP 4 DIESEL DROPS ━━━ ⛽"
    ]
    for i, item in enumerate(top_4_diesel):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        b = badges_diesel[i] if i < len(badges_diesel) else "🏷️ DISCOUNT"
        lines.append(f"{m} **{to_12h(item['time'])}** ➜ **${item['diesel']}** *(CO2: ${item.get('co2', 'N/A')}, kWh: ${item.get('kwh', 'N/A')})* {b}")

    lines.append("")
    lines.append("🍃 ━━━ 🍃 TOP 4 CO2 QUOTA DROPS ━━━ 🍃")
    for i, item in enumerate(top_4_co2):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        b = badges_co2[i] if i < len(badges_co2) else "🏷️ DISCOUNT"
        lines.append(f"{m} **{to_12h(item['time'])}** ➜ **${item['co2']}** {b}")

    lines.append("")
    lines.append("⚡ ━━━ ⚡ TOP 4 KWH ELECTRICITY DROPS ━━━ ⚡")
    for i, item in enumerate(top_4_kwh):
        m = medals[i] if i < len(medals) else f"#{i+1}"
        b = badges_kwh[i] if i < len(badges_kwh) else "🏷️ DISCOUNT"
        lines.append(f"{m} **{to_12h(item['time'])}** ➜ **${item['kwh']}** {b}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔔 **AUTO-ALERTS SCHEDULED:**")
    lines.append("📱 You will receive **4 Diesel + 4 CO2 + 4 kWh** live push alerts directly on your phone lock screen at each exact minute above!")
    lines.append("🎮 *Open Truck Manager when the alert buzzes to stock up!*")

    return "\n".join(lines)


def schedule_alerts(top_4_diesel: list, top_4_co2: list, top_4_kwh: list, now: datetime.datetime):
    """
    Schedule exact-time push alerts via ntfy.sh:
    - 4 chances for Diesel
    - 4 chances for CO2
    - 4 chances for kWh
    """
    now_ts = int(now.timestamp())
    medals = ["🥇 #1 Lowest Today!", "🥈 #2 Lowest Today!", "🥉 #3 Lowest Today!", "4️⃣ #4 Lowest Today!"]
    d_count, c_count, k_count = 0, 0, 0

    print("\n[*] Scheduling Alerts for Top 4 Lowest Diesel Drops:")
    for rank, item in enumerate(top_4_diesel, 1):
        slot_dt = get_slot_datetime(item["time"], now)
        slot_ts = int(slot_dt.timestamp())
        time_12h = to_12h(item["time"])
        
        if slot_ts > now_ts:
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank} Rank"
            alert_msg = (
                f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
                f"       ⛽ BUY DIESEL QUICKLY • CHEAPEST NOW!\n"
                f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
                f"⏰ **Exact Time:** {time_12h} [RIGHT NOW]\n"
                f"💰 **Diesel Price:** **${item['diesel']}** ({medal_label})\n"
                f"🍃 **CO2:** ${item.get('co2', 'N/A')} | ⚡ **kWh:** ${item.get('kwh', 'N/A')}\n"
                f"🏢 **Company:** abhijaysinghlimited\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                f"Diesel prices are at their lowest point for this window!\n"
                f"👉 Open **Truck Manager** right now and fuel your fleet tanks!"
            )
            title = f"BUY DIESEL QUICKLY: ${item['diesel']} at {time_12h}"
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
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank} Rank"
            alert_msg = (
                f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
                f"       🍃 BUY CO2 QUOTAS QUICKLY!\n"
                f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
                f"⏰ **Exact Time:** {time_12h} [RIGHT NOW]\n"
                f"🌿 **CO2 Price:** **${item['co2']}** ({medal_label})\n"
                f"🏢 **Company:** abhijaysinghlimited\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                f"CO2 quota prices have dropped significantly!\n"
                f"👉 Open **Truck Manager** right now and buy cheap CO2 quotas!"
            )
            title = f"BUY CO2 QUICKLY: ${item['co2']} at {time_12h}"
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
            medal_label = medals[rank - 1] if rank <= len(medals) else f"#{rank} Rank"
            alert_msg = (
                f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
                f"       ⚡ CHARGE KWH FLEET QUICKLY!\n"
                f"🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨\n"
                f"⏰ **Exact Time:** {time_12h} [RIGHT NOW]\n"
                f"🔋 **kWh Price:** **${item['kwh']}** ({medal_label})\n"
                f"🏢 **Company:** abhijaysinghlimited\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                f"Electricity rate is at rock bottom!\n"
                f"👉 Open **Truck Manager** right now and recharge your electric trucks!"
            )
            title = f"BUY KWH QUICKLY: ${item['kwh']} at {time_12h}"
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

    print(f"\n[OK] Scheduled: {d_count} Diesel, {c_count} CO2, {k_count} kWh alerts.")


def main():
    if not ENABLED and "--force" not in sys.argv:
        print("[i] Truck alerts are currently DISABLED (ENABLED=False in script). Exiting.")
        return

    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    today_str = now.strftime("%Y-%m-%d")
    today_day_str = str(now.day)
    
    state = load_state()

    # Deduplication check: if already processed today and not forced, stop!
    if state.get("last_processed_date") == today_str and "--force" not in sys.argv:
        print(f"[OK] Truck Manager briefing & alerts for today ({today_str}) have ALREADY been sent.")
        print("     Zero duplicates sent. Once sent, it stops. (Use --force to override).")
        return

    print(f"=====================================================")
    print(f" 🚛 Truck Manager Notifier - abhijaysinghlimited")
    print(f" Current Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    print(f" ntfy Topic   : {NTFY_TOPIC}")
    print(f" Goal         : Deliver Morning Briefing & Schedule Exact-Time Alerts")
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
        title=f"Truck Manager: Daily Fuel & Energy Briefing ({current_time_12h})",
        tags="truck,clipboard,fuelpump,sparkles",
        priority="default"
    )
    if sent:
        print("[OK] Daily Briefing Notification sent successfully!")
        # Record state so it NEVER sends duplicate briefing today
        state["last_processed_date"] = today_str
        save_state(state)
    else:
        print("[!] Failed to send briefing notification.")
        return

    # 2. Schedule exact-time alerts: 4 for Diesel + 4 for CO2 + 4 for kWh
    schedule_alerts(top_4_diesel, top_4_co2, top_4_kwh, now)

    print("\n[OK] Truck Manager Notifier completed successfully (State saved). It will now stop.")


if __name__ == "__main__":
    main()
