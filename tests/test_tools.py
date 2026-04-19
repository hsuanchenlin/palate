"""Unit tests for palate.tools — pure functions + mocked HTTP."""

import httpx
import pytest
import respx

from palate import tools


# ---------- _format_place ----------


def test_format_place_happy_path():
    raw = {
        "id": "abc",
        "displayName": {"text": "鼎泰豐"},
        "formattedAddress": "台北市信義區",
        "rating": 4.3,
        "userRatingCount": 1234,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "primaryType": "chinese_restaurant",
        "currentOpeningHours": {"openNow": True},
        "location": {"latitude": 25.03, "longitude": 121.56},
    }
    assert tools._format_place(raw) == {
        "place_id": "abc",
        "name": "鼎泰豐",
        "address": "台北市信義區",
        "rating": 4.3,
        "review_count": 1234,
        "price_level": "PRICE_LEVEL_MODERATE",
        "type": "chinese_restaurant",
        "open_now": True,
        "location": {"latitude": 25.03, "longitude": 121.56},
    }


def test_format_place_missing_fields_are_none():
    # Places API omits keys for missing values; .get() must not blow up.
    out = tools._format_place({"id": "x", "displayName": {"text": "無名小店"}})
    assert out["place_id"] == "x"
    assert out["name"] == "無名小店"
    assert out["rating"] is None
    assert out["open_now"] is None
    assert out["location"] is None


# ---------- _format_details ----------


def test_format_details_trims_reviews_to_five():
    raw = {
        "id": "x",
        "displayName": {"text": "test"},
        "reviews": [
            {
                "rating": 5,
                "text": {"text": f"review {i}"},
                "authorAttribution": {"displayName": f"user{i}"},
                "relativePublishTimeDescription": "a week ago",
            }
            for i in range(10)
        ],
    }
    out = tools._format_details(raw)
    assert len(out["reviews"]) == 5
    assert out["reviews"][0]["author"] == "user0"


def test_format_details_prefers_current_hours_falls_back_to_regular():
    raw = {
        "id": "x",
        "displayName": {"text": "test"},
        "regularOpeningHours": {
            "weekdayDescriptions": ["Mon: closed"],
            "openNow": False,
        },
    }
    out = tools._format_details(raw)
    assert out["hours"] == ["Mon: closed"]
    assert out["open_now"] is False


def test_format_details_phone_prefers_national():
    raw = {
        "id": "x",
        "displayName": {"text": "test"},
        "nationalPhoneNumber": "02 1234 5678",
        "internationalPhoneNumber": "+886 2 1234 5678",
    }
    assert tools._format_details(raw)["phone"] == "02 1234 5678"


def test_format_details_falls_back_to_international_phone():
    raw = {
        "id": "x",
        "displayName": {"text": "test"},
        "internationalPhoneNumber": "+886 2 1234 5678",
    }
    assert tools._format_details(raw)["phone"] == "+886 2 1234 5678"


# ---------- _check (error surfacing) ----------


def test_check_raises_with_api_message():
    body = {"error": {"status": "PERMISSION_DENIED", "message": "API disabled"}}
    resp = httpx.Response(403, json=body, request=httpx.Request("POST", "https://x"))
    with pytest.raises(RuntimeError, match="PERMISSION_DENIED: API disabled"):
        tools._check(resp)


def test_check_falls_back_to_text_body_on_non_json():
    resp = httpx.Response(500, text="Internal Server Error", request=httpx.Request("GET", "https://x"))
    with pytest.raises(RuntimeError, match="500"):
        tools._check(resp)


def test_check_is_silent_on_success():
    resp = httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", "https://x"))
    tools._check(resp)  # should not raise


# ---------- _api_key ----------


def test_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_PLACES_API_KEY"):
        tools._api_key()


def test_api_key_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    assert tools._api_key() == "k"


# ---------- search_restaurants (mocked HTTP) ----------


@respx.mock
def test_search_restaurants_sends_taiwan_context_and_formats_results(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    route = respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "p1",
                        "displayName": {"text": "牛肉麵"},
                        "formattedAddress": "台北市",
                        "rating": 4.5,
                        "userRatingCount": 500,
                    }
                ]
            },
        )
    )
    out = tools.search_restaurants("牛肉麵", region="台北", min_rating=4.0, open_now=True, max_results=5)

    assert out == {
        "results": [
            {
                "place_id": "p1",
                "name": "牛肉麵",
                "address": "台北市",
                "rating": 4.5,
                "review_count": 500,
                "price_level": None,
                "type": None,
                "open_now": None,
                "location": None,
            }
        ]
    }

    # Verify the request body carries Taiwan bias + user filters.
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["regionCode"] == "TW"
    assert sent["languageCode"] == "zh-TW"
    assert sent["includedType"] == "restaurant"
    assert sent["textQuery"] == "牛肉麵 in 台北"
    assert sent["minRating"] == 4.0
    assert sent["openNow"] is True
    assert sent["pageSize"] == 5
    # API key goes in header, not query
    assert route.calls.last.request.headers["X-Goog-Api-Key"] == "k"


@respx.mock
def test_search_restaurants_clamps_page_size(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    route = respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(200, json={"places": []})
    )
    tools.search_restaurants("ramen", max_results=999)
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent["pageSize"] == 20  # clamped to max


@respx.mock
def test_search_restaurants_surfaces_api_error(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    respx.post("https://places.googleapis.com/v1/places:searchText").mock(
        return_value=httpx.Response(
            403,
            json={"error": {"status": "PERMISSION_DENIED", "message": "not enabled"}},
        )
    )
    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        tools.search_restaurants("ramen")


# ---------- get_restaurant_details (mocked HTTP) ----------


@respx.mock
def test_get_restaurant_details_hits_correct_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    route = respx.get("https://places.googleapis.com/v1/places/abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "abc123",
                "displayName": {"text": "Din Tai Fung"},
                "nationalPhoneNumber": "02 2345 6789",
                "currentOpeningHours": {
                    "weekdayDescriptions": ["Mon: 10-22"],
                    "openNow": True,
                },
                "reviews": [],
            },
        )
    )
    out = tools.get_restaurant_details("abc123")
    assert out["place_id"] == "abc123"
    assert out["phone"] == "02 2345 6789"
    assert out["hours"] == ["Mon: 10-22"]
    assert out["open_now"] is True
    assert route.calls.last.request.headers["X-Goog-Api-Key"] == "k"
    # languageCode must be passed as a query param
    assert "languageCode=zh-TW" in str(route.calls.last.request.url)


# ---------- schema / registry ----------


def test_tool_registry_matches_schemas():
    schema_names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert schema_names == set(tools.TOOL_REGISTRY.keys())


def test_tool_schemas_have_required_fields():
    for s in tools.TOOL_SCHEMAS:
        assert s["type"] == "function"
        f = s["function"]
        assert f["name"] and f["description"]
        params = f["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
