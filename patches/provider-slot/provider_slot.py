"""Cross-process provider-call limiter using fcntl file-slot locks.

Provides a semaphore that works across independent Python subprocesses
on a single host. Each outbound provider HTTP request acquires one of N
slot files before proceeding. If all slots are held, the call blocks
until a slot frees up.

Key properties:
- Auto-release on process death (kernel releases flock when fd closes)
- Zero external dependencies (stdlib only: fcntl, os, time, uuid, logging)
- Per-call instrumentation: acquire, wait, release, timeout
- Slots wrap individual HTTP requests, NOT retry loops
- Configurable via env vars:

  HERMES_PROVIDER_CONCURRENCY_LIMIT  (default: 3)
  HERMES_PROVIDER_SLOT_POLL_SEC      (default: 0.25)
  HERMES_PROVIDER_SLOT_MAX_WAIT_SEC  (default: 300)
  HERMES_PROVIDER_SLOT_DIR           (default: /tmp/hermes_provider_slots)
"""
from __future__ import annotations

import fcntl
import logging
import os
import time
import uuid
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration (read fresh each call so env changes take effect) ──────────

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default

def _slot_dir() -> str:
    return os.environ.get(
        "HERMES_PROVIDER_SLOT_DIR",
        "/tmp/hermes_provider_slots",
    )

def _limit() -> int:
    return _env_int("HERMES_PROVIDER_CONCURRENCY_LIMIT", 3)

def _poll_sec() -> float:
    return _env_float("HERMES_PROVIDER_SLOT_POLL_SEC", 0.25)

def _max_wait_sec() -> float:
    return _env_float("HERMES_PROVIDER_SLOT_MAX_WAIT_SEC", 300.0)

# Last logged wait notification per pid (avoid spamming every 0.25s).
_last_wait_log: dict[int, float] = {}


class ProviderSlotTimeout(TimeoutError):
    """Raised when a provider slot cannot be acquired within the wait limit.

    Classified as infrastructure, not model failure — safe to retry.
    """
    pass


@contextmanager
def provider_slot(
    call_type: str = "unknown",
    provider: str = "unknown",
    model: str = "unknown",
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
):
    """Acquire a provider concurrency slot before an outbound HTTP request.

    Usage::

        with provider_slot(call_type="main", provider="umans", model="glm-5.2"):
            response = client.chat.completions.create(...)

    Blocks if all slots are held. Times out after
    ``HERMES_PROVIDER_SLOT_MAX_WAIT_SEC`` (default 300s) with a
    ``ProviderSlotTimeout``.

    Each call to this context manager wraps exactly ONE HTTP request.
    Retries must re-acquire — do NOT wrap this around a retry loop.
    """
    slot_dir = _slot_dir()
    limit = _limit()
    poll = _poll_sec()
    max_wait = _max_wait_sec()

    os.makedirs(slot_dir, exist_ok=True)

    holder = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
    call_id = uuid.uuid4().hex[:12]
    start = time.monotonic()
    acquired: Optional[tuple[int, object]] = None

    # Log the attempt
    logger.info(
        "provider_call_attempt call_id=%s holder=%s call_type=%s provider=%s "
        "model=%s session=%s task=%s pid=%s limit=%d",
        call_id, holder, call_type, provider, model,
        session_id or "-", task_id or "-", os.getpid(), limit,
    )

    # ── Acquire phase ─────────────────────────────────────────────────────
    try:
        while acquired is None:
            for i in range(limit):
                path = os.path.join(slot_dir, f"slot_{i}.lock")
                fh = open(path, "a+")
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fh.seek(0)
                    fh.truncate()
                    fh.write(
                        f"{holder} call_id={call_id} call_type={call_type} "
                        f"provider={provider} acquired_at={time.time()}\n"
                    )
                    fh.flush()
                    acquired = (i, fh)
                    logger.info(
                        "provider_slot_acquired call_id=%s slot=%d holder=%s "
                        "call_type=%s provider=%s waited=%.2fs limit=%d",
                        call_id, i, holder, call_type, provider,
                        time.monotonic() - start, limit,
                    )
                    break
                except BlockingIOError:
                    fh.close()

            if acquired is None:
                waited = time.monotonic() - start
                if waited > max_wait:
                    logger.error(
                        "provider_slot_wait_timeout call_id=%s holder=%s "
                        "call_type=%s provider=%s waited=%.1fs max_wait=%.1fs",
                        call_id, holder, call_type, provider,
                        waited, max_wait,
                    )
                    raise ProviderSlotTimeout(
                        f"Timed out waiting for provider concurrency slot "
                        f"after {waited:.1f}s (limit={limit})"
                    )

                # Throttled wait logging: once every 10s per pid
                pid = os.getpid()
                last_log = _last_wait_log.get(pid, 0.0)
                if time.monotonic() - last_log >= 10.0:
                    logger.info(
                        "provider_slot_wait call_id=%s holder=%s call_type=%s "
                        "provider=%s pid=%s waited=%.1fs limit=%d",
                        call_id, holder, call_type, provider,
                        pid, waited, limit,
                    )
                    _last_wait_log[pid] = time.monotonic()

                time.sleep(poll)

        # ── Execute the wrapped call ──────────────────────────────────────
        yield

    finally:
        # ── Release phase ────────────────────────────────────────────────
        if acquired is not None:
            slot_id, fh = acquired
            duration = time.monotonic() - start
            try:
                fh.seek(0)
                fh.truncate()
                fh.flush()
                fcntl.flock(fh, fcntl.LOCK_UN)
                logger.info(
                    "provider_slot_released call_id=%s slot=%d holder=%s "
                    "call_type=%s provider=%s duration=%.2fs",
                    call_id, slot_id, holder, call_type, provider, duration,
                )
            except Exception as e:
                logger.warning(
                    "provider_slot_release_error call_id=%s slot=%d error=%s",
                    call_id, slot_id, e,
                )
            finally:
                fh.close()


def active_slot_count() -> int:
    """Return the number of currently-held slots (for diagnostics)."""
    slot_dir = _slot_dir()
    limit = _limit()
    os.makedirs(slot_dir, exist_ok=True)
    count = 0
    for i in range(limit):
        path = os.path.join(slot_dir, f"slot_{i}.lock")
        fh = open(path, "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh, fcntl.LOCK_UN)
        except BlockingIOError:
            count += 1
        finally:
            fh.close()
    return count


def slot_status() -> list[dict]:
    """Return detailed status of each slot for diagnostics."""
    slot_dir = _slot_dir()
    limit = _limit()
    os.makedirs(slot_dir, exist_ok=True)
    slots = []
    for i in range(limit):
        path = os.path.join(slot_dir, f"slot_{i}.lock")
        fh = open(path, "a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh, fcntl.LOCK_UN)
            slots.append({"slot": i, "held": False, "holder": None})
        except BlockingIOError:
            fh.seek(0)
            content = fh.read().strip()
            slots.append({"slot": i, "held": True, "holder": content})
        finally:
            fh.close()
    return slots
