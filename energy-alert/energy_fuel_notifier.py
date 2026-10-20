"""
⚡ Energy Manager - Hourly Live Market Tracker & Strict Emergency Alerts
🏢 Company: abhijaysinghlimited
🎯 Source: https://energymanagergame.com/ (Official Game Web Client)
🔔 Topic: abhijaysinghlimited-energy-fuel-alert

✨ Strict Rules:
1. Hourly Check: Checks live prices every hour.
2. Zero Routine Spam: ONLY sends a message if at least ONE commodity is in target range:
   - 🛢️ Oil < $1.90 ➜ BUY OIL QUICKLY
   - 🪨 Coal < $1.50 ➜ BUY COAL QUICKLY
   - 💧 Hydrogen > $90.00+ ➜ SELL HYDROGEN QUICKLY
   - 🍃 CO2 Quotas < $20.00 ➜ BUY CO2 QUICKLY
   - Uranium: Ignored.
3. If all prices are normal: COMPLETELY SILENT (Zero notifications sent).
4. Deduplication: Alerts sent EXACTLY ONCE per price dip. Does not repeat every hour while price remains low.
"""

import requests
import datetime
import os
import sys
import json
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

STATE_FILE = os.path.join(os.path.dirname(__file__), "energy_state.json")

# User Credentials
EM_EMAIL = os.getenv("EM_EMAIL", "abhijaychauhan98@duck.com")
EM_PASSWORD = os.getenv("EM_PASSWORD", "alok@singh")

# --- STRICT EMERGENCY THRESHOLDS ---
OIL_BUY_THRESHOLD = 1.90        # Alert when Oil < $1.90
COAL_BUY_THRESHOLD = 1.50       # Alert when Coal < $1.50
HYDROGEN_SELL_THRESHOLD = 90.00 # Alert when Hydrogen > $90.00+
CO2_BUY_THRESHOLD = 20.00       # Alert when CO2 Quota < $20.00

