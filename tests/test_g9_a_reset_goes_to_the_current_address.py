"""G9 -- a password reset is delivered to the customer's CURRENT address, read
from the row at issue and never supplied by the caller.

Three doors, each held: the store's ``start_password_reset`` names
``deliver_to`` from the customer row, and a pending, unconfirmed email change
does NOT move it -- that is the plausible defect, "deliver to the latest
address", and it is the circular path C-3 forbids: a person who started a
change to an address they control would receive the reset there; the
command's parser has no option that could carry an address, read from
argparse itself rather than from a list; and once the change IS confirmed,
the reset goes to the new address, because it is then the current one.

A reset resets a password that exists (G5 holds the refusal); consuming it
replaces the credential, and the old password stops verifying.

**EACH RECOVERY PATH CLOSES THE OTHER.** Someone holding a phished password
starts a change to an address they control; the customer then sets a new
password. The pending change must not survive that, or its confirmation takes
the account: a new password -- through set-password or a consumed reset --
cancels it, with ``password_set`` as the reason. And a reset delivered to the
OLD address stops working once a change to a new one is confirmed, with
``email_changed`` as the reason. Each test has its over-reach control: a token
issued after the event still works.

Controls: the delivery address planted to follow the pending change; each of
the three cancellations planted away, one at a time.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from customer_account import findings as f
from customer_account.cli import _parser
from customer_account.store.postgres import tenant
from customer_account.store.records import (
    EMAIL_CHANGED,
    PASSWORD_SET,
    confirm_email_change,
    consume_password_reset,
    set_password,
    start_email_change,
    start_password_reset,
    verify_password,
)
from store_harness import (
    A_PASSWORD,
    ANOTHER_PASSWORD,
    CREATED_AT,
    needs_postgres,
    query,
    seed_customer,
)

pytestmark = needs_postgres

MINUTE = timedelta(minutes=1)
OLD, NEW = "alice@example.com", "alice.new@example.com"


def _with_credential(app, tenant_id):
    customer_id = seed_customer(app, tenant_id, OLD)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="owner", at=CREATED_AT)
    app.commit()
    return customer_id


@pytest.mark.guarantee("G9")
def test_a_pending_unconfirmed_change_does_not_move_the_delivery_address(app, tenant_id):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        change = start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=30,
                                    at=CREATED_AT, by="x")
        reset = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=30,
                                     by="support", at=CREATED_AT + MINUTE)
    app.commit()
    assert reset["deliver_to"] == OLD, "the reset followed an unconfirmed change"
    # once the change is confirmed, the new address IS the current one
    with tenant(app, tenant_id) as cursor:
        confirm_email_change(cursor, tenant_id, change["token"], at=CREATED_AT + 2 * MINUTE)
        later = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=30,
                                     by="support", at=CREATED_AT + 3 * MINUTE)
    app.commit()
    assert later["deliver_to"] == NEW


@pytest.mark.guarantee("G9")
def test_the_command_has_no_option_that_could_carry_an_address():
    """Read from the parser, not from a list somebody typed."""
    parser = _parser()
    commands = {
        name: sub for action in parser._actions
        if hasattr(action, "choices") and isinstance(action.choices, dict)
        for name, sub in action.choices.items()
    }
    options = {opt for action in commands["start-password-reset"]._actions
               for opt in action.option_strings}
    assert not any("email" in opt or "deliver" in opt or "address" in opt for opt in options), (
        options
    )
    assert "--customer" in options and "--by" in options, "the scan reads the real option set"
    # THE CONTROL on the scan: the command that legitimately takes an address is seen to
    change_options = {opt for action in commands["start-email-change"]._actions
                      for opt in action.option_strings}
    assert "--new-email" in change_options


@pytest.mark.guarantee("G9")
def test_consuming_the_reset_replaces_the_credential_and_the_old_password_stops_verifying(
    app, tenant_id
):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        reset = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=30,
                                     by="support", at=CREATED_AT)
        done = consume_password_reset(cursor, tenant_id, reset["token"], ANOTHER_PASSWORD,
                                      at=CREATED_AT + MINUTE)
        assert done["credential"] == "replaced"
        assert done["set_by"] == f"credential_reset:{reset['credential_reset']}"
        assert verify_password(cursor, tenant_id, customer_id, ANOTHER_PASSWORD).outcome == (
            f.VERIFIED)
        assert verify_password(cursor, tenant_id, customer_id, A_PASSWORD).outcome == (
            f.WRONG_PASSWORD)
    app.rollback()


@pytest.mark.guarantee("G9")
def test_the_new_password_is_held_to_the_same_rule_and_the_token_survives_the_refusal(
    app, tenant_id
):
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        reset = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=30,
                                     by="support", at=CREATED_AT)
    app.commit()
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            consume_password_reset(cursor, tenant_id, reset["token"], "short", at=CREATED_AT)
        assert refused.value.code == f.REFUSAL_PASSWORD_TOO_SHORT
    app.rollback()
    with tenant(app, tenant_id) as cursor:
        consume_password_reset(cursor, tenant_id, reset["token"], ANOTHER_PASSWORD,
                               at=CREATED_AT + MINUTE)
    app.rollback()


@pytest.mark.guarantee("G9")
@pytest.mark.parametrize("door", ["a consumed reset", "set-password"])
def test_a_new_password_cancels_the_pending_email_change_through_both_doors(
    app, tenant_id, door
):
    """OP-NODE-087: a change started with the (phished) current password, then
    a new password. The change is refused as CANCELLED, by name, with its
    reason and who cancelled it on the row, and the account keeps its address.
    A change started after the new password works as before."""
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        change = start_email_change(cursor, tenant_id, customer_id, "someone.else@example.com",
                                    valid_minutes=60, at=CREATED_AT, password=A_PASSWORD)
        if door == "a consumed reset":
            reset = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=60,
                                         by="support", at=CREATED_AT + MINUTE)
            consume_password_reset(cursor, tenant_id, reset["token"], ANOTHER_PASSWORD,
                                   at=CREATED_AT + 2 * MINUTE)
            cancelled_by = f"credential_reset:{reset['credential_reset']}"
        else:
            set_password(cursor, tenant_id, customer_id, ANOTHER_PASSWORD, by="the customer",
                         at=CREATED_AT + 2 * MINUTE)
            cancelled_by = "the customer"
    app.commit()
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            confirm_email_change(cursor, tenant_id, change["token"], at=CREATED_AT + 3 * MINUTE)
    app.rollback()
    assert refused.value.code == f.REFUSAL_TOKEN_CANCELLED
    assert PASSWORD_SET in refused.value.detail
    assert query(app, tenant_id, "SELECT state, cancelled_by, cancelled_reason, cancelled_at "
                 "FROM pending_email_changes WHERE customer_id = %s", (str(customer_id),)) == [
        ("cancelled", cancelled_by, PASSWORD_SET, CREATED_AT + 2 * MINUTE)]
    assert query(app, tenant_id, "SELECT email FROM customers WHERE id = %s",
                 (str(customer_id),)) == [(OLD,)]
    # THE OVER-REACH CONTROL: a change started after the new password takes effect
    with tenant(app, tenant_id) as cursor:
        later = start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=60,
                                   at=CREATED_AT + 4 * MINUTE, password=ANOTHER_PASSWORD)
        done = confirm_email_change(cursor, tenant_id, later["token"], at=CREATED_AT + 5 * MINUTE)
    app.rollback()
    assert done["to_email"] == NEW


@pytest.mark.guarantee("G9")
def test_a_confirmed_email_change_cancels_the_reset_sent_to_the_old_address(app, tenant_id):
    """OP-NODE-087: a reset delivered to the old address, then a change to a new
    one confirmed. The reset is refused as CANCELLED, by name, with its reason
    and the history row that cancelled it, and the password is unchanged. A
    reset issued afterwards goes to the new address and works."""
    customer_id = _with_credential(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        reset = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=60,
                                     by="support", at=CREATED_AT)
        change = start_email_change(cursor, tenant_id, customer_id, NEW, valid_minutes=60,
                                    at=CREATED_AT + MINUTE, by="front desk")
        done = confirm_email_change(cursor, tenant_id, change["token"],
                                    at=CREATED_AT + 2 * MINUTE)
    app.commit()
    assert reset["deliver_to"] == OLD
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            consume_password_reset(cursor, tenant_id, reset["token"], ANOTHER_PASSWORD,
                                   at=CREATED_AT + 3 * MINUTE)
    app.rollback()
    assert refused.value.code == f.REFUSAL_TOKEN_CANCELLED
    assert EMAIL_CHANGED in refused.value.detail
    assert query(app, tenant_id, "SELECT state, cancelled_by, cancelled_reason, cancelled_at "
                 "FROM credential_resets WHERE customer_id = %s", (str(customer_id),)) == [
        ("cancelled", f"email_change:{done['email_change']}", EMAIL_CHANGED,
         CREATED_AT + 2 * MINUTE)]
    with tenant(app, tenant_id) as cursor:
        assert verify_password(cursor, tenant_id, customer_id, A_PASSWORD).outcome == f.VERIFIED
        # THE OVER-REACH CONTROL: a reset issued after the change works, at the new address
        later = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=60,
                                     by="support", at=CREATED_AT + 4 * MINUTE)
        consume_password_reset(cursor, tenant_id, later["token"], ANOTHER_PASSWORD,
                               at=CREATED_AT + 5 * MINUTE)
    app.rollback()
    assert later["deliver_to"] == NEW
