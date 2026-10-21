"""
Google Maps business search, via the official Google Places API (New).

Pulls local businesses for a search like "web design agency" in "Austin, TX"
- name, website, phone, address, rating, review count, category and the
Google Maps link - the same listings you see on maps.google.com.

USAGE:
    GOOGLE_MAPS_API_KEY=... python scrapers/google_maps.py --query "web design agency" --location "Austin, TX"
    python scrapers/google_maps.py --query "branding studio" "ux agency" --location "London" "Manchester" \\
        --per-search 60 --min-rating 4.5 --min-reviews 10

SETUP:
    1. In Google Cloud Console, enable "Places API (New)" on a project with billing.
    2. Create an API key (restrict it to Places API (New)).
    3. Put it in backend/.env as GOOGLE_MAPS_API_KEY=..., or paste it into the
       Google Maps tab on the Scrapers page.

NOTES:
- This uses Google's API rather than scraping the Maps website: scraping
  maps.google.com is against Google's Terms of Service, gets blocked fast,
  and breaks whenever the page changes. The API returns the same data.
- Each search returns at most 60 places (3 pages of 20) - Google's limit.
  For more, split into more specific searches or more locations.
- Billing: Text Search is charged per request (each page of up to 20
  results is one request), and asking for website/phone/rating puts it in
  a higher price tier. Google gives a monthly free allowance - check
  https://developers.google.com/maps/billing-and-pricing/pricing before
  large runs.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PAGE_SIZE = 20
MAX_PER_SEARCH = 60  # Google returns at most 3 pages per search
MAX_SEARCHES = 10
REQUEST_TIMEOUT = 20.0
PAGE_TOKEN_DELAY = 1.0  # a fresh nextPageToken can take a moment to become valid
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "imports" / "google_maps_leads.csv"

# Only the fields we use - Google bills by the fields requested
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.rating",
    "places.userRatingCount",
    "places.googleMapsUri",
    "places.businessStatus",
    "places.primaryTypeDisplayName",
    "nextPageToken",
])

CSV_FIELDS = [
    "name", "website", "phone", "location", "rating", "reviews", "category",
    "business_status", "maps_url", "place_id", "search",
]

MIN_RATING_OPTIONS = [0, 3.5, 4.0, 4.5, 4.8]


class GoogleMapsError(Exception):
    """A problem worth showing the user as-is (bad key, API not enabled, quota...)."""


@dataclass
class GoogleMapsFilters:
    min_rating: float = 0.0       # sent to Google (minRating)
    min_reviews: int = 0          # applied locally
    require_website: bool = True  # applied locally
    exclude_closed: bool = True   # drop permanently/temporarily closed places
    max_results: int = 0          # 0 = no cap


def build_searches(queries: list[str], locations: list[str]) -> list[str]:
    """Every query in every location: "web design agency in Austin, TX"."""
    queries = [q.strip() for q in queries if q and q.strip()]
    locations = [l.strip() for l in locations if l and l.strip()]
    if not locations:
        return queries
    return [f"{q} in {loc}" for q in queries for loc in locations]


def parse_place(place: dict, search: str) -> dict:
    return {
        "place_id": place.get("id", ""),
        "name": (place.get("displayName") or {}).get("text", ""),
        "website": place.get("websiteUri", ""),
        "phone": place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber", ""),
        "location": place.get("formattedAddress", ""),
        "rating": place.get("rating", ""),
        "reviews": place.get("userRatingCount", 0) or 0,
        "category": (place.get("primaryTypeDisplayName") or {}).get("text", ""),
        "business_status": place.get("businessStatus", ""),
        "maps_url": place.get("googleMapsUri", ""),
        "search": search,
    }


def passes_filters(row: dict, filters: GoogleMapsFilters) -> bool:
    if filters.require_website and not row.get("website"):
        return False
    if filters.min_reviews and int(row.get("reviews") or 0) < filters.min_reviews:
        return False
    if filters.exclude_closed and row.get("business_status") in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
        return False
    return True


def _api_error(resp) -> GoogleMapsError:
    try:
        error = resp.json().get("error", {})
        message, status = error.get("message", ""), error.get("status", "")
    except ValueError:
        message, status = resp.text[:200], ""
    if resp.status_code in (401, 403) or status in ("PERMISSION_DENIED", "UNAUTHENTICATED"):
        hint = ("Check the API key, and that 'Places API (New)' is enabled for its project "
                "(with billing turned on).")
    elif resp.status_code == 429 or status == "RESOURCE_EXHAUSTED":
        hint = "Google's quota for this key is used up - try again later or raise the quota."
    elif resp.status_code == 400:
        hint = "Google rejected the search."
    else:
        hint = "Google Places API error."
    return GoogleMapsError(f"{hint} ({resp.status_code}{' ' + status if status else ''}: {message})".strip())


def _print_progress(message: str, done: Optional[int] = None, total: Optional[int] = None) -> None:
    print(message)


async def scrape_live(
    searches: list[str],
    api_key: str,
    per_search: int = PAGE_SIZE,
    filters: Optional[GoogleMapsFilters] = None,
    on_progress: Optional[Callable[..., None]] = None,
    language: str = "en",
    transport=None,  # httpx transport override, for tests
) -> dict:
    """
    Run each text search through the Places API, page by page (20 per page,
    up to per_search), merging places found by more than one search.

    on_progress(message, done=None, total=None) gets requests made vs. planned.
    Returns {"rows": [...], "stats": [per-search summary]}.
    """
    import httpx

    if not api_key:
        raise GoogleMapsError("No Google Maps API key configured - add one on the Scrapers page or set GOOGLE_MAPS_API_KEY")
    filters = filters or GoogleMapsFilters()
    log = on_progress or _print_progress
    per_search = max(PAGE_SIZE, min(per_search, MAX_PER_SEARCH))
    pages_per_search = -(-per_search // PAGE_SIZE)
    planned = len(searches) * pages_per_search
    done = 0

    rows: dict[str, dict] = {}
    stats: list[dict] = []

    def matching() -> list[dict]:
        return [r for r in rows.values() if passes_filters(r, filters)]

    def is_full() -> bool:
        return bool(filters.max_results) and len(matching()) >= filters.max_results

    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK, "Content-Type": "application/json"}
    async with httpx.AsyncClient(headers=headers, timeout=REQUEST_TIMEOUT, transport=transport) as client:
        for search in searches:
            stat = {"category": search, "url": f"https://www.google.com/maps/search/{search.replace(' ', '+')}",
                    "pages_fetched": 0, "listings": 0, "new": 0, "total_available": None, "error": None}
            stats.append(stat)
            page_token = None
            attempted = 0

            for page_num in range(1, pages_per_search + 1):
                if is_full():
                    break
                body = {"textQuery": search, "pageSize": PAGE_SIZE, "languageCode": language}
                if filters.min_rating:
                    body["minRating"] = filters.min_rating
                if page_token:
                    body["pageToken"] = page_token

                attempted += 1
                try:
                    resp = await client.post(SEARCH_URL, json=body)
                except httpx.HTTPError as exc:
                    stat["error"] = f"Network error: {exc}"
                    done += 1
                    break
                done += 1

                if resp.status_code != 200:
                    error = _api_error(resp)
                    # A bad key/permissions fails every search the same way - stop the run
                    if resp.status_code in (401, 403, 429):
                        raise error
                    stat["error"] = str(error)
                    break

                data = resp.json()
                places = data.get("places", [])
                new = 0
                for place in places:
                    row = parse_place(place, search)
                    key = row["place_id"] or f"{row['name']}|{row['location']}"
                    if key in rows:
                        if search not in rows[key]["search"].split("; "):
                            rows[key]["search"] += f"; {search}"
                        continue
                    rows[key] = row
                    new += 1

                stat["pages_fetched"] += 1
                stat["listings"] += len(places)
                stat["new"] += new
                log(f"{search}: page {page_num} - {len(matching())} businesses so far", done=done, total=planned)

                page_token = data.get("nextPageToken")
                if not page_token or not places:
                    break  # no more results for this search
                await asyncio.sleep(PAGE_TOKEN_DELAY)

            planned -= pages_per_search - attempted
            if is_full():
                log(f"Reached the {filters.max_results}-result cap, stopping.", done=done, total=done)
                break

    results = matching()
    if filters.max_results:
        results = results[: filters.max_results]
    return {"rows": results, "stats": stats}


def write_csv(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Find local businesses via the Google Places API (Google Maps data).")
    parser.add_argument("--query", nargs="+", required=True, help='What to search for, e.g. "web design agency"')
    parser.add_argument("--location", nargs="*", default=[], help='Where, e.g. "Austin, TX" (each query runs in each location)')
    parser.add_argument("--per-search", type=int, default=PAGE_SIZE, choices=[20, 40, 60])
    parser.add_argument("--min-rating", type=float, default=0.0)
    parser.add_argument("--min-reviews", type=int, default=0)
    parser.add_argument("--allow-no-website", action="store_true")
    parser.add_argument("--include-closed", action="store_true")
    parser.add_argument("--max-results", type=int, default=0)
    parser.add_argument("--api-key", default=os.environ.get("GOOGLE_MAPS_API_KEY", ""))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    args = parser.parse_args()

    filters = GoogleMapsFilters(
        min_rating=args.min_rating, min_reviews=args.min_reviews,
        require_website=not args.allow_no_website, exclude_closed=not args.include_closed,
        max_results=args.max_results,
    )
    searches = build_searches(args.query, args.location)[:MAX_SEARCHES]
    try:
        rows = asyncio.run(scrape_live(searches, args.api_key, args.per_search, filters))["rows"]
    except GoogleMapsError as exc:
        print(f"Error: {exc}")
        return
    if not rows:
        print("No businesses matched. Try a broader search or looser filters.")
        return
    write_csv(rows, Path(args.output))
    print(f"\nDone. Saved {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
