"""
Clutch.co directory scraper.

Pulls agency name, website, location, rating, review count, pricing,
team size, verification status and service focus from Clutch directory
listing pages (e.g. https://clutch.co/agencies/digital-design).

USAGE:
    python scrapers/clutch.py                      # default: DESIGN_CATEGORY_URLS, page 1 each
    python scrapers/clutch.py --url https://clutch.co/agencies/branding
    python scrapers/clutch.py --url URL1 URL2 URL3 --pages 1
    python scrapers/clutch.py --category ui-ux seo --location new-york \\
        --sort ReviewRating --hourly-rate 50-99 --min-rating 4.8 --min-reviews 5

    Manual-fetch mode is also still available if the live fetch ever stops
    working (see NOTES): save a page from your own browser and parse it
    instead of fetching live:
        python scrapers/clutch.py --html-file page1.html page2.html
        python scrapers/clutch.py --html-dir ./saved_clutch_pages

SETUP:
    Live fetch needs Playwright's Chromium build downloaded once:
        pip install -r requirements.txt
        playwright install chromium

NOTES:
- Clutch fronts these pages with a Cloudflare JS challenge ("Just a
  moment..."). A plain `requests` call gets a 403 and no real HTML - that's
  not a selector problem, there's nothing to select. A real browser passes
  it. Playwright's default headless browser (the stripped-down
  "chromium-headless-shell") gets blocked, but the full Chromium build run
  in its "new" headless mode passes - confirmed by testing both back to
  back (Oct 2026). So this scraper runs full Chromium with no window
  (channel="chromium", headless=True) - nothing is spoofed or faked, it's
  an actual browser rendering the actual page. If that ever starts getting
  blocked, --show-browser (or CLUTCH_SHOW_BROWSER=1) falls back to a
  visible window, which Cloudflare has always let through.
- Every request uses a fresh browser context (new cookie jar/session), not
  a shared one. Confirmed by testing: reusing one context across requests
  got every request after the first blocked with a fresh Cloudflare
  challenge, even with a valid cf_clearance cookie and a 10s+ pause between
  them - it's apparently tied to the session, not just elapsed time. A new
  context per request (same browser process, so still cheap) passed
  reliably in testing, including for ?page=2/3 of the same category.
- Filters (location, sort, hourly rate, budget, industry) are applied by
  Clutch itself via the URL, so fewer pages are needed for a targeted list.
  Sponsored/featured cards ignore those filters, and their website button
  is a paid-click tracking link (ppc.clutch.co) rather than the real site -
  following it would bill the advertiser, so it is never resolved. Those
  rows keep their Clutch profile URL instead, and are excluded by default.
- The page also renders a "Leaders Matrix" block that repeats cards from
  the main list - only the main list (#providers__list) is parsed.
- Because it's a real browser, this is slower and heavier than a plain HTTP
  scraper. The rate-limit delays between requests are kept for the same
  reason as before: be a polite, infrequent visitor, not a way to defeat
  detection.
- Selectors below were confirmed against a live-rendered page (Oct 2026).
  If nothing is scraped, open the page in your browser, right-click a
  listing card -> Inspect, and adjust the *_SELECTOR constants.
- Respect Clutch's Terms of Service: use this for your own outreach research
  at a slow, reasonable pace, not for republishing or reselling their data.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse

from bs4 import BeautifulSoup

CLUTCH_ROOT = "https://clutch.co"
BASE_URL = f"{CLUTCH_ROOT}/agencies/digital-design"  # change category/location as needed

# Directory categories confirmed to load real listings, grouped for the
# frontend's pick list. (label, url) pairs.
CATEGORY_GROUPS: dict[str, list[tuple[str, str]]] = {
    "Design": [
        ("Digital Design", f"{CLUTCH_ROOT}/agencies/digital-design"),
        ("Branding", f"{CLUTCH_ROOT}/agencies/branding"),
        ("Logo Design", f"{CLUTCH_ROOT}/agencies/logo-designers"),
        ("Graphic Design", f"{CLUTCH_ROOT}/agencies/graphic-designers"),
        ("UI/UX Design", f"{CLUTCH_ROOT}/agencies/ui-ux"),
        ("Web Design", f"{CLUTCH_ROOT}/web-designers"),
        ("Product Design", f"{CLUTCH_ROOT}/agencies/product-design"),
        ("Packaging Design", f"{CLUTCH_ROOT}/agencies/packaging-design"),
        ("Creative Agencies", f"{CLUTCH_ROOT}/agencies/creative"),
        ("Video Production", f"{CLUTCH_ROOT}/agencies/video-production"),
    ],
    "Development": [
        ("Web Development", f"{CLUTCH_ROOT}/web-developers"),
        ("Mobile App Development", f"{CLUTCH_ROOT}/app-developers"),
        ("Software Development", f"{CLUTCH_ROOT}/developers"),
        ("AI Development", f"{CLUTCH_ROOT}/developers/artificial-intelligence"),
        ("eCommerce Development", f"{CLUTCH_ROOT}/developers/ecommerce"),
        ("Shopify", f"{CLUTCH_ROOT}/developers/shopify"),
        ("WordPress", f"{CLUTCH_ROOT}/developers/wordpress"),
        ("React Native", f"{CLUTCH_ROOT}/developers/react-native"),
        ("Flutter", f"{CLUTCH_ROOT}/developers/flutter"),
    ],
    "Marketing": [
        ("Digital Marketing", f"{CLUTCH_ROOT}/agencies/digital-marketing"),
        ("SEO", f"{CLUTCH_ROOT}/agencies/seo"),
        ("Social Media Marketing", f"{CLUTCH_ROOT}/agencies/social-media-marketing"),
        ("PPC", f"{CLUTCH_ROOT}/agencies/ppc"),
        ("Content Marketing", f"{CLUTCH_ROOT}/agencies/content-marketing"),
        ("Media Buying", f"{CLUTCH_ROOT}/agencies/media-buying"),
        ("Market Research", f"{CLUTCH_ROOT}/agencies/market-research"),
    ],
    "IT & Business Services": [
        ("IT Services", f"{CLUTCH_ROOT}/it-services"),
        ("Cybersecurity", f"{CLUTCH_ROOT}/it-services/cybersecurity"),
        ("Cloud Consulting", f"{CLUTCH_ROOT}/it-services/cloud"),
        ("Call Centers", f"{CLUTCH_ROOT}/call-centers"),
        ("Accounting", f"{CLUTCH_ROOT}/accounting"),
    ],
}

# Kept for callers that only want the original design set (CLI default).
DESIGN_CATEGORIES = CATEGORY_GROUPS["Design"][:5]
DESIGN_CATEGORY_URLS = [url for _, url in DESIGN_CATEGORIES]
ALL_CATEGORIES = [item for group in CATEGORY_GROUPS.values() for item in group]

# Filter values exactly as Clutch's own filter form submits them.
SORT_OPTIONS = [
    ("", "Default (Clutch's order)"),
    ("ClutchRank", "Clutch Rank"),
    ("ReviewRating", "Review Rating"),
    ("NumberOfReviews", "Number of Reviews"),
    ("Verification", "Verified first"),
    ("CompanyName", "Company Name"),
]
HOURLY_RATE_OPTIONS = [
    ("", "Any rate"),
    ("0-25", "< $25/hr"),
    ("25-49", "$25 - $49/hr"),
    ("50-99", "$50 - $99/hr"),
    ("100-149", "$100 - $149/hr"),
    ("150-199", "$150 - $199/hr"),
    ("200-300", "$200 - $300/hr"),
    ("300", "$300+/hr"),
]
BUDGET_OPTIONS = [
    ("", "Any budget"),
    ("5000", "Under $5,000"),
    ("10000", "Under $10,000"),
    ("25000", "Under $25,000"),
    ("50000", "Under $50,000"),
    ("75000", "Under $75,000"),
    ("100000", "Under $100,000"),
    ("250000", "Under $250,000"),
]
INDUSTRY_OPTIONS = [
    ("", "Any industry"),
    ("field_pp_if_advertising", "Advertising & marketing"),
    ("field_pp_if_arts", "Arts, entertainment & music"),
    ("field_pp_if_automotive", "Automotive"),
    ("field_pp_if_beauty", "Beauty"),
    ("field_pp_if_bizservices", "Business services"),
    ("field_pp_if_construction", "Construction"),
    ("field_pp_if_conproducts", "Consumer products & services"),
    ("field_pp_if_dental", "Dental"),
    ("field_pp_if_ecommerce", "eCommerce"),
    ("field_pp_if_education", "Education"),
    ("field_pp_if_natural_resources", "Energy & natural resources"),
    ("field_pp_if_finservices", "Financial services"),
    ("field_pp_if_food_beverage", "Food & Beverage"),
    ("field_pp_if_gaming", "Gaming"),
    ("field_pp_if_government", "Government"),
    ("field_pp_if_home_services", "Home Services"),
    ("field_pp_if_hospitality", "Hospitality & leisure"),
    ("field_pp_if_it", "Information technology"),
    ("field_pp_if_insurance", "Insurance"),
    ("field_pp_if_legal", "Legal"),
    ("field_pp_if_manufacturing", "Manufacturing"),
    ("field_pp_if_media", "Media"),
    ("field_pp_if_healthcare", "Medical"),
    ("field_pp_if_nonprofit", "Non-profit"),
    ("field_pp_if_realestate", "Real estate"),
    ("field_pp_if_retail", "Retail"),
    ("field_pp_if_sports", "Sports"),
    ("field_pp_if_transportation", "Supply chain, logistics & transport"),
    ("field_pp_if_telecom", "Telecommunications"),
]
# Location slugs. US cities are appended to the category path
# (/agencies/ui-ux/new-york); other countries also need a country prefix
# (/uk/agencies/digital-design/london), written here as "uk/london".
# Not every category has a page for every city - Clutch then 404s, or silently
# serves the nationwide list (scrape_live detects both and skips the category).
LOCATION_PRESETS = [
    ("", "Anywhere"),
    ("new-york", "New York City"),
    ("los-angeles", "Los Angeles"),
    ("san-francisco", "San Francisco"),
    ("chicago", "Chicago"),
    ("boston", "Boston"),
    ("miami", "Miami"),
    ("uk/london", "London (UK)"),
    ("ca/toronto", "Toronto (Canada)"),
]

CSV_FIELDS = [
    "name", "website", "location", "rating", "reviews", "min_project_size",
    "hourly_rate", "employees", "verification", "services", "summary",
    "profile_url", "category", "sponsored",
]

MAX_PAGES = 5           # pages per category to pull
DELAY_RANGE = (3, 6)   # seconds between page visits, kept out of politeness, not evasion
PAGE_LOAD_WAIT_MS = 8000  # time to let Cloudflare's challenge clear before reading the page
# Show the browser window instead of running headless - only needed if
# Cloudflare starts blocking headless Chromium (see NOTES).
SHOW_BROWSER = os.environ.get("CLUTCH_SHOW_BROWSER", "").lower() in ("1", "true", "yes")
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "imports" / "clutch_leads.csv"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Selectors, confirmed against a live-rendered page - adjust these if Clutch's
# markup changes and scraping starts returning nothing.
MAIN_LIST_SELECTOR = "#providers__list"  # excludes the duplicate Leaders Matrix block
CARD_SELECTOR = "div.provider-row"
NAME_FALLBACK_SELECTOR = "h3.provider__title a"  # used only if the data-title attr is missing
WEBSITE_SELECTOR = "a.website-link__item"
LOCATION_SELECTOR = ".provider__highlights-item.location"
RATING_SELECTOR = "span.sg-rating__number"
REVIEWS_SELECTOR = "a.sg-rating__reviews"
MIN_PROJECT_SELECTOR = ".provider__highlights-item.min-project-size"
HOURLY_RATE_SELECTOR = ".provider__highlights-item.hourly-rate"
EMPLOYEES_SELECTOR = ".provider__highlights-item.employees-count"
VERIFIED_SELECTOR = ".provider__verified-mark"
SERVICES_SELECTOR = ".provider__services--provided .provider__services-chart-item"
SUMMARY_SELECTOR = ".provider__description-text-more"
PAGINATION_SELECTOR = ".providers-pagination"

SPONSORED_TYPES = {"spotlight", "featured", "sponsor"}
TOP_SERVICES = 3
SUMMARY_MAX_CHARS = 400


@dataclass
class ClutchFilters:
    """
    Run options. The first group is sent to Clutch in the URL; the second is
    applied locally after parsing (Clutch has no URL filter for them, and
    sponsored cards ignore the URL filters anyway).
    """
    location: str = ""
    sort_by: str = ""
    hourly_rate: str = ""
    budget: str = ""
    industry: str = ""

    min_rating: float = 0.0
    min_reviews: int = 0
    verified_only: bool = False
    require_website: bool = False
    include_sponsored: bool = False
    max_results: int = 0  # 0 = no cap

    def url_params(self) -> dict:
        params = {
            "sort_by": self.sort_by,
            "hourly_rate": self.hourly_rate,
            "client_budget": self.budget,
            "industries": self.industry,
        }
        return {k: v for k, v in params.items() if v}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def parse_location(value: str) -> tuple[str, str]:
    """'uk/london' -> ('uk', 'london'); 'New York' -> ('', 'new-york')."""
    country, _, city = (value or "").strip().strip("/").rpartition("/")
    return _slug(country), _slug(city)


def build_page_url(category_url: str, filters: Optional[ClutchFilters] = None, page_num: int = 1) -> str:
    """
    Turn a category URL + filters into the URL Clutch's own filter form would
    produce, e.g. /agencies/ui-ux/new-york?sort_by=ReviewRating&page=2.
    """
    filters = filters or ClutchFilters()
    parsed = urlparse(category_url)
    path = parsed.path.rstrip("/")

    country, city = parse_location(filters.location)
    if city and not path.endswith(f"/{city}"):
        path = f"{path}/{city}"
    if country and not path.startswith(f"/{country}/"):
        path = f"/{country}{path}"

    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    params.update(filters.url_params())
    params.pop("page", None)
    if page_num > 1:
        params["page"] = str(page_num)

    query = f"?{urlencode(params)}" if params else ""
    return f"{parsed.scheme or 'https'}://{parsed.netloc or 'clutch.co'}{path}{query}"


def _extract_real_website(href: str) -> str:
    """
    Clutch wraps outbound links in an analytics redirect - pull the real target
    out of it. Paid-click (ppc.clutch.co) targets aren't the company's site,
    so they come back empty rather than as a tracking link.
    """
    if not href:
        return ""
    target = parse_qs(urlparse(href).query).get("u", [""])[0]
    url = unquote(target).split("?")[0] if target else href
    host = urlparse(url).netloc
    if host.endswith("clutch.co"):
        return ""
    return url


def _text(card, selector: str) -> str:
    el = card.select_one(selector)
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _parse_int(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else 0


def _parse_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _profile_url(card) -> str:
    for a in card.select("a[href]"):
        href = a["href"].strip()
        path = urlparse(href).path if href.startswith("http") else href.split("#")[0]
        if path.startswith("/profile/"):
            return f"{CLUTCH_ROOT}{path}"
    return ""


def _services(card) -> str:
    items = []
    for el in card.select(SERVICES_SELECTOR):
        tip = BeautifulSoup(el.get("data-tooltip-content", ""), "html.parser").get_text(strip=True)
        if tip:
            items.append(tip)
    return ", ".join(items[:TOP_SERVICES])


def parse_cards(soup: BeautifulSoup) -> list[dict]:
    container = soup.select_one(MAIN_LIST_SELECTOR) or soup
    rows = []
    for card in container.select(CARD_SELECTOR):
        name = card.get("data-title", "").strip()
        if not name:
            name = _text(card, NAME_FALLBACK_SELECTOR)

        website_el = card.select_one(WEBSITE_SELECTOR)
        card_type = (card.get("data-type") or "").lower()
        sponsored = card_type in SPONSORED_TYPES or "sponsor" in card.get("class", [])

        location = _text(card, LOCATION_SELECTOR)
        if location.lower().startswith("serves "):
            location = location[len("serves "):]

        summary = _text(card, SUMMARY_SELECTOR)
        if len(summary) > SUMMARY_MAX_CHARS:
            summary = summary[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "..."

        rows.append({
            "clutch_id": card.get("data-clutch-pid") or card.get("data-id") or "",
            "name": name,
            "website": _extract_real_website(website_el.get("href", "")) if website_el else "",
            "location": location,
            "rating": _text(card, RATING_SELECTOR),
            "reviews": _parse_int(_text(card, REVIEWS_SELECTOR)),
            "min_project_size": _text(card, MIN_PROJECT_SELECTOR),
            "hourly_rate": _text(card, HOURLY_RATE_SELECTOR),
            "employees": _text(card, EMPLOYEES_SELECTOR),
            "verification": _text(card, VERIFIED_SELECTOR).split(" Look for")[0],
            "services": _services(card),
            "summary": summary,
            "profile_url": _profile_url(card),
            "sponsored": sponsored,
        })
    return rows


def parse_page_info(soup: BeautifulSoup) -> dict:
    """Total matching companies and last page number, when the page shows them."""
    total = 0
    for s in soup.find_all(string=re.compile(r"^\s*[\d,]+\s+Companies\s*$")):
        total = _parse_int(s)
        break

    last_page = 1
    pagination = soup.select_one(PAGINATION_SELECTOR)
    if pagination:
        for a in pagination.select("a[href]"):
            page = parse_qs(urlparse(a["href"]).query).get("page", ["0"])[0]
            if page.isdigit():
                last_page = max(last_page, int(page))
    return {"total": total, "last_page": last_page}


def location_mismatch(soup: BeautifulSoup, filters: ClutchFilters) -> Optional[str]:
    """
    When a category has no page for the requested city, Clutch either 404s
    or quietly serves the nationwide list. The canonical URL shows which one
    we actually got.
    """
    _, city = parse_location(filters.location)
    if not city:
        return None
    title = soup.title.get_text(strip=True) if soup.title else ""
    if title.startswith("404"):
        return f"Clutch has no '{filters.location}' page for this category"
    canonical = soup.select_one("link[rel=canonical]")
    if canonical and not urlparse(canonical.get("href", "")).path.rstrip("/").endswith(f"/{city}"):
        return f"Clutch has no '{filters.location}' page for this category (it served nationwide results)"
    return None


def parse_html(html: str) -> list[dict]:
    """Parse a saved (or otherwise already-fetched) Clutch page's HTML."""
    return parse_cards(BeautifulSoup(html, "html.parser"))


