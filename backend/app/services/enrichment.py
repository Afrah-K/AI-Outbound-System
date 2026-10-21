"""
Company enrichment: scrape a company's website for contact emails and
homepage text, persist the results, and optionally generate an
AI personalization hook from what was scraped.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.config import settings
from app.integrations.scraper.service import find_company_emails
from app.models import Company, LeadStatus, Person
from app.services.jobs import JobRun, job_handler

logger = structlog.get_logger()


UNPICKED_OVER_LIMIT = "over_limit"   # beyond the top max_people for the company
UNPICKED_OFF_DOMAIN = "off_domain"   # not on the company's domain while on-domain ones exist


def load_unpicked(company: Company) -> list[dict]:
    """The company's unpicked emails, minus any that have since become prospects."""
    try:
        items = json.loads(company.unpicked_emails or "[]")
    except ValueError:
        return []
    picked = {p.email.lower() for p in company.people}
    return [i for i in items if i.get("email", "").lower() not in picked]


def save_unpicked(company: Company, items: list[dict]) -> None:
    # Always store a list ("[]" when empty) - NULL means "enriched before
    # unpicked emails were tracked", which the UI offers to re-scan
    company.unpicked_emails = json.dumps(items)


async def enrich_company(company: Company, db: Session, max_people: int = 3, force: bool = False) -> dict:
    """
    Scrape a company's site for emails, store findings, and create Person leads.

    Cached by default: a company already enriched (status completed or
    no_emails_found) returns its existing result instantly instead of
    re-scraping - pass force=True to re-scrape anyway.
    """
    if not force and company.enrichment_status in ("completed", "no_emails_found"):
        existing_emails = [p.email for p in company.people]
        return {
            "company_id": company.id,
            "emails_found": len(existing_emails),
            "emails": existing_emails,
            "emails_created": [],
            "unpicked_emails": load_unpicked(company),
            "unpicked_tracked": company.unpicked_emails is not None,
            "cached": True,
        }

    website = company.website or company.domain
    if not website:
        company.enrichment_status = "failed"
        company.enrichment_error = "No website on file"
        company.last_enriched_at = datetime.utcnow()
        db.commit()
        return {"company_id": company.id, "emails_found": 0, "emails_created": [], "emails": [], "error": company.enrichment_error, "cached": False}

    scrape = await find_company_emails(website)

    company.homepage_text = scrape["homepage_text"] or company.homepage_text
    company.domain = company.domain or scrape["domain"]
    company.last_enriched_at = datetime.utcnow()

    if scrape["error"] and not scrape["emails"]:
        company.enrichment_status = "failed"
        company.enrichment_error = scrape["error"]
        db.commit()
        return {"company_id": company.id, "emails_found": 0, "emails_created": [], "emails": [], "error": scrape["error"], "cached": False}

    found_emails = scrape["emails"][:max_people]
    unpicked = (
        [{"email": e, "reason": UNPICKED_OVER_LIMIT} for e in scrape["emails"][max_people:]]
        + [{"email": e, "reason": UNPICKED_OFF_DOMAIN} for e in scrape.get("other_emails", [])]
    )
    save_unpicked(company, unpicked)
    created = []
    for email in found_emails:
        existing = db.query(Person).filter(Person.email == email).first()
        if existing:
            continue
        person = Person(email=email, company_id=company.id, status=LeadStatus.NEW)
        db.add(person)
        created.append(email)

    company.enrichment_status = "completed" if scrape["emails"] else "no_emails_found"
    company.enrichment_error = None
    db.commit()

    return {
        "company_id": company.id,
        "emails_found": len(scrape["emails"]),
        "emails": found_emails,
        "emails_created": created,
        "unpicked_emails": unpicked,
        "unpicked_tracked": True,
        "cached": False,
    }


async def generate_personalization_hook(company: Company) -> Optional[str]:
    """Ask OpenAI for a one-line, specific cold-email opener based on scraped homepage text."""
    if not settings.openai_api_key or not company.homepage_text:
        return None

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write one concise, specific sentence a salesperson could use to open "
                        "a cold email, referencing something real about this company from the "
                        "text provided. No generic praise, no fluff."
                    ),
                },
                {"role": "user", "content": f"Company: {company.name}\nWebsite text: {company.homepage_text[:2000]}"},
            ],
            max_tokens=80,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("enrichment.ai_hook_failed", company=company.name, error=str(exc))
        return None


@job_handler("enrich")
async def run_enrich_job(job: JobRun, payload: dict) -> list:
    """
    Background job: enrich each company (using the cache in enrich_company)
    and track progress. Companies in payload["force_ids"] are re-scraped regardless.
    Returns the per-company results.
    """
    from app.database import SessionLocal

    company_ids = payload.get("company_ids") or []
    force_ids = set(payload.get("force_ids") or [])
    results, emails_found = [], 0

    db = SessionLocal()
    try:
        for done, company_id in enumerate(company_ids, start=1):
            company = db.query(Company).filter(Company.id == company_id).first()
            if not company:
                job.progress(done=done)
                continue

            try:
                result = await enrich_company(company, db, force=company_id in force_ids)
            except Exception as exc:  # noqa: BLE001 - one bad site mustn't stop the whole list
                logger.warning("enrichment.company_failed", company_id=company_id, error=str(exc))
                db.rollback()
                company.enrichment_status = "failed"
                company.enrichment_error = str(exc)[:500]
                db.commit()
                result = {"emails": [], "error": str(exc)}
            emails_found += len(result.get("emails", []))
            results.append({
                "company_id": company.id,
                "name": company.name,
                "website": company.website,
                "status": company.enrichment_status,
                "emails": result.get("emails", []),
                "unpicked_emails": result.get("unpicked_emails", []),
                "unpicked_tracked": result.get("unpicked_tracked", True),
                "error": result.get("error"),
                "cached": result.get("cached", False),
            })
            job.extra["emails_found"] = emails_found
            job.progress(done=done)
    finally:
        db.close()
    return results
