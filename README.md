# 🎮 Trophy Games Automated Price Tracker & Alert System
### Built for **abhijaysinghlimited** · 100% Free · Cloud-Automated 24/7

An automated tracking and push notification system for **Trophy Games** titles:
* **Train Manager** (Fuel & Spot Power)
* **Truck Manager** (Diesel, CO2 Quotas, & kWh Electricity)
* **Energy Manager** (Oil, Coal, Hydrogen, & CO2 Quotas)

Delivers beautifully formatted morning briefings and **exact-time emergency buy/sell alerts** straight to your phone lock screen via [**ntfy.sh**](https://ntfy.sh) with zero server costs using **GitHub Actions**.

---

## 📱 Mobile App Setup (`ntfy`)

The system uses [**ntfy.sh**](https://ntfy.sh), a free, open-source push notification service that requires **no login, no accounts, and no credit card**.

### Step 1: Install the App
* **Android:** Download **ntfy** on [Google Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy) or [F-Droid](https://f-droid.org/packages/io.heckel.ntfy/).
* **iOS (iPhone/iPad):** Download **ntfy** on the [Apple App Store](https://apps.apple.com/app/ntfy/id1625396347).
* **Web (PC/Browser):** You can also view notifications live in any web browser without installing anything!

---

### Step 2: Subscribe to Your 3 Private Game Topics
Open the **ntfy** app on your phone, tap the **`+`** (Plus) button in the bottom right corner, and subscribe to these 3 topics:

| Game | Topic Name to Type in App | Live Web Stream Link |
| :--- | :--- | :--- |
| **🚆 Train Manager** | `abhijaysinghlimited-train-fuel-alert` | [ntfy.sh/abhijaysinghlimited-train-fuel-alert](https://ntfy.sh/abhijaysinghlimited-train-fuel-alert) |
| **🚛 Truck Manager** | `abhijaysinghlimited-truck-fuel-alert` | [ntfy.sh/abhijaysinghlimited-truck-fuel-alert](https://ntfy.sh/abhijaysinghlimited-truck-fuel-alert) |
| **⚡ Energy Manager** | `abhijaysinghlimited-energy-fuel-alert` | [ntfy.sh/abhijaysinghlimited-energy-fuel-alert](https://ntfy.sh/abhijaysinghlimited-energy-fuel-alert) |

> 💡 **Tip:** Tap on each topic in the app, open **Settings**, and ensure **Default Priority** is set to high, with vibration and sound enabled so you never miss an alert.

---

### Step 3: Phone Battery Optimization (Crucial)
Phones often put idle apps to sleep. To guarantee notifications arrive without delay:
1. Long-press the **ntfy** app icon on your home screen -> Tap **App Info (ℹ️)**.
2. Go to **Battery** or **App battery usage**.
3. Set it to **Unrestricted** (or disable "Battery Optimization").

---

## 🧠 How the System Works Under the Hood

### The Architecture Flow

```
┌──────────────────────────────────────────────┐
│  GitHub Actions (Free Cloud Scheduler)       │
│                                              │
│  - 05:53 AM / 06:07 AM IST: Train & Truck    │
│  - Every Hour (:18 min): Energy Manager      │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  Python Notifier Scripts                     │
│                                              │
│  - Fetches live market feeds / game APIs     │
│  - Converts times to 12-Hour AM/PM format    │
│  - Finds Top 4 / Emergency Price Thresholds  │
└──────────────────────┬───────────────────────┘
                       │
                       ▼ (HTTP POST with 'At' unix header)
┌──────────────────────────────────────────────┐
│  ntfy.sh Cloud Server (Go Pub/Sub Engine)    │
│                                              │
│  - Delivers morning briefing instantly       │
│  - HOLDS exact-time alerts until target time │
└──────────────────────┬───────────────────────┘
                       │
                       ▼ (Push notification packet)
┌──────────────────────────────────────────────┐
│  Google FCM (Android) / Apple APNs (iOS)     │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  📱 Your Phone Lock Screen Rings & Vibrates! │
└──────────────────────────────────────────────┘
```

### The Secret Weapon: The `At` Header
Why don't you need a computer running 24/7?
When the script runs in the morning, it detects future cheap price times (for example, fuel dropping to \$2,000 at `01:30 PM`).
Instead of running a loop all day, Python sends the alert to `ntfy.sh` with the header:
```http
At: 1792483800  <-- Exact Unix timestamp for 01:30 PM
```
The `ntfy.sh` server holds the message in its queue and releases it directly to your phone at **exactly 01:30 PM**!

---

## 🎮 Game Rules & Logic Breakdown

### 1. 🚆 Train Manager ([`train-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/train-alert/))
* **Data Feed:** `https://api.mgtools.cloud/v1/fuel-price/train`
* **Timing:** Analyzes the full 24-hour cycle in your local time (`Asia/Kolkata`).
* **Rule:**
  1. **Daily Morning Briefing:** Sent once per day with the **Top 4 Lowest Fuel Times** and **Top 4 Lowest Spot Times**, styled with ranking medals (🥇, 🥈, 🥉, 4️⃣), exact prices, and badges.
  2. **Exact-Time Alerts:** Pre-schedules alerts to buzz your phone at the exact times of the **Top 4 lowest Fuel prices** and **Top 4 lowest Spot prices**.

---

### 2. 🚛 Truck Manager ([`truck-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/truck-alert/))
* **Data Feed:** `https://api.mgtools.cloud/v1/fuel-price/truck`
* **Rule:**
  1. **Daily Morning Briefing:** Sent once per day with the **Top 4 Lowest Diesel**, **Top 4 Lowest CO2 Quota**, and **Top 4 Lowest kWh Electricity** times.
  2. **Exact-Time Alerts:** Pre-schedules alerts for each commodity:
     * 4 chances for Diesel (sent at the 4 lowest Diesel times).
     * 4 chances for CO2 (sent at the 4 lowest CO2 times).
     * 4 chances for kWh (sent at the 4 lowest kWh electricity times).

---

### 3. ⚡ Energy Manager ([`energy-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/energy-alert/))
* **Data Feed:** `https://energymanagergame.com` (Direct live account session).
* **Rule:**
  1. **Hourly Price Radar:** Checks market prices every hour.
  2. **Strict Silent Policy:** Zero routine messages sent if prices are outside target range.
  3. **Emergency Alerts (Sent ONCE per Dip only when in range):**
     * 🛢️ **Oil < \$1.90** ➜ `BUY OIL QUICKLY`
     * 🪨 **Coal < \$1.50** ➜ `BUY COAL QUICKLY`
     * 💧 **Hydrogen > \$90.00+** ➜ `SELL HYDROGEN QUICKLY`
     * 🍃 **CO2 Quotas < \$20.00** ➜ `BUY CO2 QUICKLY`

---

## 💻 100% Fail-Safe Backup (Windows Task Scheduler)

GitHub Actions runs 100% free in the cloud. However, public GitHub Actions runners can occasionally delay cron triggers during peak traffic.
To guarantee 100% reliability, you can install a local backup task on your Windows PC:

1. Right-click [`setup_windows_backup.bat`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/setup_windows_backup.bat) -> **Run as Administrator**.
2. It registers a silent background task in **Windows Task Scheduler** that runs hourly.
3. **Zero Conflicts:** Because state files record whether the briefing was already sent or alerts were scheduled, the local runner and GitHub Actions will **NEVER send duplicate messages**!

---

## 💻 Manual Local Testing (From Your PC)

If you ever want to run the scripts manually on your own computer:

```powershell
# Run Master Runner (Checks all 3 games in sequence)
python run_all_alerts.py

# Force send morning briefings right now:
python run_all_alerts.py --force

# Or test individual games:
python train-alert/train_fuel_notifier.py --force
python truck-alert/truck_fuel_notifier.py --force
python energy-alert/energy_fuel_notifier.py --force
```

---

## 🛡️ Anti-Spam & Deduplication System (Once-Only Guarantee)

1. **Energy Manager Deduplication (`energy_state.json`):**
   * When Coal drops below \$1.50 (or Oil < \$1.90, Hydrogen > \$90, CO2 < \$20), you receive the emergency alert **EXACTLY ONCE**.
   * It will **NOT** alert you again on following hours while the price stays low.
   * The alert resets only when the price recovers back above the threshold, ready for the next drop!

2. **Train & Truck Daily State (`train_state.json` / `truck_state.json`):**
   * Morning briefings and exact-time alerts are scheduled **EXACTLY ONCE PER DAY**.
   * Any duplicate executions on the same day detect the existing schedule and safely exit with zero duplicate messages.

---

## 🛠️ Maintenance & FAQ

#### Q: How do I change an alert threshold in the future?
Open `energy-alert/energy_fuel_notifier.py` and edit the constants near the top of the file:
```python
OIL_BUY_THRESHOLD = 1.90        # Alert when Oil < $1.90
COAL_BUY_THRESHOLD = 1.50       # Alert when Coal < $1.50
HYDROGEN_SELL_THRESHOLD = 90.00 # Alert when Hydrogen > $90.00+
CO2_BUY_THRESHOLD = 20.00       # Alert when CO2 Quota < $20.00
```

#### Q: What if my Energy Manager password changes?
Simply update `EM_PASSWORD` in `energy-alert/energy_fuel_notifier.py`, or set the `EM_PASSWORD` secret in your GitHub repository settings under **Settings -> Secrets and variables -> Actions**.
