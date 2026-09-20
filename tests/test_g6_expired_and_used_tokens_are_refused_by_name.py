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

**THE STATE A DOOR READS IS PARSED, NOT TRUSTED.** The unraisable round
measured that ``REFUSAL_EXPIRED_IS_DERIVED`` and ``REFUSAL_STATE_UNKNOWN``
were raised only by ``tokens.parse_state``, which no door called: the
schema's CHECK was the whole guard, and with the CHECK dropped and
``expired`` written onto a live row, ``confirm_email_change`` fell through
to the spend and refused it as "spent by another caller meanwhile" -- a false
sentence. ``_locked_token`` now parses the state it reads, so a row carrying
``expired`` is refused by its own name and a row carrying a state this
module does not have by the other, through both doors, with the row
untouched. The tests below do what the schema says nobody can -- the OWNER
drops the CHECK and writes the state -- because that is exactly the case
the module's own guard is for; the CHECK is put back before they return.

Controls: the expiry derivation planted to never fire; the already-used
branch planted to answer UNKNOWN; the parse of the read state planted away.
"""

from __future__ import annotations

import json
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


#: table -> the auto-named CHECK on ``state`` that 0001 declares inline.
STATE_CHECK = {
    "pending_email_changes": "pending_email_changes_state_check",
    "credential_resets": "credential_resets_state_check",
}
TYPED_STATES = "('issued', 'redeemed', 'cancelled')"


def _with_the_check_dropped(owner, table):
    """The owner does what the schema says nobody can, and puts it back."""
    from contextlib import contextmanager

    @contextmanager
    def dropped():
        with owner.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT {STATE_CHECK[table]}")
        try:
            yield
        finally:
            with owner.cursor() as cursor:
                cursor.execute(f"UPDATE {table} SET state = 'issued' WHERE state NOT IN "
                               f"{TYPED_STATES}")
                cursor.execute(f"ALTER TABLE {table} ADD CONSTRAINT {STATE_CHECK[table]} "
                               f"CHECK (state IN {TYPED_STATES})")
    return dropped()


@pytest.mark.guarantee("G6")
@pytest.mark.parametrize(
    "typed,code",
    [("expired", f.REFUSAL_EXPIRED_IS_DERIVED), ("spent", f.REFUSAL_STATE_UNKNOWN)],
    ids=["a typed expired", "a state the module does not have"],
)
@pytest.mark.parametrize("kind,issue,spend", KINDS, ids=KIND_IDS)
def test_a_row_carrying_a_state_the_module_does_not_have_is_refused_by_name_not_spent(
    owner, app, tenant_id, typed, code, kind, issue, spend
):
    """Both doors, both foreign states: refused by the state's own name, the
    row untouched -- not read as live (no spend, no redeemed_at) and not read
    as spent (not ALREADY_USED, the false sentence measured before)."""
    table = "pending_email_changes" if kind == "email change" else "credential_resets"
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        token = issue(cursor, tenant_id, customer_id)["token"]
    app.commit()
    with _with_the_check_dropped(owner, table):
        with owner.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET state = %s WHERE customer_id = %s",
                           (typed, str(customer_id)))
            assert cursor.rowcount == 1
        with tenant(app, tenant_id) as cursor:
            with pytest.raises(f.Refused) as refused:
                spend(cursor, tenant_id, token, CREATED_AT + MINUTES)
        app.rollback()
        assert refused.value.code == code
        assert refused.value.field == "state"
        assert query(app, tenant_id, f"SELECT state, redeemed_at FROM {table} "
                     "WHERE customer_id = %s", (str(customer_id),)) == [(typed, None)]
    # THE OVER-REACH CONTROL: the same row put back to issued is spent as before
    with tenant(app, tenant_id) as cursor:
        spend(cursor, tenant_id, token, CREATED_AT + MINUTES)
    app.commit()
    assert query(app, tenant_id, f"SELECT state FROM {table} WHERE customer_id = %s",
                 (str(customer_id),)) == [("redeemed",)]


@pytest.mark.guarantee("G6")
def test_the_command_line_refuses_a_typed_expired_state_exit_3(
    owner, app, tenant_id, capsys, monkeypatch
):
    """The door as the operator meets it: exit 3, the JSON, the code."""
    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        token = _reset(cursor, tenant_id, customer_id)["token"]
    app.commit()
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", ANOTHER_PASSWORD)
    with _with_the_check_dropped(owner, "credential_resets"):
        with owner.cursor() as cursor:
            cursor.execute("UPDATE credential_resets SET state = 'expired' WHERE customer_id = %s",
                           (str(customer_id),))
        status = main(["consume-password-reset", "--tenant", str(tenant_id), "--token", token,
                       "--at", "2026-01-01T12:01:00+00:00"])
        out = capsys.readouterr()
        assert status == 3 and out.err == "", out
        printed = json.loads(out.out)
        assert printed["refused"] == f.REFUSAL_EXPIRED_IS_DERIVED
        assert printed["field"] == "state"
        assert token not in out.out, "the token is never rendered by a refusal"


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
