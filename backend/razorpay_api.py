import hashlib
import hmac
import os

import httpx

BASE_URL = "https://api.razorpay.com/v1"


class RazorpayNotConfigured(Exception):
    pass


class RazorpayError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _key_id() -> str:
    return (os.environ.get("RAZORPAY_KEY_ID") or "").strip()


def _credentials() -> tuple[str, str]:
    key_id = _key_id()
    secret = (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip()
    if not is_configured():
        raise RazorpayNotConfigured("Razorpay API keys are not configured")
    return key_id, secret


def is_configured() -> bool:
    return _key_id().startswith(("rzp_test_", "rzp_live_")) and bool((os.environ.get("RAZORPAY_KEY_SECRET") or "").strip())


def mode() -> str | None:
    key_id = _key_id()
    if key_id.startswith("rzp_test_"):
        return "test"
    if key_id.startswith("rzp_live_"):
        return "live"
    return None


def masked_key_id() -> str | None:
    key_id = _key_id()
    if not key_id:
        return None
    return f"{key_id[:9]}••••{key_id[-4:]}"


def _webhook_secret() -> str:
    return (os.environ.get("RAZORPAY_WEBHOOK_SECRET") or "").strip()


def webhook_secret_configured() -> bool:
    return bool(_webhook_secret())


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    secret = _webhook_secret()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _request(method: str, path: str, json: dict | None = None) -> dict:
    auth = _credentials()
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.request(method, f"{BASE_URL}{path}", auth=auth, json=json)
    except httpx.HTTPError as exc:
        raise RazorpayError(502, f"Could not reach Razorpay ({exc.__class__.__name__})")
    if resp.status_code >= 400:
        try:
            message = (resp.json().get("error") or {}).get("description") or resp.text
        except ValueError:
            message = resp.text
        raise RazorpayError(resp.status_code, str(message)[:500])
    return resp.json()


def create_qr(payload: dict) -> dict:
    return _request("POST", "/payments/qr_codes", json=payload)


def fetch_qr(qr_id: str) -> dict:
    return _request("GET", f"/payments/qr_codes/{qr_id}")


def fetch_qr_payments(qr_id: str) -> list[dict]:
    return _request("GET", f"/payments/qr_codes/{qr_id}/payments").get("items", [])


def download_image(url: str) -> tuple[bytes, str]:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        raise RazorpayError(502, f"Could not download QR image ({exc.__class__.__name__})")
    if resp.status_code >= 400:
        raise RazorpayError(resp.status_code, "Could not download QR image")
    return resp.content, resp.headers.get("content-type", "image/png")
