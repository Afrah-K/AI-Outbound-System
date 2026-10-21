"""
CSV lead import, shared by the Prospects upload and a campaign's own
"upload a list" option. Every upload is also recorded as a LeadList, so a
campaign can later be pointed at exactly the people in that file - new
rows and rows that matched existing prospects alike.
"""
import csv
import io
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import Company, LeadList, LeadListMember, LeadStatus, Person

# Some exports (e.g. long homepage text) have cells bigger than csv's 128KB default
csv.field_size_limit(10 * 1024 * 1024)

EMAIL_RE = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[a-z]{2,}$", re.IGNORECASE)
EMAIL_SPLIT_RE = re.compile(r"[;,\s|]+")

# Header names (after _normalize_key) that hold the email, best match first.
# "emails" is the Enricher's export, which can hold several per cell.
EMAIL_COLUMNS = (
    "email", "email_address", "e-mail", "e_mail", "e-mail_address", "emails",
    "email_addresses", "work_email", "business_email", "contact_email",
    "primary_email", "personal_email", "mail",
)
COMPANY_COLUMNS = (
    "company_name_for_emails", "company_name", "company", "organization",
    "organisation", "organization_name", "account_name", "business_name", "employer",
)
WEBSITE_COLUMNS = ("website", "company_website", "website_url", "url", "company_url", "homepage")
DOMAIN_COLUMNS = ("domain", "company_domain", "email_domain")
FIRST_NAME_COLUMNS = ("first_name", "firstname", "first", "given_name", "forename")
LAST_NAME_COLUMNS = ("last_name", "lastname", "last", "surname", "family_name")
FULL_NAME_COLUMNS = ("full_name", "fullname", "contact_name", "person_name", "contact")
ROLE_COLUMNS = ("title", "role", "job_title", "position", "job_role")
LINKEDIN_COLUMNS = ("person_linkedin_url", "linkedin_url", "linkedin", "linkedin_profile")
PHONE_COLUMNS = ("mobile_phone", "work_direct_phone", "corporate_phone", "phone", "phone_number", "mobile")
DELIMITERS = (",", ";", "\t", "|")
ALLOWED_EXTENSIONS = (".csv", ".tsv", ".txt")


class LeadImportError(ValueError):
    """The upload couldn't be read as a lead list - the message is shown to the user."""


def is_csv_filename(filename: Optional[str]) -> bool:
    return bool(filename) and filename.lower().endswith(ALLOWED_EXTENSIONS)


