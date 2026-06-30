import importlib.util
from pathlib import Path


def load_dashboard():
    script = Path(__file__).resolve().parents[1] / "scripts" / "dashboard_v1.py"
    spec = importlib.util.spec_from_file_location("dashboard_v1", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_weekly_kcal_status_marks_missing_data_explicitly():
    dashboard = load_dashboard()

    status = dashboard.weekly_kcal_status({"avg_kcal": None}, 1587)

    assert status["state"] == "missing"
    assert status["color"] == dashboard.CHART_COLORS["missing"]
    assert status["label"] == "No food logs"


def test_weekly_kcal_status_colors_over_under_and_on_budget():
    dashboard = load_dashboard()

    under = dashboard.weekly_kcal_status({"avg_kcal": 1400}, 1587)
    on_target = dashboard.weekly_kcal_status({"avg_kcal": 1630}, 1587)
    over = dashboard.weekly_kcal_status({"avg_kcal": 1825}, 1587)

    assert under["state"] == "under"
    assert under["color"] == dashboard.CHART_COLORS["under"]
    assert under["label"] == "1400\n-187"
    assert on_target["state"] == "on_target"
    assert on_target["color"] == dashboard.CHART_COLORS["on_target"]
    assert on_target["label"] == "1630\n+43"
    assert over["state"] == "over"
    assert over["color"] == dashboard.CHART_COLORS["over"]
    assert over["label"] == "1825\n+238"


def test_build_summary_cards_reports_current_week_status():
    dashboard = load_dashboard()
    current_days = [
        {"date": "2026-04-20", "kcal_in": 1500, "protein_g": 90, "gym_flag": 1},
        {"date": "2026-04-21", "kcal_in": 1700, "protein_g": 110, "gym_flag": 0},
        {"date": "2026-04-22", "kcal_in": None, "protein_g": None, "gym_flag": 1},
    ]
    profile = {
        "sedentary_base_kcal": 2000,
        "deficit_midpoint_kcal": 650,
        "gym_calories_per_session": 400,
        "gym_days_per_week": 5,
    }

    cards = dashboard.build_summary_cards(current_days, profile)

    assert cards == [
        {"title": "Avg kcal", "value": "1600/day", "subtitle": "logged target ~1550"},
        {"title": "Budget Δ", "value": "+50/day", "subtitle": "slightly over"},
        {"title": "Workouts", "value": "2/5", "subtitle": "3 to go"},
        {"title": "Food logs", "value": "2/7", "subtitle": "5 missing"},
        {"title": "Protein", "value": "100g/day", "subtitle": "target 100–120g"},
    ]
