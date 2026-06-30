#!/usr/bin/env python3
"""
import_weight_csv.py — Import historical weigh-ins from a CSV into weekly_checkins.

Default target DB: ~/.hermes/skills/fitness-tracker/data/fitness.db

Accepted CSV columns are intentionally flexible:
- date/checkin_date/day (required)
- weight_kg/weight/kg/body_weight (required)
- waist_cm/waist (optional)
- weighin_time/time (optional; default: afternoon)
- pre_workout/pre-workout/before_workout (optional bool; default: true)
- clothing_notes/clothing (optional)
- comment/notes/note (optional)

Examples:
  python3 scripts/import_weight_csv.py ~/Downloads/weight.csv --dry-run
  python3 scripts/import_weight_csv.py ~/Downloads/weight.csv --run-pipeline
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "fitness.db"

COLUMN_ALIASES = {
    "date": ["date", "checkin_date", "day", "weigh_in_date", "weighin_date", "timestamp", "created_at"],
    "weight_kg": ["weight_kg", "weight", "kg", "body_weight", "bodyweight", "weight (kg)", "weight(kg)"],
    "waist_cm": ["waist_cm", "waist", "waist (cm)", "waist(cm)"],
    "weighin_time": ["weighin_time", "weigh_in_time", "time", "time_of_day"],
    "pre_workout": ["pre_workout", "pre-workout", "before_workout", "before workout", "pre workout"],
    "clothing_notes": ["clothing_notes", "clothing", "clothes"],
    "comment": ["comment", "comments", "note", "notes"],
}


def normalize_header(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


def build_column_map(headers: list[str]) -> dict[str, str]:
    normalized = {normalize_header(header): header for header in headers}
    column_map: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = normalize_header(alias)
            if key in normalized:
                column_map[canonical] = normalized[key]
                break
    return column_map


def parse_float(value: Any, field_name: str, row_num: int, required: bool = False) -> float | None:
    if value is None or str(value).strip() == "":
        if required:
            raise ValueError(f"Row {row_num}: missing required {field_name}")
        return None
    cleaned = str(value).strip().replace(",", ".")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(f"Row {row_num}: invalid {field_name}: {value!r}") from exc


def parse_date(value: Any, row_num: int) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError(f"Row {row_num}: missing required date")
    raw = str(value).strip()
    # Try ISO/date-like formats first. For timestamps, keep date component only.
    candidates = [raw, raw.split("T", 1)[0], raw.split(" ", 1)[0]]
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"]
    for candidate in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
            except ValueError:
                pass
    raise ValueError(f"Row {row_num}: invalid date format: {raw!r}")


def parse_bool(value: Any, default: bool = True) -> int:
    if value is None or str(value).strip() == "":
        return 1 if default else 0
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "pre", "before", "pre-workout", "pre workout"}:
        return 1
    if raw in {"0", "false", "no", "n", "post", "after", "post-workout", "post workout"}:
        return 0
    return 1 if default else 0


def read_rows(csv_path: Path) -> list[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        column_map = build_column_map(reader.fieldnames)
        missing = [name for name in ("date", "weight_kg") if name not in column_map]
        if missing:
            raise ValueError(
                "CSV is missing required column(s): "
                + ", ".join(missing)
                + ". Expected date/checkin_date and weight_kg/weight/kg."
            )

        rows: list[dict[str, Any]] = []
        for row_num, raw_row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in raw_row.values()):
                continue
            get = lambda canonical: raw_row.get(column_map[canonical], "") if canonical in column_map else ""
            rows.append(
                {
                    "checkin_date": parse_date(get("date"), row_num),
                    "weight_kg": parse_float(get("weight_kg"), "weight_kg", row_num, required=True),
                    "waist_cm": parse_float(get("waist_cm"), "waist_cm", row_num) if "waist_cm" in column_map else None,
                    "weighin_time": str(get("weighin_time") or "afternoon").strip(),
                    "pre_workout": parse_bool(get("pre_workout"), default=True),
                    "clothing_notes": str(get("clothing_notes") or "").strip(),
                    "comment": str(get("comment") or "Imported from CSV").strip(),
                }
            )
        return rows


def import_rows(db_path: Path, rows: list[dict[str, Any]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO weekly_checkins
            (checkin_date, weight_kg, waist_cm, weighin_time, pre_workout, clothing_notes, comment)
            VALUES (:checkin_date, :weight_kg, :waist_cm, :weighin_time, :pre_workout, :clothing_notes, :comment)
            ON CONFLICT(checkin_date) DO UPDATE SET
                weight_kg=excluded.weight_kg,
                waist_cm=COALESCE(excluded.waist_cm, weekly_checkins.waist_cm),
                weighin_time=excluded.weighin_time,
                pre_workout=excluded.pre_workout,
                clothing_notes=excluded.clothing_notes,
                comment=excluded.comment
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import weight check-ins from CSV into fitness.db")
    parser.add_argument("csv_path", help="CSV file path")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite DB path")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print rows without writing")
    parser.add_argument("--run-pipeline", action="store_true", help="Run scripts/run_pipeline.py after import")
    args = parser.parse_args()

    csv_path = Path(os.path.expanduser(args.csv_path)).resolve()
    db_path = Path(os.path.expanduser(args.db_path)).resolve()

    rows = read_rows(csv_path)
    if not rows:
        print("No rows to import.")
        return 0

    print(f"Parsed {len(rows)} weigh-in row(s) from {csv_path}")
    for row in rows[:5]:
        print(f"  {row['checkin_date']}: {row['weight_kg']} kg")
    if len(rows) > 5:
        print(f"  ... {len(rows) - 5} more")

    if args.dry_run:
        print("Dry run only; database not modified.")
        return 0

    import_rows(db_path, rows)
    print(f"✅ Imported {len(rows)} row(s) into {db_path}")

    if args.run_pipeline:
        subprocess.run([sys.executable, str(SKILL_DIR / "scripts" / "run_pipeline.py")], check=True, cwd=str(SKILL_DIR))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
