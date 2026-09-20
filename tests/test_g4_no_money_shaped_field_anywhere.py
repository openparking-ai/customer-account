"""G4 -- no money-shaped, card-shaped or charge-shaped field exists anywhere in
the module.

This module has no view of whether anybody is charged, and never infers one:
a password exists because the caller set one, and the reason is the caller's.
So there is no column, no answer field and no JSON key that could carry a
fee, an amount, a balance, a card, a processor or a charge -- read from the
catalogue, from every dataclass the package defines (found by walking the
package, not by a list), and from the command line's rendered JSON.

The word lists are the instrument, so each has a positive control: a name
built from the list must be caught, or an empty result is blindness.

Controls: a `fee_cents` column planted into the migration; a money field
planted onto the verification answer.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import pkgutil

import pytest

import customer_account
from store_harness import A_PASSWORD, seed_customer, store_test

#: What a money field, a card field or a charge would be called. A name
#: containing one of these is refused; the control below proves the list
#: catches. `pay` covers payment and payer; `paid` is its own word.
MONEY_WORDS = ("amount", "fee", "price", "balance", "currency", "minor", "cost", "charge",
               "invoice", "pay", "paid", "cents", "billing", "tariff")
CARD_WORDS = ("card", "cvv", "cvc", "expiry_month", "iban", "account_number", "routing",
              "stripe", "processor")


def offending(names, words) -> list[str]:
    return [n for n in names if any(w in n.lower() for w in words)]


def every_dataclass_field() -> dict[str, tuple[str, ...]]:
    """Every dataclass in the package, by walking it -- so a class added next
    round is in the set the day it lands."""
    found: dict[str, tuple[str, ...]] = {}
    for info in pkgutil.walk_packages(customer_account.__path__, "customer_account."):
        module = importlib.import_module(info.name)
        for name, obj in vars(module).items():
            if isinstance(obj, type) and dataclasses.is_dataclass(obj) and (
                obj.__module__ == info.name
            ):
                found[f"{info.name}.{name}"] = tuple(fld.name for fld in dataclasses.fields(obj))
    return found


@pytest.mark.guarantee("G4")
def test_no_dataclass_in_the_package_carries_a_money_or_card_field():
    classes = every_dataclass_field()
    assert len(classes) >= 6, f"the walk found only {len(classes)} dataclasses"
    assert "customer_account.store.records.Verification" in classes
    assert "customer_account.identity.Customer" in classes
    problems = {
        cls: offending(fields, MONEY_WORDS + CARD_WORDS) for cls, fields in classes.items()
    }
    assert {cls: hits for cls, hits in problems.items() if hits} == {}


@pytest.mark.guarantee("G4")
def test_the_word_lists_catch_what_they_are_for():
    """The positive control: names a defect would use are caught."""
    assert offending(("amount_minor", "fee_cents", "balance", "paid_at", "billing_day"),
                     MONEY_WORDS) == [
        "amount_minor", "fee_cents", "balance", "paid_at", "billing_day"]
    assert offending(("card_last4", "stripe_customer", "iban"), CARD_WORDS) == [
        "card_last4", "stripe_customer", "iban"]
    assert offending(("outcome", "email", "token"), MONEY_WORDS + CARD_WORDS) == []


@pytest.mark.guarantee("G4")
@store_test
def test_the_schema_has_no_money_shaped_or_card_shaped_column(app):
    from customer_account.store.postgres import columns_named_like

    assert columns_named_like(app, MONEY_WORDS) == []
    assert columns_named_like(app, CARD_WORDS) == []
    assert columns_named_like(app, ("email",)) == [
        "customer_email_changes.from_email", "customer_email_changes.to_email",
        "customers.email", "pending_email_changes.new_email",
    ], "the control: the same query finds the columns that ARE there"


@pytest.mark.guarantee("G4")
@store_test
def test_the_command_lines_json_carries_no_such_key(app, tenant_id, capsys, monkeypatch):
    """Every key, at every depth, of every command's output."""
    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", A_PASSWORD)
    customer_id = seed_customer(app, tenant_id)
    T = ["--tenant", str(tenant_id)]
    at = "2026-06-01T09:00:00-06:00"
    keys: set[str] = set()

    def collect(value):
        if isinstance(value, dict):
            for k, v in value.items():
                keys.add(k)
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    for argv in (
        ["set-password", *T, "--customer", str(customer_id), "--by", "o", "--at", at],
        ["verify-password", *T, "--customer", str(customer_id)],
        ["start-password-reset", *T, "--customer", str(customer_id), "--valid-minutes", "5",
         "--by", "o", "--at", at],
        ["start-email-change", *T, "--customer", str(customer_id), "--new-email",
         "b@example.com", "--valid-minutes", "5", "--at", at],
        ["show-account", *T, "--customer", str(customer_id)],
        ["show-acceptances", *T, "--customer", str(customer_id)],
    ):
        assert main(argv) == 0, argv[0]
        collect(json.loads(capsys.readouterr().out))
    assert len(keys) >= 20, "the collector saw fewer keys than the commands render"
    assert offending(keys, MONEY_WORDS + CARD_WORDS) == []

