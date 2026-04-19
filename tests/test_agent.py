"""Unit tests for palate.agent — loop, tool dispatch, error paths, termination.

The agent is driven by a fake Backend that returns scripted replies, so these tests
exercise the control flow without hitting OpenRouter or Ollama.
"""

import json

import pytest

from palate.agent import Agent, Event
from palate.llm import AssistantMessage


class ScriptedBackend:
    """Backend stub that replays a canned list of AssistantMessage replies."""

    name = "scripted"

    def __init__(self, replies: list[AssistantMessage]):
        self._replies = list(replies)
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def chat(self, messages, tools):
        # Snapshot inputs so tests can assert conversation state at each step.
        self.calls.append(([dict(m) for m in messages], tools))
        if not self._replies:
            raise AssertionError("ScriptedBackend ran out of replies")
        return self._replies.pop(0)


def _tool_call(name, args, id_="c1"):
    return {"id": id_, "name": name, "arguments": args}


def test_no_tool_calls_returns_after_one_turn():
    backend = ScriptedBackend([AssistantMessage(content="Hi!", tool_calls=[])])
    agent = Agent(backend=backend, tools=[], registry={})
    messages = [{"role": "user", "content": "hello"}]

    events = list(agent.run(messages))

    assert len(events) == 1
    assert events[0].kind == "assistant"
    assert events[0].data.content == "Hi!"
    # system prompt injected, user preserved, assistant appended
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "assistant", "content": "Hi!"}
    assert len(backend.calls) == 1


def test_single_tool_call_then_final_answer():
    fake_result = {"results": [{"place_id": "p1", "name": "Foo"}]}
    backend = ScriptedBackend([
        AssistantMessage(content=None, tool_calls=[_tool_call("search_restaurants", {"query": "ramen"})]),
        AssistantMessage(content="Try Foo.", tool_calls=[]),
    ])
    registry = {"search_restaurants": lambda **kw: fake_result}
    agent = Agent(backend=backend, tools=[], registry=registry)
    messages = [{"role": "user", "content": "ramen?"}]

    events = list(agent.run(messages))

    kinds = [e.kind for e in events]
    assert kinds == ["assistant", "tool_call", "tool_result", "assistant"]

    # tool_result event carries the actual tool output
    assert events[2].data["result"] == fake_result

    # Message history now contains: system, user, assistant-with-tool_calls, tool, final assistant
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    tool_msg = messages[3]
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["name"] == "search_restaurants"
    assert json.loads(tool_msg["content"]) == fake_result


def test_unknown_tool_returns_error_payload_not_raise():
    backend = ScriptedBackend([
        AssistantMessage(content=None, tool_calls=[_tool_call("nonexistent", {})]),
        AssistantMessage(content="sorry", tool_calls=[]),
    ])
    agent = Agent(backend=backend, tools=[], registry={})

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    tool_result_events = [e for e in events if e.kind == "tool_result"]
    assert len(tool_result_events) == 1
    assert "unknown tool" in tool_result_events[0].data["result"]["error"]


def test_tool_exception_captured_as_error_dict():
    def boom(**kw):
        raise ValueError("places API down")

    backend = ScriptedBackend([
        AssistantMessage(content=None, tool_calls=[_tool_call("search_restaurants", {})]),
        AssistantMessage(content="fallback", tool_calls=[]),
    ])
    agent = Agent(backend=backend, tools=[], registry={"search_restaurants": boom})

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    err = [e for e in events if e.kind == "tool_result"][0].data["result"]
    assert err == {"error": "ValueError: places API down"}


def test_multiple_tool_calls_in_one_turn_all_execute():
    registry = {
        "a": lambda **kw: {"from": "a"},
        "b": lambda **kw: {"from": "b"},
    }
    backend = ScriptedBackend([
        AssistantMessage(
            content=None,
            tool_calls=[
                _tool_call("a", {}, id_="c1"),
                _tool_call("b", {}, id_="c2"),
            ],
        ),
        AssistantMessage(content="done", tool_calls=[]),
    ])
    agent = Agent(backend=backend, tools=[], registry=registry)
    messages = [{"role": "user", "content": "hi"}]

    list(agent.run(messages))

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]
    assert [m["name"] for m in tool_msgs] == ["a", "b"]


def test_max_steps_prevents_infinite_loop():
    # A malicious/buggy model that keeps calling tools forever.
    def looping_reply():
        while True:
            yield AssistantMessage(content=None, tool_calls=[_tool_call("a", {})])

    replies = []
    gen = looping_reply()
    for _ in range(20):
        replies.append(next(gen))
    backend = ScriptedBackend(replies)
    agent = Agent(
        backend=backend,
        tools=[],
        registry={"a": lambda **kw: {"ok": True}},
        max_steps=3,
    )

    events = list(agent.run([{"role": "user", "content": "hi"}]))

    # 3 tool-calling turns + 1 final stopped-message event
    assistant_events = [e for e in events if e.kind == "assistant"]
    assert assistant_events[-1].data.content == "(stopped: max steps reached)"
    assert len(backend.calls) == 3


def test_system_prompt_inserted_only_if_missing():
    backend = ScriptedBackend([AssistantMessage(content="ok", tool_calls=[])])
    agent = Agent(backend=backend, tools=[], registry={})
    messages = [
        {"role": "system", "content": "custom system"},
        {"role": "user", "content": "hi"},
    ]
    list(agent.run(messages))
    assert messages[0]["content"] == "custom system"
    # No duplicate system messages
    assert sum(1 for m in messages if m["role"] == "system") == 1


def test_assistant_tool_call_message_is_openai_shaped():
    """The assistant message appended to history must be valid OpenAI format
    so the next backend call can replay it."""
    backend = ScriptedBackend([
        AssistantMessage(content=None, tool_calls=[_tool_call("a", {"x": 1})]),
        AssistantMessage(content="done", tool_calls=[]),
    ])
    agent = Agent(backend=backend, tools=[], registry={"a": lambda **kw: {}})
    messages = [{"role": "user", "content": "hi"}]
    list(agent.run(messages))

    asst = messages[2]
    assert asst["role"] == "assistant"
    tc = asst["tool_calls"][0]
    assert tc == {
        "id": "c1",
        "type": "function",
        "function": {"name": "a", "arguments": json.dumps({"x": 1})},
    }
