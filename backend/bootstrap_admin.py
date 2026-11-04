"""Create the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_NAME env vars.

Usage: python bootstrap_admin.py   (idempotent; never changes an existing account)
"""
import os

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import hash_password
from models import User


def ensure_admin(db: Session) -> str:
    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not email or not password:
        return "skipped: ADMIN_EMAIL / ADMIN_PASSWORD not set"
    if len(password) < 8:
        return "skipped: ADMIN_PASSWORD must be at least 8 characters"
    if db.scalar(select(User).where(User.email == email)):
        return f"exists: {email}"
    db.add(User(
        email=email,
        name=(os.environ.get("ADMIN_NAME") or "Administrator").strip(),
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
    ))
    try:
        db.commit()
    except IntegrityError:
        # Another worker created it at the same moment.
        db.rollback()
        return f"exists: {email}"
    return f"created: {email}"


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
    from db import SessionLocal
    from migrate import run_migrations

    run_migrations()
    with SessionLocal() as session:
        print(ensure_admin(session))
