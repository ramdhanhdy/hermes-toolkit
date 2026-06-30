---
name: nutrition-logging
description: "Meal and drink logging for the user's calorie tracker: parse portions, look up Indonesian/common foods, persist daily nutrition JSON, run the fitness pipeline, and report full macros plus remaining budget."
version: 1.0.0
created_by: agent
---

# Nutrition Logging

Use this when the user sends food, drink, snack, or meal details to log into the fitness tracker.

## Required workflow

1. Parse each item with weight/portion and cooking method.
   - If cooking method is unclear and materially changes calories, ask only when not inferable. If the user says no deep-fry/no peanut sauce/unsweetened, use that immediately.
   - If the user adds a forgotten meal later, insert it chronologically when rewriting the day, not merely append if that would confuse later review.
2. Use live lookup for nutrition values when the item is not already known.
   - Prefer USDA/FatSecret for generic foods and Indonesian foods; package labels or user-provided labels override searches.
3. Write the meal into `data/daily_nutrition.json` immediately and recalculate daily totals.
4. Validate JSON, run `scripts/run_pipeline.py`, and verify the updated row in SQLite when possible.
5. Report the full daily macro breakdown every time:
   - Meal kcal + protein/fat/carbs
   - Daily total kcal + protein/fat/carbs
   - Remaining budget for the correct day type
   - Protein gap vs 100–120g/day

## Workout-day handling

If the user mentions a post-workout drink, workout, gym, or anything implying same-day training, sync/check Lyfta before final budget status. A drink like “usual HiLo Active Berry Fitshake” after workout should be logged and the day should be treated as a gym day if Lyfta confirms it.

## Known food entries from recent logs

- HiLo Active Berry Fitshake, 1 sachet: **130 kcal, P22g, F2.5g, C5g**. Source: saved label/MyNetDiary entry.
- Peyek kacang / rempeyek: **486 kcal/100g, P6.3g, F26.4g, C57.1g**. Source: FatSecret ID / HitungKalori. Recipe and oil absorption vary a lot.
- Unsweetened cappuccino with whole milk: **~43 kcal/100ml, P~2.5g, F~2.2g, C~4.2g**. Source: Nutracheck whole-milk cappuccino no sugar proxy. Skim milk can be ~21 kcal/100ml; semi-skim ~27 kcal/100ml.
- Beef satay without peanut sauce: use **~200 kcal/100g, P18g, F12g, C5g** as a conservative recurring proxy unless a label/recipe is provided.
- Chicken satay with peanut sauce (sate ayam bumbu kacang): **~213 kcal/100g, P19g, F12g, C8g**. Source: NutriScan serving analysis (5 skewers/150g = 320 kcal, 28gF/18gF/12gC). Per 100g values derived. Caveat: meat thickness and peanut sauce amount vary heavily. Add 10-20% if sauce is generous or meat is very thick/thigh-heavy.
- Risol mayo isi telur ayam (deep-fried): **~248 kcal/100g, P10g, F14g, C21g**. Source: FatSecret risol mayo ayam (per potong Family Mart: 110 kcal, P3.73/F6.19/C9.58 per ~40g piece; 100g avg 248-275 kcal range). Caveat: oil absorption from deep-frying varies widely - could be ±20-30 kcal/100g. If homemade/less oil, use lower bound.
- Tumis tahu, not deep-fried: use firm tofu plus a light stir-fry oil estimate; explicitly caveat oil absorption.
- L-Men Isopower Creatine (1 sachet/7.8g): **25 kcal, P0g, F0g, C5g**. Source: FatSecret. This is a creatine + Vit B supplement, NOT a protein shake. Users may confuse it with L-Men Platinum/Advanced which do contain protein. Always verify which L-Men product was consumed.
- Dim sum mentai: **~202 kcal/100g, P12.2g, F8.2g, C19.2g**. Source: FatSecret ID generic dim sum mentai. Mayonnaise-based topping makes it higher fat than steamed dim sum (51 kcal/pc).
- Sate kambing with bumbu kecap: use sate kambing base **216 kcal/100g** (FatSecret ID). If served with kecap manis, add ~1-2g carbs per 10g sauce.
- Butterscotch latte (less-sweet, 120ml): **~84 kcal, P2.5g, F3g, C12g**. Source: tracker proxy from Calf To Go less-sweet (~70 kcal/100ml). Regular-sweet bottled variants (e.g. Himalayan Salt) run ~80.5 kcal/100ml → ~97 kcal/120ml. Always clarify sweetness level.
- Steamed dim sum (siomay/pangsit kukus): **51 kcal/piece, P4.5g, F0.9g, C6g**. Source: FatSecret generic siomay. 4 pieces ≈ 204 kcal.
- Telur balado: **140 kcal/70g (1 butir), P7g, F10g, C4g**. Source: NutriNusa. Per 100g: ~200 kcal. Oil in the sambal base drives fat content.
- Nasi uduk: **163 kcal/100g, P2.5g, F8.1g, C20.5g** (FatSecret ID generic, 1 mangkok ~260 kcal). Coconut milk is the fat source; calorically dense for rice. Half a standard bungkus (~100g) is a reasonable estimate when the user says "half bungkus" without weight.
- Bihun goreng: **152 kcal/100g, P5.91g, F5.68g, C18.26g**. Source: FatSecret generic bihun goreng. Oil absorption varies; street/vendor versions run higher.
- Semur tahu: **~133 kcal/100g, P8g, F6.7g, C10g**. Source: SnapCalorie + FatSecret ID recipe. Tofu in sweet soy sauce; carb content from kecap manis. Range 71-212 kcal/100g depending on recipe (hitungkalori low vs FatSecret recipe high). Use ~133 as midpoint for topping portions.
- Kerupuk (nasi uduk topping): **12 kcal/piece (kerupuk beras), P0.2g, F0.17g, C2.23g**. Source: FatSecret ID kerupuk beras. 3 pieces ≈ 36 kcal. Negligible macros but counts in totals.

