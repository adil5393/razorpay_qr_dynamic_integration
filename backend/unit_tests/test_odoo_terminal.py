"""Stage A tests use the dedicated disposable *_test database and fake transports."""
import hashlib
import hmac
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

import odoo_terminal
import razorpay_api
from conftest import make_client, signed_webhook
from db import SessionLocal
from models import CallbackDelivery

URL = "https://odoo.example.test/terminal-callback"
BODY = {"instance": "test-db", "request_reference": "request-123", "invoice_id": "42",
        "invoice_number": "INV/42", "customer_id": "9", "customer_name": "Customer",
        "amount_paise": 5000, "currency": "INR"}


def provision(admin, monkeypatch):
    monkeypatch.setenv("ODOO_CALLBACK_URLS", URL)
    response = admin.post("/api/admin/odoo-clients", json={"name": "Odoo", "instance": "test-db", "callback_url": URL})
    assert response.status_code == 201
    return {"X-Odoo-Key": response.json()["api_key"]}


def test_auth_instance_validation_and_cutover(admin_client, cashier_client, fake_rzp, monkeypatch):
    monkeypatch.setenv("ODOO_TERMINAL_CUTOVER", "true")
    assert cashier_client.post("/api/collections", json={"amount": "5", "description": "x"}).status_code == 403
    assert cashier_client.post("/api/admin/odoo-clients", json={"name": "x", "instance": "x", "callback_url": URL}).status_code == 403
    assert make_client().post("/api/odoo/payment-requests", json=BODY).status_code == 401
    headers = provision(admin_client, monkeypatch)
    assert make_client().post("/api/odoo/payment-requests", headers=headers, json={**BODY, "instance": "other"}).status_code == 403
    assert make_client().post("/api/odoo/payment-requests", headers=headers, json={**BODY, "currency": "USD"}).status_code == 422
    assert make_client().post("/api/odoo/payment-requests", headers=headers, json={**BODY, "amount_paise": 0}).status_code == 422
    assert not fake_rzp.created_payloads


