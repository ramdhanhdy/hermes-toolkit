# Fitness Tracker Skill

A Hermes skill for personal fitness tracking — calorie budgeting, macro tracking, workout detection, and weight monitoring. Designed for daily use via Telegram.

## Features

- **Meal logging** — log meals with automatic macro lookup (USDA / FatSecret data)
- **Workout detection** — syncs with Lyfta gym app, estimates calories burned using MET × duration
- **Calorie budgeting** — daily targets based on BMR (Mifflin-St Jeor), activity level, and deficit goal
- **Weight tracking** — daily weigh-ins with noise filtering (see [fitness-scale-and-nutrition-coaching](fitness-scale-and-nutrition-coaching/SKILL.md))
- **Daily dashboard** — macro breakdown table (P/F/C grams + kcal vs remaining budget)
- **Fatigue monitoring** — tracks training load and warns on overreaching

## Installation

```bash
# As a Hermes skill tap
hermes skills tap add <your-username>/hermes-toolkit
hermes skills install fitness-tracker
```

## Configuration

1. Copy `data/profile.example.json` to `data/profile.json` and fill in your stats
2. Set `LYFTA_API_KEY` in your environment (for workout sync)
3. Run `python3 scripts/init_db.py` to initialize the SQLite database

## Scripts

| Script | Purpose |
|--------|---------|
| `run_pipeline.py` | Full daily pipeline (sync → detect → dashboard) |
| `daily_dashboard.py` | Generate today's macro summary |
| `detect_new_workout.py` | Check for new Lyfta workouts and log them |
| `lyfta_sync.py` | Fetch workouts from Lyfta API |
| `etl_sync.py` | Sync data between SQLite and JSON caches |
| `materialize_weekly.py` | Roll daily data into weekly aggregates |
| `fatigue_monitor.py` | Analyze training load trends |
| `import_weight_csv.py` | Bulk import weight data from CSV |
| `import_weight_xlsx.py` | Bulk import weight data from XLSX |
| `log_checkin.py` | Manual check-in logger |
| `init_db.py` | Database initialization |

## Sub-Skills

- [nutrition-logging](nutrition-logging/SKILL.md) — Meal and drink logging
- [nutrition-tracking](nutrition-tracking/SKILL.md) — Live nutrition data lookup
- [nutrition-tracker-operations](nutrition-tracker-operations/SKILL.md) — Tracker operations
- [fitness-scale-and-nutrition-coaching](fitness-scale-and-nutrition-coaching/SKILL.md) — Weight interpretation + coaching

## Dependencies

- Python 3.11+
- `requests` (Lyfta API)
- `matplotlib` (optional, for charts)

## License

MIT
