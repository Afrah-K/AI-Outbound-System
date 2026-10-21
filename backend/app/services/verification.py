"""
List verification: catch bounce-risk emails before they ever reach a
campaign, drop generic role addresses when a personal one exists for the
same company, and tag each lead with a rough outreach segment.

Bounce rates above ~3% start damaging a sending domain's reputation, so
this is meant to run right after enrichment (Scraper -> Enricher ->
Verifier) and before a list is used in a campaign.

What "verify" means here: syntax validation plus a DNS/MX deliverability
check (does the domain exist and accept mail) via the email-validator
package. It does NOT do a live SMTP mailbox probe (connecting to the mail
server and issuing RCPT TO) - that requires specialized infrastructure to
do reliably, gets many sending IPs blocked/rate-limited by receiving
servers, and dedicated verification services (NeverBounce, ZeroBounce,
...) exist specifically because it's hard to do well yourself. This catches
typos, dead domains, and role accounts that don't accept mail - a solid
first-pass filter, not a full "does this mailbox exist" guarantee.
"""
from typing import Optional

from email_validator import EmailNotValidError, validate_email

# Role-based/shared inboxes - dropped only when a personal address exists
# for that company; kept as a fallback when it's the only contact found.
GENERIC_LOCAL_PARTS = {
    "info", "hello", "contact", "support", "sales", "team", "hi",
    "admin", "office", "enquiries", "inquiries", "general", "mail",
}

# Industries that match a design-studio lead, as scraped from Clutch
# categories (see scrapers/clutch.py's DESIGN_CATEGORIES) - anything else
# defaults to "bdr". This is a starting guess, not a hard rule; override it
# per row once you've actually looked at the list.
STUDIO_INDUSTRIES = {
    "digital-design", "branding", "logo-designers", "graphic-designers",
    "ui-ux", "packaging-design",
}


def is_generic_address(email: str) -> bool:
    local = email.split("@")[0].lower()
    return local in GENERIC_LOCAL_PARTS


def guess_segment(industry: Optional[str]) -> str:
    if industry and industry.strip().lower() in STUDIO_INDUSTRIES:
        return "studio"
    return "bdr"


def verify_email(email: str) -> dict:
    """Syntax + DNS/MX deliverability check for one address."""
    try:
        result = validate_email(email, check_deliverability=False)
        normalized = result.normalized
    except EmailNotValidError as exc:
        return {"email": email, "valid_syntax": False, "deliverable": False, "reason": str(exc)}

    try:
        validate_email(normalized, check_deliverability=True)
        return {"email": normalized, "valid_syntax": True, "deliverable": True, "reason": None}
    except EmailNotValidError as exc:
        return {"email": normalized, "valid_syntax": True, "deliverable": False, "reason": str(exc)}
