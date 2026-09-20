"""G5 -- a customer with no credential row is answered by name, never by a
crash, never by a silent false, and never as "no password required".

The credential row exists only where the caller set one; this module has no
view of whether anybody is charged and never infers one. So its ABSENCE is a
legitimate state with a NAME, on every door that meets it:

* ``verify_password`` answers ``NO_CREDENTIAL`` -- not ``WRONG_PASSWORD``,
  which would say a password exists, and not a bare ``False``, which a caller
  could read as "nothing to check" -- with the sentence saying it is not "no
  password required";
* ``start_password_reset`` refuses ``REFUSAL_NO_CREDENTIAL``: a reset resets a
  password that exists;
* an email change authorised by the current password refuses the same way,
  while one authorised by a caller goes through -- the path that exists for
  exactly this customer;
* the read says ``absent``, with the sentence.

Controls: the verification's no-credential branch planted to answer
WRONG_PASSWORD; the reset's check planted away.
"""

from __future__ import annotations

import json

import pytest

from customer_account import findings as f
from customer_account.store.postgres import tenant
from customer_account.store.records import (
    set_password,
    show_account,
    start_email_change,
    start_password_reset,
    verify_password,
)
from store_harness import A_PASSWORD, CREATED_AT, needs_postgres, seed_customer

pytestmark = needs_postgres


@pytest.mark.guarantee("G5")
def test_verification_answers_no_credential_by_name_with_the_sentence(app, tenant_id):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        answer = verify_password(cursor, tenant_id, customer_id, A_PASSWORD)
    assert answer.outcome == f.NO_CREDENTIAL
    assert answer.verified is False
    assert "no password required" in answer.sentence
    assert answer.means == f.NOT_VERIFIED_MEANS
    # THE CONTROL on the name: the same call with a credential answers differently
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="owner", at=CREATED_AT)
        assert verify_password(cursor, tenant_id, customer_id, A_PASSWORD).outcome == f.VERIFIED
        assert verify_password(cursor, tenant_id, customer_id, "not the one here").outcome == (
            f.WRONG_PASSWORD
        )
    app.rollback()


@pytest.mark.guarantee("G5")
def test_the_three_outcomes_are_the_published_set_and_every_non_verified_one_carries_the_sentence():
    assert set(f.VERIFICATIONS) == {f.VERIFIED, f.WRONG_PASSWORD, f.NO_CREDENTIAL}
    assert "no password required" in f.VERIFICATIONS[f.NO_CREDENTIAL]
    assert "never means the check may be skipped" in f.NOT_VERIFIED_MEANS


@pytest.mark.guarantee("G5")
def test_a_reset_onto_a_customer_with_no_credential_is_refused_by_name(app, tenant_id):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            start_password_reset(cursor, tenant_id, customer_id, valid_minutes=30, by="owner",
                                 at=CREATED_AT)
    assert refused.value.code == f.REFUSAL_NO_CREDENTIAL
    assert "NOT 'NO PASSWORD REQUIRED'" in f.REFUSALS[f.REFUSAL_NO_CREDENTIAL]


@pytest.mark.guarantee("G5")
def test_an_email_change_by_password_is_refused_by_name_and_by_caller_goes_through(app, tenant_id):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            start_email_change(cursor, tenant_id, customer_id, "alice.new@example.com",
                               valid_minutes=30, at=CREATED_AT, password=A_PASSWORD)
        assert refused.value.code == f.REFUSAL_NO_CREDENTIAL
    app.rollback()
    with tenant(app, tenant_id) as cursor:
        started = start_email_change(cursor, tenant_id, customer_id, "alice.new@example.com",
                                     valid_minutes=30, at=CREATED_AT, by="front desk")
    assert started["authorisation"] == "caller" and started["authorised_by"] == "front desk"
    app.rollback()


@pytest.mark.guarantee("G5")
def test_the_read_says_absent_by_name_and_the_command_line_exits_one_not_zero(
    app, tenant_id, capsys, monkeypatch
):
    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        shown = show_account(cursor, tenant_id, customer_id)
    app.rollback()
    assert shown["credential"]["state"] == "absent"
    assert "no password required" in shown["credential"]["sentence"]
    dsn_for_the_app(monkeypatch)
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", A_PASSWORD)
    status = main(["verify-password", "--tenant", str(tenant_id), "--customer", str(customer_id)])
    printed = json.loads(capsys.readouterr().out)
    assert status == 1, "a customer with no credential must not verify"
    assert printed["outcome"] == "NO_CREDENTIAL" and printed["verified"] is False
    assert "no password required" in printed["sentence"]
