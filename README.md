# Universal QR Collections

Minimal payment-collection app for an Indian distribution business: authorized staff log in, generate fixed-amount Razorpay UPI QR codes, and track collections. A payment counts as received **only** after Razorpay confirms a captured payment.

## Stack
- Frontend: React 19 + TypeScript + Tailwind + shadcn/ui (`/frontend`)
- Backend: FastAPI + SQLAlchemy 2 + Alembic (`/backend`)
- Database: PostgreSQL
- Auth: bcrypt-hashed passwords, JWT access (30 min) + refresh (7 days) tokens in httpOnly cookies, token versioning (deactivation / password reset signs users out), login lockout after 5 failures for 15 minutes
- Payments: Razorpay QR Code API (`POST /v1/payments/qr_codes`, `upi_qr`, `single_use`, `fixed_amount: true`, amount in paise, auto-close after `QR_EXPIRY_MINUTES`)

## Environment variables (backend/.env)
| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL URL, e.g. `postgresql://user:pass@host:5432/qrcollections` |
| `TEST_DATABASE_URL` | Separate database for unit tests (name must end with `_test`) |
| `JWT_SECRET` | Long random string for signing sessions |
| `COOKIE_SECURE` | `true` in any HTTPS deployment |
| `FRONTEND_URL` | Public URL of the app (CORS + origin check + webhook URL); comma-separate several |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | First admin, created once by the bootstrap; never overwrites an existing account |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay API keys (`rzp_test_…` for Test Mode) |
| `RAZORPAY_WEBHOOK_SECRET` | Secret configured on the Razorpay webhook |
| `QR_EXPIRY_MINUTES` | Unpaid QR auto-close time (default deployment value 30) |
| `LOCAL_POSTGRES_BOOTSTRAP` | `true` only in the preview container (starts the bundled local PostgreSQL); omit in production |

Frontend: `REACT_APP_BACKEND_URL` only. No secrets ever reach the browser.

## Setup
```bash
# database (preview container): bash scripts/start_postgres.sh
cd backend
pip install -r requirements.txt
python migrate.py            # alembic upgrade head (also runs at app startup)
python bootstrap_admin.py    # creates the first admin from ADMIN_* env vars
uvicorn server:app --host 0.0.0.0 --port 8001

cd ../frontend && yarn install && yarn start
```

## Razorpay webhook
In Razorpay Dashboard → Settings → Webhooks add `https://<your-domain>/api/webhooks/razorpay` with your `RAZORPAY_WEBHOOK_SECRET`, events `qr_code.credited`, `qr_code.closed`, `payment.captured`. The admin "Razorpay Setup" page shows the exact URL and recent webhook events with errors.

Processing:
1. HMAC-SHA256 of the **raw body** is verified against `X-Razorpay-Signature` (constant-time compare). Invalid signatures get 400 and are logged.
2. `X-Razorpay-Event-Id` is stored with a unique constraint; already-processed events return `duplicate`.
3. The QR is identified, then reconciled against Razorpay's authoritative records (`GET /qr_codes/{id}` and `/qr_codes/{id}/payments`). Only `captured` payments with the exact amount in INR count as successful. Payment IDs are unique, so retries never double count.
4. Out-of-order events are safe: a QR closed with reason `paid` stays *pending* until the captured payment is confirmed.
5. On failure the error is saved and HTTP 500 is returned so Razorpay retries.

The frontend also polls `GET /api/collections/{id}/status?refresh=true`, which reconciles with Razorpay (throttled) if a webhook is late or missing.

**Test Mode:** Razorpay test-mode QR codes are not meant for real UPI scanning. Simulate payments from the Razorpay test dashboard.

## Tests
```bash
cd backend/unit_tests && python -m pytest -q
```
Covers authentication (login, lockout, roles, deactivation, password reset), QR creation payload/validation/errors/scoping, and webhook processing (signature, duplicates, non-captured, amount mismatch, out-of-order, retry after failure). Razorpay is faked in tests; the app itself never generates mock QRs.

## Deployment
1. Provision a hosted PostgreSQL and set `DATABASE_URL` (do not set `LOCAL_POSTGRES_BOOTSTRAP`).
2. Set all variables above as production secrets; use `rzp_live_…` keys only when ready for real money.
3. Migrations and admin bootstrap run automatically on startup (both idempotent).
4. Register the webhook URL for the production domain.
