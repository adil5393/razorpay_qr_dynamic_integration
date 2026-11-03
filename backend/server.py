from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

import logging  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import subprocess  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import Optional  # noqa: E402

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from sqlalchemy import func, or_, select  # noqa: E402
from sqlalchemy.orm import Session, joinedload  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

import razorpay_api as rzp  # noqa: E402
from auth import (  # noqa: E402
    clear_auth_cookies, get_current_user, hash_password, require_admin,
    set_auth_cookies, user_from_token, verify_password,
)
from bootstrap_admin import ensure_admin  # noqa: E402
from db import SessionLocal, get_db  # noqa: E402
from models import LoginAttempt, Payment, QRCollection, User, WebhookEvent, utcnow  # noqa: E402
from schemas import (  # noqa: E402
    ChangePassword, CollectionCreate, LoginIn, PasswordReset, UserCreate, UserOut, UserStatusUpdate,
)
from services import collection_out, payment_out, process_webhook, sync_collection, ts_to_dt  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("uqc")

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
SYNC_THROTTLE_SECONDS = 8
UPSTREAM_ERROR = 424  # not 502: the preview proxy replaces 502 bodies with its own page


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("LOCAL_POSTGRES_BOOTSTRAP") == "true":
        subprocess.run(["bash", str(ROOT.parent / "scripts" / "start_postgres.sh")], check=False, timeout=300)
    from migrate import run_migrations

    await run_in_threadpool(run_migrations)
    with SessionLocal() as db:
        logger.info("Admin bootstrap: %s", ensure_admin(db))
    yield


app = FastAPI(title="Universal QR Collections", lifespan=lifespan)
api = APIRouter(prefix="/api")


