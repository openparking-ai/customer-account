"""G16 -- the fold is the database's, every door gives one answer, and
migration 0001 states what it requires of the database and refuses by name
where it does not hold.

**ONE AUTHORITY ON WHETHER TWO ADDRESSES ARE ONE.** ``lower(email)`` under the
collation ``customers.email`` carries -- the unique index's own expression --
asked through ``records._address_holder`` by ``create_account``,
``start_email_change`` and ``confirm_email_change`` alike. The merge gate
measured what the alternative did: a Python ``lower()`` beside the database's
disagreed with it on 28 code points on CI's own database, and for
``İstanbul@`` / ``i̇stanbul@`` ``start_email_change`` refused "it is the
current address" while ``create_account`` wrote a second customer behind it.
The first test drives the two doors on every pair the gate used and requires
them to AGREE, whatever this database's fold is -- the test is about the
doors agreeing, not about which answer the database gives, so it holds on
glibc, on macOS libc and on ICU alike.

**THE REQUIREMENT IS MEASURED, STATED, AND REFUSED BY NAME.** The fold is a
property of how the database was created: 78 rows over every locale provider
and LC_CTYPE shape PostgreSQL 16 offers (the fix round's ``y2_property.py``)
found ONE thing predicting whether ``Élodie@`` and ``élodie@`` are one
account -- the column's effective collation, which for a column with no
COLLATE clause is ``pg_database.datlocprovider`` with ``pg_database.datctype``;
``datctype`` alone does not (ICU with ``datctype = C`` folds), and
``lc_ctype`` is not a parameter on PostgreSQL 16. So 0001's pre-flight reads
exactly those two, and the tests below prove the refusal FIRES: a C-collated
database is created in the same cluster, the property is read from it, the
behaviour the property predicts is measured on it (two spellings, two rows),
and 0001 stops at ``MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY`` with nothing
created -- beside the suite's own database, on which the property holds, the
behaviour is one row, and 0001 proceeded. One without the other proves
nothing.

Controls: the pre-flight's condition planted to ``false`` (the refusal never
fires, the C-collated apply proceeds); a Python-side fold planted back into
``start_email_change`` (the doors disagree again).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import conninfo, sql

from customer_account import findings as f
from customer_account.store.postgres import tenant
from customer_account.store.records import create_account, start_email_change
from store_harness import (
    DSN,
    MIGRATIONS,
    acceptance,
    cluster_lock,
    needs_postgres,
    new_tenant,
    seed_customer,
)

pytestmark = needs_postgres

AT = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

#: The pairs the gate drove through the module: two spellings that Python's
#: lower() calls one and some database's lower() calls two, or the reverse.
PAIRS = [
    ("İstanbul@example.com", "i̇stanbul@example.com"),  # U+0130 vs i + U+0307
    ("ΟΔΟΣ@example.com", "οδος@example.com"),  # Python's Final_Sigma rule
    ("Ύ@example.com", "ώ@example.com"),  # macOS libc folds U+038E to U+03CE
    ("Élodie@example.com", "élodie@example.com"),  # two accounts under a C locale
    ("Alice@example.com", "alice@example.com"),  # the documented ASCII case
]

#: The one pair the requirement is stated for, and the behaviour it predicts.
REQUIREMENT_PAIR = ("Élodie@example.com", "élodie@example.com")

#: The fold a libc C/POSIX ctype gives: ASCII only. Read from the catalogue in
#: the same shape the migration's pre-flight reads it.
ASCII_ONLY_CTYPES = ("C", "POSIX")
REFUSAL_NAME = "MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY"
MIGRATION = next(iter(sorted(MIGRATIONS.glob("0001_*.sql"))))


def _door_answers(app, tenant_id, first: str, second: str) -> tuple[str, str]:
    """What start_email_change says about `second` for a customer holding
    `first`, and what create_account then says about `second`."""
    customer_id = seed_customer(app, tenant_id, first)
    with tenant(app, tenant_id) as cursor:
        try:
            start_email_change(cursor, tenant_id, customer_id, second, valid_minutes=30, at=AT,
                               by="ops")
            change = "STARTED"
        except f.Refused as refused:
            change = refused.code
    app.rollback()
    with tenant(app, tenant_id) as cursor:
        try:
            create_account(cursor, tenant_id, email=second, external_id=None, name=None,
                           phone=None, at=AT, acceptance=acceptance())
            create = "CREATED"
        except f.Refused as refused:
            create = refused.code
    app.rollback()
    return change, create


@pytest.mark.guarantee("G16")
def test_start_email_change_and_create_account_agree_on_whether_two_addresses_are_one(
    app, owner
):
    """The gate's finding, as a rule: whatever THIS database's fold says, both
    doors say it. UNCHANGED at one door means TAKEN at the other; STARTED
    means CREATED. The pairs are the gate's; at least one of them must split
    the two answers on this database, or the test measured nothing."""
    answers = {}
    for first, second in PAIRS:
        tenant_id = new_tenant(owner)
        answers[(first, second)] = _door_answers(app, tenant_id, first, second)
    for pair, (change, create) in answers.items():
        assert change in (f.REFUSAL_EMAIL_UNCHANGED, "STARTED"), (pair, change)
        assert create in (f.REFUSAL_EMAIL_TAKEN, "CREATED"), (pair, create)
        one = change == f.REFUSAL_EMAIL_UNCHANGED
        assert one == (create == f.REFUSAL_EMAIL_TAKEN), (
            f"the doors contradict on {pair}: start_email_change says {change}, "
            f"create_account says {create}"
        )
    outcomes = {change for change, _ in answers.values()}
    assert outcomes == {f.REFUSAL_EMAIL_UNCHANGED, "STARTED"}, (
        "every pair gave the same answer, so nothing here measured a disagreement", answers
    )


@pytest.mark.guarantee("G16")
def test_an_unchanged_address_still_refuses_by_the_same_name_and_a_different_one_is_accepted(
    app, tenant_id
):
    """THE OVER-REACH CONTROLS on the Y1 change: the documented ASCII case is
    unchanged by name, the identical spelling is unchanged by name, and a
    different address still starts a change."""
    customer_id = seed_customer(app, tenant_id, "alice@example.com")
    with tenant(app, tenant_id) as cursor:
        for spelling in ("alice@example.com", "ALICE@example.com", "  alice@example.com "):
            with pytest.raises(f.Refused) as same:
                start_email_change(cursor, tenant_id, customer_id, spelling, valid_minutes=30,
                                   at=AT, by="ops")
            assert same.value.code == f.REFUSAL_EMAIL_UNCHANGED, spelling
            assert same.value.detail == "it is the current address."
        started = start_email_change(cursor, tenant_id, customer_id, "alice.next@example.com",
                                     valid_minutes=30, at=AT, by="ops")
        assert started["new_email"] == "alice.next@example.com"
    app.rollback()


def _default_collation(cursor) -> tuple[str, str]:
    """(provider, ctype) of the current database, read as the pre-flight reads
    them; 'c' before PostgreSQL 15, where every collation is libc."""
    cursor.execute("SELECT datctype FROM pg_database WHERE datname = current_database()")
    (ctype,) = cursor.fetchone()
    cursor.execute(
        "SELECT 1 FROM pg_attribute WHERE attrelid = 'pg_catalog.pg_database'::regclass "
        "AND attname = 'datlocprovider'"
    )
    provider = "c"
    if cursor.fetchone():
        cursor.execute("SELECT datlocprovider::text FROM pg_database "
                       "WHERE datname = current_database()")
        (provider,) = cursor.fetchone()
    return provider, ctype


def _folds_the_requirement_pair(cursor) -> bool:
    """The behaviour the property predicts, measured on this database through
    the migration's own mechanism: a unique index on lower(col)."""
    first, second = REQUIREMENT_PAIR
    cursor.execute("CREATE TEMPORARY TABLE fold_probe (email text)")
    cursor.execute("CREATE UNIQUE INDEX ON fold_probe (lower(email))")
    cursor.execute("INSERT INTO fold_probe VALUES (%s)", (first,))
    try:
        cursor.execute("INSERT INTO fold_probe VALUES (%s)", (second,))
        return False
    except psycopg.errors.UniqueViolation:
        return True
    finally:
        cursor.execute("DROP TABLE fold_probe")


