"""G8 -- an email change does not take effect until confirmed at the new
address; the old address keeps working until it does; who authorised it is
stored, and travels onto the history row.

**THE TWO RECOVERY PATHS MAY NOT BE CIRCULAR.** A reset is delivered to the
current address (G9); so a change to that address is never a single write:
it is started (authorised, a token minted for the NEW address), and it takes
effect only when the new address presents the token back. Between the two the
customer is found by the OLD address and not by the new one, on the store and
on the command line.

**AUTHORISATION IS EXACTLY ONE OF TWO, AND IT IS STORED.** The customer's
current password, verified by this module (``authorisation = 'password'``,
``authorised_by`` the customer's id), or an explicit caller authorisation
(``'caller'``, the name given). Neither given: refused by name. Both given:
refused by name -- exactly one is stored, so exactly one may be true. The
pair is carried from the pending row onto the history row when the change
takes effect, because "who authorised this change" is the question asked
after a disputed account takeover.

**THE HISTORY IS READ IN ONE STATED ORDER, AND A FULL TIE IS ORDERED BY id.**
The same tie the gate measured on acceptances: ``changed_at`` is the instant
the caller stated and ``created_at`` is ``now()``, the transaction's instant,
so two changes confirmed in one transaction at one stated instant tie on both.
Measured before this was built: 8 of 8 tied on both clocks and the read came
back in heap order, stated nowhere. ``records.EMAIL_CHANGE_ORDER`` is the one
place the order is written, and it ends in ``records.TIEBREAK`` -- the SAME
tuple ``ACCEPTANCE_ORDER`` ends in, written once -- so a full tie reads the
same way on every read, arbitrarily, and the contract says so. The tie test
below confirms eight changes in one transaction so the chance that insertion
order happens to equal id order is 1 in 40,320.

Controls: the start planted to rewrite the address immediately; the
neither-given refusal planted away; the tiebreak column planted away.
"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID

import pytest

from customer_account import findings as f
from customer_account.store.postgres import tenant
from customer_account.store.records import (
    ACCEPTANCE_ORDER,
    EMAIL_CHANGE_ORDER,
    TIEBREAK,
    confirm_email_change,
    find_customer_by_email,
    set_password,
    show_account,
    start_email_change,
)
from store_harness import A_PASSWORD, CREATED_AT, LATER, needs_postgres, query, seed_customer

pytestmark = needs_postgres

MINUTE = timedelta(minutes=1)
OLD, NEW = "alice@example.com", "alice.new@example.com"


def _with_credential(app, tenant_id):
    customer_id = seed_customer(app, tenant_id, OLD)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="owner", at=CREATED_AT)
    app.commit()
    return customer_id


@pytest.mark.guarantee("G8")
def test_the_old_address_works_until_the_new_one_confirms_and_then_the_new_one_does(
    app, tenant_id
):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        started = start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                                     at=CREATED_AT, password=A_PASSWORD)
    app.commit()
    # started, not changed: found by the old address, not by the new one
    assert query(app, tenant_id, "SELECT email FROM customers WHERE id = %s",
                 (str(customer_id),)) == [(OLD,)]
    with tenant(app, tenant_id) as cursor:
        assert find_customer_by_email(cursor, tenant_id, OLD).id == customer_id
        with pytest.raises(f.Refused) as refused:
            find_customer_by_email(cursor, tenant_id, NEW)
        assert refused.value.code == f.REFUSAL_CUSTOMER_NOT_FOUND
        shown = show_account(cursor, tenant_id, customer_id)
    app.rollback()
    assert shown["email"] == OLD
    assert [p["new_email"] for p in shown["pending_email_changes"]] == [NEW]
    assert shown["email_changes"] == []
    # confirmed: the new address, the history row, the pending row spent
    with tenant(app, tenant_id) as cursor:
        done = confirm_email_change(cursor, tenant_id, started["token"], at=CREATED_AT + MINUTE)
    app.commit()
    assert (done["from_email"], done["to_email"]) == (OLD, NEW)
    with tenant(app, tenant_id) as cursor:
        assert find_customer_by_email(cursor, tenant_id, NEW).id == customer_id
        assert find_customer_by_email(cursor, tenant_id, "ALICE.NEW@example.com").id == customer_id
        with pytest.raises(f.Refused):
            find_customer_by_email(cursor, tenant_id, OLD)
        shown = show_account(cursor, tenant_id, customer_id)
    app.rollback()
    assert shown["email"] == NEW and shown["pending_email_changes"] == []
    assert [(h["from_email"], h["to_email"]) for h in shown["email_changes"]] == [(OLD, NEW)]


@pytest.mark.guarantee("G8")
def test_the_password_route_is_stored_as_such_and_travels_onto_the_history_row(app, tenant_id):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        started = start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                                     at=CREATED_AT, password=A_PASSWORD)
        assert (started["authorisation"], started["authorised_by"]) == (
            "password", str(customer_id))
        done = confirm_email_change(cursor, tenant_id, started["token"], at=CREATED_AT + MINUTE)
    app.commit()
    assert (done["authorisation"], done["authorised_by"]) == ("password", str(customer_id))
    assert query(app, tenant_id, "SELECT authorisation, authorised_by FROM "
                 "customer_email_changes WHERE customer_id = %s", (str(customer_id),)) == [
        ("password", str(customer_id))]


@pytest.mark.guarantee("G8")
def test_the_caller_route_is_stored_as_such_with_the_name_given(app, tenant_id):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        started = start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                                     at=CREATED_AT, by="front desk: J.")
        done = confirm_email_change(cursor, tenant_id, started["token"], at=CREATED_AT + MINUTE)
    app.commit()
    assert (started["authorisation"], started["authorised_by"]) == ("caller", "front desk: J.")
    assert (done["authorisation"], done["authorised_by"]) == ("caller", "front desk: J.")


@pytest.mark.guarantee("G8")
def test_neither_authorisation_is_refused_by_name_and_so_is_both(app, tenant_id):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as neither:
            start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                               at=CREATED_AT)
        assert neither.value.code == f.REFUSAL_AUTHORISATION_MISSING
        with pytest.raises(f.Refused) as both:
            start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                               at=CREATED_AT, password=A_PASSWORD, by="front desk")
        assert both.value.code == f.REFUSAL_AUTHORISATION_AMBIGUOUS
        with pytest.raises(f.Refused) as wrong:
            start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                               at=CREATED_AT, password="not the password")
        assert wrong.value.code == f.REFUSAL_PASSWORD_WRONG
    app.rollback()
    assert query(app, tenant_id, "SELECT count(*) FROM pending_email_changes") == [(0,)]


@pytest.mark.guarantee("G8")
def test_the_same_address_and_a_taken_address_are_refused_by_name_at_start_and_a_race_at_confirm(
    app, tenant_id
):
    customer_id = _with_credential(app, tenant_id)
    seed_customer(app, tenant_id, "bob@example.com")
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as same:
            start_email_change(cursor, tenant_id, customer_id, "ALICE@example.com",
                               valid_minutes=30, at=CREATED_AT, by="x")
        assert same.value.code == f.REFUSAL_EMAIL_UNCHANGED
        with pytest.raises(f.Refused) as taken:
            start_email_change(cursor, tenant_id, customer_id, "Bob@example.com",
                               valid_minutes=30, at=CREATED_AT, by="x")
        assert taken.value.code == f.REFUSAL_EMAIL_TAKEN
    app.rollback()
    # the race: the address was free at start and taken before confirm
    with tenant(app, tenant_id) as cursor:
        started = start_email_change(cursor, tenant_id, customer_id, "carol@example.com",
                                     valid_minutes=30, at=CREATED_AT, by="x")
    app.commit()
    seed_customer(app, tenant_id, "carol@example.com")
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as raced:
            confirm_email_change(cursor, tenant_id, started["token"], at=CREATED_AT + MINUTE)
    assert raced.value.code == f.REFUSAL_EMAIL_TAKEN
    app.rollback()
    assert query(app, tenant_id, "SELECT email FROM customers WHERE id = %s",
                 (str(customer_id),)) == [(OLD,)]


@pytest.mark.guarantee("G8")
def test_the_command_line_finds_by_the_old_address_until_confirmed(
    app, tenant_id, capsys, monkeypatch
):
    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    customer_id = _with_credential(app, tenant_id)
    T = ["--tenant", str(tenant_id)]
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", A_PASSWORD)
    assert main(["start-email-change", *T, "--customer", str(customer_id), "--new-email", NEW,
                 "--valid-minutes", "30", "--at", "2026-06-01T09:00:00-06:00"]) == 0
    token = json.loads(capsys.readouterr().out)["token"]
    assert main(["show-account", *T, "--email", OLD]) == 0
    assert json.loads(capsys.readouterr().out)["email"] == OLD
    assert main(["show-account", *T, "--email", NEW]) == 3
    assert json.loads(capsys.readouterr().out)["refused"] == f.REFUSAL_CUSTOMER_NOT_FOUND
    assert main(["confirm-email-change", *T, "--token", token,
                 "--at", "2026-06-01T09:01:00-06:00"]) == 0
    capsys.readouterr()
    assert main(["show-account", *T, "--email", NEW]) == 0
    assert json.loads(capsys.readouterr().out)["email"] == NEW


def _confirmed_changes(cursor, tenant_id, customer_id, count: int, *, at) -> list[UUID]:
    """``count`` changes started and confirmed, each to a fresh address, all at
    ``at``; returns the history row ids in the order they were written."""
    written = []
    for n in range(count):
        started = start_email_change(cursor, tenant_id, customer_id, f"alice{n}@example.com",
                                     valid_minutes=30, at=at, by=f"front desk {n}")
        done = confirm_email_change(cursor, tenant_id, started["token"], at=at)
        written.append(UUID(done["email_change"]))
    return written


@pytest.mark.guarantee("G8")
def test_changes_sharing_an_instant_tie_on_both_clocks_and_are_read_in_id_order(app, tenant_id):
    """Eight changes in ONE transaction, all at LATER: changed_at ties by
    construction and created_at ties because now() is the transaction's
    instant -- both measured here, not assumed -- and the read comes back in
    id order, the stated tiebreak."""
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        written = _confirmed_changes(cursor, tenant_id, customer_id, 8, at=LATER)
        shown = show_account(cursor, tenant_id, customer_id)["email_changes"]
    app.commit()
    assert len(shown) == 8 and {row["changed_at"] for row in shown} == {LATER}
    clocks = query(app, tenant_id, "SELECT count(DISTINCT created_at) FROM customer_email_changes "
                   "WHERE customer_id = %s", (str(customer_id),))
    assert clocks == [(1,)], "created_at did not tie, so this measured nothing about the tie"
    id_of = dict(query(app, tenant_id, "SELECT to_email, id FROM customer_email_changes "
                       "WHERE customer_id = %s", (str(customer_id),)))
    read = [UUID(str(id_of[row["to_email"]])) for row in shown]
    assert sorted(read) == sorted(written), "the read is the eight rows written"
    assert read == sorted(read), "a full tie is read in id order"
    assert EMAIL_CHANGE_ORDER == ("changed_at", "created_at", "id")
    assert EMAIL_CHANGE_ORDER[-len(TIEBREAK):] == TIEBREAK == ACCEPTANCE_ORDER[-len(TIEBREAK):], (
        "both histories end in the ONE tiebreak")


@pytest.mark.guarantee("G8")
def test_the_tiebreak_changes_nothing_for_changes_that_do_not_tie(app, tenant_id):
    """THE OVER-REACH CONTROL: on a pair with distinct changed_at the old
    ordering (changed_at, created_at) and the stated one read identically --
    the address in effect is still the latest changed_at."""
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        _confirmed_changes(cursor, tenant_id, customer_id, 1, at=CREATED_AT)
    app.commit()
    with tenant(app, tenant_id) as cursor:
        started = start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                                     at=LATER, by="front desk, later")
        confirm_email_change(cursor, tenant_id, started["token"], at=LATER)
    app.commit()
    select = "SELECT id FROM customer_email_changes WHERE customer_id = %s ORDER BY "
    old = query(app, tenant_id, select + "changed_at, created_at", (str(customer_id),))
    stated = query(app, tenant_id, select + ", ".join(EMAIL_CHANGE_ORDER), (str(customer_id),))
    assert old == stated and len(stated) == 2
    with tenant(app, tenant_id) as cursor:
        shown = show_account(cursor, tenant_id, customer_id)
    app.rollback()
    id_of = dict(query(app, tenant_id, "SELECT to_email, id FROM customer_email_changes "
                       "WHERE customer_id = %s", (str(customer_id),)))
    assert [str(row[0]) for row in stated] == [str(id_of[h["to_email"]])
                                              for h in shown["email_changes"]]
    assert shown["email_changes"][-1]["changed_at"] == LATER, "the row in effect is the latest"
    assert shown["email"] == NEW == shown["email_changes"][-1]["to_email"]
