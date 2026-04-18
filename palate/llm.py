import os
from dataclasses import dataclass
from typing import Any, Iterable, Protocol

import ollama
from openai import OpenAI


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


class OpenRouterBackend:
    name = "openrouter"

    def __init__(self, model: str = "meta-llama/llama-3.3-70b-instruct:free", api_key: str | None = None):
        self.model = model
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY"),
            default_headers={
                "HTTP-Referer": "https://github.com/hsuanchenlin/palate",
                "X-Title": "Palate",
            },
        )

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
        )
        msg = resp.choices[0].message
        tool_calls = []
        for tc in msg.tool_calls or []:
            import json
            tool_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments or "{}"),
            })
        return AssistantMessage(content=msg.content, tool_calls=tool_calls)


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
