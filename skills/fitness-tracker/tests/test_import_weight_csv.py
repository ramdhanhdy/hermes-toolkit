"""Tests for CSV weight import."""

import sqlite3
from pathlib import Path
import sys

SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))

from import_weight_csv import import_rows, read_rows


def make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE weekly_checkins (
            checkin_date TEXT PRIMARY KEY,
            weight_kg REAL,
            waist_cm REAL,
            weighin_time TEXT,
            pre_workout INTEGER,
            clothing_notes TEXT,
            comment TEXT
        );
        """
    )
    conn.close()


def test_import_weight_csv_accepts_common_headers(tmp_path):
    csv_path = tmp_path / "weights.csv"
    csv_path.write_text(
        "Date,Weight,Waist,Notes\n"
        "2026-04-20,83.2,92.5,first gym checkin\n"
        "21/04/2026,82.9,,second gym checkin\n",
        encoding="utf-8",
    )

    rows = read_rows(csv_path)

    assert rows[0]["checkin_date"] == "2026-04-20"
    assert rows[0]["weight_kg"] == 83.2
    assert rows[0]["waist_cm"] == 92.5
    assert rows[0]["comment"] == "first gym checkin"
    assert rows[1]["checkin_date"] == "2026-04-21"


def test_import_weight_csv_upserts_weekly_checkins(tmp_path):
    db_path = tmp_path / "fitness.db"
    make_db(db_path)
    rows = [
        {
            "checkin_date": "2026-04-20",
            "weight_kg": 83.2,
            "waist_cm": None,
            "weighin_time": "afternoon",
            "pre_workout": 1,
            "clothing_notes": "",
            "comment": "first",
        },
        {
            "checkin_date": "2026-04-20",
            "weight_kg": 82.8,
            "waist_cm": None,
            "weighin_time": "afternoon",
            "pre_workout": 1,
            "clothing_notes": "",
            "comment": "updated",
        },
    ]

    import_rows(db_path, rows)

    conn = sqlite3.connect(db_path)
    result = conn.execute("SELECT checkin_date, weight_kg, comment FROM weekly_checkins").fetchall()
    conn.close()
    assert result == [("2026-04-20", 82.8, "updated")]
