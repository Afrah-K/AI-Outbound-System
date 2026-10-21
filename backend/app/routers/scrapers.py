"""
Runs the standalone lead-source scrapers in backend/scrapers/ on demand from
the API, so they can be triggered from the frontend instead of only the CLI.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.calendly import get_settings as get_integration_settings
from app.services.jobs import JobRun, enqueue_job, get_job, job_handler, to_dict
from scrapers import awwwards, clutch, google_maps
from scrapers.google_maps import GoogleMapsError, GoogleMapsFilters
from scrapers.awwwards import AwwwardsFilters
from scrapers.clutch import ClutchFilters, parse_files, scrape_live

router = APIRouter()

MAX_PAGES = 5
MAX_URLS = 10
MAX_RESULTS = 2000


class ClutchFilterOptions(BaseModel):
    location: str = Field(default="", max_length=80)
    sort_by: str = ""
    hourly_rate: str = ""
    budget: str = ""
    industry: str = ""
    min_rating: float = Field(default=0.0, ge=0, le=5)
    min_reviews: int = Field(default=0, ge=0)
    verified_only: bool = False
    require_website: bool = False
    include_sponsored: bool = False
    max_results: int = Field(default=0, ge=0, le=MAX_RESULTS)


class ClutchScrapeRequest(BaseModel):
    urls: list[str] = Field(default_factory=lambda: list(clutch.DESIGN_CATEGORY_URLS), min_length=1, max_length=MAX_URLS)
    pages: int = Field(default=1, ge=1, le=MAX_PAGES)
    filters: ClutchFilterOptions = Field(default_factory=ClutchFilterOptions)


class AwwwardsFilterOptions(BaseModel):
    countries: list[str] = Field(default_factory=list, max_length=len(awwwards.COUNTRIES))
    min_total_awards: int = Field(default=0, ge=0)
    min_sotd: int = Field(default=0, ge=0)
    pro_only: bool = False
    require_website: bool = True
    with_profiles: bool = False
    active_within_months: int = Field(default=0, ge=0, le=120)
    max_results: int = Field(default=0, ge=0, le=MAX_RESULTS)


class AwwwardsScrapeRequest(BaseModel):
    listings: list[str] = Field(default_factory=lambda: [""], min_length=1, max_length=MAX_URLS)
    pages: int = Field(default=2, ge=1, le=awwwards.MAX_PAGES)
    filters: AwwwardsFilterOptions = Field(default_factory=AwwwardsFilterOptions)


class GoogleMapsFilterOptions(BaseModel):
    min_rating: float = Field(default=0.0, ge=0, le=5)
    min_reviews: int = Field(default=0, ge=0)
    require_website: bool = True
    exclude_closed: bool = True
    max_results: int = Field(default=0, ge=0, le=MAX_RESULTS)


class GoogleMapsScrapeRequest(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=google_maps.MAX_SEARCHES)
    locations: list[str] = Field(default_factory=list, max_length=google_maps.MAX_SEARCHES)
    per_search: int = Field(default=google_maps.PAGE_SIZE, ge=google_maps.PAGE_SIZE, le=google_maps.MAX_PER_SEARCH)
    filters: GoogleMapsFilterOptions = Field(default_factory=GoogleMapsFilterOptions)


class GoogleMapsKeyRequest(BaseModel):
    api_key: str = Field(default="", max_length=200)  # empty clears the saved key


def _google_maps_key(db: Session) -> tuple[str, Optional[str]]:
    """(key, where it came from) - .env wins over a key saved from the UI."""
    if settings.google_maps_api_key:
        return settings.google_maps_api_key, "env"
    saved = get_integration_settings(db).google_maps_api_key
    return (saved, "saved") if saved else ("", None)


def _options(pairs):
    return [{"value": value, "label": label} for value, label in pairs]


def _validate_choice(name: str, value: str, pairs) -> None:
    if value and value not in {v for v, _ in pairs}:
        raise HTTPException(status_code=422, detail=f"Unknown {name}: {value}")


def _to_filters(options: Optional[ClutchFilterOptions]) -> ClutchFilters:
    options = options or ClutchFilterOptions()
    _validate_choice("sort_by", options.sort_by, clutch.SORT_OPTIONS)
    _validate_choice("hourly_rate", options.hourly_rate, clutch.HOURLY_RATE_OPTIONS)
    _validate_choice("budget", options.budget, clutch.BUDGET_OPTIONS)
    _validate_choice("industry", options.industry, clutch.INDUSTRY_OPTIONS)
    return ClutchFilters(**options.model_dump())


@router.get("")
async def list_scrapers(db: Session = Depends(get_db)):
    """Available lead-source scrapers and their run parameters."""
    _, key_source = _google_maps_key(db)
    return {
        "scrapers": [
            {
                "id": "clutch",
                "name": "Clutch.co Directory",
                "description": (
                    "Pulls agencies from Clutch directory listings - name, website, location, "
                    "rating, reviews, pricing, team size, verification and service focus."
                ),
                "default_urls": clutch.DESIGN_CATEGORY_URLS,
                "categories": [{"label": label, "url": url} for label, url in clutch.DESIGN_CATEGORIES],
                "category_groups": [
                    {"group": group, "categories": [{"label": label, "url": url} for label, url in items]}
                    for group, items in clutch.CATEGORY_GROUPS.items()
                ],
                "filter_options": {
                    "sort_by": _options(clutch.SORT_OPTIONS),
                    "hourly_rate": _options(clutch.HOURLY_RATE_OPTIONS),
                    "budget": _options(clutch.BUDGET_OPTIONS),
                    "industry": _options(clutch.INDUSTRY_OPTIONS),
                    "location": _options(clutch.LOCATION_PRESETS),
                },
                "fields": clutch.CSV_FIELDS,
                "max_pages": MAX_PAGES,
                "max_urls": MAX_URLS,
                "max_results": MAX_RESULTS,
                # Clutch fronts its pages with a Cloudflare JS challenge that blocks
                # plain HTTP requests. A real (visible) browser passes it, so live
                # fetch works, but it launches an actual Chrome window while it runs.
                "live_fetch_blocked": False,
                "live_fetch_note": (
                    "Uses a real, visible Chromium window to pass Clutch's bot-check - "
                    "expect a browser window to briefly appear for each page fetched "
                    "(~10-15s per page). Location, sort, rate, budget and industry are "
                    "applied by Clutch itself, so a targeted run needs fewer pages."
                ),
                "upload_supported": True,
            },
            {
                "id": "awwwards",
                "name": "Awwwards Directory",
                "description": (
                    "Pulls award-winning studios and freelancers from the Awwwards directory - "
                    "name, website, country, PRO status and award counts, plus optional profile "
                    "details (city, budget, languages, LinkedIn/Instagram, last award date)."
                ),
                "listing_groups": [
                    {"group": group, "listings": [{"value": slug, "label": label} for slug, label in items]}
                    for group, items in awwwards.LISTING_GROUPS.items()
                ],
                "countries": awwwards.COUNTRIES,
                "fields": awwwards.CSV_FIELDS,
                "max_pages": awwwards.MAX_PAGES,
                "max_urls": MAX_URLS,
                "max_results": MAX_RESULTS,
                "max_profiles": awwwards.MAX_PROFILES,
                "cards_per_page": awwwards.CARDS_PER_PAGE,
                "live_fetch_note": (
                    "Plain HTTP, no browser window - about 2-3s per directory page (24 studios) and "
                    "~1s per profile when profile details are on. Each listing is one filter "
                    "(a service, type, budget or country); Awwwards' combined search is off-limits "
                    "per its robots.txt, so narrow results with the filters below instead. To target "
                    "one country, browse that country's listing rather than filtering a service listing."
                ),
                "upload_supported": False,
            },
            {
                "id": "google_maps",
                "name": "Google Maps",
                "description": (
                    "Finds local businesses the way a Google Maps search does - name, website, phone, "
                    "address, rating, review count and category - via Google's official Places API."
                ),
                "configured": key_source is not None,
                "key_source": key_source,  # "env", "saved" or None - the key itself is never sent
                "fields": google_maps.CSV_FIELDS,
                "max_searches": google_maps.MAX_SEARCHES,
                "per_search_options": [20, 40, 60],
                "min_rating_options": google_maps.MIN_RATING_OPTIONS,
                "max_results": MAX_RESULTS,
                "live_fetch_note": (
                    "Uses Google's Places API, so it needs an API key with 'Places API (New)' enabled. "
                    "Each search returns at most 60 businesses (Google's limit) - add more locations or "
                    "more specific searches for bigger lists. Google bills per request (each page of 20 "
                    "is one), with a monthly free allowance."
                ),
                "upload_supported": False,
            },
        ]
    }


async def _scrape_clutch(payload: ClutchScrapeRequest, filters: ClutchFilters, on_progress=None) -> dict:
    result = await scrape_live(payload.urls, payload.pages, filters, on_progress=on_progress)

    if not result["rows"]:
        fetched_any = any(s["pages_fetched"] for s in result["stats"])
        raise HTTPException(
            status_code=502 if not fetched_any else 404,
            detail=(
                "Pages loaded, but no listings matched your filters - try loosening "
                "min rating/reviews, 'verified only' or 'has website', or adding pages."
                if fetched_any else
                "No listings found. Clutch may still be showing its Cloudflare "
                "challenge, the category/location may have no results, or the page "
                "layout changed - check scrapers/clutch.py's selectors. You can "
                "also fall back to 'Upload saved page(s)'."
            ),
        )

    return {"rows": result["rows"], "count": len(result["rows"]), "stats": result["stats"]}


def _awwwards_filters(payload: AwwwardsScrapeRequest) -> AwwwardsFilters:
    unknown = [slug for slug in payload.listings if slug not in awwwards.ALL_LISTINGS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown listing(s): {', '.join(unknown)}")
    bad_countries = [c for c in payload.filters.countries if c not in awwwards.COUNTRIES]
    if bad_countries:
        raise HTTPException(status_code=422, detail=f"Unknown country: {', '.join(bad_countries)}")

    options = payload.filters.model_dump()
    if options["active_within_months"]:
        options["with_profiles"] = True
    return AwwwardsFilters(**options)


async def _scrape_awwwards(payload: AwwwardsScrapeRequest, filters: AwwwardsFilters, on_progress=None) -> dict:
    result = await awwwards.scrape_live(payload.listings, payload.pages, filters, on_progress=on_progress)

    if not result["rows"]:
        fetched_any = any(s["pages_fetched"] for s in result["stats"])
        raise HTTPException(
            status_code=404 if fetched_any else 502,
            detail=(
                "Pages loaded, but no studios matched your filters - try loosening the "
                "awards/country/activity filters, or adding pages."
                if fetched_any else
                "Couldn't load the Awwwards directory - the site may be down, or its "
                "layout changed (check scrapers/awwwards.py's selectors)."
            ),
        )

    return {"rows": result["rows"], "count": len(result["rows"]), "stats": result["stats"]}


# Background jobs: the API validates and queues; the worker (in-process locally,
# a Vercel Daemon in production) runs these handlers - see app/services/jobs.py

@job_handler("clutch")
async def _clutch_job(job: JobRun, data: dict) -> dict:
    payload = ClutchScrapeRequest(**data)
    return await _scrape_clutch(payload, _to_filters(payload.filters), on_progress=job.progress)


@job_handler("awwwards")
async def _awwwards_job(job: JobRun, data: dict) -> dict:
    payload = AwwwardsScrapeRequest(**data)
    return await _scrape_awwwards(payload, _awwwards_filters(payload), on_progress=job.progress)


@job_handler("google_maps")
async def _google_maps_job(job: JobRun, data: dict) -> dict:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        api_key, _ = _google_maps_key(db)  # read here, so the key never sits in the job record
    finally:
        db.close()
    if not api_key:
        raise HTTPException(status_code=400, detail="Add a Google Maps API key first (Places API (New))")
    return await _scrape_google_maps(GoogleMapsScrapeRequest(**data), api_key, on_progress=job.progress)


@router.post("/clutch/jobs")
async def start_clutch_job(payload: ClutchScrapeRequest, db: Session = Depends(get_db)):
    """
    Start a Clutch scrape in the background and return immediately - poll
    GET /scrapers/jobs/{job_id} for progress and, once completed, the rows.
    Lets the frontend move to other pages while it runs.
    """
    _to_filters(payload.filters)  # reject bad filter values now, not in the worker
    return enqueue_job(db, "clutch", payload.model_dump(), total=len(payload.urls) * payload.pages,
                       message="Opening the browser...")


@router.post("/awwwards/jobs")
async def start_awwwards_job(payload: AwwwardsScrapeRequest, db: Session = Depends(get_db)):
    """Start an Awwwards scrape in the background - poll GET /scrapers/jobs/{job_id}."""
    _awwwards_filters(payload)
    return enqueue_job(db, "awwwards", payload.model_dump(), total=len(payload.listings) * payload.pages,
                       message="Starting...")


@router.put("/google-maps/key")
async def save_google_maps_key(payload: GoogleMapsKeyRequest, db: Session = Depends(get_db)):
    """Save (or, with an empty key, clear) the Google Maps API key used when .env doesn't set one."""
    row = get_integration_settings(db)
    row.google_maps_api_key = payload.api_key.strip() or None
    db.commit()
    _, key_source = _google_maps_key(db)
    return {"configured": key_source is not None, "key_source": key_source}


