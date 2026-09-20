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

Controls: the boundary's ``except Refused`` planted away.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from customer_account import findings as f
from store_harness import A_PASSWORD, seed_customer, store_test

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

