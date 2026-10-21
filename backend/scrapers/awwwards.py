"""
Awwwards.com directory scraper.

Pulls studios and freelancers from the Awwwards directory
(https://www.awwwards.com/directory/) - name, website, country, PRO status
and award counts (Honorable Mentions, Sites of the Day/Month/Year) - and can
optionally visit each profile page for city, budget, languages, social links,
a short bio and the date of their most recent award.

USAGE:
    python scrapers/awwwards.py                          # whole directory, 2 pages
    python scrapers/awwwards.py --listing web-design ux-ui --pages 3
    python scrapers/awwwards.py --listing "United States" --min-sotd 3 --pro-only
    python scrapers/awwwards.py --listing agency-studio --country "United Kingdom" \\
        --with-profiles --active-within-months 12

NOTES:
- Unlike Clutch there's no bot-check here, so this is plain HTTP (httpx) -
  no browser window, and fast. Delays between requests are still kept so
  this stays a polite, infrequent visitor.
- Each directory listing is a single path filter: /directory/<service>/,
  /directory/<type>/, /directory/<Country>/ or /directory/<budget>/.
  Awwwards only combines filters through /directory/search/?..., which its
  robots.txt disallows, so this scraper never uses it. Instead, pick one
  listing to browse (e.g. a service) and narrow it with the local filters
  (country, awards, PRO, ...), which use data shown on every card.
- Listings are ordered by awards, most-awarded first, 24 cards per page.
  Awwwards doesn't show a last page number; pages past the end return 404.
- Profile enrichment is one extra request per company, so it's off by
  default and capped (MAX_PROFILES).
- Selectors were confirmed against the live site (Oct 2026). If nothing is
  scraped, inspect a directory card and adjust the *_SELECTOR constants.
- Respect Awwwards' Terms of Service: use this for your own outreach
  research at a slow, reasonable pace, not for republishing their data.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

AWWWARDS_ROOT = "https://www.awwwards.com"
DIRECTORY_URL = f"{AWWWARDS_ROOT}/directory/"

# One listing = one path filter on /directory/. (slug, label) pairs.
SERVICE_LISTINGS = [
    ("web-design", "Web Design"),
    ("web-development", "Web Development"),
    ("ux-ui", "UX / UI"),
    ("interactive", "Interactive"),
    ("art-direction", "Art Direction"),
    ("graphic-design", "Graphic Design"),
    ("app-development", "App Development"),
    ("social-media", "Social Media"),
    ("seo-sem", "SEO / SEM"),
    ("other", "Other"),
]
TYPE_LISTINGS = [
    ("agency-studio", "Agency & Studio"),
    ("freelance", "Freelance"),
    ("international", "International"),
]
BUDGET_LISTINGS = [
    ("less_than_five_thousand", "Under $5,000"),
    ("five_thirty_thousand", "$5,000 - $30,000"),
    ("over_thirty_thousand", "$30,000 - $50,000"),
    ("fifty_to_hundred_thousand", "$50,000 - $100,000"),
    ("over_hundred_thousand", "Over $100,000"),
]
# Ordered by number of listed studios (as Awwwards orders its own filter).
COUNTRIES = [
    "United States", "United Kingdom", "France", "Canada", "Italy", "Netherlands",
    "Australia", "Spain", "Germany", "Japan", "India", "Poland", "Ukraine", "Brazil",
    "Denmark", "Switzerland", "United Arab Emirates", "Austria", "Greece", "Serbia",
    "South Africa", "Belgium", "New Zealand", "Portugal", "Israel", "Turkey",
    "Argentina", "Mexico", "Sweden", "Croatia", "Indonesia", "Czech Republic",
    "Iceland", "South Korea", "Colombia", "Russia", "Bulgaria", "Malaysia",
    "Singapore", "Uruguay", "Vietnam", "Cyprus", "Finland", "Ireland", "Norway",
    "Saudi Arabia", "Slovakia", "Thailand", "China", "Georgia", "Hong Kong - Macau",
    "Romania", "Slovenia", "Sri Lanka", "Bangladesh", "Chile", "Estonia", "Kenya",
    "Lithuania", "Luxembourg", "Qatar", "Venezuela", "Algeria", "Armenia", "Bolivia",
    "Cameroon", "Cayman Islands", "Congo", "Hungary", "Isle of Man", "Kosovo",
    "Latvia", "Lebanon", "Malta", "Mongolia", "Montenegro", "Nepal", "Pakistan",
    "Peru", "Réunion", "Togo", "Uzbekistan",
]

LISTING_GROUPS: dict[str, list[tuple[str, str]]] = {
    "All": [("", "Whole directory")],
    "Service": SERVICE_LISTINGS,
    "Type": TYPE_LISTINGS,
    "Budget": BUDGET_LISTINGS,
    "Country": [(c, c) for c in COUNTRIES],
}
ALL_LISTINGS = {slug: label for group in LISTING_GROUPS.values() for slug, label in group}

AWARD_KEYS = {"HM": "honorable_mentions", "SOTD": "sotd", "SOTM": "sotm", "SOTY": "soty"}

CSV_FIELDS = [
    "name", "website", "location", "city", "pro", "honorable_mentions", "sotd", "sotm",
    "soty", "total_awards", "works", "budget", "languages", "open_to", "status",
    "last_award_date", "linkedin", "instagram", "twitter", "bio", "profile_url", "listing",
]

MAX_PAGES = 10
MAX_PROFILES = 300
CARDS_PER_PAGE = 24
DELAY_RANGE = (1.5, 3.0)          # between directory pages
PROFILE_DELAY_RANGE = (0.8, 1.6)  # between profile pages
REQUEST_TIMEOUT = 20.0
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "imports" / "awwwards_leads.csv"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Selectors, confirmed against the live site - adjust if Awwwards' markup changes.
CARD_SELECTOR = ".card-directory"
NAME_SELECTOR = ".avatar-name__name strong"
PROFILE_LINK_SELECTOR = "a.avatar-name__link"
PRO_SELECTOR = ".avatar-name__name sup"
CARD_FIELD_SELECTOR = ".card-directory__list > li"
CARD_FIELD_LABEL_SELECTOR = ".card-directory__section"
SCORE_SELECTOR = ".box-score"
PROFILE_SUBTITLE_SELECTOR = ".head-user-pro__subtitle"
PROFILE_STATS_SELECTOR = "table.tb-stats"
PROFILE_BIO_SELECTOR = ".head-user-pro p.heading-6, p.heading-6"
PROFILE_SOCIAL_SELECTOR = "a.button--circle--outline[href]"
PROFILE_WEBSITE_SELECTOR = "a.toolbar-bts__item[href]"
AWARD_DATE_RE = re.compile(r"\b([A-Z][a-z]{2} \d{2}, \d{4})\b")


@dataclass
class AwwwardsFilters:
    """Local filters - applied to card (and, if fetched, profile) data."""
    countries: list[str] = field(default_factory=list)
    min_total_awards: int = 0
    min_sotd: int = 0
    pro_only: bool = False
    require_website: bool = True
    with_profiles: bool = False
    active_within_months: int = 0  # needs with_profiles
    max_results: int = 0           # 0 = no cap


def listing_url(slug: str, page_num: int = 1) -> str:
    base = f"{DIRECTORY_URL}{quote(slug)}/" if slug else DIRECTORY_URL
    return base if page_num <= 1 else f"{base}?page={page_num}"


def listing_label(slug: str) -> str:
    return ALL_LISTINGS.get(slug, slug or "Whole directory")


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def _int(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else 0


def _absolute(href: str) -> str:
    if not href:
        return ""
    return href if href.startswith("http") else f"{AWWWARDS_ROOT}{href}"


def parse_cards(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for card in soup.select(CARD_SELECTOR):
        link = card.select_one(PROFILE_LINK_SELECTOR)
        row = {
            "name": _text(card.select_one(NAME_SELECTOR)),
            "profile_url": _absolute(link.get("href", "")) if link else "",
            "pro": card.select_one(PRO_SELECTOR) is not None,
            "website": "",
            "location": "",
            **{key: 0 for key in AWARD_KEYS.values()},
        }

        for item in card.select(CARD_FIELD_SELECTOR):
            label = _text(item.select_one(CARD_FIELD_LABEL_SELECTOR)).lower()
            if label == "location":
                value = item.find_all("div", recursive=False)
                row["location"] = _text(value[-1]) if value else ""
            elif label == "website":
                a = item.select_one("a[href]")
                row["website"] = a["href"].strip() if a else ""
            elif label == "awards":
                for box in item.select(SCORE_SELECTOR):
                    key = AWARD_KEYS.get(_text(box.select_one(".box-score__top")).upper())
                    if key:
                        row[key] = _int(_text(box.select_one(".box-score__bottom")))

        row["total_awards"] = sum(row[k] for k in AWARD_KEYS.values())
        if row["name"]:
            rows.append(row)
    return rows


def parse_html(html: str) -> list[dict]:
    return parse_cards(BeautifulSoup(html, "html.parser"))


def parse_profile(html: str) -> dict:
    """Extra details from a studio's profile page (/<slug>/)."""
    soup = BeautifulSoup(html, "html.parser")
    info: dict = {}

    subtitle = _text(soup.select_one(PROFILE_SUBTITLE_SELECTOR))  # "Canada - Montréal"
    if " - " in subtitle:
        info["city"] = subtitle.split(" - ", 1)[1].strip()

    # Two stat tables: Works/SOTY/SOTM/SOTD/HM, then Languages/Status/Budget/Open to
    for table in soup.select(PROFILE_STATS_SELECTOR):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [_text(th).lower() for th in rows[0].find_all("th")]
        # "English , French" -> "English, French", but leave "$100,000" alone
        values = [re.sub(r"\s*,\s*(?=[^\d\s])", ", ", _text(td)) for td in rows[1].find_all("td")]
        for header, value in zip(headers, values):
            if value.lower() == "not specified":
                continue
            if header == "works":
                info["works"] = _int(value)
            elif header in ("languages", "status", "budget"):
                info[header] = value
            elif header == "open to":
                info["open_to"] = value

    bio = soup.select_one(PROFILE_BIO_SELECTOR)
    if bio:
        info["bio"] = _text(bio)[:500]

    for a in soup.select(PROFILE_SOCIAL_SELECTOR):
        host = urlparse(a["href"]).netloc.lower()
        for network in ("linkedin", "instagram", "twitter", "x.com"):
            if network in host:
                info["twitter" if network == "x.com" else network] = a["href"]

    website = soup.select_one(PROFILE_WEBSITE_SELECTOR)
    if website:
        info["website"] = website["href"].strip()

    # Works are listed newest first, each with its award date
    dates = []
    for match in AWARD_DATE_RE.findall(soup.get_text(" ", strip=True)):
        try:
            dates.append(datetime.strptime(match, "%b %d, %Y"))
        except ValueError:
            continue
    if dates:
        info["last_award_date"] = max(dates).date().isoformat()

    return info


