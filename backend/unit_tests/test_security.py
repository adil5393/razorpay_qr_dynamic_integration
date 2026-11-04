"""Phase 1 hardening: config checks, client IP / lockout, webhook limits, health, request IDs,
orphan QR handling and migration locking."""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text

import config
import razorpay_api
from conftest import PASSWORD, make_client, signed_webhook
from db import Base, engine
from server import client_ip

BACKEND_DIR = Path(__file__).resolve().parents[1]

# ---------- Startup configuration ----------

VALID_PROD = {
    "APP_ENV": "production",
    "DATABASE_URL": "postgresql://u:p@db:5432/qrcollections",
    "JWT_SECRET": "x" * 40,
    "COOKIE_SECURE": "true",
    "FRONTEND_URL": "https://pay.example.com",
    "QR_EXPIRY_MINUTES": "30",
    "RAZORPAY_KEY_ID": "rzp_test_abc123",
    "RAZORPAY_KEY_SECRET": "secret",
    "RAZORPAY_EXPECTED_MODE": "test",
    "TRUSTED_PROXIES": "172.18.0.0/16",
}


def _errors(monkeypatch, **overrides):
    for k, v in {**VALID_PROD, **overrides}.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    return config.collect_errors()


def test_valid_production_config(monkeypatch):
    assert _errors(monkeypatch) == []


def test_live_key_with_live_mode_ok_in_production(monkeypatch):
    assert _errors(monkeypatch, RAZORPAY_KEY_ID="rzp_live_abc", RAZORPAY_EXPECTED_MODE="live") == []


@pytest.mark.parametrize("overrides, fragment", [
    ({"APP_ENV": "development", "RAZORPAY_KEY_ID": "rzp_live_abc", "RAZORPAY_EXPECTED_MODE": None}, "only allowed when APP_ENV=production"),
    ({"RAZORPAY_KEY_ID": "rzp_live_abc"}, "is a live key but RAZORPAY_EXPECTED_MODE is 'test'"),
    ({"RAZORPAY_EXPECTED_MODE": None}, "RAZORPAY_EXPECTED_MODE ('test' or 'live') is required"),
    ({"RAZORPAY_KEY_SECRET": None}, "must be set together"),
    ({"RAZORPAY_KEY_ID": "abc"}, "must start with rzp_test_"),
    ({"COOKIE_SECURE": "false"}, "COOKIE_SECURE must be 'true' in production"),
    ({"FRONTEND_URL": "http://pay.example.com"}, "must use https in production"),
    ({"JWT_SECRET": "short"}, "at least 32 characters"),
    ({"JWT_SECRET": None}, "JWT_SECRET is required"),
    ({"QR_EXPIRY_MINUTES": "1"}, "QR_EXPIRY_MINUTES"),
    ({"QR_EXPIRY_MINUTES": None}, "QR_EXPIRY_MINUTES"),
    ({"DATABASE_URL": "sqlite:///x.db"}, "DATABASE_URL"),
    ({"TRUSTED_PROXIES": "not-an-ip"}, "TRUSTED_PROXIES"),
    ({"LOCAL_POSTGRES_BOOTSTRAP": "true"}, "LOCAL_POSTGRES_BOOTSTRAP"),
    ({"APP_ENV": "prod"}, "APP_ENV must be one of"),
    ({"RUN_MIGRATIONS_ON_STARTUP": "true"}, "RUN_MIGRATIONS_ON_STARTUP must be false in production"),
])
def test_invalid_config_is_reported(monkeypatch, overrides, fragment):
    errors = _errors(monkeypatch, **overrides)
    assert any(fragment in e for e in errors), errors


def test_validate_raises_with_all_problems(monkeypatch):
    _errors(monkeypatch, COOKIE_SECURE="false", JWT_SECRET="short")
    with pytest.raises(config.ConfigError) as exc:
        config.validate()
    assert "COOKIE_SECURE" in str(exc.value) and "JWT_SECRET" in str(exc.value)


# ---------- Client IP and login lockout ----------

def _req(peer, xff=None):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


@pytest.fixture
def trust_docker_proxy(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "172.18.0.0/16, 127.0.0.1")
    config.trusted_proxies.cache_clear()
    yield
    config.trusted_proxies.cache_clear()


