from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel

from app.database import get_db
from app.models import Sequence, SequenceStep

router = APIRouter()


class StepCreate(BaseModel):
    order: int
    delay_days: int = 0
    delay_hours: int = 0
    subject: str
    body: str
    use_gpt: bool = False
    gpt_prompt: Optional[str] = None


class StepUpdate(BaseModel):
    delay_days: Optional[int] = None
    delay_hours: Optional[int] = None
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
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sequences
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("")
async def create_sequence(sequence: SequenceCreate, db: Session = Depends(get_db)):
    """Create a new sequence."""
    db_sequence = Sequence(
        name=sequence.name,
        description=sequence.description,
    )
    db.add(db_sequence)
    db.flush()

    # Add steps if provided
    if sequence.steps:
        for step_data in sequence.steps:
            step = SequenceStep(
                sequence_id=db_sequence.id,
                order=step_data.order,
                delay_days=step_data.delay_days,
                delay_hours=step_data.delay_hours,
                subject=step_data.subject,
                body=step_data.body,
                use_gpt=step_data.use_gpt,
                gpt_prompt=step_data.gpt_prompt,
            )
            db.add(step)

    db.commit()
    db.refresh(db_sequence)
    return {"id": db_sequence.id, "message": "Sequence created"}


@router.get("/{sequence_id}")
async def get_sequence(sequence_id: int, db: Session = Depends(get_db)):
    """Get sequence with all steps."""
    sequence = db.query(Sequence).filter(Sequence.id == sequence_id).first()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    return {
        "id": sequence.id,
        "name": sequence.name,
        "description": sequence.description,
        "steps": [
            {
                "id": step.id,
                "order": step.order,
                "delay_days": step.delay_days,
                "delay_hours": step.delay_hours,
                "subject": step.subject,
                "body": step.body,
                "use_gpt": step.use_gpt,
                "gpt_prompt": step.gpt_prompt,
            }
            for step in sorted(sequence.steps, key=lambda s: s.order)
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
    """Update sequence details."""
    sequence = db.query(Sequence).filter(Sequence.id == sequence_id).first()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(sequence, field, value)

    db.commit()
    return {"message": "Sequence updated"}


@router.delete("/{sequence_id}")
async def delete_sequence(sequence_id: int, db: Session = Depends(get_db)):
    """Delete a sequence."""
    sequence = db.query(Sequence).filter(Sequence.id == sequence_id).first()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    db.delete(sequence)
    db.commit()
    return {"message": "Sequence deleted"}


@router.post("/{sequence_id}/steps")
async def add_step(sequence_id: int, step: StepCreate, db: Session = Depends(get_db)):
    """Add a step to a sequence."""
    sequence = db.query(Sequence).filter(Sequence.id == sequence_id).first()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    db_step = SequenceStep(
        sequence_id=sequence_id,
        order=step.order,
        delay_days=step.delay_days,
        delay_hours=step.delay_hours,
        subject=step.subject,
        body=step.body,
        use_gpt=step.use_gpt,
        gpt_prompt=step.gpt_prompt,
    )
    db.add(db_step)
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
    for field, value in update_data.items():
        setattr(step, field, value)

    db.commit()
    return {"message": "Step updated"}


@router.delete("/{sequence_id}/steps/{step_id}")
async def delete_step(sequence_id: int, step_id: int, db: Session = Depends(get_db)):
    """Delete a sequence step."""
    step = db.query(SequenceStep).filter(
        SequenceStep.id == step_id,
        SequenceStep.sequence_id == sequence_id
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    db.delete(step)
    db.commit()
    return {"message": "Step deleted"}


@router.post("/{sequence_id}/steps/reorder")
async def reorder_steps(
    sequence_id: int,
    step_ids: List[int],
    db: Session = Depends(get_db)
):
    """Reorder sequence steps."""
    sequence = db.query(Sequence).filter(Sequence.id == sequence_id).first()
    if not sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    for new_order, step_id in enumerate(step_ids):
        step = db.query(SequenceStep).filter(
            SequenceStep.id == step_id,
            SequenceStep.sequence_id == sequence_id
        ).first()
        if step:
            step.order = new_order

    db.commit()
    return {"message": "Steps reordered"}
