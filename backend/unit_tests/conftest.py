import os
from pathlib import Path

from dotenv import dotenv_values

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
TEST_DB = os.environ.get("TEST_DATABASE_URL") or _env.get("TEST_DATABASE_URL")
assert TEST_DB and TEST_DB.rsplit("/", 1)[-1].endswith("_test"), "TEST_DATABASE_URL must point to a *_test database"

os.environ.update({
    "DATABASE_URL": TEST_DB,
    "JWT_SECRET": "test-secret-for-pytest-only-0123456789abcdef",
    "COOKIE_SECURE": "false",
    "FRONTEND_URL": "http://testserver",
    "QR_EXPIRY_MINUTES": "30",
    "RAZORPAY_KEY_ID": "rzp_test_dummykey1234",
    "RAZORPAY_KEY_SECRET": "dummy_secret",
    "RAZORPAY_WEBHOOK_SECRET": "whsec_test_123",
    "ADMIN_EMAIL": "",
    "ADMIN_PASSWORD": "",
})

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import razorpay_api  # noqa: E402
from auth import hash_password  # noqa: E402
from db import Base, SessionLocal, engine  # noqa: E402
from models import User  # noqa: E402
from server import app, public_limiter  # noqa: E402

PASSWORD = "Passw0rd!23"


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all([
            User(email="admin@test.local", name="Admin", password_hash=hash_password(PASSWORD), role="admin"),
            User(email="cashier@test.local", name="Cashier One", password_hash=hash_password(PASSWORD), role="cashier"),
            User(email="cashier2@test.local", name="Cashier Two", password_hash=hash_password(PASSWORD), role="cashier"),
        ])
        db.commit()
    public_limiter.reset()
    yield


def make_client(email: str | None = None) -> TestClient:
    client = TestClient(app)
    if email:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
    return client


@pytest.fixture
def admin_client():
    return make_client("admin@test.local")


@pytest.fixture
def cashier_client():
    return make_client("cashier@test.local")


class FakeRazorpay:
    def __init__(self):
        self.qrs: dict[str, dict] = {}
        self.payments: dict[str, list[dict]] = {}
        self.created_payloads: list[dict] = []
        self.fail_fetch = False
        self.fail_close: Exception | None = None  # raised by close_qr
        self.before_close = None  # callable(qr_id), e.g. to land a payment just before the close
        self.close_calls: list[str] = []

    def create_qr(self, payload):
        self.created_payloads.append(payload)
        qr_id = f"qr_TEST{len(self.qrs) + 1:06d}"
        self.qrs[qr_id] = {
            "id": qr_id, "entity": "qr_code", "status": "active", "close_reason": None, "closed_at": None,
            "payment_amount": payload["payment_amount"], "close_by": payload["close_by"],
            "image_url": f"https://rzp.io/i/{qr_id}",
        }
        self.payments[qr_id] = []
        return self.qrs[qr_id]

    def fetch_qr(self, qr_id):
        if self.fail_fetch:
            raise razorpay_api.RazorpayError(503, "Razorpay temporarily unavailable")
        return self.qrs[qr_id]

    def fetch_qr_payments(self, qr_id):
        if self.fail_fetch:
            raise razorpay_api.RazorpayError(503, "Razorpay temporarily unavailable")
        return self.payments[qr_id]

    def add_payment(self, qr_id, pay_id, amount, status="captured"):
        p = {"id": pay_id, "entity": "payment", "amount": amount, "currency": "INR", "status": status,
             "captured": status == "captured", "method": "upi", "vpa": "test@upi", "created_at": int(time.time())}
        self.payments[qr_id].append(p)
        return p

    def close_qr(self, qr_id):
        self.close_calls.append(qr_id)
        if self.before_close:
            self.before_close(qr_id)
        if self.fail_close:
            raise self.fail_close
        qr = self.qrs[qr_id]
        if qr["status"] == "closed":
            raise razorpay_api.RazorpayError(400, "QR code is already closed")
        self.close(qr_id, "on_demand")
        return dict(qr)

    def close(self, qr_id, reason):
        self.qrs[qr_id].update({"status": "closed", "close_reason": reason, "closed_at": int(time.time())})


@pytest.fixture
def fake_rzp(monkeypatch):
    fake = FakeRazorpay()
    monkeypatch.setattr(razorpay_api, "create_qr", fake.create_qr)
    monkeypatch.setattr(razorpay_api, "fetch_qr", fake.fetch_qr)
    monkeypatch.setattr(razorpay_api, "fetch_qr_payments", fake.fetch_qr_payments)
    monkeypatch.setattr(razorpay_api, "close_qr", fake.close_qr)
    return fake


def signed_webhook(client: TestClient, payload: dict, event_id: str, secret: str = "whsec_test_123"):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks/razorpay", content=body, headers={
        "Content-Type": "application/json", "X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id,
    })
