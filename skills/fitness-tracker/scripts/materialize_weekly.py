#!/usr/bin/env python3
"""
materialize_weekly.py — Build weekly_summary from daily_facts + weekly_checkins.
Run after etl_sync.py, or whenever you add a weekly checkin.
"""
import sqlite3
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.expanduser("~/.hermes/skills/fitness-tracker/data")
DB_PATH = os.path.join(DATA_DIR, "fitness.db")
PROFILE_PATH = os.path.join(DATA_DIR, "profile.json")

def get_monday(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

def load_json(path):
    import json
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)

def materialize():
    profile = load_json(PROFILE_PATH)
    sed = profile.get("sedentary_base_kcal", 2000)
    deficit = profile.get("deficit_midpoint_kcal", 650)
    gym_cals = profile.get("gym_calories_per_session", 420)
    assumed_maintenance_gym = sed + gym_cals
    assumed_maintenance_rest = sed

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Build daily aggregates with week_start
    cur.execute("""
    SELECT
        date,
        kcal_in,
        protein_g,
        gym_flag,
        workout_duration_min,
        adherence_score,
        hunger_score,
        energy_score
    FROM daily_facts
    WHERE gym_flag IS NOT NULL
    ORDER BY date
    """)

    from collections import defaultdict
    weeks = defaultdict(lambda: {
        "days": 0, "kcal_sum": 0, "kcal_count": 0,
        "protein_sum": 0, "protein_count": 0,
        "workouts": 0, "workout_min_sum": 0,
        "adherence_sum": 0, "adherence_count": 0,
        "hunger_sum": 0, "hunger_count": 0,
        "energy_sum": 0, "energy_count": 0,
        "saturday_kcal": None, "sunday_kcal": None,
        "weekend_kcal_sum": 0, "weekend_days": 0,
        "weekday_kcal_sum": 0, "weekday_days": 0,
    })

    for row in cur.fetchall():
        date_str, kcal, protein, gym_flag, wdur, adherence, hunger, energy = row
        wk = get_monday(date_str)
        d = weeks[wk]
        d["days"] += 1
        if kcal is not None:
            d["kcal_sum"] += kcal
            d["kcal_count"] += 1
        if protein is not None:
            d["protein_sum"] += protein
            d["protein_count"] += 1
        if gym_flag:
            d["workouts"] += 1
        if wdur is not None:
            d["workout_min_sum"] += wdur
        if adherence is not None:
            d["adherence_sum"] += adherence
            d["adherence_count"] += 1
        if hunger is not None:
            d["hunger_sum"] += hunger
            d["hunger_count"] += 1
        if energy is not None:
            d["energy_sum"] += energy
            d["energy_count"] += 1

        # Weekend vs weekday
        dow = datetime.strptime(date_str, "%Y-%m-%d").weekday()
        if dow >= 5:  # Sat=5, Sun=6
            d["weekend_kcal_sum"] += kcal if kcal else 0
            d["weekend_days"] += 1 if kcal else 0
        else:
            d["weekday_kcal_sum"] += kcal if kcal else 0
            d["weekday_days"] += 1 if kcal else 0

    # Pull weekly checkins
    cur.execute("SELECT checkin_date, weight_kg FROM weekly_checkins ORDER BY checkin_date")
    checkins = {}
    for row in cur.fetchall():
        wk = get_monday(row[0])
        checkins[wk] = row[1]

    # Get previous week weights for change calculation.
    # Include checkin-only weeks too: historical weight imports may not have
    # nutrition/workout rows in daily_facts, but they are still valid trend data.
    sorted_weeks = sorted(set(weeks.keys()) | set(checkins.keys()))
    checkin_weeks = sorted(checkins.keys())

    # Upsert weekly_summary
    upsert_sql = """
    INSERT INTO weekly_summary
    (week_start, avg_kcal, avg_protein_g, total_workouts, total_workout_min,
     avg_adherence, avg_hunger, avg_energy, weekly_weight_kg,
     weekly_weight_change_kg, empirical_tdee_low, empirical_tdee_high,
     maintenance_confidence)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(week_start) DO UPDATE SET
        avg_kcal=excluded.avg_kcal,
        avg_protein_g=excluded.avg_protein_g,
        total_workouts=excluded.total_workouts,
        total_workout_min=excluded.total_workout_min,
        avg_adherence=excluded.avg_adherence,
        avg_hunger=excluded.avg_hunger,
        avg_energy=excluded.avg_energy,
        weekly_weight_kg=excluded.weekly_weight_kg,
        weekly_weight_change_kg=excluded.weekly_weight_change_kg,
        empirical_tdee_low=excluded.empirical_tdee_low,
        empirical_tdee_high=excluded.empirical_tdee_high,
        maintenance_confidence=excluded.maintenance_confidence
    """

    count = 0
    prev_weight = None
    for i, wk in enumerate(sorted_weeks):
        d = weeks[wk]
        days = d["days"]
        avg_kcal = round(d["kcal_sum"] / d["kcal_count"], 0) if d["kcal_count"] > 0 else None
        avg_protein = round(d["protein_sum"] / d["protein_count"], 1) if d["protein_count"] > 0 else None
        avg_adherence = round(d["adherence_sum"] / d["adherence_count"], 1) if d["adherence_count"] > 0 else None
        avg_hunger = round(d["hunger_sum"] / d["hunger_count"], 1) if d["hunger_count"] > 0 else None
        avg_energy = round(d["energy_sum"] / d["energy_count"], 1) if d["energy_count"] > 0 else None

        weight_kg = checkins.get(wk)
        weight_change = None
        empirical_low = None
        empirical_high = None
        confidence = None

        if weight_kg is not None:
            # Find previous checkin weight (any prior week with data)
            prev_w = None
            for pw in checkin_weeks:
                if pw < wk:
                    prev_w = pw
            if prev_w:
                prev_weight = checkins.get(prev_w)
            if prev_weight is not None:
                weight_change = round(weight_kg - prev_weight, 2)

            # Empiric TDEE: avg_kcal - weight_change_kg * 7700 / 7
            # Weight loss is negative weight_change, so TDEE should rise above intake.
            # But we need >1 week of data for this to be meaningful
            if avg_kcal is not None and weight_change is not None:
                empirical = avg_kcal - (weight_change * 7700 / 7)
                # Band: ±200 kcal (generous)
                empirical_low = round(max(empirical - 200, 1000), 0)
                empirical_high = round(empirical + 200, 0)
                # Simple confidence: based on data density
                adherence_pct = d["adherence_count"] / 7
                if adherence_pct >= 0.85 and d["days"] >= 6:
                    confidence = "medium"
                elif adherence_pct >= 0.6:
                    confidence = "low"
                else:
                    confidence = "too_sparse"

        cur.execute(upsert_sql, (
            wk, avg_kcal, avg_protein, d["workouts"], round(d["workout_min_sum"], 1),
            avg_adherence, avg_hunger, avg_energy, weight_kg, weight_change,
            empirical_low, empirical_high, confidence
        ))
        count += 1
        if weight_kg is not None:
            prev_weight = weight_kg

    conn.commit()
    conn.close()
    print(f"Materialized {count} weeks into weekly_summary.")

if __name__ == "__main__":
    materialize()
