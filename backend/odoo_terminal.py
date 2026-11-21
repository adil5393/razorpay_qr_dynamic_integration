"""Odoo terminal API and callback outbox. No Odoo accounting assumptions are made here."""
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import razorpay_api as rzp
from auth import get_current_user, require_admin
from db import get_db, SessionLocal
from models import ApiClient, CallbackDelivery, CallbackAttempt, OdooPaymentRequest, QRCollection, User, utcnow
from services import collection_out, ts_to_dt

router = APIRouter(prefix="/api")
logger = logging.getLogger("uqc.odoo")


def cutover_enabled():
    return os.environ.get("ODOO_TERMINAL_CUTOVER", "false").lower() == "true"


def allowed_callback(url):
    # Exact administrator-configured URLs only. No redirects, credentials, or request-supplied destinations.
    allowed = [x.strip() for x in os.environ.get("ODOO_CALLBACK_URLS", "").split(",") if x.strip()]
    parsed = urlsplit(url)
    return url in allowed and parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    instance: str = Field(min_length=1, max_length=120)
    callback_url: str = Field(min_length=1, max_length=2048)


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)
    instance: str = Field(min_length=1, max_length=120)
    request_reference: str = Field(min_length=1, max_length=128)
    invoice_id: str = Field(min_length=1, max_length=80)
    invoice_number: str = Field(min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=80)
    customer_name: str = Field(min_length=1, max_length=120)
    amount_paise: int = Field(ge=100, le=100000000)
    currency: str

    @field_validator("currency")
    @classmethod
    def inr_only(cls, value):
        if value != "INR":
            raise ValueError("Only INR is supported")
        return value


def client_auth(x_odoo_key: str = Header(default="", max_length=256), db: Session = Depends(get_db)):
    if not x_odoo_key.startswith("odoo_") or len(x_odoo_key) < 40:
        raise HTTPException(401, "Invalid API credential")
    digest = hashlib.sha256(x_odoo_key.encode()).hexdigest()
    client = db.scalar(select(ApiClient).where(ApiClient.key_prefix == x_odoo_key[:16]))
    if not client or not client.is_active or client.revoked_at or not client.odoo_instance or not hmac.compare_digest(client.key_hash, digest) or client.environment != rzp.mode():
        raise HTTPException(401, "Invalid API credential")
    return client


def request_out(row):
    col = row.collection
    return {"id": row.id, "instance": row.instance, "request_reference": row.request_reference,
            "invoice_id": row.invoice_id, "invoice_number": row.invoice_number,
            "customer_id": row.customer_id, "customer_name": row.customer_name,
            "amount_paise": row.amount_paise, "currency": row.currency, "state": row.state,
            "created_at": row.created_at, "error": row.error, "collection": collection_out(col) if col else None}


@router.post("/admin/odoo-clients", status_code=201)
def create_client(data: ClientCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not allowed_callback(data.callback_url):
        raise HTTPException(422, "Callback URL must be an exact configured ODOO_CALLBACK_URLS entry")
    mode = rzp.mode()
    if not mode:
        raise HTTPException(503, "Razorpay mode is not configured")
    key = "odoo_" + secrets.token_urlsafe(40)
    digest = hashlib.sha256(key.encode()).hexdigest()
    client = ApiClient(name=data.name, odoo_instance=data.instance, key_prefix=key[:16], key_hash=digest,
                       environment=mode, callback_url=data.callback_url, created_by_id=admin.id, is_active=True)
    db.add(client)
    db.commit()
    return {"id": client.id, "instance": client.odoo_instance, "api_key": key}


@router.get("/admin/odoo-clients")
def list_clients(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiClient).where(ApiClient.odoo_instance.is_not(None)).order_by(ApiClient.id)).all()
    return [{"id": row.id, "name": row.name, "instance": row.odoo_instance,
             "environment": row.environment, "active": row.is_active, "callback_url": row.callback_url} for row in rows]


