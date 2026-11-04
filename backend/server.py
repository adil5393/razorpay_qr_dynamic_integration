from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

import config  # noqa: E402

config.validate()  # fail fast with a readable list of problems

import ipaddress  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from datetime import timedelta  # noqa: E402
from typing import Optional  # noqa: E402

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.encoders import jsonable_encoder  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from sqlalchemy import func, or_, select, text  # noqa: E402
from sqlalchemy.orm import Session, joinedload  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

import razorpay_api as rzp  # noqa: E402
from auth import (  # noqa: E402
    clear_auth_cookies, get_current_user, hash_password, require_admin,
    set_auth_cookies, user_from_token, verify_password,
)
from bootstrap_admin import ensure_admin  # noqa: E402
from db import SessionLocal, engine, get_db  # noqa: E402
from logging_setup import configure_logging, new_request_id, request_id_var  # noqa: E402
from models import LoginAttempt, Payment, QRCollection, User, WebhookEvent, utcnow  # noqa: E402
from schemas import (  # noqa: E402
    ChangePassword, CollectionCreate, LoginIn, PasswordReset, UserCreate, UserOut, UserStatusUpdate,
)
from ratelimit import RateLimiter  # noqa: E402
from services import (  # noqa: E402
    SYNC_ERRORS, apply_closed_qr, collection_out, payment_out, process_webhook, refresh_if_stale, sync_collection,
    ts_to_dt,
)

configure_logging()
logger = logging.getLogger("uqc")
access_logger = logging.getLogger("uqc.access")

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
PUBLIC_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
PUBLIC_POLL_INTERVAL_MS = 4000
# Polling every 4 s is 15 requests a minute; allow a few open tabs per IP before refusing.
public_limiter = RateLimiter(limit=90, window_seconds=60)
PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}
# Shown to customers instead of the internal names (closed -> cancelled).
PUBLIC_STATUS = {"pending": "pending", "paid": "paid", "expired": "expired", "closed": "cancelled"}
UPSTREAM_ERROR = 424  # not 502: the preview proxy replaces 502 bodies with its own page
MAX_WEBHOOK_BYTES = 256 * 1024  # Razorpay events are a few KB


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("LOCAL_POSTGRES_BOOTSTRAP") == "true":
        subprocess.run(["bash", str(ROOT.parent / "scripts" / "start_postgres.sh")], check=False, timeout=300)
    from migrate import ensure_database_at_head, run_migrations

    if config.run_migrations_on_startup():
        logger.info("RUN_MIGRATIONS_ON_STARTUP=true: applying migrations (development convenience)")
        await run_in_threadpool(run_migrations)
    else:
        # Migrations are a deployment step; refuse to serve on an out-of-date schema.
        await run_in_threadpool(ensure_database_at_head)
    logger.info("Starting (APP_ENV=%s, Razorpay mode=%s)", config.app_env(), rzp.mode() or "not configured")
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


@app.middleware("http")
async def request_context(request: Request, call_next):
    # Registered last, so it runs first: every log line, including the origin guard's, gets the ID.
    rid = new_request_id(request.headers.get("x-request-id"))
    token = request_id_var.set(rid)
    start = time.perf_counter()
    status = 500
    try:
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            response = JSONResponse({"detail": "Internal server error", "request_id": rid}, status_code=500)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        level = logging.DEBUG if request.url.path == "/api/health" else logging.INFO
        access_logger.log(level, "%s %s %s", request.method, request.url.path, status, extra={
            "method": request.method, "path": request.url.path, "status": status,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1), "client_ip": client_ip(request),
        })
        request_id_var.reset(token)


