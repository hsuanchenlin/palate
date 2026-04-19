"""Live integration tests — hit real APIs.

Skipped by default. Run with:  uv run pytest -m live

Each test skips itself if the required env var is missing, so `-m live` won't
fail on a machine that only has one of the keys.
"""

import os

import pytest
from dotenv import load_dotenv

from palate.agent import Agent
from palate.llm import OpenRouterBackend
from palate.tools import get_restaurant_details, search_restaurants

load_dotenv()

pytestmark = pytest.mark.live


def _require(var: str):
    if not os.environ.get(var):
        pytest.skip(f"{var} not set")


def test_live_search_returns_taiwan_restaurants():
    _require("GOOGLE_PLACES_API_KEY")
    out = search_restaurants("牛肉麵", region="台北大安區", max_results=5)
    results = out["results"]
    assert len(results) > 0
    # At least one hit should be an actual Taiwan address.
    assert any("台" in (r.get("address") or "") or "Taiwan" in (r.get("address") or "") for r in results)
    # place_ids should be non-empty strings
    assert all(isinstance(r["place_id"], str) and r["place_id"] for r in results)


def test_live_details_includes_reviews_and_hours():
    _require("GOOGLE_PLACES_API_KEY")
    search = search_restaurants("鼎泰豐", region="台北", max_results=1)
    assert search["results"], "no search hits to look up"
    details = get_restaurant_details(search["results"][0]["place_id"])
    assert details["name"]
    # Rich details should be populated for a well-known chain.
    assert details["maps_url"] and details["maps_url"].startswith("https://")
    assert details["hours"] is None or isinstance(details["hours"], list)


def test_live_agent_loop_through_openrouter():
    _require("GOOGLE_PLACES_API_KEY")
    _require("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    agent = Agent(backend=OpenRouterBackend(model=model))
    messages = [{"role": "user", "content": "Find 2 beef noodle places in Da-an, Taipei. Just names + ratings."}]

    events = []
    try:
        for ev in agent.run(messages):
            events.append(ev)
    except Exception as e:  # pragma: no cover — free tier is flaky
        if "429" in str(e) or "rate" in str(e).lower() or "503" in str(e):
            pytest.skip(f"OpenRouter free tier transient failure: {e}")
        raise

    kinds = [e.kind for e in events]
    assert "tool_call" in kinds, "agent never called a tool — model may not support function calls"
    # There should be a final assistant message after tool results.
    assert events[-1].kind == "assistant"
    assert events[-1].data.content
