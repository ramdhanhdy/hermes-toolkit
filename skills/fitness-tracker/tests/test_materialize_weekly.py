import importlib.util
import sqlite3
from pathlib import Path


def load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "materialize_weekly.py"
    spec = importlib.util.spec_from_file_location("materialize_weekly", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE daily_facts (
            date TEXT PRIMARY KEY,
            kcal_in REAL,
            protein_g REAL,
            carbs_g REAL,
            fat_g REAL,
            gym_flag INTEGER,
            workout_kcal REAL,
            workout_duration_min REAL,
            steps_estimated REAL,
            adherence_score REAL,
            hunger_score REAL,
            energy_score REAL,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE weekly_checkins (
            checkin_date TEXT PRIMARY KEY,
            weight_kg REAL,
            waist_cm REAL,
            weighin_time TEXT,
            pre_workout INTEGER,
            clothing_notes TEXT,
            comment TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE weekly_summary (
            week_start TEXT PRIMARY KEY,
            avg_kcal REAL,
            avg_protein_g REAL,
            total_workouts INTEGER,
            total_workout_min REAL,
            avg_adherence REAL,
            avg_hunger REAL,
            avg_energy REAL,
            weekly_weight_kg REAL,
            weekly_weight_change_kg REAL,
            empirical_tdee_low REAL,
            empirical_tdee_high REAL,
            maintenance_confidence TEXT
        )
    """)
    return conn


def test_materialize_averages_only_logged_nutrition_days(tmp_path):
    db_path = tmp_path / "fitness.db"
    conn = init_db(db_path)
    rows = [
        ("2026-04-13", 1600, 100, 1, 60, 90),
        ("2026-04-14", None, None, 1, 50, None),  # Lyfta-only row; must not dilute nutrition averages
        ("2026-04-15", 1800, 120, 0, None, 95),
        ("2026-04-16", None, None, 1, 40, None),
    ]
    conn.executemany(
        "INSERT INTO daily_facts (date, kcal_in, protein_g, gym_flag, workout_duration_min, adherence_score) VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    module = load_module()
    module.DB_PATH = str(db_path)
    module.PROFILE_PATH = str(tmp_path / "missing_profile.json")

    module.materialize()

    conn = sqlite3.connect(db_path)
    avg_kcal, avg_protein = conn.execute(
        "SELECT avg_kcal, avg_protein_g FROM weekly_summary WHERE week_start='2026-04-13'"
    ).fetchone()
    conn.close()

    assert avg_kcal == 1700
    assert avg_protein == 110


def test_empirical_tdee_rises_above_intake_when_weight_decreases(tmp_path):
    db_path = tmp_path / "fitness.db"
    conn = init_db(db_path)
    for date in ["2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10", "2026-04-11", "2026-04-12"]:
        conn.execute(
            "INSERT INTO daily_facts (date, kcal_in, protein_g, gym_flag, adherence_score) VALUES (?, 1700, 100, 0, 100)",
            (date,),
        )
    for date in ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17", "2026-04-18", "2026-04-19"]:
        conn.execute(
            "INSERT INTO daily_facts (date, kcal_in, protein_g, gym_flag, adherence_score) VALUES (?, 1700, 100, 0, 100)",
            (date,),
        )
    conn.execute("INSERT INTO weekly_checkins (checkin_date, weight_kg) VALUES ('2026-04-06', 83.0)")
    conn.execute("INSERT INTO weekly_checkins (checkin_date, weight_kg) VALUES ('2026-04-13', 82.5)")
    conn.commit()
    conn.close()

    module = load_module()
    module.DB_PATH = str(db_path)
    module.PROFILE_PATH = str(tmp_path / "missing_profile.json")

    module.materialize()

    conn = sqlite3.connect(db_path)
    low, high = conn.execute(
        "SELECT empirical_tdee_low, empirical_tdee_high FROM weekly_summary WHERE week_start='2026-04-13'"
    ).fetchone()
    conn.close()

    assert low == 2050
    assert high == 2450
