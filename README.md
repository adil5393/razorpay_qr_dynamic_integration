# Universal QR Collections

Minimal payment-collection app for an Indian distribution business: authorized staff log in, generate fixed-amount Razorpay UPI QR codes, and track collections. A payment counts as received **only** after Razorpay confirms a captured payment.

## Stack
- Frontend: React 19 + TypeScript + Tailwind + shadcn/ui (`/frontend`)
- Backend: FastAPI + SQLAlchemy 2 + Alembic (`/backend`)
- Database: PostgreSQL
- Auth: bcrypt-hashed passwords, JWT access (30 min) + refresh (7 days) tokens in httpOnly cookies, token versioning (deactivation / password reset signs users out), login lockout after 5 failures for 15 minutes
- Payments: Razorpay QR Code API (`POST /v1/payments/qr_codes`, `upi_qr`, `single_use`, `fixed_amount: true`, amount in paise, auto-close after `QR_EXPIRY_MINUTES`)

## Environment variables (backend/.env)
Copy `backend/.env.example` to `backend/.env`. The backend checks the configuration at startup and refuses to start with a list of problems if anything is missing or unsafe.

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` (default), `test` or `production`. Production enforces https origins, `COOKIE_SECURE=true`, a 32+ character `JWT_SECRET` and an explicit `RAZORPAY_EXPECTED_MODE` |
| `DATABASE_URL` | PostgreSQL URL, e.g. `postgresql://…` (psycopg2) or `postgresql+psycopg://…` (psycopg 3) |
| `TEST_DATABASE_URL` | Separate database for unit tests (name must end with `_test`) |
| `JWT_SECRET` | Long random string for signing sessions |
| `COOKIE_SECURE` | `true` in any HTTPS deployment |
| `FRONTEND_URL` | Public URL of the app (CORS + origin check + webhook URL); comma-separate several |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_NAME` | First admin, created once by the bootstrap; never overwrites an existing account |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay API keys (`rzp_test_…` for Test Mode) |
| `RAZORPAY_WEBHOOK_SECRET` | Secret configured on the Razorpay webhook |
| `QR_EXPIRY_MINUTES` | Unpaid QR auto-close time, 3–1440 (default deployment value 30) |
| `RAZORPAY_EXPECTED_MODE` | `test` or `live`; must match the key. Required in production. Live keys are refused unless `APP_ENV=production` |
| `TRUSTED_PROXIES` | IPs/CIDRs of reverse proxies whose `X-Forwarded-For` is believed (e.g. the nginx Docker network). Empty = trust none |
| `RUN_MIGRATIONS_ON_STARTUP` | Development convenience (default `true` outside production). Must be `false` in production, where `python migrate.py` is an explicit release step |
| `LOG_FORMAT`, `LOG_LEVEL` | `text` (default) or `json`; every log line and response carries an `X-Request-ID` |
| `LOCAL_POSTGRES_BOOTSTRAP` | `true` only in the preview container (starts the bundled local PostgreSQL); omit in production |

Frontend: `REACT_APP_BACKEND_URL` only. No secrets ever reach the browser.

## Setup
```bash
# database (preview container): bash scripts/start_postgres.sh
cd backend
pip install -r requirements-dev.txt   # production installs requirements.txt only
python migrate.py            # apply migrations explicitly (see "Migrations")
python bootstrap_admin.py    # creates the first admin from ADMIN_* env vars
uvicorn server:app --host 0.0.0.0 --port 8001

cd ../frontend && npm ci && npm start
```

## Database schema (migrations)
| Revision | Contents |
|---|---|
| `0001_initial` | users, qr_collections, payments, webhook_events, login_attempts |
| `0002_integration_foundation` | Additive. `qr_collections` gains `public_token` (random, unique, backfilled), `source` (`dashboard`/`api`), `api_client_id`, `idempotency_key` + `idempotency_fingerprint` (unique per API client), `updated_at`, and amount checks. New tables: `api_clients` (only a key prefix + key hash are stored; https-only callback URL; encrypted callback secret), `callback_deliveries` (outbox, one row per status change per client) + `callback_attempts`, `audit_logs` (append-only: a trigger rejects UPDATE/DELETE) |

All money is integer paise. Migrations only add tables/columns/constraints; `alembic downgrade 0001_initial` removes exactly what 0002 added.

### Migrations
Migrations are always run explicitly (`RUN_MIGRATIONS_ON_STARTUP=false`, the recommended setting everywhere). With it off, the app refuses to start until the database is up to date.

```bash
cd backend
python -m alembic current            # revision the database is at
python -m alembic history            # all revisions
python -m alembic upgrade head --sql # preview the SQL without running it
python migrate.py                    # apply all pending migrations (takes a lock; safe to re-run)
```
Back up the database (`pg_dump -Fc`) before applying migrations in production. Downgrades (`python -m alembic downgrade <rev>`) drop the data in anything the later revision added; never run them on production without a backup and explicit approval.

If `RUN_MIGRATIONS_ON_STARTUP=true` locally, a running `uvicorn --reload` applies new migration files to your local database as soon as they appear.

## Razorpay webhook
In Razorpay Dashboard → Settings → Webhooks add `https://<your-domain>/api/webhooks/razorpay`. You choose the webhook secret yourself (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`); enter it in Razorpay and set the same value as `RAZORPAY_WEBHOOK_SECRET`. Use separate secrets for test and live. Subscribe to `qr_code.credited`, `qr_code.closed`, `payment.captured`. The admin "Razorpay Setup" page shows the exact URL and recent webhook events with errors.

