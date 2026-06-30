#!/usr/bin/env python3
"""
detect_new_workout.py — Polls Lyfta API for workouts today and reports
any that haven't been acknowledged yet.

Stores last-reported workout ID in SQLite so we never double-report.
"""
import sqlite3
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path so we can import lyfta_sync helpers
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from lyfta_sync import get_api_key, fetch_all_workouts, normalize_workout, estimate_calories_burned

DB_PATH = Path.home() / ".hermes" / "skills" / "fitness-tracker" / "data" / "fitness.db"

def get_conn():
    return sqlite3.connect(DB_PATH)

def get_last_reported_workout_id():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM kv_store WHERE key = 'last_reported_workout_id'")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def set_last_reported_workout_id(workout_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO kv_store (key, value) VALUES ('last_reported_workout_id', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (str(workout_id),))
    conn.commit()
    conn.close()

def progressive_overload_check(exercise_name, current_sets):
    """Compare current top set against historical best for this exercise."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT weight_kg, reps, workout_date
        FROM exercise_sets
        WHERE exercise_name = ?
        ORDER BY workout_date DESC, weight_kg DESC, reps DESC
        LIMIT 5
    """, (exercise_name.strip(),))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return None  # No history

    # Find best previous set (highest weight, tiebreak reps)
    best_weight, best_reps, best_date = max(rows, key=lambda r: (r[0], r[1]))

    # Find current best set
    current_best = max(
        ((s.get("weight", 0) or 0), (s.get("reps", 0) or 0))
        for s in current_sets
        if s.get("weight") and s.get("reps")
    )
    curr_weight, curr_reps = current_best

    if curr_weight > best_weight:
        return f"🔼 NEW PR! {curr_weight} kg × {curr_reps} (was {best_weight} kg × {best_reps} on {best_date})"
    elif curr_weight == best_weight and curr_reps > best_reps:
        return f"🔼 Rep PR! {curr_weight} kg × {curr_reps} (was × {best_reps} on {best_date})"
    elif curr_reps >= 8 and curr_weight >= best_weight:
        return f"✅ Threshold hit — {curr_weight} kg × {curr_reps}. Bump weight next session."
    else:
        return None

def store_workout_exercises(workout):
    """Persist exercises to DB for progressive overload tracking."""
    conn = get_conn()
    cur = conn.cursor()
    date_str = workout.get("date", datetime.now().strftime("%Y-%m-%d"))

    for ex in workout.get("exercises", []):
        name = ex.get("name", "Unknown").strip()
        for s in ex.get("sets", []):
            weight = s.get("weight")
            reps = s.get("reps")
            if weight and reps:
                cur.execute("""
                    INSERT INTO exercise_sets (workout_date, exercise_name, weight_kg, reps, set_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str, name, weight, reps, s.get("set_type", "0")))
    conn.commit()
    conn.close()

def format_workout_report(workout):
    lines = []
    lines.append(f"🏋️ WORKOUT DETECTED — {workout['date']}")
    lines.append(f"   {workout['title']} | {workout['duration']} | {workout['calories_burned']} kcal")
    lines.append("")

    for ex in workout.get("exercises", []):
        name = ex.get("name", "Unknown")
        sets = ex.get("sets", [])
        cardio = ex.get("cardio_info")

        if cardio:
            dist = cardio.get("distance")
            dur = cardio.get("duration")
            lines.append(f"   🏃 {name}: {dist} km in {dur}")
            continue

        if not sets:
            continue

        set_strs = []
        for s in sets:
            w = s.get("weight")
            r = s.get("reps")
            set_strs.append(f"{w}×{r}")

        # Progressive overload check
        overload = progressive_overload_check(name, sets)
        overload_tag = f"\n      {overload}" if overload else ""

        lines.append(f"   💪 {name}: {', '.join(set_strs)}{overload_tag}")

    lines.append("")
    lines.append("Keep logging meals to see full daily totals. 💪")
    return "\n".join(lines)

def ensure_tables():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kv_store (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS exercise_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_date TEXT NOT NULL,
            exercise_name TEXT NOT NULL,
            weight_kg REAL,
            reps INTEGER,
            set_type TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def main():
    ensure_tables()
    api_key = get_api_key()
    if not api_key:
        print("Lyfta API key not found.")
        sys.exit(1)

    # Fetch today's workouts
    today_str = datetime.now().strftime("%Y-%m-%d")
    raw_workouts = fetch_all_workouts(api_key, max_workouts=20)
    workouts = [normalize_workout(w) for w in raw_workouts if w.get("workout_perform_date", "").startswith(today_str)]

    if not workouts:
        return  # Silent — no workouts today yet

    # Sort by time, newest last
    workouts.sort(key=lambda w: w.get("workout_perform_date", ""))

    last_id = get_last_reported_workout_id()
    new_workouts = []
    for w in workouts:
        wid = str(w.get("id", ""))
        if last_id and wid == last_id:
            # We've seen this one, skip everything before/including it
            new_workouts = []
            continue
        new_workouts.append(w)

    if not new_workouts:
        return  # Nothing new

    # Report the newest workout (assume one per day for now, but handle multiple)
    workout = new_workouts[-1]
    workout["calories_burned"] = estimate_calories_burned(workout)
    store_workout_exercises(workout)
    set_last_reported_workout_id(workout["id"])

    report = format_workout_report(workout)
    print(report)

if __name__ == "__main__":
    main()
