"""G14 -- the command line refuses, never tracebacks.

Every ``Refused`` the module raises reaches the boundary as
``{"refused", "field", "detail"}`` with exit 3. What the libraries the
boundary calls can raise is mapped there too: an instant that does not parse
or carries no offset, a text file that is missing or is a directory, a
``--channel`` pair without its ``=``, a window that is not a whole number.
A machine that is not set up -- no DSN, a DSN that does not connect -- is one
sentence on stderr with exit 2, and the DSN is not in it. A value that starts
with a dash reaches the module rather than argparse's usage error.

**AND EVERY REFUSAL CODE THE MODULE CAN RAISE IS REGISTERED.** The raise
sites are read from the AST of every source file; each code named at one is
in ``findings.REFUSALS``, and each registered code is named at a raise site
somewhere -- an orphan sentence published for a code nothing raises is the
defect the contract check cannot see on its own.

**AND WHAT THE TOKEN WINDOW AND STANDARD INPUT CAN MEET.** A window so large
that its expiry cannot be computed was a traceback, exit 1; it is refused by
name, exit 3, with nothing written -- and no maximum was added, so a window of
years is accepted as before. A token on standard input that is blank or is
not text is refused by name, never a traceback.

Controls: the boundary's ``except Refused`` planted away; the window's
overflow refusal planted away; the not-text refusal on standard input planted
away.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from customer_account import findings as f
from store_harness import A_PASSWORD, CREATED_AT, seed_customer, store_test

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "customer_account"


def _codes_named_at_raise_sites() -> set[str]:
    """Every ``REFUSAL_*`` name passed as the first argument of a ``Refused(...)``
    call, from the AST."""
    named: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and (
                node.func.id == "Refused" and node.args
            ):
                first = node.args[0]
                if isinstance(first, ast.Name):
                    named.add(first.id)
    return named


@pytest.mark.guarantee("G14")
def test_every_code_raised_is_registered_and_every_registered_code_is_raised():
    raised = _codes_named_at_raise_sites()
    assert len(raised) >= 20, "the AST walk found fewer raise sites than the module has"
    registered = {name for name in dir(f) if name.startswith("REFUSAL_")}
    assert raised - registered == set(), "raised but not registered"
    assert registered - raised == set(), "registered but raised nowhere: an orphan sentence"
    assert {getattr(f, name) for name in registered} == set(f.REFUSALS)


@pytest.mark.guarantee("G14")
def test_a_code_invented_at_a_raise_site_fails_at_the_raise_site():
    with pytest.raises(KeyError):
        f.Refused("REFUSAL_NOBODY_REGISTERED_THIS", "x", "y")


def _run(main, argv, capsys):
    status = main(argv)
    out = capsys.readouterr()
    return status, out.out, out.err


@pytest.mark.guarantee("G14")
def test_no_dsn_and_a_dsn_that_does_not_connect_are_one_sentence_on_stderr_exit_2(
    capsys, monkeypatch
):
    from customer_account.cli import main

    monkeypatch.delenv("CUSTOMER_ACCOUNT_DSN", raising=False)
    T = ["--tenant", "00000000-0000-0000-0000-000000000000"]
    status, out, err = _run(main, ["show-acceptances", *T, "--customer",
                                   "00000000-0000-0000-0000-000000000001"], capsys)
    assert (status, out) == (2, "") and "CUSTOMER_ACCOUNT_DSN is not set" in err
    secret = "host=localhost port=1 dbname=nowhere password=must-not-be-echoed-9f1c"
    monkeypatch.setenv("CUSTOMER_ACCOUNT_DSN", secret)
    status, out, err = _run(main, ["show-acceptances", *T, "--customer",
                                   "00000000-0000-0000-0000-000000000001"], capsys)
    assert (status, out) == (2, "") and "did not connect" in err
    assert "must-not-be-echoed" not in err and len(err.splitlines()) >= 1
    assert "Traceback" not in err


@pytest.mark.guarantee("G14")
@store_test
@pytest.mark.parametrize(
    "argv_tail,code,field",
    [
        (["--at", "2026-06-01T09:00:00"], f.REFUSAL_INSTANT_MALFORMED, "--at"),
        (["--at", "yesterday"], f.REFUSAL_INSTANT_MALFORMED, "--at"),
        (["--at", "2026-06-01T09:00:00-06:00", "--terms-shown", "/nowhere/terms.txt"],
         f.REFUSAL_DOCUMENT_UNREADABLE, "--terms-shown"),
        (["--at", "2026-06-01T09:00:00-06:00", "--terms-shown", "/"],
         f.REFUSAL_DOCUMENT_UNREADABLE, "--terms-shown"),
        (["--at", "2026-06-01T09:00:00-06:00", "--channel", "sms"],
         f.REFUSAL_FIELD_BLANK, "--channel"),
        (["--at", "2026-06-01T09:00:00-06:00", "--email", "-not-an-address"],
         f.REFUSAL_EMAIL_MALFORMED, "email"),
    ],
    ids=["naive instant", "not an instant", "missing file", "a directory", "channel pair",
         "value starting with a dash"],
)
def test_what_the_boundary_can_meet_is_refused_by_name_exit_3(
    app, tenant_id, tmp_path, capsys, monkeypatch, argv_tail, code, field
):
    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    terms = tmp_path / "terms.txt"
    terms.write_text("the terms")
    argv = ["create-account", "--tenant", str(tenant_id), "--by", "x", "--terms-version", "v1",
            "--terms-shown", str(terms)]
    if "--email" not in argv_tail:
        argv += ["--email", "a@example.com"]
    argv += argv_tail
    # where the tail names its own --terms-shown, argparse keeps the LAST, so the
    # unreadable one is the one read
    status, out, err = _run(main, argv, capsys)
    assert status == 3, (out, err)
    assert err == "" and "Traceback" not in out
    printed = json.loads(out)
    assert printed["refused"] == code and printed["field"] == field, printed


@pytest.mark.guarantee("G14")
@store_test
def test_a_refusal_from_the_store_is_the_same_json_shape_and_writes_nothing(
    app, tenant_id, capsys, monkeypatch
):
    from customer_account.cli import main
    from store_harness import query
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    customer_id = seed_customer(app, tenant_id)
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", A_PASSWORD)
    status, out, err = _run(main, ["start-password-reset", "--tenant", str(tenant_id),
                                   "--customer", str(customer_id), "--valid-minutes", "x",
                                   "--by", "o", "--at", "2026-06-01T09:00:00-06:00"], capsys)
    assert status == 3 and json.loads(out)["refused"] == f.REFUSAL_FIELD_BLANK
    status, out, err = _run(main, ["start-password-reset", "--tenant", str(tenant_id),
                                   "--customer", str(customer_id), "--by", "o",
                                   "--at", "2026-06-01T09:00:00-06:00"], capsys)
    assert status == 3 and json.loads(out)["refused"] == f.REFUSAL_VALID_MINUTES_NOT_STATED
    status, out, err = _run(main, ["start-password-reset", "--tenant", str(tenant_id),
                                   "--customer", str(customer_id), "--valid-minutes", "30",
                                   "--by", "o", "--at", "2026-06-01T09:00:00-06:00"], capsys)
    assert status == 3 and json.loads(out)["refused"] == f.REFUSAL_NO_CREDENTIAL
    assert query(app, tenant_id, "SELECT count(*) FROM credential_resets") == [(0,)]



@pytest.mark.guarantee("G14")
def test_a_window_whose_end_cannot_be_computed_is_refused_by_name_and_a_long_one_is_not():
    """OP-NODE-088, at the function the doors share: past the year 9999 (in
    UTC too) is refused by name; a window of about nine and a half years is an
    instant like any other -- no maximum was added."""
    from datetime import datetime, timedelta, timezone

    from customer_account.tokens import expiry

    # an hour on from here is still the year 9999 where it was stated, and the
    # year 10000 in UTC, where the store's instants are read back
    near_the_end = datetime(9999, 12, 31, 20, tzinfo=timezone(timedelta(hours=-6)))
    for issued_at, minutes in ((CREATED_AT, 5_000_000_000), (CREATED_AT, 10**20),
                               (near_the_end, 60)):
        with pytest.raises(f.Refused) as refused:
            expiry(issued_at, minutes)
        assert refused.value.code == f.REFUSAL_VALID_MINUTES_TOO_LARGE, (issued_at, minutes)
        assert refused.value.field == "valid_minutes"
    assert expiry(CREATED_AT, 5_000_000) == CREATED_AT + timedelta(minutes=5_000_000)


@pytest.mark.guarantee("G14")
@store_test
@pytest.mark.parametrize("command", ["start-password-reset", "start-email-change"])
def test_a_window_too_large_to_compute_is_refused_by_name_exit_3_and_writes_nothing(
    app, tenant_id, capsys, monkeypatch, command
):
    """The door as the operator meets it: five billion minutes was a traceback
    and exit 1; now exit 3, the JSON, nothing written. Five million minutes is
    still accepted, as before."""
    from customer_account.cli import main
    from customer_account.store.postgres import tenant
    from customer_account.store.records import set_password
    from store_harness import query
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="o", at=CREATED_AT)
    app.commit()
    monkeypatch.delenv("CUSTOMER_ACCOUNT_PASSWORD", raising=False)
    table = "credential_resets" if command == "start-password-reset" else "pending_email_changes"
    extra = ["--by", "o"] + (["--new-email", "alice.new@example.com"]
                             if command == "start-email-change" else [])

    def run(minutes: str):
        return _run(main, [command, "--tenant", str(tenant_id), "--customer", str(customer_id),
                           "--valid-minutes", minutes, *extra,
                           "--at", "2026-06-01T09:00:00-06:00"], capsys)

    status, out, err = run("5000000000")
    assert status == 3 and err == "" and "Traceback" not in out, (status, out, err)
    printed = json.loads(out)
    assert printed["refused"] == f.REFUSAL_VALID_MINUTES_TOO_LARGE, printed
    assert printed["field"] == "valid_minutes"
    assert query(app, tenant_id, f"SELECT count(*) FROM {table}") == [(0,)]
    status, out, err = run("5000000")
    assert status == 0, (out, err)
    assert query(app, tenant_id, f"SELECT count(*) FROM {table}") == [(1,)]


@pytest.mark.guarantee("G14")
@store_test
@pytest.mark.parametrize("command", ["confirm-email-change", "consume-password-reset"])
@pytest.mark.parametrize("given", ["blank", "not text"])
def test_a_token_on_stdin_that_is_blank_or_not_text_is_refused_by_name_exit_3(
    app, tenant_id, capsys, monkeypatch, command, given
):
    import io
    import sys

    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", A_PASSWORD)
    raw = b"\n" if given == "blank" else b"\xff\xfe not text\n"
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    status, out, err = _run(main, [command, "--tenant", str(tenant_id),
                                   "--at", "2026-06-01T09:00:00-06:00"], capsys)
    assert status == 3 and err == "" and "Traceback" not in out, (status, out, err)
    printed = json.loads(out)
    assert (printed["refused"], printed["field"]) == (f.REFUSAL_FIELD_BLANK, "token"), printed
