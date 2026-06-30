#!/usr/bin/env python3
"""
dashboard_v1.py — Minimal weekly dashboard answering 5 questions:
1. Did I stay roughly on calorie target this week?
2. How many workouts did I complete?
3. Is my 4-week weight trend moving the right way?
4. Are weekends the main source of drift?
5. Is my assumed maintenance clearly off?

Outputs: terminal text + optional PNG chart to ~/.hermes/scripts/fitness_output/
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict

# matplotlib setup for headless
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = os.path.expanduser("~/.hermes/skills/fitness-tracker/data")
DB_PATH = os.path.join(DATA_DIR, "fitness.db")
PROD_DB_PATH = os.path.expanduser("~/.hermes/skills/productivity-tracker/data/productivity.db")
PROFILE_PATH = os.path.join(DATA_DIR, "profile.json")
OUTPUT_DIR = os.path.expanduser("~/.hermes/scripts/fitness_output")

CHART_COLORS = {
    "under": "#2ca58d",
    "on_target": "#4a90e2",
    "over": "#e07a3f",
    "missing": "#d8d8d8",
}


def load_profile():
    if not os.path.exists(PROFILE_PATH):
        return {}
    with open(PROFILE_PATH) as f:
        return json.load(f)

def get_monday(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")

def get_week_label(week_start):
    d = datetime.strptime(week_start, "%Y-%m-%d")
    return f"{d.month}/{d.day}"

def calculate_chart_target_budget(profile, weeks):
    """Return the deficit calorie budget line for the weekly intake chart.

    The chart compares intake against a calorie *budget*, not maintenance.
    Use a blended rest/gym-day deficit target based on workout counts in the
    displayed weeks. If workout counts are unavailable, fall back to rest-day
    budget rather than maintenance so the line remains a weight-loss target.
    """
    sedentary = profile.get("sedentary_base_kcal", 2000)
    deficit = profile.get("deficit_midpoint_kcal", 650)
    gym_cals = profile.get("gym_calories_per_session", 420)
    rest_budget = sedentary - deficit
    gym_budget = sedentary + gym_cals - deficit

    if not weeks:
        return round(rest_budget)

    workout_days = sum(max(0, min(7, int(w.get("total_workouts") or 0))) for w in weeks)
    total_days = len(weeks) * 7
    rest_days = max(total_days - workout_days, 0)
    blended = ((workout_days * gym_budget) + (rest_days * rest_budget)) / total_days
    return round(blended)


def calculate_logged_day_target(profile, logged_days):
    """Return blended deficit budget for the provided logged days."""
    sedentary = profile.get("sedentary_base_kcal", 2000)
    deficit = profile.get("deficit_midpoint_kcal", 650)
    gym_cals = profile.get("gym_calories_per_session", 420)
    rest_budget = sedentary - deficit
    gym_budget = sedentary + gym_cals - deficit

    if not logged_days:
        return round(rest_budget)

    gym_days = sum(1 for d in logged_days if d.get("gym_flag"))
    rest_days = len(logged_days) - gym_days
    return round(((gym_days * gym_budget) + (rest_days * rest_budget)) / len(logged_days))


def format_signed_kcal(value):
    return f"{value:+.0f}"


def weekly_kcal_status(week, target):
    """Return visual status metadata for a weekly average kcal bar."""
    avg_kcal = week.get("avg_kcal")
    if avg_kcal is None:
        return {
            "state": "missing",
            "color": CHART_COLORS["missing"],
            "label": "No food logs",
            "delta": None,
            "display_value": max(target * 0.08, 80),
        }

    delta = avg_kcal - target
    if delta > 200:
        state = "over"
    elif delta < -100:
        state = "under"
    else:
        state = "on_target"

    return {
        "state": state,
        "color": CHART_COLORS[state],
        "label": f"{avg_kcal:.0f}\n{format_signed_kcal(delta)}",
        "delta": delta,
        "display_value": avg_kcal,
    }


def build_summary_cards(current_days, profile):
    """Build compact current-week status cards for the PNG dashboard."""
    logged_days = [d for d in current_days if d.get("kcal_in") is not None]
    target = calculate_logged_day_target(profile, logged_days)
    target_sessions = profile.get("gym_days_per_week", 5)
    workout_count = sum(1 for d in current_days if d.get("gym_flag"))

    if logged_days:
        avg_kcal = sum(d["kcal_in"] for d in logged_days) / len(logged_days)
        delta = avg_kcal - target
        if delta == 0:
            budget_subtitle = "on target"
        elif delta > 0:
            budget_subtitle = "slightly over" if delta <= 200 else "over target"
        else:
            budget_subtitle = "under target"
        kcal_value = f"{avg_kcal:.0f}/day"
        delta_value = f"{format_signed_kcal(delta)}/day"
    else:
        kcal_value = "No logs"
        delta_value = "—"
        budget_subtitle = "log food first"

    protein_values = [d.get("protein_g") for d in logged_days if d.get("protein_g") is not None]
    if protein_values:
        protein_value = f"{sum(protein_values) / len(protein_values):.0f}g/day"
    else:
        protein_value = "No data"

    missing_logs = max(7 - len(logged_days), 0)
    workouts_remaining = max(target_sessions - workout_count, 0)

    return [
        {"title": "Avg kcal", "value": kcal_value, "subtitle": f"logged target ~{target}"},
        {"title": "Budget Δ", "value": delta_value, "subtitle": budget_subtitle},
        {"title": "Workouts", "value": f"{workout_count}/{target_sessions}", "subtitle": "target met" if workouts_remaining == 0 else f"{workouts_remaining} to go"},
        {"title": "Food logs", "value": f"{len(logged_days)}/7", "subtitle": "complete" if missing_logs == 0 else f"{missing_logs} missing"},
        {"title": "Protein", "value": protein_value, "subtitle": "target 100–120g"},
    ]

def fetch_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Last 4 weeks of summary
    cur.execute("""
        SELECT * FROM weekly_summary
        ORDER BY week_start DESC
        LIMIT 4
    """)
    weeks = [dict(r) for r in cur.fetchall()]
    weeks.reverse()  # chronological

    # Daily data for current week
    today = datetime.now().strftime("%Y-%m-%d")
    current_monday = get_monday(today)
    cur.execute("""
        SELECT date, kcal_in, protein_g, gym_flag, adherence_score,
               workout_kcal, workout_duration_min,
               CAST(strftime('%w', date) AS INTEGER) as dow
        FROM daily_facts
        WHERE date >= ?
        ORDER BY date
    """, (current_monday,))
    current_days = [dict(r) for r in cur.fetchall()]

    # Weekend vs weekday for last 4 weeks (where we have kcal_in)
    cur.execute("""
        SELECT date, kcal_in,
               CASE WHEN CAST(strftime('%w', date) AS INTEGER) IN (0,6)
                    THEN 'weekend' ELSE 'weekday' END as period
        FROM daily_facts
        WHERE date >= date('now', '-28 days')
          AND kcal_in IS NOT NULL
    """)
    period_rows = cur.fetchall()

    conn.close()
    return weeks, current_days, period_rows

def analyze_weekends(period_rows):
    totals = {"weekday": [], "weekend": []}
    for date_str, kcal, period in period_rows:
        if kcal is not None:
            totals[period].append(kcal)

    if not totals["weekday"] or not totals["weekend"]:
        return None, None, None

    avg_weekday = sum(totals["weekday"]) / len(totals["weekday"])
    avg_weekend = sum(totals["weekend"]) / len(totals["weekend"])
    drift = avg_weekend - avg_weekday
    return avg_weekday, avg_weekend, drift

def build_weekly_review(weeks, current_days, period_rows, profile):
    report = []
    report.append("═" * 50)
    report.append("📊 FITNESS DASHBOARD v1")
    today = datetime.now().strftime("%Y-%m-%d")
    current_monday = get_monday(today)
    report.append(f"Week of {current_monday}")
    report.append("═" * 50)

    # --- Q1: Calorie target this week ---
    report.append("\n🍽  Q1: On calorie target this week?")
    if current_days:
        logged_days = [d for d in current_days if d["kcal_in"] is not None]
        logged_days.sort(key=lambda d: d["date"])
        if logged_days:
            avg_kcal = sum(d["kcal_in"] for d in logged_days) / len(logged_days)
            budget_rest = profile.get("sedentary_base_kcal", 2000) - profile.get("deficit_midpoint_kcal", 650)
            budget_gym = profile.get("sedentary_base_kcal", 2000) + profile.get("gym_calories_per_session", 420) - profile.get("deficit_midpoint_kcal", 650)
            # Approximate blended target for the days logged
            gym_days_logged = len([d for d in logged_days if d["gym_flag"]])
            rest_days_logged = len(logged_days) - gym_days_logged
            if gym_days_logged + rest_days_logged > 0:
                blended_target = (gym_days_logged * budget_gym + rest_days_logged * budget_rest) / len(logged_days)
            else:
                blended_target = budget_rest
            diff = avg_kcal - blended_target
            status = "✅ ON" if abs(diff) < 200 else ("⚠️ OVER" if diff > 0 else "🔻 UNDER")
            report.append(f"   {status} | Avg {avg_kcal:.0f} kcal/day vs target ~{blended_target:.0f}")
            report.append(f"   Logged {len(logged_days)}/7 days")
            for d in logged_days:
                dow_i = datetime.strptime(d["date"], "%Y-%m-%d").weekday()
                dow_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
                dow_name = dow_names[dow_i]
                flag = "💪" if d["gym_flag"] else "🛋"
                report.append(f"   {dow_name} {d['date'][5:]}: {d['kcal_in']:.0f} kcal {flag}")
        else:
            report.append("   No nutrition logged this week yet.")
    else:
        report.append("   No data for current week yet.")

    # --- Q2: Workouts ---
    report.append("\n🏋️ Q2: Workouts this week?")
    if current_days:
        workout_days = [d for d in current_days if d["gym_flag"]]
        report.append(f"   {len(workout_days)} sessions logged")
        target_sessions = profile.get("gym_days_per_week", 5)
        report.append(f"   Target: {target_sessions}/week")
        for d in workout_days:
            dow_i = datetime.strptime(d["date"], "%Y-%m-%d").weekday()
            dow_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            dow_name = dow_names[dow_i]
            dur = d.get("workout_duration_min")
            dur_str = f" ({dur:.0f}min)" if dur else ""
            report.append(f"   {dow_name} {d['date'][5:]}:{dur_str}")
        if len(workout_days) < target_sessions:
            remaining = target_sessions - len(workout_days)
            report.append(f"   ⏳ {remaining} more to hit target")
    else:
        report.append("   No workout data this week.")

    # --- Q3: 4-week weight trend ---
    report.append("\n⚖️  Q3: Weight trend (4 weeks)?")
    weight_weeks = [w for w in weeks if w.get("weekly_weight_kg") is not None]
    if len(weight_weeks) >= 2:
        labels = [get_week_label(w["week_start"]) for w in weight_weeks]
        weights = [w["weekly_weight_kg"] for w in weight_weeks]
        changes = [w.get("weekly_weight_change_kg") for w in weight_weeks[1:]]
        report.append(f"   Latest: {weights[-1]:.1f} kg")
        if changes:
            report.append(f"   Changes: " + ", ".join([f"{c:+.2f}" if c else "?" for c in changes]))
        goal_loss = profile.get("goal_weight_loss_per_week_kg", 0.65)
        if changes and changes[-1] is not None:
            if changes[-1] <= -goal_loss * 0.5:
                report.append(f"   ✅ Good direction (target: -{goal_loss} kg/wk)")
            elif changes[-1] <= 0:
                report.append(f"   🟡 Flat/slow (target: -{goal_loss} kg/wk)")
            else:
                report.append(f"   🔴 Gaining (target: -{goal_loss} kg/wk)")
    elif len(weight_weeks) == 1:
        report.append(f"   Only 1 weigh-in: {weight_weeks[0]['weekly_weight_kg']:.1f} kg")
        report.append("   Need ≥2 data points for trend.")
    else:
        report.append("   🚫 No weigh-ins yet.")
        report.append("   Next gym session: record weight before workout!")

    # --- Q4: Weekend drift ---
    report.append("\n📅 Q4: Weekend drift?")
    wd, we, drift = analyze_weekends(period_rows)
    if wd and we:
        report.append(f"   Weekday avg: {wd:.0f} kcal")
        report.append(f"   Weekend avg: {we:.0f} kcal")
        if drift > 300:
            report.append(f"   🔴 Weekend blowout: +{drift:.0f} kcal ({drift/wd*100:.0f}%)")
        elif drift > 100:
            report.append(f"   🟡 Moderate drift: +{drift:.0f} kcal")
        else:
            report.append(f"   ✅ Tight: {drift:+.0f} kcal")
    else:
        report.append("   Not enough data (need both weekday + weekend logs)")

    # --- Q5: Maintenance estimate ---
    report.append("\n🔬 Q5: Is assumed maintenance off?")
    assumed_gym = profile.get("sedentary_base_kcal", 2000) + profile.get("gym_calories_per_session", 420)
    assumed_rest = profile.get("sedentary_base_kcal", 2000)
    report.append(f"   Assumed: ~{assumed_rest} rest / ~{assumed_gym} gym day")

    # Use latest week with weight change + kcal data
    emp_weeks = [w for w in weeks if w.get("empirical_tdee_low") and w.get("weekly_weight_kg")]
    if emp_weeks:
        ew = emp_weeks[-1]
        report.append(f"   Empirical band: {ew['empirical_tdee_low']:.0f}–{ew['empirical_tdee_high']:.0f}")
        report.append(f"   Confidence: {ew['maintenance_confidence']}")
        mid = (ew["empirical_tdee_low"] + ew["empirical_tdee_high"]) / 2
        diff = mid - assumed_rest
        if abs(diff) < 150:
            report.append(f"   ✅ Assumed maintenance looks about right")
        elif diff > 150:
            report.append(f"   ⚠️ Real maintenance may be {diff:.0f} kcal HIGHER")
        else:
            report.append(f"   ⚠️ Real maintenance may be {abs(diff):.0f} kcal LOWER")
    else:
        report.append("   Need ≥2 weigh-ins + consistent logging to estimate.")
        report.append("   Current data too sparse — keep logging and weighing.")

    # --- Q6: Productivity this week ---
    report.append("\n🎯 Q6: Productivity this week?")
    conn2 = sqlite3.connect(DB_PATH)
    conn2.execute(f"ATTACH DATABASE '{PROD_DB_PATH}' AS prod")
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT total_blocks, total_focus_min, deep_blocks, standard_blocks, micro_blocks,
               coding_min, reading_min, watching_min, morning_win, completion_rate
        FROM prod.daily_productivity
        WHERE date >= ?
    """, (current_monday,))
    prod_days = cur2.fetchall()
    conn2.close()

    if prod_days:
        total_b = sum(d[0] or 0 for d in prod_days)
        total_m = sum(d[1] or 0 for d in prod_days)
        deep = sum(d[2] or 0 for d in prod_days)
        std = sum(d[3] or 0 for d in prod_days)
        micro = sum(d[4] or 0 for d in prod_days)
        code = sum(d[5] or 0 for d in prod_days)
        read = sum(d[6] or 0 for d in prod_days)
        watch = sum(d[7] or 0 for d in prod_days)
        mw = sum(d[8] or 0 for d in prod_days)
        avg_rate = sum(d[9] or 0 for d in prod_days) / len(prod_days)

        def fmt(m):
            return f"{m//60}h{m%60}m" if m >= 60 else f"{m}m"

        report.append(f"   {total_b} blocks | {fmt(total_m)} total focus")
        report.append(f"   Deep/Std/Micro: {deep}/{std}/{micro}")
        report.append(f"   Coding: {fmt(code)} | Reading: {fmt(read)} | Watching: {fmt(watch)}")
        report.append(f"   Morning wins: {mw}/{len(prod_days)} days | Completion: {avg_rate:.0f}%")
    else:
        report.append("   No focus blocks logged this week.")
        report.append("   Start with: focus_start.py <task> -c <category> -l <minutes>")

    # --- Bottom line ---
    report.append("\n" + "─" * 50)
    report.append("BOTTOM LINE:")
    if current_days:
        logged = [d for d in current_days if d["kcal_in"] is not None]
        avg_kcal = sum(d["kcal_in"] for d in logged) / len(logged) if logged else 0
        wdays = len([d for d in current_days if d["gym_flag"]])
        prod_str = f" | {total_b} focus blocks" if prod_days else ""
        report.append(f"   Ate ~{avg_kcal:.0f} kcal/day | {wdays} workouts{prod_str} | Weight: TBD")
        if wdays >= profile.get("gym_days_per_week", 5):
            report.append("   Gym target met — focus on food consistency.")
        else:
            report.append(f"   {profile.get('gym_days_per_week',5)-wdays} more sessions to hit target.")
    else:
        report.append("   No data yet — start logging!")
    report.append("─" * 50)

    return "\n".join(report)