@router.post("/admin/odoo-clients/{client_id}/revoke")
def revoke_client(client_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(ApiClient, client_id)
    if not row or not row.odoo_instance:
        raise HTTPException(404, "Client not found")
    row.is_active = False
    row.revoked_at = row.revoked_at or utcnow()
    db.commit()
    return {"status": "revoked"}


@router.post("/odoo/payment-requests", status_code=202)
def create_request(data: RequestIn, client: ApiClient = Depends(client_auth), db: Session = Depends(get_db)):
    if data.instance != client.odoo_instance:
        raise HTTPException(403, "Instance is not authorized")
    fingerprint = hashlib.sha256(json.dumps(data.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    row = OdooPaymentRequest(api_client_id=client.id, fingerprint=fingerprint, state="creating", **data.model_dump())
    db.add(row)
    try:
        db.commit()  # The claim MUST be durable before the external call.
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(OdooPaymentRequest).where(OdooPaymentRequest.instance == data.instance, OdooPaymentRequest.request_reference == data.request_reference))
        if existing is None:
            raise
        if not hmac.compare_digest(existing.fingerprint, fingerprint):
            raise HTTPException(409, "Request reference already used with different details")
        return request_out(existing)
    rid = row.id
    code = f"UQC-{utcnow():%y%m%d}-{secrets.token_hex(3).upper()}"
    close_by = int((utcnow() + timedelta(minutes=int(os.environ["QR_EXPIRY_MINUTES"]))).timestamp())
    payload = {"type": "upi_qr", "name": "Universal QR Collections", "usage": "single_use",
               "fixed_amount": True, "payment_amount": data.amount_paise,
               "description": ("Odoo invoice " + data.invoice_number)[:255], "close_by": close_by,
               "notes": {"collection_code": code, "odoo_request_id": str(rid)}}
    try:
        qr = rzp.create_qr(payload)
        if not qr.get("id") or not qr.get("image_url") or int(qr.get("payment_amount") or 0) != data.amount_paise:
            raise ValueError("Unexpected Razorpay response")
        col = QRCollection(code=code, razorpay_qr_id=qr["id"], amount_paise=data.amount_paise, currency="INR",
            reference=data.invoice_number[:64], customer_name=data.customer_name, description=payload["description"],
            image_url=qr["image_url"], qr_status=qr.get("status") or "active",
            close_by=ts_to_dt(qr.get("close_by")) or ts_to_dt(close_by), payment_status="pending",
            created_by_id=client.created_by_id, source="api", api_client_id=client.id)
        db.add(col)
        db.flush()
        row.collection_id = col.id
        row.state = "ready"
        db.commit()
        return request_out(row)
    except Exception:
        db.rollback()
        logger.exception("Odoo QR creation outcome requires investigation (request %s)", rid)
        row = db.get(OdooPaymentRequest, rid)
        row.state = "ambiguous"
        row.error = "QR creation outcome unknown; investigate in Razorpay before taking action"
        db.commit()
        return request_out(row)


@router.get("/odoo/payment-requests/{request_id}")
def get_request(request_id: int, client: ApiClient = Depends(client_auth), db: Session = Depends(get_db)):
    row = db.get(OdooPaymentRequest, request_id)
    if not row or row.instance != client.odoo_instance:
        raise HTTPException(404, "Request not found")
    return request_out(row)


@router.get("/terminal/requests")
def terminal_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(OdooPaymentRequest).outerjoin(QRCollection, OdooPaymentRequest.collection_id == QRCollection.id)
        .order_by(case((QRCollection.payment_status == "pending", 0), (OdooPaymentRequest.collection_id.is_(None), 0), else_=1),
                  OdooPaymentRequest.created_at.desc()).limit(100)).all()
    return [request_out(row) for row in rows]


@router.get("/admin/odoo-deliveries")
def deliveries(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(CallbackDelivery).order_by(CallbackDelivery.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "event_id": r.event_id, "collection_id": r.collection_id, "status": r.status,
             "attempts": r.attempts, "last_error": r.last_error, "last_response_status": r.last_response_status,
             "next_attempt_at": r.next_attempt_at, "delivered_at": r.delivered_at} for r in rows]


@router.post("/admin/odoo-deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.scalar(select(CallbackDelivery).where(CallbackDelivery.id == delivery_id).with_for_update())
    if not row:
        raise HTTPException(404, "Delivery not found")
    if row.status not in ("failed", "abandoned"):
        raise HTTPException(409, "Only failed or abandoned deliveries can be retried")
    row.status = "pending"
    row.next_attempt_at = utcnow()
    row.max_attempts = max(row.max_attempts, row.attempts + 12)
    row.last_error = None
    db.commit()
    return {"status": row.status}


def enqueue_payment(db, col, payment):
    if not col.api_client_id or not payment.is_successful:
        return
    request = db.scalar(select(OdooPaymentRequest).where(OdooPaymentRequest.collection_id == col.id))
    client = db.get(ApiClient, col.api_client_id)
    if not request or not client or not client.callback_url:
        return
    event_type = "p:" + hashlib.sha256(payment.razorpay_payment_id.encode()).hexdigest()[:62]
    exists = db.scalar(select(CallbackDelivery.id).where(CallbackDelivery.collection_id == col.id,
        CallbackDelivery.api_client_id == client.id, CallbackDelivery.event_type == event_type))
    if exists:
        return
    event_id = str(uuid.uuid4())
    payload = {"event_id": event_id, "event": "payment.captured", "instance": request.instance,
        "request_reference": request.request_reference, "invoice_id": request.invoice_id,
        "invoice_number": request.invoice_number, "customer_id": request.customer_id,
        "amount_paise": payment.amount_paise, "currency": payment.currency, "razorpay_qr_id": col.razorpay_qr_id,
        "razorpay_payment_id": payment.razorpay_payment_id}
    db.add(CallbackDelivery(event_id=event_id, api_client_id=client.id, collection_id=col.id, event_type=event_type,
                            payload=payload, target_url=client.callback_url, status="pending"))


def deliver_one():
    with SessionLocal() as db:
        now = utcnow()
        row = db.scalar(select(CallbackDelivery).where(
            ((CallbackDelivery.status.in_(("pending", "failed"))) & (CallbackDelivery.next_attempt_at <= now)) |
            ((CallbackDelivery.status == "delivering") & (CallbackDelivery.locked_until < now))
        ).order_by(CallbackDelivery.id).with_for_update(skip_locked=True).limit(1))
        if not row:
            return False
        row.status = "delivering"
        row.locked_until = now + timedelta(minutes=2)
        row.attempts += 1
        attempt_no, row_id = row.attempts, row.id
        client = db.get(ApiClient, row.api_client_id)
        body = json.dumps(row.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        target = row.target_url
        digest = client.key_hash if client and client.is_active and not client.revoked_at else None
        db.commit()
        start = time.monotonic()
        status, error = None, None
        try:
            if not digest or not allowed_callback(target):
                raise ValueError("Client disabled or callback URL not allowed")
            signature = hmac.new(bytes.fromhex(digest), body, hashlib.sha256).hexdigest()
            with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as http:
                response = http.post(target, content=body, headers={"Content-Type": "application/json",
                    "X-Terminal-Signature": signature, "X-Terminal-Event-Id": row.event_id})
            status = response.status_code
            if not 200 <= status < 300:
                error = f"HTTP {status}"
        except Exception as exc:
            error = f"Delivery failed: {type(exc).__name__}"
        row = db.scalar(select(CallbackDelivery).where(CallbackDelivery.id == row_id).with_for_update())
        if row.status != "delivering" or row.attempts != attempt_no:
            return True
        row.last_attempt_at = utcnow()
        row.last_response_status = status
        row.last_error = error
        row.locked_until = None
        if error:
            row.status = "abandoned" if attempt_no >= row.max_attempts else "failed"
            row.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 2 ** min(attempt_no, 11)))
        else:
            row.status = "delivered"
            row.delivered_at = utcnow()
        db.add(CallbackAttempt(delivery_id=row_id, attempt_no=attempt_no, started_at=now,
            duration_ms=int((time.monotonic() - start) * 1000), response_status=status, error=error))
        db.commit()
        return True


def worker(stop):
    # Recover captures when a webhook arrives before the QR link commits.
    next_reconcile = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_reconcile:
                from services import refresh_if_stale
                with SessionLocal() as db:
                    rows = db.scalars(select(QRCollection).where(
                        QRCollection.source == "api", QRCollection.payment_status == "pending"
                    ).order_by(QRCollection.last_synced_at.asc().nullsfirst()).limit(25)).all()
                    for col in rows:
                        if stop.is_set():
                            break
                        refresh_if_stale(db, col)
                next_reconcile = time.monotonic() + 30
            if not deliver_one():
                stop.wait(5)
        except Exception:
            logger.exception("Callback worker iteration failed")
            stop.wait(5)
