"""A migrated database, an application connection, and the rows seeded --
shared by every store-backed test.

Not a test module (no ``test_`` prefix, so the guarantee guard does not ask it
for a mark) and not a conftest: it is imported by name, so a reader of any test
can see where the database came from. Migrations are applied as the OWNER from
``migrations/``, sorted, so the schema under test is the schema that ships; the
application connects as the NOSUPERUSER NOBYPASSRLS role.

**ONE DATABASE, ONE TENANT PER TEST, FRESH ROWS PER TEST.** The tenant policy
stops a test reading anything but its own rows, and G7 proves that.

**ONE MIGRATION AT A TIME IN THE CLUSTER.** The migration ``CREATE``s or
``ALTER``s the application ROLE, and a role is cluster-global: two databases
migrating at once in one cluster collide on it (``tuple concurrently
updated``). So ``migrate`` runs under a cluster-wide advisory lock, taken on
ONE shared database of the cluster (``postgres``, else ``template1``) through a
second connection held for the length of the migration -- an advisory lock is
per database, measured on the sibling module this harness is copied from.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from customer_account.consent import Acceptance, Channel, ChannelShown
from customer_account.store.postgres import connect, set_tenant, tenant
from customer_account.store.records import as_uuid, create_account

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
DSN = os.environ.get("CUSTOMER_ACCOUNT_TEST_DSN")
APP_PASSWORD = "test-only-password"

#: One key, one meaning: "a migration of this module is running in this cluster".
MIGRATION_LOCK_KEY = 0x63757374616363  # 'custacc', as a bigint

CREATED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LATER = CREATED_AT + timedelta(hours=1)
#: A password that clears the minimum; used by every test that sets one.
A_PASSWORD = "correct horse battery"
ANOTHER_PASSWORD = "a different passphrase"

TERMS_V1 = "Version 1 of the terms. You agree to be contacted about your parking."
EMAIL_SHOWN = "We will email you receipts and notices about your parking."
SMS_SHOWN = "We will text you when your vehicle is ready. Reply STOP to opt out."


def acceptance(version: str = "v1", at: datetime = CREATED_AT, by: str = "self-registration",
               channels: tuple[ChannelShown, ...] | None = None) -> Acceptance:
    if channels is None:
        channels = (ChannelShown(Channel.EMAIL, EMAIL_SHOWN), ChannelShown(Channel.SMS, SMS_SHOWN))
    return Acceptance(terms_version=version, terms_shown=TERMS_V1, accepted_by=by,
                      accepted_at=at, channels=channels)


@contextmanager
def cluster_lock(dsn: str):
    import psycopg
    from psycopg import conninfo

    params = conninfo.conninfo_to_dict(dsn)
    holder = None
    for shared in ("postgres", "template1"):
        try:
            holder = connect(conninfo.make_conninfo(**{**params, "dbname": shared}))
            break
        except psycopg.OperationalError:
            continue
    if holder is None:
        print(
            "store_harness.cluster_lock: no shared database accepted the connection; the "
            "migration lock is taken on the target database and serialises that database "
            "only.",
            file=sys.stderr,
        )
        holder = connect(dsn)
    holder.autocommit = True
    with holder.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            yield
        finally:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
    holder.close()


def migrate(dsn: str) -> Any:
    """Drop and rebuild the schema from ``migrations/`` as the owner -- one
    migration at a time in the cluster."""
    owner = connect(dsn)
    owner.autocommit = True
    with cluster_lock(dsn), owner.cursor() as cursor:
        cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
        for path in sorted(MIGRATIONS.glob("*.sql")):
            try:
                cursor.execute(path.read_text())
            except Exception:
                # A migration file opens its own BEGIN and never reaches its COMMIT
                # when it raises, so the connection is left inside an aborted
                # transaction. End it here, so the failure is the migration's
                # message and not "current transaction is aborted".
                cursor.execute("ROLLBACK")
                raise
        cursor.execute(f"ALTER ROLE customer_account_app LOGIN PASSWORD '{APP_PASSWORD}'")
    return owner


def app_connection(dsn: str) -> Any:
    connection = connect(f"{dsn} user=customer_account_app password={APP_PASSWORD}")
    connection.autocommit = False
    return connection


def new_tenant(owner: Any, slug: str | None = None) -> UUID:
    slug = slug or f"t-{uuid4().hex[:8]}"
    with owner.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (slug, name) VALUES (%s, %s) RETURNING id", (slug, slug)
        )
        (tenant_id,) = cursor.fetchone()
    return as_uuid(tenant_id)


def seed_customer(app: Any, tenant_id: UUID, email: str = "alice@example.com",
                  external_id: str | None = None, **fields: Any) -> UUID:
    """A customer with its first acceptance, committed. Returns the uuid."""
    with tenant(app, tenant_id) as cursor:
        created = create_account(
            cursor, tenant_id, email=email, external_id=external_id,
            name=fields.get("name"), phone=fields.get("phone"), at=CREATED_AT,
            acceptance=acceptance(),
        )
    app.commit()
    return as_uuid(created["customer"])


def query(app: Any, tenant_id: Any, statement: str, parameters: tuple = ()) -> list[tuple]:
    """A read inside the tenant's context, rolled back afterwards."""
    with app.cursor() as cursor:
        set_tenant(cursor, tenant_id)
        cursor.execute(statement, parameters)
        rows = cursor.fetchall()
    app.rollback()
    return rows


#: The marks every store-backed test module carries. The fixtures that hand a
#: test its database live in conftest.py, so no module has to import them.
needs_postgres = [
    pytest.mark.needs_postgres,
    pytest.mark.skipif(not DSN, reason="CUSTOMER_ACCOUNT_TEST_DSN is not set"),
]


def store_test(function):
    """The same marks, for one test in a module that also runs without a database."""
    for mark in needs_postgres:
        function = mark(function)
    return function


def seed_full_graph(app: Any, tenant_id: UUID) -> UUID:
    """A row in EVERY table, as one tenant, through the module: a customer
    with its acceptance and channels, a credential, a pending email change,
    a confirmed one (and so a history row), a password reset. The isolation
    test's denominator. Returns the customer's uuid."""
    from customer_account.store.records import (
        confirm_email_change,
        set_password,
        start_email_change,
        start_password_reset,
    )

    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="seed", at=CREATED_AT)
        started = start_email_change(cursor, tenant_id, customer_id, "alice.new@example.com",
                                     valid_minutes=120, at=CREATED_AT, by="seed")
        confirm_email_change(cursor, tenant_id, started["token"], at=LATER)
        start_email_change(cursor, tenant_id, customer_id, "alice.next@example.com",
                           valid_minutes=60, at=LATER, by="seed")
        start_password_reset(cursor, tenant_id, customer_id, valid_minutes=60, by="seed",
                             at=LATER)
    app.commit()
    return customer_id
