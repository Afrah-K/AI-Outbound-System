"""
Website scraper for finding public contact emails and homepage text
used to enrich a Company record.
"""
import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import httpx
import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Substrings that show up in scraped "emails" but aren't real contact addresses
# (tracking pixels, CDN asset names, placeholder text, image files, etc.)
EMAIL_BLOCKLIST_SUBSTRINGS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    "sentry.io", "wixpress.com", "example.com", "godaddy.com",
    "schema.org", "w3.org", "yourdomain", "domain.com",
    "email.com", "company.com", "acme.com", "@2x", "@3x",
)

# TLD-shaped suffixes that are really asset/bundler extensions, not real domains
# (e.g. "background@2x.css" or a webpack chunk hash ending in ".zmd")
FAKE_TLDS = {"css", "js", "json", "map", "woff", "woff2", "ttf", "eot", "zmd", "scss"}

# 32/40-char hex strings as the local-part are Cloudflare/CDN obfuscation hashes,
# not real mailboxes
HASH_LOCAL_PART = re.compile(r"^[0-9a-f]{16,40}$")

# Pages likely to list a contact address, checked in order until one yields a hit
CANDIDATE_PATHS = ("", "contact", "contact-us", "about", "about-us", "team")

# Generic inbox aliases, most useful for cold outreach first
PRIORITY_PREFIXES = ("hello", "info", "contact", "hi", "team", "support", "sales")

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadEnricher/1.0)"}


def _looks_like_real_email(email: str) -> bool:
    email = email.lower()
    if any(bad in email for bad in EMAIL_BLOCKLIST_SUBSTRINGS):
        return False

    local, _, domain = email.partition("@")
    if not local or not domain:
        return False
    # Automated senders - nobody reads replies to these
    if re.sub(r"[-_.]", "", local) in ("noreply", "donotreply", "mailerdaemon", "postmaster"):
        return False
    if HASH_LOCAL_PART.match(local):
        return False

    tld = domain.rsplit(".", 1)[-1]
    if tld in FAKE_TLDS:
        return False

    return True


def _normalize_website(website: str) -> Optional[str]:
    if not website:
        return None
    website = website.strip()
    if not website:
        return None
    if not website.startswith("http"):
        website = f"https://{website}"
    return website.rstrip("/")


MAX_REDIRECTS = 5
NON_WEB_REDIRECT_HEADER = "x-non-web-redirect"


async def _stash_non_web_redirect(response: httpx.Response) -> None:
    """
    Response hook: httpx parses every redirect's Location into a URL (even with
    follow_redirects=False) and raises InvalidURL for ones like mailto: - so
    move those out of Location before it gets the chance.
    """
    location = response.headers.get("location", "").strip()
    if location and urlparse(location).scheme.lower() not in ("", "http", "https"):
        response.headers[NON_WEB_REDIRECT_HEADER] = location
        del response.headers["location"]


async def _fetch(client: httpx.AsyncClient, url: str) -> tuple[Optional[str], set]:
    """
    GET a page, following redirects by hand. Returns (html or None, emails).

    Redirects are followed manually because some sites point their /contact
    page straight at a mailto: link (e.g. 301 -> mailto:hello@studio.com) -
    httpx can't follow that and raises InvalidURL, but it's exactly the
    address we're looking for, so it's returned as a found email. Needs a
    client with the _stash_non_web_redirect response hook.
    """
    emails: set = set()
    for _ in range(MAX_REDIRECTS + 1):
        try:
            resp = await client.get(url, timeout=10.0, follow_redirects=False)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            # Any one bad page (timeouts, malformed URLs, ...) just yields nothing
            logger.debug("scraper.fetch_failed", url=url, error=str(exc))
            return None, emails

        non_web = resp.headers.get(NON_WEB_REDIRECT_HEADER, "")
        if non_web:
            if non_web.lower().startswith("mailto:"):
                address = unquote(non_web[len("mailto:"):].split("?")[0]).strip()
                if "@" in address and _looks_like_real_email(address):
                    emails.add(address.lower())
            return None, emails

        if resp.is_redirect:
            location = resp.headers.get("location", "").strip()
            next_url = urljoin(str(resp.url), location)
            if urlparse(next_url).scheme not in ("http", "https"):
                return None, emails
            url = next_url
            continue

        content_type = resp.headers.get("content-type", "")
        if resp.status_code == 200 and "html" in content_type:
            return resp.text, emails
        return None, emails

    logger.debug("scraper.too_many_redirects", url=url)
    return None, emails


def _extract_emails(html: str) -> set:
    emails = set(EMAIL_REGEX.findall(html))

    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            address = href.split(":", 1)[1].split("?")[0].strip()
            if address and "@" in address:
                emails.add(address)

    return {e for e in emails if _looks_like_real_email(e)}


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.stripped_strings)
    return text[:5000]


def rank_emails(emails: set, domain: Optional[str]) -> list:
    """
    Prefer generic inbox aliases (hello@, info@, ...) on the company's own domain.

    If any on-domain address was found, off-domain addresses are dropped entirely -
    those are usually personal emails picked up from a testimonial or comment
    section, not a way to reach the company.
    """
    def is_same_domain(email: str) -> bool:
        return domain is not None and email.lower().endswith(f"@{domain}")

    on_domain = [e for e in emails if is_same_domain(e)]
    candidates = on_domain if on_domain else list(emails)

    def score(email: str):
        local = email.split("@")[0].lower()
        priority = next((i for i, p in enumerate(PRIORITY_PREFIXES) if local == p), len(PRIORITY_PREFIXES))
        return (priority, email)

    return sorted(candidates, key=score)


async def find_company_emails(website: str) -> dict:
    """
    Scrape a company's public website for contact emails and homepage text.

    Checks the homepage first, then a handful of common contact/about/team
    pages, stopping as soon as a page yields an email to keep requests low.
    """
    base_url = _normalize_website(website)
    result = {"emails": [], "other_emails": [], "homepage_text": "", "domain": None, "error": None}
    if not base_url:
        result["error"] = "No website provided"
        return result

    domain = urlparse(base_url).netloc.replace("www.", "")
    result["domain"] = domain

    all_emails: set = set()
    homepage_text = ""
    pages_reached = 0

    async with httpx.AsyncClient(
        headers=REQUEST_HEADERS,
        event_hooks={"response": [_stash_non_web_redirect]},
    ) as client:
        for i, path in enumerate(CANDIDATE_PATHS):
            url = urljoin(base_url + "/", path)
            html, redirect_emails = await _fetch(client, url)
            if redirect_emails:
                # e.g. /contact redirecting to mailto:hello@... - the site reached us
                pages_reached += 1
                all_emails |= redirect_emails
                break
            if not html:
                continue

            pages_reached += 1
            if i == 0:
                homepage_text = _extract_text(html)

            found = _extract_emails(html)
            all_emails |= found
            if found:
                break

    if pages_reached == 0:
        result["error"] = "Could not reach website"

    result["emails"] = rank_emails(all_emails, domain)
    # Off-domain addresses rank_emails left out because on-domain ones exist
    result["other_emails"] = sorted(e for e in all_emails if e not in result["emails"])
    result["homepage_text"] = homepage_text
    return result
