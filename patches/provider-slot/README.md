# Provider-Slot Concurrency Limiter

A cross-process concurrency limiter for Hermes Agent provider calls. Uses POSIX file locks (`fcntl.flock`) to enforce a hard concurrency cap across independent Python subprocesses — no Redis, no database, no external dependencies.

## The Problem

Some LLM providers (e.g. `api.code.umans.ai`) offer unlimited tokens but cap concurrent requests (e.g. 4 simultaneous). Hermes runs multiple agents, subagents, auxiliary calls (compression, vision, title generation), and MoA reference models — all hitting the same provider. Without limiting, the system exceeds the cap and gets rate-limited.

## How It Works

Three layers:

### 1. sitecustomize.py (Bootstrap)
Python auto-imports `sitecustomize.py` on startup. This file installs an import hook that patches Hermes' chat and auxiliary modules the moment they're loaded — before any HTTP request can fire.

### 2. provider_slot_patch.py (Monkey-Patch)
Wraps three call sites:
- `interruptible_streaming_api_call` — main agent streaming calls
- `call_llm` — synchronous auxiliary calls (compression, title generation)
- `async_call_llm` — async auxiliary calls (vision, session search)

**Provider scoping:** Only calls matching `HERMES_PROVIDER_LIMITED_PROVIDERS` / `HERMES_PROVIDER_LIMITED_MODELS` / `HERMES_PROVIDER_LIMITED_BASE_URLS` are capped. Other providers pass through uncapped.

**Fail-open:** If a patch target is missing, the original function runs uncapped and a `PROVIDER_LIMITER_PATCH_MISSING` error is logged. The system never blocks on a patching failure.

### 3. provider_slot.py (Slot Mechanism)
Creates N lock files in a temp directory. Before each HTTP request, acquires one via `fcntl.flock(LOCK_EX | LOCK_NB)`. If all slots are held, polls until one frees. After the request completes, releases the lock.

Key properties:
- **Auto-release on crash** — kernel closes file descriptors on process death, releasing locks
- **Cross-process** — fcntl locks work across independent subprocesses (unlike threading.Lock)
- **Zero dependencies** — stdlib only (fcntl, os, time, uuid, logging)
- **Per-call granularity** — each slot wraps exactly ONE HTTP request, not a retry loop

## Installation

1. Copy the patch files to a directory:
```bash
mkdir -p ~/.hermes/patches
cp provider_slot.py provider_slot_patch.py sitecustomize.py ~/.hermes/patches/
```

2. Copy `sitecustomize.py` to Python's site-packages:
```bash
SITE=$(python3 -c "import site; print(site.getsitepackages()[0])")
cp sitecustomize.py "$SITE/"
```

3. Set environment variables:
```bash
export HERMES_PATCHES_DIR=~/.hermes/patches
export HERMES_PROVIDER_CONCURRENCY_LIMIT=3        # leave 1 slot for chat
export HERMES_PROVIDER_LIMITED_PROVIDERS="your-provider-here"
export HERMES_PROVIDER_LIMITED_MODELS="your-model-here"
```

4. Restart Hermes. Verify the limiter is active:
```bash
python3 provider_limiter_healthcheck.py
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HERMES_PATCHES_DIR` | `~/.hermes/patches` | Directory containing patch files |
| `HERMES_PROVIDER_CONCURRENCY_LIMIT` | `3` | Max concurrent calls to limited providers |
| `HERMES_PROVIDER_SLOT_POLL_SEC` | `0.25` | Polling interval when waiting for a slot |
| `HERMES_PROVIDER_SLOT_MAX_WAIT_SEC` | `300` | Timeout for slot acquisition |
| `HERMES_PROVIDER_SLOT_DIR` | `/tmp/hermes_provider_slots` | Directory for lock files |
| `HERMES_PROVIDER_LIMITED_PROVIDERS` | `custom:api.code.umans.ai,api.code.umans.ai` | Comma-separated provider strings to limit |
| `HERMES_PROVIDER_LIMITED_MODELS` | `umans-glm-5.2` | Comma-separated model names to limit |
| `HERMES_PROVIDER_LIMITED_BASE_URLS` | `api.code.umans.ai` | Comma-separated base URLs to limit |

## Design Decisions

**Why limit=3 not 4?** Setting limit to one less than the provider cap leaves a slot always free for interactive chat, even under full pipeline load.

**Why fcntl not Redis/semaphore?** See the [analysis document](../../../ideas/longcat-limiter-analysis.md) for a full comparison. Short version: fcntl is zero-dependency, works across processes, and auto-releases on crash. Redis adds infrastructure. threading.Semaphore doesn't work across processes. asyncio.Semaphore doesn't work across event loops.

**Why fail-open?** If the patch fails, the agent still works (just uncapped). Fail-closed would block ALL provider calls, making the system unusable. Temporary rate-limit risk > total system failure.

## Tested With

- Hermes Agent (June 2026 release)
- Python 3.13
- Linux (Railway container)

**Note:** This patch monkey-patches specific Hermes internal functions. If Hermes updates and function signatures change, the patch will fail-open (calls proceed uncapped) and log `PROVIDER_LIMITER_PATCH_MISSING`. Run `provider_limiter_healthcheck.py` after any Hermes update to verify.

## License

MIT
