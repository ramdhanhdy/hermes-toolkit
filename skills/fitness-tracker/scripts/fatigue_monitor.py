#!/usr/bin/env python3
"""
Cumulative Fatigue Detection System for Lyfta Training Data.

Computes six fatigue indicators from workout history:
  1. ACWR (Acute:Chronic Workload Ratio) — rolling + EWMA
  2. Training Monotony & Strain
  3. Per-Exercise Volume Trends (linear regression)
  4. Consecutive Training Days
  5. Within-Session Volume Drop
  6. Actionable Recommendations

Usage:
    python fatigue_monitor.py                  # Human-readable report
    python fatigue_monitor.py --json           # JSON output
    python fatigue_monitor.py --days 60        # Custom lookback
"""

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "lyfta_cache.json"

# ── Config ──────────────────────────────────────────────────────────────────
ACUTE_WINDOW = 7          # Days for acute load
CHRONIC_WINDOW = 28       # Days for chronic load
EWMA_LAMBDA = 0.3         # EWMA smoothing (higher = more reactive)
MONOTONY_WARN = 2.0       # Monotony threshold
CONSECUTIVE_WARN = 4      # Consecutive days threshold
VOLUME_DROP_WARN = 30     # Within-session drop % threshold
TREND_WINDOW = 6          # Max sessions per exercise for trend


# ═══════════════════════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════════════════════

def parse_duration_s(s):
    """Parse 'HH:MM:SS' or 'MM:SS' to total seconds."""
    if not s:
        return 0
    parts = str(s).split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return 0


def parse_date(s):
    """Parse 'YYYY-MM-DD' to date, or None."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s).split(" ")[0], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def date_range(d1, d2):
    """Inclusive date range [d1, d2]."""
    days = (d2 - d1).days
    return [d1 + timedelta(days=i) for i in range(days + 1)]


def std_dev(vals):
    """Population standard deviation."""
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))


def linear_slope(xs, ys):
    """Least-squares slope. Returns slope, intercept, r_squared."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0, 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n, 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    mean_y = sy / n
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, intercept, r2


# ═══════════════════════════════════════════════════════════════════════════
#  Data Loading
# ═══════════════════════════════════════════════════════════════════════════

def load_workouts():
    """Load normalized workouts from Lyfta cache."""
    if not CACHE_FILE.exists():
        print("ERROR: No Lyfta cache found. Run lyfta_sync.py first.")
        sys.exit(1)
    with open(CACHE_FILE) as f:
        cache = json.load(f)
    workouts = []
    for w in cache.get("workouts", []):
        d = parse_date(w.get("date"))
        if d:
            workouts.append({
                "date": d,
                "date_str": w.get("date", ""),
                "volume": float(w.get("total_volume") or 0),
                "calories": float(w.get("calories_burned") or 0),
                "duration_s": parse_duration_s(w.get("duration")),
                "exercises": w.get("exercises", []),
            })
    workouts.sort(key=lambda w: w["date"])
    return workouts


# ═══════════════════════════════════════════════════════════════════════════
#  Daily Load Computation
# ═══════════════════════════════════════════════════════════════════════════

def compute_daily_loads(workouts, start, end):
    """
    Build daily training loads across [start, end].
    Returns {date: {volume, calories, exercises, sets}}.
    """
    by_date = defaultdict(lambda: {
        "volume": 0.0, "calories": 0.0, "exercises": 0, "sets": 0
    })
    for w in workouts:
        d = w["date"]
        if start <= d <= end:
            by_date[d]["volume"] += w["volume"]
            by_date[d]["calories"] += w["calories"]
            by_date[d]["exercises"] += len(w["exercises"])
            for ex in w["exercises"]:
                by_date[d]["sets"] += len(ex.get("sets", []))

    days = date_range(start, end)
    return {d: by_date[d] for d in days}


# ═══════════════════════════════════════════════════════════════════════════
#  Metric 1: ACWR
# ═══════════════════════════════════════════════════════════════════════════

