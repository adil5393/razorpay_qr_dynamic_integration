import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import razorpay_api as rzp
from models import Payment, QRCollection, WebhookEvent, utcnow

logger = logging.getLogger("uqc.services")


def ts_to_dt(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def payment_out(p: Payment) -> dict:
    return {
        "id": p.id,
        "razorpay_payment_id": p.razorpay_payment_id,
        "collection_id": p.collection_id,
        "amount_paise": p.amount_paise,
        "currency": p.currency,
        "status": p.status,
        "method": p.method,
        "vpa": p.vpa,
        "is_successful": p.is_successful,
        "error_description": p.error_description,
        "rzp_created_at": p.rzp_created_at,
        "first_seen_at": p.first_seen_at,
    }


def collection_out(c: QRCollection) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "razorpay_qr_id": c.razorpay_qr_id,
        "amount_paise": c.amount_paise,
        "currency": c.currency,
        "reference": c.reference,
        "customer_name": c.customer_name,
        "description": c.description,
        "image_url": c.image_url,
        "qr_status": c.qr_status,
        "close_reason": c.close_reason,
        "close_by": c.close_by,
        "closed_at": c.closed_at,
        "payment_status": c.payment_status,
        "paid_at": c.paid_at,
        "amount_received_paise": c.amount_received_paise,
        "created_by": {"id": c.created_by.id, "name": c.created_by.name},
        "created_at": c.created_at,
        "last_synced_at": c.last_synced_at,
    }


def _apply_qr_entity(col: QRCollection, qr: dict) -> None:
    if qr.get("id") != col.razorpay_qr_id:
        raise ValueError("Razorpay returned a different QR code than requested")
    col.qr_status = qr.get("status") or col.qr_status
    col.close_reason = qr.get("close_reason")
    col.closed_at = ts_to_dt(qr.get("closed_at"))
    if qr.get("close_by"):
        col.close_by = ts_to_dt(qr.get("close_by"))


def _upsert_payment(db: Session, col: QRCollection, p: dict) -> Payment:
    pay_id = p.get("id")
    if not pay_id:
        raise ValueError("Payment without id in Razorpay response")
    rec = db.scalar(select(Payment).where(Payment.razorpay_payment_id == pay_id).with_for_update())
    if rec and rec.collection_id != col.id:
        raise ValueError(f"Payment {pay_id} already linked to another collection")
    now = utcnow()
    if rec is None:
        rec = Payment(razorpay_payment_id=pay_id, collection_id=col.id, first_seen_at=now)
        db.add(rec)
    amount = int(p.get("amount") or 0)
    currency = p.get("currency") or "INR"
    status = p.get("status") or "unknown"
    rec.amount_paise = amount
    rec.currency = currency
    rec.status = status
    rec.method = p.get("method")
    rec.vpa = p.get("vpa")
    rec.email = p.get("email")
    rec.contact = p.get("contact")
    rec.rzp_created_at = ts_to_dt(p.get("created_at"))
    rec.updated_at = now
    captured = status == "captured" and bool(p.get("captured", True))
    amount_ok = amount == col.amount_paise and currency == "INR"
    rec.is_successful = captured and amount_ok
    if captured and not amount_ok:
        rec.error_description = f"Amount mismatch: received {amount} {currency}, expected {col.amount_paise} INR"
    else:
        rec.error_description = p.get("error_description")
    return rec


def _recompute(db: Session, col: QRCollection) -> None:
    payments = db.scalars(select(Payment).where(Payment.collection_id == col.id)).all()
    successful = [p for p in payments if p.is_successful]
    if successful:
        col.payment_status = "paid"
        col.amount_received_paise = sum(p.amount_paise for p in successful)
        col.paid_at = min((p.rzp_created_at or p.first_seen_at) for p in successful)
        return
    col.amount_received_paise = 0
    col.paid_at = None
    if col.qr_status == "closed" and col.close_reason != "paid":
        col.payment_status = "expired" if col.close_reason == "expired" else "closed"
    else:
        # A QR closed with reason "paid" stays pending until the captured payment is confirmed.
        col.payment_status = "pending"


def sync_collection(db: Session, collection_id: int) -> QRCollection:
    """Reconcile a collection against Razorpay's authoritative QR + payment records."""
    col = db.scalar(select(QRCollection).where(QRCollection.id == collection_id).with_for_update())
    qr = rzp.fetch_qr(col.razorpay_qr_id)
    payments = rzp.fetch_qr_payments(col.razorpay_qr_id)
    _apply_qr_entity(col, qr)
    for p in payments:
        _upsert_payment(db, col, p)
    db.flush()
    _recompute(db, col)
    col.last_synced_at = utcnow()
    col.last_sync_error = None
    db.commit()
    return col


def _entity_id(payload: dict, key: str) -> str | None:
    return (((payload.get("payload") or {}).get(key) or {}).get("entity") or {}).get("id")


def process_webhook(db: Session, body: bytes, signature: str, event_id: str | None) -> tuple[int, dict]:
    if not rzp.webhook_secret_configured():
        return 503, {"detail": "Webhook secret not configured"}
    if not rzp.verify_webhook_signature(body, signature):
        db.add(WebhookEvent(
            event_id=None, signature_valid=False, status="rejected", attempts=1,
            error=f"Invalid signature (event id: {(event_id or 'n/a')[:64]})", received_at=utcnow(),
        ))
        db.commit()
        return 400, {"detail": "Invalid signature"}
    try:
        payload = json.loads(body)
    except ValueError:
        return 400, {"detail": "Invalid JSON"}

    event_type = payload.get("event")
    qr_id = _entity_id(payload, "qr_code")
    pay_id = _entity_id(payload, "payment")

    ev = None
    if event_id:
        ev = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == event_id).with_for_update())
        if ev and ev.status in ("processed", "ignored"):
            ev.attempts += 1
            db.commit()
            return 200, {"status": "duplicate"}
    if ev is None:
        ev = WebhookEvent(event_id=event_id, signature_valid=True, status="received", attempts=0, received_at=utcnow())
        db.add(ev)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return 409, {"detail": "Event is already being processed"}
    ev.attempts += 1
    ev.event_type = event_type
    ev.payload = payload
    ev.razorpay_qr_id = qr_id
    ev.razorpay_payment_id = pay_id
    ev.status = "received"
    db.commit()
    ev_pk = ev.id

    col = None
    if qr_id:
        col = db.scalar(select(QRCollection).where(QRCollection.razorpay_qr_id == qr_id))
    if col is None and pay_id:
        known = db.scalar(select(Payment).where(Payment.razorpay_payment_id == pay_id))
        col = known.collection if known else None
    if col is None:
        ev.status = "ignored"
        ev.error = "No matching QR collection for this event"
        ev.processed_at = utcnow()
        db.commit()
        return 200, {"status": "ignored"}

    ev.collection_id = col.id
    db.commit()
    try:
        sync_collection(db, col.id)
    except Exception as exc:
        db.rollback()
        message = exc.message if isinstance(exc, rzp.RazorpayError) else f"{exc.__class__.__name__}: {exc}"
        logger.warning("Webhook %s processing failed: %s", event_id, message)
        ev = db.get(WebhookEvent, ev_pk)
        ev.status = "failed"
        ev.error = message[:1000]
        db.commit()
        return 500, {"detail": "Processing failed; Razorpay will retry"}
    ev = db.get(WebhookEvent, ev_pk)
    ev.status = "processed"
    ev.error = None
    ev.processed_at = utcnow()
    db.commit()
    return 200, {"status": "processed"}
