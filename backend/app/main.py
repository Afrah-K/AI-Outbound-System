from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from app.config import settings
from app.database import init_db

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    logger.info("Starting Cold Email Platform...", worker=settings.worker_mode)
    if settings.worker_mode == "in_process":
        # Local / single server: migrations, schedulers and the job worker all run here.
        # On Vercel the API is serverless and the separate worker (app/worker.py) does this.
        import asyncio

        from app.services.jobs import job_worker_loop
        from app.worker import start_schedulers, stop_schedulers

        init_db()
        logger.info("Database initialized")
        start_schedulers()
        stop = asyncio.Event()
        jobs = asyncio.create_task(job_worker_loop(stop))

    yield

    # Shutdown
    logger.info("Shutting down Cold Email Platform...")
    if settings.worker_mode == "in_process":
        stop_schedulers()
        stop.set()
        await jobs


app = FastAPI(
    title=settings.app_name,
    description="A localhost cold email platform for managing outbound campaigns",
    version="1.0.0",
    lifespan=lifespan,
)

class TenancyResetMiddleware:
    """
    Start every request with no signed-in workspace, so nothing carries over
    between requests sharing one connection. require_user then sets it.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        from app.tenancy import reset_request_context, restore_context

        tokens = reset_request_context()
        try:
            await self.app(scope, receive, send)
        finally:
            restore_context(tokens)


app.add_middleware(TenancyResetMiddleware)

# CORS middleware for frontend - cookies (the login session) need explicit origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Import and include routers
from app.routers import auth, inboxes, leads, campaigns, sequences, analytics, system, scrapers, unibox, warmup, calendar
from app.services.auth import require_user

# Public: signing in
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])

# Everything else needs a signed-in user, and only ever sees that user's workspace
signed_in = [Depends(require_user)]
app.include_router(inboxes.router, prefix="/api/v1/inboxes", tags=["Inboxes"], dependencies=signed_in)
app.include_router(warmup.router, prefix="/api/v1/warmup", tags=["Warmup"], dependencies=signed_in)
app.include_router(leads.router, prefix="/api/v1/leads", tags=["Leads"], dependencies=signed_in)
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["Campaigns"], dependencies=signed_in)
app.include_router(sequences.router, prefix="/api/v1/sequences", tags=["Sequences"], dependencies=signed_in)
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"], dependencies=signed_in)
app.include_router(system.router, prefix="/api/v1/system", tags=["System"], dependencies=signed_in)
app.include_router(scrapers.router, prefix="/api/v1/scrapers", tags=["Scrapers"], dependencies=signed_in)
app.include_router(unibox.router, prefix="/api/v1/unibox", tags=["Unibox"], dependencies=signed_in)
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["Calendar"], dependencies=signed_in)


@app.get("/")
async def root():
    """Root endpoint - API health check."""
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
