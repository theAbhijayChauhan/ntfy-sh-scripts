"""
🎮 Trophy Games Master Alert Runner
Runs Train, Truck, and Energy Manager notifiers sequentially.
Uses built-in deduplication state: zero duplicate alerts even if run multiple times.
"""

import subprocess
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run_script(rel_path, *args):
    script_path = os.path.join(BASE_DIR, rel_path)
    cmd = [sys.executable, script_path] + list(args)
    print(f"\n=======================================================")
    print(f"[*] Running: {' '.join(cmd)}")
    print(f"=======================================================")
    res = subprocess.run(cmd)
    return res.returncode

def main():
    print("🚀 Trophy Games Master Alert Runner Starting...")
    extra_args = sys.argv[1:]
    
    # 1. Train Manager
    run_script(os.path.join("train-alert", "train_fuel_notifier.py"), *extra_args)
    
    # 2. Truck Manager
    run_script(os.path.join("truck-alert", "truck_fuel_notifier.py"), *extra_args)
    
    # 3. Energy Manager
    run_script(os.path.join("energy-alert", "energy_fuel_notifier.py"), *extra_args)
    
    print("\n[OK] Master Alert Runner completed all checks!")

if __name__ == "__main__":
    main()
