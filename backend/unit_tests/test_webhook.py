from conftest import make_client, signed_webhook


def _create(client, amount="100"):
    return client.post("/api/collections", json={"amount": amount, "description": "Counter"}).json()


def _credited_event(qr_id, pay_id, amount):
    return {
        "entity": "event", "event": "qr_code.credited",
        "payload": {
            "payment": {"entity": {"id": pay_id, "amount": amount, "status": "captured"}},
            "qr_code": {"entity": {"id": qr_id, "status": "closed", "close_reason": "paid"}},
        },
    }


def test_invalid_signature_rejected(cashier_client, admin_client, fake_rzp):
    col = _create(cashier_client)
    r = signed_webhook(make_client(), _credited_event(col["razorpay_qr_id"], "pay_X", 10000), "evt_bad", secret="wrong")
    assert r.status_code == 400
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "pending"
    events = admin_client.get("/api/admin/webhook-events").json()
    assert events[0]["status"] == "rejected" and events[0]["signature_valid"] is False


def test_captured_payment_marks_paid(cashier_client, fake_rzp):
    col = _create(cashier_client)
    qr_id = col["razorpay_qr_id"]
    fake_rzp.add_payment(qr_id, "pay_001", 10000)
    fake_rzp.close(qr_id, "paid")
    r = signed_webhook(make_client(), _credited_event(qr_id, "pay_001", 10000), "evt_1")
    assert r.status_code == 200 and r.json()["status"] == "processed"
    detail = cashier_client.get(f"/api/collections/{col['id']}").json()
    assert detail["payment_status"] == "paid"
    assert detail["payments"][0]["razorpay_payment_id"] == "pay_001"
    assert detail["payments"][0]["is_successful"] is True
    dash = cashier_client.get("/api/dashboard").json()
    assert dash["total_confirmed_paise"] == 10000 and dash["successful_payment_count"] == 1
    assert dash["pending_qr_count"] == 0


def test_duplicate_events_and_payments_are_not_double_counted(cashier_client, fake_rzp):
    col = _create(cashier_client)
    qr_id = col["razorpay_qr_id"]
    fake_rzp.add_payment(qr_id, "pay_dup", 10000)
    anon = make_client()
    assert signed_webhook(anon, _credited_event(qr_id, "pay_dup", 10000), "evt_dup").json()["status"] == "processed"
    assert signed_webhook(anon, _credited_event(qr_id, "pay_dup", 10000), "evt_dup").json()["status"] == "duplicate"
    payment_captured = {"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_dup"}}}}
    assert signed_webhook(anon, payment_captured, "evt_other").json()["status"] == "processed"
    detail = cashier_client.get(f"/api/collections/{col['id']}").json()
    assert len(detail["payments"]) == 1
    assert cashier_client.get("/api/dashboard").json()["successful_payment_count"] == 1


def test_non_captured_or_wrong_amount_not_successful(cashier_client, fake_rzp):
    col = _create(cashier_client)
    qr_id = col["razorpay_qr_id"]
    fake_rzp.add_payment(qr_id, "pay_failed", 10000, status="failed")
    fake_rzp.add_payment(qr_id, "pay_short", 5000)
    signed_webhook(make_client(), _credited_event(qr_id, "pay_short", 5000), "evt_2")
    detail = cashier_client.get(f"/api/collections/{col['id']}").json()
    assert detail["payment_status"] == "pending"
    assert all(not p["is_successful"] for p in detail["payments"])
    assert any("mismatch" in (p["error_description"] or "") for p in detail["payments"])


def test_out_of_order_closed_before_credited(cashier_client, fake_rzp):
    col = _create(cashier_client)
    qr_id = col["razorpay_qr_id"]
    fake_rzp.close(qr_id, "paid")
    closed = {"event": "qr_code.closed", "payload": {"qr_code": {"entity": {"id": qr_id, "status": "closed"}}}}
    assert signed_webhook(make_client(), closed, "evt_closed").status_code == 200
    detail = cashier_client.get(f"/api/collections/{col['id']}").json()
    assert detail["qr_status"] == "closed" and detail["payment_status"] == "pending"
    fake_rzp.add_payment(qr_id, "pay_late", 10000)
    signed_webhook(make_client(), _credited_event(qr_id, "pay_late", 10000), "evt_credit")
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "paid"


def test_expired_qr(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.close(col["razorpay_qr_id"], "expired")
    closed = {"event": "qr_code.closed", "payload": {"qr_code": {"entity": {"id": col["razorpay_qr_id"]}}}}
    signed_webhook(make_client(), closed, "evt_exp")
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "expired"


def test_processing_failure_then_retry(cashier_client, admin_client, fake_rzp):
    col = _create(cashier_client)
    qr_id = col["razorpay_qr_id"]
    fake_rzp.add_payment(qr_id, "pay_retry", 10000)
    fake_rzp.fail_fetch = True
    r = signed_webhook(make_client(), _credited_event(qr_id, "pay_retry", 10000), "evt_retry")
    assert r.status_code == 500
    ev = admin_client.get("/api/admin/webhook-events").json()[0]
    assert ev["status"] == "failed" and "unavailable" in ev["error"]
    fake_rzp.fail_fetch = False
    r = signed_webhook(make_client(), _credited_event(qr_id, "pay_retry", 10000), "evt_retry")
    assert r.status_code == 200 and r.json()["status"] == "processed"
    ev = admin_client.get("/api/admin/webhook-events").json()[0]
    assert ev["status"] == "processed" and ev["attempts"] == 2
    assert cashier_client.get(f"/api/collections/{col['id']}").json()["payment_status"] == "paid"


def test_status_check_polls_razorpay(cashier_client, fake_rzp):
    col = _create(cashier_client)
    fake_rzp.add_payment(col["razorpay_qr_id"], "pay_poll", 10000)
    r = cashier_client.get(f"/api/collections/{col['id']}/status", params={"refresh": "true"}).json()
    assert r["payment_status"] == "paid"
    assert r["successful_payment"]["razorpay_payment_id"] == "pay_poll"
