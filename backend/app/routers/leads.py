from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Company, Person, LeadStatus

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


@router.get("/people")
async def list_people(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List people with pagination and filters."""
    query = db.query(Person)
    if search:
        query = query.filter(
            (Person.email.ilike(f"%{search}%")) |
            (Person.first_name.ilike(f"%{search}%")) |
            (Person.last_name.ilike(f"%{search}%"))
        )
    if status:
        try:
            status_enum = LeadStatus(status)
            query = query.filter(Person.status == status_enum)
        except ValueError:
            pass

    total = query.count()
    people = query.offset(skip).limit(limit).all()

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
                "linkedin_url": p.linkedin_url,
                "phone": p.phone,
                "status": p.status.value if p.status else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in people
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


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
    db: Session = Depends(get_db)
):
    """
    Import leads from CSV file.

    Supports Apollo exports and standard CSV formats.
    Key columns: Email, First Name, Last Name, Company Name, Title, Person Linkedin Url, Website
    """
    import csv
    import io

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    try:
        decoded = content.decode('utf-8')
    except UnicodeDecodeError:
        decoded = content.decode('latin-1')

    reader = csv.DictReader(io.StringIO(decoded))

    # Normalize column names (lowercase, strip whitespace, replace spaces with underscores)
    original_fieldnames = reader.fieldnames.copy() if reader.fieldnames else []
    if reader.fieldnames:
        reader.fieldnames = [name.lower().strip().replace(' ', '_') for name in reader.fieldnames]

    imported_people = 0
    imported_companies = 0
    updated_people = 0
    skipped = 0

    for row_num, row in enumerate(reader, start=2):
        # Normalize row keys
        row = {k.lower().strip().replace(' ', '_'): v.strip() if v else '' for k, v in row.items()}

        email = row.get('email', '')
        if not email:
            skipped += 1
            continue

        # Get or create company
        company = None
        # Apollo uses "company_name" or "company_name_for_emails"
        company_name = (
            row.get('company_name_for_emails', '') or
            row.get('company_name', '') or
            row.get('company', '')
        )
        # Extract domain from website if not provided
        website = row.get('website', '')
        domain = row.get('domain', '') or row.get('company_domain', '')
        if not domain and website:
            # Extract domain from website URL
            from urllib.parse import urlparse
            try:
                parsed = urlparse(website if website.startswith('http') else f'https://{website}')
                domain = parsed.netloc.replace('www.', '')
            except:
                pass

        if company_name:
            # Try to find existing company
            company = db.query(Company).filter(Company.name == company_name).first()
            if not company and domain:
                company = db.query(Company).filter(Company.domain == domain).first()

            if not company:
                # Create new company
                company = Company(
                    name=company_name,
                    domain=domain or None,
                    website=website or None,
                    industry=row.get('industry', '') or None,
                    size=row.get('company_size', '') or row.get('size', '') or row.get('#_employees', '') or None,
                    linkedin_url=row.get('company_linkedin_url', '') or None,
                    location=row.get('company_city', '') or row.get('company_country', '') or None,
                )
                db.add(company)
                db.flush()
                imported_companies += 1

        # Extract person fields - handle Apollo column names
        first_name = row.get('first_name', '') or row.get('firstname', '')
        last_name = row.get('last_name', '') or row.get('lastname', '')

        # Apollo uses "person_linkedin_url" for individual LinkedIn
        linkedin = (
            row.get('person_linkedin_url', '') or
            row.get('linkedin_url', '') or
            row.get('linkedin', '')
        )

        # Apollo uses "title" for job role
        role = (
            row.get('title', '') or
            row.get('role', '') or
            row.get('job_title', '')
        )

        # Phone fields in Apollo
        phone = (
            row.get('mobile_phone', '') or
            row.get('work_direct_phone', '') or
            row.get('corporate_phone', '') or
            row.get('phone', '') or
            row.get('phone_number', '')
        )

        # Check if person already exists
        existing = db.query(Person).filter(Person.email == email).first()

        if existing:
            if update_existing:
                # Update existing person
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
        else:
            # Create new person
            person = Person(
                email=email,
                first_name=first_name or None,
                last_name=last_name or None,
                role=role or None,
                linkedin_url=linkedin or None,
                phone=phone or None,
                company_id=company.id if company else None,
                status=LeadStatus.NEW,
            )
            db.add(person)
            imported_people += 1

    db.commit()

    return {
        "message": "CSV import completed",
        "imported_people": imported_people,
        "imported_companies": imported_companies,
        "updated_people": updated_people,
        "skipped": skipped,
        "columns_found": original_fieldnames[:10],  # Show first 10 columns for debugging
    }


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
