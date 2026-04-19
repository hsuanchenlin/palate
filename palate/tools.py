import os

import httpx

PLACES_BASE = "https://places.googleapis.com/v1"

SEARCH_FIELDS = (
    "places.id,places.displayName,places.formattedAddress,places.rating,"
    "places.userRatingCount,places.priceLevel,places.primaryType,"
    "places.currentOpeningHours.openNow,places.location,places.googleMapsUri"
)

DETAILS_FIELDS = (
    "id,displayName,formattedAddress,rating,userRatingCount,priceLevel,"
    "primaryType,types,nationalPhoneNumber,internationalPhoneNumber,websiteUri,"
    "googleMapsUri,currentOpeningHours,regularOpeningHours,reviews,editorialSummary,"
    "location,businessStatus"
)


def _api_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not set")
    return key


def _check(r: httpx.Response) -> None:
    if r.is_success:
        return
    try:
        err = r.json().get("error", {})
        msg = err.get("message") or r.text
        status = err.get("status") or r.status_code
    except Exception:
        msg, status = r.text, r.status_code
    raise RuntimeError(f"Google Places {status}: {msg}")


def search_restaurants(
    query: str,
    region: str = "Taiwan",
    min_rating: float | None = None,
    open_now: bool | None = None,
    max_results: int = 10,
) -> dict:
    """Text search for restaurants in Taiwan via Google Places API v1."""
    body: dict = {
        "textQuery": f"{query} in {region}",
        "includedType": "restaurant",
        "regionCode": "TW",
        "languageCode": "zh-TW",
        "pageSize": max(1, min(max_results, 20)),
    }
    if min_rating is not None:
        body["minRating"] = min_rating
    if open_now is not None:
        body["openNow"] = open_now

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _api_key(),
        "X-Goog-FieldMask": SEARCH_FIELDS,
    }
    r = httpx.post(f"{PLACES_BASE}/places:searchText", json=body, headers=headers, timeout=20)
    _check(r)
    data = r.json()
    return {"results": [_format_place(p) for p in data.get("places", [])]}


def get_restaurant_details(place_id: str) -> dict:
    """Fetch detailed info for one place, including reviews and hours."""
    headers = {
        "X-Goog-Api-Key": _api_key(),
        "X-Goog-FieldMask": DETAILS_FIELDS,
    }
    params = {"languageCode": "zh-TW"}
    r = httpx.get(f"{PLACES_BASE}/places/{place_id}", headers=headers, params=params, timeout=20)
    _check(r)
    return _format_details(r.json())


def _format_place(p: dict) -> dict:
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text"),
        "address": p.get("formattedAddress"),
        "rating": p.get("rating"),
        "review_count": p.get("userRatingCount"),
        "price_level": p.get("priceLevel"),
        "type": p.get("primaryType"),
        "open_now": (p.get("currentOpeningHours") or {}).get("openNow"),
        "maps_url": p.get("googleMapsUri"),
        "location": p.get("location"),
    }


def _format_details(p: dict) -> dict:
    reviews = []
    for r in (p.get("reviews") or [])[:5]:
        reviews.append({
            "rating": r.get("rating"),
            "text": (r.get("text") or {}).get("text"),
            "author": (r.get("authorAttribution") or {}).get("displayName"),
            "relative_time": r.get("relativePublishTimeDescription"),
        })
    hours = p.get("currentOpeningHours") or p.get("regularOpeningHours") or {}
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text"),
        "address": p.get("formattedAddress"),
        "rating": p.get("rating"),
        "review_count": p.get("userRatingCount"),
        "price_level": p.get("priceLevel"),
        "type": p.get("primaryType"),
        "phone": p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber"),
        "website": p.get("websiteUri"),
        "maps_url": p.get("googleMapsUri"),
        "summary": (p.get("editorialSummary") or {}).get("text"),
        "hours": hours.get("weekdayDescriptions"),
        "open_now": hours.get("openNow"),
        "business_status": p.get("businessStatus"),
        "reviews": reviews,
        "location": p.get("location"),
    }


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_restaurants",
            "description": (
                "Search for restaurants in Taiwan by cuisine, dish, neighborhood, or any free-text query. "
                "Returns up to 10 candidates with name, address, rating, and place_id. "
                "Use get_restaurant_details for reviews, hours, and phone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text search, e.g. '牛肉麵 台北大安區', 'ramen Ximending', 'vegan brunch Tainan'.",
                    },
                    "region": {
                        "type": "string",
                        "description": "Area within Taiwan to prefer (city or district). Defaults to 'Taiwan'.",
                    },
                    "min_rating": {
                        "type": "number",
                        "description": "Filter to places with rating >= this value (0-5).",
                    },
                    "open_now": {
                        "type": "boolean",
                        "description": "If true, only return places open at request time.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (1-20, default 10).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_restaurant_details",
            "description": (
                "Fetch full details for one restaurant by place_id: reviews, opening hours, phone, website, "
                "Google Maps link, editorial summary. Call this after search_restaurants when the user wants "
                "more info about a specific place."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "place_id": {
                        "type": "string",
                        "description": "Google Places place_id returned by search_restaurants.",
                    },
                },
                "required": ["place_id"],
            },
        },
    },
]


TOOL_REGISTRY = {
    "search_restaurants": search_restaurants,
    "get_restaurant_details": get_restaurant_details,
}
