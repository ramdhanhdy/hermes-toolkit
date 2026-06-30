#!/usr/bin/env python3
"""
Lyfta Workout Sync
Pulls recent workouts from Lyfta API and caches locally.
Usage: python lyfta_sync.py [--days 7] [--limit 20]
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "lyfta_cache.json"
API_BASE = "https://my.lyfta.app"
MET_STRENGTH = 6.0  # MET value for moderate strength training
MET_CARDIO = 8.0    # MET value for moderate-high intensity cardio (aerobics, HIIT, etc.)


def get_api_key():
    """Load Lyfta API key from environment."""
    # Try .env file first
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.startswith("LYFTA_API_KEY="):
                    return line.strip().split("=", 1)[1]
    # Fallback to env var
    return os.environ.get("LYFTA_API_KEY")


def fetch_workouts(api_key, limit=50, page=1):
    """Fetch workouts with full detail from Lyfta API."""
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"limit": limit, "page": page}
    resp = requests.get(f"{API_BASE}/api/v1/workouts", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_workouts(api_key, max_workouts=500):
    """Fetch all workouts with pagination (max 100 per call)."""
    all_workouts = []
    page = 1
    while len(all_workouts) < max_workouts:
        data = fetch_workouts(api_key, limit=100, page=page)
        workouts = data.get("workouts", [])
        if not workouts:
            break
        all_workouts.extend(workouts)
        total_pages = data.get("total_pages", 1)
        if page >= total_pages:
            break
        page += 1
    return all_workouts[:max_workouts]


def fetch_workout_summaries(api_key, limit=1000, page=1):
    """Fetch workout summaries (lighter, up to 1000 per call)."""
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"limit": limit, "page": page}
    resp = requests.get(f"{API_BASE}/api/v1/workouts/summary", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_duration(duration_str):
    """Parse duration string HH:MM:SS to total minutes."""
    if not duration_str:
        return None
    parts = str(duration_str).split(":")
    if len(parts) == 3:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        return hours * 60 + minutes + seconds / 60
    elif len(parts) == 2:
        minutes, seconds = int(parts[0]), int(parts[1])
        return minutes + seconds / 60
    return None


def estimate_calories_burned(workout):
    """
    Estimate calories burned from workout data.
    Handles both strength and cardio exercises.
    Formula: kcal = MET × 3.5 × body_weight_kg / 200 × minutes
    """
    body_weight = workout.get("body_weight") or 83  # default to user's weight
    total_kcal = 0

    # Check for cardio exercises and estimate their calories separately
    for ex in workout.get("exercises", []):
        if ex.get("cardio_info"):
            cardio = ex["cardio_info"]
            duration_str = cardio.get("duration")
            minutes = parse_duration(duration_str)
            if minutes and minutes > 0:
                kcal_per_min = MET_CARDIO * 3.5 * body_weight / 200
                total_kcal += round(minutes * kcal_per_min)
            elif cardio.get("distance"):
                # Fallback: estimate 10 min per km for walking/jogging
                distance_km = cardio["distance"]
                est_minutes = distance_km * 10
                kcal_per_min = MET_CARDIO * 3.5 * body_weight / 200
                total_kcal += round(est_minutes * kcal_per_min)

    # If we already estimated cardio calories, add strength portion
    if total_kcal > 0:
        # Estimate strength portion from volume
        strength_volume = sum(
            sum(s.get("weight", 0) * s.get("reps", 0) for s in ex.get("sets", []))
            for ex in workout.get("exercises", [])
            if not ex.get("cardio_info")
        )
        if strength_volume > 0:
            total_kcal += round(strength_volume * 0.05)
        return total_kcal

    # No cardio — use original logic for strength-only workouts
    # Try duration-based estimation
    duration_str = workout.get("duration") or workout.get("workout_duration")
    total_minutes = parse_duration(duration_str)
    if total_minutes and total_minutes > 0:
        kcal_per_min = MET_STRENGTH * 3.5 * body_weight / 200
        return round(total_minutes * kcal_per_min)

    # Fallback: estimate from volume (sets × reps × weight)
    total_volume = workout.get("total_volume", 0)
    if total_volume and isinstance(total_volume, (int, float)) and total_volume > 0:
        return round(total_volume * 0.05)

    # Default fallback for a 1-hour strength session
    return 420


def normalize_workout(raw_workout, from_summary=False):
    """Normalize a workout to a consistent internal format."""
    if from_summary:
        date_str = raw_workout.get("workout_perform_date", "")
        return {
            "id": raw_workout.get("id"),
            "title": raw_workout.get("title", "Workout"),
            "date": date_str.split(" ")[0] if date_str else "",
            "duration": raw_workout.get("workout_duration", "00:00:00"),
            "total_volume": raw_workout.get("total_volume", 0),
            "calories_burned": None,  # Will estimate below
            "exercises": [],
        }

    date_str = raw_workout.get("workout_perform_date", "")
    exercises = []
    workout_duration = raw_workout.get("duration") or raw_workout.get("workout_duration", "")
    for ex in raw_workout.get("exercises", []):
        exercise_type = ex.get("exercise_type", "weight_reps")
        sets = []
        cardio_info = None

        # Handle cardio/duration exercises
        if exercise_type in ("distance_duration", "duration"):
            # Duration is inside sets, not at exercise level
            for s in ex.get("sets", []):
                dur = s.get("duration")
                dist = s.get("distance")
                if dur or dist:
                    cardio_info = {
                        "distance": float(dist) if dist else None,
                        "duration": dur if isinstance(dur, str) else str(dur) if dur else None,
                    }
                    break  # Take first set with duration data
        else:
            # Strength exercises — parse weight/reps sets
            for s in ex.get("sets", []):
                try:
                    weight = float(s.get("weight", 0) or 0)
                    reps = int(s.get("reps", 0) or 0)
                except (ValueError, TypeError):
                    weight, reps = 0, 0
                if weight > 0 and reps > 0:
                    sets.append({
                        "weight": weight,
                        "reps": reps,
                        "set_type": s.get("set_type_id", "working"),
                    })

        # Include exercise if it has sets OR cardio info
        if sets or cardio_info:
            exercises.append({
                "name": ex.get("excercise_name", "Unknown"),
                "type": exercise_type,
                "sets": sets,
                "cardio_info": cardio_info,
            })

    return {
        "id": raw_workout.get("id"),
        "title": raw_workout.get("title", "Workout"),
        "date": date_str.split(" ")[0] if date_str else "",
        "body_weight": raw_workout.get("body_weight"),
        "duration": workout_duration,
        "total_volume": raw_workout.get("total_volume", 0),
        "calories_burned": None,
        "exercises": exercises,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync Lyfta workouts")
    parser.add_argument("--days", type=int, default=30, help="Days to look back")
    parser.add_argument("--limit", type=int, default=50, help="Max workouts to fetch")
    parser.add_argument("--summary-only", action="store_true", help="Only fetch summaries (faster)")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("ERROR: LYFTA_API_KEY not found in ~/.hermes/.env or environment")
        sys.exit(1)

    print(f"Fetching workouts (limit={args.limit})...")

    if args.summary_only:
        data = fetch_workout_summaries(api_key, limit=min(args.limit, 1000))
        raw_workouts = data.get("workouts", [])
    else:
        raw_workouts = fetch_all_workouts(api_key, max_workouts=args.limit)

        # Merge duration from summary endpoint (full endpoint lacks it)
        try:
            summary_data = fetch_workout_summaries(api_key, limit=min(args.limit, 1000))
            summary_by_id = {}
            for sw in summary_data.get("workouts", []):
                sid = sw.get("id")
                dur = sw.get("workout_duration") or sw.get("duration", "")
                if sid and dur:
                    summary_by_id[str(sid)] = dur
            for w in raw_workouts:
                wid = str(w.get("id", ""))
                if wid in summary_by_id and not (w.get("duration") or w.get("workout_duration")):
                    w["duration"] = summary_by_id[wid]
        except Exception:
            pass  # Summary merge is best-effort
    
    workouts = [normalize_workout(w, from_summary=args.summary_only) for w in raw_workouts]

    # Filter by date if --days specified
    if args.days:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        workouts = [w for w in workouts if w.get("date", "") >= cutoff]

    # Estimate calories for each workout
    for w in workouts:
        if w["calories_burned"] is None:
            w["calories_burned"] = estimate_calories_burned(w)

    # Save to cache
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = {
        "last_sync": datetime.now().isoformat(),
        "total_workouts": len(workouts),
        "workouts": workouts,
    }
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

    print(f"Synced {len(workouts)} workouts to {CACHE_FILE}")
    print(f"Last sync: {cache['last_sync']}")

    # Quick summary
    if workouts:
        dates = [w["date"] for w in workouts if w["date"]]
        if dates:
            print(f"Date range: {min(dates)} to {max(dates)}")
        total_cal = sum(w["calories_burned"] for w in workouts if w["calories_burned"])
        print(f"Total estimated calories burned: {total_cal} kcal")


if __name__ == "__main__":
    main()
