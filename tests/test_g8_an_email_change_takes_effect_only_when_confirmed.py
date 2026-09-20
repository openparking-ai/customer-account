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

Controls: the start planted to rewrite the address immediately; the
neither-given refusal planted away.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from customer_account import findings as f
from customer_account.store.postgres import tenant
from customer_account.store.records import (
    confirm_email_change,
    find_customer_by_email,
    set_password,
    show_account,
    start_email_change,
)
from store_harness import A_PASSWORD, CREATED_AT, needs_postgres, query, seed_customer

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
