import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from palate.llm import AssistantMessage, Backend
from palate.tools import TOOL_REGISTRY, TOOL_SCHEMAS

SYSTEM_PROMPT = """You are Palate, a Taiwan restaurant concierge.

You help users discover restaurants across Taiwan — from night-market stalls in Tainan to
fine dining in Taipei. You speak whichever language the user writes in (Mandarin, English,
or mixed is fine).

Tool usage:
- Call `search_restaurants` whenever the user names a dish, cuisine, area, or vibe. Pass the
  user's intent into the `query` in whatever language fits best (Chinese queries often return
  better matches for local spots).
- Call `get_restaurant_details` when the user asks about a specific place, wants reviews,
  hours, or a phone number — use the place_id from the prior search.
- For every restaurant you mention, include its Google Maps link as a Markdown link on the
  name, e.g. `[鼎泰豐](https://maps.google.com/...)`. The `maps_url` field is present on every
  search result — never omit it, and never invent one.
- Prefer citing rating, review count, and a short excerpt from a review when you have one.
- If results are empty or low quality, broaden the query (drop area, try English/Chinese) and
  try again before apologizing.

Never invent place_ids, addresses, or phone numbers. Only quote what the tools return."""


@dataclass
class Event:
    kind: str  # "assistant" | "tool_call" | "tool_result"
    data: Any


@dataclass
class Agent:
    backend: Backend
    tools: list[dict] = field(default_factory=lambda: TOOL_SCHEMAS)
    registry: dict[str, Callable[..., Any]] = field(default_factory=lambda: TOOL_REGISTRY)
    max_steps: int = 6

    def run(self, messages: list[dict]) -> Iterator[Event]:
        """Run the agent loop, yielding events as they happen.

        `messages` is mutated in place with new assistant/tool messages so the caller
        can persist chat history.
        """
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

        for _ in range(self.max_steps):
            reply: AssistantMessage = self.backend.chat(messages, self.tools)

            assistant_msg: dict = {"role": "assistant", "content": reply.content or ""}
            if reply.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in reply.tool_calls
                ]
            messages.append(assistant_msg)
            yield Event("assistant", reply)

            if not reply.tool_calls:
                return

            for tc in reply.tool_calls:
                yield Event("tool_call", tc)
                result = self._invoke(tc["name"], tc["arguments"])
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
                messages.append(tool_msg)
                yield Event("tool_result", {"id": tc["id"], "name": tc["name"], "result": result})

        yield Event("assistant", AssistantMessage(content="(stopped: max steps reached)", tool_calls=[]))

    def _invoke(self, name: str, args: dict) -> Any:
        fn = self.registry.get(name)
        if fn is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return fn(**args)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
