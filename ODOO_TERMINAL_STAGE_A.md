# Stage A: Odoo terminal contract and local testing

Stage A requires validation in an isolated environment before use. It does not implement any Odoo accounting code. A successful HTTP callback delivery is not evidence that an Odoo payment was posted or reconciled.

## Configuration and rollout

- ODOO_TERMINAL_CUTOVER defaults to false. False preserves the legacy cashier interface and manual creation permissions. Set true only after the Odoo client and callback receiver have been tested. With true, cashiers see Odoo requests and cannot create or cancel QR collections; admins retain manual creation, cancellation and historical access.
- ODOO_CALLBACK_WORKER_ENABLED defaults to false. Set true on at least one backend process to run delivery and pending-QR recovery. Multiple workers use PostgreSQL row leases and SKIP LOCKED. The worker runs within the backend process; monitor it and delivery failures.
- ODOO_CALLBACK_URLS is a comma-separated exact allowlist of HTTPS callback URLs. Set it in the backend environment before creating clients and keep it configured during delivery. Requests cannot select destinations. Redirects and proxy environment variables are not used for callbacks. Only allow trusted, controlled destinations and enforce network egress restrictions at deployment.

Migration 0003 adds an optional instance binding to api_clients and an odoo_payment_requests table. Historical collections remain unchanged. The old client rows lack an instance binding and cannot authenticate to the new API. Run migrations explicitly using the existing deployment process; back up first. Downgrading 0003 destroys the new request mapping and is unsafe after real requests exist.

## Administration and authentication

An authenticated administrator calls POST /api/admin/odoo-clients with JSON {name, instance, callback_url}. The URL must exactly match ODOO_CALLBACK_URLS; the client's environment is the current Razorpay mode. The response contains id, instance and api_key; the key is returned once. Transfer it securely to the corresponding Odoo instance. GET /api/admin/odoo-clients lists metadata, and POST /api/admin/odoo-clients/{id}/revoke disables the key and its deliveries. Requests remain unique per instance and reference across client rotation. Revocation also stops delivery of that client’s existing events; plan their recovery before revocation.

Odoo calls the endpoints below with X-Odoo-Key. The credential is bound to one configured instance and Razorpay environment. Use HTTPS. Odoo must authenticate its own users, validate posted invoice/company/customer/currency and amount against current residual, and prevent concurrent requests exceeding that residual. POS authenticates the client and validates the data, but cannot independently verify invoice state.

## Request API

POST /api/odoo/payment-requests accepts a JSON object with instance, request_reference, invoice_id, invoice_number, customer_id and customer_name as nonempty strings, amount_paise as an integer from 100 to 100000000, and currency exactly INR. IDs are strings. Use a stable, unique reference for each payment request, including partial payments.

The response is HTTP 202 with request id, immutable invoice/customer/amount fields, state and collection (null until ready). GET /api/odoo/payment-requests/{id} requires the same client credential. Repeating an identical request for the same instance and reference returns the existing request, including while creation is in progress. Reusing a reference with changed data returns 409. A request can remain creating after process interruption, or become ambiguous after an external or persistence failure. Neither state is automatically retried: an administrator must investigate the request ID and Razorpay notes before any new request is made. The create operation can complete upstream even if no QR ID was recorded locally. There is currently no automated resolution endpoint.

GET /api/terminal/requests returns up to 100 requests with pending and unresolved requests first, then recent completed requests. Authenticated staff may access it. Collection status and QR display use the existing staff endpoints. The existing Razorpay webhook verifies the signature and fetches Razorpay records; only matching captured payments are successful. Failed attempts do not automatically close a QR; expiry and cancellation follow the Razorpay QR state.

## Callback contract

Captured payments create an outbox entry in the same database transaction as reconciliation. The worker posts UTF-8 JSON with event_id, event (payment.captured), instance, request_reference, invoice_id, invoice_number, customer_id, amount_paise, currency, razorpay_qr_id and razorpay_payment_id. Header X-Terminal-Event-Id equals event_id. X-Terminal-Signature is lowercase hex HMAC-SHA256 over the exact transmitted body, with the binary SHA-256 digest of the UTF-8 API key as the HMAC key. The receiver must compute and compare signatures in constant time. Protect both the API key and its digest as secrets.

Delivery is at least once, including after a lost response or expired worker lease. Odoo must deduplicate transactionally by Razorpay payment ID and event ID; validate instance, original request, invoice, company, currency and amount; post through its normal accounting mechanisms; persist the Odoo payment mapping in that same transaction; and return 2xx only after commit. Define how Odoo reports its accounting payment ID in a future contract; this implementation does not record or verify an Odoo accounting acknowledgment. A delivered status means only that the receiver returned 2xx.

GET /api/admin/odoo-deliveries lists recent deliveries and errors; POST /api/admin/odoo-deliveries/{id}/retry requeues failed or abandoned deliveries. Revocation prevents delivery; do not revoke a client with outstanding events without planning recovery.

## Isolated local tests (PowerShell)

Use a disposable PostgreSQL database created solely for these tests; the unit test fixture drops and recreates all application tables for every test. Never point TEST_DATABASE_URL at production or a database containing data to keep. Use mock Razorpay and callback transports; do not configure live keys or run the live-server regression tests against production.

1. Install Python 3.12 and PostgreSQL locally, create a virtual environment and install backend/requirements-dev.txt in it. Create a fresh empty database named, for example, stage_a_disposable_test, on a local test-only PostgreSQL instance.
2. From the project root, in PowerShell:

   cd backend
   python -m venv .venv-stage-a
   .\.venv-stage-a\Scripts\Activate.ps1
   python -m pip install -r requirements-dev.txt
   $env:TEST_DATABASE_URL = 'postgresql://<local-test-user>:<local-test-password>@127.0.0.1:<test-port>/stage_a_disposable_test'
   cd unit_tests
   python -m pytest -q

The fixture supplies dummy Razorpay credentials and mocks Razorpay in payment tests. The migration tests operate on the same disposable database. Remove the disposable database after testing. For a local interactive environment, use a separate disposable database, APP_ENV=test, test-mode Razorpay settings, a test callback URL and the standard README setup; do not use production .env files. Apply migrations with python migrate.py, enable the worker, provision a client, and only then enable the cutover flag. An end-to-end Odoo test also requires implementing the above receiver and invoice-side authorization in the actual Odoo integration.

Frontend checks from frontend: npm ci, npm run build, and npx tsc --noEmit.

## Remaining release gates

Run the full test suite and migration tests, perform security review and mock failure/concurrency testing, verify callback network restrictions, and exercise integration with the real Odoo test instance. Confirm monitoring for stuck creating/ambiguous requests, unmatched webhooks, worker health and abandoned callbacks. Production deployment is manual: back up, build, run the migration release job, deploy the reviewed backend/frontend with worker and callback configuration, validate using the approved production procedure, and enable cutover only after Odoo is ready. For rollback, disable cutover and restore the previous application images only after confirming compatibility; retain the additive schema and preserve/reconcile outstanding requests and outbox events. Do not downgrade 0003 while mappings or payments need retention.