def test_forwarded_for_ignored_from_untrusted_peer():
    config.trusted_proxies.cache_clear()
    assert client_ip(_req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"


def test_forwarded_for_from_trusted_proxy(trust_docker_proxy):
    # nginx appends the real peer on the right; anything to its left is client-supplied.
    assert client_ip(_req("172.18.0.5", "6.6.6.6, 198.51.100.7")) == "198.51.100.7"
    assert client_ip(_req("172.18.0.5", "198.51.100.7, 127.0.0.1")) == "198.51.100.7"
    assert client_ip(_req("172.18.0.5", "garbage")) == "172.18.0.5"
    assert client_ip(_req("172.18.0.5")) == "172.18.0.5"


def test_lockout_not_bypassed_by_spoofed_forwarded_for():
    client = make_client()
    for i in range(5):
        r = client.post("/api/auth/login", json={"email": "cashier@test.local", "password": "nope"},
                        headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "cashier@test.local", "password": PASSWORD},
                    headers={"X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 429


def _login_from(peer: str, xff: str | None, password: str = "nope") -> int:
    """POST /api/auth/login with an exact TCP peer address, as uvicorn --no-proxy-headers would see it."""
    import asyncio

    import httpx

    from server import app

    async def go():
        transport = httpx.ASGITransport(app=app, client=(peer, 40000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            headers = {"X-Forwarded-For": xff} if xff else {}
            r = await c.post("/api/auth/login", json={"email": "cashier@test.local", "password": password}, headers=headers)
            return r.status_code
    return asyncio.run(go())


def test_behind_trusted_nginx_spoofed_hops_cannot_bypass_lockout(trust_docker_proxy):
    # Attacker sends their own X-Forwarded-For; nginx ($proxy_add_x_forwarded_for) appends the real IP.
    for i in range(5):
        assert _login_from("172.18.0.5", f"6.6.6.{i}, 198.51.100.7") == 401
    assert _login_from("172.18.0.5", "9.9.9.9, 198.51.100.7", password=PASSWORD) == 429
    # A different real client is unaffected.
    assert _login_from("172.18.0.5", "198.51.100.8", password=PASSWORD) == 200


def test_direct_connection_bypassing_nginx_cannot_spoof(trust_docker_proxy):
    # Someone reaching the app port directly (not from a trusted proxy) has their header ignored.
    for i in range(5):
        assert _login_from("203.0.113.50", f"10.0.0.{i}") == 401
    assert _login_from("203.0.113.50", "10.9.9.9", password=PASSWORD) == 429


# ---------- Webhook hardening ----------

def test_rejected_webhook_rows_are_capped(admin_client):
    anon = make_client()
    for i in range(25):
        signed_webhook(anon, {"event": "qr_code.credited"}, f"evt_bad_{i}", secret="wrong")
    rejected = [e for e in admin_client.get("/api/admin/webhook-events").json() if e["status"] == "rejected"]
    assert len(rejected) == 20


def test_unknown_qr_event_is_flagged_unmatched(admin_client):
    event = {"event": "qr_code.credited", "payload": {
        "qr_code": {"entity": {"id": "qr_UNKNOWN01"}}, "payment": {"entity": {"id": "pay_orphan"}}}}
    anon = make_client()
    r = signed_webhook(anon, event, "evt_orphan")
    assert r.status_code == 200 and r.json()["status"] == "unmatched"
    assert signed_webhook(anon, event, "evt_orphan").json()["status"] == "duplicate"
    ev = admin_client.get("/api/admin/webhook-events").json()[0]
    assert ev["status"] == "unmatched" and "qr_UNKNOWN01" in ev["error"]


def test_non_qr_payment_event_is_ignored():
    event = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_from_checkout"}}}}
    assert signed_webhook(make_client(), event, "evt_other_product").json()["status"] == "ignored"


def test_oversized_webhook_rejected():
    r = make_client().post("/api/webhooks/razorpay", content=b"x" * (300 * 1024),
                           headers={"Content-Type": "application/json", "X-Razorpay-Signature": "0" * 64})
    assert r.status_code == 413


# ---------- Orphan QR protection ----------

def test_qr_is_closed_at_razorpay_if_saving_fails(cashier_client, fake_rzp, monkeypatch):
    closed = []
    monkeypatch.setattr(razorpay_api, "close_qr", lambda qr_id: closed.append(qr_id) or {"status": "closed"})
    first = cashier_client.post("/api/collections", json={"amount": "10", "description": "A"}).json()
    # Make Razorpay hand back an id we already stored, so the database insert fails.
    original = fake_rzp.create_qr
    monkeypatch.setattr(razorpay_api, "create_qr", lambda p: {**original(p), "id": first["razorpay_qr_id"]})
    r = cashier_client.post("/api/collections", json={"amount": "10", "description": "B"})
    assert r.status_code == 500 and "cancelled" in r.json()["detail"]
    assert closed == [first["razorpay_qr_id"]]
    assert cashier_client.get("/api/collections").json()["total"] == 1


# ---------- Health and request IDs ----------

def test_health_checks_database():
    client = make_client()
    assert client.get("/api/health").json() == {"ok": True, "database": "ok"}
    assert client.get("/api/health/live").json() == {"ok": True}


def test_request_id_header():
    client = make_client()
    generated = client.get("/api/health").headers["X-Request-ID"]
    assert len(generated) == 32
    assert client.get("/api/health", headers={"X-Request-ID": "abc12345-proxy"}).headers["X-Request-ID"] == "abc12345-proxy"
    assert client.get("/api/health", headers={"X-Request-ID": "bad id\n"}).headers["X-Request-ID"] != "bad id\n"


# ---------- Migrations ----------

def test_startup_refuses_out_of_date_schema():
    from migrate import ensure_database_at_head

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    with pytest.raises(RuntimeError, match="Run `python migrate.py`"):
        ensure_database_at_head()


def test_migrations_apply_cleanly_and_concurrently():
    """Real Alembic migrations (not create_all), started by two processes at once as two workers would.
    The advisory lock makes the second wait, then find nothing left to do."""
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    # DATABASE_URL is the *_test database (set in conftest); child processes inherit it.
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    code = "from migrate import run_migrations; run_migrations()"
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for _ in range(2)]
    outputs = [p.communicate(timeout=120)[0].decode(errors="replace") for p in procs]
    errors = [out for p, out in zip(procs, outputs) if p.returncode != 0]
    try:
        assert errors == [], errors
        tables = set(inspect(engine).get_table_names())
        assert {"users", "qr_collections", "payments", "webhook_events", "login_attempts", "alembic_version"} <= tables
        from migrate import ensure_database_at_head, pending_migration_state

        current, head = pending_migration_state()
        assert current == head
        ensure_database_at_head()  # does not raise
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