BASE_URL = "https://energymanagergame.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def load_state() -> dict:
    """Load persistent alert state to prevent duplicate notifications."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "oil_alerted": False,
        "coal_alerted": False,
        "hydrogen_alerted": False,
        "co2_alerted": False,
        "last_briefing_date": None
    }


def save_state(state: dict):
    """Save persistent alert state."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[!] Warning: Could not save state: {e}")


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
    Optional Manual Market Briefing (Only sent if explicitly called with --briefing).
    """
    date_str = now.strftime("%A, %d %B %Y")
    current_time_12h = now.strftime("%I:%M %p")
    
    lines = [
        "⚡ ━━━━━━━━━━━━━━━━━━━━━━━━━ ⚡",
        "      ENERGY MANAGER • MARKET BRIEFING",
        "             abhijaysinghlimited",
        "⚡ ━━━━━━━━━━━━━━━━━━━━━━━━━ ⚡",
        f"📅 **Date:** {date_str} | ⏰ **Time:** {current_time_12h} IST",
        f"📡 **Account:** `{EM_EMAIL}`",
        "",
        "📊 ━━━ 🌐 LIVE COMMODITY SNAPSHOT ━━━ 📊"
    ]
    
    if "oil" in market:
        curr = market['oil']['current']
        status = "🟢 CRITICAL BUY!" if curr < OIL_BUY_THRESHOLD else "⏳ NORMAL"
        lines.append(f"• 🛢️ **Oil:** **${curr:.2f}** *(Target: < ${OIL_BUY_THRESHOLD:.2f})* {status}")
    if "coal" in market:
        curr = market['coal']['current']
        status = "🟢 CRITICAL BUY!" if curr < COAL_BUY_THRESHOLD else "⏳ NORMAL"
        lines.append(f"• 🪨 **Coal:** **${curr:.2f}** *(Target: < ${COAL_BUY_THRESHOLD:.2f})* {status}")
    if "hydrogen" in market:
        curr = market['hydrogen']['current']
        status = "🚀 PEAK SELL!" if curr > HYDROGEN_SELL_THRESHOLD else "⏳ HOLDING"
        lines.append(f"• 💧 **Hydrogen:** **${curr:.2f}** *(Target: > ${HYDROGEN_SELL_THRESHOLD:.2f}+)* {status}")
    if "co2" in market:
        curr = market['co2']['current']
        status = "🟢 CRITICAL BUY!" if curr < CO2_BUY_THRESHOLD else "⏳ NORMAL"
        lines.append(f"• 🍃 **CO2 Quota:** **${curr:.2f}** *(Target: < ${CO2_BUY_THRESHOLD:.2f})* {status}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🚨 **STRICT RADAR ACTIVE:** Alerts only fire when a commodity enters target range!")
    return "\n".join(lines)


def check_emergency_conditions(market: dict, state: dict, current_time_12h: str) -> tuple[dict, int]:
    """
    Check exact threshold conditions and send emergency alert ONCE per dip:
    - Oil < $1.90
    - Coal < $1.50
    - Hydrogen > $90.00
    - CO2 < $20.00
    
    Returns (state, alerts_sent_count)
    """
    alerts_sent = 0

    # 1. Oil Condition (< $1.90)
    if "oil" in market:
        oil_price = market["oil"]["current"]
        if oil_price < OIL_BUY_THRESHOLD:
            if not state.get("oil_alerted", False):
                title = f"BUY OIL QUICKLY (${oil_price:.2f})"
                msg = (
                    f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                    f"          🛢️ BUY OIL QUICKLY! CRASH DETECTED!\n"
                    f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                    f"⏰ **Detected At:** {current_time_12h} IST [LIVE]\n"
                    f"💰 **Current Price:** **${oil_price:.2f}** *(Below Target < ${OIL_BUY_THRESHOLD:.2f})*\n"
                    f"📉 **Market Status:** ROCK BOTTOM BUY WINDOW\n"
                    f"🏢 **Account:** `{EM_EMAIL}`\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                    f"Oil price has crashed below your buy threshold!\n"
                    f"👉 Open **Energy Manager** right now and purchase full oil reserves!"
                )
                if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,fuelpump,warning", priority="urgent"):
                    print(f"  [OK] Alert Sent: BUY OIL QUICKLY (${oil_price:.2f})")
                    state["oil_alerted"] = True
                    alerts_sent += 1
            else:
                print(f"  [-] Oil is low (${oil_price:.2f}) but already alerted previously. Zero spam.")
        else:
            if state.get("oil_alerted", False):
                print(f"  [+] Oil price has recovered (${oil_price:.2f}). Resetting alert state.")
                state["oil_alerted"] = False

    # 2. Coal Condition (< $1.50)
    if "coal" in market:
        coal_price = market["coal"]["current"]
        if coal_price < COAL_BUY_THRESHOLD:
            if not state.get("coal_alerted", False):
                title = f"BUY COAL QUICKLY (${coal_price:.2f})"
                msg = (
                    f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                    f"          🪨 BUY COAL QUICKLY! CRASH DETECTED!\n"
                    f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                    f"⏰ **Detected At:** {current_time_12h} IST [LIVE]\n"
                    f"💰 **Current Price:** **${coal_price:.2f}** *(Below Target < ${COAL_BUY_THRESHOLD:.2f})*\n"
                    f"📉 **Market Status:** ROCK BOTTOM BUY WINDOW\n"
                    f"🏢 **Account:** `{EM_EMAIL}`\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                    f"Coal price has crashed below your buy threshold!\n"
                    f"👉 Open **Energy Manager** right now and stock up coal reserves!"
                )
                if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,fire,warning", priority="urgent"):
                    print(f"  [OK] Alert Sent: BUY COAL QUICKLY (${coal_price:.2f})")
                    state["coal_alerted"] = True
                    alerts_sent += 1
            else:
                print(f"  [-] Coal is low (${coal_price:.2f}) but already alerted previously. Zero spam.")
        else:
            if state.get("coal_alerted", False):
                print(f"  [+] Coal price has recovered (${coal_price:.2f}). Resetting alert state.")
                state["coal_alerted"] = False

    # 3. Hydrogen Condition (> $90.00+)
    if "hydrogen" in market:
        h2_price = market["hydrogen"]["current"]
        if h2_price > HYDROGEN_SELL_THRESHOLD:
            if not state.get("hydrogen_alerted", False):
                title = f"SELL HYDROGEN QUICKLY (${h2_price:.2f})"
                msg = (
                    f"🚀🚀🚀 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚀🚀🚀\n"
                    f"        💧 SELL HYDROGEN QUICKLY! PEAK SPIKE!\n"
                    f"🚀🚀🚀 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚀🚀🚀\n"
                    f"⏰ **Detected At:** {current_time_12h} IST [LIVE]\n"
                    f"💰 **Market Value:** **${h2_price:.2f}** *(PEAK: Above > ${HYDROGEN_SELL_THRESHOLD:.2f}+)*\n"
                    f"📈 **Market Status:** MAXIMUM PROFIT WINDOW\n"
                    f"🏢 **Account:** `{EM_EMAIL}`\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                    f"Hydrogen has surged past $90+ on the global exchange!\n"
                    f"👉 Open **Hydrogen Exchange** (`hydrogen-exchange.php`) and SELL stored hydrogen now for peak revenue!"
                )
                if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,money_with_wings,zap", priority="urgent"):
                    print(f"  [OK] Alert Sent: SELL HYDROGEN QUICKLY (${h2_price:.2f})")
                    state["hydrogen_alerted"] = True
                    alerts_sent += 1
            else:
                print(f"  [-] Hydrogen is at peak (${h2_price:.2f}) but already alerted previously. Zero spam.")
        else:
            if state.get("hydrogen_alerted", False):
                print(f"  [+] Hydrogen price normalized (${h2_price:.2f}). Resetting alert state.")
                state["hydrogen_alerted"] = False

    # 4. CO2 Condition (< $20.00)
    if "co2" in market:
        co2_price = market["co2"]["current"]
        if co2_price < CO2_BUY_THRESHOLD:
            if not state.get("co2_alerted", False):
                title = f"BUY CO2 QUICKLY (${co2_price:.2f})"
                msg = (
                    f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                    f"          🍃 BUY CO2 QUOTAS QUICKLY!\n"
                    f"🚨🚨🚨 ━━━━━━━━━━━━━━━━━━━━━━━━━ 🚨🚨🚨\n"
                    f"⏰ **Detected At:** {current_time_12h} IST [LIVE]\n"
                    f"💰 **Current Price:** **${co2_price:.2f}** *(Below Target < ${CO2_BUY_THRESHOLD:.2f})*\n"
                    f"📉 **Market Status:** ROCK BOTTOM BUY WINDOW\n"
                    f"🏢 **Account:** `{EM_EMAIL}`\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 **IMMEDIATE ACTION REQUIRED:**\n"
                    f"CO2 quota prices have dropped below your $20 target!\n"
                    f"👉 Open **Energy Manager** right now and buy CO2 quotas immediately!"
                )
                if send_to_ntfy(NTFY_TOPIC, msg, title, tags="rotating_light,recycle,warning", priority="urgent"):
                    print(f"  [OK] Alert Sent: BUY CO2 QUICKLY (${co2_price:.2f})")
                    state["co2_alerted"] = True
                    alerts_sent += 1
            else:
                print(f"  [-] CO2 is low (${co2_price:.2f}) but already alerted previously. Zero spam.")
        else:
            if state.get("co2_alerted", False):
                print(f"  [+] CO2 price has recovered (${co2_price:.2f}). Resetting alert state.")
                state["co2_alerted"] = False

    return state, alerts_sent


def main():
    now = datetime.datetime.now(LOCAL_TZ)
    current_time_12h = now.strftime("%I:%M %p")
    today_str = now.strftime("%Y-%m-%d")
    
    # Load persistent state
    state = load_state()

    # Rule: ONLY send routine briefing if explicitly called with --briefing
    # On all normal hourly checks: ZERO routine messages. ONLY ping if commodity is in range!
    should_send_briefing = ("--briefing" in sys.argv)

    print(f"=====================================================")
    print(f" ⚡ Energy Manager Live Tracker - abhijaysinghlimited")
    print(f" Current Time : {now.strftime('%Y-%m-%d %I:%M:%S %p')} ({TIMEZONE_NAME})")
    print(f" ntfy Topic   : {NTFY_TOPIC}")
    print(f" Policy       : SILENT unless commodity is in range")
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

    oil_curr = market.get('oil', {}).get('current', 'N/A')
    coal_curr = market.get('coal', {}).get('current', 'N/A')
    h2_curr = market.get('hydrogen', {}).get('current', 'N/A')
    co2_curr = market.get('co2', {}).get('current', 'N/A')

    print(f"[OK] Current Prices:")
    print(f"     • Oil      : ${oil_curr} (Target: < ${OIL_BUY_THRESHOLD:.2f})")
    print(f"     • Coal     : ${coal_curr} (Target: < ${COAL_BUY_THRESHOLD:.2f})")
    print(f"     • Hydrogen : ${h2_curr} (Target: > ${HYDROGEN_SELL_THRESHOLD:.2f}+)")
    print(f"     • CO2 Quota: ${co2_curr} (Target: < ${CO2_BUY_THRESHOLD:.2f})")

    # 1. Manual Briefing (Only if --briefing was passed)
    if should_send_briefing:
        briefing_msg = build_morning_briefing(market, now)
        print("\n[*] Sending manual briefing to ntfy.sh/{NTFY_TOPIC}...")
        send_to_ntfy(
            topic=NTFY_TOPIC,
            message=briefing_msg,
            title=f"Energy Manager: Market Status ({current_time_12h})",
            tags="factory,clipboard,zap",
            priority="default"
        )
        print("[OK] Briefing sent successfully!")
        state["last_briefing_date"] = today_str

    # 2. Check emergency threshold conditions (Alert sent ONLY if price is in range)
    print("\n[*] Checking Emergency Conditions...")
    state, alerts_sent = check_emergency_conditions(market, state, current_time_12h)

    if alerts_sent == 0:
        print("[i] All commodity prices are currently outside alert range.")
        print("[i] Policy enforced: ZERO messages sent to phone.")
    else:
        print(f"[OK] Total emergency alerts sent: {alerts_sent}")

    # Save state
    save_state(state)
    print("\n[OK] Energy Manager check completed successfully (State saved).")


if __name__ == "__main__":
    main()