def parse_html_file(path: Path) -> list[dict]:
    return parse_html(path.read_text(encoding="utf-8", errors="replace"))


def passes_filters(row: dict, filters: ClutchFilters) -> bool:
    if row.get("sponsored") and not filters.include_sponsored:
        return False
    if filters.min_rating and _parse_float(row.get("rating")) < filters.min_rating:
        return False
    if filters.min_reviews and int(row.get("reviews") or 0) < filters.min_reviews:
        return False
    if filters.verified_only and not row.get("verification"):
        return False
    if filters.require_website and not row.get("website"):
        return False
    return True


class RowCollector:
    """
    Dedupes companies across pages and categories by Clutch ID. If a company
    shows up both as a sponsored card (no real website) and an organic one,
    the organic row wins.
    """

    def __init__(self, filters: ClutchFilters):
        self.filters = filters
        self._rows: dict[str, dict] = {}

    def add(self, rows: list[dict], category: str = "") -> int:
        added = 0
        for row in rows:
            row = {**row, "category": row.get("category") or category}
            key = row["clutch_id"] or row["website"] or row["name"]
            if not key:
                continue
            existing = self._rows.get(key)
            if existing:
                categories = existing["category"].split(", ") if existing["category"] else []
                if row["category"] and row["category"] not in categories:
                    categories.append(row["category"])
                if existing["sponsored"] and not row["sponsored"]:
                    self._rows[key] = existing = row
                existing["category"] = ", ".join(categories)
                continue
            self._rows[key] = row
            added += 1
        return added

    def results(self) -> list[dict]:
        rows = [r for r in self._rows.values() if passes_filters(r, self.filters)]
        if self.filters.max_results:
            rows = rows[: self.filters.max_results]
        return rows

    def is_full(self) -> bool:
        return bool(self.filters.max_results) and len(self.results()) >= self.filters.max_results


