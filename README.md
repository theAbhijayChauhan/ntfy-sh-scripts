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

## 🛑 How to Stop or Pause Any Alert (e.g., Truck Alerts)

If you ever want to stop receiving alerts for one specific game (like Truck Manager):

### Method 1: Instant Mute from Your Phone (Easiest - 5 Seconds)
1. Open the **ntfy** app on your phone.
2. Tap on `abhijaysinghlimited-truck-fuel-alert`.
3. Tap the **3 dots (Menu)** in the top right -> Tap **Unsubscribe** (or set **Mute** / disable notifications).
4. That's it! Your phone will immediately stop ringing for truck alerts.

### Method 2: Toggle `ENABLED = False` in the Script
Every script has a master switch at the very top:
* Open [`truck-alert/truck_fuel_notifier.py`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/truck-alert/truck_fuel_notifier.py).
* Change line 20 from:
  ```python
  ENABLED = True
  ```
  to:
  ```python
  ENABLED = False
  ```
* Commit and push to GitHub. The script will immediately exit and send nothing.

### Method 3: In GitHub Actions Workflow
In [`.github/workflows/daily_briefing_scheduler.yml`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/.github/workflows/daily_briefing_scheduler.yml), comment out the truck step by adding `#`:
```yaml
# - name: Run Truck Manager Notifier (4 Diesel + 4 CO2 + 4 kWh)
#   run: |
#     python truck-alert/truck_fuel_notifier.py
```

---

## 🎮 Game Rules & Retry Windows Breakdown

### 1. 🚆 Train Manager ([`train-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/train-alert/))
* **Continuous Morning Window (06:00 AM – 07:00 AM IST):**
  - Tries repeatedly every 10 minutes between 6:00 AM and 7:00 AM IST until today's morning briefing is sent.
  - **Once sent, it immediately stops!** Subsequent runs see that today is already completed and safely exit in 1 second with zero duplicate messages.
* **Exact-Time Alerts:** Pre-schedules alerts to buzz your phone at the exact times of the **Top 4 lowest Fuel prices** and **Top 4 lowest Spot prices**.

---

### 2. 🚛 Truck Manager ([`truck-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/truck-alert/))
* **Continuous Morning Window (06:00 AM – 07:00 AM IST):**
  - Tries repeatedly every 10 minutes between 6:00 AM and 7:00 AM IST until today's morning briefing is sent.
  - **Once sent, it immediately stops!**
* **Exact-Time Alerts:** Pre-schedules alerts for each commodity:
  * 4 chances for Diesel (sent at the 4 lowest Diesel times).
  * 4 chances for CO2 (sent at the 4 lowest CO2 times).
  * 4 chances for kWh (sent at the 4 lowest kWh electricity times).

---

### 3. ⚡ Energy Manager ([`energy-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/energy-alert/))
* **Continuous Morning Window (06:30 AM – 07:30 AM IST):**
  - Tries repeatedly every 10 minutes between 6:30 AM and 7:30 AM IST until today's market briefing is sent.
  - **Once sent, it stops sending briefings for today.**
* **Silent Hourly Price Radar (Rest of the Day):**
  - Checks live market prices every hour.
  - **Strictly silent:** Zero messages sent if prices are outside range.
* **Strict Emergency Alerts (Sent ONCE per Dip only when in range):**
  * 🛢️ **Oil < \$1.90** ➜ `BUY OIL QUICKLY`
  * 🪨 **Coal < \$1.50** ➜ `BUY COAL QUICKLY`
  * 💧 **Hydrogen > \$90.00+** ➜ `SELL HYDROGEN QUICKLY`
  * 🍃 **CO2 Quotas < \$20.00** ➜ `BUY CO2 QUICKLY`

---

## 💻 100% Fail-Safe Backup (Windows Task Scheduler)

GitHub Actions runs 100% free in the cloud. However, public GitHub Actions runners can occasionally delay cron triggers during peak global traffic.
To guarantee 100% reliability, you can install a local backup task on your Windows PC:

1. Right-click [`setup_windows_backup.bat`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/setup_windows_backup.bat) -> **Run as Administrator**.
2. It registers a silent background task in **Windows Task Scheduler** that runs every 15 minutes.
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
