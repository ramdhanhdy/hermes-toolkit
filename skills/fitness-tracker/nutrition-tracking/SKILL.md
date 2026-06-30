---
name: nutrition-tracking
description: Log meals into the user's fitness tracker with live nutrition lookup, Indonesian-food proxies, pipeline verification, and concise macro/budget reporting.
version: 1.0.0
created_by: agent
---

# Nutrition Tracking

Use this when the user sends food, drink, snack, dinner, or meal details to log for the fitness tracker.

## Required workflow

1. Resolve the target date first.
   - For relative phrases like “yesterday dinner,” map to the correct calendar date before writing.
   - If a prior run may have been interrupted, inspect/verify the target day before adding entries so duplicates are not created.
2. Parse every item with amount and cooking method.
   - Ask only when missing cooking method materially changes the estimate and cannot be inferred.
   - Respect explicit details like “no sauce,” “no peanut sauce,” “not deep-fried,” or “unsweetened.”
3. Use live nutrition lookup for unknown foods.
   - Prefer package labels, USDA/FatSecret, and Indonesian sources such as FatSecret Indonesia / nilaigizi.
   - Keep estimates consistent with prior logged proxies when the exact same food recurs.
   - For recurring Indonesian/cafe proxies captured from sessions, see `references/indonesian-and-cafe-proxies.md`.
4. Persist the meal in `data/daily_nutrition.json`, recalculate totals, validate JSON, run `scripts/run_pipeline.py`, and verify the `daily_facts` row when possible.
5. Report concisely every time:
   - Added meal kcal + protein/fat/carbs
   - Daily total kcal + protein/fat/carbs
   - Correct day budget and remaining calories
   - Protein status vs 100–120g/day

## Recurring Indonesian food proxies

Use these as fallbacks when no better label/recipe data is available:

- HiLo Active Berry Fitshake, 1 sachet: **130 kcal, P22g, F2.5g, C5g**.
- L-Men Platinum Noodles, 1 pack: **220 kcal, P24g, F5g, C19g**.
- Unsweetened cappuccino with whole milk: **~43 kcal/100ml, P~2.5g, F~2.2g, C~4.2g**. Skim/semi-skim can be lower.
- Nasi goreng generic FatSecret Indonesia: **168 kcal/100g, P6.3g, F6.23g, C21.06g**. Restaurant/food-stall versions can be much higher if oily or large.
- Steamed dimsum / siomay / pangsit kukus: **51 kcal/piece, P4.5g, F0.9g, C6g**; fried/large/sauce-heavy pieces are higher.
- Se'i sapi meat-only: **191 kcal/100g, P32g, F6g, C0g**. Do not apply to full rice bowls/sambal-luat meals.
- Orange americano, unsweetened: coffee negligible; if final volume is known but juice ratio is not, use **~45 kcal/100ml mostly carbs** as a conservative cafe proxy; add syrup separately.
- Telur dadar FatSecret Indonesia: **153 kcal/100g, P10.62g, F12.02g, C0.69g**; add extra oil separately if obvious.
- Beef patty USDA 100% patty proxy: **204 kcal/100g, P14.63g, F15.69g, C0g**; lean/fat-drained patties may be lower, filler/breaded patties may include carbs.
- Beef satay without peanut sauce: **~200 kcal/100g, P18g, F12g, C5g**.
- Chicken satay without peanut sauce: **~237 kcal/100g, P27.1g, F13.5g, C0g** from FatSecret-style chicken satay results. If sweet marinade is obvious, note carbs may be understated.
- Daging empal: **~212 kcal/100g, P22.3g, F10.3g, C7.5g** from FatSecret Indonesia search results. Empal varies with oil/sugar/bumbu; caveat briefly.
- Cooked basmati rice: use a consistent cooked-rice proxy around **121–130 kcal/100g, P~2.7–3.5g, F~0.3g, C~25–28g**. Avoid dry-rice values.
- Tempe goreng: FatSecret Indonesia-style entries vary around **200–242 kcal/100g** depending oil. Pick a midpoint for small portions and caveat oil absorption.
- Peyek/rempeyek: **486 kcal/100g, P6.3g, F26.4g, C57.1g**; oil absorption varies a lot.
- Tumis tahu, not deep-fried: firm tofu plus light stir-fry oil estimate; caveat oil absorption.

## Output style

Keep it short and grounded. The user wants the numbers, budget, and important caveats — not a long source essay.

**Telegram formatting:** Avoid `**bold**` inside pipe-delimited table cells — Telegram renders these as literal asterisks. Use bold only in standalone text and headers. For long-form analyses (workout evaluations, multi-week reports), use collapsible `<details>` sections, footnotes, heading hierarchy, and task lists. Ensure `platforms.telegram.extra.rich_messages: true` is set in config for full markdown rendering (32,768 char limit via Bot API 10.1 `sendRichMessage`).

## Pitfalls

- **CRITICAL: Meals logged in chat MUST be persisted to `data/daily_nutrition.json` immediately.** Displaying the macro table is not enough — cron reminder jobs read the JSON file, not chat history. If you log in chat but don't write to file, the cron sends duplicate reminders. This is a RECURRING failure mode (Apr 2026, Jun 2026). ALWAYS write to JSON before reporting.
- Do not skip persistence/pipeline verification; nutrition logging is not just calculating macros in chat.
- Do not omit daily macro totals. The user explicitly wants the full daily macro breakdown whenever a meal is logged.
- Do not assume rest day if workout evidence exists; sync/check Lyfta when the message implies training or when budget status depends on it.
- Do not mix proxies within the same day in a way that creates inconsistent rice/meat totals unless a better source overrides prior assumptions.
- When a food range is supplied (e.g. 120–150g), use a midpoint and state that in the logged item/note unless the user asks for low/high bounds.