def list_name_from_filename(filename: Optional[str]) -> str:
    """The lead list name a file's name suggests: "clutch_leads (2).csv" -> "clutch leads (2)".

    Exports name their files after the list ("Clutch - Branding - Oct 21.csv"),
    so importing one gives the list back its name. Mirrors nameFromFile in the frontend.
    """
    stem = re.sub(r"\.(csv|tsv|txt)$", "", (filename or "").strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip()[:255] or "Imported leads"


def _normalize_key(name: str) -> str:
    return (name or "").replace("﻿", "").strip().strip('"').lower().replace(" ", "_")


def _decode(content: bytes) -> str:
    """UTF-8 (with or without BOM), UTF-16 (Excel's "Unicode Text"), else Windows-1252."""
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16")
    head = content[:2000]
    if head and head.count(b"\x00") > len(head) // 4:  # UTF-16 without a BOM
        return content.decode("utf-16-le" if head[1:2] == b"\x00" else "utf-16-be", errors="replace")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _detect_delimiter(text: str) -> str:
    """Comma, or whatever separator the header row clearly uses instead (e.g. ';' from European Excel)."""
    header = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    header = re.sub(r'"[^"]*"', "", header)  # ignore separators inside quoted names
    counts = {d: header.count(d) for d in DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] > counts[","] else ","


def _first(row: dict, columns) -> str:
    for column in columns:
        value = row.get(column)
        if value:
            return value
    return ""


def _emails_in(value: str) -> list[str]:
    value = (value or "").strip().lower()
    if value.startswith("mailto:"):
        value = value[len("mailto:"):]
    return [part for part in EMAIL_SPLIT_RE.split(value) if EMAIL_RE.match(part)]


def _find_email_column(fieldnames: list[str], sample: list[dict]) -> Optional[str]:
    """
    A known email header if there is one; otherwise any column whose name
    mentions email, or failing that, whose values mostly look like addresses
    (e.g. a header-less column called "Contact").
    """
    def looks_like_emails(column: str) -> bool:
        values = [r.get(column, "") for r in sample if r.get(column)]
        return bool(values) and sum(1 for v in values if _emails_in(v)) >= max(1, len(values) // 2)

    for column in EMAIL_COLUMNS:
        if column in fieldnames:
            return column
    named = [c for c in fieldnames if "email" in c or "e-mail" in c or "e_mail" in c]
    for column in named:
        if looks_like_emails(column):
            return column
    for column in fieldnames:
        if looks_like_emails(column):
            return column
    return None


def _read_rows(content: bytes) -> tuple[list[str], list[dict]]:
    if content.startswith(b"PK\x03\x04"):
        raise LeadImportError("This is an Excel workbook, not a CSV - in Excel use File > Save As > 'CSV UTF-8', then upload that")
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        raise LeadImportError("This is an old-style Excel (.xls) file - save it as 'CSV UTF-8' and upload that")
    text = _decode(content)
    if not text.strip():
        raise LeadImportError("The file is empty")

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=_detect_delimiter(text))
        original = [f for f in (reader.fieldnames or []) if f is not None]
        reader.fieldnames = [_normalize_key(f) for f in (reader.fieldnames or [])]
        rows = [
            {k: (v or "").strip() if isinstance(v, str) else "" for k, v in row.items() if k}
            for row in reader
        ]
    except csv.Error as exc:
        raise LeadImportError(f"Couldn't read the file as a CSV ({exc}). Re-save it from Excel/Sheets as 'CSV UTF-8'.") from exc

    if not original:
        raise LeadImportError("The file has no header row - the first line should name the columns (e.g. email, first_name, company)")
    return original, rows


def import_leads_csv(
    db: Session,
    content: bytes,
    filename: str,
    update_existing: bool = False,
    list_name: Optional[str] = None,
) -> dict:
    """
    Import leads from CSV content. Supports Apollo exports, the app's own
    Scraper/Enricher exports, and typical spreadsheet exports - header names
    like "Email Address", "E-mail" or "Work Email", comma/semicolon/tab
    separators, and UTF-8/UTF-16/Windows-1252 files.

    Rows without an email still import their company (for enrichment later).
    A cell holding several addresses ("a@x.com; b@x.com") becomes one
    prospect per address.

    Commits. Returns import counts, `warnings` to show the user, plus
    `lead_list_id` and `person_ids` (everyone in the file with an email).
    Raises LeadImportError if the file can't be read as a lead list.
    """
    original_fieldnames, rows = _read_rows(content)
    fieldnames = [_normalize_key(f) for f in original_fieldnames]
    email_column = _find_email_column(fieldnames, rows[:50])

    has_company_column = any(c in fieldnames for c in COMPANY_COLUMNS)
    has_site_column = any(c in fieldnames for c in WEBSITE_COLUMNS + DOMAIN_COLUMNS)
    # "name" is the company in scraper/enricher exports (name + website, no
    # company column), but the person in a contact list ("email, name, company").
    name_is_company = "name" in fieldnames and not has_company_column and (has_site_column or not email_column)
    name_is_person = "name" in fieldnames and not name_is_company

    imported_people = 0
    imported_companies = 0
    updated_people = 0
    skipped = 0
    invalid_emails = 0
    person_ids = []

    for row in rows:
        company_name = _first(row, COMPANY_COLUMNS) or (row.get("name", "") if name_is_company else "")

        # Extract domain from website if not provided
        website = _first(row, WEBSITE_COLUMNS)
        domain = _first(row, DOMAIN_COLUMNS)
        if not domain and website:
            try:
                parsed = urlparse(website if website.startswith("http") else f"https://{website}")
                domain = parsed.netloc.replace("www.", "")
            except ValueError:
                pass

        company = None
        if company_name:
            company = db.query(Company).filter(Company.name == company_name).first()
            if not company and domain:
                company = db.query(Company).filter(Company.domain == domain).first()

            if not company:
                company = Company(
                    name=company_name,
                    domain=domain or None,
                    website=website or None,
                    industry=row.get("industry", "") or row.get("category", "") or None,
                    size=row.get("company_size", "") or row.get("size", "") or row.get("#_employees", "") or None,
                    linkedin_url=row.get("company_linkedin_url", "") or None,
                    location=row.get("company_city", "") or row.get("company_country", "") or row.get("location", "") or None,
                )
                db.add(company)
                db.flush()
                imported_companies += 1

        raw_email = row.get(email_column, "") if email_column else ""
        emails = _emails_in(raw_email)
        if not emails:
            if raw_email:
                invalid_emails += 1
            elif not company:
                # Neither an email nor a company - nothing to import
                skipped += 1
            # No email (e.g. a scraped company list) - the company alone is still
            # worth importing for enrichment
            continue

        first_name = _first(row, FIRST_NAME_COLUMNS)
        last_name = _first(row, LAST_NAME_COLUMNS)
        if not first_name and not last_name:
            full_name = _first(row, [c for c in FULL_NAME_COLUMNS if c != email_column]) or (
                row.get("name", "") if name_is_person else ""
            )
            if "@" not in full_name:
                first_name, _, last_name = full_name.partition(" ")

        linkedin = _first(row, LINKEDIN_COLUMNS)
        role = _first(row, ROLE_COLUMNS)
        phone = _first(row, PHONE_COLUMNS)

        for email in emails:
            existing = db.query(Person).filter(Person.email.ilike(email)).first()

            if existing:
                if update_existing:
                    if first_name:
                        existing.first_name = first_name
                    if last_name:
                        existing.last_name = last_name
                    if role:
                        existing.role = role
                    if linkedin:
                        existing.linkedin_url = linkedin
                    if phone:
                        existing.phone = phone
                    if company:
                        existing.company_id = company.id
                    updated_people += 1
                else:
                    skipped += 1
                person_ids.append(existing.id)
            else:
                person = Person(
                    email=email,
                    first_name=first_name or None,
                    last_name=last_name.strip() or None,
                    role=role or None,
                    linkedin_url=linkedin or None,
                    phone=phone or None,
                    company_id=company.id if company else None,
                    status=LeadStatus.NEW,
                )
                db.add(person)
                db.flush()
                person_ids.append(person.id)
                imported_people += 1

    person_ids = list(dict.fromkeys(person_ids))

    warnings = []
    if not email_column:
        warnings.append(
            "No email column found, so no prospects were added"
            + (f" - only {imported_companies} compan{'y' if imported_companies == 1 else 'ies'}" if imported_companies else "")
            + f". Columns in the file: {', '.join(original_fieldnames[:12])}"
        )
    if invalid_emails:
        warnings.append(f"Skipped {invalid_emails} row{'s' if invalid_emails != 1 else ''} with an invalid email address")

    lead_list = None
    if person_ids:
        lead_list = LeadList(name=(list_name or "").strip() or list_name_from_filename(filename), source_filename=filename)
        db.add(lead_list)
        db.flush()
        db.add_all(LeadListMember(lead_list_id=lead_list.id, person_id=pid) for pid in person_ids)

    db.commit()

    return {
        "message": "CSV import completed",
        "imported_people": imported_people,
        "imported_companies": imported_companies,
        "updated_people": updated_people,
        "skipped": skipped,
        "invalid_emails": invalid_emails,
        "email_column": original_fieldnames[fieldnames.index(email_column)] if email_column else None,
        "warnings": warnings,
        "lead_list_id": lead_list.id if lead_list else None,
        "lead_list_name": lead_list.name if lead_list else None,
        "people_in_file": len(person_ids),
        "person_ids": person_ids,
        "columns_found": original_fieldnames[:10],  # Show first 10 columns for debugging
    }


BATCH_GAP = timedelta(minutes=15)
SETTLE_TIME = timedelta(minutes=10)


def group_unlisted_prospects(db: Session) -> int:
    """
    Put every prospect that isn't in any lead list into one: people added
    before lists were tracked, or by tools other than CSV import (e.g. the
    Enricher). Prospects created close together form one batch - a new list
    starts after a 15-minute gap - named after when they were added. People
    added in the last 10 minutes are left for later so a batch that's still
    arriving isn't split. Only adds lists; never changes the prospects.
    Returns how many lists were created.
    """
    cutoff = datetime.utcnow() - SETTLE_TIME
    listed = db.query(LeadListMember.person_id)
    unlisted = (
        db.query(Person.id, Person.created_at)
        .filter(~Person.id.in_(listed), Person.created_at <= cutoff)
        .order_by(Person.created_at, Person.id)
        .all()
    )
    if not unlisted:
        return 0

    batches, current, last_seen = [], [], None
    for person_id, created_at in unlisted:
        if current and created_at - last_seen > BATCH_GAP:
            batches.append(current)
            current = []
        current.append((person_id, created_at))
        last_seen = created_at
    batches.append(current)

    for batch in batches:
        first_added = batch[0][1]
        lead_list = LeadList(
            name=f"Added {first_added:%b} {first_added.day}, {first_added:%Y} at {first_added:%H:%M} UTC",
            created_at=first_added,
        )
        db.add(lead_list)
        db.flush()
        db.add_all(LeadListMember(lead_list_id=lead_list.id, person_id=pid) for pid, _ in batch)
    db.commit()
    return len(batches)