def _allowed_origins() -> list[str]:
    return [o.strip().rstrip("/") for o in os.environ["FRONTEND_URL"].split(",") if o.strip()]


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith("/api/") \
            and not request.url.path.startswith("/api/webhooks/"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in _allowed_origins():
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------- Auth ----------

@api.post("/auth/login")
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    identifier = f"{client_ip(request)}:{email}"[:320]
    now = utcnow()
    attempt = db.get(LoginAttempt, identifier)
    if attempt and attempt.locked_until and attempt.locked_until > now:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(data.password, user.password_hash):
        if attempt is None:
            attempt = LoginAttempt(identifier=identifier, failed_count=0)
            db.add(attempt)
        if attempt.locked_until and attempt.locked_until <= now:
            attempt.failed_count = 0
            attempt.locked_until = None
        attempt.failed_count += 1
        attempt.updated_at = now
        if attempt.failed_count >= MAX_FAILED_LOGINS:
            attempt.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated. Contact an administrator.")
    if attempt:
        db.delete(attempt)
    user.last_login_at = now
    db.commit()
    set_auth_cookies(response, user)
    return UserOut.model_validate(user)


@api.post("/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    user = user_from_token(db, request.cookies.get("refresh_token"), "refresh")
    set_auth_cookies(response, user)
    return UserOut.model_validate(user)


@api.post("/auth/logout")
def logout(response: Response):
    clear_auth_cookies(response)
    return {"ok": True}


@api.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@api.post("/auth/change-password")
def change_password(data: ChangePassword, response: Response, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    db.commit()
    set_auth_cookies(response, user)
    return {"ok": True}


# ---------- Users (admin) ----------

@api.get("/users")
def list_users(status: str = Query("all", pattern="^(all|active|inactive)$"),
               _: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(User).order_by(User.created_at.desc())
    if status != "all":
        q = q.where(User.is_active.is_(status == "active"))
    return [UserOut.model_validate(u) for u in db.scalars(q).all()]


@api.post("/users", status_code=201)
def create_user(data: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(email=data.email, name=data.name, password_hash=hash_password(data.password),
                role="cashier", is_active=True, created_by_id=admin.id)
    db.add(user)
    db.commit()
    return UserOut.model_validate(user)


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@api.patch("/users/{user_id}")
def update_user_status(user_id: int, data: UserStatusUpdate, admin: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    if user.id == admin.id and not data.is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    if user.is_active and not data.is_active:
        user.token_version += 1
    user.is_active = data.is_active
    db.commit()
    return UserOut.model_validate(user)


@api.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, data: PasswordReset, _: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    db.commit()
    return {"ok": True}


# ---------- Config ----------

@api.get("/config")
def app_config(_: User = Depends(get_current_user)):
    return {
        "razorpay_configured": rzp.is_configured(),
        "razorpay_mode": rzp.mode(),
        "qr_expiry_minutes": int(os.environ["QR_EXPIRY_MINUTES"]),
    }


@api.get("/admin/razorpay")
def razorpay_status(_: User = Depends(require_admin)):
    base = _allowed_origins()[0]
    return {
        "configured": rzp.is_configured(),
        "mode": rzp.mode(),
        "key_id_masked": rzp.masked_key_id(),
        "webhook_secret_configured": rzp.webhook_secret_configured(),
        "webhook_url": f"{base}/api/webhooks/razorpay",
        "webhook_events": ["qr_code.credited", "qr_code.closed", "payment.captured"],
    }


@api.get("/admin/webhook-events")
def webhook_events(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(50)).all()
    return [{
        "id": e.id, "event_id": e.event_id, "event_type": e.event_type, "status": e.status,
        "signature_valid": e.signature_valid, "error": e.error, "attempts": e.attempts,
        "razorpay_qr_id": e.razorpay_qr_id, "razorpay_payment_id": e.razorpay_payment_id,
        "received_at": e.received_at, "processed_at": e.processed_at,
    } for e in rows]


# ---------- Collections ----------

def _scope(user: User) -> list:
    return [] if user.role == "admin" else [QRCollection.created_by_id == user.id]


def _get_collection(db: Session, cid: int, user: User) -> QRCollection:
    col = db.get(QRCollection, cid)
    if not col or (user.role != "admin" and col.created_by_id != user.id):
        raise HTTPException(status_code=404, detail="Collection not found")
    return col


@api.post("/collections", status_code=201)
def create_collection(data: CollectionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    amount_paise = int((data.amount * 100).to_integral_value())
    if amount_paise < 100:
        raise HTTPException(status_code=422, detail="Minimum amount is ₹1.00")
    code = f"UQC-{utcnow():%y%m%d}-{secrets.token_hex(3).upper()}"
    close_by = int((utcnow() + timedelta(minutes=int(os.environ["QR_EXPIRY_MINUTES"]))).timestamp())
    payload = {
        "type": "upi_qr",
        "name": "Universal QR Collections",
        "usage": "single_use",
        "fixed_amount": True,
        "payment_amount": amount_paise,
        "description": data.description[:255],
        "close_by": close_by,
        "notes": {
            "collection_code": code,
            "reference": data.reference or "",
            "customer_name": data.customer_name or "",
            "created_by": user.email,
        },
    }
    try:
        qr = rzp.create_qr(payload)
    except rzp.RazorpayNotConfigured:
        raise HTTPException(status_code=UPSTREAM_ERROR, detail="Razorpay is not configured. Ask an administrator to add valid API keys.")
    except rzp.RazorpayError as exc:
        logger.warning("Razorpay QR creation failed (%s): %s", exc.status_code, exc.message)
        raise HTTPException(status_code=UPSTREAM_ERROR, detail=f"Razorpay could not create the QR: {exc.message}")
    if not qr.get("id") or not qr.get("image_url") or int(qr.get("payment_amount") or 0) != amount_paise:
        raise HTTPException(status_code=UPSTREAM_ERROR, detail="Unexpected response from Razorpay; QR not saved")
    col = QRCollection(
        code=code, razorpay_qr_id=qr["id"], amount_paise=amount_paise, currency="INR",
        reference=data.reference, customer_name=data.customer_name, description=data.description,
        image_url=qr["image_url"], qr_status=qr.get("status") or "active",
        close_by=ts_to_dt(qr.get("close_by")) or ts_to_dt(close_by),
        payment_status="pending", created_by_id=user.id, created_at=utcnow(),
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return collection_out(col)


@api.get("/collections")
def list_collections(
    search: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, pattern="^(pending|paid|expired|closed)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = _scope(user)
    if status:
        filters.append(QRCollection.payment_status == status)
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(or_(
            QRCollection.code.ilike(term), QRCollection.razorpay_qr_id.ilike(term),
            QRCollection.reference.ilike(term), QRCollection.customer_name.ilike(term), User.name.ilike(term),
        ))
    base = select(QRCollection).join(User, QRCollection.created_by_id == User.id).where(*filters)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(
        base.options(joinedload(QRCollection.created_by))
        .order_by(QRCollection.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [collection_out(c) for c in rows], "total": total, "page": page, "page_size": page_size}


@api.get("/collections/{cid}")
def get_collection(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    col = _get_collection(db, cid, user)
    out = collection_out(col)
    out["payments"] = [payment_out(p) for p in col.payments]
    return out


@api.get("/collections/{cid}/status")
def collection_status(cid: int, refresh: bool = False, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    col = _get_collection(db, cid, user)
    sync_error = None
    stale = col.last_synced_at is None or (utcnow() - col.last_synced_at).total_seconds() > SYNC_THROTTLE_SECONDS
    if refresh and col.payment_status == "pending" and stale:
        try:
            col = sync_collection(db, col.id)
        except (rzp.RazorpayError, rzp.RazorpayNotConfigured, ValueError) as exc:
            db.rollback()
            sync_error = getattr(exc, "message", None) or str(exc)
            col = db.get(QRCollection, cid)
            col.last_sync_error = sync_error[:1000]
            col.last_synced_at = utcnow()
            db.commit()
    successful = next((p for p in col.payments if p.is_successful), None)
    return {
        "id": col.id,
        "payment_status": col.payment_status,
        "qr_status": col.qr_status,
        "close_reason": col.close_reason,
        "close_by": col.close_by,
        "paid_at": col.paid_at,
        "amount_received_paise": col.amount_received_paise,
        "last_synced_at": col.last_synced_at,
        "sync_error": sync_error,
        "successful_payment": payment_out(successful) if successful else None,
    }


@api.get("/collections/{cid}/qr-image")
def collection_qr_image(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    col = _get_collection(db, cid, user)
    try:
        content, content_type = rzp.download_image(col.image_url)
    except rzp.RazorpayError as exc:
        raise HTTPException(status_code=UPSTREAM_ERROR, detail=exc.message)
    ext = "png" if "png" in content_type else "jpg"
    return Response(content=content, media_type=content_type,
                    headers={"Content-Disposition": f'attachment; filename="{col.code}.{ext}"'})


# ---------- Dashboard ----------

@api.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    scope = _scope(user)
    pay_base = select(Payment).join(QRCollection, Payment.collection_id == QRCollection.id).where(*scope)
    confirmed = pay_base.where(Payment.is_successful.is_(True)).subquery()
    total_paise = db.scalar(select(func.coalesce(func.sum(confirmed.c.amount_paise), 0)))
    success_count = db.scalar(select(func.count()).select_from(confirmed))
    pending = select(QRCollection).where(*scope, QRCollection.payment_status == "pending").subquery()
    pending_count = db.scalar(select(func.count()).select_from(pending))
    pending_paise = db.scalar(select(func.coalesce(func.sum(pending.c.amount_paise), 0)))
    total_qrs = db.scalar(select(func.count()).select_from(select(QRCollection).where(*scope).subquery()))
    recent = db.scalars(
        pay_base.options(joinedload(Payment.collection)).order_by(Payment.first_seen_at.desc()).limit(10)
    ).all()
    return {
        "total_confirmed_paise": int(total_paise),
        "successful_payment_count": success_count,
        "pending_qr_count": pending_count,
        "pending_qr_paise": int(pending_paise),
        "total_qr_count": total_qrs,
        "recent_payments": [{
            **payment_out(p),
            "collection": {"id": p.collection.id, "code": p.collection.code, "reference": p.collection.reference,
                           "customer_name": p.collection.customer_name},
        } for p in recent],
    }


# ---------- Webhook ----------

def _handle_webhook(body: bytes, signature: str, event_id: Optional[str]):
    with SessionLocal() as db:
        return process_webhook(db, body, signature, event_id)


@api.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    body = await request.body()
    status_code, content = await run_in_threadpool(
        _handle_webhook, body, request.headers.get("x-razorpay-signature", ""), request.headers.get("x-razorpay-event-id"),
    )
    return JSONResponse(content, status_code=status_code)


@api.get("/health")
def health():
    return {"ok": True}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
