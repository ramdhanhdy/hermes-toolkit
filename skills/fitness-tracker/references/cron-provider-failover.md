# Cron Provider Failover & Concurrency Guard

## Provider death diagnosis

When a cron job fails with HTTP 402 (Insufficient Balance), HTTP 429 (Rate Limit), or repeated model/provider errors:
1. Run `cronjob action=list` to see every job's `model`, `provider`, schedule, and `last_status`.
2. Test the candidate replacement with a one-shot Hermes call before touching cron config, e.g. `hermes -m deepseek-v4-flash --provider opencode-go -z 'Reply exactly: OK' --yolo`.
3. Update only the affected class of jobs unless the user asks for a global provider switch. For fitness work, normally update only `fitness-breakfast`, `fitness-lunch`, `fitness-dinner`, and `fitness-workout`.
4. Preserve schedules unless the user explicitly asks to reactivate or reschedule. A parked job (`0 3 1 1 *`) should stay parked when only changing model/provider.
5. Verify with a second `cronjob action=list` that the intended jobs changed and unrelated jobs did not.

## Current preferred fitness cron model

For fitness reminders and workout detection, prefer a non-umans provider when available so these background jobs do not consume the umans concurrency slots used by chat/kanban workers.

```json
{"model": "deepseek-v4-flash", "provider": "opencode-go"}
```

Use this for:
- `fitness-breakfast`
- `fitness-lunch`
- `fitness-dinner`
- `fitness-workout`

Before applying it, verify live model availability. OpenCode Go may move between rate-limited and available states; do not rely on yesterday's status.

Example update pattern:

```python
for jid in ["fitness-breakfast", "fitness-lunch", "fitness-dinner", "fitness-workout"]:
    cronjob action=update, job_id=jid,
            model={"model": "deepseek-v4-flash", "provider": "opencode-go"}
```

Common failure modes (Jun 2026):
- DeepSeek direct provider: HTTP 402 "Insufficient Balance" — out of credits on this deployment.
- OpenCode Go: HTTP 429 "Weekly usage limit reached" — can clear later; re-test before writing it off.
- OpenCode Go: HTTP 401 "Model not supported" — wrong model slug.
- Umans: HTTP 402 may be concurrency rejection, not funds.
- Umans temporary account pause — caused by untracked subprocess fan-out exceeding a 4-concurrent plan.

## zai as emergency failover provider

Use zai only as an emergency fallback if opencode-go and openai-codex are unavailable or if the user explicitly requests it. Zai has been rate-limited on this deployment, so do not make it the default for routine fitness crons.

```
Model: glm-5.2
Provider: zai
Base URL: https://api.z.ai/api/coding/paas/v4
```

## Umans concurrency limit

The Umans API plan has:
- Unlimited tokens
- 4 concurrent agent limit (hard limit)

When 4+ agents try to run simultaneously, the API returns HTTP 402 which looks
like "insufficient balance" but is actually a concurrency rejection.

## Concurrency guard script

Location: `concurrency-guard.sh (from this toolkit)`

Usage:
```bash
bash concurrency-guard.sh (from this toolkit) 3
# exit 0 = OK to proceed
# exit 1 = at capacity, skip
```

The script counts:
- Running kanban workers (`hermes kanban ls | grep '●'`)
- Active hermes agent processes (`pgrep -f "hermes.*-p.*<profile>"`)

Total is compared against the argument (default 3). Leaves 1 slot for the
main chat session on a 4-concurrent-limit plan.

## Adding the guard to cron prompts

Every agent-based cron job should have this prepended to its prompt:

```
IMPORTANT: Before doing anything else, run this command via terminal tool:
bash concurrency-guard.sh (from this toolkit) 3
If it exits with code 1 (at capacity), STOP immediately and output only
"⏳ Concurrency limit reached, skipping this run." Do not proceed.
If it exits 0, continue with your normal task.
```

This costs 1 terminal tool call per cron run — negligible overhead.

## Updating all crons after provider death

```python
# Procedure (run in chat):
# 1. List all jobs: cronjob action=list
# 2. For each job with a dead provider:
#    cronjob action=update, job_id=<id>, model={"model": "umans-glm-5.2", "provider": "custom"}
# 3. Also update the prompt to include the concurrency guard
# 4. Verify with cronjob action=list that all jobs show the new model
```

## Recognizing and fixing parked cron schedules

Cron jobs may be "parked" by setting their schedule to a far-future date like `0 3 1 1 *` (Jan 1, 03:00 UTC — effectively never fires). This is done intentionally to stop jobs from firing while testing provider/model changes. When a user says "I haven't seen any cron jobs fire" or "I expected it to fire but nothing happened":

1. Run `cronjob action=list` and check `next_run_at` for each job.
2. If `next_run_at` is months or years in the future (e.g. `2027-01-01T03:00:00+00:00`), the job is parked.
3. The user may have forgotten the jobs were parked — they only remember switching the model. Ask "should I reactivate them?" rather than assuming the schedule is intentional.
4. To unpark: convert WIB times to UTC (WIB = UTC+7, so subtract 7 hours) and update the schedule. Default meal times: breakfast 08:00 WIB = `0 1 * * *` UTC, lunch 12:00 WIB = `0 5 * * *` UTC, dinner 18:00 WIB = `0 11 * * *` UTC, workout check 20:00 WIB = `0 13 * * *` UTC.
5. After unparking, fire a manual test with `cronjob action=run, job_id=<id>` to verify the provider/model works.

## Verifying cron model configs

After updating, verify all jobs with `cronjob action=list`:
- Fitness jobs should show the requested replacement model/provider, currently usually `deepseek-v4-flash` via `opencode-go` when available.
- Check `next_run_at` — if it's in 2027, the job is parked and won't fire. Unpark if the user expects it to run.
- Non-fitness jobs should remain unchanged unless the user asked for a global provider migration.
- `last_status` should transition from `error` to `ok` on the next actual run.
