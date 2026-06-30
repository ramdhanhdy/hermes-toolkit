#!/usr/bin/env python3
"""
log_checkin.py — Record a weekly weigh-in into weekly_checkins.
Usage: python log_checkin.py 2026-04-21 82.5 --pre-workout --notes "felt bloated"
"""
import sqlite3
import os
import argparse
from datetime import datetime

DATA_DIR = os.path.expanduser("~/.hermes/skills/fitness-tracker/data")
DB_PATH = os.path.join(DATA_DIR, "fitness.db")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="Checkin date YYYY-MM-DD")
    parser.add_argument("weight", type=float, help="Weight in kg")
    parser.add_argument("--waist", type=float, default=None, help="Waist cm (optional)")
    parser.add_argument("--time", default="afternoon", help="Weigh-in time descriptor")
    parser.add_argument("--pre-workout", action="store_true", dest="pre_workout", help="Before workout")
    parser.add_argument("--post-workout", action="store_false", dest="pre_workout", help="After workout")
    parser.add_argument("--clothing", default="", help="Clothing notes")
    parser.add_argument("--notes", default="", help="Comment")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO weekly_checkins
    (checkin_date, weight_kg, waist_cm, weighin_time, pre_workout, clothing_notes, comment)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(checkin_date) DO UPDATE SET
        weight_kg=excluded.weight_kg,
        waist_cm=COALESCE(excluded.waist_cm, weekly_checkins.waist_cm),
        weighin_time=excluded.weighin_time,
        pre_workout=excluded.pre_workout,
        clothing_notes=excluded.clothing_notes,
        comment=excluded.comment
    """, (
        args.date, args.weight, args.waist, args.time,
        1 if args.pre_workout else 0, args.clothing, args.notes
    ))
    conn.commit()
    conn.close()
    print(f"✅ Logged weigh-in: {args.date} — {args.weight} kg")
    if args.waist:
        print(f"   Waist: {args.waist} cm")

if __name__ == "__main__":
    main()
