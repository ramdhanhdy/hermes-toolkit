#!/usr/bin/env python3
"""
etl_sync.py — Backfill daily_facts from existing JSON sources.
Merges daily_nutrition.json + lyfta_cache.json into unified SQLite.
Idempotent: replaces existing rows for dates found in either source.
"""
import json
import sqlite3
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.expanduser("~/.hermes/skills/fitness-tracker/data")
DB_PATH = os.path.join(DATA_DIR, "fitness.db")
NUTRITION_PATH = os.path.join(DATA_DIR, "daily_nutrition.json")
LYFTA_PATH = os.path.join(DATA_DIR, "lyfta_cache.json")
PROFILE_PATH = os.path.join(DATA_DIR, "profile.json")

def parse_duration_to_min(duration_str):
    if not duration_str or not isinstance(duration_str, str):
        return None
    parts = duration_str.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 60 + m + s / 60
        elif len(parts) == 2:
            m, s = map(int, parts)
            return m + s / 60
    except (ValueError, TypeError):
        pass
    return None

def get_budgets(profile):
    sed = profile.get("sedentary_base_kcal", 2000)
    deficit = profile.get("deficit_midpoint_kcal", 650)
    gym_cals = profile.get("gym_calories_per_session", 420)
    rest_budget = sed - deficit
    gym_budget = sed + gym_cals - deficit
    return rest_budget, gym_budget

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)

def extract_nutrition_row(date_str, day_data, rest_budget, gym_budget):
    meals = day_data.get("meals", [])
    total_kcal = day_data.get("total_kcal")
    protein = sum(m.get("protein_g", 0) or 0 for m in meals)
    carbs = sum(m.get("carbs_g", 0) or 0 for m in meals)
    fat = sum(m.get("fat_g", 0) or 0 for m in meals)
    meal_kcal_sum = sum(m.get("kcal", 0) or 0 for m in meals)
    kcal_in = total_kcal if total_kcal is not None else meal_kcal_sum

    # Workout extraction from nutrition JSON
    workout = day_data.get("workout", {})
    gym_flag = 1 if workout or day_data.get("note", "").lower().startswith("rest day") else 0
    # Actually the note says "Rest day. No gym." - let's not flag gym if the note explicitly says rest
    if day_data.get("note", "").lower().startswith("rest day"):
        gym_flag = 0

    workout_kcal = 0
    workout_dur_min = None
    if workout:
        for wtype, wdata in workout.items():
            if isinstance(wdata, dict):
                cb = wdata.get("calories_burned")
                if cb:
                    workout_kcal += cb
                dur = wdata.get("duration")
                if dur and workout_dur_min is None:
                    workout_dur_min = parse_duration_to_min(dur)
        total_cb = workout.get("total_calories_burned")
        if total_cb and workout_kcal == 0:
            workout_kcal = total_cb

    notes = day_data.get("note", "")
    steps_estimated = day_data.get("steps_estimated")
    return {
        "date": date_str,
        "kcal_in": kcal_in,
        "protein_g": round(protein, 1),
        "carbs_g": round(carbs, 1),
        "fat_g": round(fat, 1),
        "gym_flag": gym_flag,
        "workout_kcal": workout_kcal if workout_kcal > 0 else None,
        "workout_duration_min": round(workout_dur_min, 1) if workout_dur_min else None,
        "steps_estimated": steps_estimated,
        "adherence_score": None,
        "hunger_score": None,
        "energy_score": None,
        "notes": notes,
    }

def extract_lyfta_workouts(lyfta_data):
    """Returns dict: date_str -> {calories_burned, duration_min}"""
    workouts = lyfta_data.get("workouts", [])
    result = {}
    for w in workouts:
        date_str = w.get("date")
        if not date_str:
            continue
        cb = w.get("calories_burned")
        dur = parse_duration_to_min(w.get("duration"))
        result[date_str] = {
            "calories_burned": cb,
            "duration_min": dur,
        }
    return result

def compute_adherence(kcal_in, gym_flag, rest_budget, gym_budget, steps_estimated=None):
    if kcal_in is None:
        return None
    budget = gym_budget if gym_flag else rest_budget
    if steps_estimated:
        budget += steps_estimated * 0.04
    if budget:
        return round((kcal_in / budget) * 100, 1)
    return None

