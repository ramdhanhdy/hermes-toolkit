"""Bootstrap for provider-slot limiter patches.

Install: copy this file to your Python's site-packages directory.
  python -c "import site; print(site.getsitepackages()[0])"

Then set HERMES_PATCHES_DIR to point to the directory containing
provider_slot_patch.py and provider_slot.py.

The limiter activates automatically when Hermes imports its chat/auxiliary
modules. No manual intervention needed after installation.
"""
import sys
import os
import builtins
import logging

PATCHES_DIR = os.environ.get("HERMES_PATCHES_DIR", os.path.expanduser("~/.hermes/patches"))
sys.path.insert(0, PATCHES_DIR)

logger = logging.getLogger("provider_slot.sitecustomize")

_orig_import = builtins.__import__

_patched = {"streaming": False, "auxiliary": False}
_all_done = False


def _maybe_emit_status():
    global _all_done
    if not _all_done and _patched["streaming"] and _patched["auxiliary"]:
        _all_done = True
        try:
            from provider_slot_patch import emit_startup_status
            emit_startup_status()
        except Exception as e:
            logger.error("provider_slot: could not emit startup status: %s", e)


def _patched_import(name, *args, **kwargs):
    result = _orig_import(name, *args, **kwargs)

    if name == "agent.chat_completion_helpers" and not _patched["streaming"]:
        _patched["streaming"] = True
        try:
            from provider_slot_patch import patch_streaming
            patch_streaming()
        except Exception as e:
            logger.error(
                "PROVIDER_LIMITER_PATCH_MISSING target=interruptible_streaming_api_call "
                "reason=patch_exception: %s", e
            )
        _maybe_emit_status()

    if name == "agent.auxiliary_client" and not _patched["auxiliary"]:
        _patched["auxiliary"] = True
        try:
            from provider_slot_patch import patch_auxiliary
            patch_auxiliary()
        except Exception as e:
            logger.error(
                "PROVIDER_LIMITER_PATCH_MISSING target=auxiliary "
                "reason=patch_exception: %s", e
            )
        _maybe_emit_status()

    return result

builtins.__import__ = _patched_import
