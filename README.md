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

### Step 3: Android Battery Optimization (Important)
Android often puts idle apps to sleep. To guarantee notifications arrive at the exact second:
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
│  - 06:00 AM IST: Train & Truck Manager       │
│  - Every Hour (6:30 AM+): Energy Manager     │
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
When the script runs at 6:00 AM, it detects future cheap price times (for example, fuel dropping to \$2,000 at `11:30 PM`).
Instead of running a loop all day, Python sends the alert to `ntfy.sh` with the header:
```http
At: 1792432800  <-- Exact Unix timestamp for 11:30 PM
```
The `ntfy.sh` server holds the message in its queue and releases it directly to your phone at **exactly 11:30 PM**!

---

## 🎮 Game Rules & Logic Breakdown

### 1. 🚆 Train Manager ([`train-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/train-alert/))
* **Data Feed:** `https://api.mgtools.cloud/v1/fuel-price/train`
* **Timing:** Analyzes the full 24-hour cycle in your local time (`Asia/Kolkata`).
* **Morning Briefing (06:00 AM IST):**
  * 🥇 🥈 🥉 4️⃣ **Top 4 Best Times to Buy Fuel Today**
  * 🥇 🥈 🥉 4️⃣ **Top 4 Best Times to Buy Spot Power Today**
* **Exact-Time Alerts (Strict 4-Chance Rule):**
  * **4 Fuel Alerts:** Sent at the exact minutes of the 4 lowest Fuel prices.
  * **4 Spot Alerts:** Sent at the exact minutes of the 4 lowest Spot prices.
  * *Zero spam in between!*

---

### 2. 🚛 Truck Manager ([`truck-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/truck-alert/))
* **Data Feed:** `https://api.mgtools.cloud/v1/fuel-price/truck`
* **Timing:** Analyzes the full 24-hour cycle in your local time (`Asia/Kolkata`).
* **Morning Briefing (06:00 AM IST):**
  * ⛽ **Top 4 Best Times to Buy Diesel Today** (with CO2 and kWh values)
  * 🍃 **Top 4 Best Times to Buy CO2 Quotas Today**
  * ⚡ **Top 4 Best Times to Charge kWh Electricity Today**
* **Exact-Time Alerts (Strict 4-Chance Rule):**
  * **4 Diesel Alerts:** Sent at the exact minutes of the 4 lowest Diesel prices.
  * **4 CO2 Alerts:** Sent at the exact minutes of the 4 lowest CO2 prices.
  * **4 kWh Alerts:** Sent at the exact minutes of the 4 lowest kWh prices.
  * *Total: 12 exact alerts across the day.*

---

