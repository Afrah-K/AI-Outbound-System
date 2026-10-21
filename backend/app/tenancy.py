"""
Workspace isolation: every row of user data belongs to one account
(owner_id), and every ORM query is automatically limited to the account
the current request - or scheduler pass - is working for.

How it works:
- `current_owner_id` holds the signed-in user's id for the duration of a
  request (set by the auth dependency) or of one scheduler pass per user
  (`run_per_owner`).
- A `do_orm_execute` hook adds `owner_id = <current user>` to every SELECT,
  UPDATE and DELETE touching an owned table - including relationship loads
  and Session.get() - so routers can keep writing plain queries.
- A `before_flush` hook stamps new rows with the current owner.

Deny by default: an ORM query on an owned table with no current owner raises
instead of silently returning everyone's data. Code that genuinely needs to
see all accounts (startup migration, listing users for the schedulers) must
opt in with `system_context()`; in that mode new rows inherit their owner
from the row they're attached to (inbox, campaign, person, ...).
"""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Awaitable, Callable, Optional

from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.orm import Session, with_loader_criteria

current_owner_id: ContextVar[Optional[int]] = ContextVar("current_owner_id", default=None)
_system_mode: ContextVar[bool] = ContextVar("tenancy_system_mode", default=False)


_NO_OWNER = -1  # an id no account has


class TenancyError(RuntimeError):
    """An owned table was queried without knowing whose workspace it is."""


def owned_models() -> list:
    """Every mapped model with an owner_id column."""
    from app.models.base import Base

    return [m.class_ for m in Base.registry.mappers if "owner_id" in m.columns]


@contextmanager
def owner_context(owner_id: int):
    token = current_owner_id.set(owner_id)
    mode = _system_mode.set(False)
    try:
        yield
    finally:
        current_owner_id.reset(token)
        _system_mode.reset(mode)


@contextmanager
def system_context():
    """See and write every account's data - migrations and scheduler bookkeeping only."""
    token = _system_mode.set(True)
    owner = current_owner_id.set(None)
    try:
        yield
    finally:
        _system_mode.reset(token)
        current_owner_id.reset(owner)


def reset_request_context() -> tuple:
    """Fresh, empty tenancy state - used per request so nothing leaks between requests on one connection."""
    return current_owner_id.set(None), _system_mode.set(False)


def restore_context(tokens: tuple) -> None:
    current_owner_id.reset(tokens[0])
    _system_mode.reset(tokens[1])


# Where a row created in system context gets its owner from (first match wins)
_OWNER_SOURCES = (
    ("inbox_id", "Inbox"),
    ("campaign_id", "Campaign"),
    ("person_id", "Person"),
    ("company_id", "Company"),
    ("sequence_id", "Sequence"),
    ("lead_list_id", "LeadList"),
    ("sender_inbox_id", "Inbox"),
)


def _infer_owner(session: Session, obj) -> Optional[int]:
    import app.models as models

    for attr, model_name in _OWNER_SOURCES:
        parent_id = getattr(obj, attr, None)
        if parent_id:
            model = getattr(models, model_name)
            with session.no_autoflush:
                owner = session.query(model.owner_id).filter(model.id == parent_id).scalar()
            if owner:
                return owner
    return None


def install(session_class=Session) -> None:
    """Register the query filter and insert hook on every Session."""

    @event.listens_for(session_class, "do_orm_execute")
    def _scope_queries(execute_state):
        if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
            return
        if execute_state.execution_options.get("skip_tenancy"):
            return

        mappers = getattr(execute_state, "all_mappers", None) or []
        touched = [m.class_ for m in mappers if "owner_id" in m.columns]
        if not touched and not execute_state.is_select:
            return

        if _system_mode.get():
            return
        owner = current_owner_id.get()
        if owner is None:
            if touched:
                names = ", ".join(sorted({c.__name__ for c in touched}))
                raise TenancyError(f"Query on {names} without a signed-in user (no workspace to scope it to)")
            # Owned tables can hide inside a statement (e.g. count() wraps the query in
            # a subquery), so anything else still gets a filter that matches no rows -
            # with no workspace, the answer is "nothing", never "everyone's".
            owner = _NO_OWNER

        for model in owned_models():
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(model, lambda cls: cls.owner_id == owner, include_aliases=True)
            )

    @event.listens_for(session_class, "before_flush")
    def _stamp_owner(session, flush_context, instances):
        owner = current_owner_id.get()
        for obj in session.new:
            if "owner_id" not in sa_inspect(obj).mapper.columns or getattr(obj, "owner_id", None):
                continue
            if owner is not None:
                obj.owner_id = owner
            elif _system_mode.get():
                obj.owner_id = _infer_owner(session, obj)
            else:
                raise TenancyError(f"Creating a {type(obj).__name__} without a signed-in user")


async def run_per_owner(fn: Callable[..., Awaitable], *args, **kwargs) -> dict:
    """
    Run `fn(db, ...)` once per account, each in its own session scoped to that
    account - how the background schedulers stay inside one workspace at a time.
    Returns {owner_id: result}; one account failing doesn't stop the others.
    """
    import structlog

    from app.database import SessionLocal
    from app.models import User

    logger = structlog.get_logger()
    with system_context():
        db = SessionLocal()
        try:
            owner_ids = [uid for (uid,) in db.query(User.id)]
        finally:
            db.close()

    results = {}
    for owner_id in owner_ids:
        with owner_context(owner_id):
            db = SessionLocal()
            try:
                results[owner_id] = await fn(db, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.error("tenancy.owner_run_failed", owner_id=owner_id, fn=fn.__name__, error=str(exc))
                db.rollback()
            finally:
                db.close()
    return results
