from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

def _database_url(url: str) -> str:
    # Neon / Vercel Postgres hand out postgres://...; SQLAlchemy wants postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _database_url(settings.database_url)
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    # FastAPI uses sessions across threads
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=settings.debug)
else:
    # Hosted Postgres (e.g. Neon on Vercel): small pools per instance, and check
    # connections before use since serverless instances sit idle between requests
    engine = create_engine(
        DATABASE_URL, echo=settings.debug, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Every ORM query is limited to the signed-in account's rows (see app/tenancy.py)
from app.tenancy import install as _install_tenancy  # noqa: E402

_install_tenancy()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables, and bring an existing database up to date."""
    from app.models.base import Base
    from app.tenancy import system_context

    with system_context():
        Base.metadata.create_all(bind=engine)
        _add_missing_columns(Base.metadata)
        _add_missing_indexes(Base.metadata)
        _scope_unique_indexes()
        _assign_unowned_rows()


def _add_missing_indexes(metadata) -> None:
    """Indexes on columns added by _add_missing_columns (e.g. owner_id) - create_all skips existing tables."""
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            for index in table.indexes:
                index.create(bind=conn, checkfirst=True)


# Single-column unique indexes from before accounts existed, which must become
# unique per account instead: (table, old index, column, new per-account unique index)
_GLOBAL_TO_SCOPED_UNIQUE = (
    ("people", "ix_people_email", "email", "uq_people_owner_email"),
    ("companies", "ix_companies_domain", "domain", "uq_companies_owner_domain"),
)


def _scope_unique_indexes() -> None:
    """
    Swap the old "email unique across the whole database" indexes for
    "unique within one account". Only touches indexes, never row data.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, old_index, column, scoped in _GLOBAL_TO_SCOPED_UNIQUE:
            if table not in tables:
                continue
            indexes = {i["name"]: i for i in inspector.get_indexes(table)}
            old = indexes.get(old_index)
            if old and old.get("unique"):
                conn.execute(text(f'DROP INDEX "{old_index}"'))
                conn.execute(text(f'CREATE INDEX "{old_index}" ON "{table}" ("{column}")'))
            if scoped not in indexes and not any(
                u.get("name") == scoped for u in inspector.get_unique_constraints(table)
            ):
                conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{scoped}" ON "{table}" (owner_id, "{column}")'))


def _assign_unowned_rows() -> None:
    """
    Rows from before accounts existed belong to INITIAL_OWNER_EMAIL's account,
    which is created (Google sign-in only, no password) if it doesn't exist yet.
    """
    import structlog
    from sqlalchemy import text

    from app.models import User
    from app.tenancy import owned_models

    logger = structlog.get_logger()
    tables = [m.__tablename__ for m in owned_models()]
    with engine.begin() as conn:
        unowned = {t: conn.execute(text(f'SELECT COUNT(*) FROM "{t}" WHERE owner_id IS NULL')).scalar() for t in tables}
    unowned = {t: n for t, n in unowned.items() if n}
    if not unowned:
        return

    email = (settings.initial_owner_email or "").strip().lower()
    if not email:
        logger.warning("tenancy.unowned_rows_need_owner", tables=unowned,
                       hint="Set INITIAL_OWNER_EMAIL in backend/.env so existing data gets an owner")
        return

    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.email == email).first()
        if owner is None:
            owner = User(email=email, name=email.split("@")[0])
            db.add(owner)
            db.commit()
        owner_id = owner.id
    finally:
        db.close()

    with engine.begin() as conn:
        for table in unowned:
            conn.execute(text(f'UPDATE "{table}" SET owner_id = :owner WHERE owner_id IS NULL'), {"owner": owner_id})
    logger.info("tenancy.assigned_existing_data", owner=email, rows=unowned)


def _add_missing_columns(metadata) -> None:
    """
    create_all() only creates missing tables - it never adds a column a model
    gained later. Add those columns (ALTER TABLE ... ADD COLUMN, which never
    touches existing data) so model changes work on an existing local DB
    without a full Alembic migration.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                default = column.default.arg if column.default is not None and column.default.is_scalar else None
                if isinstance(default, bool):
                    ddl += f" DEFAULT {int(default)}"
                elif isinstance(default, (int, float)):
                    ddl += f" DEFAULT {default}"
                elif isinstance(default, str):
                    ddl += " DEFAULT '" + default.replace("'", "''") + "'"
                conn.execute(text(ddl))
