"""Booking (Calendly link) and Calendar (booked calls) endpoints."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import calendly

router = APIRouter()


@router.get("/settings")
async def calendar_settings(db: Session = Depends(get_db)):
    """The booking link and whether a Calendly token is saved (the token itself is never returned)."""
    return {**calendly.settings_payload(calendly.get_settings(db)), "required_scopes": list(calendly.REQUIRED_SCOPES)}


class CalendarSettingsUpdate(BaseModel):
    calendly_url: Optional[str] = None
    # Send "" to remove the saved token.
    calendly_token: Optional[str] = None


@router.put("/settings")
async def update_calendar_settings(payload: CalendarSettingsUpdate, db: Session = Depends(get_db)):
    row = calendly.get_settings(db)
    data = payload.model_dump(exclude_unset=True)

    if "calendly_token" in data:
        token = (data["calendly_token"] or "").strip()
        if token:
            try:
                user = await calendly.current_user(token)
            except calendly.CalendlyError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Couldn't reach Calendly: {exc}")
            row.calendly_token = token
            # Fill in the booking link from the account if none was set yet.
            if not row.calendly_url and not data.get("calendly_url") and user.get("scheduling_url"):
                row.calendly_url = user["scheduling_url"]
        else:
            row.calendly_token = None

    if "calendly_url" in data:
        url = (data["calendly_url"] or "").strip()
        if url and not calendly.valid_booking_url(url):
            raise HTTPException(status_code=400, detail="Use your Calendly link, e.g. https://calendly.com/your-name/30min")
        row.calendly_url = url or None

    db.commit()
    return calendly.settings_payload(row)


@router.get("/events")
async def calendar_events(
    start: Optional[datetime] = Query(None, description="UTC; defaults to now"),
    end: Optional[datetime] = Query(None, description="UTC; defaults to start + 30 days"),
    include_canceled: bool = False,
    db: Session = Depends(get_db),
):
    """Booked Calendly calls in a time range, each invitee matched to a prospect (and their campaign) when known."""
    start = (start or datetime.utcnow()).replace(tzinfo=None)
    end = (end or start + timedelta(days=30)).replace(tzinfo=None)
    if end <= start:
        raise HTTPException(status_code=400, detail="end must be after start")
    if end - start > timedelta(days=100):
        raise HTTPException(status_code=400, detail="Ask for at most 100 days at a time")
    try:
        events = await calendly.fetch_events(db, start, end, include_canceled=include_canceled)
    except calendly.CalendlyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't reach Calendly: {exc}")
    return {"events": events, "total": len(events)}
