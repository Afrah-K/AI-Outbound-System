"""
Background jobs for long-running, user-started work (scrapes, enrichment,
list verification, personalization), stored in the database.

The API queues a job (`enqueue_job`) and returns at once; a worker claims it
and runs the handler registered for its kind (`@job_handler("...")`) inside
the owner's workspace, saving progress as it goes. Because the job lives in
the database, any API instance can report on it - so this works both as one
local process (the worker runs in-process, see main.py) and on Vercel, where
the API is serverless and the worker is a separate always-on daemon
(app/worker.py).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

import structlog
from sqlalchemy.orm import Session

from app.config import settings

logger = structlog.get_logger()

MAX_CONCURRENT_JOBS = 3
SAVE_PROGRESS_EVERY = 1.0                  # seconds between progress writes
HEARTBEAT_EVERY = 20                       # seconds
STALE_AFTER = timedelta(minutes=3)         # running, but no heartbeat for this long -> its worker died
KEEP_FINISHED_FOR = timedelta(days=7)

Handler = Callable[["JobRun", dict], Awaitable[Any]]
_handlers: dict[str, Handler] = {}
_wakeup: Optional[asyncio.Event] = None    # lets an in-process worker start a new job immediately


class JobFailed(Exception):
    """Raise from a handler to fail the job with a message meant for the user."""


def job_handler(kind: str):
    """Register the function that runs jobs of this kind: async fn(job: JobRun, payload: dict) -> result."""
    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn
    return register


def to_dict(job) -> dict:
    """The API shape for a job. Queued jobs read as running - they start within a moment."""
    return {
        "job_id": job.id,
        "kind": job.kind,
        "status": "running" if job.status == "queued" else job.status,
        "processed": job.processed or 0,
        "total": job.total or 0,
        "message": job.message or ("Waiting to start..." if job.status == "queued" else ""),
        "error": job.error,
        "extra": job.extra or {},
        "created_at": job.created_at.isoformat() + "Z" if job.created_at else None,
        "finished_at": job.finished_at.isoformat() + "Z" if job.finished_at else None,
        # Results can be large - only sent once there's something final to send
        "result": job.result if job.status == "completed" else None,
    }


def enqueue_job(db: Session, kind: str, payload: dict, total: int = 0, message: str = "") -> dict:
    """Queue work for the worker. Must run in a signed-in request: the job belongs to that account."""
    from app.models import BackgroundJob

    if kind not in _handlers:
        raise ValueError(f"No handler registered for job kind '{kind}'")
    job = BackgroundJob(
        id=str(uuid.uuid4()), kind=kind, status="queued", payload=payload,
        total=total, processed=0, message=message, extra={},
    )
    db.add(job)
    db.commit()
    if _wakeup is not None:
        _wakeup.set()
    return to_dict(job)


def get_job(db: Session, job_id: str, kind: Optional[str] = None):
    """The job if it exists in the signed-in account (tenancy scopes the query), else None."""
    from app.models import BackgroundJob

    query = db.query(BackgroundJob).filter(BackgroundJob.id == job_id)
    if kind:
        query = query.filter(BackgroundJob.kind == kind)
    return query.first()


class JobRun:
    """What a handler gets: its job's id and payload, and a way to report progress."""

    def __init__(self, job_id: str, owner_id: int, total: int):
        self.id = job_id
        self.owner_id = owner_id
        self.processed = 0
        self.total = total or 0
        self.message = ""
        self.extra: dict = {}
        self._last_save = 0.0
        self._dirty = False

    def progress(self, message: Optional[str] = None, done: Optional[int] = None, total: Optional[int] = None) -> None:
        # Bare log lines (raw URLs etc.) aren't user-facing - only messages that
        # come with a progress count replace the status text.
        if message and (done is not None or total is not None):
            self.message = message.strip()[:500]
        if total is not None:
            self.total = max(total, self.processed)
        if done is not None:
            self.processed = done
            self.total = max(self.total, done)
        self._dirty = True
        self.save()

    def set_extra(self, **values) -> None:
        self.extra.update(values)
        self._dirty = True
        self.save()

    def save(self, force: bool = False) -> None:
        """Write progress to the job row - at most once a second unless forced."""
        if not self._dirty and not force:
            return
        now = time.monotonic()
        if not force and now - self._last_save < SAVE_PROGRESS_EVERY:
            return
        self._last_save, self._dirty = now, False
        _update(self.id, processed=self.processed, total=self.total, message=self.message,
                extra=dict(self.extra), heartbeat_at=datetime.utcnow())


def _update(job_id: str, **fields) -> None:
    from app.database import SessionLocal
    from app.models import BackgroundJob

    db = SessionLocal()
    try:
        db.query(BackgroundJob).filter(BackgroundJob.id == job_id).update(fields, synchronize_session=False)
        db.commit()
    finally:
        db.close()


