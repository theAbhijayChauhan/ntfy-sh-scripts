"""
Energy Manager - Hourly Live Market Tracker & Emergency Alerts
Company: abhijaysinghlimited
Source: https://energymanagergame.com/ (Official Game Web Client)
Topic: abhijaysinghlimited-energy-fuel-alert

Trigger Rules (Hourly live checks):
- Oil < $1.90       -> "EMERGENCY: BUY OIL QUICKLY!"
- Coal < $1.50      -> "EMERGENCY: BUY COAL QUICKLY!"
- Hydrogen > $90.00 -> "EMERGENCY: SELL HYDROGEN QUICKLY!"
- CO2 Quota < $20.00-> "EMERGENCY: BUY CO2 QUICKLY!"
- Uranium           -> Skipped (no alert)
"""

import requests
import datetime
import os
import sys
from zoneinfo import ZoneInfo

# Ensure UTF-8 output in Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ==========================================
# CONFIGURATION
# ==========================================
NTFY_TOPIC = "abhijaysinghlimited-energy-fuel-alert"
TIMEZONE_NAME = "Asia/Kolkata"
LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)

# User Credentials
EM_EMAIL = os.getenv("EM_EMAIL", "abhijaychauhan98@duck.com")
EM_PASSWORD = os.getenv("EM_PASSWORD", "alok@singh")

# --- STRICT EMERGENCY THRESHOLDS ---
OIL_BUY_THRESHOLD = 1.90        # Alert when Oil < $1.90
COAL_BUY_THRESHOLD = 1.50       # Alert when Coal < $1.50
HYDROGEN_SELL_THRESHOLD = 90.00 # Alert when Hydrogen > $90.00+
CO2_BUY_THRESHOLD = 20.00       # Alert when CO2 Quota < $20.00
# Uranium: No alerts requested

BASE_URL = "https://energymanagergame.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def create_authenticated_session():
    """Log in to energymanagergame.com with credentials."""
    session = requests.Session()
    session.headers.update(HEADERS)

    login_url = f"{BASE_URL}/weblogin/signin.php"
    login_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/weblogin/",
        "Origin": BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
    }
    payload = {
        "mail": EM_EMAIL,
        "pass": EM_PASSWORD,
        "remember": "1"
    }
    
    res = session.post(login_url, data=payload, headers=login_headers, timeout=15)
    if "energymanagergame.com" in res.text or res.status_code == 200:
        return session
    else:
        print(f"[!] Login failed. Response: {res.text[:200]}")
        return None


def fetch_live_commodity_prices(session):
    """
    Fetch live market prices:
    - Oil, Coal, Hydrogen, CO2
    """
    market = {}
    targets = ["oil", "coal", "hydrogen", "co2"]
    
    for t in targets:
        url = f"{BASE_URL}/api/price.history.api.php?target={t}"
        try:
            r = session.get(url, timeout=10)
            if r.status_code == 200:
                history = r.json()
                if isinstance(history, list) and len(history) > 0:
                    current_price = history[-1]
                    market[t] = {
                        "current": current_price,
                        "min": min(history),
                        "max": max(history),
                        "history": history
                    }
        except Exception as e:
            print(f"[!] Error fetching {t}: {e}")

    return market


def send_to_ntfy(topic: str, message: str, title: str, tags: str = "factory,fuelpump", priority: str = "default"):
    """Send push notification to phone via ntfy.sh."""
    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Markdown": "yes"
    }
    response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
    return response.status_code == 200


def build_morning_briefing(market: dict, now: datetime.datetime) -> str:
    """
    Build the 6:30 AM Morning Briefing showing the initial commodity market status.
    """
    date_str = now.strftime("%A, %d %B %Y")
    current_time_12h = now.strftime("%I:%M %p")
    
    lines = [
        f"**⚡ Energy Manager Morning Briefing**",
        f"📅 *{date_str} at {current_time_12h} (IST)*\n",
        "📊 **CURRENT COMMODITY MARKET PRICES:**"
    ]
    
    if "oil" in market:
        lines.append(f"• 🛢️ **Oil:** **${market['oil']['current']:.2f}** (Target: < ${OIL_BUY_THRESHOLD:.2f})")
    if "coal" in market:
        lines.append(f"• 🪨 **Coal:** **${market['coal']['current']:.2f}** (Target: < ${COAL_BUY_THRESHOLD:.2f})")
    if "hydrogen" in market:
        lines.append(f"• 💧 **Hydrogen:** **${market['hydrogen']['current']:.2f}** (Peak Target: > ${HYDROGEN_SELL_THRESHOLD:.2f}+)")
    if "co2" in market:
        lines.append(f"• 🍃 **CO2 Quota:** **${market['co2']['current']:.2f}** (Target: < ${CO2_BUY_THRESHOLD:.2f})")

    lines.append("\n" + "—" * 28)
    lines.append("🚨 *Hourly checks active: You will receive emergency alerts when any target is triggered.*")

    return "\n".join(lines)


