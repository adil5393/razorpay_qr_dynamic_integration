# Universal QR Collections - API regression tests (auth, users, collections, config, webhook)
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN = {"email": "adil.shahid93@gmail.com", "password": "kRMJR_Bbf6M44isj"}
SECRET_FRAGMENTS = ["kRMJR_Bbf6M44isj"]


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    return s, r


@pytest.fixture(scope="module")
def admin():
    s, r = _login(**ADMIN)
    if r.status_code != 200:
        pytest.skip(f"admin login failed {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def cashier(admin):
    email = f"test_cashier_{uuid.uuid4().hex[:6]}@example.com"
    r = admin.post(f"{BASE_URL}/api/users", json={"name": "TEST_Cashier", "email": email, "password": "Passw0rd!1"})
    assert r.status_code == 201, r.text
    u = r.json()
    yield {"id": u["id"], "email": email, "password": "Passw0rd!1"}
    admin.patch(f"{BASE_URL}/api/users/{u['id']}", json={"is_active": False})


# Origin guard / CORS
class TestOrigin:
    def test_public_frontend_origin_allowed(self):
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "nobody_test@example.com", "password": "x"},
                          headers={"Origin": BASE_URL})
        assert r.status_code != 403, f"Public frontend origin rejected: {r.text}"


# Auth
class TestAuth:
    def test_unauth_401(self):
        for p in ["/api/auth/me", "/api/dashboard", "/api/collections", "/api/users", "/api/config"]:
            assert requests.get(f"{BASE_URL}{p}").status_code == 401, p

    def test_admin_login_cookies(self):
        s, r = _login(**ADMIN)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"
        assert "password_hash" not in r.json()
        sc = r.headers.get("set-cookie", "").lower()
        assert "access_token" in sc and "httponly" in sc and "secure" in sc
        me = s.get(f"{BASE_URL}/api/auth/me")
        assert me.status_code == 200 and me.json()["email"] == ADMIN["email"]

    def test_logout(self):
        s, _ = _login(**ADMIN)
        assert s.post(f"{BASE_URL}/api/auth/logout").status_code == 200
        assert s.get(f"{BASE_URL}/api/auth/me").status_code == 401


# Users (admin)
class TestUsers:
    def test_duplicate_email_409(self, admin, cashier):
        r = admin.post(f"{BASE_URL}/api/users", json={"name": "TEST_dup", "email": cashier["email"], "password": "Passw0rd!1"})
        assert r.status_code == 409

    def test_create_validation(self, admin):
        r = admin.post(f"{BASE_URL}/api/users", json={"name": "TEST_x", "email": "bad", "password": "short"})
        assert r.status_code == 422

    def test_list_filters(self, admin, cashier):
        active = admin.get(f"{BASE_URL}/api/users?status=active").json()
        assert any(u["id"] == cashier["id"] for u in active)
        assert all(u["is_active"] for u in active)
        inactive = admin.get(f"{BASE_URL}/api/users?status=inactive").json()
        assert all(not u["is_active"] for u in inactive)

    def test_deactivate_blocks_login_then_reactivate(self, admin, cashier):
        cs, r = _login(cashier["email"], cashier["password"])
        assert r.status_code == 200
        r = admin.patch(f"{BASE_URL}/api/users/{cashier['id']}", json={"is_active": False})
        assert r.status_code == 200 and r.json()["is_active"] is False
        assert cs.get(f"{BASE_URL}/api/auth/me").status_code == 401  # session revoked
        _, r = _login(cashier["email"], cashier["password"])
        assert r.status_code == 403 and "deactivated" in r.json()["detail"].lower()
        r = admin.patch(f"{BASE_URL}/api/users/{cashier['id']}", json={"is_active": True})
        assert r.json()["is_active"] is True
        _, r = _login(cashier["email"], cashier["password"])
        assert r.status_code == 200

    def test_cannot_deactivate_self(self, admin):
        me = admin.get(f"{BASE_URL}/api/auth/me").json()
        assert admin.patch(f"{BASE_URL}/api/users/{me['id']}", json={"is_active": False}).status_code == 400

    def test_reset_password(self, admin, cashier):
        r = admin.post(f"{BASE_URL}/api/users/{cashier['id']}/reset-password", json={"new_password": "NewPassw0rd!"})
        assert r.status_code == 200
        _, r = _login(cashier["email"], "NewPassw0rd!")
        assert r.status_code == 200
        _, r = _login(cashier["email"], cashier["password"])
        assert r.status_code == 401
        cashier["password"] = "NewPassw0rd!"

    def test_user_404(self, admin):
        assert admin.patch(f"{BASE_URL}/api/users/99999999", json={"is_active": True}).status_code == 404