def passes_card_filters(row: dict, filters: AwwwardsFilters) -> bool:
    if filters.countries and row.get("location") not in filters.countries:
        return False
    if filters.min_total_awards and row.get("total_awards", 0) < filters.min_total_awards:
        return False
    if filters.min_sotd and row.get("sotd", 0) < filters.min_sotd:
        return False
    if filters.pro_only and not row.get("pro"):
        return False
    if filters.require_website and not row.get("website"):
        return False
    return True


def passes_profile_filters(row: dict, filters: AwwwardsFilters, today: Optional[datetime] = None) -> bool:
    if not filters.active_within_months:
        return True
    last = row.get("last_award_date")
    if not last:
        return False
    today = today or datetime.now()
    months = (today.year - int(last[:4])) * 12 + (today.month - int(last[5:7]))
    return months <= filters.active_within_months


def _print_progress(message: str, done: Optional[int] = None, total: Optional[int] = None) -> None:
    print(message)


async def _fetch(client, url: str) -> tuple[int, str]:
    try:
        resp = await client.get(url)
        return resp.status_code, resp.text
    except Exception as exc:
        print(f"  Failed to load {url}: {exc}")
        return 0, ""


async def scrape_live(
    listings: list[str] | str,
    pages_per_listing: int = 2,
    filters: Optional[AwwwardsFilters] = None,
    on_progress: Optional[Callable[..., None]] = None,
) -> dict:
    """
    Fetch directory listings (slugs from LISTING_GROUPS, "" = whole directory),
    apply local filters, and optionally enrich survivors from their profile
    pages. Studios found in several listings are merged.

    on_progress(message, done=None, total=None) gets log lines plus requests
    done vs. requests still planned (directory pages, then profile pages).

    Returns {"rows": [...], "stats": [per-listing summary]}.
    """
    import httpx

    if isinstance(listings, str):
        listings = [listings]
    filters = filters or AwwwardsFilters()
    log = on_progress or _print_progress
    planned = len(listings) * pages_per_listing
    done = 0

    rows: dict[str, dict] = {}
    stats: list[dict] = []

    def matching() -> list[dict]:
        return [r for r in rows.values() if passes_card_filters(r, filters)]

    def is_full() -> bool:
        # With an activity filter some rows get dropped after enrichment, so
        # don't stop paging early on the card-level count alone.
        return bool(filters.max_results) and not filters.active_within_months and len(matching()) >= filters.max_results

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
        for index, slug in enumerate(listings):
            label = listing_label(slug)
            stat = {"category": label, "url": listing_url(slug), "pages_fetched": 0,
                    "listings": 0, "new": 0, "total_available": None, "error": None}
            stats.append(stat)

            attempted = 0
            for page_num in range(1, pages_per_listing + 1):
                if is_full():
                    break
                url = listing_url(slug, page_num)
                log(f"Fetching {url}")
                attempted += 1
                status, html = await _fetch(client, url)
                done += 1
                log(f"{label}: read page {page_num}", done=done, total=planned)
                if status == 404:
                    if page_num == 1:
                        stat["error"] = "Listing not found"
                    break
                if status != 200:
                    stat["error"] = f"HTTP {status or 'error'} on page {page_num}"
                    break

                cards = parse_html(html)
                if not cards:
                    if page_num == 1:
                        stat["error"] = "No studios found - the page layout may have changed"
                    break

                new = 0
                for card in cards:
                    key = card["profile_url"] or card["website"] or card["name"]
                    if key in rows:
                        if label not in rows[key]["listing"].split(", "):
                            rows[key]["listing"] += f", {label}"
                        continue
                    rows[key] = {**card, "listing": label}
                    new += 1

                stat["pages_fetched"] += 1
                stat["listings"] += len(cards)
                stat["new"] += new
                log(f"  Got {len(cards)} studios ({new} new, {len(matching())} matching filters)")
                log(f"{label}: page {page_num} - {len(matching())} studios so far", done=done, total=planned)

                if len(cards) < CARDS_PER_PAGE:
                    break  # last page
                if page_num < pages_per_listing:
                    await asyncio.sleep(random.uniform(*DELAY_RANGE))

            planned -= pages_per_listing - attempted
            if is_full():
                log(f"Reached the {filters.max_results}-result cap, stopping.")
                break
            if index < len(listings) - 1:
                await asyncio.sleep(random.uniform(*DELAY_RANGE))

        results = matching()

        if filters.with_profiles:
            to_enrich = results[: filters.max_results or MAX_PROFILES][:MAX_PROFILES]
            planned = done + len(to_enrich)
            log(f"Fetching {len(to_enrich)} profile pages...", done=done, total=planned)
            for i, row in enumerate(to_enrich):
                done += 1
                if not row["profile_url"]:
                    continue
                status, html = await _fetch(client, row["profile_url"])
                log(f"Profile details: {i + 1} of {len(to_enrich)}", done=done, total=planned)
                if status == 200:
                    info = parse_profile(html)
                    if row["website"]:
                        info.pop("website", None)  # card's link is already the real site
                    row.update(info)
                if i < len(to_enrich) - 1:
                    await asyncio.sleep(random.uniform(*PROFILE_DELAY_RANGE))
            results = [r for r in to_enrich if passes_profile_filters(r, filters)]

    if filters.max_results:
        results = results[: filters.max_results]
    return {"rows": results, "stats": stats}


