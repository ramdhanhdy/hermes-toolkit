#!/usr/bin/env python3
"""Health check: verify provider_slot limiter is active in the live runtime.

Usage:
    python3 provider_limiter_healthcheck.py

Exit 0 if all three wrappers are active, exit 1 if any are missing.
"""
import sys
import os

# Ensure patches dir is on path (in case sitecustomize didn't run)
sys.path.insert(0, "${HERMES_PATCHES_DIR:-$HOME/hermes_patches}")

print("=== Provider Slot Limiter Health Check ===")
print()

# 1. Confirm sitecustomize loaded
try:
    import sitecustomize as sc
    print(f"✓ sitecustomize loaded: {sc.__file__}")
except ImportError:
    print("✗ sitecustomize NOT loaded")
    sys.exit(1)

# 2. Confirm provider_slot module loaded
try:
    from provider_slot import provider_slot, active_slot_count, slot_status
    print(f"✓ provider_slot module loaded")
except ImportError as e:
    print(f"✗ provider_slot module NOT loaded: {e}")
    sys.exit(1)

# 3. Confirm agent modules are importable
try:
    import agent.chat_completion_helpers as cch
    import agent.auxiliary_client as aux
    print(f"✓ agent modules imported")
except ImportError as e:
    print(f"✗ agent modules not importable: {e}")
    sys.exit(1)

# 4. Check all three wrappers
targets = [
    ("interruptible_streaming_api_call", cch.interruptible_streaming_api_call),
    ("call_llm", aux.call_llm),
    ("async_call_llm", aux.async_call_llm),
]

all_ok = True
for name, fn in targets:
    wrapped = getattr(fn, "provider_slot_wrapped", False)
    has_wrap = hasattr(fn, "__wrapped__")
    status = "✓" if (wrapped or has_wrap) else "✗"
    print(f"{status} {name}: provider_slot_wrapped={wrapped} __wrapped__={has_wrap}")
    if not (wrapped or has_wrap):
        all_ok = False

print()

# 5. Show current config
limit = os.environ.get("HERMES_PROVIDER_CONCURRENCY_LIMIT", "3")
max_wait = os.environ.get("HERMES_PROVIDER_SLOT_MAX_WAIT_SEC", "300")
print(f"Config: HERMES_PROVIDER_CONCURRENCY_LIMIT={limit}")
print(f"Config: HERMES_PROVIDER_SLOT_MAX_WAIT_SEC={max_wait}")
print(f"Active slots: {active_slot_count()}")
print(f"Slot status: {slot_status()}")
print()

if all_ok:
    print("=== ALL CHECKS PASSED ===")
    sys.exit(0)
else:
    print("=== CHECKS FAILED — limiter not fully active ===")
    sys.exit(1)
