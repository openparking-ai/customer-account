"""G6 -- an expired token and an already-used token are each refused by name,
distinctly from an unknown one and from a cancelled one.

Four refusals, four codes, and a test for each pair that could be confused:
a token nobody issued (UNKNOWN); one presented after its stated window
(EXPIRED -- derived from ``expires_at`` against the instant given, and at the
boundary instant itself); one presented twice (ALREADY_USED, the second
time, and the first spend is what stands); one superseded by a newer token
for the same customer (CANCELLED, with ``superseded`` as the reason). The
same four hold for both kinds of token, so both are driven.

**AND THE SPEND ASSERTS ONE ROW.** ``_spend`` updates ``WHERE state =
'issued'`` and refuses when no row moved -- the backstop for two callers
racing past the lock.

Controls: the expiry derivation planted to never fire; the already-used
branch planted to answer UNKNOWN.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from customer_account import findings as f
from customer_account.store.postgres import tenant
from customer_account.store.records import (
    confirm_email_change,
    consume_password_reset,
    set_password,
    start_email_change,
    start_password_reset,
)
from customer_account.tokens import EXPIRED, TokenState, is_expired, parse_state
from store_harness import (
    A_PASSWORD,
    ANOTHER_PASSWORD,
    CREATED_AT,
    needs_postgres,
    query,
    seed_customer,
)

pytestmark = needs_postgres

MINUTES = timedelta(minutes=1)


def _with_credential(app, tenant_id):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="owner", at=CREATED_AT)
    app.commit()
    return customer_id


def _change(cursor, tenant_id, customer_id, at=CREATED_AT, minutes=30):
    return start_email_change(cursor, tenant_id, customer_id, "alice.new@example.com",
                              valid_minutes=minutes, at=at, by="owner")


def _reset(cursor, tenant_id, customer_id, at=CREATED_AT, minutes=30):
    return start_password_reset(cursor, tenant_id, customer_id, valid_minutes=minutes,
                                by="owner", at=at)


def _confirm(cursor, tenant_id, token, at):
    return confirm_email_change(cursor, tenant_id, token, at=at)


def _consume(cursor, tenant_id, token, at):
    return consume_password_reset(cursor, tenant_id, token, ANOTHER_PASSWORD, at=at)


KINDS = [("email change", _change, _confirm), ("password reset", _reset, _consume)]
KIND_IDS = [k[0] for k in KINDS]


@pytest.mark.guarantee("G6")
@pytest.mark.parametrize("kind,issue,spend", KINDS, ids=KIND_IDS)
def test_an_unknown_token_is_unknown(app, tenant_id, kind, issue, spend):
    _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            spend(cursor, tenant_id, "nobody-issued-this", CREATED_AT)
    assert refused.value.code == f.REFUSAL_TOKEN_UNKNOWN


@pytest.mark.guarantee("G6")
@pytest.mark.parametrize("kind,issue,spend", KINDS, ids=KIND_IDS)
def test_a_token_past_its_window_is_expired_not_unknown_and_the_boundary_is_expired(
    app, tenant_id, kind, issue, spend
):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        token = issue(cursor, tenant_id, customer_id, minutes=30)["token"]
    app.commit()
    for at in (CREATED_AT + 30 * MINUTES, CREATED_AT + 31 * MINUTES, CREATED_AT + 999 * MINUTES):
        with tenant(app, tenant_id) as cursor:
            with pytest.raises(f.Refused) as refused:
                spend(cursor, tenant_id, token, at)
        assert refused.value.code == f.REFUSAL_TOKEN_EXPIRED, at
        app.rollback()
    # one minute inside the window it works: the control that the window is the window
    with tenant(app, tenant_id) as cursor:
        spend(cursor, tenant_id, token, CREATED_AT + 29 * MINUTES)
    app.rollback()


@pytest.mark.guarantee("G6")
@pytest.mark.parametrize("kind,issue,spend", KINDS, ids=KIND_IDS)
def test_a_token_presented_twice_is_already_used_the_second_time_and_the_first_spend_stands(
    app, tenant_id, kind, issue, spend
):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        token = issue(cursor, tenant_id, customer_id)["token"]
        first = spend(cursor, tenant_id, token, CREATED_AT + MINUTES)
    app.commit()
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            spend(cursor, tenant_id, token, CREATED_AT + 2 * MINUTES)
    assert refused.value.code == f.REFUSAL_TOKEN_ALREADY_USED
    assert (CREATED_AT + MINUTES).isoformat()[:16] in refused.value.detail or "used at" in (
        refused.value.detail
    )
    app.rollback()
    if kind == "email change":
        assert query(app, tenant_id, "SELECT email FROM customers WHERE id = %s",
                     (str(customer_id),)) == [("alice.new@example.com",)]
        assert first["to_email"] == "alice.new@example.com"


@pytest.mark.guarantee("G6")
@pytest.mark.parametrize("kind,issue,spend", KINDS, ids=KIND_IDS)
def test_a_superseded_token_is_cancelled_with_that_reason_and_the_newest_works(
    app, tenant_id, kind, issue, spend
):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        older = issue(cursor, tenant_id, customer_id)["token"]
        newer = issue(cursor, tenant_id, customer_id, at=CREATED_AT + MINUTES)
    app.commit()
    assert newer["superseded"] == 1
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            spend(cursor, tenant_id, older, CREATED_AT + 2 * MINUTES)
    assert refused.value.code == f.REFUSAL_TOKEN_CANCELLED
    assert "superseded" in refused.value.detail
    app.rollback()
    with tenant(app, tenant_id) as cursor:
        spend(cursor, tenant_id, newer["token"], CREATED_AT + 2 * MINUTES)
    app.rollback()


@pytest.mark.guarantee("G6")
def test_expiry_is_derived_and_expired_cannot_be_typed():
    assert is_expired(CREATED_AT, CREATED_AT) is True
    assert is_expired(CREATED_AT, CREATED_AT - MINUTES) is False
    with pytest.raises(f.Refused) as refused:
        parse_state(EXPIRED)
    assert refused.value.code == f.REFUSAL_EXPIRED_IS_DERIVED
    assert [s.value for s in TokenState] == ["issued", "redeemed", "cancelled"]
    with pytest.raises(f.Refused) as unknown:
        parse_state("spent")
    assert unknown.value.code == f.REFUSAL_STATE_UNKNOWN


@pytest.mark.guarantee("G6")
def test_the_migration_refuses_a_typed_expired_state(owner, app, tenant_id):
    """The schema's backstop for a raw write."""
    import psycopg

    customer_id = _with_credential(app, tenant_id)
    with owner.cursor() as cursor:
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO credential_resets (tenant_id, customer_id, token_sha256, issued_by, "
                "issued_at, expires_at, state) VALUES (%s, %s, repeat('a', 64), 'x', %s, %s, "
                "'expired')",
                (str(tenant_id), str(customer_id), CREATED_AT, CREATED_AT + MINUTES),
            )


