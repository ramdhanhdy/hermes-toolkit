---
name: nutrition-tracker-operations
description: "Operate the user's nutrition tracker: log meals, use live nutrition lookups, persist daily JSON, run the pipeline, verify SQLite, and report concise macro/budget status."
version: 1.0.0
created_by: agent
---

# Nutrition Tracker Operations

Use this when the user sends meal, snack, drink, or ingredient details to log into the fitness/nutrition tracker.

## Workflow

1. Parse foods, weights, serving sizes, and cooking method.
   - If the user gives grams, use them directly.
   - If cooking method materially changes calories and is not inferable, ask; otherwise use the closest conservative proxy and caveat briefly.
2. Use live nutrition lookup for non-saved foods.
   - Prefer USDA/FatSecret for generic foods and Indonesian foods.
   - Package labels or user-provided labels override generic databases.
   - Keep source notes short; the final user reply should not become a source essay.
3. Write the meal to the active tracker immediately.
   - Primary active data path: `~/.hermes/skills/fitness-tracker/data/daily_nutrition.json`.
   - Primary scripts path: `~/.hermes/skills/fitness-tracker/scripts/`.
   - Ignore profile-copy tracker files under `~/.hermes/profiles/*/skills/fitness-tracker/` unless explicitly working in that profile.
4. Preserve meal order and totals.
   - If logging an earlier meal after later meals exist, insert chronologically.
   - De-duplicate exact reruns before writing.
   - Recalculate daily totals from the meal list instead of hand-adjusting old totals.
5. Validate and materialize.
   - Ensure JSON parses after writing.
   - Run `python scripts/run_pipeline.py` from the fitness-tracker skill directory.
   - Verify the date row in SQLite after the pipeline; a short Python `sqlite3` query is portable and avoids depending on shell-specific SQLite CLI availability.
6. Report the required concise summary.
   - Meal kcal + protein/fat/carbs.
   - Daily total kcal + protein/fat/carbs.
   - Remaining budget for the day type.
   - Protein gap/status vs 100–120g/day.

## Output style

Keep it short and numbers-first. Mention only material caveats, such as oil absorption, sauce/coating, package label uncertainty, or whether the workout-day budget is pending Lyfta sync.

**Telegram formatting:** Avoid `**bold**` inside pipe-delimited table cells — Telegram renders these as literal asterisks. Use bold only in standalone text and headers. For long-form analyses, use collapsible `<details>` sections, footnotes, heading hierarchy, and task lists. Ensure `platforms.telegram.extra.rich_messages: true` is set for full markdown rendering.

## Pitfalls

- Do not calculate only in-chat; persistence and pipeline verification are part of the task. **This is a RECURRING failure mode** — the agent calculates macros, displays the table, then forgets to call `write_file` to persist to `daily_nutrition.json`. The cron reminder jobs read the JSON file, not chat history, so they send duplicate reminders for meals already discussed. ALWAYS write to JSON before reporting.
- Do not omit macros. The user expects full daily macro breakdown whenever logging any meal.
- Do not ask for information already inferable from grams and common food names; use live lookup and clear proxies.
- Do not treat copied profile data files as the active tracker by default.