**Local testing:** Razorpay cannot reach `localhost`. Expose the backend port with a tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`) and register `https://<tunnel-host>/api/webhooks/razorpay` as a Test Mode webhook.

Processing:
1. HMAC-SHA256 of the **raw body** is verified against `X-Razorpay-Signature` (constant-time compare). Invalid signatures get 400 and are logged.
2. `X-Razorpay-Event-Id` is stored with a unique constraint; already-processed events return `duplicate`.
3. The QR is identified, then reconciled against Razorpay's authoritative records (`GET /qr_codes/{id}` and `/qr_codes/{id}/payments`). Only `captured` payments with the exact amount in INR count as successful. Payment IDs are unique, so retries never double count.
4. Out-of-order events are safe: a QR closed with reason `paid` stays *pending* until the captured payment is confirmed.
5. On failure the error is saved and HTTP 500 is returned so Razorpay retries.
6. Events about a QR this app has no record of are stored as `unmatched` and logged as errors (shown on the Razorpay Setup page). Payments from other Razorpay products are `ignored`.
7. Bodies over 256 KB get 413. At most 20 bad-signature events per minute are stored; the rest are only logged.

If saving a newly created QR fails, the app immediately closes that QR at Razorpay so it cannot be paid without a record.

The frontend also polls `GET /api/collections/{id}/status?refresh=true`, which reconciles with Razorpay (throttled) if a webhook is late or missing.

**Test Mode:** Razorpay test-mode QR codes are not meant for real UPI scanning. Simulate payments from the Razorpay test dashboard.

## Customer payment page
Each collection has an unguessable `public_token`. Staff copy or open the link (`/pay/<token>`) from the collection screen and send it to the customer. No login is needed.

- `GET /api/public/pay/{token}` is the only public API. It returns customer name, amount (paise), status (`pending` / `paid` / `expired` / `cancelled`), the Razorpay QR image URL (only while payable), expiry, payment time and Razorpay payment reference. It never returns internal ids, staff, contact details, credentials or webhook data. Unknown or malformed tokens get 404. Responses are `no-store` / `noindex`; limited to 90 requests per minute per IP (per worker; add nginx `limit_req` in production).
- The page polls every 3–5 s and stops once the status is final, or 10 minutes after expiry. Each poll may re-check Razorpay, at most once per 8 s per collection. "Paid" only ever comes from Razorpay's own records (captured, exact amount, INR).

## Cancelling a QR
`POST /api/collections/{id}/cancel` (owner or admin). The app re-checks Razorpay, closes the QR at Razorpay, then reads the result back. A payment captured at any point before the close wins: the collection becomes paid and the call returns 409. If Razorpay cannot close the QR, nothing changes locally and the call returns 424, because the QR may still be payable. Cancelling twice is harmless.

## Health checks
- `GET /api/health/live`: process is up (no database access).
- `GET /api/health`: database reachable; returns 503 otherwise.

## Tests
```bash
cd backend/unit_tests && python -m pytest -q      # needs TEST_DATABASE_URL (a *_test database)
```
`backend/tests/` holds live-server regression tests; they are skipped unless `UQC_TEST_BASE_URL`, `UQC_TEST_ADMIN_EMAIL` and `UQC_TEST_ADMIN_PASSWORD` are set. Never hardcode credentials in tests.
Covers authentication (login, lockout, roles, deactivation, password reset), QR creation payload/validation/errors/scoping, and webhook processing (signature, duplicates, non-captured, amount mismatch, out-of-order, retry after failure). Razorpay is faked in tests; the app itself never generates mock QRs.

## Deployment
Never commit `.env` files, credentials or database files (`pgdata/` is ignored).

**Migrations are a deployment step.** Run `python migrate.py` once per release, before starting the new app containers. With `APP_ENV=production` the app refuses `RUN_MIGRATIONS_ON_STARTUP=true` and refuses to start if the database schema is not at the latest revision.

**Reverse proxy (nginx) and client IPs.** Login rate limiting uses the client IP, so it must not be spoofable:
- Run uvicorn with `--no-proxy-headers --no-access-log` (uvicorn's own forwarded-header handling is turned off; `TRUSTED_PROXIES` alone decides; requests are logged once, with request IDs).
- Set `TRUSTED_PROXIES` to exactly the address/subnet nginx connects from (e.g. the Docker network of the nginx container). Nothing else.
- In nginx, overwrite the header at the edge rather than appending to what the client sent:
  `proxy_set_header X-Forwarded-For $remote_addr;` and `proxy_set_header X-Request-ID $request_id;`
- Never publish the app port on a public interface. Bind it to `127.0.0.1` or keep it on the internal Docker network only; otherwise traffic could reach the app from an address inside `TRUSTED_PROXIES` without passing through nginx.
- `X-Real-IP` and `Forwarded` headers are ignored by the app.

1. Provision a hosted PostgreSQL and set `DATABASE_URL` (do not set `LOCAL_POSTGRES_BOOTSTRAP`).
2. Set all variables above as production secrets; use `rzp_live_…` keys only when ready for real money.
3. Run `python migrate.py` as a release step; the admin bootstrap runs on startup (idempotent).
4. Register the webhook URL for the production domain.
