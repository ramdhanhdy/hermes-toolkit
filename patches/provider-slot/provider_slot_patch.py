"""Monkey-patch provider call sites to wrap them with the fcntl slot limiter.

Imported via sitecustomize.py. Patches:
1. interruptible_streaming_api_call — main agent streaming calls
2. call_llm — auxiliary calls (compression, vision, title generation)
3. async_call_llm — async auxiliary calls

Scope: provider-scoped. Only calls to the umans provider are capped.
Other providers (openai-codex, etc.) pass through uncapped.

Failure mode: fail-OPEN with warning.
If a patch target is missing, the original function runs uncapped and a
PROVIDER_LIMITER_PATCH_MISSING log line is emitted. Operational safety
depends on post-restart verification.
"""
import logging
import functools
import os

logger = logging.getLogger(__name__)

_streaming_done = False
_call_llm_done = False
_async_call_llm_done = False

# Track which patches succeeded for startup verification
_patch_status = {
    "streaming": False,
    "call_llm": False,
    "async_call_llm": False,
}


# ---------------------------------------------------------------------------
# Provider scoping — only limit calls to specific providers/models/base URLs
# ---------------------------------------------------------------------------

def _csv_env(name, default):
    raw = os.environ.get(name, default)
    return [x.strip().lower() for x in raw.split(",") if x.strip()]

LIMITED_PROVIDERS = _csv_env(
    "HERMES_PROVIDER_LIMITED_PROVIDERS",
    "custom:api.code.umans.ai,api.code.umans.ai",
)
LIMITED_MODELS = _csv_env(
    "HERMES_PROVIDER_LIMITED_MODELS",
    "umans-glm-5.2",
)
LIMITED_BASE_URLS = _csv_env(
    "HERMES_PROVIDER_LIMITED_BASE_URLS",
    "api.code.umans.ai",
)


def _should_limit(provider=None, model=None, api_kwargs=None, kwargs=None):
    """Return True if this call should be capped by the slot limiter."""
    provider_s = str(provider or "").lower()
    model_s = str(model or "").lower()

    # Quick exit for empty provider
    if not provider_s or provider_s == "unknown":
        # Fall back to model matching only
        if any(m and m == model_s for m in LIMITED_MODELS):
            return True
        return False

    # Check provider string
    if any(p and p in provider_s for p in LIMITED_PROVIDERS):
        return True

    # Check model string
    if any(m and m == model_s for m in LIMITED_MODELS):
        return True

    # Check base URL in api_kwargs or kwargs (stringified)
    haystack = " ".join([
        str(api_kwargs or "").lower(),
        str(kwargs or "").lower(),
    ])
    if any(u and u in haystack for u in LIMITED_BASE_URLS):
        return True

    return False


def patch_streaming():
    """Wrap interruptible_streaming_api_call with the provider_slot limiter."""
    global _streaming_done
    if _streaming_done:
        return
    try:
        from provider_slot import provider_slot
        import agent.chat_completion_helpers as _cch

        target_name = "interruptible_streaming_api_call"
        if not hasattr(_cch, target_name):
            logger.error(
                "PROVIDER_LIMITER_PATCH_MISSING target=%s reason=attribute_not_found "
                "in module agent.chat_completion_helpers",
                target_name,
            )
            _streaming_done = True
            return

        _orig = _cch.interruptible_streaming_api_call

        @functools.wraps(_orig)
        def _wrapped(agent, api_kwargs, *, on_first_delta=None):
            provider = getattr(agent, "provider", "unknown")
            model = getattr(agent, "model", "unknown")
            session_id = getattr(agent, "session_id", None)

            if _should_limit(provider=provider, model=model, api_kwargs=api_kwargs):
                with provider_slot(
                    call_type="main",
                    provider=str(provider),
                    model=str(model),
                    session_id=str(session_id) if session_id else None,
                ):
                    return _orig(agent, api_kwargs, on_first_delta=on_first_delta)
            else:
                logger.debug(
                    "provider_limiter_skip call_type=main provider=%s model=%s",
                    provider, model,
                )
                return _orig(agent, api_kwargs, on_first_delta=on_first_delta)

        # Mark for health-check verification
        _wrapped.provider_slot_wrapped = True
        _cch.interruptible_streaming_api_call = _wrapped
        _streaming_done = True
        _patch_status["streaming"] = True
        logger.info("provider_slot: patched interruptible_streaming_api_call (scoped)")
    except ImportError as e:
        logger.error(
            "PROVIDER_LIMITER_PATCH_MISSING target=interruptible_streaming_api_call "
            "reason=import_error: %s", e,
        )
        _streaming_done = True
    except Exception as e:
        logger.error(
            "PROVIDER_LIMITER_PATCH_MISSING target=interruptible_streaming_api_call "
            "reason=unexpected_error: %s", e,
        )
        _streaming_done = True


