import importlib.util
from pathlib import Path


def load_dashboard():
    script = Path(__file__).resolve().parents[1] / "scripts" / "dashboard_v1.py"
    spec = importlib.util.spec_from_file_location("dashboard_v1", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chart_target_uses_rest_day_deficit_budget_when_no_workouts():
    dashboard = load_dashboard()
    profile = {
        "sedentary_base_kcal": 2000,
        "deficit_midpoint_kcal": 650,
        "gym_calories_per_session": 400,
    }
    weeks = [{"week_start": "2026-04-20", "total_workouts": 0}]

    target = dashboard.calculate_chart_target_budget(profile, weeks)

    assert target == 1350


def test_chart_target_uses_blended_deficit_budget_when_workouts_exist():
    dashboard = load_dashboard()
    profile = {
        "sedentary_base_kcal": 2000,
        "deficit_midpoint_kcal": 650,
        "gym_calories_per_session": 400,
    }
    weeks = [{"week_start": "2026-04-20", "total_workouts": 5}]

    target = dashboard.calculate_chart_target_budget(profile, weeks)

    # 5 gym days at 1750 budget + 2 rest days at 1350 budget, averaged over 7 days.
    assert target == round(((5 * 1750) + (2 * 1350)) / 7)
