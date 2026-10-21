"""
Live web crawling for the Personalizer: instead of relying only on the
homepage snippet captured once during enrichment, walk a handful of a
company's own pages (about, services, work, team...) at personalization
time, and pull in recent public mentions of the company from a web search.

No API key required - the search uses DuckDuckGo's plain HTML endpoint.
Both steps are best-effort: any failure (site down, search blocked,
markup changed) degrades to an empty result rather than raising, since a
draft with less context is far better than a failed job.
"""
import asyncio
import re
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Internal links worth following, scored by how likely they are to carry
# content useful for a personalized pitch (what they do, who they serve,
# proof of work) rather than boilerplate (privacy policy, login, careers).
LINK_KEYWORDS = (
    "about", "our-story", "who-we-are",
    "service", "what-we-do", "solutions", "product",
    "work", "portfolio", "case-stud", "project", "client",
    "team", "people",
    "blog", "news", "press", "insight",
)

SKIP_LINK_SUBSTRINGS = (
    "privacy", "terms", "cookie", "login", "signin", "sign-in", "cart",
    "career", "job", ".pdf", ".jpg", ".png", ".svg", "mailto:", "tel:",
    "#", "javascript:",
)

MAX_TEXT_PER_PAGE = 1200
MAX_COMBINED_TEXT = 6000


def _normalize_website(website: str) -> Optional[str]:
    if not website:
        return None
    website = website.strip()
    if not website:
        return None
    if not website.startswith("http"):
        website = f"https://{website}"
    return website.rstrip("/")


async def _fetch(client: httpx.AsyncClient, url: str, timeout: float = 8.0) -> Optional[str]:
    try:
        resp = await client.get(url, timeout=timeout, follow_redirects=True)
        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 200 and "html" in content_type:
            return resp.text
    except httpx.HTTPError as exc:
        logger.debug("crawler.fetch_failed", url=url, error=str(exc))
    return None


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = " ".join(soup.stripped_strings)
    return text[:MAX_TEXT_PER_PAGE]


def _extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()[:120]
    return ""


def _score_link(href: str, text: str) -> int:
    haystack = f"{href} {text}".lower()
    return sum(1 for kw in LINK_KEYWORDS if kw in haystack)


def _find_internal_links(html: str, base_url: str, domain: str, limit: int) -> list:
    soup = BeautifulSoup(html, "lxml")
    scored = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or any(bad in href.lower() for bad in SKIP_LINK_SUBSTRINGS):
            continue

        absolute = urljoin(base_url + "/", href)
        parsed = urlparse(absolute)
        if parsed.netloc.replace("www.", "") != domain:
            continue

        clean = absolute.split("#")[0].rstrip("/")
        if clean in seen or clean == base_url:
            continue
        seen.add(clean)

        score = _score_link(href, a.get_text(" ", strip=True))
        if score > 0:
            scored.append((score, clean))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [url for _, url in scored[:limit]]


async def crawl_company_site(website: str, max_pages: int = 5) -> dict:
    """
    Fetch a company's homepage plus its most relevant internal pages
    (scored by LINK_KEYWORDS), live, at call time.

    Returns {"domain", "pages": [{"url","title","text"}], "combined_text", "error"}.
    """
    base_url = _normalize_website(website)
    result = {"domain": None, "pages": [], "combined_text": "", "error": None}
    if not base_url:
        result["error"] = "No website provided"
        return result

    domain = urlparse(base_url).netloc.replace("www.", "")
    result["domain"] = domain

    async with httpx.AsyncClient(headers=BROWSER_HEADERS) as client:
        home_html = await _fetch(client, base_url)
        if not home_html:
            result["error"] = "Could not reach website"
            return result

        pages = [{"url": base_url, "title": _extract_title(home_html), "text": _extract_text(home_html)}]

        follow_urls = _find_internal_links(home_html, base_url, domain, limit=max_pages - 1)

        semaphore = asyncio.Semaphore(4)

        async def fetch_one(url: str):
            async with semaphore:
                html = await _fetch(client, url)
                if html:
                    return {"url": url, "title": _extract_title(html), "text": _extract_text(html)}
                return None

        fetched = await asyncio.gather(*(fetch_one(u) for u in follow_urls))
        pages.extend(p for p in fetched if p and p["text"])

    result["pages"] = pages
    combined = "\n\n".join(f"[{p['title'] or p['url']}]\n{p['text']}" for p in pages)
    result["combined_text"] = combined[:MAX_COMBINED_TEXT]
    return result


# DuckDuckGo wraps result links as /l/?uddg=<encoded target>&...
def _unwrap_ddg_redirect(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


async def search_web_for_company(company_name: str, exclude_domain: Optional[str] = None, max_results: int = 4) -> list:
    """
    Best-effort public web search for recent mentions of a company
    (press, directory listings, social profiles) via DuckDuckGo's HTML
    endpoint - no API key needed. Returns [] on any failure or block.
    """
    if not company_name or not company_name.strip():
        return []

    try:
        async with httpx.AsyncClient(headers=BROWSER_HEADERS) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": company_name.strip()},
                timeout=8.0,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "lxml")
            mentions = []
            for result in soup.select(".result"):
                title_el = result.select_one(".result__title a")
                snippet_el = result.select_one(".result__snippet")
                if not title_el or not title_el.get("href"):
                    continue

                url = _unwrap_ddg_redirect(title_el["href"])
                domain = urlparse(url).netloc.replace("www.", "")
                if exclude_domain and domain == exclude_domain:
                    continue

                mentions.append({
                    "title": title_el.get_text(" ", strip=True)[:150],
                    "url": url,
                    "snippet": snippet_el.get_text(" ", strip=True)[:300] if snippet_el else "",
                })
                if len(mentions) >= max_results:
                    break

            return mentions
    except Exception as exc:
        logger.debug("crawler.search_failed", company=company_name, error=str(exc))
        return []
