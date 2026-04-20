"""Unit tests for palate.cache.PlacesCache."""

import time

import httpx
import pytest
import respx

from palate import cache as cache_mod
from palate.cache import PlacesCache
from palate import tools


@pytest.fixture
def cache(tmp_path):
    return PlacesCache(path=tmp_path / "places.sqlite3")


# ---------- basic put / get / miss ----------


def test_miss_returns_none(cache):
    assert cache.get("search_restaurants", {"query": "ramen"}) is None


def test_put_then_get_roundtrips(cache):
    cache.put("search_restaurants", {"query": "ramen"}, {"results": [{"name": "A"}]})
    assert cache.get("search_restaurants", {"query": "ramen"}) == {"results": [{"name": "A"}]}


def test_different_fn_same_args_are_separate_keys(cache):
    cache.put("search_restaurants", {"q": "x"}, {"fn": "search"})
    cache.put("get_restaurant_details", {"q": "x"}, {"fn": "details"})
    assert cache.get("search_restaurants", {"q": "x"}) == {"fn": "search"}
    assert cache.get("get_restaurant_details", {"q": "x"}) == {"fn": "details"}


def test_args_order_doesnt_matter(cache):
    cache.put("search_restaurants", {"a": 1, "b": 2}, {"ok": True})
    assert cache.get("search_restaurants", {"b": 2, "a": 1}) == {"ok": True}


def test_chinese_args_roundtrip(cache):
    cache.put("search_restaurants", {"query": "牛肉麵"}, {"results": [{"name": "地一"}]})
    assert cache.get("search_restaurants", {"query": "牛肉麵"}) == {
        "results": [{"name": "地一"}]
    }


# ---------- TTL ----------


def test_expired_entry_returns_none_and_is_evicted(cache):
    cache.put("search_restaurants", {"q": "x"}, {"ok": True})
    # Rewrite the expires_at to the past.
    import sqlite3

    conn = sqlite3.connect(cache.path)
    conn.execute("UPDATE cache SET expires_at = ?", (time.time() - 1,))
    conn.commit()
    conn.close()
    assert cache.get("search_restaurants", {"q": "x"}) is None
    # Second call still miss (evicted).
    assert cache.get("search_restaurants", {"q": "x"}) is None


def test_per_function_ttl(tmp_path):
    cache = PlacesCache(
        path=tmp_path / "c.sqlite3",
        ttls={"search_restaurants": 1, "get_restaurant_details": 1000},
    )
    assert cache.ttls["search_restaurants"] == 1
    assert cache.ttls["get_restaurant_details"] == 1000


# ---------- clear / stats ----------


def test_clear_wipes_and_returns_count(cache):
    cache.put("search_restaurants", {"q": "x"}, {"ok": True})
    cache.put("search_restaurants", {"q": "y"}, {"ok": True})
    assert cache.clear() == 2
    assert cache.get("search_restaurants", {"q": "x"}) is None


def test_stats_counts_entries_and_buckets_by_fn(cache):
    cache.put("search_restaurants", {"q": "x"}, {"ok": True})
    cache.put("search_restaurants", {"q": "y"}, {"ok": True})
    cache.put("get_restaurant_details", {"pid": "p1"}, {"ok": True})
    s = cache.stats()
    assert s["total"] == 3
    assert s["by_fn"] == {"search_restaurants": 2, "get_restaurant_details": 1}


# ---------- disabled mode ----------


def test_disabled_cache_is_silent_noop(tmp_path):
    cache = PlacesCache(path=tmp_path / "x.sqlite3", disabled=True)
    cache.put("search_restaurants", {"q": "x"}, {"ok": True})
    assert cache.get("search_restaurants", {"q": "x"}) is None
    assert cache.stats() == {"disabled": True}
    assert cache.clear() == 0


# ---------- integration with tools.py ----------


@respx.mock
def test_tools_uses_cache_on_second_call(tmp_path, monkeypatch):
    """First search hits the API; second identical search hits the cache only."""
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    cache_mod.set_default(PlacesCache(path=tmp_path / "c.sqlite3"))

    route = respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(
            200,
            json={"places": [{"id": "p1", "displayName": {"text": "A"}}]},
        )
    )

    first = tools.search_restaurants("ramen", region="Taipei")
    second = tools.search_restaurants("ramen", region="Taipei")

    assert first == second
    assert route.call_count == 1  # second call served from cache


@respx.mock
def test_tools_different_args_are_separate_cache_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    cache_mod.set_default(PlacesCache(path=tmp_path / "c.sqlite3"))

    route = respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(200, json={"places": []})
    )

    tools.search_restaurants("ramen", region="Taipei")
    tools.search_restaurants("ramen", region="Tainan")  # different region

    assert route.call_count == 2


@respx.mock
def test_tools_details_are_cached_by_place_id(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    cache_mod.set_default(PlacesCache(path=tmp_path / "c.sqlite3"))

    route = respx.get("https://places.googleapis.com/v1/places/abc").mock(
        return_value=httpx.Response(
            200,
            json={"id": "abc", "displayName": {"text": "Din Tai Fung"}},
        )
    )

    tools.get_restaurant_details("abc")
    tools.get_restaurant_details("abc")

    assert route.call_count == 1