def client_ip(request: Request) -> str:
    """The real client IP. X-Forwarded-For is only believed when the direct peer is a proxy listed
    in TRUSTED_PROXIES; then the right-most address that is not a trusted proxy is the client.
    Anyone can send a fake X-Forwarded-For, so trusting it blindly would let attackers dodge the
    login lockout by inventing a new IP for every attempt."""
    peer = request.client.host if request.client else None
    if not config.is_trusted_proxy(peer):
        return peer or "unknown"
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            break  # malformed entry: stop and fall back to the peer
        if not config.is_trusted_proxy(hop):
            return hop
    return peer or "unknown"


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
    try:
        db.add(col)
        db.commit()
        db.refresh(col)
    except Exception:
        db.rollback()
        logger.exception("Saving new QR %s failed; closing it at Razorpay so it cannot be paid", qr["id"])
        try:
            rzp.close_qr(qr["id"])
        except Exception:
            logger.exception("Could not close orphan Razorpay QR %s; close it from the Razorpay dashboard", qr["id"])
        raise HTTPException(status_code=500, detail="The QR could not be saved and has been cancelled. Please try again.")
    logger.info("Created collection %s (Razorpay QR %s, %s paise) by user %s", code, qr["id"], amount_paise, user.id)
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
    if refresh:
        col, sync_error = refresh_if_stale(db, col)
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


def _cancel_conflict(col: QRCollection) -> Optional[HTTPException]:
    """Why a collection cannot be cancelled now, or None if it can."""
    if col.payment_status == "paid":
        return HTTPException(status_code=409, detail="This collection is already paid and cannot be cancelled.")
    if col.payment_status == "expired":
        return HTTPException(status_code=409, detail="This QR has already expired.")
    if col.qr_status == "closed" and col.close_reason == "paid":
        return HTTPException(status_code=409, detail="A payment is being confirmed by Razorpay; it cannot be cancelled.")
    return None