def patch_auxiliary():
    """Wrap call_llm and async_call_llm with the provider_slot limiter."""
    global _call_llm_done, _async_call_llm_done
    try:
        from provider_slot import provider_slot
        import agent.auxiliary_client as _aux

        if not _call_llm_done:
            target_name = "call_llm"
            if not hasattr(_aux, target_name):
                logger.error(
                    "PROVIDER_LIMITER_PATCH_MISSING target=%s reason=attribute_not_found",
                    target_name,
                )
                _call_llm_done = True
            else:
                _orig = _aux.call_llm

                @functools.wraps(_orig)
                def _wrapped(*args, **kwargs):
                    provider = kwargs.get("provider", "unknown")
                    model = kwargs.get("model", "unknown")

                    if _should_limit(provider=provider, model=model, kwargs=kwargs):
                        with provider_slot(
                            call_type="auxiliary",
                            provider=str(provider),
                            model=str(model),
                        ):
                            return _orig(*args, **kwargs)
                    else:
                        logger.debug(
                            "provider_limiter_skip call_type=auxiliary provider=%s model=%s",
                            provider, model,
                        )
                        return _orig(*args, **kwargs)

                _wrapped.provider_slot_wrapped = True
                _aux.call_llm = _wrapped
                _call_llm_done = True
                _patch_status["call_llm"] = True
                logger.info("provider_slot: patched call_llm (scoped)")

        if not _async_call_llm_done:
            target_name = "async_call_llm"
            if not hasattr(_aux, target_name):
                logger.error(
                    "PROVIDER_LIMITER_PATCH_MISSING target=%s reason=attribute_not_found",
                    target_name,
                )
                _async_call_llm_done = True
            else:
                _orig_async = _aux.async_call_llm

                @functools.wraps(_orig_async)
                async def _wrapped_async(*args, **kwargs):
                    provider = kwargs.get("provider", "unknown")
                    model = kwargs.get("model", "unknown")

                    if _should_limit(provider=provider, model=model, kwargs=kwargs):
                        with provider_slot(
                            call_type="auxiliary_async",
                            provider=str(provider),
                            model=str(model),
                        ):
                            return await _orig_async(*args, **kwargs)
                    else:
                        logger.debug(
                            "provider_limiter_skip call_type=auxiliary_async provider=%s model=%s",
                            provider, model,
                        )
                        return await _orig_async(*args, **kwargs)

                _wrapped_async.provider_slot_wrapped = True
                _aux.async_call_llm = _wrapped_async
                _async_call_llm_done = True
                _patch_status["async_call_llm"] = True
                logger.info("provider_slot: patched async_call_llm (scoped)")
    except ImportError as e:
        logger.error(
            "PROVIDER_LIMITER_PATCH_MISSING target=auxiliary "
            "reason=import_error: %s", e,
        )
        _call_llm_done = True
        _async_call_llm_done = True
    except Exception as e:
        logger.error(
            "PROVIDER_LIMITER_PATCH_MISSING target=auxiliary "
            "reason=unexpected_error: %s", e,
        )
        _call_llm_done = True
        _async_call_llm_done = True


def emit_startup_status():
    """Emit a single PROVIDER_LIMITER_ACTIVE or PATCH_MISSING log line.

    Called after all patches have been attempted.
    """
    limit = os.environ.get("HERMES_PROVIDER_CONCURRENCY_LIMIT", "3")
    patched = [k for k, v in _patch_status.items() if v]
    missing = [k for k, v in _patch_status.items() if not v]

    if not missing:
        logger.info(
            "PROVIDER_LIMITER_ACTIVE limit=%s scope=provider "
            "limited_providers=%s limited_models=%s limited_base_urls=%s "
            "patched=%s",
            limit,
            ",".join(LIMITED_PROVIDERS),
            ",".join(LIMITED_MODELS),
            ",".join(LIMITED_BASE_URLS),
            ",".join(patched),
        )
    else:
        logger.error(
            "PROVIDER_LIMITER_PATCH_MISSING limit=%s patched=[%s] missing=[%s] "
            "— provider calls will be UNCAPPED until patched",
            limit, ",".join(patched), ",".join(missing),
        )
