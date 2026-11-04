"""Phase 3: public payment page API and QR cancellation."""
from datetime import timedelta

import pytest

import razorpay_api
from conftest import make_client, signed_webhook
from db import SessionLocal
from models import QRCollection, utcnow

PUBLIC_FIELDS = {"customer_name", "amount_paise", "currency", "status", "confirming", "qr_image_url", "expires_at",
                 "paid_at", "payment_reference", "test_mode", "server_time", "poll_interval_ms"}


def _create(client, amount="250.50", **extra):
    body = {"amount": amount, "description": "Internal note: shelf 4", "customer_name": "Ravi Kumar",
            "reference": "INV-SECRET-77", **extra}
    r = client.post("/api/collections", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _public(token, client=None):
    return (client or make_client()).get(f"/api/public/pay/{token}")


def _expire_sync_throttle(cid):
    with SessionLocal() as db:
        db.get(QRCollection, cid).last_synced_at = utcnow() - timedelta(minutes=1)
        db.commit()


def _credited(qr_id, pay_id, amount):
    return {"event": "qr_code.credited", "payload": {
        "payment": {"entity": {"id": pay_id, "amount": amount, "status": "captured"}},
        "qr_code": {"entity": {"id": qr_id}}}}


# ---------- Public token handling ----------

def test_staff_view_includes_payment_page_link(cashier_client, fake_rzp):
    col = _create(cashier_client)
    assert len(col["public_token"]) == 43
    assert col["payment_page_url"] == f"http://testserver/pay/{col['public_token']}"


def test_public_page_needs_no_login_and_shows_only_safe_fields(cashier_client, fake_rzp):
    col = _create(cashier_client)
    r = _public(col["public_token"])
    assert r.status_code == 200
    data = r.json()
    assert set(data) == PUBLIC_FIELDS
    assert data["customer_name"] == "Ravi Kumar"
    assert data["amount_paise"] == 25050 and isinstance(data["amount_paise"], int) and data["currency"] == "INR"
    assert data["status"] == "pending" and data["poll_interval_ms"] == 4000
    assert data["qr_image_url"] == col["image_url"]  # the real Razorpay image, nothing generated
    assert data["expires_at"] and data["test_mode"] is True
    assert r.headers["Cache-Control"] == "no-store" and r.headers["Referrer-Policy"] == "no-referrer"
    assert "noindex" in r.headers["X-Robots-Tag"]


def test_public_response_leaks_nothing_internal(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.add_payment(col["razorpay_qr_id"], "pay_PUB1", 25050)
    signed_webhook(make_client(), _credited(col["razorpay_qr_id"], "pay_PUB1", 25050), "evt_pub1")
    body = _public(col["public_token"]).text
    for secret in [col["code"], col["razorpay_qr_id"], "INV-SECRET-77", "Internal note", "Cashier One",
                   "cashier@test.local", "test@upi", '"id"', "created_by", "whsec_", "rzp_test_", "evt_pub1"]:
        assert secret not in body, secret


@pytest.mark.parametrize("token", ["1", "12345", "x" * 42, "x" * 44, "../../etc/passwd", "a" * 42 + "!",
                                   "A" * 43])  # last one is well-formed but does not exist
def test_invalid_or_unknown_tokens_are_404(cashier_client, fake_rzp, token):
    _create(cashier_client)
    r = _public(token)
    assert r.status_code == 404
    if "/" not in token:  # tokens with slashes never reach the endpoint; the router 404s them
        assert r.json() == {"detail": "Payment link not found"}
        assert r.headers["Cache-Control"] == "no-store"


def test_sequential_id_cannot_be_used(cashier_client, fake_rzp):
    col = _create(cashier_client)
    assert _public(str(col["id"])).status_code == 404


def test_public_endpoint_is_rate_limited(cashier_client, fake_rzp):
    token = _create(cashier_client)["public_token"]
    anon = make_client()
    codes = [_public(token, anon).status_code for _ in range(95)]
    assert codes[:90] == [200] * 90 and codes[-1] == 429


# ---------- Status updates ----------

def test_public_status_turns_paid_from_verified_razorpay_data(cashier_client, fake_rzp):
    col = _create(cashier_client)
    token, qr_id = col["public_token"], col["razorpay_qr_id"]
    assert _public(token).json()["status"] == "pending"
    fake_rzp.add_payment(qr_id, "pay_LIVE", 25050)
    fake_rzp.close(qr_id, "paid")
    _expire_sync_throttle(col["id"])
    data = _public(token).json()  # page poll reconciles with Razorpay (no webhook needed)
    assert data["status"] == "paid" and data["payment_reference"] == "pay_LIVE"
    assert data["qr_image_url"] is None and data["poll_interval_ms"] is None and data["paid_at"]


def test_webhook_payload_alone_does_not_mark_paid(cashier_client, fake_rzp):
    col = _create(cashier_client)
    # A signed event claims a capture, but Razorpay's own records show no payment.
    signed_webhook(make_client(), _credited(col["razorpay_qr_id"], "pay_FAKE", 25050), "evt_claim")
    assert _public(col["public_token"]).json()["status"] == "pending"


def test_wrong_amount_is_not_success(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.add_payment(col["razorpay_qr_id"], "pay_SHORT", 100)
    _expire_sync_throttle(col["id"])
    assert _public(col["public_token"]).json()["status"] == "pending"


def test_qr_closed_paid_awaiting_capture_shows_confirming(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.close(col["razorpay_qr_id"], "paid")
    _expire_sync_throttle(col["id"])
    data = _public(col["public_token"]).json()
    assert data["status"] == "pending" and data["confirming"] is True
    assert data["qr_image_url"] is None and data["poll_interval_ms"] == 4000


def test_expired_qr_is_terminal(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.close(col["razorpay_qr_id"], "expired")
    _expire_sync_throttle(col["id"])
    data = _public(col["public_token"]).json()
    assert data["status"] == "expired" and data["qr_image_url"] is None and data["poll_interval_ms"] is None


def test_razorpay_outage_keeps_last_confirmed_state(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.fail_fetch = True
    r = _public(col["public_token"])
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert "unavailable" not in r.text  # upstream errors are not shown to customers


def test_status_polls_are_throttled(cashier_client, fake_rzp, monkeypatch):
    col = _create(cashier_client)
    calls = []
    original = fake_rzp.fetch_qr
    monkeypatch.setattr(razorpay_api, "fetch_qr", lambda qr_id: calls.append(qr_id) or original(qr_id))
    for _ in range(5):
        _public(col["public_token"])
    assert len(calls) == 1  # many viewers polling still means at most one Razorpay call per 8 s


# ---------- Cancellation: permissions ----------

def test_cancel_requires_login(cashier_client, fake_rzp):
    col = _create(cashier_client)
    assert make_client().post(f"/api/collections/{col['id']}/cancel").status_code == 401


def test_cashier_cannot_cancel_someone_elses_collection(cashier_client, fake_rzp):
    col = _create(cashier_client)
    other = make_client("cashier2@test.local")
    assert other.post(f"/api/collections/{col['id']}/cancel").status_code == 404
    assert fake_rzp.close_calls == []


def test_owner_can_cancel_and_public_page_shows_cancelled(cashier_client, fake_rzp):
    col = _create(cashier_client)
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 200, r.text
    assert r.json()["payment_status"] == "closed" and r.json()["close_reason"] == "on_demand"
    assert fake_rzp.close_calls == [col["razorpay_qr_id"]]
    data = _public(col["public_token"]).json()
    assert data["status"] == "cancelled" and data["qr_image_url"] is None and data["poll_interval_ms"] is None


def test_admin_can_cancel_any_collection(cashier_client, admin_client, fake_rzp):
    col = _create(cashier_client)
    assert admin_client.post(f"/api/collections/{col['id']}/cancel").json()["payment_status"] == "closed"


def test_cancel_is_idempotent(cashier_client, fake_rzp):
    col = _create(cashier_client)
    cashier_client.post(f"/api/collections/{col['id']}/cancel")
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 200 and r.json()["payment_status"] == "closed"
    assert len(fake_rzp.close_calls) == 1


def test_cancel_rejected_from_foreign_origin(cashier_client, fake_rzp):
    col = _create(cashier_client)
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and fake_rzp.close_calls == []


# ---------- Cancellation: paid vs cancelled ----------

def test_cannot_cancel_paid_collection(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.add_payment(col["razorpay_qr_id"], "pay_DONE", 25050)
    signed_webhook(make_client(), _credited(col["razorpay_qr_id"], "pay_DONE", 25050), "evt_done")
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 409 and "already paid" in r.json()["detail"]
    assert fake_rzp.close_calls == []


def test_payment_that_arrived_before_cancel_is_found_first(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.add_payment(col["razorpay_qr_id"], "pay_JUST", 25050)  # no webhook yet
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 409 and fake_rzp.close_calls == []
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "paid"


def test_payment_landing_during_cancel_wins(cashier_client, fake_rzp):
    col = _create(cashier_client)
    qr_id = col["razorpay_qr_id"]
    fake_rzp.before_close = lambda q: fake_rzp.add_payment(q, "pay_RACE", 25050)
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 409 and "now marked paid" in r.json()["detail"]
    detail = cashier_client.get(f"/api/collections/{col['id']}").json()
    assert detail["payment_status"] == "paid" and detail["payments"][0]["razorpay_payment_id"] == "pay_RACE"
    assert _public(col["public_token"]).json()["status"] == "paid"
    assert qr_id in fake_rzp.close_calls


def test_qr_closed_as_paid_awaiting_capture_cannot_be_cancelled(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.close(col["razorpay_qr_id"], "paid")
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 409 and "being confirmed" in r.json()["detail"]


def test_payment_in_flight_closes_qr_during_cancel(cashier_client, fake_rzp):
    """The customer's payment closes the QR (reason 'paid') just before our close call, which then fails.
    That is not a cancellation: report the in-flight payment, never 'cancelled'."""
    col = _create(cashier_client)
    fake_rzp.before_close = lambda q: fake_rzp.close(q, "paid")
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 409 and "being confirmed" in r.json()["detail"]
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "pending"
    data = _public(col["public_token"]).json()
    assert data["status"] == "pending" and data["confirming"] is True


def test_cannot_cancel_expired(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.close(col["razorpay_qr_id"], "expired")
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 409 and "expired" in r.json()["detail"]


def test_late_webhook_after_cancel_turns_paid(cashier_client, fake_rzp, monkeypatch):
    """Close succeeded but the read-back failed; a payment Razorpay captured just before the close
    arrives later by webhook and must still win."""
    col = _create(cashier_client)
    qr_id = col["razorpay_qr_id"]
    real_fetch = fake_rzp.fetch_qr
    state = {"closed": False}

    def close_then_break(q):
        state["closed"] = True
        fake_rzp.add_payment(q, "pay_LATE", 25050)

    def fetch(q):
        if state["closed"]:
            raise razorpay_api.RazorpayError(503, "Razorpay temporarily unavailable")
        return real_fetch(q)
    fake_rzp.before_close = close_then_break
    monkeypatch.setattr(razorpay_api, "fetch_qr", fetch)
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 200 and r.json()["payment_status"] == "closed"

    monkeypatch.setattr(razorpay_api, "fetch_qr", real_fetch)
    signed_webhook(make_client(), _credited(qr_id, "pay_LATE", 25050), "evt_late")
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "paid"


# ---------- Cancellation: Razorpay errors ----------

def test_razorpay_close_failure_does_not_mark_cancelled(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.fail_close = razorpay_api.RazorpayError(500, "Internal server error")
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 424 and "may still be payable" in r.json()["detail"]
    detail = cashier_client.get(f"/api/collections/{col['id']}").json()
    assert detail["payment_status"] == "pending" and detail["qr_status"] == "active"
    assert _public(col["public_token"]).json()["qr_image_url"]  # still shown: it can still be paid


def test_razorpay_unreachable_before_cancel(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.fail_fetch = True
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 424 and "not cancelled" in r.json()["detail"]
    assert fake_rzp.close_calls == []
    fake_rzp.fail_fetch = False
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "pending"


def test_close_error_but_qr_already_closed_elsewhere(cashier_client, fake_rzp):
    """Someone closed it in the Razorpay dashboard between our check and our close call."""
    col = _create(cashier_client)
    fake_rzp.before_close = lambda q: fake_rzp.close(q, "on_demand")
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 200 and r.json()["payment_status"] == "closed"


def test_razorpay_not_configured(cashier_client, fake_rzp, monkeypatch):
    col = _create(cashier_client)

    def not_configured(_):
        raise razorpay_api.RazorpayNotConfigured("Razorpay API keys are not configured")
    monkeypatch.setattr(razorpay_api, "close_qr", not_configured)
    r = cashier_client.post(f"/api/collections/{col['id']}/cancel")
    assert r.status_code == 424
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "pending"