def test_duplicate_request_and_changed_payload(admin_client, fake_rzp, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    client = make_client()
    a = client.post("/api/odoo/payment-requests", headers=headers, json=BODY)
    b = client.post("/api/odoo/payment-requests", headers=headers, json=BODY)
    assert a.status_code == b.status_code == 202
    assert a.json()["id"] == b.json()["id"] and b.json()["state"] == "ready"
    assert client.post("/api/odoo/payment-requests", headers=headers, json={**BODY, "amount_paise": 1000}).status_code == 409
    assert len(fake_rzp.created_payloads) == 1


def test_concurrent_request_sees_durable_claim(admin_client, fake_rzp, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    started, release = threading.Event(), threading.Event()
    original = fake_rzp.create_qr
    def slow(payload):
        started.set()
        assert release.wait(10)
        return original(payload)
    monkeypatch.setattr(razorpay_api, "create_qr", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(lambda: make_client().post("/api/odoo/payment-requests", headers=headers, json=BODY))
        assert started.wait(10)
        duplicate = make_client().post("/api/odoo/payment-requests", headers=headers, json=BODY)
        release.set()
        first = future.result(timeout=10)
    assert duplicate.json()["state"] == "creating"
    assert first.json()["state"] == "ready"
    assert len(fake_rzp.created_payloads) == 1


def test_ambiguous_create_never_retried(admin_client, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    calls = []
    def timeout(payload):
        calls.append(payload)
        raise razorpay_api.RazorpayError(502, "timeout")
    monkeypatch.setattr(razorpay_api, "create_qr", timeout)
    client = make_client()
    assert client.post("/api/odoo/payment-requests", headers=headers, json=BODY).json()["state"] == "ambiguous"
    assert client.post("/api/odoo/payment-requests", headers=headers, json=BODY).json()["state"] == "ambiguous"
    assert len(calls) == 1


def test_webhook_outbox_delivery_failure_and_retry(admin_client, fake_rzp, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    result = make_client().post("/api/odoo/payment-requests", headers=headers, json=BODY).json()
    col = result["collection"]
    fake_rzp.add_payment(col["razorpay_qr_id"], "pay_partial_invoice", 5000)
    event = {"event": "qr_code.credited", "payload": {"qr_code": {"entity": {"id": col["razorpay_qr_id"]}}}}
    assert signed_webhook(make_client(), event, "evt_1").status_code == 200
    assert signed_webhook(make_client(), event, "evt_1").json()["status"] == "duplicate"
    signed_webhook(make_client(), event, "evt_2")
    with SessionLocal() as db:
        rows = db.scalars(select(CallbackDelivery)).all()
        assert len(rows) == 1 and rows[0].payload["razorpay_payment_id"] == "pay_partial_invoice"
    sent = []
    class FakeHTTP:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, content, headers):
            sent.append((url, content, headers))
            return type("Response", (), {"status_code": 503 if len(sent) == 1 else 200})()
    monkeypatch.setattr(odoo_terminal.httpx, "Client", FakeHTTP)
    assert odoo_terminal.deliver_one()
    row = admin_client.get("/api/admin/odoo-deliveries").json()[0]
    assert row["status"] == "failed" and row["last_response_status"] == 503
    assert admin_client.post(f"/api/admin/odoo-deliveries/{row['id']}/retry").status_code == 200
    assert odoo_terminal.deliver_one()
    assert admin_client.get("/api/admin/odoo-deliveries").json()[0]["status"] == "delivered"
    key = hashlib.sha256(headers["X-Odoo-Key"].encode()).digest()
    assert hmac.compare_digest(sent[0][2]["X-Terminal-Signature"], hmac.new(key, sent[0][1], hashlib.sha256).hexdigest())
    assert sent[0][1] == sent[1][1]


def test_cashier_sees_requests_but_cannot_cancel(admin_client, cashier_client, fake_rzp, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    result = make_client().post("/api/odoo/payment-requests", headers=headers, json=BODY).json()
    monkeypatch.setenv("ODOO_TERMINAL_CUTOVER", "true")
    assert cashier_client.get("/api/terminal/requests").json()[0]["invoice_number"] == BODY["invoice_number"]
    cid = result["collection"]["id"]
    assert cashier_client.get(f"/api/collections/{cid}").status_code == 200
    assert cashier_client.post(f"/api/collections/{cid}/cancel").status_code == 403
    assert cashier_client.get("/api/admin/odoo-deliveries").status_code == 403
    assert not fake_rzp.close_calls


def test_failed_and_mismatched_payments_do_not_queue(admin_client, fake_rzp, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    result = make_client().post("/api/odoo/payment-requests", headers=headers, json=BODY).json()
    qr = result["collection"]["razorpay_qr_id"]
    fake_rzp.add_payment(qr, "pay_failed", 5000, status="failed")
    fake_rzp.add_payment(qr, "pay_wrong", 1000)
    event = {"event": "qr_code.credited", "payload": {"qr_code": {"entity": {"id": qr}}}}
    assert signed_webhook(make_client(), event, "evt_mismatch").status_code == 200
    assert make_client().get("/api/odoo/payment-requests/" + str(result["id"]), headers=headers).json()["collection"]["payment_status"] == "pending"
    with SessionLocal() as db:
        assert db.scalars(select(CallbackDelivery)).all() == []


def test_revoked_client_cannot_create(admin_client, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    client_id = admin_client.get("/api/admin/odoo-clients").json()[0]["id"]
    assert admin_client.post(f"/api/admin/odoo-clients/{client_id}/revoke").status_code == 200
    assert make_client().post("/api/odoo/payment-requests", headers=headers, json=BODY).status_code == 401


def test_request_reference_survives_client_rotation(admin_client, fake_rzp, monkeypatch):
    first_key = provision(admin_client, monkeypatch)
    first = make_client().post("/api/odoo/payment-requests", headers=first_key, json=BODY).json()
    second_key = provision(admin_client, monkeypatch)
    retry = make_client().post("/api/odoo/payment-requests", headers=second_key, json=BODY)
    assert retry.json()["id"] == first["id"]
    assert len(fake_rzp.created_payloads) == 1


def test_expired_qr_remains_unpaid(admin_client, fake_rzp, monkeypatch):
    headers = provision(admin_client, monkeypatch)
    result = make_client().post("/api/odoo/payment-requests", headers=headers, json=BODY).json()
    qr = result["collection"]["razorpay_qr_id"]
    fake_rzp.close(qr, "expired")
    event = {"event": "qr_code.closed", "payload": {"qr_code": {"entity": {"id": qr}}}}
    assert signed_webhook(make_client(), event, "evt_expired").status_code == 200
    response = make_client().get("/api/odoo/payment-requests/" + str(result["id"]), headers=headers).json()
    assert response["collection"]["payment_status"] == "expired"
    with SessionLocal() as db:
        assert db.scalars(select(CallbackDelivery)).all() == []
