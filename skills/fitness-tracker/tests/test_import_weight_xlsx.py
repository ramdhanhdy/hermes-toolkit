"""Tests for MovingLife XLSX weight import helpers."""

from pathlib import Path
import sys

SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_DIR / "scripts"))

from import_weight_xlsx import parse_date, parse_float_from_text, parse_percent


def test_parse_movinglife_weight_text():
    assert parse_float_from_text("81.80kg", "Weight") == 81.8


def test_parse_fraction_percent_as_human_percent():
    assert parse_percent("0.314") == 31.4


def test_parse_numeric_serial_swaps_ambiguous_movinglife_date():
    # Excel serial for 2026-08-04 17:08, but MovingLife export row context shows 2026-04-08.
    assert parse_date("46238.71407407407") == ("2026-04-08", "17:08")
