"""
Copy everything from the local SQLite database into the production Postgres
database (e.g. Neon on Vercel) - accounts, prospects, campaigns, email
history, connected inboxes, settings - so the deployed app starts with your
existing work.

USAGE (from backend/):
    python scripts/migrate_sqlite_to_postgres.py "postgresql://user:pass@host/db?sslmode=require"
    python scripts/migrate_sqlite_to_postgres.py "$DATABASE_URL_UNPOOLED" --sqlite data/outbound.db

Use the direct (unpooled) connection string for this. The target must be
empty: the script creates the tables itself and refuses to run if any data
is already there, so it can't duplicate or overwrite anything.
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def main():
    parser = argparse.ArgumentParser(description="Copy the local SQLite data into Postgres.")
    parser.add_argument("postgres_url", help="Target Postgres connection string (direct/unpooled)")
    parser.add_argument("--sqlite", default=str(BACKEND / "data" / "outbound.db"), help="Source SQLite file")
    args = parser.parse_args()

    source_path = Path(args.sqlite)
    if not source_path.exists():
        sys.exit(f"No SQLite database at {source_path}")

    # Point the app at the target before importing it, so init_db() builds the Postgres schema
    os.environ["DATABASE_URL"] = args.postgres_url
    from sqlalchemy import create_engine, inspect, select, text

    from app.database import DATABASE_URL, engine as target, init_db
    from app.models.base import Base

    if DATABASE_URL.startswith("sqlite"):
        sys.exit("The target must be a Postgres URL")

    source = create_engine(f"sqlite:///{source_path}")
    source_tables = set(inspect(source).get_table_names())
    if "users" not in source_tables:
        sys.exit("The SQLite database predates accounts - start the app once locally first so it's upgraded")

    with target.connect() as conn:
        existing = set(inspect(conn).get_table_names())
        if "users" in existing and conn.execute(text("SELECT COUNT(*) FROM users")).scalar():
            sys.exit("The target database already has data - refusing to copy over it")

    print("Creating tables in Postgres...")
    init_db()

    copied, ids, cleared, skipped = {}, {}, {}, {}
    with source.connect() as src, target.begin() as dst:
        for table in Base.metadata.sorted_tables:  # parents before children
            if table.name not in source_tables:
                continue
            src_columns = {c["name"] for c in inspect(source).get_columns(table.name)}
            columns = [c for c in table.columns if c.name in src_columns]
            rows = [dict(r._mapping) for r in src.execute(select(*columns))]

            # SQLite never enforced foreign keys, so some rows point at things deleted
            # long ago (e.g. emails from a deleted campaign). Postgres refuses those:
            # clear the reference when it's optional, otherwise leave the row out.
            kept = []
            for row in rows:
                ok = True
                for column in columns:
                    for fk in column.foreign_keys:
                        value = row.get(column.name)
                        target_table = fk.column.table.name
                        if value is None or target_table not in ids or value in ids[target_table]:
                            continue
                        if column.nullable:
                            row[column.name] = None
                            cleared[f"{table.name}.{column.name}"] = cleared.get(f"{table.name}.{column.name}", 0) + 1
                        else:
                            ok = False
                if ok:
                    kept.append(row)
                else:
                    skipped[table.name] = skipped.get(table.name, 0) + 1

            for start in range(0, len(kept), 500):
                dst.execute(table.insert(), kept[start:start + 500])
            copied[table.name] = len(kept)
            pk = list(table.primary_key.columns)
            if len(pk) == 1:
                ids[table.name] = {row[pk[0].name] for row in kept}

        # Integer ids were copied as-is, so move each id sequence past the highest one
        for table in Base.metadata.sorted_tables:
            pk = list(table.primary_key.columns)
            if len(pk) == 1 and pk[0].type.python_type is int and copied.get(table.name):
                dst.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), "
                    f"(SELECT COALESCE(MAX({pk[0].name}), 1) FROM \"{table.name}\"))"
                ))

    for name, count in copied.items():
        if count:
            print(f"  {name}: {count}")
    for name, count in cleared.items():
        print(f"  cleared {count} link(s) in {name} to rows deleted earlier")
    for name, count in skipped.items():
        print(f"  left out {count} {name} row(s) pointing at rows deleted earlier")
    print(f"Done - copied {sum(copied.values())} rows from {source_path.name}.")


if __name__ == "__main__":
    main()