def compute_acwr(daily_loads, end_date):
    """
    Acute:Chronic Workload Ratio.
    Returns dict with rolling and EWMA variants.
    """
    dates = sorted(daily_loads.keys())
    volumes = [daily_loads[d]["volume"] for d in dates]

    # Rolling average ACWR
    acute_idx = max(0, len(volumes) - ACUTE_WINDOW)
    chronic_idx = max(0, len(volumes) - CHRONIC_WINDOW)

    acute_vols = volumes[acute_idx:]
    chronic_vols = volumes[chronic_idx:]

    acute_avg = sum(acute_vols) / len(acute_vols)
    chronic_avg = sum(chronic_vols) / len(chronic_vols)
    rolling_ratio = acute_avg / chronic_avg if chronic_avg > 0 else float("inf")

    # EWMA ACWR
    ewma = None
    for v in volumes:
        ewma = v if ewma is None else EWMA_LAMBDA * v + (1 - EWMA_LAMBDA) * ewma

    # EWMA for acute and chronic windows
    acute_ewma = None
    for v in acute_vols:
        acute_ewma = v if acute_ewma is None else EWMA_LAMBDA * v + (1 - EWMA_LAMBDA) * acute_ewma
    chronic_ewma = None
    for v in chronic_vols:
        chronic_ewma = v if chronic_ewma is None else EWMA_LAMBDA * v + (1 - EWMA_LAMBDA) * chronic_ewma

    ewma_ratio = (acute_ewma / chronic_ewma
                  if chronic_ewma and chronic_ewma > 0 else float("inf"))

    return {
        "acute_avg": round(acute_avg, 1),
        "chronic_avg": round(chronic_avg, 1),
        "rolling_ratio": round(rolling_ratio, 2),
        "acute_ewma": round(acute_ewma, 1) if acute_ewma else 0,
        "chronic_ewma": round(chronic_ewma, 1) if chronic_ewma else 0,
        "ewma_ratio": round(ewma_ratio, 2) if math.isfinite(ewma_ratio) else 99.99,
        "acute_days": len(acute_vols),
        "chronic_days": len(chronic_vols),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Metric 2: Monotony & Strain
# ═══════════════════════════════════════════════════════════════════════════

def compute_monotony_strain(daily_loads):
    """
    Training Monotony = mean(daily) / stdev(daily).
    Strain = total_weekly_load × monotony.
    """
    dates = sorted(daily_loads.keys())
    volumes = [daily_loads[d]["volume"] for d in dates]
    non_zero = [v for v in volumes if v > 0]

    if len(non_zero) < 2:
        return {
            "monotony": 0, "strain": 0,
            "daily_mean": 0, "daily_std": 0,
            "training_days": len(non_zero),
        }

    mean = sum(non_zero) / len(non_zero)
    std = std_dev(non_zero)
    monotony = mean / std if std > 0 else 99.9
    weekly_total = sum(volumes[-7:]) if len(volumes) >= 7 else sum(volumes)
    strain = weekly_total * monotony

    return {
        "monotony": round(monotony, 2),
        "strain": round(strain, 0),
        "daily_mean": round(mean, 0),
        "daily_std": round(std, 0),
        "training_days": len(non_zero),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Metric 3: Per-Exercise Trends
# ═══════════════════════════════════════════════════════════════════════════

def exercise_volume(ex):
    """Total volume for one exercise (sum of weight × reps across sets)."""
    sets = ex.get("sets", [])
    if sets:
        return sum(float(s.get("weight", 0)) * int(s.get("reps", 0)) for s in sets)
    return 0


def exercise_set_count(ex):
    """Number of working sets for an exercise."""
    return len(ex.get("sets", []))


def compute_exercise_trends(workouts, n_sessions=8):
    """
    Track volume per exercise across recent sessions.
    Returns {exercise_name: {sessions, slope_per_session, pct_change, r2}}.
    """
    # Collect: {exercise_name: [(date, volume), ...]}
    exercise_history = defaultdict(list)

    for w in workouts[-n_sessions:]:
        for ex in w["exercises"]:
            name = ex.get("name", "Unknown")
            vol = exercise_volume(ex)
            if vol > 0:
                exercise_history[name].append((w["date"], vol))

    results = {}
    for name, history in exercise_history.items():
        if len(history) < 2:
            results[name] = {
                "sessions": len(history),
                "latest_vol": history[0][1] if history else 0,
                "slope": 0, "pct_change": 0, "r2": 0,
                "verdict": "insufficient_data",
            }
            continue

        vols = [h[1] for h in history]
        xs = list(range(len(vols)))  # 0=oldest ... N-1=newest

        slope, intercept, r2 = linear_slope(xs, vols)
        first = vols[0]
        last = vols[-1]
        pct = ((last - first) / first * 100) if first > 0 else 0

        if slope > 5 and r2 > 0.3:
            verdict = "improving"
        elif slope < -5 and r2 > 0.3:
            verdict = "declining"
        else:
            verdict = "stable"

        results[name] = {
            "sessions": len(history),
            "first_vol": round(first, 0),
            "last_vol": round(last, 0),
            "slope_per_session": round(slope, 1),
            "pct_change": round(pct, 1),
            "r2": round(r2, 3),
            "verdict": verdict,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════
#  Metric 4: Consecutive Training Days
# ═══════════════════════════════════════════════════════════════════════════

def compute_consecutive(workouts, today=None):
    """
    Current streak of consecutive training days ending at today or most recent.
    Returns {current, longest, is_training_today, ...}.
    """
    if today is None:
        today = datetime.now().date()

    workout_dates = sorted({w["date"] for w in workouts})

    # Current streak (counting backward from today)
    current = 0
    check = today
    date_set = set(workout_dates)
    while check in date_set:
        current += 1
        check -= timedelta(days=1)
    # Also check if streak extends from yesterday
    if current == 0:
        check = today - timedelta(days=1)
        while check in date_set:
            current += 1
            check -= timedelta(days=1)

    # Longest streak ever
    longest = 0
    streak = 0
    for i, d in enumerate(workout_dates):
        if i == 0:
            streak = 1
        elif (d - workout_dates[i - 1]).days == 1:
            streak += 1
        else:
            streak = 1
        longest = max(longest, streak)

    return {
        "current": current,
        "longest": longest,
        "is_training_today": today in date_set,
        "last_workout": max(workout_dates).isoformat() if workout_dates else None,
        "days_since_last": (today - max(workout_dates)).days if workout_dates else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Metric 5: Within-Session Volume Drop
# ═══════════════════════════════════════════════════════════════════════════

def compute_session_fatigue(workouts, n_sessions=5):
    """
    For each exercise with 3+ sets in recent sessions,
    compute drop from first-set volume to last-set volume.
    Returns [{date, exercise, first_vol, last_vol, drop_pct}, ...]
    """
    fatigued = []

    for w in workouts[-n_sessions:]:
        for ex in w["exercises"]:
            sets = ex.get("sets", [])
            if len(sets) < 3:
                continue

            first_vol = (float(sets[0].get("weight", 0))
                         * int(sets[0].get("reps", 0)))
            last_vol = (float(sets[-1].get("weight", 0))
                        * int(sets[-1].get("reps", 0)))
            if first_vol <= 0:
                continue

            drop = (first_vol - last_vol) / first_vol * 100
            if drop >= VOLUME_DROP_WARN:
                fatigued.append({
                    "date": w["date"].isoformat(),
                    "exercise": ex.get("name", "Unknown"),
                    "sets": len(sets),
                    "first_vol": round(first_vol, 0),
                    "last_vol": round(last_vol, 0),
                    "drop_pct": round(drop, 1),
                })

    return fatigued


# ═══════════════════════════════════════════════════════════════════════════
#  Metric 6: Weekly Volume Breakdown
# ═══════════════════════════════════════════════════════════════════════════

def compute_weekly_breakdown(workouts, n_weeks=4):
    """
    Aggregate volume, duration, sessions per calendar week (Mon–Sun).
    Returns list of {week_start, week_end, sessions, volume, duration_min, ...}.
    """
    from collections import defaultdict as dd

    # Group by ISO week
    weeks = dd(lambda: {
        "sessions": 0, "volume": 0.0,
        "duration_s": 0.0, "calories": 0.0, "sets": 0
    })

    for w in workouts:
        d = w["date"]
        # Monday of that week
        monday = d - timedelta(days=d.weekday())
        weeks[monday]["sessions"] += 1
        weeks[monday]["volume"] += w["volume"]
        weeks[monday]["duration_s"] += w["duration_s"]
        weeks[monday]["calories"] += w["calories"]
        for ex in w["exercises"]:
            weeks[monday]["sets"] += len(ex.get("sets", []))

    result = []
    for monday in sorted(weeks.keys(), reverse=True)[:n_weeks]:
        w = weeks[monday]
        result.append({
            "week_start": monday.isoformat(),
            "week_end": (monday + timedelta(days=6)).isoformat(),
            "sessions": w["sessions"],
            "volume": round(w["volume"], 0),
            "duration_min": round(w["duration_s"] / 60, 0),
            "calories": round(w["calories"], 0),
            "sets": w["sets"],
        })

    return list(reversed(result))  # chronological order


# ═══════════════════════════════════════════════════════════════════════════
#  Status Rating
# ═══════════════════════════════════════════════════════════════════════════

def rate_acwr(ratio):
    if ratio < 0.8:
        return "🔻", "UNDERTRAINED", "yellow"
    if ratio <= 1.3:
        return "✅", "OPTIMAL", "green"
    if ratio <= 1.5:
        return "⚠️", "ELEVATED RISK", "yellow"
    return "🚨", "HIGH RISK", "red"


def rate_monotony(m):
    if m < 1.5:
        return "✅", "GREAT VARIETY", "green"
    if m < 2.0:
        return "✅", "GOOD", "green"
    if m < 2.5:
        return "⚠️", "REPETITIVE", "yellow"
    return "🚨", "DANGEROUSLY REPETITIVE", "red"


def rate_consecutive(n):
    if n < 3:
        return "✅", "FRESH", "green"
    if n < 5:
        return "⚠️", "BUILDING FATIGUE", "yellow"
    return "🚨", "TAKE A REST DAY", "red"


# ═══════════════════════════════════════════════════════════════════════════
#  Report Generation
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(days=60):
    """Main entry point — computes all metrics and returns structured report."""
    workouts = load_workouts()
    if not workouts:
        return {"error": "No workouts in cache"}

    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    recent = [w for w in workouts if start <= w["date"] <= today]

    if not recent:
        return {"error": f"No workouts in the last {days} days"}

    # ── Compute all metrics ─────────────────────────────────────────────
    daily_loads = compute_daily_loads(workouts, start, today)
    acwr = compute_acwr(daily_loads, today)
    monotony_data = compute_monotony_strain(daily_loads)
    trends = compute_exercise_trends(workouts)
    consecutive = compute_consecutive(workouts, today)
    session_fatigue = compute_session_fatigue(workouts)
    weekly = compute_weekly_breakdown(workouts)

    acwr_emoji, acwr_status, _ = rate_acwr(acwr["rolling_ratio"])
    mon_emoji, mon_status, _ = rate_monotony(monotony_data["monotony"])
    con_emoji, con_status, _ = rate_consecutive(consecutive["current"])

    report = {
        "generated": today.isoformat(),
        "period_days": days,
        "workouts_in_period": len(recent),
        "acwr": acwr,
        "acwr_status": acwr_status,
        "monotony": monotony_data,
        "monotony_status": mon_status,
        "consecutive": consecutive,
        "consecutive_status": con_status,
        "exercise_trends": trends,
        "within_session_fatigue": session_fatigue,
        "weekly_breakdown": weekly,
    }

    # ── Recommendations ─────────────────────────────────────────────────
    recs = []

    # ACWR
    if acwr["rolling_ratio"] > 1.5:
        recs.append(
            f"🚨 ACWR is {acwr['rolling_ratio']} — you've spiked training load "
            f"too fast (acute {acwr['acute_avg']:.0f} vs chronic {acwr['chronic_avg']:.0f}). "
            "Cut volume 20-30% this week."
        )
    elif acwr["rolling_ratio"] < 0.8:
        recs.append(
            f"🔻 ACWR is {acwr['rolling_ratio']} — detraining zone. "
            "Gradually ramp back up to avoid a harsh return."
        )

    # Monotony
    if monotony_data["monotony"] >= MONOTONY_WARN:
        recs.append(
            f"😴 Monotony is {monotony_data['monotony']} — every session looks the same. "
            "Add a light day, swap exercises, or vary rep ranges."
        )

    # Consecutive
    if consecutive["current"] >= CONSECUTIVE_WARN:
        recs.append(
            f"🔥 {consecutive['current']} days straight without rest. "
            "Your body needs recovery. Take tomorrow off."
        )

    # Declining exercises
    declining = [
        (name, info) for name, info in trends.items()
        if info.get("verdict") == "declining"
    ]
    if declining:
        names = ", ".join(name for name, _ in declining)
        recs.append(
            f"📉 Volume declining on: {names}. "
            "Could be fatigue, under-recovery, or stale programming."
        )

    # Within-session drops
    drop_exercises = {f["exercise"] for f in session_fatigue}
    if drop_exercises:
        names = ", ".join(sorted(drop_exercises))
        recs.append(
            f"⚡ Big within-session drops on: {names}. "
            "Consistent set-to-set drop >30% = systemic fatigue marker."
        )

    # Volume trend from weekly breakdown
    if len(weekly) >= 2:
        last_week = weekly[-1]["volume"]
        prev_week = weekly[-2]["volume"]
        if prev_week > 0:
            change = (last_week - prev_week) / prev_week * 100
            if change > 30:
                recs.append(
                    f"📈 Weekly volume jumped {change:.0f}% — big spike. "
                    "Make sure you can recover from this."
                )
            elif change < -40:
                recs.append(
                    f"📉 Weekly volume dropped {abs(change):.0f}% — "
                    "if unintentional, you might be losing momentum."
                )

    if not recs:
        recs.append("💪 All fatigue markers look healthy. Keep it up!")

    report["recommendations"] = recs
    return report


# ═══════════════════════════════════════════════════════════════════════════
#  Formatters
# ═══════════════════════════════════════════════════════════════════════════

def fmt_dur_min(minutes):
    """Format minutes to human-readable."""
    if minutes >= 60:
        return f"{int(minutes) // 60}h{int(minutes) % 60:02d}m"
    return f"{int(minutes)}m"


def format_report_text(report):
    """Format report dict to human-readable text (Telegram-safe, no markdown)."""
    if "error" in report:
        return f"❌ {report['error']}"

    lines = []
    a = report["acwr"]
    m = report["monotony"]
    c = report["consecutive"]

    acwr_e, acwr_s, _ = rate_acwr(a["rolling_ratio"])
    mon_e, mon_s, _ = rate_monotony(m["monotony"])
    con_e, con_s, _ = rate_consecutive(c["current"])

    # Header
    lines.append(f"🏋️ Fatigue Report — {report['generated']}")
    lines.append(f"   {report['workouts_in_period']} workouts in last {report['period_days']} days")
    lines.append("─" * 40)

    # ACWR
    lines.append("")
    lines.append(f"1. ACWR (Acute:Chronic Workload Ratio)")
    lines.append(f"   Rolling:  {a['rolling_ratio']}  {acwr_e} {acwr_s}")
    lines.append(f"   EWMA:     {a['ewma_ratio']}")
    lines.append(f"   Acute 7d avg:   {a['acute_avg']:.0f} volume")
    lines.append(f"   Chronic 28d avg: {a['chronic_avg']:.0f} volume")

    # Monotony & Strain
    lines.append("")
    lines.append(f"2. Training Monotony & Strain")
    lines.append(f"   Monotony: {m['monotony']}  {mon_e} {mon_s}")
    lines.append(f"   Strain:   {m['strain']:.0f}")
    lines.append(f"   Avg daily load: {m['daily_mean']:.0f} ± {m['daily_std']:.0f}")
    lines.append(f"   Training days:  {m['training_days']}")

    # Consecutive
    lines.append("")
    lines.append(f"3. Consecutive Training Days")
    lines.append(f"   Current:  {c['current']}  {con_e} {con_s}")
    lines.append(f"   Longest:  {c['longest']}")
    if c.get("days_since_last") is not None:
        suffix = " (today)" if c["days_since_last"] == 0 else f" ({c['days_since_last']}d ago)"
        lines.append(f"   Last workout: {c['last_workout']}{suffix}")

    # Weekly breakdown
    weekly = report.get("weekly_breakdown", [])
    if weekly:
        lines.append("")
        lines.append(f"4. Weekly Breakdown")
        lines.append(f"   {'Week':<14} {'Sess':>4} {'Volume':>8} {'Dur':>6} {'Kcal':>6}")
        for wk in weekly:
            lines.append(
                f"   {wk['week_start']:<14} {wk['sessions']:>4} "
                f"{wk['volume']:>8.0f} {fmt_dur_min(wk['duration_min']):>6} "
                f"{wk['calories']:>6.0f}"
            )

    # Exercise trends
    trends = report.get("exercise_trends", {})
    if trends:
        # Separate exercises with enough data from those without
        tracked = {k: v for k, v in trends.items() if v.get("verdict") != "insufficient_data"}
        skipped = {k: v for k, v in trends.items() if v.get("verdict") == "insufficient_data"}

        if tracked:
            lines.append("")
            lines.append(f"5. Per-Exercise Trends")
            lines.append(f"   {'Exercise':<25} {'Δ':>6} {'R²':>5} {'Status':<12}")
            for name, info in sorted(tracked.items(), key=lambda x: x[1].get("pct_change", 0)):
                pct = info.get("pct_change", 0)
                r2 = info.get("r2", 0)
                verdict = info.get("verdict", "?")
                arrow = "▲" if pct > 0 else "▼" if pct < 0 else "─"
                # Flag 2-session trends as provisional
                provisional = " *" if info.get("sessions", 0) <= 2 else ""
                lines.append(
                    f"   {name:<25} {arrow}{abs(pct):>5.1f}% {r2:>5.3f} {verdict:<12}{provisional}"
                )
            if any(info.get("sessions", 0) <= 2 for info in tracked.values()):
                lines.append(f"   (* = only 2 sessions, trend is provisional)")

    # Within-session drops
    session_fatigue = report.get("within_session_fatigue", [])
    if session_fatigue:
        lines.append("")
        lines.append(f"6. Within-Session Volume Drops (>30%)")
        for f in session_fatigue:
            lines.append(
                f"   {f['date']} — {f['exercise']}: "
                f"{f['first_vol']:.0f}→{f['last_vol']:.0f} ({f['drop_pct']:.0f}% drop, {f['sets']} sets)"
            )

    # Recommendations
    lines.append("")
    lines.append("═" * 40)
    lines.append("💡 Recommendations")
    lines.append("═" * 40)
    for rec in report.get("recommendations", []):
        lines.append(f"  {rec}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cumulative fatigue detector for Lyfta data")
    parser.add_argument("--days", type=int, default=60, help="Lookback window (days)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    report = generate_report(days=args.days)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_report_text(report))


if __name__ == "__main__":
    main()