def draw_summary_cards(fig, cards):
    """Draw compact metric cards across the top of the figure."""
    card_count = len(cards)
    left_margin = 0.04
    gap = 0.012
    card_width = (0.92 - gap * (card_count - 1)) / card_count
    y = 0.76
    height = 0.18

    for i, card in enumerate(cards):
        x = left_margin + i * (card_width + gap)
        rect = plt.Rectangle(
            (x, y), card_width, height,
            transform=fig.transFigure,
            facecolor="#f7f8fa",
            edgecolor="#d9dee7",
            linewidth=1.0,
            zorder=2,
        )
        fig.patches.append(rect)
        fig.text(x + 0.015, y + height - 0.045, card["title"].upper(),
                 fontsize=8, color="#667085", weight="bold")
        fig.text(x + 0.015, y + 0.072, card["value"],
                 fontsize=15, color="#101828", weight="bold")
        fig.text(x + 0.015, y + 0.025, card["subtitle"],
                 fontsize=8.5, color="#667085")


def build_chart(weeks, current_days, period_rows):
    """Build dashboard PNG with intake, budget, workouts, and weight in one frame."""
    profile = load_profile()
    fig, ax1 = plt.subplots(1, 1, figsize=(13, 6.2))
    fig.suptitle("Fitness Dashboard", fontsize=16, fontweight="bold", x=0.04, ha="left", y=0.98)
    draw_summary_cards(fig, build_summary_cards(current_days, profile))

    wk_labels = [get_week_label(w["week_start"]) for w in weeks]
    workouts = [w.get("total_workouts") or 0 for w in weeks]
    target = calculate_chart_target_budget(profile, weeks)
    statuses = [weekly_kcal_status(w, target) for w in weeks]
    avg_kcals_display = [s["display_value"] for s in statuses]
    colors = [s["color"] for s in statuses]
    x = list(range(len(wk_labels)))

    # Primary axis: weekly calorie intake bars + deficit budget line.
    bars = ax1.bar(x, avg_kcals_display, color=colors, alpha=0.86, label="Avg kcal")
    for bar, status in zip(bars, statuses):
        if status["state"] == "missing":
            bar.set_hatch("///")
            bar.set_alpha(0.55)
            label_xytext = (0, 6)
            label_va = "bottom"
            label_color = "#444"
            label_bbox = dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.85)
            fontweight = "normal"
        else:
            label_xytext = (0, -18)
            label_va = "top"
            label_color = "white"
            label_bbox = None
            fontweight = "bold"
        ax1.annotate(
            status["label"],
            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
            xytext=label_xytext,
            textcoords="offset points",
            ha="center",
            va=label_va,
            fontsize=9,
            fontweight=fontweight,
            color=label_color,
            bbox=label_bbox,
        )

    budget_line = ax1.axhline(
        y=target,
        color="#667085",
        linestyle="--",
        linewidth=1.3,
        alpha=0.75,
        label=f"4wk budget ~{target}",
    )
    ax1.set_xticks(x)
    ax1.set_xticklabels(wk_labels)
    ax1.set_ylabel("Avg kcal/day")
    ax1.set_title("Weekly Intake, Budget & Weight Trend")
    ax1.grid(axis="y", alpha=0.18)
    ymax = max(avg_kcals_display + [target]) * 1.30 if avg_kcals_display else target * 1.30
    ax1.set_ylim(0, ymax)

    # Workout count is contextual, not a third axis: show it as a top row.
    workout_y = ymax * 0.94
    for xi, workout_count in zip(x, workouts):
        ax1.annotate(
            f"{workout_count} workout{'s' if workout_count != 1 else ''}",
            xy=(xi, workout_y),
            ha="center",
            va="center",
            fontsize=8.5,
            color="#b42318",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#fff1f0", edgecolor="#f4b4ad", alpha=0.9),
        )

    # Secondary axis: weight trend on the same weekly x-axis.
    ax2 = ax1.twinx()
    weight_points_x = []
    weights = []
    for i, w in enumerate(weeks):
        if w.get("weekly_weight_kg") is not None:
            weight_points_x.append(i)
            weights.append(w["weekly_weight_kg"])

    weight_line = None
    if len(weights) >= 2:
        (weight_line,) = ax2.plot(
            weight_points_x,
            weights,
            "o-",
            color="#2563eb",
            linewidth=2.4,
            markersize=7,
            label="Weight",
            zorder=5,
        )
        for xi, weight in zip(weight_points_x, weights):
            ax2.annotate(
                f"{weight:.1f}",
                xy=(xi, weight),
                xytext=(0, 9),
                textcoords="offset points",
                ha="center",
                fontsize=8.5,
                color="#1d4ed8",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.78),
            )
        change = weights[-1] - weights[0]
        ax2.annotate(
            f"{change:+.2f} kg",
            xy=(weight_points_x[-1], weights[-1]),
            xytext=(12, 0),
            textcoords="offset points",
            va="center",
            fontsize=10,
            color="green" if change <= 0 else "red",
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="none", alpha=0.75),
        )
        pad = max((max(weights) - min(weights)) * 0.18, 0.25)
        ax2.set_ylim(min(weights) - pad, max(weights) + pad)
    else:
        ax2.text(
            0.5,
            0.50,
            "Need ≥2 weigh-ins for weight line",
            ha="center",
            va="center",
            transform=ax2.transAxes,
            fontsize=10,
            color="#667085",
        )
    ax2.set_ylabel("Weight (kg)", color="#2563eb")
    ax2.tick_params(axis="y", labelcolor="#2563eb")

    # Combined legend below the single frame.
    handles, labels = ax1.get_legend_handles_labels()
    if weight_line is not None:
        handles.append(weight_line)
        labels.append("Weight")
    ax1.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=len(handles),
        fontsize=8.5,
        frameon=False,
    )

    fig.text(
        0.04,
        0.075,
        "Workout counts are shown as red chips; weight uses the blue right axis.",
        fontsize=8.5,
        color="#667085",
    )

    plt.tight_layout(rect=[0.04, 0.10, 0.98, 0.72])
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"dashboard_{datetime.now().strftime('%Y%m%d')}.png")
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Chart saved: {path}")
    return path

def main():
    profile = load_profile()
    weeks, current_days, period_rows = fetch_data()
    report = build_weekly_review(weeks, current_days, period_rows, profile)
    print(report)
    chart_path = build_chart(weeks, current_days, period_rows)
    return report, chart_path

if __name__ == "__main__":
    main()