@pytest.mark.guarantee("G16")
def test_the_suites_own_database_meets_the_requirement_and_0001_proceeded_on_it(owner):
    """THE POSITIVE HALF, in the same run as the refusal below: the property
    holds here, it predicts one account, and the migration applied."""
    with owner.cursor() as cursor:
        provider, ctype = _default_collation(cursor)
        assert provider in ("c", "i"), f"provider {provider!r} is one the fold was not measured on"
        assert not (provider == "c" and ctype in ASCII_ONLY_CTYPES), (provider, ctype)
        assert _folds_the_requirement_pair(cursor), (provider, ctype)
        cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        (tables,) = cursor.fetchone()
        assert tables == 8, "0001 did not proceed on the suite's own database"
        # customers.email takes the DATABASE'S collation: no clause of its own,
        # so the pre-flight's judgement is the judgement that applies to it.
        cursor.execute(
            "SELECT c.collname FROM pg_attribute a JOIN pg_collation c ON c.oid = a.attcollation "
            "WHERE a.attrelid = 'customers'::regclass AND a.attname = 'email'"
        )
        assert cursor.fetchone() == ("default",)


@pytest.mark.guarantee("G16")
def test_0001_refuses_by_name_on_a_c_collated_database_in_the_same_cluster_and_creates_nothing(
    owner,
):
    """A C-collated database beside the suite's: the property reads (libc, C),
    it predicts TWO accounts and two are measured, and 0001 stops at the
    named refusal before its first CREATE. Then the database is dropped."""
    params = conninfo.conninfo_to_dict(DSN)
    name = f"{params.get('dbname', 'customer_account_test')}_c_collated"
    with owner.cursor() as cursor:
        cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        cursor.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'")
            .format(sql.Identifier(name))
        )
    try:
        c_dsn = conninfo.make_conninfo(**{**params, "dbname": name})
        with psycopg.connect(c_dsn, autocommit=True) as c_collated, c_collated.cursor() as cursor:
            provider, ctype = _default_collation(cursor)
            assert provider == "c" and ctype in ASCII_ONLY_CTYPES, (provider, ctype)
            assert not _folds_the_requirement_pair(cursor), "the property did not predict"
            with cluster_lock(DSN):
                with pytest.raises(psycopg.errors.InvalidParameterValue) as refused:
                    cursor.execute(MIGRATION.read_text())
                cursor.execute("ROLLBACK")
            message = refused.value.diag.message_primary or ""
            assert message.startswith(f"{REFUSAL_NAME}: "), message
            assert refused.value.diag.message_detail == "locale provider libc, LC_CTYPE C."
            cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
            assert cursor.fetchone() == (0,), "the refusal fired after something was created"
            cursor.execute("SELECT count(*) FROM pg_proc WHERE proname = 'current_tenant_id'")
            assert cursor.fetchone() == (0,)
    finally:
        with owner.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


@pytest.mark.guarantee("G16")
def test_the_refusal_the_migration_raises_is_the_one_the_documents_name():
    """The name in the migration, the README and the contract is one name:
    a refusal published under a name nothing raises is an orphan."""
    raised = set(re.findall(r"MIGRATION_REFUSAL_[A-Z_]+", MIGRATION.read_text()))
    assert REFUSAL_NAME in raised
    root = MIGRATIONS.parent
    for document in (root / "README.md", root / "docs" / "CONTRACT.md"):
        published = set(re.findall(r"MIGRATION_REFUSAL_[A-Z_]+", document.read_text()))
        assert published == raised, (document.name, published ^ raised)
