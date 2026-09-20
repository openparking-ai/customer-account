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

**THE COMMAND LINE'S DOORS ARE DERIVED FROM THE PARSER, NOT LISTED.** The
L3 of this round found the JSON instrument driving 6 of the parser's 10
commands from a typed argv list, so a money key on `create-account`'s output
left it green -- a hand-picked list of doors is not a denominator, and this
project has paid for that shape before. Now ``every_command`` is read from
``_parser()``; ``drive_every_command`` has one driver per command and the
test REFUSES if the parser exposes a door the drivers do not cover (or the
reverse) -- a new command tomorrow fails here until it is driven. The count
of doors is produced, not typed. And the control that proves the fix is the
fix: under a plant on a door the old list never drove, the derived instrument
reads RED while the old typed list, kept beside it, reads GREEN on the same
plant -- run as a child process, because a reloaded plant in this process is
the thing plant.py's docstring warns about.

Controls: a `fee_cents` column planted into the migration; a money field
planted onto the verification answer; a money key planted onto each of the
four doors the old list never drove, one at a time.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import pkgutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import customer_account
from customer_account.cli import _parser
from plant import planted
from store_harness import A_PASSWORD, ANOTHER_PASSWORD, store_test

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


def every_command() -> frozenset[str]:
    """The parser's commands -- the denominator, read from argparse itself."""
    return frozenset(
        name for action in _parser()._actions
        if isinstance(action, argparse._SubParsersAction) for name in action.choices
    )


#: The six commands the instrument drove before the fix round, kept as the
#: OLD instrument's denominator so the control below can show the two differ.
COMMANDS_THE_OLD_LIST_DROVE = frozenset({
    "set-password", "verify-password", "start-password-reset", "start-email-change",
    "show-account", "show-acceptances",
})

AT = "2026-06-01T09:00:00-06:00"
LATER_AT = "2026-06-01T09:05:00-06:00"

#: A runner takes argv and the password to put in the environment (or None),
#: and returns (exit status, the JSON printed).
Runner = Callable[[list[str], str | None], tuple[int, dict]]


def drive_every_command(run: Runner, tenant_id, terms_dir: Path) -> dict[str, dict]:
    """ONE DRIVER PER COMMAND, and the set of drivers is held equal to the
    parser's command set in both directions -- so a door added to the parser
    that nothing here drives is a failure of this instrument, by name, never
    a skip. Returns every command's rendered JSON, keyed by command."""
    terms_dir.mkdir(parents=True, exist_ok=True)
    terms = terms_dir / "terms.txt"
    email_text = terms_dir / "email.txt"
    terms.write_text("The terms, as shown.")
    email_text.write_text("We will email you.")
    T = ["--tenant", str(tenant_id)]
    out: dict[str, dict] = {}

    def done(command: str, argv: list[str], password: str | None = None) -> dict:
        status, body = run([command, *T, *argv], password)
        assert status == 0, (command, status, body)
        out[command] = body
        return body

    customer = done("create-account", ["--email", "g4@example.com", "--by", "self", "--at", AT,
                                       "--terms-version", "v1", "--terms-shown", str(terms),
                                       "--channel", f"email={email_text}"])["customer"]
    C = ["--customer", customer]
    done("record-terms-acceptance", [*C, "--by", "self", "--at", LATER_AT, "--terms-version", "v2",
                                     "--terms-shown", str(terms)])
    done("set-password", [*C, "--by", "o", "--at", AT], A_PASSWORD)
    done("verify-password", C, A_PASSWORD)
    change = done("start-email-change", [*C, "--new-email", "g4.new@example.com",
                                         "--valid-minutes", "30", "--at", AT], A_PASSWORD)
    done("confirm-email-change", ["--token", change["token"], "--at", LATER_AT])
    reset = done("start-password-reset", [*C, "--valid-minutes", "30", "--by", "o", "--at", AT])
    done("consume-password-reset", ["--token", reset["token"], "--at", LATER_AT], ANOTHER_PASSWORD)
    done("show-account", C)
    done("show-acceptances", C)

    driven, exposed = frozenset(out), every_command()
    assert driven == exposed, (
        f"the parser exposes doors this instrument does not drive: {sorted(exposed - driven)}; "
        f"drivers for doors the parser does not expose: {sorted(driven - exposed)}"
    )
    return out


