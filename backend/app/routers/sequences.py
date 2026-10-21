from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import Campaign, CampaignStatus, Sequence, SequenceStep
from app.services.campaign_engine import KNOWN_VARIABLES, VARIABLE_ALIASES, find_unknown_variables

router = APIRouter()

STEP_FIELDS = ("delay_days", "delay_hours", "subject", "body", "use_gpt", "gpt_prompt")


class StepCreate(BaseModel):
    # Only used when a full step list is sent on sequence update: identifies an existing step to keep.
    id: Optional[int] = None
    # Position in the sequence. Omit to append; steps are renumbered 0, 1, 2... after every change.
    order: Optional[int] = None
    delay_days: int = Field(0, ge=0)
    delay_hours: int = Field(0, ge=0)
    # A follow-up may leave the subject blank to reply in the previous email's thread.
    subject: str = ""
    body: str
    use_gpt: bool = False
    gpt_prompt: Optional[str] = None


class StepUpdate(BaseModel):
    delay_days: Optional[int] = Field(None, ge=0)
    delay_hours: Optional[int] = Field(None, ge=0)
    subject: Optional[str] = None
    body: Optional[str] = None
    use_gpt: Optional[bool] = None
    gpt_prompt: Optional[str] = None


class SequenceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    steps: Optional[List[StepCreate]] = None


class SequenceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # When present, replaces the sequence's steps with this list (in this order).
    steps: Optional[List[StepCreate]] = None


def _get_sequence_or_404(db: Session, sequence_id: int) -> Sequence:
    sequence = db.query(Sequence).filter(Sequence.id == sequence_id).first()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return sequence


def _check_variables(*texts: Optional[str]) -> None:
    unknown = find_unknown_variables(*texts)
    if unknown:
        allowed = ", ".join(f"{{{{{name}}}}}" for name in list(KNOWN_VARIABLES) + list(VARIABLE_ALIASES))
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template variables: {', '.join(unknown)}. Available: {allowed}",
        )


def _ordered(sequence: Sequence) -> list:
    return sorted(sequence.steps, key=lambda s: (s.order, s.id or 0))


def _renumber(steps: list) -> None:
    for position, step in enumerate(steps):
        step.order = position


def _in_flight_campaigns(db: Session, sequence_id: int) -> list:
    return db.query(Campaign).filter(
        Campaign.sequence_id == sequence_id,
        Campaign.status.in_((CampaignStatus.ACTIVE, CampaignStatus.PAUSED)),
    ).all()


def _replace_steps(db: Session, sequence: Sequence, incoming: List[StepCreate]) -> None:
    """
    Sync the sequence's steps to `incoming`, updating rows in place where
    possible (matched by id, else by position) so email history and stats
    keep pointing at the same step rows.
    """
    existing = _ordered(sequence)
    by_id = {s.id: s for s in existing}
    claimed_ids = {data.id for data in incoming if data.id in by_id}
    unclaimed = iter([s for s in existing if s.id not in claimed_ids])

    ordered_incoming = sorted(
        enumerate(incoming),
        key=lambda pair: (pair[1].order if pair[1].order is not None else pair[0], pair[0]),
    )

    kept = []
    for _, data in ordered_incoming:
        step = by_id.get(data.id) if data.id in by_id else next(unclaimed, None)
        if step is None:
            step = SequenceStep(sequence_id=sequence.id)
            sequence.steps.append(step)
        for field in STEP_FIELDS:
            setattr(step, field, getattr(data, field))
        kept.append(step)

    for step in existing:
        if step not in kept:
            sequence.steps.remove(step)

    _renumber(kept)


def _serialize_step(step: SequenceStep) -> dict:
    return {
        "id": step.id,
        "order": step.order,
        "delay_days": step.delay_days,
        "delay_hours": step.delay_hours,
        "subject": step.subject,
        "body": step.body,
        "use_gpt": step.use_gpt,
        "gpt_prompt": step.gpt_prompt,
    }


