#!/usr/bin/env python3
"""
Daily Fitness Dashboard
Generates a daily summary combining nutrition, workouts, and calorie budget.
Usage: python daily_dashboard.py [--date 2026-04-14]
"""

import json
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
PROFILE_FILE = DATA_DIR / "profile.json"
WEIGHT_FILE = DATA_DIR / "weight_log.json"
NUTRITION_FILE = DATA_DIR / "daily_nutrition.json"
LYFTA_CACHE = DATA_DIR / "lyfta_cache.json"


def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def is_gym_day(target_date):
    """Check if there's a logged workout for this date."""
    cache = load_json(LYFTA_CACHE)
    for w in cache.get("workouts", []):
        if w.get("date") == target_date:
            return w
    return None


def calculate_budget(profile, workout=None):
    """Calculate daily calorie budget based on gym day vs rest day."""
    base = profile["sedentary_base_kcal"]
    deficit = profile["deficit_midpoint_kcal"]

    if workout:
        gym_cal = workout.get("calories_burned", profile["gym_calories_per_session"])
        expenditure = base + gym_cal
        day_type = "Gym Day"
    else:
        expenditure = base
        day_type = "Rest Day"

    budget = expenditure - deficit
    return {
        "type": day_type,
        "expenditure": expenditure,
        "budget": budget,
        "deficit_target": deficit,
    }


def get_daily_nutrition(target_date):
    """Get logged meals for the target date."""
    data = load_json(NUTRITION_FILE, default={})
    return data.get(target_date, {"meals": [], "total_kcal": 0})


def get_recent_weight_trend(days=7):
    """Get weight trend for the past N days."""
    data = load_json(WEIGHT_FILE, default={})
    if not data:
        return None, None, []

    sorted_dates = sorted(data.keys(), reverse=True)
    recent = [(d, data[d]) for d in sorted_dates[:days]]

    if len(recent) < 2:
        return recent[0][1] if recent else None, None, recent

    latest = recent[0][1]
    oldest = recent[-1][1]
    delta = round(latest - oldest, 1)
    return latest, delta, recent


def get_weekly_deficit_summary(profile, target_date):
    """Calculate average daily deficit for the past week."""
    nutrition = load_json(NUTRITION_FILE, default={})
    lyfta = load_json(LYFTA_CACHE)

    # Build workout lookup by date
    workout_by_date = {}
    for w in lyfta.get("workouts", []):
        workout_by_date[w["date"]] = w

    dt = datetime.strptime(target_date, "%Y-%m-%d")
    deficits = []

    for i in range(7):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        workout = workout_by_date.get(d)
        budget_info = calculate_budget(profile, workout)
        consumed = nutrition.get(d, {}).get("total_kcal", 0)
        if consumed > 0:
            deficit = budget_info["expenditure"] - consumed
            deficits.append({"date": d, "deficit": deficit, "consumed": consumed})

    if not deficits:
        return None

    avg_deficit = sum(d["deficit"] for d in deficits) / len(deficits)
    projected_loss = round(avg_deficit * 7 / 7700, 2)  # 7700 kcal ≈ 1 kg

    return {
        "days_logged": len(deficits),
        "avg_daily_deficit": round(avg_deficit),
        "projected_weekly_loss_kg": projected_loss,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily fitness dashboard")
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    profile = load_json(PROFILE_FILE)
    if not profile:
        print("ERROR: profile.json not found. Create it first.")
        sys.exit(1)

    target_date = args.date
    workout = is_gym_day(target_date)
    budget = calculate_budget(profile, workout)
    nutrition = get_daily_nutrition(target_date)
    weight, weight_delta, weight_history = get_recent_weight_trend()
    weekly = get_weekly_deficit_summary(profile, target_date)

    # Output
    print(f"=== FITNESS DASHBOARD — {target_date} ===\n")

    print(f"Day Type:     {budget['type']}")
    print(f"Expenditure:  {budget['expenditure']} kcal")
    print(f"Budget:       {budget['budget']} kcal")
    print(f"Deficit aim:  {budget['deficit_target']} kcal\n")

    if nutrition["meals"]:
        print(f"Meals logged: {len(nutrition['meals'])}")
        for m in nutrition["meals"]:
            print(f"  • {m['time']} — {m['description']}: {m['kcal']} kcal")
        remaining = budget["budget"] - nutrition["total_kcal"]
        status = "UNDER" if remaining > 0 else "OVER"
        print(f"Consumed:     {nutrition['total_kcal']} kcal")
        print(f"Remaining:    {abs(remaining)} kcal {status}\n")
    else:
        print(f"Meals logged: None yet")
        print(f"Budget left:  {budget['budget']} kcal\n")

    if weight:
        print(f"Latest weight: {weight} kg")
        if weight_delta is not None:
            direction = "down" if weight_delta < 0 else "up" if weight_delta > 0 else "stable"
            print(f"7-day trend:   {abs(weight_delta)} kg {direction}")
    else:
        print("Weight:        No data yet\n")

    if weekly:
        print(f"\n--- Weekly Summary ---")
        print(f"Days logged:        {weekly['days_logged']}/7")
        print(f"Avg daily deficit:  {weekly['avg_daily_deficit']} kcal")
        print(f"Projected loss:     {weekly['projected_weekly_loss_kg']} kg/week")


if __name__ == "__main__":
    main()
