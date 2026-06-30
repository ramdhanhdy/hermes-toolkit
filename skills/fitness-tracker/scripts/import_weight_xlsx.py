#!/usr/bin/env python3
"""
import_weight_xlsx.py — Import MovingLife / smart-scale XLSX exports into weekly_checkins.

This exists because Telegram/Hermes accepts .xlsx attachments but rejects raw .csv.
The MovingLife export sometimes stores ambiguous dates as Excel serial numbers with
month/day reversed; this importer normalizes those into realistic MM-DD dates.

Examples:
  python3 scripts/import_weight_xlsx.py ~/Downloads/movinglife_export.xlsx --dry-run
  python3 scripts/import_weight_xlsx.py ~/Downloads/movinglife_export.xlsx --run-pipeline
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SKILL_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "fitness.db"
NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def colnum(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def parse_float_from_text(value: object, field_name: str) -> float:
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    if not match:
        raise ValueError(f"Invalid {field_name}: {value!r}")
    return float(match.group(0).replace(",", "."))


def parse_percent(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    parsed = parse_float_from_text(value, "percent")
    return parsed * 100 if 0 <= parsed <= 1 else parsed


def parse_date(value: object) -> tuple[str, str]:
    """Return (YYYY-MM-DD, HH:MM)."""
    raw = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        serial_dt = datetime(1899, 12, 30) + timedelta(days=float(raw))
        # MovingLife exports observed in Apr 2026 stored ambiguous dates as serials
        # whose month/day need swapping, e.g. Excel 2026-08-04 means 2026-04-08.
        try:
            swapped = serial_dt.replace(month=serial_dt.day, day=serial_dt.month)
            return swapped.date().isoformat(), swapped.strftime("%H:%M")
        except ValueError:
            return serial_dt.date().isoformat(), serial_dt.strftime("%H:%M")

    for fmt in (
        "%m-%d-%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m-%d-%Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.date().isoformat(), dt.strftime("%H:%M")
        except ValueError:
            pass
    raise ValueError(f"Invalid date: {raw!r}")


def read_first_sheet_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", NS):
                shared.append("".join(t.text or "" for t in si.findall(".//main:t", NS)))

        # MovingLife export has one sheet; use first worksheet for dependency-free parsing.
        sheet_path = sorted(name for name in names if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))[0]
        sheet = ET.fromstring(z.read(sheet_path))
        rows: list[list[str]] = []
        for row in sheet.findall("main:sheetData/main:row", NS):
            cells: list[tuple[int, str]] = []
            maxidx = -1
            for c in row.findall("main:c", NS):
                idx = colnum(c.attrib.get("r", "A1"))
                maxidx = max(maxidx, idx)
                cell_type = c.attrib.get("t")
                value = c.find("main:v", NS)
                text = ""
                if value is not None:
                    raw = value.text or ""
                    text = shared[int(raw)] if cell_type == "s" and raw.isdigit() else raw
                elif cell_type == "inlineStr":
                    text = "".join(t.text or "" for t in c.findall(".//main:t", NS))
                cells.append((idx, text))
            values = [""] * (maxidx + 1)
            for idx, text in cells:
                values[idx] = text
            if any(str(v).strip() for v in values):
                rows.append(values)
        return rows


def read_rows(path: Path) -> list[dict[str, object]]:
    rows = read_first_sheet_rows(path)
    if not rows:
        raise ValueError("XLSX has no rows")
    headers = [h.strip() for h in rows[0]]
    required = {"date", "Weight"}
    missing = required - set(headers)
    if missing:
        raise ValueError(f"XLSX missing required columns: {', '.join(sorted(missing))}")

    parsed_rows: list[dict[str, object]] = []
    for raw_row in rows[1:]:
        raw_row += [""] * (len(headers) - len(raw_row))
        data = dict(zip(headers, raw_row))
        checkin_date, weighin_time = parse_date(data.get("date", ""))
        weight_kg = parse_float_from_text(data.get("Weight", ""), "Weight")

        comment_parts = ["MovingLife XLSX import"]
        body_fat = parse_percent(data.get("Body Fat(%)"))
        muscle = parse_percent(data.get("Muscle(%)"))
        if body_fat is not None:
            comment_parts.append(f"body_fat={body_fat:.1f}%")
        if muscle is not None:
            comment_parts.append(f"muscle={muscle:.1f}%")
        for label, column in (("BMI", "BMI"), ("BMR", "BMR"), ("lean_mass", "Lean body mass")):
            value = data.get(column)
            if value:
                comment_parts.append(f"{label}={value}")

        parsed_rows.append(
            {
                "checkin_date": checkin_date,
                "weight_kg": weight_kg,
                "waist_cm": None,
                "weighin_time": weighin_time,
                "pre_workout": 1,
                "clothing_notes": "",
                "comment": "; ".join(comment_parts),
            }
        )
    return parsed_rows


def import_rows(db_path: Path, rows: list[dict[str, object]]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
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
    parser = argparse.ArgumentParser(description="Import MovingLife XLSX weight data into fitness.db")
    parser.add_argument("xlsx_path", help="XLSX file path")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Target SQLite DB path")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print rows without writing")
    parser.add_argument("--run-pipeline", action="store_true", help="Run scripts/run_pipeline.py after import")
    args = parser.parse_args()

    xlsx_path = Path(os.path.expanduser(args.xlsx_path)).resolve()
    db_path = Path(os.path.expanduser(args.db_path)).resolve()
    rows = read_rows(xlsx_path)
    print(f"Parsed {len(rows)} weigh-in row(s) from {xlsx_path}")
    for row in rows[:8]:
        print(f"  {row['checkin_date']} {row['weighin_time']} — {row['weight_kg']} kg")
    if len(rows) > 8:
        print(f"  ... {len(rows) - 8} more")

    if args.dry_run:
        print("Dry run only; database not modified.")
        return 0

    import_rows(db_path, rows)
    print(f"✅ Imported/upserted {len(rows)} row(s) into {db_path}")

    if args.run_pipeline:
        subprocess.run([sys.executable, str(SKILL_DIR / "scripts" / "run_pipeline.py")], check=True, cwd=str(SKILL_DIR))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
