"""
Calendly integration: the booking link (embedded on the Book a Call page and
offered to the reply agent) and, with a personal access token, the booked
calls shown on the Calendar page - each matched to the prospect who booked.
"""
import asyncio
import re
from datetime import datetime
from typing import Optional

import httpx
import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CampaignLead, IntegrationSettings, Person

logger = structlog.get_logger()

API = "https://api.calendly.com"
MAX_EVENTS = 200

_CALENDLY_URL = re.compile(r"^https://(www\.)?calendly\.com/[^\s]+$", re.IGNORECASE)


class CalendlyError(Exception):
    pass


def get_settings(db: Session) -> IntegrationSettings:
    row = db.query(IntegrationSettings).first()
    if not row:
        row = IntegrationSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def booking_url(db: Session) -> Optional[str]:
    return get_settings(db).calendly_url or None


def valid_booking_url(url: str) -> bool:
    return bool(_CALENDLY_URL.match((url or "").strip()))


def settings_payload(row: IntegrationSettings) -> dict:
    token = row.calendly_token or ""
    return {
        "calendly_url": row.calendly_url or "",
        "has_token": bool(token),
        "token_hint": f"...{token[-4:]}" if len(token) > 8 else ("set" if token else ""),
    }


# Read-only scopes the integration needs when creating a Calendly personal access token.
REQUIRED_SCOPES = ("users:read", "scheduled_events:read")


def _find_required_scopes(payload) -> list:
    """Calendly's 403 body lists the missing scopes in a `required_scopes` array (location varies)."""
    if isinstance(payload, dict):
        if isinstance(payload.get("required_scopes"), list):
            return [str(s) for s in payload["required_scopes"]]
        for value in payload.values():
            found = _find_required_scopes(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_required_scopes(item)
            if found:
                return found
    return []


async def _get(client: httpx.AsyncClient, url: str, token: str, params: Optional[dict] = None) -> dict:
    resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 401:
        raise CalendlyError("Calendly rejected the access token - create a new one at calendly.com/integrations/api_webhooks")
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code == 403:
            missing = _find_required_scopes(body)
            needed = ", ".join(REQUIRED_SCOPES)
            raise CalendlyError(
                (f"Your Calendly token is missing the {', '.join(missing)} permission. " if missing else "Your Calendly token doesn't have the permissions this needs. ")
                + f"Create a new personal access token with these read-only scopes: {needed}."
            )
        detail = (body or {}).get("message") if isinstance(body, dict) else None
        raise CalendlyError(f"Calendly API error ({resp.status_code}): {detail or resp.text}")
    return resp.json()


async def current_user(token: str) -> dict:
    """The Calendly account the token belongs to: {uri, name, email, scheduling_url, timezone}."""
    async with httpx.AsyncClient(timeout=15) as client:
        data = await _get(client, f"{API}/users/me", token)
    user = data.get("resource", {})
    return {
        "uri": user.get("uri"),
        "name": user.get("name"),
        "email": user.get("email"),
        "scheduling_url": user.get("scheduling_url"),
        "timezone": user.get("timezone"),
    }


def _join_url(location: Optional[dict]) -> Optional[str]:
    if not location:
        return None
    return location.get("join_url") or (location.get("location") if str(location.get("location", "")).startswith("http") else None)


def _location_label(location: Optional[dict]) -> Optional[str]:
    if not location:
        return None
    kind = (location.get("type") or "").replace("_", " ")
    where = location.get("location")
    if where and not str(where).startswith("http"):
        return where
    return {"google conference": "Google Meet", "zoom": "Zoom", "microsoft teams conference": "Microsoft Teams"}.get(kind, kind.title() or None)


async def fetch_events(db: Session, start: datetime, end: datetime, include_canceled: bool = False) -> list:
    """Booked calls between start and end (naive UTC), with invitees matched to prospects."""
    token = get_settings(db).calendly_token
    if not token:
        raise CalendlyError("Add a Calendly personal access token to see booked calls")

    async with httpx.AsyncClient(timeout=20) as client:
        user = (await _get(client, f"{API}/users/me", token)).get("resource", {})
        params = {
            "user": user.get("uri"),
            "min_start_time": start.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            "max_start_time": end.strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
            "count": 100,
            "sort": "start_time:asc",
        }
        if not include_canceled:
            params["status"] = "active"

        events, url = [], f"{API}/scheduled_events"
        while url and len(events) < MAX_EVENTS:
            page = await _get(client, url, token, params)
            events.extend(page.get("collection", []))
            url, params = (page.get("pagination") or {}).get("next_page"), None

        semaphore = asyncio.Semaphore(5)

        async def invitees_for(event):
            async with semaphore:
                try:
                    data = await _get(client, f"{event['uri']}/invitees", token, {"count": 100})
                    return data.get("collection", [])
                except CalendlyError as exc:
                    logger.warning("calendly.invitees_failed", event=event.get("uri"), error=str(exc))
                    return []

        all_invitees = await asyncio.gather(*(invitees_for(e) for e in events))

    emails = {(i.get("email") or "").lower() for invs in all_invitees for i in invs if i.get("email")}
    people = {
        p.email.lower(): p for p in db.query(Person).filter(func.lower(Person.email).in_(emails)).all()
    } if emails else {}
    campaign_by_person = {}
    if people:
        for lead in (
            db.query(CampaignLead)
            .filter(CampaignLead.person_id.in_([p.id for p in people.values()]))
            .order_by(CampaignLead.created_at.desc())
            .all()
        ):
            campaign_by_person.setdefault(lead.person_id, lead.campaign)

    result = []
    for event, invitees in zip(events, all_invitees):
        guest_list = []
        for inv in invitees:
            person = people.get((inv.get("email") or "").lower())
            campaign = campaign_by_person.get(person.id) if person else None
            guest_list.append({
                "name": inv.get("name"),
                "email": inv.get("email"),
                "status": inv.get("status"),
                "reschedule_url": inv.get("reschedule_url"),
                "cancel_url": inv.get("cancel_url"),
                "answers": [
                    {"question": qa.get("question"), "answer": qa.get("answer")}
                    for qa in (inv.get("questions_and_answers") or [])
                ],
                "prospect": {
                    "id": person.id,
                    "status": person.status.value if person.status else None,
                    "company_name": person.company.name if person.company else None,
                } if person else None,
                "campaign": {"id": campaign.id, "name": campaign.name} if campaign else None,
            })
        result.append({
            "uri": event.get("uri"),
            "name": event.get("name"),
            "status": event.get("status"),
            "start_time": event.get("start_time"),
            "end_time": event.get("end_time"),
            "location": _location_label(event.get("location")),
            "join_url": _join_url(event.get("location")),
            "invitees": guest_list,
        })
    return result