## Output style

Keep it concise. The user wants grounded numbers, not long explanations. Mention only important caveats that could materially change the estimate, e.g. oil absorption, sauce/crumbed vs plain chicken, skim vs full-cream milk, or recipe-dependent fried snacks.

**Telegram formatting:** Avoid `**bold**` inside pipe-delimited table cells - Telegram renders these as literal asterisks. Use bold only in standalone text and headers. For long-form analyses (workout evaluations, multi-week reports), use collapsible `<details>` sections, footnotes, heading hierarchy, and task lists. Ensure `platforms.telegram.extra.rich_messages: true` is set in config for full markdown rendering (32,768 char limit via Bot API 10.1 `sendRichMessage`).

## "Should I eat X?" decision support

When the user asks whether they should eat a specific item (e.g., "should I eat the leftovers?", "if I drink only whey protein, would that be enough?"):

1. Calculate the item's kcal + protein/fat/carbs.
2. Add it to the current day total.
3. Compare against remaining budget and protein target.
4. Give a **direct yes/no answer first**, then the numbers that justify it.
5. If the answer is "yes but..." (e.g., fits kcal but misses protein), say so clearly and suggest the simplest fix (e.g., "+ whey scoop closes the protein gap").

Do NOT give a long analysis. The user wants a quick yes/no with the math. One table showing current → projected → budget remaining is enough.

## Pitfalls

- Do not just calculate mentally; persistence is part of the task.
- **CRITICAL: Meals logged in chat MUST be persisted to `data/daily_nutrition.json` immediately.** Displaying the macro table is not enough - the cron reminder jobs read the JSON file, not the chat history. If you log a meal in chat but don't write it to the file, the cron will send a duplicate reminder, and the user will wonder why they're being reminded for something they already logged. This happened on June 26 - breakfast was displayed in chat but not persisted, causing a duplicate reminder. **This is a RECURRING failure mode** - it happened before (Apr 2026 bug) and again in Jun 2026. The pattern: user tells you what they ate → you calculate macros → you display the table → you forget to call `write_file` or run the pipeline. ALWAYS write to JSON as step 3 of the workflow, before reporting.
- Do not skip macro totals. User explicitly wants full daily macro breakdown whenever logging a meal.
- Do not assume rest day after a post-workout item; sync/check workout data or treat as gym day if already confirmed.
- Do not turn every small lookup into a verbose source essay. Cite source/proxy briefly.
- **L-Men product confusion:** L-Men Isopower Creatine = zero protein (creatine supplement). L-Men Platinum/Advanced = protein products. Always verify which L-Men product was consumed before logging.
- **Supplement vs meal:** If the user says "drinking X at the gym," verify whether it's a protein shake or a non-protein supplement (creatine, BCAA, electrolyte). Don't assume "gym drink = protein."
- **Backfilling missed meals:** If the user mentions meals from previous days that weren't logged (e.g., "I thought I logged breakfast"), check the JSON file first, then backfill any missing meals using the same lookup and persistence workflow. Recalculate daily totals after backfilling.