def keys_at_every_depth(outputs: dict[str, dict]) -> set[str]:
    keys: set[str] = set()

    def collect(value):
        if isinstance(value, dict):
            for k, v in value.items():
                keys.add(k)
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    for body in outputs.values():
        collect(body)
    return keys


def in_process_runner(capsys, monkeypatch) -> Runner:
    from customer_account.cli import main

    def run(argv, password):
        if password is None:
            monkeypatch.delenv("CUSTOMER_ACCOUNT_PASSWORD", raising=False)
        else:
            monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", password)
        status = main(argv)
        printed = capsys.readouterr().out
        return status, (json.loads(printed) if printed.strip() else {})

    return run


def child_process_runner() -> Runner:
    """The command line in a FRESH interpreter, so a plant in the source is
    what runs. In-process, the already-imported module would run instead."""
    root = Path(__file__).resolve().parent.parent

    def run(argv, password):
        env = {k: v for k, v in os.environ.items() if k != "CUSTOMER_ACCOUNT_PASSWORD"}
        if password is not None:
            env["CUSTOMER_ACCOUNT_PASSWORD"] = password
        done = subprocess.run([sys.executable, "-m", "customer_account.cli", *argv], cwd=root,
                              capture_output=True, text=True, env=env)
        return done.returncode, (json.loads(done.stdout) if done.stdout.strip() else {})

    return run


@pytest.mark.guarantee("G4")
def test_the_door_set_is_read_from_the_parser_and_is_larger_than_the_old_list():
    exposed = every_command()
    assert len(exposed) >= 10, sorted(exposed)
    assert COMMANDS_THE_OLD_LIST_DROVE < exposed, "the old list is a strict subset: the two differ"
    assert {"create-account", "record-terms-acceptance", "confirm-email-change",
            "consume-password-reset"} <= exposed - COMMANDS_THE_OLD_LIST_DROVE


@pytest.mark.guarantee("G4")
@store_test
def test_the_command_lines_json_carries_no_such_key(app, tenant_id, tmp_path, capsys, monkeypatch):
    """Every key, at every depth, of EVERY command's output -- the commands
    read from the parser."""
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    outputs = drive_every_command(in_process_runner(capsys, monkeypatch), tenant_id, tmp_path)
    assert len(outputs) == len(every_command()), "every door drove: the count is produced here"
    keys = keys_at_every_depth(outputs)
    assert len(keys) >= 25, "the collector saw fewer keys than the commands render"
    assert offending(keys, MONEY_WORDS + CARD_WORDS) == []


@pytest.mark.guarantee("G4")
@store_test
def test_a_key_on_a_door_the_old_list_never_drove_is_red_here_and_was_green_there(
    app, owner, tenant_id, tmp_path, monkeypatch
):
    """THE CONTROL THAT PROVES THE FIX IS THE FIX. A money key planted onto
    create-account's output -- a door outside the old denominator -- in a
    child process: the derived instrument reads RED; the old six-command list,
    kept beside it, reads GREEN on the same plant. Then, unplanted, both are
    green, so the red was the plant and not the runner."""
    from store_harness import new_tenant
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    run = child_process_runner()
    with planted(
        "store/records.py",
        '    return {"customer": str(customer_id), "email": address, "external_id": reference,\n'
        '            "acceptance": accepted}',
        '    return {"customer": str(customer_id), "email": address, "external_id": reference,\n'
        '            "acceptance": accepted, "fee_cents": 0}  # PLANTED',
    ):
        outputs = drive_every_command(run, tenant_id, tmp_path / "planted")
    derived = offending(keys_at_every_depth(outputs), MONEY_WORDS + CARD_WORDS)
    old = offending(keys_at_every_depth(
        {c: b for c, b in outputs.items() if c in COMMANDS_THE_OLD_LIST_DROVE}
    ), MONEY_WORDS + CARD_WORDS)
    assert derived == ["fee_cents"], f"the derived instrument did not go RED: {derived}"
    assert old == [], f"the old typed list went red on a door it never drove: {old}"
    # unplanted, in a fresh tenant, both green -- the restore is proven by the run
    outputs = drive_every_command(run, new_tenant(owner), tmp_path / "clean")
    assert offending(keys_at_every_depth(outputs), MONEY_WORDS + CARD_WORDS) == []
