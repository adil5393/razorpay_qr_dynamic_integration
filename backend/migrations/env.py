import os
import sys
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from db import Base  # noqa: E402
import models  # noqa: E402,F401

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=os.environ["DATABASE_URL"], target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


# Arbitrary constant; all app processes use it so only one runs migrations at a time.
MIGRATION_LOCK_KEY = 74_210_391


def run_migrations_online():
    engine = create_engine(os.environ["DATABASE_URL"], poolclass=pool.NullPool)
    with engine.connect() as connection:
        locked = connection.dialect.name == "postgresql"
        if locked:
            # Blocks until any other process has finished migrating, then re-checks the version.
            connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if locked:
                connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
