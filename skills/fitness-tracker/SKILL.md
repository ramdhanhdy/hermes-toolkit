---
name: fitness-tracker
description: Personal fitness tracking — calorie budgeting, meal logging, weight tracking, and Lyfta workout integration for deficit-based weight loss. Uses SQLite pipeline. Productivity tracking split to `productivity-tracker` skill.
category: automation
---

# Fitness Tracker

Personal calorie deficit tracking system for weight loss. Combines nutrition logging, gym workout data (via Lyfta API), and weekly weigh-ins into a SQLite-backed analytics pipeline.

> Productivity tracking (focus blocks, projects) was split to the `productivity-tracker` skill on 2026-04-23. The dashboard still shows productivity data via SQLite `ATTACH DATABASE`.

## Setup / Dependencies

**See `references/railway-deployment.md`** for Railway-specific deployment notes (canonical path symlink, read-only venv workaround, productivity DB stub, verification checklist).

**Python packages** (required by pipeline scripts):
- `requests` — Lyfta API calls (`lyfta_sync.py`, `detect_new_workout.py`)
- `matplotlib` — dashboard chart generation (`dashboard_v1.py`)

Install with: `uv pip install requests matplotlib` (or `--target` if the system venv is read-only).

**Productivity DB stub** (required for dashboard to run, even without productivity data):
```bash
mkdir -p ~/.hermes/skills/productivity-tracker/data
python3 -c "
import sqlite3
db = sqlite3.connect(os.path.expanduser('~/.hermes/skills/productivity-tracker/data/productivity.db'))
db.execute('''CREATE TABLE IF NOT EXISTS daily_productivity (
    date TEXT PRIMARY KEY, total_blocks INTEGER, total_focus_min REAL,
    deep_blocks INTEGER, standard_blocks INTEGER, micro_blocks INTEGER,
    coding_min REAL, reading_min REAL, watching_min REAL,
    morning_win TEXT, completion_rate REAL
)''')
db.commit(); db.close()
"
```

**Lyfta API key:** Set `LYFTA_API_KEY` as an environment variable (Railway service variable, or in `~/.hermes/.env` as `LYFTA_API_KEY=...`). The sync script checks both.

**Canonical path:** Scripts hardcode `~/.hermes/skills/fitness-tracker/`. If the skill lives elsewhere (e.g., `~/.hermes/skills/.archive/...` or `<hermes-skills-dir>/`), create a symlink:
```bash
mkdir -p ~/.hermes/skills
ln -sfn /actual/path/to/fitness-tracker ~/.hermes/skills/fitness-tracker
```

## User Profile

- 33M, 159cm, ~83kg (update weight in data/profile.json as it changes)
- BMR: 1,664 kcal | Sedentary base: 1,997 kcal
- Gym: 5x/week strength training, ~420 kcal/session
- Weigh-in: weekly at gym (no home scale)
- Target: 0.5-0.8 kg/week loss (midpoint 650 kcal daily deficit)
- Collagen target: 2.5g/day (Hilo Berryfit: 500mg, Hilo Active: 2,000mg)

## Daily Budget

| Scenario  | Expenditure | Budget (expenditure - 650) |
|-----------|-------------|---------------------------|
| Gym day   | ~2,400 kcal | ~1,750 kcal               |
| Rest day  | ~2,000 kcal | ~1,350 kcal               |

Budget is dynamic: if Lyfta data shows a different workout duration/volume, adjust gym calories accordingly. If user does cardio classes (FatBurn, HIIT, etc.) in addition to strength, add ~250-400 kcal to expenditure for that day.

**⏰ Weekdays default to gym day — verify by end of day.** When logging meals on Mon-Fri, assume gym day budget (~1,767 kcal) by default. However, always sync Lyfta by evening (`lyfta_sync.py --days 1`) to verify. If Lyfta definitively shows no workout that day, switch budget to rest day (~1,347 kcal) and recalculate remaining. Do NOT silently flip the assumption without checking — the user corrected this on 2026-06-22 when a Monday was mislabeled as rest without verification. Sunday is always a scheduled rest day.

## Core Philosophy: Weekly Measurement, Daily Behavior

This system treats **bodyweight as a weekly validation signal**, not a daily modeling target. That means:
- **Daily:** log food, log workouts, observe adherence
- **Weekly:** one standardized weigh-in at the gym (same day, same time, before workout)
- **Analytics:** weekly regression, empirical TDEE bands, weekend drift — not daily TDEE calibration or Kalman filtering

This is more honest than pretending high-frequency bodyweight data exists.

## Workflows

### Meal Logging (user texts what they ate)

For future smart-scale or hardware-assisted logging, see `references/smart-food-scale.md` for the ESP32/HX711 portable scale blueprint, price estimate, and integration path into this tracker.

1. Parse food items, amounts, cooking methods
   - **Clarify portion weights when ambiguous.** If user says "60g of wrap + patty + egg + tomato", ask: "is that 60g total or 60g for just the wrap?" Combining multiple items under one weight is common — don't assume individual weights without confirming.
2. Look up calories via USDA FoodData Central or FatSecret
3. **Write to `data/daily_nutrition.json` immediately.** Do NOT just calculate and report — the data must persist. Append the meal to today's `meals` array and recalculate `total_kcal`.
4. **Auto-run the pipeline** (`etl_sync.py` → `materialize_weekly.py` → `dashboard_v1.py`) without asking the user. They expect data to flow seamlessly.

   **On Railway:** `execute_code` and `memory` are both blocked in cron mode. Use `terminal()`, `read_file`, `search_files`, `write_file`, and `patch` directly — they cover everything needed for meal logging (check JSON, append meal, recalculate totals, run pipeline). For Python logic between steps, use the write-temp-script workaround (see `references/railway-deployment.md` § "Cron-mode tool restrictions"). Pipeline invocation needs `PYTHONPATH` prefix if packages are installed via `--target`:
   ```bash
   cd ~/.hermes/skills/fitness-tracker
   PYTHONPATH=$PYTHONPATH (ensure site-packages is on path) python3 scripts/run_pipeline.py
   ```

5. Report: consumed / budget remaining / updated dashboard

**⚠️ Critical: Write THEN sync.** In Apr 2026, a bug occurred where breakfast was calculated mentally but never written to JSON, causing the dashboard to underreport by 317 kcal. Always verify the file was updated before running the pipeline.

**⚠️ Critical: Meals logged in chat MUST be persisted to JSON immediately.**
This is a RECURRING failure pattern (Apr 2026, Jun 2026). The agent
calculates macros, shows the table to the user, but never calls `write_file`
or patches `daily_nutrition.json`. The user thinks the meal is logged, but
the cron jobs check the file (not the chat) — so the next reminder asks
about a meal that was already discussed. The fix is simple: after showing
the macro table, ALWAYS write to `daily_nutrition.json` using `write_file`
or a Python script that reads-modifies-writes the JSON. Do not rely on
"auto-run the pipeline" alone — the pipeline reads the JSON, so if the
JSON wasn't updated, nothing flows.

**⚠️ Telegram formatting for fitness reports:** Avoid `**bold**` inside
pipe-delimited tables — Telegram renders it as literal asterisks. Use
plain text in table cells, bold only in standalone text/headers. Prefer
rich long-form markdown (collapsible `<details>` sections, footnotes,
headings, task lists) for deep analyses — but ensure
`platforms.telegram.extra.rich_messages: true` is set in config.yaml,
otherwise Telegram degrades tables to bullet lists and splits long
messages at 4096 chars.

**⚠️ Recurring failure (Jun 2026):** Meals logged in chat were displayed to the user with full macro tables but NEVER written to `daily_nutrition.json`. The cron reminders then fired and asked the user to log meals they'd already reported. This happened because the agent calculated macros, showed the table, and moved on without calling `write_file` or `patch` on the JSON. The fix is simple: **after every meal log, immediately write to the JSON file before doing anything else** — before running the pipeline, before showing the daily summary, before responding to the next message. If you showed the user a macro table but didn't write to the file, you failed the logging step. The display is not the log; the file is the log.