def sync():
    nutrition = load_json(NUTRITION_PATH)
    lyfta = load_json(LYFTA_PATH)
    profile = load_json(PROFILE_PATH)
    rest_budget, gym_budget = get_budgets(profile)
    lyfta_workouts = extract_lyfta_workouts(lyfta)

    # Collect all unique dates
    all_dates = set(nutrition.keys()) | set(lyfta_workouts.keys())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    upsert_sql = """
    INSERT INTO daily_facts
    (date, kcal_in, protein_g, carbs_g, fat_g, gym_flag, workout_kcal,
     workout_duration_min, steps_estimated, adherence_score, hunger_score,
     energy_score, notes)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(date) DO UPDATE SET
        kcal_in=COALESCE(excluded.kcal_in, daily_facts.kcal_in),
        protein_g=COALESCE(excluded.protein_g, daily_facts.protein_g),
        carbs_g=COALESCE(excluded.carbs_g, daily_facts.carbs_g),
        fat_g=COALESCE(excluded.fat_g, daily_facts.fat_g),
        gym_flag=CASE
            WHEN COALESCE(excluded.workout_kcal, daily_facts.workout_kcal, 0) > 0 THEN 1
            ELSE COALESCE(excluded.gym_flag, daily_facts.gym_flag)
        END,
        workout_kcal=COALESCE(excluded.workout_kcal, daily_facts.workout_kcal),
        workout_duration_min=COALESCE(excluded.workout_duration_min, daily_facts.workout_duration_min),
        steps_estimated=COALESCE(excluded.steps_estimated, daily_facts.steps_estimated),
        adherence_score=COALESCE(excluded.adherence_score, daily_facts.adherence_score),
        hunger_score=COALESCE(excluded.hunger_score, daily_facts.hunger_score),
        energy_score=COALESCE(excluded.energy_score, daily_facts.energy_score),
        notes=COALESCE(excluded.notes, daily_facts.notes)
    """

    count = 0
    for date_str in sorted(all_dates):
        # Base from nutrition if available
        if date_str in nutrition:
            row = extract_nutrition_row(date_str, nutrition[date_str], rest_budget, gym_budget)
        else:
            # Lyfta-only day: create placeholder
            row = {
                "date": date_str,
                "kcal_in": None,
                "protein_g": None,
                "carbs_g": None,
                "fat_g": None,
                "gym_flag": 1,  # Lyfta workout = gym day
                "workout_kcal": None,
                "workout_duration_min": None,
                "steps_estimated": None,
                "adherence_score": None,
                "hunger_score": None,
                "energy_score": None,
                "notes": "Workout data from Lyfta only; nutrition not logged",
            }

        # Override / supplement with Lyfta data if available
        if date_str in lyfta_workouts:
            lw = lyfta_workouts[date_str]
            # Lyfta calories override nutrition JSON estimates (more accurate)
            row["workout_kcal"] = lw["calories_burned"]
            row["workout_duration_min"] = round(lw["duration_min"], 1) if lw["duration_min"] else row["workout_duration_min"]
            row["gym_flag"] = 1

        # Compute adherence now that gym_flag is final
        row["adherence_score"] = compute_adherence(
            row["kcal_in"], row["gym_flag"], rest_budget, gym_budget, row.get("steps_estimated")
        )

        cur.execute(upsert_sql, (
            row["date"], row["kcal_in"], row["protein_g"], row["carbs_g"],
            row["fat_g"], row["gym_flag"], row["workout_kcal"],
            row["workout_duration_min"], row["steps_estimated"],
            row["adherence_score"], row["hunger_score"], row["energy_score"],
            row["notes"]
        ))
        count += 1

    conn.commit()
    conn.close()
    print(f"Synced {count} days into daily_facts.")
    print(f"  Nutrition-only: {len(nutrition.keys() - lyfta_workouts.keys())}")
    print(f"  Lyfta-only: {len(lyfta_workouts.keys() - nutrition.keys())}")
    print(f"  Both sources: {len(set(nutrition.keys()) & set(lyfta_workouts.keys()))}")
    print(f"Budgets: rest={rest_budget}, gym={gym_budget}")

if __name__ == "__main__":
    sync()