@api.post("/collections/{cid}/cancel")
def cancel_collection(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Close the QR at Razorpay so it can no longer be paid, then record it as cancelled.

    Razorpay is the source of truth throughout: the collection is only marked cancelled after Razorpay
    confirms the QR is closed, and a payment captured at any point (even milliseconds before the close)
    always wins, because every decision is made from a fresh read of Razorpay's QR and payment records.
    """
    col = _get_collection(db, cid, user)
    if col.payment_status == "closed":
        return collection_out(col)  # already cancelled: idempotent
    if (conflict := _cancel_conflict(col)):
        raise conflict
    qr_id = col.razorpay_qr_id

    # 1. Re-check first, so a payment that has just arrived is seen before we try to cancel.
    try:
        col = sync_collection(db, cid)
    except SYNC_ERRORS as exc:
        db.rollback()
        raise HTTPException(status_code=UPSTREAM_ERROR,
                            detail=f"Could not check the QR with Razorpay, so it was not cancelled: {getattr(exc, 'message', exc)}")
    if col.payment_status == "closed":
        return collection_out(col)
    if (conflict := _cancel_conflict(col)):
        raise conflict

    # 2. Close at Razorpay.
    closed_qr, close_error = None, None
    try:
        closed_qr = rzp.close_qr(qr_id)
    except rzp.RazorpayNotConfigured:
        raise HTTPException(status_code=UPSTREAM_ERROR, detail="Razorpay is not configured; the QR was not cancelled.")
    except rzp.RazorpayError as exc:
        logger.warning("Razorpay refused to close QR %s (%s): %s", qr_id, exc.status_code, exc.message)
        close_error = exc.message  # it may have closed for another reason meanwhile; step 3 finds out

    # 3. Read the final state back from Razorpay (payments included).
    try:
        col = sync_collection(db, cid)
    except SYNC_ERRORS as exc:
        db.rollback()
        if closed_qr is None:
            raise HTTPException(status_code=UPSTREAM_ERROR,
                                detail=f"Razorpay could not cancel the QR, so it may still be payable: {close_error}")
        # Close succeeded but the read-back failed: record Razorpay's close response. Any payment that
        # landed just before the close still arrives by webhook and turns this into paid.
        logger.warning("QR %s closed but re-check failed: %s", qr_id, getattr(exc, "message", exc))
        col = apply_closed_qr(db, cid, closed_qr)

    if col.payment_status == "paid":
        raise HTTPException(status_code=409, detail="A payment was received before the QR could be cancelled. It is now marked paid.")
    if col.qr_status == "closed" and col.close_reason == "paid":
        # The customer's payment closed it first; capture not confirmed yet. Not a cancellation.
        raise HTTPException(status_code=409, detail="A payment is being confirmed by Razorpay; it cannot be cancelled.")
    if col.qr_status != "closed":
        raise HTTPException(status_code=UPSTREAM_ERROR,
                            detail=f"Razorpay could not cancel the QR, so it may still be payable: {close_error}")
    if col.payment_status == "expired":
        raise HTTPException(status_code=409, detail="This QR expired before it could be cancelled.")
    logger.info("Collection %s cancelled by user %s (Razorpay QR %s, close reason %s)",
                col.code, user.id, qr_id, col.close_reason)
    return collection_out(col)


# ---------- Public payment page ----------

def _public_payment_out(db: Session, col: QRCollection) -> dict:
    """The only fields a customer's browser ever sees. No internal ids, staff, contact details or payloads."""
    status = PUBLIC_STATUS.get(col.payment_status, "pending")
    show_qr = status == "pending" and col.qr_status == "active"
    paid_payment = db.scalar(
        select(Payment).where(Payment.collection_id == col.id, Payment.is_successful.is_(True))
        .order_by(Payment.first_seen_at).limit(1)) if status == "paid" else None
    return {
        "customer_name": col.customer_name,
        "amount_paise": col.amount_paise,
        "currency": col.currency,
        "status": status,
        # QR closed with reason "paid" but the capture is not confirmed yet: no QR, keep polling.
        "confirming": status == "pending" and col.qr_status == "closed",
        "qr_image_url": col.image_url if show_qr else None,
        "expires_at": col.close_by,
        "paid_at": col.paid_at,
        "payment_reference": paid_payment.razorpay_payment_id if paid_payment else None,
        "test_mode": rzp.mode() == "test",
        "server_time": utcnow(),
        "poll_interval_ms": PUBLIC_POLL_INTERVAL_MS if status == "pending" else None,
    }


@api.get("/public/pay/{token}")
def public_payment(token: str, request: Request, db: Session = Depends(get_db)):
    """Read-only status for the customer payment page. No login; found only by its random token."""
    if not public_limiter.allow(client_ip(request)):
        return JSONResponse({"detail": "Too many requests. Please wait a moment."}, status_code=429,
                            headers={**PUBLIC_HEADERS, "Retry-After": "30"})
    not_found = JSONResponse({"detail": "Payment link not found"}, status_code=404, headers=PUBLIC_HEADERS)
    if not PUBLIC_TOKEN_RE.fullmatch(token):
        return not_found
    col = db.scalar(select(QRCollection).where(QRCollection.public_token == token))
    if col is None:
        return not_found
    col, sync_error = refresh_if_stale(db, col)
    if sync_error:
        logger.info("Public page status check for %s failed: %s", col.code, sync_error)
    return JSONResponse(jsonable_encoder(_public_payment_out(db, col)), headers=PUBLIC_HEADERS)


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
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        return JSONResponse({"detail": "Payload too large"}, status_code=413)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_BYTES:
            return JSONResponse({"detail": "Payload too large"}, status_code=413)
        chunks.append(chunk)
    body = b"".join(chunks)
    status_code, content = await run_in_threadpool(
        _handle_webhook, body, request.headers.get("x-razorpay-signature", ""), request.headers.get("x-razorpay-event-id"),
    )
    return JSONResponse(content, status_code=status_code)


@api.get("/health/live")
def health_live():
    """Liveness: the process is up. Does not touch the database."""
    return {"ok": True}


@api.get("/health")
def health():
    """Readiness: the app can reach PostgreSQL."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: database unavailable")
        return JSONResponse({"ok": False, "database": "unavailable"}, status_code=503)
    return {"ok": True, "database": "ok"}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