def parse_files(htmls: list[str], filters: Optional[ClutchFilters] = None) -> list[dict]:
    """Parse several saved pages with the same dedupe + filtering as a live run."""
    collector = RowCollector(filters or ClutchFilters(include_sponsored=True))
    for html in htmls:
        collector.add(parse_html(html))
    return collector.results()


def _print_progress(message: str, done: Optional[int] = None, total: Optional[int] = None) -> None:
    print(message)


def _is_challenge_page(html: str) -> bool:
    return "Just a moment" in html and "cloudflare" in html.lower()


def page_has_listings(html: str) -> bool:
    return "provider-row" in html


async def _settled_content(page, attempts: int = 3) -> str:
    """
    page.content() throws if the page is mid-navigation (Cloudflare's
    challenge redirecting to the real page, or a category URL that Clutch
    redirects elsewhere) - wait for the new page to load and try again.
    """
    for attempt in range(attempts):
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            return await page.content()
        except Exception:
            if attempt == attempts - 1:
                raise
            await page.wait_for_timeout(2000)
    return ""


async def _fetch_rendered_html(browser, url: str, retry_wait_ms: int = 5000) -> str | None:
    """
    Load a page in a fresh browser context and return its rendered HTML.

    A NEW context per request matters, not just a new tab: reusing one
    context across requests got every request after the first blocked, even
    with a valid cf_clearance cookie and long pauses between them. A fresh
    context (same browser process, new cookie jar/session) passes every
    time - confirmed by testing both back to back.
    """
    context = await browser.new_context(user_agent=USER_AGENT)
    try:
        page = await context.new_page()
        await page.goto(url, timeout=30000)
        await page.wait_for_timeout(PAGE_LOAD_WAIT_MS)
        html = await _settled_content(page)

        # The challenge is time-based (auto-resolving JS), not interactive - if it's
        # still showing (or the page was mid-redirect), waiting a bit longer usually
        # clears it rather than retrying blind.
        if _is_challenge_page(html) or not page_has_listings(html):
            await page.wait_for_timeout(retry_wait_ms)
            html = await _settled_content(page)
    except Exception as exc:
        print(f"  Failed to load {url}: {exc}")
        return None
    finally:
        await context.close()

    if _is_challenge_page(html):
        print(f"  Still showing Cloudflare's challenge for {url}")
        return None

    return html