async def _run(job_id: str, owner_id: int, kind: str, payload: dict, total: int) -> None:
    from app.tenancy import owner_context

    # The whole job runs inside its owner's workspace (see app/tenancy.py)
    with owner_context(owner_id):
        run = JobRun(job_id, owner_id, total)

        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_EVERY)
                _update(job_id, heartbeat_at=datetime.utcnow())

        beat = asyncio.create_task(heartbeat())
        try:
            result = await _handlers[kind](run, payload or {})
            run.save(force=True)
            _update(job_id, status="completed", result=result, processed=max(run.processed, run.total),
                    total=run.total, extra=dict(run.extra), finished_at=datetime.utcnow())
        except Exception as exc:  # noqa: BLE001 - surfaced to the user on the job
            message = getattr(exc, "detail", None) or str(exc) or exc.__class__.__name__
            if not isinstance(exc, JobFailed) and not getattr(exc, "detail", None):
                logger.exception("jobs.failed", kind=kind, job_id=job_id)
            run.save(force=True)
            _update(job_id, status="failed", error=str(message)[:2000], finished_at=datetime.utcnow())
        finally:
            beat.cancel()


def _claim_queued(limit: int) -> list[tuple]:
    """Atomically take up to `limit` queued jobs (safe with several workers: the UPDATE only succeeds once)."""
    from app.database import SessionLocal
    from app.models import BackgroundJob
    from app.tenancy import system_context

    claimed = []
    with system_context():
        db = SessionLocal()
        try:
            candidates = (
                db.query(BackgroundJob.id, BackgroundJob.owner_id, BackgroundJob.kind, BackgroundJob.payload, BackgroundJob.total)
                .filter(BackgroundJob.status == "queued")
                .order_by(BackgroundJob.created_at)
                .limit(limit)
                .all()
            )
            now = datetime.utcnow()
            for job_id, owner_id, kind, payload, total in candidates:
                taken = (
                    db.query(BackgroundJob)
                    .filter(BackgroundJob.id == job_id, BackgroundJob.status == "queued")
                    .update({"status": "running", "started_at": now, "heartbeat_at": now}, synchronize_session=False)
                )
                db.commit()
                if taken:
                    claimed.append((job_id, owner_id, kind, payload, total))
        finally:
            db.close()
    return claimed


def _housekeeping(running_here: set) -> None:
    """Fail jobs whose worker died mid-run; drop old finished jobs."""
    from app.database import SessionLocal
    from app.models import BackgroundJob
    from app.tenancy import system_context

    now = datetime.utcnow()
    with system_context():
        db = SessionLocal()
        try:
            stale = (
                db.query(BackgroundJob)
                .filter(BackgroundJob.status == "running", BackgroundJob.heartbeat_at < now - STALE_AFTER)
                .all()
            )
            for job in stale:
                if job.id in running_here:
                    continue
                job.status = "failed"
                job.error = "Interrupted - the worker restarted. Please run it again."
                job.finished_at = now
            db.query(BackgroundJob).filter(
                BackgroundJob.status.in_(("completed", "failed")),
                BackgroundJob.finished_at < now - KEEP_FINISHED_FOR,
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()


async def job_worker_loop(stop: Optional[asyncio.Event] = None) -> None:
    """Claim and run queued jobs forever (until `stop` is set), a few at a time."""
    global _wakeup
    _wakeup = asyncio.Event()
    stop = stop or asyncio.Event()
    running: dict[str, asyncio.Task] = {}
    last_housekeeping = 0.0
    logger.info("jobs.worker_started", max_concurrent=MAX_CONCURRENT_JOBS)

    while not stop.is_set():
        try:
            for job_id in [j for j, task in running.items() if task.done()]:
                running.pop(job_id)
            free = MAX_CONCURRENT_JOBS - len(running)
            if free > 0:
                for job_id, owner_id, kind, payload, total in await asyncio.to_thread(_claim_queued, free):
                    if kind not in _handlers:
                        _update(job_id, status="failed", error=f"Unknown job kind '{kind}'", finished_at=datetime.utcnow())
                        continue
                    running[job_id] = asyncio.create_task(_run(job_id, owner_id, kind, payload, total))
            if time.monotonic() - last_housekeeping > 60:
                last_housekeeping = time.monotonic()
                await asyncio.to_thread(_housekeeping, set(running))
        except Exception as exc:  # noqa: BLE001 - keep the worker alive
            logger.error("jobs.worker_error", error=str(exc))

        _wakeup.clear()
        try:
            # A job queued by this same process wakes the loop at once; otherwise poll
            await asyncio.wait_for(_wakeup.wait(), timeout=settings.job_poll_seconds)
        except asyncio.TimeoutError:
            pass

    # Shutting down: let running jobs finish briefly; anything left is reported as interrupted
    if running:
        await asyncio.wait(running.values(), timeout=20)
