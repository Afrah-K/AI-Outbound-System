from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional

from datetime import datetime

from fastapi.concurrency import run_in_threadpool

from app.database import get_db
from app.models import AgentDraft, Campaign, CampaignLead, Company, EmailLog, LeadList, LeadListMember, Person, LeadStatus, SendQueue
from app.services.lead_import import LeadImportError, group_unlisted_prospects, import_leads_csv, is_csv_filename
from app.services.enrichment import enrich_company, load_unpicked, save_unpicked
from app.services.verification import guess_segment, is_generic_address, verify_email
from app.services.jobs import JobRun, enqueue_job, get_job, job_handler, to_dict
import app.services.personalization  # noqa: F401 - registers the "personalize" job handler

router = APIRouter()


@router.get("/companies")
async def list_companies(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List companies with pagination."""
    query = db.query(Company)
    if search:
        query = query.filter(Company.name.ilike(f"%{search}%"))

    total = query.count()
    companies = query.offset(skip).limit(limit).all()

    return {
        "companies": [
            {
                "id": c.id,
                "name": c.name,
                "domain": c.domain,
                "website": c.website,
                "industry": c.industry,
                "size": c.size,
                "linkedin_url": c.linkedin_url,
                "location": c.location,
                "enrichment_status": c.enrichment_status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in companies
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/companies/{company_id}")
async def get_company(company_id: int, db: Session = Depends(get_db)):
    """Get company details with associated people."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return {
        "id": company.id,
        "name": company.name,
        "domain": company.domain,
        "website": company.website,
        "industry": company.industry,
        "size": company.size,
        "employee_count": company.employee_count,
        "funding_stage": company.funding_stage,
        "linkedin_url": company.linkedin_url,
        "location": company.location,
        "enrichment_status": company.enrichment_status,
        "personalization_hook": company.personalization_hook,
        "last_enriched_at": company.last_enriched_at.isoformat() if company.last_enriched_at else None,
        "people": [
            {
                "id": p.id,
                "email": p.email,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "role": p.role,
                "status": p.status.value if p.status else None,
            }
            for p in company.people
        ],
        "created_at": company.created_at.isoformat() if company.created_at else None,
    }