async def _scrape_google_maps(payload: GoogleMapsScrapeRequest, api_key: str, on_progress=None) -> dict:
    searches = google_maps.build_searches(payload.queries, payload.locations)
    try:
        result = await google_maps.scrape_live(
            searches, api_key, payload.per_search, GoogleMapsFilters(**payload.filters.model_dump()),
            on_progress=on_progress,
        )
    except GoogleMapsError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not result["rows"]:
        found_any = any(s["listings"] for s in result["stats"])
        errors = [s["error"] for s in result["stats"] if s["error"]]
        raise HTTPException(
            status_code=404 if found_any else 502,
            detail=(
                "Google found businesses, but none matched your filters - try allowing places "
                "without a website, or lowering the minimum rating/reviews."
                if found_any else
                errors[0] if errors else "Google found no businesses for these searches - try broader terms."
            ),
        )
    return {"rows": result["rows"], "count": len(result["rows"]), "stats": result["stats"]}


@router.post("/google-maps/jobs")
async def start_google_maps_job(payload: GoogleMapsScrapeRequest, db: Session = Depends(get_db)):
    """Start a Google Maps (Places API) search in the background - poll GET /scrapers/jobs/{job_id}."""
    api_key, _ = _google_maps_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="Add a Google Maps API key first (Places API (New))")
    searches = google_maps.build_searches(payload.queries, payload.locations)
    if not searches:
        raise HTTPException(status_code=422, detail="Enter at least one search, e.g. 'web design agency'")
    if len(searches) > google_maps.MAX_SEARCHES:
        raise HTTPException(
            status_code=422,
            detail=f"{len(searches)} searches (queries x locations) - the limit is {google_maps.MAX_SEARCHES} per run",
        )

    pages = -(-payload.per_search // google_maps.PAGE_SIZE)
    return enqueue_job(db, "google_maps", payload.model_dump(), total=len(searches) * pages,
                       message="Searching Google Maps...")


@router.get("/jobs/{job_id}")
async def get_scrape_job(job_id: str, db: Session = Depends(get_db)):
    """Progress of a background scrape; `result` holds {rows, count, stats} once completed."""
    job = get_job(db, job_id)
    if not job or job.kind not in ("clutch", "awwwards", "google_maps"):
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return to_dict(job)


@router.post("/clutch/run")
async def run_clutch_scraper(payload: ClutchScrapeRequest):
    """
    Scrape Clutch directory listings live and wait for the result (blocking
    variant of POST /clutch/jobs, kept for scripts/CLI-style callers).
    """
    return await _scrape_clutch(payload, _to_filters(payload.filters))


@router.post("/clutch/parse")
async def parse_clutch_pages(
    files: list[UploadFile] = File(...),
    include_sponsored: bool = Form(True),
    require_website: bool = Form(False),
):
    """Parse one or more Clutch directory pages saved from a browser (fallback path)."""
    htmls = []
    for file in files:
        if not file.filename.lower().endswith((".html", ".htm")):
            raise HTTPException(status_code=400, detail=f"{file.filename} is not an HTML file")

        content = await file.read()
        try:
            htmls.append(content.decode("utf-8"))
        except UnicodeDecodeError:
            htmls.append(content.decode("latin-1"))

    rows = parse_files(htmls, ClutchFilters(include_sponsored=include_sponsored, require_website=require_website))

    if not rows:
        raise HTTPException(
            status_code=422,
            detail=(
                "No listings found in the uploaded file(s). Make sure you saved the "
                "fully-rendered page (not the Cloudflare interstitial), or the page "
                "layout changed and scrapers/clutch.py's selectors need updating."
            ),
        )

    return {"rows": rows, "count": len(rows)}


@router.post("/awwwards/run")
async def run_awwwards_scraper(payload: AwwwardsScrapeRequest):
    """Scrape Awwwards and wait for the result (blocking variant of POST /awwwards/jobs)."""
    return await _scrape_awwwards(payload, _awwwards_filters(payload))
