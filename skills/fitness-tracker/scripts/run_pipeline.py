#!/usr/bin/env python3
"""
run_pipeline.py — One-shot: sync JSON → SQLite → materialize weekly → dashboard.
Run this after logging new meals or after a gym session.
"""
import subprocess
import sys
import os

BASE = os.path.expanduser("~/.hermes/skills/fitness-tracker/scripts")

def run(script):
    path = os.path.join(BASE, script)
    print(f"\n▶️  {script}", flush=True)
    r = subprocess.run([sys.executable, path], capture_output=False)
    if r.returncode != 0:
        print(f"❌ {script} failed")
        sys.exit(1)

if __name__ == "__main__":
    run("etl_sync.py")
    run("materialize_weekly.py")
    run("dashboard_v1.py")
    print("\n✅ Pipeline complete.")