@pytest.mark.guarantee("G6")
def test_the_spend_asserts_one_row_so_a_caller_that_skips_the_lock_still_refuses(
    app, tenant_id, monkeypatch
):
    """THE BACKSTOP, measured with the primary removed: the locked re-read
    is patched to see ``issued`` whatever the row says, and the UPDATE's
    rowcount is what refuses the second spend."""
    from customer_account.store import records

    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        token = _reset(cursor, tenant_id, customer_id)["token"]
        _consume(cursor, tenant_id, token, CREATED_AT + MINUTES)
    app.commit()
    real = records._locked_token

    def blind(cursor, table, tenant_id_, token_, at):
        cursor.execute(
            f"SELECT id, customer_id, expires_at FROM {table} WHERE tenant_id = %s "
            "AND token_sha256 = %s",
            (str(tenant_id_), records.digest(token_)),
        )
        token_id, owner_id, expires_at = cursor.fetchone()
        return records.as_uuid(token_id), records.as_uuid(owner_id), expires_at

    monkeypatch.setattr(records, "_locked_token", blind)
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            _consume(cursor, tenant_id, token, CREATED_AT + 2 * MINUTES)
    assert refused.value.code == f.REFUSAL_TOKEN_ALREADY_USED
    assert "another caller" in refused.value.detail
    monkeypatch.setattr(records, "_locked_token", real)