@router.get("")
async def list_sequences(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """List all sequences."""
    query = db.query(Sequence)
    total = query.count()
    sequences = query.order_by(Sequence.created_at.desc()).offset(skip).limit(limit).all()

    return {
        "sequences": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "step_count": len(s.steps),
                "campaign_count": len(s.campaigns),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sequences
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/variables")
async def list_template_variables():
    """Template variables usable in step subjects and bodies, e.g. {{first_name}} or {{first_name|there}}."""
    return {
        "variables": [{"name": name, "description": desc} for name, desc in KNOWN_VARIABLES.items()],
        "aliases": VARIABLE_ALIASES,
        "fallback_syntax": "{{variable|fallback}} - used when the lead has no value. Without a fallback, leads missing the value are skipped.",
    }


@router.post("")
async def create_sequence(sequence: SequenceCreate, db: Session = Depends(get_db)):
    """Create a new sequence."""
    for step in sequence.steps or []:
        _check_variables(step.subject, step.body)

    db_sequence = Sequence(
        name=sequence.name,
        description=sequence.description,
    )
    db.add(db_sequence)
    db.flush()

    if sequence.steps:
        _replace_steps(db, db_sequence, sequence.steps)

    db.commit()
    db.refresh(db_sequence)
    return {"id": db_sequence.id, "message": "Sequence created"}


@router.get("/{sequence_id}")
async def get_sequence(sequence_id: int, db: Session = Depends(get_db)):
    """Get sequence with all steps."""
    sequence = _get_sequence_or_404(db, sequence_id)

    return {
        "id": sequence.id,
        "name": sequence.name,
        "description": sequence.description,
        "steps": [_serialize_step(step) for step in _ordered(sequence)],
        "campaigns": [
            {"id": c.id, "name": c.name, "status": c.status.value if c.status else None}
            for c in sequence.campaigns
        ],
        "created_at": sequence.created_at.isoformat() if sequence.created_at else None,
        "updated_at": sequence.updated_at.isoformat() if sequence.updated_at else None,
    }


@router.put("/{sequence_id}")
async def update_sequence(
    sequence_id: int,
    update: SequenceUpdate,
    db: Session = Depends(get_db)
):
    """
    Update sequence details, and its steps when a `steps` list is sent.
    Leads already partway through keep their step position, so edits to
    upcoming steps apply to them too.
    """
    sequence = _get_sequence_or_404(db, sequence_id)

    update_data = update.model_dump(exclude_unset=True, exclude={"steps"})
    for field, value in update_data.items():
        setattr(sequence, field, value)

    if update.steps is not None:
        for step in update.steps:
            _check_variables(step.subject, step.body)
        _replace_steps(db, sequence, update.steps)

    db.commit()
    return {"message": "Sequence updated"}


@router.delete("/{sequence_id}")
async def delete_sequence(sequence_id: int, db: Session = Depends(get_db)):
    """Delete a sequence. Refused while an active or paused campaign uses it."""
    sequence = _get_sequence_or_404(db, sequence_id)

    in_flight = _in_flight_campaigns(db, sequence_id)
    if in_flight:
        names = ", ".join(c.name for c in in_flight)
        raise HTTPException(status_code=409, detail=f"Sequence is used by running or paused campaigns: {names}")

    for campaign in sequence.campaigns:
        campaign.sequence_id = None

    db.delete(sequence)
    db.commit()
    return {"message": "Sequence deleted"}


@router.post("/{sequence_id}/duplicate")
async def duplicate_sequence(sequence_id: int, db: Session = Depends(get_db)):
    """Copy a sequence and all its steps."""
    source = _get_sequence_or_404(db, sequence_id)

    copy = Sequence(name=f"{source.name} (copy)", description=source.description)
    for step in _ordered(source):
        copy.steps.append(SequenceStep(order=step.order, **{f: getattr(step, f) for f in STEP_FIELDS}))
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return {"id": copy.id, "message": "Sequence duplicated"}


@router.post("/{sequence_id}/steps")
async def add_step(sequence_id: int, step: StepCreate, db: Session = Depends(get_db)):
    """Add a step to a sequence - at `order` if given, else at the end."""
    sequence = _get_sequence_or_404(db, sequence_id)
    _check_variables(step.subject, step.body)

    steps = _ordered(sequence)
    db_step = SequenceStep(sequence_id=sequence_id, **{f: getattr(step, f) for f in STEP_FIELDS})
    position = len(steps) if step.order is None else max(0, min(step.order, len(steps)))
    steps.insert(position, db_step)
    sequence.steps.append(db_step)
    _renumber(steps)

    db.commit()
    db.refresh(db_step)
    return {"id": db_step.id, "message": "Step added"}


@router.put("/{sequence_id}/steps/{step_id}")
async def update_step(
    sequence_id: int,
    step_id: int,
    update: StepUpdate,
    db: Session = Depends(get_db)
):
    """Update a sequence step."""
    step = db.query(SequenceStep).filter(
        SequenceStep.id == step_id,
        SequenceStep.sequence_id == sequence_id
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    update_data = update.model_dump(exclude_unset=True)
    _check_variables(update_data.get("subject"), update_data.get("body"))
    for field, value in update_data.items():
        setattr(step, field, value)

    db.commit()
    return {"message": "Step updated"}


@router.delete("/{sequence_id}/steps/{step_id}")
async def delete_step(sequence_id: int, step_id: int, db: Session = Depends(get_db)):
    """Delete a sequence step."""
    sequence = _get_sequence_or_404(db, sequence_id)
    step = next((s for s in sequence.steps if s.id == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    sequence.steps.remove(step)
    _renumber(_ordered(sequence))
    db.commit()
    return {"message": "Step deleted"}


@router.post("/{sequence_id}/steps/reorder")
async def reorder_steps(
    sequence_id: int,
    step_ids: List[int],
    db: Session = Depends(get_db)
):
    """Reorder sequence steps. `step_ids` must list every step of the sequence exactly once."""
    sequence = _get_sequence_or_404(db, sequence_id)

    by_id = {s.id: s for s in sequence.steps}
    if sorted(step_ids) != sorted(by_id):
        raise HTTPException(status_code=400, detail="step_ids must contain each of the sequence's step ids exactly once")

    _renumber([by_id[step_id] for step_id in step_ids])
    db.commit()
    return {"message": "Steps reordered"}
