"""
The background worker: the campaign sender, warmup, the reply agent, inbox
placement checks, and queued jobs (scrapes, enrichment, verification,
personalization).

Normally all of this runs inside the API process (see main.py's lifespan) -
locally and on Render. It can also run as its own process, e.g. next to a
serverless API, with BACKGROUND_WORKER=external on the API:

    python -m app.worker

Stops cleanly on SIGTERM: no new work is picked up, and running jobs get a
moment to finish.
"""
import asyncio
import signal

import structlog

from app.database import init_db

logger = structlog.get_logger()


def start_schedulers() -> None:
    from app.services.campaign_engine import start_campaign_scheduler
    from app.services.placement import start_placement_scheduler
    from app.services.reply_agent import start_agent_scheduler
    from app.services.warmup import start_warmup_scheduler

    start_warmup_scheduler()
    start_campaign_scheduler()
    start_agent_scheduler()
    start_placement_scheduler()


def stop_schedulers() -> None:
    from app.services.campaign_engine import stop_campaign_scheduler
    from app.services.placement import stop_placement_scheduler
    from app.services.reply_agent import stop_agent_scheduler
    from app.services.warmup import stop_warmup_scheduler

    stop_warmup_scheduler()
    stop_campaign_scheduler()
    stop_agent_scheduler()
    stop_placement_scheduler()


def register_job_handlers() -> None:
    """Job handlers live next to the code they run; importing these registers them."""
    import app.routers.leads  # noqa: F401 - verify, enrich, personalize
    import app.routers.scrapers  # noqa: F401 - clutch, awwwards, google_maps


async def main() -> None:
    from app.services.jobs import job_worker_loop

    init_db()
    register_job_handlers()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    start_schedulers()
    logger.info("worker.started")
    jobs = asyncio.create_task(job_worker_loop(stop))
    await stop.wait()

    logger.info("worker.stopping")
    stop_schedulers()
    await jobs
    logger.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
