"""Unit tests for OpenRouterBackend fallback behavior.

We stub the OpenAI client on a constructed backend so no network calls fly.
"""

import types

import httpx
import pytest
from openai import APIStatusError, RateLimitError

from palate.llm import (
    DEFAULT_FALLBACK_MODELS,
    AssistantMessage,
    OpenRouterBackend,
    _is_retryable,
)


def _fake_completion(content: str = "ok"):
    """Build an object shaped like an OpenAI ChatCompletion response."""
    choice = types.SimpleNamespace(
        message=types.SimpleNamespace(content=content, tool_calls=None)
    )
    return types.SimpleNamespace(choices=[choice])


def _rate_limit_error(model: str) -> RateLimitError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(429, request=req, json={"error": {"message": f"{model} rate-limited"}})
    return RateLimitError(message=f"{model} rate-limited", response=resp, body=None)


def _service_unavailable() -> APIStatusError:
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    resp = httpx.Response(503, request=req, json={"error": {"message": "no healthy upstream"}})
    return APIStatusError(message="503", response=resp, body=None)


class StubCompletions:
    def __init__(self, plan):
        # plan: list of (model_matcher, outcome) — outcome is either an Exception or a response obj
        self.plan = plan
        self.calls: list[str] = []

    def create(self, *, model, messages, tools=None, tool_choice=None):
        self.calls.append(model)
        for matcher, outcome in self.plan:
            if matcher(model):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected model: {model}")


def _patched_backend(stub: StubCompletions) -> OpenRouterBackend:
    b = OpenRouterBackend(model="primary", api_key="k", fallback_models=["fb1", "fb2"])
    # Replace the openai client's chat.completions with our stub.
    b.client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=stub)
    )
    return b


def test_is_retryable_flags_429_and_5xx():
    assert _is_retryable(_rate_limit_error("x"))
    assert _is_retryable(_service_unavailable())
    assert not _is_retryable(ValueError("nope"))


def test_primary_succeeds_no_fallback():
    stub = StubCompletions([(lambda m: True, _fake_completion("hi"))])
    backend = _patched_backend(stub)

    out = backend.chat([{"role": "user", "content": "hi"}], tools=[])

    assert out.content == "hi"
    assert stub.calls == ["primary"]
    assert backend.last_used_model == "primary"
    assert backend.fallback_reason is None


def test_falls_back_on_429_to_first_healthy_model():
    stub = StubCompletions([
        (lambda m: m == "primary", _rate_limit_error("primary")),
        (lambda m: m == "fb1", _fake_completion("from fb1")),
    ])
    backend = _patched_backend(stub)

    out = backend.chat([{"role": "user", "content": "hi"}], tools=[])

    assert out.content == "from fb1"
    assert stub.calls == ["primary", "fb1"]
    assert backend.last_used_model == "fb1"
    assert backend.fallback_reason is not None
    assert "primary" in backend.fallback_reason
    assert "RateLimitError" in backend.fallback_reason


def test_falls_back_on_503():
    stub = StubCompletions([
        (lambda m: m == "primary", _service_unavailable()),
        (lambda m: m == "fb1", _fake_completion("ok")),
    ])
    backend = _patched_backend(stub)

    out = backend.chat([{"role": "user", "content": "hi"}], tools=[])
    assert out.content == "ok"
    assert backend.last_used_model == "fb1"


def test_non_retryable_error_propagates():
    # A 401 (auth) is NOT retryable — trying another model won't help.
    class AuthErr(Exception):
        pass
    stub = StubCompletions([(lambda m: m == "primary", AuthErr("bad key"))])
    backend = _patched_backend(stub)

    with pytest.raises(AuthErr):
        backend.chat([{"role": "user", "content": "hi"}], tools=[])

    # Fallback chain must NOT have been tried.
    assert stub.calls == ["primary"]


def test_all_models_fail_raises_last_error():
    stub = StubCompletions([
        (lambda m: m == "primary", _rate_limit_error("primary")),
        (lambda m: m == "fb1", _rate_limit_error("fb1")),
        (lambda m: m == "fb2", _rate_limit_error("fb2")),
    ])
    backend = _patched_backend(stub)

    with pytest.raises(RateLimitError) as exc:
        backend.chat([{"role": "user", "content": "hi"}], tools=[])

    assert "fb2" in str(exc.value)
    assert stub.calls == ["primary", "fb1", "fb2"]


def test_default_chain_dedups_primary_from_fallbacks():
    # Primary is llama-3.3; it also appears in DEFAULT_FALLBACK_MODELS. Don't retry it twice.
    assert "meta-llama/llama-3.3-70b-instruct:free" in DEFAULT_FALLBACK_MODELS
    b = OpenRouterBackend(model="meta-llama/llama-3.3-70b-instruct:free", api_key="k")
    # Each model should appear exactly once in the chain.
    assert len(b._chain) == len(set(b._chain))


def test_explicit_empty_fallback_list_means_no_retries():
    stub = StubCompletions([(lambda m: m == "primary", _rate_limit_error("primary"))])
    b = OpenRouterBackend(model="primary", api_key="k", fallback_models=[])
    b.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=stub))

    with pytest.raises(RateLimitError):
        b.chat([{"role": "user", "content": "hi"}], tools=[])
    assert stub.calls == ["primary"]
