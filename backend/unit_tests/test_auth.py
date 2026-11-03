from conftest import PASSWORD, make_client


def test_login_sets_session_and_me_works():
    client = make_client()
    r = client.post("/api/auth/login", json={"email": "ADMIN@test.local", "password": PASSWORD})
    assert r.status_code == 200
    assert "password_hash" not in r.json()
    assert "access_token" in r.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["role"] == "admin"


def test_wrong_password_and_lockout():
    client = make_client()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "cashier@test.local", "password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "cashier@test.local", "password": PASSWORD})
    assert r.status_code == 429


def test_unauthenticated_requests_rejected():
    client = make_client()
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/collections").status_code == 401
    assert client.get("/api/dashboard").status_code == 401


def test_no_public_registration():
    client = make_client()
    assert client.post("/api/auth/register", json={"email": "x@y.z", "password": "12345678"}).status_code in (404, 405)


def test_cashier_cannot_manage_users_or_view_razorpay(cashier_client):
    assert cashier_client.get("/api/users").status_code == 403
    assert cashier_client.post("/api/users", json={"name": "X", "email": "x@y.zz", "password": "longpassword"}).status_code == 403
    assert cashier_client.get("/api/admin/razorpay").status_code == 403


def test_admin_user_lifecycle(admin_client):
    r = admin_client.post("/api/users", json={"name": "New Cashier", "email": "New@Test.local", "password": "Cashier#2026"})
    assert r.status_code == 201 and r.json()["role"] == "cashier"
    uid = r.json()["id"]
    assert admin_client.post("/api/users", json={"name": "Dup", "email": "new@test.local", "password": "Cashier#2026"}).status_code == 409

    cashier = make_client()
    assert cashier.post("/api/auth/login", json={"email": "new@test.local", "password": "Cashier#2026"}).status_code == 200

    assert admin_client.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 200
    assert cashier.get("/api/auth/me").status_code == 401
    assert make_client().post("/api/auth/login", json={"email": "new@test.local", "password": "Cashier#2026"}).status_code == 403

    assert admin_client.patch(f"/api/users/{uid}", json={"is_active": True}).status_code == 200
    assert admin_client.post(f"/api/users/{uid}/reset-password", json={"new_password": "Changed#2026"}).status_code == 200
    assert make_client().post("/api/auth/login", json={"email": "new@test.local", "password": "Changed#2026"}).status_code == 200
    assert admin_client.get("/api/users", params={"status": "active"}).status_code == 200


def test_admin_cannot_deactivate_self(admin_client):
    me = admin_client.get("/api/auth/me").json()
    assert admin_client.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 400