**⚠️ Lyfta cache wipe pitfall:** Running `lyfta_sync.py --days 1` (or any narrow range) **overwrites** `lyfta_cache.json` with only that day's workouts, wiping all historical data. This happened during the Jun 22 Railway deployment session — a `--days 1` check before workout analysis destroyed 30 workouts of cache. **Always use `--days 30` or wider** unless you explicitly want to discard history. If you need to check just today, read the cache file after a wide sync instead of re-syncing narrow.

**⚠️ JSON Patch Pitfall:** When appending a meal to an existing day's `meals` array, do NOT patch after `}]` or `},\n    ]` — this can accidentally create a **duplicate `"meals"` key** in the JSON object, which is invalid and causes data loss. Instead, patch a unique string inside the last meal entry (e.g., the `"note"` or `"carbs_g"` value of the final meal) and append the new meal object before the closing `]`. Always read the file after patching to verify the structure is correct. **Also: the `patch` tool can corrupt JSON by inserting escaped backslashes (`\"`) instead of plain quotes when the replacement text itself contains quotes.** When making large structural changes to `daily_nutrition.json`, use `write_file` to rewrite the entire file rather than patching — it's more reliable. Always validate with `python3 -c "import json; json.load(open('file.json'))"` after editing.

### Weight Logging (user reports weigh-in at gym)

Use the `log_checkin.py` CLI for a single weigh-in. This writes to the SQLite `weekly_checkins` table, not the old `weight_log.json`.

```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/log_checkin.py 2026-04-28 81.8 --pre-workout --notes "felt light"
```

For CSV uploads / historical weight exports, use `import_weight_csv.py` instead of searching unrelated app code. Accepted headers are flexible: `date`/`checkin_date` plus `weight_kg`/`weight`/`kg`; optional `waist_cm`, `weighin_time`, `pre_workout`, `clothing_notes`, `comment`/`notes`. If Telegram rejects `.csv`, upload `.xlsx` and use `import_weight_xlsx.py` (works for MovingLife exports).

```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/import_weight_csv.py /path/to/weights.csv --dry-run
python3 scripts/import_weight_csv.py /path/to/weights.csv --run-pipeline
python3 scripts/import_weight_xlsx.py /path/to/movinglife_export.xlsx --dry-run
python3 scripts/import_weight_xlsx.py /path/to/movinglife_export.xlsx --run-pipeline
```

Then run the full pipeline if `--run-pipeline` was not used:
```bash
python3 scripts/run_pipeline.py
```

For historical weight screenshots from older scale apps, use `vision_analyze` to extract only fully visible rows into structured data: date/time, weight kg, body fat %, muscle mass kg, plus visible monthly summaries. Do not import cut-off rows unless all metric values are visible. Upsert extracted rows into `weekly_checkins` with `comment='old app screenshot import; body_fat=X%; muscle_mass=Ykg'`, create a DB backup first, then run `scripts/run_pipeline.py` and regenerate `weight_trend_extended_YYYYMMDD.png`. If a screenshot is duplicate or contains already-imported rows, skip or upsert idempotently by `checkin_date`.

**Measurement protocol:** Same weekday, same approximate time, before workout, before large meal, similar clothing. If you can't control all of that, at least lock in: weekday + time + pre/post workout status. That metadata lives in `weekly_checkins` and matters for interpreting the number.

### Unified Pipeline (runs automatically after meal logs)

```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/run_pipeline.py
```

**Canonical path pitfall:** Some archived/curated installs may place the live skill under `~/.hermes/skills/.archive/.../fitness-tracker` while tracker scripts still hardcode `~/.hermes/skills/fitness-tracker/...` (`run_pipeline.py`, `etl_sync.py`, etc.). If meal logging fails with “can't open file ~/.hermes/skills/fitness-tracker/scripts/etl_sync.py” or the canonical directory is missing, restore the canonical path before rerunning:
```bash
ln -sfn ~/.hermes/skills/.archive/umbrella-2026-04-30/fitness-tracker ~/.hermes/skills/fitness-tracker
cd ~/.hermes/skills/fitness-tracker
python3 scripts/run_pipeline.py
```
Do not keep operating from the archive path with broken hardcoded paths; fix the symlink/canonical path, then verify JSON + SQLite.

This executes in order:
1. `etl_sync.py` — ingests `daily_nutrition.json` + `lyfta_cache.json` → `daily_facts` (SQLite)
2. `materialize_weekly.py` — aggregates `daily_facts` + `weekly_checkins` → `weekly_summary`
3. `dashboard_v1.py` — generates 5-question text report + PNG chart

**Chart output:** `~/.hermes/scripts/fitness_output/dashboard_YYYYMMDD.png`

### Lyfta Workout Sync (manual, as needed)

If workouts are missing from dashboard, or if the user corrects you that "today is workout day," immediately sync Lyfta before recalculating budget/status:
```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/lyfta_sync.py --days 3
python3 scripts/run_pipeline.py
```

**⚠️ Railway/PEP 668 environments:** If `python3` lacks `requests` (ModuleNotFoundError), use `uv run --with requests` instead. See `references/railway-deployment.md` for the full verification checklist including venv read-only workarounds.

For general backfill:
```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/lyfta_sync.py --days 30 --summary-only
python3 scripts/run_pipeline.py
```

### Gym / Workout Recommendation Advice

**ALWAYS check Lyfta data first when asked about going to the gym or what to train today.** Run the sync script and review recent workout history before giving advice. Never say "I don't know your schedule" — you have API access. Consider: consecutive training days, weekly session count vs 5x/week target, volume/intensity of recent sessions, rest day patterns, and same-day nutrition/carbs.

When the user asks **"what should I work on today at the gym"**, give a split recommendation based on recent muscle-group coverage, not a generic workout. Use recent Lyfta exercise names to infer coverage:
- Chest/push: bench press, fly, chest press, push-up
- Legs: squat, leg press, calf press, lunge
- Arms: curl, triceps extension/pushdown
- Core: cable crunch, twisting crunch/press
- Back/pull: row, pulldown, pull-up, lat-focused work
- Shoulders/rear delts: shoulder press, lateral raise, face pull, rear delt fly

**⏰ Analysis depth: use 4 weeks (30 days), not 5-7 days.** The user corrected a shallow 7-day analysis on 2026-06-22 — when asked "what should I work on today," they expected muscle frequency, progressive overload tracking, and volume trends across a full month, not just the last week. Default workflow: `lyfta_sync.py --days 30` (⚠️ follow with `--days 45 --limit 100` to restore the cache — see narrow-sync pitfall), then compute per-muscle weekly frequency, identify the highest-priority gap (days since last trained × frequency deficit), and pull progressive overload history for every exercise in the recommended muscle group.