def _people_query(db: Session, search: Optional[str], status: Optional[str], list_id: Optional[int]):
    """Prospects matching the Prospects page filters - shared by listing and bulk delete."""
    query = db.query(Person).outerjoin(Company, Person.company_id == Company.id)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            Person.email.ilike(term)
            | Person.first_name.ilike(term)
            | Person.last_name.ilike(term)
            | Person.full_name.ilike(term)
            | Person.role.ilike(term)
            | Company.name.ilike(term)
            | Company.domain.ilike(term)
        )
    if status:
        try:
            query = query.filter(Person.status == LeadStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status '{status}'")
    if list_id:
        query = query.filter(
            Person.id.in_(db.query(LeadListMember.person_id).filter(LeadListMember.lead_list_id == list_id))
        )
    return query


@router.get("/people")
async def list_people(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    list_id: Optional[int] = Query(None, description="Only prospects in this uploaded lead list"),
    db: Session = Depends(get_db)
):
    """
    List prospects, newest first, with their company details and how many
    campaigns each is in. Search matches name, email, role and company.
    `status_counts` covers all prospects (ignores filters) for the summary cards.
    """
    query = _people_query(db, search, status, list_id)

    total = query.count()
    people = query.order_by(Person.created_at.desc(), Person.id.desc()).offset(skip).limit(limit).all()

    page_ids = [p.id for p in people]
    campaign_counts = dict(
        db.query(CampaignLead.person_id, func.count(CampaignLead.id))
        .filter(CampaignLead.person_id.in_(page_ids))
        .group_by(CampaignLead.person_id)
        .all()
    ) if page_ids else {}

    status_counts = {s.value: 0 for s in LeadStatus}
    for status_value, count in db.query(Person.status, func.count(Person.id)).group_by(Person.status).all():
        if status_value:
            status_counts[status_value.value] = count

    return {
        "people": [
            {
                "id": p.id,
                "email": p.email,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "full_name": p.full_name,
                "role": p.role,
                "company_id": p.company_id,
                "company_name": p.company.name if p.company else None,
                "company_domain": p.company.domain if p.company else None,
                "company_website": p.company.website if p.company else None,
                "industry": p.company.industry if p.company else None,
                "location": p.company.location if p.company else None,
                "linkedin_url": p.linkedin_url,
                "phone": p.phone,
                "status": p.status.value if p.status else None,
                "campaign_count": campaign_counts.get(p.id, 0),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in people
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
        "status_counts": status_counts,
        "total_prospects": sum(status_counts.values()),
    }


class BulkStatusRequest(BaseModel):
    person_ids: List[int]
    status: str


@router.post("/people/bulk-status")
async def bulk_update_person_status(payload: BulkStatusRequest, db: Session = Depends(get_db)):
    """Set the same status on many prospects at once."""
    try:
        new_status = LeadStatus(payload.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {payload.status}")
    updated = (
        db.query(Person)
        .filter(Person.id.in_(payload.person_ids))
        .update({"status": new_status}, synchronize_session=False)
    ) if payload.person_ids else 0
    db.commit()
    return {"message": f"Updated {updated} prospects", "updated": updated}


@router.get("/people/{person_id}")
async def get_person(person_id: int, db: Session = Depends(get_db)):
    """Get person details."""
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    return {
        "id": person.id,
        "email": person.email,
        "first_name": person.first_name,
        "last_name": person.last_name,
        "full_name": person.full_name,
        "role": person.role,
        "seniority": person.seniority,
        "department": person.department,
        "linkedin_url": person.linkedin_url,
        "phone": person.phone,
        "company_id": person.company_id,
        "company": {
            "id": person.company.id,
            "name": person.company.name,
            "domain": person.company.domain,
        } if person.company else None,
        "status": person.status.value if person.status else None,
        "personalization_sentence": person.personalization_sentence,
        "created_at": person.created_at.isoformat() if person.created_at else None,
        "updated_at": person.updated_at.isoformat() if person.updated_at else None,
    }


@router.post("/import")
async def import_csv(
    file: UploadFile = File(...),
    update_existing: bool = Query(False, description="Update existing leads instead of skipping"),
    list_name: Optional[str] = Query(None, description="Name for the lead list this upload creates (defaults to the filename)"),
    db: Session = Depends(get_db)
):
    """
    Import leads from CSV file. Every upload is saved as a lead list that a
    campaign can be sent to.

    Supports Apollo exports and standard CSV formats.
    Key columns: Email, First Name, Last Name, Company Name, Title, Person Linkedin Url, Website
    """
    if not is_csv_filename(file.filename):
        raise HTTPException(status_code=400, detail="File must be a CSV (.csv, .tsv or .txt)")

    try:
        result = import_leads_csv(db, await file.read(), file.filename, update_existing, list_name)
    except LeadImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result.pop("person_ids")
    return result


@router.get("/lists")
async def list_lead_lists(db: Session = Depends(get_db)):
    """
    Every lead list, newest first, with how many prospects each holds.
    Prospects not in any list yet are grouped into dated lists first, so the
    lists together cover everyone in the prospects table.
    """
    group_unlisted_prospects(db)
    rows = (
        db.query(LeadList, func.count(LeadListMember.id))
        .outerjoin(LeadListMember, LeadListMember.lead_list_id == LeadList.id)
        .filter(LeadList.deleted_at.is_(None))
        .group_by(LeadList.id)
        .order_by(LeadList.created_at.desc())
        .all()
    )
    return {
        "lists": [
            {
                "id": lead_list.id,
                "name": lead_list.name,
                "source_filename": lead_list.source_filename,
                "lead_count": count,
                "created_at": lead_list.created_at.isoformat() if lead_list.created_at else None,
            }
            for lead_list, count in rows
        ],
        "total_prospects": db.query(Person).count(),
    }


class BulkDeletePeopleRequest(BaseModel):
    # The Prospects page's current filters - every prospect they match is a candidate
    search: Optional[str] = None
    status: Optional[str] = None
    list_id: Optional[int] = None
    dry_run: bool = False


# Prospects in these states keep their record: deleting it would lose the
# email history, and an opted-out person re-imported later could be emailed again.
KEEP_STATUSES = (
    LeadStatus.CONTACTED, LeadStatus.REPLIED, LeadStatus.CONVERTED,
    LeadStatus.BOUNCED, LeadStatus.UNSUBSCRIBED, LeadStatus.DO_NOT_CONTACT,
)
DELETE_CHUNK = 500


@router.post("/people/bulk-delete")
async def bulk_delete_people(payload: BulkDeletePeopleRequest, db: Session = Depends(get_db)):
    """
    Delete every prospect matching the given filters ("Remove all" on the
    Prospects page). Prospects who've been emailed, replied, bounced,
    unsubscribed or are marked do-not-contact are kept, so their history and
    opt-outs survive. With dry_run, only reports what would happen.
    """
    matched = [pid for (pid,) in _people_query(db, payload.search, payload.status, payload.list_id).with_entities(Person.id)]
    if not matched:
        return {"matched": 0, "deleted": 0, "kept": 0, "kept_reasons": {}, "dry_run": payload.dry_run}

    emailed, kept_status = set(), {}
    for i in range(0, len(matched), DELETE_CHUNK):
        chunk = matched[i:i + DELETE_CHUNK]
        emailed |= {pid for (pid,) in db.query(EmailLog.person_id).filter(EmailLog.person_id.in_(chunk)).distinct()}
        emailed |= {pid for (pid,) in db.query(AgentDraft.person_id).filter(AgentDraft.person_id.in_(chunk)).distinct()}
        kept_status.update(
            db.query(Person.id, Person.status).filter(Person.id.in_(chunk), Person.status.in_(KEEP_STATUSES)).all()
        )

    kept_reasons: dict = {}
    deletable = []
    for pid in matched:
        if pid in kept_status:
            reason = kept_status[pid].value
        elif pid in emailed:
            reason = "emailed"
        else:
            deletable.append(pid)
            continue
        kept_reasons[reason] = kept_reasons.get(reason, 0) + 1

    in_campaigns = set()
    for i in range(0, len(deletable), DELETE_CHUNK):
        in_campaigns |= {
            pid for (pid,) in db.query(CampaignLead.person_id).filter(CampaignLead.person_id.in_(deletable[i:i + DELETE_CHUNK])).distinct()
        }

    result = {
        "matched": len(matched),
        "deleted": len(deletable),
        "in_campaigns": len(in_campaigns),  # of the deleted, how many get taken out of campaigns
        "kept": len(matched) - len(deletable),
        "kept_reasons": kept_reasons,
        "dry_run": payload.dry_run,
    }
    if payload.dry_run or not deletable:
        return result

    affected_campaigns = set()
    for i in range(0, len(deletable), DELETE_CHUNK):
        chunk = deletable[i:i + DELETE_CHUNK]
        affected_campaigns |= {
            cid for (cid,) in db.query(CampaignLead.campaign_id).filter(CampaignLead.person_id.in_(chunk)).distinct()
        }
        db.query(SendQueue).filter(SendQueue.person_id.in_(chunk)).delete(synchronize_session=False)
        db.query(CampaignLead).filter(CampaignLead.person_id.in_(chunk)).delete(synchronize_session=False)
        db.query(LeadListMember).filter(LeadListMember.person_id.in_(chunk)).delete(synchronize_session=False)
        db.query(Person).filter(Person.id.in_(chunk)).delete(synchronize_session=False)

    db.flush()
    for campaign in db.query(Campaign).filter(Campaign.id.in_(affected_campaigns)):
        campaign.total_leads = db.query(CampaignLead).filter(CampaignLead.campaign_id == campaign.id).count()
    db.commit()
    return result


@router.delete("/lists/{list_id}")
async def delete_lead_list(list_id: int, db: Session = Depends(get_db)):
    """
    Delete a lead list. The prospects themselves are kept (still under "All
    lead lists"), and campaigns they were already added to are unaffected.
    """
    lead_list = db.query(LeadList).filter(LeadList.id == list_id, LeadList.deleted_at.is_(None)).first()
    if not lead_list:
        raise HTTPException(status_code=404, detail="Lead list not found")
    lead_list.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": f'Deleted lead list "{lead_list.name}"', "name": lead_list.name}


@router.patch("/people/{person_id}/status")
async def update_person_status(
    person_id: int,
    status: str,
    db: Session = Depends(get_db)
):
    """Update lead status."""
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    try:
        person.status = LeadStatus(status)
        db.commit()
        return {"message": "Status updated", "status": status}
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")


class PickEmailRequest(BaseModel):
    email: str


@router.post("/companies/{company_id}/emails/pick")
async def pick_unpicked_email(company_id: int, payload: PickEmailRequest, db: Session = Depends(get_db)):
    """
    Turn one of a company's unpicked emails (found by the Enricher but left
    out - over the per-company limit, or on another domain) into a prospect.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    email = payload.email.strip().lower()
    unpicked = load_unpicked(company)
    if email not in {i["email"].lower() for i in unpicked}:
        raise HTTPException(status_code=404, detail=f"{email} isn't one of this company's unpicked emails")

    person = db.query(Person).filter(Person.email.ilike(email)).first()
    if person is None:
        person = Person(email=email, company_id=company.id, status=LeadStatus.NEW)
        db.add(person)
    elif person.company_id is None:
        person.company_id = company.id
    save_unpicked(company, [i for i in unpicked if i["email"].lower() != email])
    db.commit()

    return {"email": email, "person_id": person.id, "unpicked_emails": load_unpicked(company)}


@router.post("/companies/{company_id}/enrich")
async def enrich_company_endpoint(company_id: int, db: Session = Depends(get_db)):
    """Scrape a company's website for contact emails and homepage text."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    result = await enrich_company(company, db)
    return result


@router.post("/enrich/pending")
async def enrich_pending_companies(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Run the email-finding enricher over companies that haven't been enriched yet."""
    companies = db.query(Company).filter(Company.enrichment_status == "pending").limit(limit).all()

    results = [await enrich_company(company, db) for company in companies]
    total_emails = sum(r["emails_found"] for r in results)

    return {
        "companies_processed": len(results),
        "total_emails_found": total_emails,
        "results": results,
    }


MAX_ENRICH_UPLOAD_ROWS = 100000


@router.post("/enrich/upload")
async def upload_and_enrich(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a scraped company list (name, website, location, category - e.g. a
    Clutch or directory export with no emails yet) and find contact emails
    for every company.

    Runs as a background job (poll GET /enrich/jobs/{job_id} for progress)
    instead of blocking one request until every company is scraped - for a
    few hundred companies that can take well past any reasonable timeout.
    Companies already enriched are returned from cache instantly (see
    enrich_company's cache) rather than re-scraped.
    """
    import csv
    import io
    from urllib.parse import urlparse

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    try:
        decoded = content.decode('utf-8')
    except UnicodeDecodeError:
        decoded = content.decode('latin-1')

    reader = csv.DictReader(io.StringIO(decoded))
    if reader.fieldnames:
        reader.fieldnames = [name.lower().strip().replace(' ', '_') for name in reader.fieldnames]

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    if len(rows) > MAX_ENRICH_UPLOAD_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Max {MAX_ENRICH_UPLOAD_ROWS} companies per upload - split your file into smaller batches",
        )

    companies = []
    for row in rows:
        row = {k: (v.strip() if v else '') for k, v in row.items()}
        name = row.get('name', '') or row.get('company_name', '') or row.get('company', '')
        website = row.get('website', '')
        if not name and not website:
            continue

        domain = row.get('domain', '') or row.get('company_domain', '')
        if not domain and website:
            try:
                parsed = urlparse(website if website.startswith('http') else f'https://{website}')
                domain = parsed.netloc.replace('www.', '')
            except ValueError:
                pass

        # Domain first: names like "Hook" or "Clay" can belong to a different
        # company already in the database, whose website would then get scraped
        company = db.query(Company).filter(Company.domain == domain).first() if domain else None
        if not company and name:
            same_name = db.query(Company).filter(Company.name == name).first()
            if same_name and (not domain or not same_name.domain or same_name.domain == domain):
                company = same_name

        if not company:
            company = Company(
                name=name or domain or website,
                website=website or None,
                domain=domain or None,
                location=row.get('location', '') or None,
                industry=row.get('industry', '') or row.get('category', '') or None,
            )
            db.add(company)
            db.flush()

        companies.append(company)

    db.commit()

    job = enqueue_job(db, "enrich", {"company_ids": [c.id for c in companies]}, total=len(companies))
    return {"job_id": job["job_id"], "total": job["total"]}


class RescanRequest(BaseModel):
    company_ids: List[int]
    force_ids: List[int] = []


@router.post("/enrich/rescan")
async def rescan_companies(payload: RescanRequest, db: Session = Depends(get_db)):
    """
    Re-run enrichment over a previous result list: companies in force_ids are
    re-scraped (e.g. ones enriched before unpicked emails were tracked), the
    rest come back from cache, so the job's results cover the whole list again.
    """
    if not payload.company_ids:
        raise HTTPException(status_code=400, detail="No companies to re-scan")
    if len(payload.company_ids) > MAX_ENRICH_UPLOAD_ROWS:
        raise HTTPException(status_code=400, detail=f"Max {MAX_ENRICH_UPLOAD_ROWS} companies per run")

    job = enqueue_job(db, "enrich", {"company_ids": payload.company_ids, "force_ids": payload.force_ids},
                      total=len(payload.company_ids))
    return {"job_id": job["job_id"], "total": job["total"]}


@router.get("/enrich/jobs/{job_id}")
async def get_enrich_job_status(job_id: str, db: Session = Depends(get_db)):
    """Poll a background enrichment job's progress and (once completed) its results."""
    job = get_job(db, job_id, kind="enrich")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    data = to_dict(job)
    return {
        "job_id": data["job_id"],
        "status": data["status"],
        "total": data["total"],
        "processed": data["processed"],
        "emails_found": data["extra"].get("emails_found", 0),
        "error": data["error"],
        "results": data["result"] or [],
    }


class VerifyCompanyInput(BaseModel):
    company_id: Optional[int] = None
    name: str = ""
    website: str = ""
    emails: List[str] = []


class VerifyRequest(BaseModel):
    results: List[VerifyCompanyInput]


BOUNCE_RATE_SAFE_THRESHOLD = 3.0


def _prepare_verify_rows(payload: VerifyRequest, db: Session) -> tuple[int, int, list[dict]]:
    """
    Drop generic role addresses (info@, hello@, ...) where a personal address
    exists for the same company, tag a segment guess, and dedupe by email.
    Returns (total_input_emails, after_generic_filter, deduped_rows).
    """
    total_input = sum(len(c.emails) for c in payload.results)

    candidate_rows = []
    for company in payload.results:
        industry = None
        if company.company_id:
            db_company = db.query(Company).filter(Company.id == company.company_id).first()
            industry = db_company.industry if db_company else None

        personal = [e for e in company.emails if not is_generic_address(e)]
        generic = [e for e in company.emails if is_generic_address(e)]
        keep = personal if personal else generic

        segment = guess_segment(industry)
        for email in keep:
            candidate_rows.append({
                "company_id": company.company_id,
                "company_name": company.name,
                "website": company.website,
                "email": email,
                "segment": segment,
            })

    seen = set()
    deduped = []
    for row in candidate_rows:
        key = row["email"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return total_input, len(candidate_rows), deduped


def _verify_rows(rows: list[dict], on_progress=None) -> None:
    """Syntax + DNS/MX check per row, in place. Blocking - run it off the event loop."""
    for i, row in enumerate(rows):
        v = verify_email(row["email"])
        row["email"] = v["email"]
        row["valid_syntax"] = v["valid_syntax"]
        row["deliverable"] = v["deliverable"]
        row["reason"] = v["reason"]
        if on_progress:
            on_progress(f"Checked {i + 1} of {len(rows)} addresses", done=i + 1, total=len(rows))


def _verify_summary(total_input: int, after_generic: int, rows: list[dict]) -> dict:
    deliverable_count = sum(1 for r in rows if r["deliverable"])
    risky_count = len(rows) - deliverable_count
    bounce_rate = round((risky_count / len(rows) * 100), 1) if rows else 0.0

    return {
        "total_input_emails": total_input,
        "after_generic_filter": after_generic,
        "after_dedupe": len(rows),
        "deliverable_count": deliverable_count,
        "risky_count": risky_count,
        "estimated_bounce_rate": bounce_rate,
        "safe_threshold": BOUNCE_RATE_SAFE_THRESHOLD,
        "over_safe_threshold": bounce_rate > BOUNCE_RATE_SAFE_THRESHOLD,
        "rows": rows,
    }


@router.post("/verify")
async def verify_leads(payload: VerifyRequest, db: Session = Depends(get_db)):
    """
    Run an enriched list through list hygiene before it reaches a campaign:

    - Verify each email (syntax + DNS/MX deliverability)
    - Drop generic role addresses (info@, hello@, ...) where a personal
      address exists for the same company
    - Dedupe by email
    - Tag each row with a studio/BDR segment guess (override per row)

    Blocks until done - the frontend uses POST /verify/jobs instead.
    """
    total_input, after_generic, rows = _prepare_verify_rows(payload, db)
    await run_in_threadpool(_verify_rows, rows)
    return _verify_summary(total_input, after_generic, rows)


@router.post("/verify/jobs")
async def start_verify_job(payload: VerifyRequest, db: Session = Depends(get_db)):
    """
    Same as POST /verify, but runs in the background so the user can move to
    other pages - poll GET /verify/jobs/{job_id}; `result` holds the summary.
    """
    total_input, after_generic, rows = _prepare_verify_rows(payload, db)
    return enqueue_job(
        db, "verify", {"total_input": total_input, "after_generic": after_generic, "rows": rows},
        total=len(rows), message=f"Checking {len(rows)} addresses...",
    )


@job_handler("verify")
async def _verify_job(job: JobRun, payload: dict) -> dict:
    rows = payload["rows"]
    await run_in_threadpool(_verify_rows, rows, job.progress)
    return _verify_summary(payload["total_input"], payload["after_generic"], rows)


@router.get("/verify/jobs/{job_id}")
async def get_verify_job(job_id: str, db: Session = Depends(get_db)):
    job = get_job(db, job_id, kind="verify")
    if not job:
        raise HTTPException(status_code=404, detail="Verify job not found")
    return to_dict(job)


class PersonalizeLead(BaseModel):
    company_id: Optional[int] = None
    company_name: str = ""
    website: str = ""
    email: str
    segment: Optional[str] = None
    contact_name: Optional[str] = None


class PersonalizeRequest(BaseModel):
    leads: List[PersonalizeLead]
    offer: str


MAX_PERSONALIZE_LEADS = 200


@router.post("/personalize")
async def personalize_leads(payload: PersonalizeRequest, db: Session = Depends(get_db)):
    """
    Draft one AI-personalized cold email per lead. Crawls the company's own
    site live (homepage plus its most relevant pages - about, services,
    work, team...) and searches the web for recent public mentions, on top
    of whatever's already known from the DB (industry, location, segment).
    Runs as a background job - poll GET /personalize/jobs/{job_id} for
    progress and results.
    """
    if not payload.offer or not payload.offer.strip():
        raise HTTPException(status_code=400, detail="Describe what you're offering so the AI has something to pitch")
    if not payload.leads:
        raise HTTPException(status_code=400, detail="No leads provided")
    if len(payload.leads) > MAX_PERSONALIZE_LEADS:
        raise HTTPException(
            status_code=400,
            detail=f"Max {MAX_PERSONALIZE_LEADS} leads per run - split into smaller batches",
        )

    items = [lead.model_dump() for lead in payload.leads]
    job = enqueue_job(db, "personalize", {"items": items, "offer": payload.offer}, total=len(items))
    return {"job_id": job["job_id"], "total": job["total"]}


@router.get("/personalize/jobs/{job_id}")
async def get_personalize_job_status(job_id: str, db: Session = Depends(get_db)):
    """Poll a background personalization job's progress and (once completed) its drafted emails."""
    job = get_job(db, job_id, kind="personalize")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    data = to_dict(job)
    return {
        "job_id": data["job_id"],
        "status": data["status"],
        "total": data["total"],
        "processed": data["processed"],
        "error": data["error"],
        "results": data["result"] or [],
    }
