"""
Import a scraped company list (name, website, location, rating, category -
e.g. a Clutch export) and run the email-finding enricher over it end to end.

Usage:
    python scripts/enrich_csv.py path/to/leads.csv
"""
import asyncio
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, init_db
from app.models import Company
from app.services.enrichment import enrich_company


def get_or_create_company(db, row: dict) -> Company:
    name = row.get("name", "").strip()
    website = row.get("website", "").strip()
    location = row.get("location", "").strip()
    category = row.get("category", "").strip()

    domain = None
    if website:
        parsed = urlparse(website if website.startswith("http") else f"https://{website}")
        domain = parsed.netloc.replace("www.", "")

    company = db.query(Company).filter(Company.name == name).first()
    if not company and domain:
        company = db.query(Company).filter(Company.domain == domain).first()

    if not company:
        company = Company(
            name=name,
            website=website or None,
            domain=domain,
            location=location or None,
            industry=category or None,
        )
        db.add(company)
        db.flush()

    return company


async def main(csv_path: str):
    init_db()
    db = SessionLocal()

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} rows from {csv_path}\n")

    companies = []
    for row in rows:
        company = get_or_create_company(db, row)
        companies.append(company)
    db.commit()

    total_emails = 0
    for company in companies:
        result = await enrich_company(company, db)
        found = result.get("emails_created", [])
        total_emails += len(found)
        status = ", ".join(found) if found else (result.get("error") or "no public email found")
        print(f"  {company.name:<28} {company.website or '':<32} -> {status}")

    print(f"\nDone. {len(companies)} companies processed, {total_emails} new email leads created.")
    db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/enrich_csv.py path/to/leads.csv")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