### 3. ⚡ Energy Manager ([`energy-alert/`](file:///c:/Users/abhij/OneDrive/Desktop/Ntfy%20sh/energy-alert/))
* **Data Feed:** Official Game Web Client ([`energymanagergame.com`](https://energymanagergame.com/))
* **Account:** Authenticates securely via your verified account (`abhijaychauhan98@duck.com`).
* **Schedule:** Checks live market prices **every hour starting at 06:30 AM IST**.
* **Morning Briefing (06:30 AM IST):** Shows the opening commodity prices and 20-hour market trends.
* **Emergency Triggers (High Priority Push):**

| Commodity | Trigger Condition | Phone Alert Notification | Action |
| :--- | :--- | :--- | :--- |
| 🛢️ **Oil** | **$<\$1.90$** | **`🚨 BUY OIL QUICKLY ($X.XX)`** | Buy plant fuel immediately before the price rises! |
| 🪨 **Coal** | **$<\$1.50$** | **`🚨 BUY COAL QUICKLY ($X.XX)`** | Stock up coal for your thermal power plants! |
| 💧 **Hydrogen** | **$>\$90.00+$** | **`🚨 SELL HYDROGEN QUICKLY ($X.XX)`** | Open Hydrogen Exchange and SELL stored hydrogen for peak profit! |
| 🍃 **CO2 Quota** | **$<\$20.00$** | **`🚨 BUY CO2 QUICKLY ($X.XX)`** | Buy cheap carbon credits to offset emissions! |
| ☢️ **Uranium** | *None* | Skipped (No alerts) | Ignored as requested. |

---

## 📁 Project Directory Structure

```
Ntfy sh/
│
├── README.md                          <-- Comprehensive documentation (this file)
├── requirements.txt                   <-- Python dependencies for GitHub Actions
│
├── .github/
│   └── workflows/
│       ├── daily_briefing_scheduler.yml  <-- Runs at 06:00 AM IST (Train & Truck)
│       └── energy_hourly_tracker.yml     <-- Runs every hour from 06:30 AM IST (Energy)
│
├── train-alert/
│   ├── requirements.txt
│   └── train_fuel_notifier.py         <-- Train Manager Engine (4 Fuel + 4 Spot)
│
├── truck-alert/
│   ├── requirements.txt
│   └── truck_fuel_notifier.py         <-- Truck Manager Engine (4 Diesel + 4 CO2 + 4 kWh)
│
└── energy-alert/
    ├── requirements.txt
    └── energy_fuel_notifier.py        <-- Energy Manager Engine (Hourly Emergency Monitor)
```

---

## 🚀 How to Deploy on GitHub Actions (Free 24/7 Cloud)

Follow these steps once to run this forever in the cloud for free:

### 1. Initialize & Push to GitHub
Open your terminal in `c:\Users\abhij\OneDrive\Desktop\Ntfy sh` and run:

```powershell
git init
git add .
git commit -m "Initial commit for abhijaysinghlimited Trophy Games tracker"
git branch -M main
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/trophy-games-tracker.git
git push -u origin main
```

*(Replace `<YOUR_GITHUB_USERNAME>` with your GitHub username).*

---

### 2. Verify Your GitHub Actions Workflows
1. Open your repository on GitHub.
2. Click the **Actions** tab at the top.
3. You will see your two automated jobs:
   * **`Daily Morning Briefing & 4-Chance Scheduler (Train & Truck)`** (Runs daily at 06:00 AM IST).
   * **`Energy Manager Hourly Live Tracker`** (Runs every hour starting at 06:30 AM IST).

---

### 3. How to Test Instantly from GitHub
You don't have to wait for 6:00 AM to test:
1. In the **Actions** tab on GitHub, click either workflow name in the left sidebar.
2. Click the **Run workflow** button on the right side.
3. Within 30 seconds, GitHub will launch a cloud runner, execute the code, and your phone will ring!

---

## 💻 Manual Local Testing (From Your PC)

If you ever want to run the scripts manually on your own computer:

```powershell
# Run Train Manager Tracker
python train-alert/train_fuel_notifier.py

# Run Truck Manager Tracker
python truck-alert/truck_fuel_notifier.py

# Run Energy Manager Hourly Check
python energy-alert/energy_fuel_notifier.py

# Run Energy Manager Morning Briefing
python energy-alert/energy_fuel_notifier.py --briefing
```

---


---

## 🛡️ Anti-Spam & Deduplication System (Once-Only Guarantee)

To guarantee you never receive annoying repeated notifications for the same price condition:

1. **Energy Manager Deduplication (energy_state.json):**
   * When Coal drops below .50 (or Oil < .90, Hydrogen > , CO2 < ), you receive the emergency alert **EXACTLY ONCE**.
   * Even though the script checks every hour, it will **NOT** alert you again while the price stays low.
   * The alert resets only when the price recovers back above the threshold, ready for the next genuine drop!

2. **Train & Truck Daily State (	rain_state.json / 	ruck_state.json):**
   * Morning briefings and exact-time alerts are scheduled **EXACTLY ONCE PER DAY**.
   * Any duplicate executions on the same day automatically detect the existing schedule and safely exit with zero duplicate messages.
   * If you ever want to re-run manually, pass --force (e.g. python train-alert/train_fuel_notifier.py --force).

## 🛠️ Maintenance & FAQ

#### Q: How do I change an alert threshold in the future?
Open the corresponding script and edit the constants near the top of the file:
* In `energy-alert/energy_fuel_notifier.py`:
  ```python
  OIL_BUY_THRESHOLD = 1.90       # Change threshold here
  COAL_BUY_THRESHOLD = 1.50      # Change threshold here
  HYDROGEN_SELL_THRESHOLD = 90.00# Change threshold here
  CO2_BUY_THRESHOLD = 20.00      # Change threshold here
  ```

#### Q: What if my Energy Manager password changes?
Simply update `EM_PASSWORD` at line 29 of `energy-alert/energy_fuel_notifier.py`, or set the `EM_PASSWORD` secret in your GitHub repository settings under **Settings -> Secrets and variables -> Actions**.

#### Q: Can I add more games in the future?
Yes! The repository is modular. Simply create a new folder (e.g. `shipping-alert/` or `airline-alert/`) and add a step in `.github/workflows/daily_briefing_scheduler.yml`.
