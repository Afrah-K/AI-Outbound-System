"""
Interactive entrypoint for the containerized Clutch scraper.

Asks for a Clutch category (domain/slug or full URL) and how many pages to
pull, then runs it through the same Playwright-based live scraper used by
the app (scrapers/clutch.py - a real Chromium browser, run headless),
saving results to a CSV.

USAGE (from backend/):
    docker build -f scrapers/clutch_scraper/Dockerfile -t clutch-scraper .
    docker run -it -v "$(pwd)/data/imports:/data" clutch-scraper
"""
import asyncio
import sys
from pathlib import Path

from scrapers.clutch import BASE_URL, ClutchFilters, scrape_live, write_csv

OUTPUT_PATH = Path("/data/clutch_leads.csv")


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        return BASE_URL
    if value.startswith("http"):
        return value
    return f"https://clutch.co/agencies/{value}"


def prompt_int(message: str, default: int) -> int:
    raw = input(f"{message} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        print(f"  Not a number, using default ({default}).")
        return default


def prompt_float(message: str, default: float) -> float:
    raw = input(f"{message} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        print(f"  Not a number, using default ({default}).")
        return default


def main():
    print("Clutch Scraper (containerized)\n")

    domain = input(
        "Clutch category - full URL or slug, e.g. digital-design "
        f"[{BASE_URL.rsplit('/', 1)[-1]}]: "
    )
    url = normalize_url(domain)
    pages = prompt_int("Pages to scrape", 1)
    location = input("Location slug, e.g. new-york, london (blank = anywhere): ").strip()
    min_rating = prompt_float("Minimum rating (0 = any)", 0.0)
    filters = ClutchFilters(location=location, min_rating=min_rating)

    print(f"\nScraping {url} ({pages} page{'s' if pages != 1 else ''})...\n")
    rows = asyncio.run(scrape_live(url, pages, filters))["rows"]

    if not rows:
        print("\nNo listings found - check the URL/category, or Clutch may be showing its bot-check.")
        sys.exit(1)

    write_csv(rows, OUTPUT_PATH)

    print(f"\nDone. Saved {len(rows)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
