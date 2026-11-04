from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent


def _config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def run_migrations():
    command.upgrade(_config(), "head")


def pending_migration_state() -> tuple[str | None, str]:
    """(current revision in the database, newest revision in the code)."""
    import os

    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, pool

    head = ScriptDirectory.from_config(_config()).get_current_head()
    engine = create_engine(os.environ["DATABASE_URL"], poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    return current, head


def ensure_database_at_head() -> None:
    current, head = pending_migration_state()
    if current != head:
        raise RuntimeError(
            f"Database schema is at {current or 'nothing'} but the code needs {head}. "
            "Run `python migrate.py` before starting the app."
        )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
    run_migrations()
    print("Migrations applied")