def write_csv(rows: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resolve_listing(value: str) -> str:
    """Accept a slug ('web-design'), a label ('Web Design') or a country name."""
    if value.lower() in ("all", "directory", ""):
        return ""
    for slug, label in ALL_LISTINGS.items():
        if value.lower() in (slug.lower(), label.lower()):
            return slug
    return value


def main():
    parser = argparse.ArgumentParser(description="Pull studios and freelancers from the Awwwards directory.")
    parser.add_argument(
        "--listing", nargs="+", metavar="NAME", default=[""],
        help="Listings to browse: a service (web-design), type (agency-studio), "
             "budget (over_hundred_thousand) or country ('United States'). Default: whole directory.",
    )
    parser.add_argument("--pages", type=int, default=2, help=f"Pages per listing ({CARDS_PER_PAGE} studios each)")
    parser.add_argument("--country", nargs="+", default=[], help="Only keep studios in these countries")
    parser.add_argument("--min-awards", type=int, default=0, help="Minimum total awards")
    parser.add_argument("--min-sotd", type=int, default=0, help="Minimum Sites of the Day")
    parser.add_argument("--pro-only", action="store_true")
    parser.add_argument("--allow-no-website", action="store_true")
    parser.add_argument("--with-profiles", action="store_true", help="Visit each profile for city, budget, socials, bio")
    parser.add_argument("--active-within-months", type=int, default=0, help="Needs --with-profiles")
    parser.add_argument("--max-results", type=int, default=0)
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="CSV output path")
    args = parser.parse_args()

    filters = AwwwardsFilters(
        countries=args.country, min_total_awards=args.min_awards, min_sotd=args.min_sotd,
        pro_only=args.pro_only, require_website=not args.allow_no_website,
        with_profiles=args.with_profiles or bool(args.active_within_months),
        active_within_months=args.active_within_months, max_results=args.max_results,
    )
    listings = [_resolve_listing(v) for v in args.listing]
    rows = asyncio.run(scrape_live(listings, args.pages, filters))["rows"]

    if not rows:
        print("No studios matched. Try loosening the filters or adding pages.")
        return

    write_csv(rows, Path(args.output))
    print(f"\nDone. Saved {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