# Role restrictions
class TestCashierRBAC:
    def test_cashier_forbidden(self, cashier):
        s, r = _login(cashier["email"], cashier["password"])
        assert r.status_code == 200 and r.json()["role"] == "cashier"
        assert s.get(f"{BASE_URL}/api/users").status_code == 403
        assert s.get(f"{BASE_URL}/api/admin/razorpay").status_code == 403
        assert s.get(f"{BASE_URL}/api/admin/webhook-events").status_code == 403
        assert s.post(f"{BASE_URL}/api/users", json={"name": "TEST_n", "email": "test_n@example.com", "password": "Passw0rd!1"}).status_code == 403

    def test_wrong_password_lockout(self, cashier):
        email = cashier["email"]
        codes = [_login(email, "wrong-pass")[1].status_code for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429, codes


# Collections / config / dashboard
class TestCollections:
    def test_config_not_configured(self, admin):
        c = admin.get(f"{BASE_URL}/api/config").json()
        assert c["razorpay_configured"] is False and c["qr_expiry_minutes"] == 30

    def test_create_424(self, admin):
        r = admin.post(f"{BASE_URL}/api/collections", json={"amount": "100.00", "description": "TEST_qr"})
        assert r.status_code == 424
        assert r.json()["detail"].startswith("Razorpay is not configured")

    @pytest.mark.parametrize("amount", ["0", "1.234", "-5", "1000001"])
    def test_create_invalid_amount_422(self, admin, amount):
        r = admin.post(f"{BASE_URL}/api/collections", json={"amount": amount, "description": "TEST_qr"})
        assert r.status_code == 422

    def test_create_missing_description_422(self, admin):
        r = admin.post(f"{BASE_URL}/api/collections", json={"amount": "10", "description": "   "})
        assert r.status_code == 422

    def test_list_and_filters(self, admin):
        r = admin.get(f"{BASE_URL}/api/collections?search=zzz&status=pending")
        assert r.status_code == 200 and set(r.json()) >= {"items", "total"}
        assert admin.get(f"{BASE_URL}/api/collections?status=bogus").status_code == 422
        assert admin.get(f"{BASE_URL}/api/collections/99999999").status_code == 404

    def test_dashboard(self, admin):
        d = admin.get(f"{BASE_URL}/api/dashboard").json()
        for k in ["total_confirmed_paise", "successful_payment_count", "pending_qr_count", "recent_payments"]:
            assert k in d
        assert isinstance(d["recent_payments"], list)

    def test_admin_razorpay_no_secrets(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/razorpay")
        assert r.status_code == 200
        d = r.json()
        assert d["configured"] is False
        assert d["webhook_url"].endswith("/api/webhooks/razorpay")
        assert "secret" not in str({k: v for k, v in d.items() if k != "webhook_secret_configured"}).lower()

    def test_webhook_url_matches_public_url(self, admin):
        d = admin.get(f"{BASE_URL}/api/admin/razorpay").json()
        assert d["webhook_url"] == f"{BASE_URL}/api/webhooks/razorpay", d["webhook_url"]


# Webhook
class TestWebhook:
    def test_invalid_signature_400(self):
        r = requests.post(f"{BASE_URL}/api/webhooks/razorpay", data=b'{"event":"qr_code.credited"}',
                          headers={"Content-Type": "application/json", "X-Razorpay-Signature": "deadbeef"})
        assert r.status_code == 400, r.text

    def test_missing_signature_400(self):
        r = requests.post(f"{BASE_URL}/api/webhooks/razorpay", data=b"{}")
        assert r.status_code == 400