def check_emergency_conditions(market: dict, current_time_12h: str):
    """
    Check exact threshold conditions and send emergency alerts immediately:
    - Oil < $1.90
    - Coal < $1.50
    - Hydrogen > $90.00
    - CO2 < $20.00
    """
    sent_count = 0

    # 1. Oil Condition: Oil < $1.90
    if "oil" in market and market["oil"]["current"] < OIL_BUY_THRESHOLD:
        oil_price = market["oil"]["current"]
        title = f"BUY OIL QUICKLY (${oil_price:.2f})"
        msg = (
            f"🚨 **EMERGENCY ALERT: BUY OIL QUICKLY!**\n\n"
            f"• Time: **{current_time_12h}**\n"
            f"• Current Oil Price: **${oil_price:.2f}** (Below target < ${OIL_BUY_THRESHOLD:.2f})!\n\n"
            f"👉 Open Energy Manager right now and purchase oil for your power plants!"
        )
        if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,fuelpump,warning", priority="urgent"):
            print(f"  [OK] Emergency Alert Sent: BUY OIL QUICKLY (${oil_price:.2f})")
            sent_count += 1

    # 2. Coal Condition: Coal < $1.50
    if "coal" in market and market["coal"]["current"] < COAL_BUY_THRESHOLD:
        coal_price = market["coal"]["current"]
        title = f"BUY COAL QUICKLY (${coal_price:.2f})"
        msg = (
            f"🚨 **EMERGENCY ALERT: BUY COAL QUICKLY!**\n\n"
            f"• Time: **{current_time_12h}**\n"
            f"• Current Coal Price: **${coal_price:.2f}** (Below target < ${COAL_BUY_THRESHOLD:.2f})!\n\n"
            f"👉 Open Energy Manager right now and stock up coal for your power plants!"
        )
        if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,fire,warning", priority="urgent"):
            print(f"  [OK] Emergency Alert Sent: BUY COAL QUICKLY (${coal_price:.2f})")
            sent_count += 1

    # 3. Hydrogen Condition: Hydrogen > $90.00
    if "hydrogen" in market and market["hydrogen"]["current"] > HYDROGEN_SELL_THRESHOLD:
        h2_price = market["hydrogen"]["current"]
        title = f"SELL HYDROGEN QUICKLY (${h2_price:.2f})"
        msg = (
            f"🚨 **EMERGENCY ALERT: SELL HYDROGEN QUICKLY!**\n\n"
            f"• Time: **{current_time_12h}**\n"
            f"• Market Value: **${h2_price:.2f}** (PEAK above > ${HYDROGEN_SELL_THRESHOLD:.2f}+)!\n\n"
            f"👉 Open Hydrogen Exchange (hydrogen-exchange.php) and SELL stored hydrogen now for peak profit!"
        )
        if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,money_with_wings,zap", priority="urgent"):
            print(f"  [OK] Emergency Alert Sent: SELL HYDROGEN QUICKLY (${h2_price:.2f})")
            sent_count += 1

    # 4. CO2 Condition: CO2 < $20.00
    if "co2" in market and market["co2"]["current"] < CO2_BUY_THRESHOLD:
        co2_price = market["co2"]["current"]
        title = f"BUY CO2 QUICKLY (${co2_price:.2f})"
        msg = (
            f"🚨 **EMERGENCY ALERT: BUY CO2 QUICKLY!**\n\n"
            f"• Time: **{current_time_12h}**\n"
            f"• CO2 Quota Price: **${co2_price:.2f}** (Below target < ${CO2_BUY_THRESHOLD:.2f})!\n\n"
            f"👉 Open Energy Manager right now and buy CO2 quotas immediately!"
        )
        if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,recycle,warning", priority="urgent"):
            print(f"  [OK] Emergency Alert Sent: BUY CO2 QUICKLY (${co2_price:.2f})")
            sent_count += 1

    if sent_count == 0:
        print("[OK] All commodity prices are currently within normal ranges. Zero spam sent.")


def main():
    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    
    # Check if this run is specifically for morning briefing (e.g. 6:30 AM or --briefing flag)
    is_morning_briefing = ("--briefing" in sys.argv) or (now.hour == 6 and now.minute >= 25 and now.minute <= 45)
    
    print(f"=====================================================")
    print(f" Energy Manager Live Tracker - abhijaysinghlimited")
    print(f" Current Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    print(f" ntfy Topic   : {NTFY_TOPIC}")
    print(f" Mode         : {'Morning Briefing + Live Check' if is_morning_briefing else 'Hourly Live Check'}")
    print(f"=====================================================\n")

    print("[*] Logging in to energymanagergame.com...")
    session = create_authenticated_session()
    if not session:
        print("[!] Failed to log in.")
        return

    print("[OK] Logged in successfully!")
    print("[*] Fetching live commodity prices...")
    market = fetch_live_commodity_prices(session)

    if not market:
        print("[!] No market data retrieved.")
        return

    print(f"[OK] Current Prices:")
    print(f"     • Oil      : ${market.get('oil', {}).get('current', 'N/A')}")
    print(f"     • Coal     : ${market.get('coal', {}).get('current', 'N/A')}")
    print(f"     • Hydrogen : ${market.get('hydrogen', {}).get('current', 'N/A')}")
    print(f"     • CO2 Quota: ${market.get('co2', {}).get('current', 'N/A')}")

    # 1. Send morning briefing if it's the 6:30 AM run or --briefing is passed
    if is_morning_briefing:
        briefing_msg = build_morning_briefing(market, now)
        print("\n--- MORNING BRIEFING PREVIEW ---")
        print(briefing_msg)
        print("--------------------------------\n")
        print(f"[*] Sending 6:30 AM briefing to ntfy.sh/{NTFY_TOPIC}...")
        send_to_ntfy(
            topic=NTFY_TOPIC,
            message=briefing_msg,
            title=f"Energy Manager: Morning Market Briefing ({current_time_12h})",
            tags="factory,clipboard,zap",
            priority="default"
        )
        print("[OK] Morning Briefing sent successfully!")

    # 2. Check emergency threshold conditions (Oil < 1.9, Coal < 1.5, Hydrogen > 90, CO2 < 20)
    print("\n[*] Checking Emergency Conditions (Oil < 1.9, Coal < 1.5, H2 > 90, CO2 < 20)...")
    check_emergency_conditions(market, current_time_12h)

    print("\n[OK] Energy Manager check completed successfully.")


if __name__ == "__main__":
    main()
