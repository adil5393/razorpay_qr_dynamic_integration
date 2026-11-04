"""Migration 0002: fresh install, upgrade from 0001 with existing data, schema/ORM agreement,
constraints, append-only audit log, and downgrade/re-upgrade. Runs against the *_test database."""
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from db import Base, engine
from migrate import _config

HEAD = "0002_integration_foundation"
OLD_TABLES = ["users", "qr_collections", "payments", "webhook_events", "login_attempts"]
NEW_TABLES = ["api_clients", "callback_deliveries", "callback_attempts", "audit_logs"]
T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def _wipe():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def empty_db():
    _wipe()
    yield
    _wipe()
    Base.metadata.create_all(engine)  # leave the schema the other tests expect


def _upgrade(rev="head"):
    command.upgrade(_config(), rev)


def _version():
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _seed_0001(conn):
    """Realistic pre-0002 data: an admin, a cashier, paid/pending/expired collections, payments, events."""
    conn.execute(text("""
        INSERT INTO users (id, email, name, password_hash, role, is_active, token_version, created_by_id, created_at, last_login_at)
        VALUES (1, 'admin@shop.test', 'Admin', '$2b$12$hash1', 'admin', true, 3, NULL, :t0, :t1),
               (2, 'cashier@shop.test', 'Cashier', '$2b$12$hash2', 'cashier', false, 1, 1, :t0, NULL)
    """), {"t0": T0, "t1": T0 + timedelta(hours=1)})
    rows = [
        (1, "UQC-261101-AAAAAA", "qr_OLD0001", 10000, "INV-1", "Ravi", "paid", 10000, T0 + timedelta(minutes=5)),
        (2, "UQC-261101-BBBBBB", "qr_OLD0002", 25050, None, None, "pending", 0, None),
        (3, "UQC-261101-CCCCCC", "qr_OLD0003", 99999999, "INV-3", "Asha", "expired", 0, None),
    ]
    for cid, code, qr, amt, ref, cust, status, recv, synced in rows:
        conn.execute(text("""
            INSERT INTO qr_collections (id, code, razorpay_qr_id, amount_paise, currency, reference, customer_name,
                description, image_url, qr_status, close_reason, close_by, closed_at, payment_status, paid_at,
                amount_received_paise, created_by_id, created_at, last_synced_at, last_sync_error)
            VALUES (:id, :code, :qr, :amt, 'INR', :ref, :cust, 'Counter', :img, 'closed',
                    NULL, :t0, NULL, :status, NULL, :recv, 2, :t0, :synced, NULL)
        """), {"id": cid, "code": code, "qr": qr, "amt": amt, "ref": ref, "cust": cust, "status": status,
               "recv": recv, "t0": T0, "synced": synced, "img": f"https://rzp.io/i/{qr}"})
    conn.execute(text("""
        INSERT INTO payments (id, razorpay_payment_id, collection_id, amount_paise, currency, status, method, vpa,
            email, contact, is_successful, error_description, rzp_created_at, first_seen_at, updated_at)
        VALUES (1, 'pay_OLD1', 1, 10000, 'INR', 'captured', 'upi', 'ravi@upi', NULL, NULL, true, NULL, :t0, :t0, :t0),
               (2, 'pay_OLD2', 2, 5000, 'INR', 'captured', 'upi', NULL, NULL, NULL, false, 'Amount mismatch', :t0, :t0, :t0)
    """), {"t0": T0})
    conn.execute(text("""
        INSERT INTO webhook_events (id, event_id, event_type, signature_valid, status, error, razorpay_qr_id,
            razorpay_payment_id, collection_id, attempts, payload, received_at, processed_at)
        VALUES (1, 'evt_OLD1', 'qr_code.credited', true, 'processed', NULL, 'qr_OLD0001', 'pay_OLD1', 1, 2,
                '{"event": "qr_code.credited"}', :t0, :t0),
               (2, NULL, NULL, false, 'rejected', 'Invalid signature', NULL, NULL, NULL, 1, NULL, :t0, NULL)
    """), {"t0": T0})
    conn.execute(text("INSERT INTO login_attempts VALUES ('1.2.3.4:x@y.z', 3, NULL, :t0)"), {"t0": T0})
    for table in ("users", "qr_collections", "payments", "webhook_events"):
        conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))"))