def _category_label(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    known = {urlparse(cat_url).path.rstrip("/"): label for label, cat_url in ALL_CATEGORIES}
    # Also match a known category with a location suffix, e.g. /agencies/ui-ux/new-york
    for candidate in (path, path.rsplit("/", 1)[0]):
        if candidate in known:
            return known[candidate]
    return path.rsplit("/", 1)[-1].replace("-", " ").title()


async def scrape_live(
    urls: list[str] | str,
    pages_per_url: int = 1,
    filters: Optional[ClutchFilters] = None,
    on_progress: Optional[Callable[..., None]] = None,
    show_browser: Optional[bool] = None,
) -> dict:
    """
    Fetch and parse Clutch listings from one or more category URLs using a
    real Chromium browser (headless unless show_browser) - a fresh browser
    context per request
    (see _fetch_rendered_html). Filters are applied via Clutch's URL params
    where possible and locally otherwise; companies that show up in more
    than one category are merged.

    on_progress(message, done=None, total=None) is called with log lines and,
    after each page, pages fetched so far vs. pages still planned (the plan
    shrinks when a category runs out of pages early).

    Returns {"rows": [...], "stats": [per-category summary]}.
    """
    from playwright.async_api import async_playwright

    if isinstance(urls, str):
        urls = [urls]
    filters = filters or ClutchFilters()
    log = on_progress or _print_progress
    planned = len(urls) * pages_per_url
    done = 0

    collector = RowCollector(filters)
    stats: list[dict] = []

    async with async_playwright() as p:
        headed = SHOW_BROWSER if show_browser is None else show_browser
        # channel="chromium" = the full browser in new headless mode, not the
        # headless shell that Cloudflare blocks (see NOTES)
        browser = await p.chromium.launch(headless=not headed, channel="chromium")
        try:
            for url_index, url in enumerate(urls):
                category = _category_label(url)
                stat = {"category": category, "url": build_page_url(url, filters), "pages_fetched": 0,
                        "listings": 0, "new": 0, "total_available": None, "error": None}
                stats.append(stat)
                last_page = pages_per_url
                attempted = 0

                for page_num in range(1, pages_per_url + 1):
                    if page_num > last_page or collector.is_full():
                        break
                    page_url = build_page_url(url, filters, page_num)
                    log(f"Fetching {page_url}")

                    attempted += 1
                    html = await _fetch_rendered_html(browser, page_url)
                    done += 1
                    log(f"{category}: read page {page_num}", done=done, total=planned)
                    if html is None:
                        stat["error"] = "Blocked by Cloudflare or failed to load"
                        break

                    soup = BeautifulSoup(html, "html.parser")
                    if page_num == 1:
                        mismatch = location_mismatch(soup, filters)
                        if mismatch:
                            stat["error"] = mismatch
                            log(f"  {mismatch} - skipping.")
                            break
                    rows = parse_cards(soup)
                    if page_num == 1:
                        info = parse_page_info(soup)
                        stat["total_available"] = info["total"] or None
                        last_page = min(pages_per_url, info["last_page"])
                    if not rows:
                        if page_num == 1:
                            stat["error"] = "No listings - check the category/location, or selectors need updating"
                        log("  No cards found -- last page, or selectors need updating.")
                        break

                    new = collector.add(rows, category)
                    stat["pages_fetched"] += 1
                    stat["listings"] += len(rows)
                    stat["new"] += new
                    log(f"  Got {len(rows)} listings ({new} new, {len(collector.results())} matching filters)")
                    log(f"{category}: page {page_num} - {len(collector.results())} leads so far", done=done, total=planned)

                    if page_num < last_page:
                        await asyncio.sleep(random.uniform(*DELAY_RANGE))

                planned -= pages_per_url - attempted
                log(f"Finished {category}", done=done, total=planned)
                if collector.is_full():
                    log(f"Reached the {filters.max_results}-result cap, stopping.")
                    break
                if url_index < len(urls) - 1:
                    await asyncio.sleep(random.uniform(*DELAY_RANGE))
        finally:
            await browser.close()

    return {"rows": collector.results(), "stats": stats}


def _resolve_category(value: str) -> str:
    """Accept a full URL, a known label, or a path slug like 'ui-ux' / 'web-developers'."""
    if value.startswith("http"):
        return value
    for label, url in ALL_CATEGORIES:
        path = urlparse(url).path.strip("/")
        if value.lower() in (label.lower(), path, path.rsplit("/", 1)[-1]):
            return url
    return f"{CLUTCH_ROOT}/agencies/{value.strip('/')}"


def write_csv(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Pull agencies from Clutch directory listings.")
    parser.add_argument(
        "--url", nargs="+", metavar="URL", default=None,
        help=f"One or more Clutch directory URLs (live fetch). Default: {len(DESIGN_CATEGORY_URLS)} design categories.",
    )
    parser.add_argument(
        "--category", nargs="+", metavar="NAME",
        help="Category labels or slugs instead of full URLs, e.g. ui-ux branding web-developers",
    )
    parser.add_argument("--pages", type=int, default=MAX_PAGES, help="Pages per category (live fetch)")
    parser.add_argument("--location", default="", help="City/region slug, e.g. new-york, london")
    parser.add_argument("--sort", default="", choices=[v for v, _ in SORT_OPTIONS], help="Clutch sort order")
    parser.add_argument("--hourly-rate", default="", choices=[v for v, _ in HOURLY_RATE_OPTIONS])
    parser.add_argument("--budget", default="", choices=[v for v, _ in BUDGET_OPTIONS], help="Max client budget")
    parser.add_argument("--industry", default="", choices=[v for v, _ in INDUSTRY_OPTIONS], help="Industry focus")
    parser.add_argument("--min-rating", type=float, default=0.0)
    parser.add_argument("--min-reviews", type=int, default=0)
    parser.add_argument("--verified-only", action="store_true")
    parser.add_argument("--require-website", action="store_true")
    parser.add_argument("--include-sponsored", action="store_true")
    parser.add_argument("--max-results", type=int, default=0)
    parser.add_argument(
        "--html-file", nargs="+", metavar="PATH",
        help="Parse one or more saved Clutch page(s) instead of fetching live",
    )
    parser.add_argument(
        "--html-dir", metavar="PATH",
        help="Parse every .html file in this directory instead of fetching live",
    )
    parser.add_argument(
        "--show-browser", action="store_true",
        help="Show the Chromium window instead of running headless (if Cloudflare blocks headless)",
    )
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="CSV output path")
    args = parser.parse_args()

    filters = ClutchFilters(
        location=args.location, sort_by=args.sort, hourly_rate=args.hourly_rate,
        budget=args.budget, industry=args.industry, min_rating=args.min_rating,
        min_reviews=args.min_reviews, verified_only=args.verified_only,
        require_website=args.require_website, include_sponsored=args.include_sponsored,
        max_results=args.max_results,
    )

    if args.html_file or args.html_dir:
        html_paths = [Path(p) for p in (args.html_file or [])]
        if args.html_dir:
            html_paths.extend(sorted(Path(args.html_dir).glob("*.html")))
        for path in html_paths:
            print(f"Parsing {path}")
        all_rows = parse_files([p.read_text(encoding="utf-8", errors="replace") for p in html_paths], filters)
    else:
        urls = args.url or [_resolve_category(c) for c in (args.category or [])] or DESIGN_CATEGORY_URLS
        all_rows = asyncio.run(scrape_live(urls, args.pages, filters, show_browser=args.show_browser or None))["rows"]

    if not all_rows:
        print("No data scraped. Check access to Clutch, the filters, and the page selectors.")
        return

    write_csv(all_rows, Path(args.output))
    print(f"\nDone. Saved {len(all_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
