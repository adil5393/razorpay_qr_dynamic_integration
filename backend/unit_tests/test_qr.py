import razorpay_api
from conftest import make_client


def test_create_qr_sends_correct_payload(cashier_client, fake_rzp):
    r = cashier_client.post("/api/collections", json={
        "amount": "123.45", "reference": "INV-001", "customer_name": "Ravi Traders", "description": "Invoice payment",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    sent = fake_rzp.created_payloads[0]
    assert sent["type"] == "upi_qr"
    assert sent["usage"] == "single_use"
    assert sent["fixed_amount"] is True
    assert sent["payment_amount"] == 12345
    assert body["amount_paise"] == 12345
    assert body["razorpay_qr_id"] == "qr_TEST000001"
    assert body["image_url"].startswith("https://")
    assert body["payment_status"] == "pending"
    assert body["created_by"]["name"] == "Cashier One"
    assert body["close_by"] is not None


def test_create_qr_validation(cashier_client, fake_rzp):
    assert cashier_client.post("/api/collections", json={"amount": "0", "description": "x"}).status_code == 422
    assert cashier_client.post("/api/collections", json={"amount": "0.50", "description": "x"}).status_code == 422
    assert cashier_client.post("/api/collections", json={"amount": "10.123", "description": "x"}).status_code == 422
    assert cashier_client.post("/api/collections", json={"amount": "10", "description": "  "}).status_code == 422
    assert fake_rzp.created_payloads == []


def test_create_qr_not_configured(cashier_client, monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID")
    r = cashier_client.post("/api/collections", json={"amount": "10", "description": "x"})
    assert r.status_code == 424


def test_create_qr_razorpay_error(cashier_client, monkeypatch):
    def boom(payload):
        raise razorpay_api.RazorpayError(400, "The api key provided is invalid")
    monkeypatch.setattr(razorpay_api, "create_qr", boom)
    r = cashier_client.post("/api/collections", json={"amount": "10", "description": "x"})
    assert r.status_code == 424 and "invalid" in r.json()["detail"]
    assert cashier_client.get("/api/collections").json()["total"] == 0


def test_cashier_scope_and_admin_visibility(cashier_client, admin_client, fake_rzp):
    cid = cashier_client.post("/api/collections", json={"amount": "50", "description": "x", "reference": "REF-9"}).json()["id"]
    other = make_client("cashier2@test.local")
    assert other.get(f"/api/collections/{cid}").status_code == 404
    assert other.get("/api/collections").json()["total"] == 0
    assert admin_client.get(f"/api/collections/{cid}").status_code == 200
    assert admin_client.get("/api/collections", params={"search": "ref-9"}).json()["total"] == 1
    assert admin_client.get("/api/collections", params={"status": "paid"}).json()["total"] == 0


def test_amount_cannot_be_edited(cashier_client, fake_rzp):
    cid = cashier_client.post("/api/collections", json={"amount": "50", "description": "x"}).json()["id"]
    assert cashier_client.patch(f"/api/collections/{cid}", json={"amount": "1"}).status_code == 405
    assert cashier_client.put(f"/api/collections/{cid}", json={"amount": "1"}).status_code == 405


def test_generating_qr_does_not_count_as_payment(cashier_client, fake_rzp):
    cashier_client.post("/api/collections", json={"amount": "50", "description": "x"})
    d = cashier_client.get("/api/dashboard").json()
    assert d["total_confirmed_paise"] == 0
    assert d["successful_payment_count"] == 0
    assert d["pending_qr_count"] == 1
