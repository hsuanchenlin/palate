import json
import os
from dataclasses import dataclass
from typing import Iterable, Protocol

import ollama
from openai import APIStatusError, OpenAI, RateLimitError


@dataclass
class AssistantMessage:
    content: str | None
    tool_calls: list[dict]  # [{id, name, arguments(dict)}]


class Backend(Protocol):
    name: str

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> AssistantMessage: ...


# Free OpenRouter models that support tool calling, tried in order when the
# primary model is rate-limited. Ordered roughly by answer quality.
DEFAULT_FALLBACK_MODELS = (
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-nano-9b-v2:free",
)


def _is_retryable(err: Exception) -> bool:
    """429 upstream rate limits, 503 no-healthy-upstream — try another model."""
    if isinstance(err, RateLimitError):
        return True
    if isinstance(err, APIStatusError) and err.status_code in (502, 503, 504):
        return True
    return False


class OpenRouterBackend:
    name = "openrouter"

    def __init__(
        self,
        model: str = "meta-llama/llama-3.3-70b-instruct:free",
        api_key: str | None = None,
        fallback_models: Iterable[str] | None = None,
    ):
        self.model = model
        # Chain = primary + fallbacks (dedup, preserve order).
        chain: list[str] = [model]
        for m in (fallback_models if fallback_models is not None else DEFAULT_FALLBACK_MODELS):
            if m not in chain:
                chain.append(m)
        self._chain = chain
        self.last_used_model: str = model
        self.fallback_reason: str | None = None  # set when we had to fall back
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY"),
            default_headers={
                "HTTP-Referer": "https://github.com/hsuanchenlin/palate",
                "X-Title": "Palate",
            },
        )

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        last_err: Exception | None = None
        self.fallback_reason = None
        for m in self._chain:
            try:
                resp = self.client.chat.completions.create(
                    model=m,
                    messages=messages,
                    tools=tools or None,
                    tool_choice="auto" if tools else None,
                )
            except Exception as e:
                last_err = e
                if not _is_retryable(e):
                    raise
                if m == self._chain[0]:
                    # Only mark the fallback reason once — when the primary failed.
                    self.fallback_reason = f"{m} failed ({type(e).__name__}); trying fallback models"
                continue
            self.last_used_model = m
            msg = resp.choices[0].message
            tool_calls = []
            for tc in msg.tool_calls or []:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments or "{}"),
                })
            return AssistantMessage(content=msg.content, tool_calls=tool_calls)

        assert last_err is not None
        raise last_err


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str = "gemma3:4b", host: str | None = None):
        self.model = model
        self.client = ollama.Client(host=host or os.environ.get("OLLAMA_HOST", "http://localhost:11434"))

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        resp = self.client.chat(
            model=self.model,
            messages=_to_ollama_messages(messages),
            tools=tools or None,
        )
        msg = resp["message"]
        tool_calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            tool_calls.append({
                "id": tc.get("id") or f"call_{i}",
                "name": fn.get("name"),
                "arguments": fn.get("arguments") or {},
            })
        return AssistantMessage(content=msg.get("content") or None, tool_calls=tool_calls)


def _to_ollama_messages(messages: list[dict]) -> list[dict]:
    """Ollama accepts the same OpenAI-style schema but strip unknown keys."""
    out = []
    for m in messages:
        role = m["role"]
        if role == "tool":
            out.append({
                "role": "tool",
                "content": m.get("content", ""),
                "tool_call_id": m.get("tool_call_id"),
            })
        elif role == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in m["tool_calls"]
                ],
            })
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out


def available_ollama_models(host: str | None = None) -> Iterable[str]:
    try:
        client = ollama.Client(host=host or os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
        return [m["model"] for m in client.list().get("models", [])]
    except Exception:
        return []
