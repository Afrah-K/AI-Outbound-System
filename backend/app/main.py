from fastapi import FastAPI
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
    logger.info("Starting Cold Email Platform...")
    init_db()
    logger.info("Database initialized")

    # Import and start scheduler here when implemented
    # from app.tasks.scheduler import start_scheduler
    # start_scheduler()

    yield

    # Shutdown
    logger.info("Shutting down Cold Email Platform...")
    # Stop scheduler here when implemented
    # from app.tasks.scheduler import stop_scheduler
    # stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    description="A localhost cold email platform for managing outbound campaigns",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Import and include routers
from app.routers import inboxes, leads, campaigns, sequences, analytics, system

app.include_router(inboxes.router, prefix="/api/v1/inboxes", tags=["Inboxes"])
app.include_router(leads.router, prefix="/api/v1/leads", tags=["Leads"])
app.include_router(campaigns.router, prefix="/api/v1/campaigns", tags=["Campaigns"])
app.include_router(sequences.router, prefix="/api/v1/sequences", tags=["Sequences"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])


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