Default heuristic: avoid repeating the most recent hard-trained muscle group; choose the largest undertrained area from the 4-week frequency table, then provide a concise exercise menu with sets/reps and progressive-overload targets (last session's top set → next weight bump). Include the ⚡BUMP signal (>8 reps on final working set → increase weight next session) and a secondary muscle group to pair. Also include a short nutrition note if same-day protein is low.

**Recovery override for long streaks:** If Lyfta shows ~6–7 consecutive training days, prioritize recovery even when a smaller muscle group is technically “due.” Recommend Zone 2 cardio / active recovery as the default, because it preserves gym momentum and calorie burn without deepening fatigue. If the user strongly wants the planned lift, offer a maintenance-only version: 2–3 exercises, 2–3 sets each, RPE 7–8, stop 1–2 reps before failure, no PR chasing, then optional 10–20 min Zone 2. Frame it as the smarter move after a streak, not as skipping.

**Low-carb / keto gym decision rule (May 2026):** If carbs are extremely low and the user asks weights vs Zone 2, do not reflexively switch to cardio. If they feel “less energized but not totally flat,” recommend **maintenance/technique weights** for the highest-leverage undertrained split, with reduced intensity (RPE 7–8, stop 1–2 reps before failure, no PR chasing) and optional 10–15 min Zone 2 finisher. Choose cardio-only if they feel dizzy, truly flat, unusually weak (>15–20% drop on first compound), poorly recovered, or joint-beat-up. Always mention water + salt/electrolytes because low-carb days can feel low-energy from sodium/water loss.

**Low-carb electrolyte practicals:** Coke Zero is fine for caffeine/fluid and keeps carbs low, but it does not solve sodium. Table salt works for sodium: suggest ~1/8 tsp in 300–500ml water pre-gym (~290mg sodium), with caution not to overdo it; 1/4 tsp is ~575mg sodium. If there are blood pressure/kidney concerns, advise caution. If no salt is available, proceed cautiously with water/Coke Zero and longer warm-up.

### Multi-Week Program Analysis (Sports Science)

When the user asks for a program-level analysis (not a single-session breakdown), take a sports scientist's perspective across 3–6 weeks of data. This is distinct from the per-session "Proactive Workout Analysis" above — here you're looking at macro patterns.

**Trigger phrases:** "analyze my workout data", "how's my training", "am I progressing", "sports scientist analyze"

**Workflow:**

1. **Sync 30 days of Lyfta** first: `lyfta_sync.py --days 30` then `run_pipeline.py`
2. **Pull nutrition adherence** from SQLite `daily_facts` (kcal_in, adherence_score, gym_flag) alongside workout data
3. **Check for nutrition-training decoupling** — the most important long-term signal. Query adherence per week vs workout count. The user's pattern: adherence and tracking drop first, gym attendance follows 2-3 weeks later. Flag it early.

**Analysis structure:**

| Section | Data source | What to flag |
|---|---|---|
| Training overview | Lyfta cache (14 sessions) | Volume trend, frequency, session density |
| Weight trajectory | `weekly_checkins` | Rate of change, stale data (>2 weeks without weigh-in) |
| Nutrition-training coupling | `daily_facts` + Lyfta | Adherence vs training volume per week. Decoupling = adherence drops while training holds |
| Muscle group frequency | Lyfta cache | Undertrained groups, split balance |
| Body composition trends | `weekly_checkins` comments (body_fat, skeletal_muscle, visceral_fat) | LBM preservation, BF% trend direction |
| Overreaching signals | Combined | Abrupt 5→0 session drops, consecutive 4+ day streaks, nutrition underfueling on high-volume weeks |

**Key interpretative rules:**

- **A Saturday→Monday gap with Sunday off is NORMAL**, not a crash. The training week starts Monday.
- **500 kcal logged on a training day doesn't mean they ate 500 kcal.** It means they stopped logging. Compare to bodyweight trend (if weight is stable at 85 kg, they're eating at maintenance regardless of what's logged).
- **Nutrition dropout precedes gym dropout by ~2-3 weeks.** This is the earliest warning signal — catch it before the gym follows.
- **Body composition data from smart-scale screenshots lives in `weekly_checkins.comment`**, not in structured columns. Parse it: body_fat%, skeletal_muscle%, visceral_fat, lean_body_mass_kg, BMR. Track LBM trend — if LBM drops >1 kg during a deficit, protein is insufficient.
- **Don't moralize gaps.** "You stopped logging" not "you failed." The pattern is known and predictable — describe it neutrally and give the next step.

**Recommended output format:** A structured report with a verdict section, training split table, nutrition coupling table, body comp summary, and 3-5 priority recommendations. End with the single highest-leverage action (usually: resume logging, weigh in, or add protein).

**Telegram long-form rendering:** Deep workout analyses often exceed 4,000 chars. Use collapsible `<details>` sections for full data tables (per-session volume, 6-week nutrition log) so the main message stays scannable. Use footnotes `[^1]` for methodology notes. Use task lists `- [ ]` for action items. Avoid `**bold**` inside pipe-delimited tables — Telegram renders it as literal asterisks. Keep tables to 4-5 columns max for mobile readability.

1. **Pull exercise details** via `lyfta_sync.py` (not summary-only) to get sets/reps/weights
2. **Gather context before judging the workout** — at minimum sync/review the last 7–30 days of Lyfta history, not only today's exercises. The user corrected an overly narrow evaluation on 2026-05-01: today's arm/triceps session was appropriate because shoulders/back were trained the day before. Do not criticize a missing muscle group until checking recent split coverage.
3. **Identify top sets** per exercise (highest weight or estimated 1RM for working sets) and compare to prior occurrences of the same exercise when available.
4. **Apply progressive overload rule:** >8 reps on last working set → increase weight next session. Flag exercises ready to progress, almost-ready holds, and baseline/new movements separately.
5. **Track muscle group coverage** for the week (e.g., "Chest Apr 28, back/shoulders Apr 30, arms today") and make the next-split recommendation from the actual coverage gaps.
6. **Suggest tomorrow's split** based on what's been trained recently

Evaluation pitfall: avoid standalone “balanced session” framing for accessory days. If a workout is intentionally narrow (arms, forearms, core, etc.), grade it by its role in the weekly program, not by whether it includes every upper-body muscle.

Example output format:
```
🎯 Progressive Overload Signals:
- DB Bench Press: 20 kg × 8 reps → bump to 22.5 kg next session
- Lever Seated Fly: 66 kg × 8 reps → bump working set to 77 kg

📊 Weekly Coverage: 3/5 sessions | Chest ✓ | Back ✓ | Shoulders ✓
```

### Dashboard v1: The 6 Questions

The dashboard answers only these questions (no noise, no false precision). The chart target line must show the **deficit calorie budget**, not maintenance: rest budget = `sedentary_base_kcal - deficit_midpoint_kcal`; gym budget = `sedentary_base_kcal + gym_calories_per_session - deficit_midpoint_kcal`; weekly chart target = blended rest/gym budget based on displayed weeks' workout counts. Keep this covered by `tests/test_dashboard_targets.py`.

**Visualization/legibility rules from May 2026 dashboard iteration:**
- Avoid split panels when the user wants to compare cause/effect. A useful single-frame version combines weekly intake bars, deficit-budget line, workout-count chips, and weight trend on a shared weekly x-axis.
- Do not overlay three full line axes. Keep calories as bars on the left axis, weight as a blue right-axis line, and workouts as contextual red chips/top-row labels rather than a third y-axis.
- Put kcal labels inside bars when workout or weight labels are near the bar tops; use high-contrast text and small white label boxes for external annotations.
- Move legends outside the plot area (usually below) if they crowd titles or labels. Always regenerate the PNG and inspect for label/title/legend overlaps before reporting success.
- If using vision inspection and it is rate-limited, state that visual verification was limited and ask the user to confirm the rendered chart.

The dashboard answers only these questions (no noise, no false precision):

1. Did I stay roughly on calorie target this week?
2. How many workouts did I complete?
3. Is my 4-week weight trend moving the right way?
4. Are weekends the main source of drift?
5. Is my assumed maintenance clearly off?
6. What did I focus on this week?

What unlocks when:
- 2+ weigh-ins → Weight trend panel activates
- 4–8 weeks → Weekend drift becomes reliable
- 8–12 weeks → Empirical TDEE gets "medium" confidence; weekly regression possible
- 3+ months → Changepoint detection, forecasting, macro A/B tests

### Deficit Calibration (weekly review)

Compare projected vs actual weight loss over 2-3 weeks:
- If actual loss > projected: NEAT is higher than estimated, can raise budget
- If actual loss < projected: tighten budget or review meal log accuracy
- Update `data/profile.json` if multiplier needs adjustment

## Data Model (SQLite)

Three tables in `data/fitness.db`:

### `daily_facts` — one row per calendar day
| Column | Meaning |
|--------|---------|
| `date` | PK, YYYY-MM-DD |
| `kcal_in`, `protein_g`, `carbs_g`, `fat_g` | Aggregated from meals |
| `gym_flag` | 1 if workout logged |
| `workout_kcal`, `workout_duration_min` | From Lyfta |
| `adherence_score` | `% of budget hit` (100% = on target) |
| `hunger_score`, `energy_score` | Reserved (1–5 scale) |
| `notes` | Freeform |

### `weekly_checkins` — one row per weigh-in
| Column | Meaning |
|--------|---------|
| `checkin_date` | PK |
| `weight_kg`, `waist_cm` | Measurements |
| `weighin_time`, `pre_workout`, `clothing_notes` | Standardization metadata |
| `comment` | Subjective note |

### `weekly_summary` — materialized view
| Column | Meaning |
|--------|---------|
| `week_start` | PK (Monday) |
| `avg_kcal`, `avg_protein_g`, `total_workouts` | Weekly aggregates; nutrition averages divide by logged nutrition days only, not Lyfta-only/no-food placeholder rows |
| `avg_adherence` | Mean adherence % |
| `weekly_weight_kg`, `weekly_weight_change_kg` | From checkins |
| `empirical_tdee_low/high` | `avg_kcal - (weight_change × 7700 / 7)` ± 200; negative weight change means TDEE above intake |
| `maintenance_confidence` | `too_sparse` / `low` / `medium` |

### `kv_store` — detector state (created by `detect_new_workout.py`)
| Column | Meaning |
|--------|---------|
| `key` | PK (e.g. `'last_reported_workout_id'`) |
| `value` | The last workout ID that was reported to the user |

The workout detector uses `kv_store` to avoid double-reporting. It stores `last_reported_workout_id` after each notification. When diagnosing "why wasn't my workout detected/reported," check this value — if it already matches today's workout ID, the detector considered it already reported. Clear it with `DELETE FROM kv_store WHERE key='last_reported_workout_id'` to force re-reporting.

### `exercise_sets` — progressive overload tracking (created by `detect_new_workout.py`)
| Column | Meaning |
|--------|---------|
| `id` | Auto-increment PK |
| `workout_date` | YYYY-MM-DD of the session |
| `exercise_name` | Normalized exercise name from cache |
| `weight_kg` | Set weight |
| `reps` | Set reps |
| `set_type` | Set type (warm-up/working, from Lyfta) |
| `created_at` | Row insertion timestamp |

Used by `progressive_overload_check()` to compare current top sets against historical bests and flag PRs / rep records / threshold bumps. These tables are created lazily by `ensure_tables()` in `detect_new_workout.py` — a fresh DB without prior workout detection runs will not have them until the first detection.

> Productivity tables (`projects`, `focus_blocks`, `daily_productivity`) live in `productivity-tracker/data/productivity.db`. The dashboard attaches this DB to show Q6 (productivity) alongside fitness data.

## Productivity Tracking

> **Moved to `productivity-tracker` skill.** Focus blocks, project management, and daily productivity aggregates now live in a separate SQLite database at `~/.hermes/skills/productivity-tracker/data/productivity.db`.
>
> The fitness dashboard (Q6) still displays productivity data by attaching the productivity database via SQLite `ATTACH DATABASE`. Cross-domain analytics (e.g., "gym days vs focus completion") are enabled by this join layer.
>
> See `productivity-tracker/SKILL.md` for full CLI reference, cron jobs, and backfilling workflows.

### Proactive Monitoring (ADHD-Friendly)

The user prefers **proactive agent behavior**: initiate nudges and check-ins rather than waiting for explicit commands. Implemented via cron scripts that follow a **"silent unless state change"** philosophy:

#### Workouts (Fully Automatic)
- **Auto Workout Detector** (`*/30 15-23 * * *` in WIB = `*/30 8-16 * * *` UTC): Polls Lyfta API every 30 min during gym hours. When a new workout is detected:
  1. Auto-reports exercise breakdown, volume, calories
  2. Flags progressive overload hits (new PRs, threshold reps)
  3. Auto-runs pipeline so dashboard reflects the workout
  4. Stores exercise history for future comparison

**The user does NOT need to mention gym or workouts.** The system detects them from Lyfta data and proactively reports. If the auto-detector missed something (rare), the user can say "sync my workout" to force a manual pull.

**Cron command template (3-step):**
```bash
# Step 1: Sync Lyfta cache for pipeline use — MUST use --days 30 (NOT --days 1).
# detect_new_workout.py uses the API directly and doesn't need the cache,
# but the pipeline (step 3) reads lyfta_cache.json for historical trend data.
# --days 1 would wipe the cache and break multi-week dashboard trends.
cd ~/.hermes/skills/fitness-tracker && python3 scripts/lyfta_sync.py --days 30

# Step 2: Detect and report new workouts (uses API directly, not cache)
cd ~/.hermes/skills/fitness-tracker && python3 scripts/detect_new_workout.py

# Step 3: If step 2 produced output (new workout), refresh the dashboard
cd ~/.hermes/skills/fitness-tracker && python3 scripts/run_pipeline.py
```

**⚠️ `--days 1` in the cron sync step will silently destroy workout history every 30 minutes.** The sync writes `lyfta_cache.json` with ONLY the fetched date range. `--days 1` → cache holds ≤2 days of workouts → pipeline loses multi-week trend context → dashboard shows wrong weights, frequency, and volume data. Always use `--days 30` in the cron sync step. If you ever run `--days 1` manually, immediately restore with `--days 45 --limit 100`.

**⚠️ "Forgot to tap finish workout" pattern (Jun 2026):** If the user says they trained but `lyfta_sync.py --days 1` returns 0 workouts, do NOT conclude "no session today." The user often forgets to tap "Finish Workout" in the Lyfta app, which means the session isn't uploaded to the API yet. Ask: "did you tap finish in the app?" and re-sync after they confirm. This is a recurring behavioral pattern, not a one-off.

**Key principle:** Low noise, high signal. ADHD brains tune out frequent reminders. These scripts only speak when they have actionable state to report.

## Calorie & Macro Lookup

Always use USDA FoodData Central or FatSecret as primary sources. Cite which source was used. When the user asks for "accurate numbers," do live web lookups — don't estimate from memory.

### Known Indonesian Foods (per 100g cooked, USDA/FatSecret)

| Food | Kcal | Protein | Fat | Carbs | Source |
|---|---|---|---|---|---|
| Nasi putih (white rice) | 130 | 2.7g | 0.3g | 28g | USDA |
| Nasi goreng (fried rice) | 168 | 6.3g | 6.2g | 21.1g | FatSecret |
| Nasi goreng spesial (Solaria, ~450g plate) | ~1,035 | ~39g | ~38g | ~130g | FatSecret (230kcal/100g × 450g portion) |
| Nasi uduk (coconut rice) | 168-220 | ~2.5g | ~5g | ~26g | FatSecret (varies w/ coconut milk) |
| Mee hoon goreng (fried vermicelli) | 170-190 | ~3g | ~7g | ~25g | Estimated (bihun goreng) |
| Telur (boiled egg) | 155 | 12.6g | 10.6g | 1.1g | USDA |
| Telur balado (egg + chili sauce) | ~180 | ~11g | ~13g | ~2g | Estimated (egg + oil-based sauce) |
| Ayam dada (chicken breast) | 157 | 31g | 3.6g | 0g | USDA |
| Orek tempeh (sweet soy tempeh) | ~200 | ~10g | ~8g | ~15g | Estimated (fried tempeh + kecap) |
| Tempeh (plain, cooked) | 192 | 19g | 11g | 9g | USDA |
| Udang goreng tepung (breaded fried shrimp) | 308 | 8g | 19g | 28g | USDA FDC #172037 |
| Udang goreng tepung (light batter, home-style) | 100-120 | ~12g | ~5g | ~6g | Estimated (minimal batter) |
| Pepes ayam (steamed chicken in banana leaf) | ~160 | ~22g | ~7g | ~1.5g | FatSecret (steamed, not fried — verify if recipe uses coconut milk) |
| Sate taichan (chicken, per piece ~30g) | ~50 | ~6g | ~3g | ~1g | SnapCalorie |
| Bratwurst (cooked, per piece ~66g) | ~196 | ~7g | ~16g | ~1g | FatSecret |
| Basmati rice (cooked) | ~130 | ~2.7g | ~0.3g | ~28g | USDA (similar to white rice) |
| Rendang daging sapi | ~195 | ~19.7g | ~11.1g | ~4.5g | FatSecret |
| Lemper ayam | ~190 | ~6g | ~5.6g | ~14.9g | FatSecret ID |
| Semur ayam (chicken stew w/ kecap manis) | 223 | 18.8g | 12.0g | 9.4g | FatSecret ID |
| Scrambled egg (made with oil) | ~149 | ~6.4g | ~12.4g | ~1.4g | NutritionValue (with oil) |
| Aren latte / palm sugar latte (small) | ~120-150 | ~2g | ~3g | ~25-28g | Estimated (palm sugar + milk/cream) |
| Minyak goreng (cooking oil) | 120 | 0g | 14g | 0g | per tbsp |
| Minyak zaitun (olive oil) | 119 | 0g | 14g | 0g | per tbsp |
| Minyak cabai (chilli oil) | 127 | 0g | 14g | 0g | per tbsp |
| Telur dadar (fried omelette) | 154 | 10.5g | 11.2g | 1.1g | SnapCalorie |
| Pastel goreng (fried pastry, per 100g) | 378 | ~7g | ~22g | ~38g | Fitia |
| Siomay / steamed dimsum | 138 | ~8g | ~4g | ~15g | FatSecret |
| Omelet mie (noodle omelette) | 138 | ~4.5g | ~2g | ~25g | FatSecret ID |
| Gurame tepung (battered fried carp) | 183 | ~17.5g | ~12g | 0g | FatSecret ID |
| Ikan dori goreng tepung | 228 | 17.1g | 12.0g | 12.0g | FatSecret ID |
| Kwetiau goreng (Solaria-style) | 210 | 7g | 9g | 26g | FatSecret ID |
| Gepuk/empal daging sapi | 212 | 22.3g | 10.3g | 7.5g | FatSecret ID search |
| Hilo Protein UHT Berryfit (190ml) | 120 | 12g | 2g | 13g | Label |
| Hilo Active 22g Berry Fitshake (1 sachet) | 130 | 22g | 2.5g | 5g | Label/MyNetDiary |
| HiLo Protein Chocofit (190ml, small pack) | 140 | 14g | 2.5g | 15g | Label (Apr 2026) |
| L-Men Isopower Creatine (1 sachet/7.8g) | 25 | 0g | 0g | 5g | FatSecret; creatine + Vit B supplement, NOT a protein shake |
| Collagena Susu Steril (189ml can) | 130 | 8g | 6g | 11g | FatSecret |
| Good Day Coffee Freeze (sachet 30g) | 130 | 1g | 3.5g | 25g | FatSecret |
| Good Day Freeze (can ~240ml) | ~120 | ~2g | ~3g | ~22g | Estimated from sachet |
| Flour tortilla (cooked) | 292 | 8g | 8g | 49g | USDA |
| Small supermarket roti canai/paratha (frozen circle, ~60g/piece) | ~160 per piece | ~4g | ~3-8g | ~26-29g | FatSecret/Kart's/Kawan refs; user describes as small circle supermarket roti canai |
| Minyak wijen / sesame oil | 40 per tsp; 120 per tbsp | 0g | 4.5g/tsp; 13.6g/tbsp | 0g | USDA/FatSecret |
| Tongseng (beef/goat stew, ready-to-eat) | 169 | 10.8g | 11.8g | 6.4g | FatSecret ID generic tongseng |
| Sate kambing | 216 | ~19.2g | ~14.3g | ~4.9g | FatSecret ID (100g kcal + per-tusuk macro ratio) |
| Siomay / pangsit kukus | 51 kcal/piece; 138 kcal/100g | 4.5g/piece | 0.9g/piece | 6.0g/piece | FatSecret generic siomay |
| Dim sum mentai | 202 | 12.2g | 8.2g | 19.2g | FatSecret ID generic dim sum mentai (mayo-based sauce adds fat vs plain steamed dim sum) |
| Pisang molen | 275 | 3.9g | 11.7g | 39.1g | FatSecret ID |
| Small train/cafe cold brew aren latte bottle | ~150-220 per bottle | ~2-6g | ~2-7g | ~25-40g | Estimate from FatSecret plain latte + gula aren; bottle size/sugar highly variable |
| KFC fried chicken wing (large piece, ~75g original recipe) | ~220 per piece | ~16g | ~15g | ~8g | Estimated; breaded deep-fried chicken wing |
| Fried sausage (standard supermarket, ~45g) | ~120 per piece | ~4g | ~10g | ~3g | Estimated; supermarket fried sausage |
| Cappuccino ice unsweetened (120ml) | ~45 | ~2g | ~1.5g | ~5g | Estimated; milk + espresso, no sugar |
| Perkedel kentang (fried potato patty, ~175 kcal/100g) | ~55 per 31g piece | ~2g per piece | ~3g per piece | ~5g per piece | Estimated; mashed potato + egg, deep-fried |
| KFC fried chicken (original recipe, per 100g) | ~230 | ~19g | ~15g | ~6g | Estimated; breaded deep-fried, consistent across pieces |
| Nasi uduk common toppings (per serving ~45g) | ~85 | ~3g | ~3.5g | ~9g | Estimated; bihun goreng + orek tempe + serundeng + sambal mix |

**Train snack logging note:** Small travel snacks add up fast. If user reports train snacks after the fact, log them as one “train snacks” meal and use weights where provided. For molen keju without a label, use ~300 kcal/100g as a pisang-keju/molen proxy; for molen pisang use FatSecret pisang molen 275 kcal/100g. For siomay/pangsit kukus, default to FatSecret siomay 51 kcal per dumpling plus separate boiled egg if included. For cold brew/aren latte bottle, assume ~170 kcal for a small unknown bottle and flag +50–120 kcal if larger/very sweet.

**Roti canai logging note:** If the user says supermarket circle roti canai and “not huge/kind of small,” default to ~160 kcal per piece unless label/weight is available. If oil is mentioned but amount is not, log ~1 tsp total for a light drizzle and explicitly state that 1 tbsp would add ~80 kcal more.

**Critical: NEVER assume cooking method — always verify or web-search first.** A dish's calorie count can vary 2-3x based on preparation (e.g., pepes ayam is steamed ~160 kcal/100g, not fried ~250+ kcal/100g). When the user describes a meal, ask about cooking method if unclear before estimating.

**Important:** For fried-battered foods, always ask the user about batter style. "Fast food" USDA data (heavy batter, deep fried) can be 2-3x the calories of home-style light coating. Flag this distinction.

**Restaurant portions are typically 2-3x home portions.** Solaria nasi goreng spesial is ~450g per plate (~1,035 kcal) vs ~200g home-cooked (~460 kcal). Always estimate generously for restaurant/food stall meals.

**Bone-in steak logging pitfall:** When user reports a steak weight (e.g., T-bone), ask/notice whether the weight includes bone. If bone-in/menu weight includes bone, estimate edible meat at ~75% by default (bone/refuse often ~20-25%) unless the user provides eaten meat weight. For grilled/cooked T-bone edible meat, use USDA/MyFoodData/FatSecret data; one useful basis from May 2026: grilled T-bone cooked lean-only trimmed to 1/8\" fat = 180 kcal, 23.7g protein, 8.8g fat, 0g carbs per 85g. Example: 300g bone-in ≈ 225g edible ≈ 476 kcal, P62.7/F23.3/C0; add extra eaten meat separately if user says “another 80g of the beef.”

**Label corrections override search snippets:** If the user pastes a nutrition label or app entry after an estimate, immediately correct the log and rerun the pipeline. Example from May 2026: bolen pisang keju was corrected from a search-snippet 163 kcal/piece to user-provided 117 kcal per 50g piece (P1.3/F3/C28).

### Macro Breakdown Reporting

When user asks for macros or wants to see the daily picture:
1. Show per-item macros (protein, fat, carbs in grams)
2. Show macro split by percentage (protein/fat/carbs of total kcal)
3. Show daily running total vs budget with % used
4. Flag protein targets — user tends to eat low-protein meals. Budget ~100-120g protein/day.

**Telegram rendering quirk:** `**bold**` inside pipe-delimited table cells renders as literal asterisks, not bold text. Avoid bold markers inside table cells — use plain text in tables. Apply bold only to standalone text, section headers, and lines outside table syntax.

### Ketosis / Low-Carb Status Reporting

When the user asks whether a ketosis attempt is “cancelled” after a meal, answer in threshold bands rather than binary moralizing:
- Strict keto: ~20g net/total carbs/day — if over, say “slightly over strict keto” not “ruined.”
- Moderate keto: ~25–30g/day — report exact remaining carbs.
- Liberal low-carb/keto-ish: ~50g/day — report exact remaining carbs.
- Consider prior-day context: if yesterday was very low-carb, mention the 2-day average can still be low even if today crosses strict keto.
- For same-day guidance, recommend protein + fat + low-carb veg and avoid rice/noodles/potato/tempe/beans/sugary latte if keeping the attempt alive.
- If gym may happen on a low-carb day, pair advice with water + sodium/electrolytes and maintenance/technique lifting guidance from the low-carb gym rule.

### Steps & NEAT Adjustment

The user sometimes mentions step counts from their phone/tracker. Use this formula for rough expenditure adjustment:
- **~0.04 kcal/step** for the user's weight (~85kg)
- 4,600 steps ≈ **184 kcal extra burned**
- 5,700 steps ≈ **228 kcal extra burned**
- This adjusts the rest-day expenditure upward: `1,997 + steps*0.04`; deficit budget becomes `sedentary_base + steps*0.04 - 650`.
- Travel days with substantial walking still count as **rest days** if there is no gym/structured workout, but label them as **active rest / travel day** and apply the step adjustment.

Log steps in `daily_nutrition.json` as `"steps_estimated": 4600`. Verify after running the pipeline:
```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/run_pipeline.py
python3 - <<'PY'
import sqlite3
conn=sqlite3.connect('data/fitness.db')
print(conn.execute("SELECT date, steps_estimated, adherence_score FROM daily_facts WHERE date='YYYY-MM-DD'").fetchone())
PY
```

**Apr 2026 bugfix:** `etl_sync.py` previously ignored `steps_estimated` and left `daily_facts.steps_estimated` NULL, so step-adjusted adherence was not applied even when JSON had the field. It is now patched to ingest `day_data.get("steps_estimated")` and include steps in `compute_adherence()`. If this regresses, patch `extract_nutrition_row()` and `compute_adherence()` before trusting the dashboard.

## Telegram Formatting

- **Avoid `**bold**` inside pipe-delimited table cells** — Telegram renders these as literal asterisks, not bold. Use bold only in standalone text, headings, and list items outside tables.
- **Long-form markdown requires `platforms.telegram.extra.rich_messages: true`** in config.yaml. Without this, Hermes uses legacy MarkdownV2 which: (1) chunks messages at 4,096 chars, (2) degrades tables to bullet lists, (3) strips collapsible sections, task lists, and math. With rich messages enabled, Telegram Bot API 10.1 sendRichMessage accepts up to 32,768 chars in a single message with full markdown rendering.
- **`hermes config set` can append duplicate config blocks** — when setting nested keys like `platforms.telegram.extra.rich_messages`, the command may append a NEW top-level `platforms:` block at the end of config.yaml instead of updating the existing key. The existing block (earlier in the file) takes precedence. Fix: verify with python3 raw read and patch the file directly.
- **Gateway restart required after config changes** — cannot restart from inside the gateway process. User must run `hermes gateway restart` from a terminal or separate shell.
- **Prefer rich long-form markdown for deep analyses** — collapsible sections for optional detail, footnotes for citations, proper heading hierarchy, task lists, and real Markdown tables for structured data. Tables degrade gracefully to bullet groups if rich rendering is unavailable.
- **Keep short answers short** — rich markdown is for deep dives (workout analysis, research reports). A meal log or quick status check should be a few lines, not a formatted report.

## User Behavioral Pattern (Critical)

The user has a yo-yo consistency pattern — strong starts (~2 months of 5x/week gym), then drops off entirely (gym + tracking), regaining 3-4kg per gap:
- Started 85.6kg → lost 6kg in 2 months → slacked months 3-5 → regained 3kg
- Restarted Dec → 79kg after 2 months → stopped Ramadan (Mar) → 82kg
- Now 83kg restarting (Apr 2026)

**Key insight: the user stops BOTH gym and calorie tracking during gaps.** Calorie tracking is more important than gym for weight maintenance. When the user stops going to the gym, they should NEVER stop logging food — that's what causes the regain.

Coaching approach:
- If user misses 3+ gym days, gently check in — don't let them quietly quit for months
**⚠️ Concurrency guard for cron jobs:** When the active provider has a concurrency limit (e.g. Umans = 4 concurrent agents), prepend this guard to every agent-based cron prompt to prevent HTTP 402 collisions:

```
IMPORTANT: Before doing anything else, run this command via terminal tool:
bash concurrency-guard.sh (from this toolkit) 3
If it exits with code 1 (at capacity), STOP immediately and output only
"⏳ Concurrency limit reached, skipping this run." Do not proceed.
If it exits 0, continue with your normal task.
```

The guard counts running kanban workers + active hermes processes. If at capacity, the cron skips silently and retries on the next tick. The script lives at `concurrency-guard.sh (from this toolkit)` and takes a single argument (max agents, default 3).

**⚠️ Cron provider selection:** Fitness cron jobs should normally avoid the umans provider when a working non-umans option exists, so reminders/workout detection do not consume the same concurrency slots as chat and kanban workers. Current preferred setting when available: `deepseek-v4-flash` via `opencode-go`. Before changing cron models, test the candidate with a one-shot Hermes call, then update only the four fitness jobs (`fitness-breakfast`, `fitness-lunch`, `fitness-dinner`, `fitness-workout`) and verify with `cronjob action=list`. Preserve parked schedules unless the user explicitly asks to reactivate. See `references/cron-provider-failover.md`.

**⚠️ Cron schedule staggering:** The 4 fitness cron jobs (3 meal reminders + 1 workout detector) are staggered so no two fire in the same minute — meal crons are 5 hours apart (`30 0`, `30 5`, `30 12` UTC), workout poller runs `*/30 8-16 * * *` on `:00`/`:30` offsets that don't collide with meal cron minutes. This is the only defense against cron-to-cron concurrency collisions, since cron jobs bypass the kanban queue and the guard script only protects kanban fan-out. Adding a 5th cron job requires manually verifying no schedule overlap. See `kanban-multi-agent-pipeline` skill → `references/concurrency-guard.md` § "Layer 5".

**⚠️ state.db growth from cron sessions:** The 4 cron jobs create ~50 sessions/day in `state.db`. Workout detector sessions store 50-62K char tool results. With dual FTS indexes (`messages_fts` + `messages_fts_trigram`), this causes ~15 MB/day growth (~450 MB/month). A weekly prune cron (`prune-cron-sessions.sh (from this toolkit)`, scheduled `0 3 * * 1` UTC) deletes cron sessions older than 7 days, rebuilds FTS indexes, and runs VACUUM. Verify the prune cron exists after any fresh deploy.

**⚠️ Telegram rich messages (Jun 2026):** By default, Hermes uses the legacy MarkdownV2 path for Telegram which caps messages at 4,096 chars and splits long content into multiple messages. Rich markdown constructs (tables, task lists, collapsible `<details>`, footnotes, math) are degraded to plain bullet lists. To enable full long-form markdown in a single message (up to 32,768 chars via Bot API 10.1 `sendRichMessage`), set `platforms.telegram.extra.rich_messages: true` in config.yaml. Note: `hermes config set` may append a duplicate `platforms:` block at the end instead of updating the existing key — verify with python3 raw read and patch the file directly if needed. Requires gateway restart to take effect.

**⚠️ Telegram formatting quirk:** `**bold**` inside pipe-delimited table cells renders as literal asterisks on some Telegram clients. Avoid bold markers inside table cells — use plain text in cells, bold only in standalone text and headers. This applies to both legacy MarkdownV2 and rich message paths. See `references/concurrency-guard.md` in the `kanban-multi-agent-pipeline` skill for full details.

**⚠� Telegram rich messages for long-form analyses:** Deep workout evaluations and multi-week reports exceed Telegram's legacy 4,096-char MarkdownV2 limit, causing messages to split into chunks and degrading tables/task-lists/collapsible-sections into plain text. Ensure `platforms.telegram.extra.rich_messages` is `true` in config.yaml — this enables Bot API 10.1 `sendRichMessage` (32,768 char limit, full markdown rendering). Requires gateway restart. Pitfall: `hermes config set` may append a duplicate `platforms:` block at the end of config.yaml instead of updating the existing key — verify with python3 raw read and patch directly if needed.

**⚠️ Cron timezone pitfall:** Hermes cron runs on server time (UTC on Railway and most cloud deploys). If the cron expression is written for the user's local time (e.g., `30 19 * * *` intending 19:30 WIB), it fires at 19:30 UTC = 02:30 WIB — the middle of the night. Always convert: WIB = UTC+7, so shift cron expressions **back by -7 hours**. The workout detector (15:00-23:00 WIB) becomes `*/30 8-16 * * *` UTC. Verify with `cronjob action=list` after setting schedules to confirm `next_run_at` matches expected local time.

Each reminder should check `data/daily_nutrition.json` BEFORE asking — if the meal is already logged for the current time window, send the running total instead of asking to log again. This avoids redundant nudge fatigue for the user. Time windows for each meal:
- Breakfast: 05:00-10:59
- Lunch: 11:00-14:59
- Dinner: 17:00-22:59

If not yet logged, ask what they ate, portion sizes, and cooking method. Keep casual and ADHD-friendly.

Weekly Sunday review (set up when user is ready):
- Weight trend
- Avg daily deficit
- Projected vs actual loss

## Data Files

- `data/profile.json` — user stats and metabolic parameters
- `data/daily_nutrition.json` — raw meal logs (Hermes writes here)
- `data/lyfta_cache.json` — synced workout data from Lyfta API
- `data/fitness.db` — ⭐ unified SQLite (daily_facts, weekly_checkins, weekly_summary)
- `data/weight_log.json` — legacy, empty/superseded by weekly_checkins

## Scripts Index

| Script | Purpose |
|--------|---------|
| `init_db.py` | One-time SQLite schema setup (fitness tables) |
| `etl_sync.py` | JSON → SQLite ingestion |
| `log_checkin.py` | CLI for weekly weigh-ins |
| `import_weight_csv.py` | Import historical weight CSVs into `weekly_checkins` |
| `import_weight_xlsx.py` | Import MovingLife/smart-scale XLSX exports into `weekly_checkins` |
| `materialize_weekly.py` | daily_facts + checkins → weekly_summary |
| `dashboard_v1.py` | 6-question report (fitness + productivity via ATTACH) + chart |
| `run_pipeline.py` | One-shot: sync → materialize → dashboard |
| `lyfta_sync.py` | Lyfta API sync |
| `detect_new_workout.py` | Auto-detect new Lyfta workouts |
| `fatigue_monitor.py` | Monitor workout fatigue signals |

> Productivity scripts (`focus_start.py`, `focus_end.py`, `focus_status.py`, `project_manage.py`, `productivity_digest.py`, cron monitors) moved to `productivity-tracker/scripts/`.

## Lyfta API Pitfalls

- **Exercise name typo**: The API returns `excercise_name` (double 'c'), NOT `exercise_name`. Always use `excercise_name` when reading exercise names.
- **`is_completed` is always `False`**: The Lyfta API returns `is_completed: False` for ALL sets, even though weight/reps data is valid. Never filter by `is_completed` — include sets based on whether weight/reps data exists.
- **`/api/v1/exercises/progress`** exists but returns empty data as of Apr 2026. Don't rely on it — parse workout data directly instead.
- **`/api/v1/exercises`** returns exercise *definitions* (name, type, muscles), not performed history. Useful for metadata only.
- **Pagination**: Max 100 workouts per call. Use `page` parameter to fetch all history. Summary endpoint supports up to 1000 per call but omits exercise details.
- **Cardio exercises** have `exercise_type: "duration"` (custom user exercises like FitBurn) or `"distance_duration"` (built-in). Duration data is inside the **sets array** (each set has a `duration` field like `"23:00"`), NOT at the exercise level. The sync script now captures these with `cardio_info` (distance/duration) and estimates calories using MET_CARDIO (8.0). Previously these were silently dropped by the weight/reps filter — patched Apr 2026.
- **Cache field names differ from API field names.** After `lyfta_sync.py` writes `lyfta_cache.json`, the cached JSON uses different keys than the raw API: `date` (not `started_at`), `weight` (not `weight_kg` on sets), `name` (not `excercise_name` on exercises), `calories_burned` (not `estimated_kcal`), and `duration` as a `"HH:MM:SS"` string (not `duration_minutes`). When reading the cache directly for analysis, use these fields — the API-typo fields only appear in raw API responses, not the cache.
- **Narrow-sync cache wipe (Jun 2026).** Calling `lyfta_sync.py --days 1` (e.g., to verify whether today is a workout day) **overwrites the entire `lyfta_cache.json`** with only the last 1 day of data. If no workout exists today, the cache becomes empty — destroying all exercise history needed for multi-week analysis. **Always follow a narrow sync with a wide restore:** `lyfta_sync.py --days 45 --limit 100` immediately after any `--days 1` or `--days 3` sync. The `gym_flag` bug documented below is a downstream consequence of this same pattern.
- **Deep workout analysis requires 30+ days of data.** When asked to "evaluate my workout deeply" or "analyze my training," always sync `--days 30` (preferably `--days 45 --limit 100`) and analyze: (1) muscle group frequency over 4-6 weeks, (2) progressive overload trend per exercise (top working set session-over-session), (3) BUMP signals (last set ≥8 reps → increase weight), (4) session volume (total sets + tonnage — flag sessions >20 sets as junk volume), (5) set intensity distribution (rep ranges: 1-5/6-8/9-12/13+), (6) gaps between workouts, (7) nutrition-training coupling from `daily_facts` (adherence drops before gym drops — the earliest yo-yo warning signal). Present as a single long-form markdown report with collapsible detail sections, not multiple messages.
- **Meals logged in chat must be persisted to `daily_nutrition.json` immediately.** Displaying a macro table without writing to the JSON file is a silent failure — the cron reminder checks the file, not the chat history, so it will re-ask about meals you already logged. Always write to file THEN display the table.


## Nutrition Source / Product-Variant Pitfalls

- Do not assume a brand/product name maps to one nutrition profile. Indonesian RTD products often have multiple variants with different macros under very similar names.
- When the user corrects a variant, update the logged item and daily totals immediately, then rerun the fitness pipeline so dashboards/materialized facts match the corrected JSON.
- If a source confirms only part of the label (e.g. “14g protein” but not full macros), state which values are confirmed vs inferred/known from tracker assumptions, and ask for a label photo only for exact precision.
- Example: L-Men Protein 2GO has at least an older 12g/70 kcal variant and a Chocolate 200ml RTD 14g whey protein variation; do not substitute one for the other.

## Maintenance / Code Changes

When modifying tracker scripts, use regression tests first and verify them before touching live data:

```bash
cd ~/.hermes/skills/fitness-tracker
python3 -m pytest -q
python3 -m py_compile scripts/*.py
```

If the local WSL Python does not have `pytest`, `pip`, or `matplotlib` installed, use `uv` without modifying the user's Windows/venv setup:
```bash
cd ~/.hermes/skills/fitness-tracker
uv run --with pytest --with matplotlib python -m pytest tests -q
uv run --with matplotlib python -m py_compile scripts/*.py
```

Existing regression coverage lives in `tests/`, including `tests/test_materialize_weekly.py` for weekly calorie/protein averaging and empirical TDEE sign, plus `tests/test_dashboard_targets.py` for dashboard deficit-budget chart targets. Do not blindly run `--help` against every script during reviews: some scripts execute work when invoked and can refresh `data/fitness.db` or dashboard PNGs. Prefer `py_compile`, direct file review, targeted pytest, and read-only SQLite connections for safe evaluation.

### Previewing Mature Dashboard State

When the user asks what the dashboard will look like once there is enough data, do not mutate the live DB. Instead, load `scripts/dashboard_v1.py` with `importlib`, monkeypatch `load_profile()` / `OUTPUT_DIR`, and pass synthetic `weeks`, `current_days`, and `period_rows` directly into `build_chart()`. Save the generated preview under `~/.hermes/scripts/fitness_output/` with an explicit preview filename (e.g. `dashboard_preview_enough_data.png`) and label text output as synthetic/mature-data preview. This reuses the real chart code while avoiding fake rows in `fitness.db`.

## Important Notes

- **Training week starts Monday. Sunday is a scheduled rest day.** A Saturday→Monday gap with Sunday off is normal, not a crash. Never interpret the Sunday-Monday transition as a pattern break or "abrupt stop" — check which day of the week it is before diagnosing burnout. The 5x/week target runs Mon-Sat with Sunday off.
- Weight fluctuations are normal — track trends, not individual readings
- Always use cooked weights for food unless user specifies raw
- The user communicates in Indonesian sometimes — accept informal food names
- If user says "beli nasi goreng" estimate ~450-550 kcal for a standard portion
- Restaurant/food stall portions are typically larger — estimate generously
- Gym weigh-ins are afternoon, not morning — ~0.5-1.5kg heavier than true morning weight
- User's progressive overload rule: >8 reps → increase weight next session
- After ANY meal log, auto-run the pipeline without asking — the user expects seamless data flow
- **Telegram rich_messages must be enabled** for long-form workout analyses and reports. Set `platforms.telegram.extra.rich_messages: true` in config.yaml — otherwise messages split at 4096 chars and markdown degrades (tables → bullet lists, collapsible sections stripped). If `hermes config set` appends a duplicate `platforms:` block instead of updating the existing key, patch the file directly with python3 raw read/write.
- **Meals logged in chat MUST be persisted to `daily_nutrition.json` immediately.** Do not just calculate and display macros — write the meal to the JSON file and recalculate totals. If the user reports a meal in chat but the cron reads the file (not the chat), the cron will send a redundant reminder. The gap between "displayed in chat" and "persisted in file" is the #1 cause of missed meal logs.

### Known Bugs & Pitfalls

**Productivity DB hard crash (Jun 2026):** `dashboard_v1.py` line 346 does `ATTACH DATABASE` to `~/.hermes/skills/productivity-tracker/data/productivity.db` with no try/except. If the file doesn't exist (fresh deploy, or skill split before productivity-tracking was set up), the pipeline crashes at step 3 even though ETL + materialize succeeded. **Fix:** create the stub DB as documented in the Setup section above. Do NOT skip this on fresh deploys.

**Historical CSV/XLSX weight imports (Apr 2026):** Telegram/Hermes attachment ingestion rejects raw `.csv` with "Unsupported document type '.csv'"; ask the user to upload `.xlsx`, `.zip`, rename CSV to `.txt`, or paste the CSV. For MovingLife/smart-scale `.xlsx` exports, use `scripts/import_weight_xlsx.py` and dry-run first. MovingLife may store some dates as Excel serial numbers that parse as impossible future dates because month/day are effectively swapped; `import_weight_xlsx.py` normalizes these (e.g. serial for 2026-08-04 becomes 2026-04-08) and has regression coverage. After importing historical check-ins, run `scripts/run_pipeline.py` and verify:
```sql
SELECT COUNT(*), MIN(checkin_date), MAX(checkin_date) FROM weekly_checkins;
SELECT week_start, weekly_weight_kg, weekly_weight_change_kg FROM weekly_summary WHERE weekly_weight_kg IS NOT NULL ORDER BY week_start DESC LIMIT 8;
```
`materialize_weekly.py` must include checkin-only weeks (`set(weeks.keys()) | set(checkins.keys())`), otherwise historical weigh-ins without nutrition rows are imported into `weekly_checkins` but missing from `weekly_summary`/dashboard trends.

**detect_new_workout.py timezone coupling (Jun 2026):** `detect_new_workout.py` builds its "today" filter with `datetime.now().strftime("%Y-%m-%d")` and matches it against `workout_perform_date` from the API (format `"YYYY-MM-DD HH:MM:SS"`). This works on Railway because the server is UTC and the API returns UTC timestamps — both sides agree on what "today" means. But this is an **implicit** assumption: if the container TZ is ever set to WIB (or any non-UTC zone), workouts after 17:00 UTC (midnight WIB) would be attributed to the next calendar day and the detector would miss them or report them late. Do not set `TZ` in the Railway environment without also adjusting `detect_new_workout.py` to use `datetime.utcnow()` explicitly (or convert the API timestamp to the same zone). The cron schedule `*/30 8-16 * * *` UTC is already documented and aligns with this assumption.

**Debugging "detect_new_workout.py produced no output":** When the auto-detector returns empty, the cause is almost always one of: (a) no workout was actually completed today, (b) the user forgot to tap "Finish Workout" in the Lyfta app (session not yet uploaded), or (c) a timezone mismatch between `datetime.now()` and the API's `workout_perform_date`. To diagnose, query the API directly and compare:
```python
import sys; sys.path.insert(0, 'scripts')
from lyfta_sync import get_api_key, fetch_all_workouts, normalize_workout
from datetime import datetime
api_key = get_api_key()
today = datetime.now().strftime('%Y-%m-%d')
raw = fetch_all_workouts(api_key, max_workouts=20)
today_w = [w for w in raw if w.get('workout_perform_date','').startswith(today)]
print(f'Server today={today}, workouts_today={len(today_w)}')
for w in raw[:3]:
    print(f"  {w.get('workout_perform_date')} | id={w.get('id')}")
```
If `workout_perform_date` values are present but don't start with `today`, check for a TZ mismatch. If they're absent entirely, the user likely didn't finish the workout in the app.

**Lyfta cache structure pitfall (Jun 2026):** The API returns workout dates in a `date` field (string `YYYY-MM-DD`), NOT `started_at`. Sets use `weight` and `reps` keys, NOT `weight_kg`. Exercise names are in `name`, with an `excercise_name` alias. The `is_completed` field is always `False`. Exercise `type` field distinguishes strength from cardio (`duration`/`distance_duration`). When parsing the cache for analysis, always verify the actual key names in the JSON before assuming field names. `etl_sync.py` can ingest workout data from `lyfta_cache.json` (setting `workout_kcal` and `workout_duration_min` in `daily_facts`) but fail to set `gym_flag=1`. A second failure mode happens when `lyfta_sync.py --days N` overwrites `lyfta_cache.json` with only recent workouts: rerunning ETL for older nutrition dates can set `gym_flag=0` while retaining old `workout_kcal`, so the dashboard undercounts workouts even though calories exist. If the user says workout logs are missing, check SQLite directly:
```sql
SELECT date, kcal_in, gym_flag, workout_kcal, workout_duration_min
FROM daily_facts
WHERE COALESCE(workout_kcal,0) > 0 AND gym_flag = 0
ORDER BY date;
```
Then restore the Lyfta cache with a wide sync and rerun the pipeline:
```bash
cd ~/.hermes/skills/fitness-tracker
python3 scripts/lyfta_sync.py --days 45 --limit 100
python3 scripts/run_pipeline.py
```
`etl_sync.py` has been patched so the upsert sets `gym_flag=1` whenever `COALESCE(excluded.workout_kcal, daily_facts.workout_kcal, 0) > 0`.

**Also verify `daily_nutrition.json`** — if a workout exists in JSON but not in `daily_facts`, the `gym_flag` won't be set. The user had this exact issue on 2026-04-21: Lyfta data was in the DB but `gym_flag` was 0, causing the dashboard to show 2 workouts instead of 3.
