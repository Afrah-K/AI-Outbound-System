"""
AI email personalization: crawl what's publicly available about a company
right now - its own site plus recent web mentions - layer that on top of
whatever's already known from the DB (industry, location, segment,
contact), and have OpenAI draft one specific cold email from it - not a
template with merge fields, an actual email that references real,
current things about the company.

Runs as a background job (see PersonalizeJob) for the same reason
enrichment does: a batch of these is a batch of LLM calls plus a batch of
live crawls, easily past any reasonable request timeout.
"""
import json
import uuid
from dataclasses import dataclass, field
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.config import settings
from app.services.jobs import JobRun, job_handler
from app.models import Company
from app.services.web_crawler import crawl_company_site, search_web_for_company

logger = structlog.get_logger()

SYSTEM_PROMPT = """You write short, specific cold outreach emails.

Rules:
- Reference at least one concrete, specific detail about the recipient's company from the context given - never generic praise ("I love your work", "impressive portfolio"). If nothing specific is available in the context, keep the email short and honest rather than inventing details.
- 3-5 sentences, plain text, no exclamation points, no marketing fluff, no emoji.
- End with a low-friction call to action - a specific question, not "let's hop on a call" or "let me know if you're interested."
- No placeholders like [Name] or [Company] - use the real values given.
- Adjust tone to the segment given: "studio" = peer-to-peer, creative-industry tone; "bdr" = slightly more formal, outcome-focused tone. If no segment is given, use a neutral professional tone.

Respond with a JSON object: {"subject": "...", "body": "..."}
The subject should be short (under 60 characters) and specific, not generic ("Quick question" is fine, "Great opportunity!!!" is not)."""


def _static_lines(name: str, company: Optional[Company] = None, website: str = "", segment: Optional[str] = None) -> list:
    """The cheap, already-known facts about a company - DB fields if there's a matching record, else just what was handed in."""
    lines = [f"Company: {name}"]
    if company:
        if company.industry:
            lines.append(f"Industry/category: {company.industry}")
        if company.location:
            lines.append(f"Location: {company.location}")
        if company.website or website:
            lines.append(f"Website: {company.website or website}")
        if company.size:
            lines.append(f"Size: {company.size}")
        if company.funding_stage:
            lines.append(f"Funding stage: {company.funding_stage}")
    elif website:
        lines.append(f"Website: {website}")
    if segment:
        lines.append(f"Segment: {segment}")
    return lines


def build_company_context(company: Company, segment: Optional[str] = None) -> str:
    """Rich context from a Company already in the DB (scraped/enriched). Kept for callers that don't need a live crawl."""
    lines = _static_lines(company.name, company=company, segment=segment)
    if company.homepage_text:
        lines.append(f"Homepage text (scraped from their site):\n{company.homepage_text[:2000]}")
    return "\n".join(lines)


def build_minimal_context(name: str, website: str = "", segment: Optional[str] = None) -> str:
    """Fallback context for an ad-hoc lead with no matching DB record (no scraped data available)."""
    return "\n".join(_static_lines(name, website=website, segment=segment))


async def build_live_context(
    name: str,
    website: str = "",
    segment: Optional[str] = None,
    company: Optional[Company] = None,
) -> dict:
    """
    Build personalization context by crawling the company's site and
    searching the web for it live, right now - not just whatever was
    cached from a prior enrichment pass.

    Returns {"context": str, "pages_crawled": int, "web_mentions": int, "crawl_error": str|None}.
    """
    lines = _static_lines(name, company=company, website=website, segment=segment)
    effective_website = (company.website if company else None) or website

    pages_crawled = 0
    web_mentions = 0
    crawl_error = None
    crawl_domain = None

    if effective_website:
        crawl = await crawl_company_site(effective_website)
        crawl_domain = crawl.get("domain")
        crawl_error = crawl.get("error")
        if crawl["pages"]:
            pages_crawled = len(crawl["pages"])
            lines.append(f"Their website, crawled live just now ({pages_crawled} pages):\n{crawl['combined_text']}")
        elif company and company.homepage_text:
            # Live crawl failed (site down, blocked) - fall back to whatever was cached from enrichment.
            lines.append(f"Homepage text (scraped from their site):\n{company.homepage_text[:2000]}")

    mentions = await search_web_for_company(name, exclude_domain=crawl_domain)
    if mentions:
        web_mentions = len(mentions)
        mention_lines = "\n".join(f"- {m['title']}: {m['snippet']} ({m['url']})" for m in mentions)
        lines.append(f"Recent public mentions found via web search:\n{mention_lines}")

    return {
        "context": "\n\n".join(lines),
        "pages_crawled": pages_crawled,
        "web_mentions": web_mentions,
        "crawl_error": crawl_error if pages_crawled == 0 else None,
    }


async def generate_personalized_email(
    offer: str,
    context: str,
    contact_name: Optional[str] = None,
) -> dict:
    """Returns {subject, body} on success, or {error} on failure."""
    if not settings.openai_api_key or settings.openai_api_key.startswith("your_"):
        return {"error": "OPENAI_API_KEY is not configured (backend/.env still has the placeholder value)"}

    user_prompt = f"What we're offering:\n{offer}\n\nRecipient's company:\n{context}"
    if contact_name:
        user_prompt += f"\n\nWriting to: {contact_name}"

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=350,
            temperature=0.7,
        )
        parsed = json.loads(resp.choices[0].message.content)
        return {"subject": parsed.get("subject", ""), "body": parsed.get("body", "")}
    except Exception as exc:
        logger.warning("personalization.generate_failed", error=str(exc))
        return {"error": str(exc)}


@job_handler("personalize")
async def run_personalize_job(job: JobRun, payload: dict) -> list:
    """payload: {"offer": str, "items": [{company_id?, company_name?, website?, email, segment, contact_name}, ...]}"""
    from app.database import SessionLocal

    offer = payload.get("offer") or ""
    results = []
    db: Session = SessionLocal()
    try:
        for done, item in enumerate(payload.get("items") or [], start=1):
            company = db.query(Company).filter(Company.id == item["company_id"]).first() if item.get("company_id") else None
            company_name = company.name if company else (item.get("company_name") or "this company")

            live = await build_live_context(
                company_name,
                website=item.get("website", ""),
                segment=item.get("segment"),
                company=company,
            )

            result = await generate_personalized_email(
                offer,
                live["context"],
                contact_name=item.get("contact_name"),
            )
            results.append({
                "company_id": company.id if company else None,
                "company_name": company_name,
                "website": (company.website if company else None) or item.get("website", ""),
                "email": item.get("email"),
                "segment": item.get("segment"),
                "subject": result.get("subject"),
                "body": result.get("body"),
                "error": result.get("error"),
                "pages_crawled": live["pages_crawled"],
                "web_mentions": live["web_mentions"],
            })
            job.progress(done=done)
    finally:
        db.close()
    return results