def _snapshot(conn):
    """Every row of every 0001 table, limited to the 0001 columns."""
    snap = {}
    for table in OLD_TABLES:
        cols = [c["name"] for c in inspect(conn).get_columns(table)]
        key = "identifier" if table == "login_attempts" else "id"
        snap[table] = {"cols": cols, "rows": [
            dict(r._mapping) for r in conn.execute(text(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {key}"))]}
    return snap


# ---------- Fresh database ----------

def test_fresh_database_migrates_to_head(empty_db):
    _upgrade()
    assert _version() == HEAD
    tables = set(inspect(engine).get_table_names())
    assert set(OLD_TABLES + NEW_TABLES + ["alembic_version"]) <= tables


def test_migrated_schema_matches_orm_models(empty_db):
    """Alembic autogenerate finds nothing to change: the migration and models.py agree exactly."""
    _upgrade()
    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diffs == []


# ---------- Upgrade from 0001 with existing data ----------

def test_upgrade_from_0001_preserves_existing_records(empty_db):
    _upgrade("0001_initial")
    with engine.begin() as conn:
        _seed_0001(conn)
    with engine.connect() as conn:
        before = _snapshot(conn)

    _upgrade()
    assert _version() == HEAD

    with engine.connect() as conn:
        for table, data in before.items():
            key = "identifier" if table == "login_attempts" else "id"
            after = [dict(r._mapping) for r in conn.execute(
                text(f"SELECT {', '.join(data['cols'])} FROM {table} ORDER BY {key}"))]
            assert after == data["rows"], f"{table} changed"
        new = conn.execute(text(
            "SELECT id, public_token, source, api_client_id, idempotency_key, updated_at, created_at, last_synced_at "
            "FROM qr_collections ORDER BY id")).all()
    assert len(new) == 3
    tokens = [r.public_token for r in new]
    assert all(t and len(t) == 43 for t in tokens) and len(set(tokens)) == 3
    assert all(r.source == "dashboard" and r.api_client_id is None and r.idempotency_key is None for r in new)
    assert [r.updated_at for r in new] == [r.last_synced_at or r.created_at for r in new]


def test_upgrade_is_idempotent_when_already_at_head(empty_db):
    _upgrade()
    _upgrade()
    assert _version() == HEAD


def test_downgrade_then_upgrade_keeps_0001_data(empty_db):
    _upgrade("0001_initial")
    with engine.begin() as conn:
        _seed_0001(conn)
    with engine.connect() as conn:
        before = _snapshot(conn)
    _upgrade()
    command.downgrade(_config(), "0001_initial")
    assert _version() == "0001_initial"
    assert not set(NEW_TABLES) & set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        assert _snapshot(conn) == before
    _upgrade()
    assert _version() == HEAD


# ---------- Constraints on the migrated schema ----------

@pytest.fixture
def migrated(empty_db):
    _upgrade("0001_initial")
    with engine.begin() as conn:
        _seed_0001(conn)
    _upgrade()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO api_clients (id, name, key_prefix, key_hash, environment, callback_url)
            VALUES (1, 'Client A', 'uqc_test_aaaa', 'hash-a', 'test', 'https://a.example/cb'),
                   (2, 'Client B', 'uqc_test_bbbb', 'hash-b', 'test', NULL)
        """))
    yield


def _insert_collection(conn, n, **cols):
    base = {"code": f"UQC-N-{n}", "razorpay_qr_id": f"qr_NEW{n}", "amount_paise": 100, "currency": "INR",
            "description": "x", "image_url": "https://rzp.io/i/x", "qr_status": "active", "payment_status": "pending",
            "amount_received_paise": 0, "created_by_id": 1, "created_at": T0, "public_token": f"tok{n}"}
    base.update(cols)
    names = ", ".join(base)
    params = ", ".join(f":{k}" for k in base)
    conn.execute(text(f"INSERT INTO qr_collections ({names}) VALUES ({params})"), base)


def _violates(fn, exc=IntegrityError):
    with pytest.raises(exc):
        with engine.begin() as conn:
            fn(conn)


def test_idempotency_key_unique_per_client(migrated):
    with engine.begin() as conn:
        _insert_collection(conn, 1, source="api", api_client_id=1, idempotency_key="order-42")
        _insert_collection(conn, 2, source="api", api_client_id=2, idempotency_key="order-42")  # other client: ok
        _insert_collection(conn, 3)  # dashboard rows have no key; many allowed
        _insert_collection(conn, 4)
    _violates(lambda c: _insert_collection(c, 5, source="api", api_client_id=1, idempotency_key="order-42"))


@pytest.mark.parametrize("cols", [
    {"source": "api"},                                   # api without a client
    {"source": "dashboard", "api_client_id": 1},         # dashboard with a client
    {"source": "odoo"},                                  # unknown source
    {"idempotency_key": "k"},                            # key without a client
    {"amount_paise": 0},                                 # non-positive amount
    {"amount_received_paise": -1},
    {"public_token": "tok_dup", "code": "dup-a"},        # (first insert below makes this a duplicate)
    {"api_client_id": 999, "source": "api"},             # unknown client (foreign key)
])
def test_collection_constraints(migrated, cols):
    if cols.get("public_token") == "tok_dup":
        with engine.begin() as conn:
            _insert_collection(conn, 90, public_token="tok_dup")
    _violates(lambda c: _insert_collection(c, 91, **cols))


@pytest.mark.parametrize("sql", [
    "INSERT INTO api_clients (name, key_prefix, key_hash, environment) VALUES ('x', 'uqc_test_aaaa', 'h', 'test')",
    "INSERT INTO api_clients (name, key_prefix, key_hash, environment) VALUES ('x', 'p', 'hash-a', 'test')",
    "INSERT INTO api_clients (name, key_prefix, key_hash, environment) VALUES ('x', 'p', 'h', 'staging')",
    "INSERT INTO api_clients (name, key_prefix, key_hash, environment, callback_url) VALUES ('x', 'p', 'h', 'test', 'http://a.example')",
    "INSERT INTO api_clients (name, key_prefix, key_hash, environment, revoked_at) VALUES ('x', 'p', 'h', 'test', now())",
    "INSERT INTO payments (razorpay_payment_id, collection_id, amount_paise, currency, status, is_successful, first_seen_at, updated_at) VALUES ('pay_neg', 1, -5, 'INR', 'captured', false, now(), now())",
])
def test_other_constraints(migrated, sql):
    _violates(lambda c: c.execute(text(sql)))


def test_callback_outbox_constraints_and_cascade(migrated):
    insert = ("INSERT INTO callback_deliveries (event_id, api_client_id, collection_id, event_type, payload, target_url) "
              "VALUES (:e, 1, 1, :t, '{}', :u)")
    with engine.begin() as conn:
        conn.execute(text(insert), {"e": "cbe_1", "t": "payment.succeeded", "u": "https://a.example/cb"})
        row = conn.execute(text("SELECT id, status, attempts, max_attempts, next_attempt_at, created_at "
                                "FROM callback_deliveries")).one()
        assert row.status == "pending" and row.attempts == 0 and row.max_attempts == 12
        assert row.next_attempt_at is not None and row.created_at is not None
        conn.execute(text("INSERT INTO callback_attempts (delivery_id, attempt_no, response_status) VALUES (:d, 1, 500)"),
                     {"d": row.id})
    # same status change queued twice for the same client
    _violates(lambda c: c.execute(text(insert), {"e": "cbe_2", "t": "payment.succeeded", "u": "https://a.example/cb"}))
    # same event id
    _violates(lambda c: c.execute(text(insert), {"e": "cbe_1", "t": "payment.expired", "u": "https://a.example/cb"}))
    # non-https target, unknown status
    _violates(lambda c: c.execute(text(insert), {"e": "cbe_3", "t": "payment.expired", "u": "http://a.example/cb"}))
    _violates(lambda c: c.execute(text("UPDATE callback_deliveries SET status = 'sent'")))
    # duplicate attempt number
    _violates(lambda c: c.execute(text("INSERT INTO callback_attempts (delivery_id, attempt_no) VALUES (:d, 1)"),
                                  {"d": row.id}))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM callback_deliveries"))
        assert conn.execute(text("SELECT count(*) FROM callback_attempts")).scalar() == 0


def test_audit_log_is_append_only(migrated):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO audit_logs (actor_type, actor_user_id, action, entity_type, entity_id, details) "
                          "VALUES ('user', 1, 'collection.create', 'qr_collection', '1', '{\"amount_paise\": 100}')"))
        assert conn.execute(text("SELECT occurred_at IS NOT NULL FROM audit_logs")).scalar()
    _violates(lambda c: c.execute(text("UPDATE audit_logs SET action = 'tampered'")), DBAPIError)
    _violates(lambda c: c.execute(text("DELETE FROM audit_logs")), DBAPIError)
    _violates(lambda c: c.execute(text("INSERT INTO audit_logs (actor_type, action) VALUES ('hacker', 'x')")))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT action FROM audit_logs")).scalar() == "collection.create"
