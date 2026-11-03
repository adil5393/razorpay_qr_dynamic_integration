from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent


def run_migrations():
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(BACKEND_DIR / ".env")
    run_migrations()
    print("Migrations applied")
