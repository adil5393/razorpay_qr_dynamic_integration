import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from db import get_db
from models import User

JWT_ALGORITHM = "HS256"
ACCESS_MINUTES = 30
REFRESH_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _create_token(user: User, kind: str, delta: timedelta) -> str:
    payload = {
        "sub": str(user.id),
        "tv": user.token_version,
        "type": kind,
        "exp": datetime.now(timezone.utc) + delta,
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


def _cookie_secure() -> bool:
    return os.environ["COOKIE_SECURE"].lower() == "true"


def set_auth_cookies(response: Response, user: User) -> None:
    common = {"httponly": True, "secure": _cookie_secure(), "samesite": "lax"}
    response.set_cookie(
        "access_token", _create_token(user, "access", timedelta(minutes=ACCESS_MINUTES)),
        max_age=ACCESS_MINUTES * 60, path="/", **common,
    )
    response.set_cookie(
        "refresh_token", _create_token(user, "refresh", timedelta(days=REFRESH_DAYS)),
        max_age=REFRESH_DAYS * 86400, path="/api/auth", **common,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")


def user_from_token(db: Session, token: str | None, kind: str) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session")
    if payload.get("type") != kind:
        raise HTTPException(status_code=401, detail="Invalid session")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or user.token_version != payload.get("tv"):
        raise HTTPException(status_code=401, detail="Session is no longer valid")
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    return user_from_token(db, token, "access")


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
