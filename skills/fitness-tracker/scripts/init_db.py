#!/usr/bin/env python3
"""
init_db.py — Create the fitness SQLite schema.
Run this once to set up the database, then use etl_sync.py to populate it.
"""
import sqlite3
import os

DB_PATH = os.path.expanduser("~/.hermes/skills/fitness-tracker/data/fitness.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_facts (
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
);

CREATE TABLE IF NOT EXISTS weekly_checkins (
    checkin_date TEXT PRIMARY KEY,
    weight_kg REAL,
    waist_cm REAL,
    weighin_time TEXT,
    pre_workout INTEGER,
    clothing_notes TEXT,
    comment TEXT
);

CREATE TABLE IF NOT EXISTS weekly_summary (
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
);
"""

def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database initialized at: {DB_PATH}")

if __name__ == "__main__":
    init()
