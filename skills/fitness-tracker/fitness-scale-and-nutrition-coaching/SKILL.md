---
name: fitness-scale-and-nutrition-coaching
description: Interpret noisy weigh-ins during calorie/protein decisions; coach without punishment logic while preserving deficit and protein targets.
version: 1.0.0
created_by: agent
---

# Fitness Scale & Nutrition Coaching

Use when the user reports a surprising weigh-in, worries about sudden weight changes, or considers changing food/protein intake because of scale anxiety.

## Core workflow

1. **Separate trend from single datapoint.** Ask or infer whether the reading is comparable: same scale, same time, after bathroom, before food/drink, similar hydration/clothing, pre/post workout.
2. **Compare like-with-like first.** If the user has a same-scale home trend, prioritize that series over cross-scale gym/home comparisons.
3. **Use surplus math to defuse fat-gain panic.** A sudden 0.8–1.4kg jump would require roughly 6k–11k kcal surplus to be fat. If intake was near target, treat the jump as water/food/sodium/carbs/gut-content noise unless it persists.
4. **Do not reinforce punishment logic.** If the user wants to skip protein because of a scary scale number, separate protein/recovery from scale anxiety.
5. **Give a concrete action rule.** Re-weigh under identical morning conditions. If it returns to the prior band, ignore the spike. If it persists for 3+ comparable weigh-ins, reassess trend and calories.

## Protein shake decision pattern

When an optional protein shake is being considered after a scale spike:

- Calculate the new total with the shake.
- Compare against both the deficit budget and estimated maintenance.
- If not hungry: skipping is fine.
- If hungry or recovery-focused: a small protein shake can be acceptable even if it slightly exceeds deficit target, especially if still below maintenance.
- Avoid framing protein as something to punish/remove solely because the scale jumped.

Example wording:

> If you’re not hungry, skip it tonight. But don’t skip protein because of scale panic. With the shake you’re only slightly over deficit target and still below maintenance; without it, protein is lower but acceptable for one rest day.

## Key pitfall from session

Do not automatically assume a gym smart-scale low reading is the noisy datapoint when a later home-scale reading is higher. If the user has been consistently weighing on the same home scale in a stable band (e.g. 79.2–79.8kg) and gets one sudden 80.6kg reading, the sudden high reading is more likely the noisy datapoint.

## Output style

Be concise, direct, and honest. The user appreciates uncomfortable truth, but not shame. Use grounded numbers and practical next-step rules.