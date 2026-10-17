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
years is accepted as before. Nothing written holds at the module too, where
the caller owns the transaction: the refusal comes before the customer's live
token is superseded, not after. The store reads an instant back in the SESSION's
TimeZone, not in UTC, so an expiry is refused too where a session the database
accepts could not read it back: one at 9999-12-31T20:00Z was stored, and every
later read of the row in a session east of UTC failed in the driver. A token on
standard input that is blank or is not text is refused by name, never a
traceback -- under the C locale and ``PYTHONUTF8=1`` as well, where Python
reads standard input leniently and nothing raises at the read.

Controls: the boundary's ``except Refused`` planted away; the window's
overflow refusal planted away; the read-back margin planted away at each end;
the range-naming detail planted back to "past the last instant"; the
expiry planted back after the supersede, in each issue function; the
not-text refusal on standard input planted away; the strict re-encoding of the
line planted away.
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
    """OP-NODE-088, at the function the doors share: an expiry that cannot be
    computed, or that a session the database accepts could not read back, is
    refused by name; a window of about nine and a half years is an instant like
    any other -- no maximum was added."""
    from datetime import UTC, datetime, timedelta, timezone

    from customer_account.tokens import FIRST_READABLE, LAST_READABLE, expiry

    # An hour on from here is still the year 9999 where it was stated, and the
    # year 10000 in UTC: past what a datetime can hold anywhere.
    near_the_end = datetime(9999, 12, 31, 20, tzinfo=timezone(timedelta(hours=-6)))
    # The reported case: 9999-12-31T20:00Z is a datetime in UTC, so a check made
    # in UTC alone accepted it, and the store wrote it. The driver reads an
    # instant back in the SESSION's TimeZone, and at Pacific/Kiritimati (+14)
    # this one is the year 10000: every later read of the row failed.
    stated = datetime(2026, 6, 1, 9, tzinfo=timezone(timedelta(hours=-6)))
    reported = 4_193_699_340
    assert stated + timedelta(minutes=reported) == datetime(9999, 12, 31, 20, tzinfo=UTC)
    # The low end: a 30-minute window from an instant that is the year 0 in UTC.
    at_the_start = datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5)))
    # Just inside the first instant a datetime holds, but not a session west of
    # UTC: at Etc/GMT+12 (-12) this is the year 0.
    first_day = datetime(1, 1, 1, 10, tzinfo=UTC)
    for issued_at, minutes in ((CREATED_AT, 5_000_000_000), (CREATED_AT, 10**20),
                               (near_the_end, 60), (stated, reported), (at_the_start, 30),
                               (first_day, 30), (LAST_READABLE - timedelta(minutes=29), 30)):
        with pytest.raises(f.Refused) as refused:
            expiry(issued_at, minutes)
        assert refused.value.code == f.REFUSAL_VALID_MINUTES_TOO_LARGE, (issued_at, minutes)
        assert refused.value.field == "valid_minutes"
        # The detail names the range, and never says "past the last instant" of a
        # window that overflowed at the low end -- that one is thirty minutes long.
        detail = refused.value.detail
        assert "outside the instants" in detail and "past the last instant" not in detail
        assert FIRST_READABLE.isoformat() in detail and LAST_READABLE.isoformat() in detail
    # Each end of the range is itself an expiry like any other.
    end = LAST_READABLE - timedelta(minutes=30)
    assert expiry(end, 30) == LAST_READABLE
    assert expiry(FIRST_READABLE, 30) == FIRST_READABLE + timedelta(minutes=30)
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
@pytest.mark.parametrize("kind", ["password reset", "email change"])
def test_a_window_too_large_writes_nothing_at_the_module_so_the_live_token_stays_issued(
    app, tenant_id, kind
):
    """At the module, where the caller owns the transaction: the refusal writes
    nothing there either. The issue functions superseded the customer's live
    token FIRST and computed the expiry after, so the refusal arrived with the
    earlier token already 'cancelled', 'superseded' by one that was never issued,
    in the caller's open transaction -- and a caller that trusted "nothing is
    written" and committed left the emailed link dead. The command line rolls
    back on a refusal, which is why the door-level tests above could not see it.
    Here the earlier token still reads 'issued' after the refusal, in the same
    transaction; after a commit it is still redeemed. The control: an ordinary
    window -- five million minutes, still accepted -- does supersede it, read
    the same way."""
    from customer_account.store.postgres import tenant
    from customer_account.store.records import (
        confirm_email_change,
        consume_password_reset,
        set_password,
        start_email_change,
        start_password_reset,
    )
    from store_harness import ANOTHER_PASSWORD, LATER

    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="o", at=CREATED_AT)
    app.commit()
    if kind == "password reset":
        table, key = "credential_resets", "credential_reset"

        def issue(cursor, minutes, at):
            return start_password_reset(cursor, tenant_id, customer_id, valid_minutes=minutes,
                                        by="o", at=at)

        def redeem(cursor, token):
            return consume_password_reset(cursor, tenant_id, token, ANOTHER_PASSWORD, at=LATER)
    else:
        table, key = "pending_email_changes", "pending_email_change"

        def issue(cursor, minutes, at):
            address = "alice.new@example.com" if at == CREATED_AT else "alice.next@example.com"
            return start_email_change(cursor, tenant_id, customer_id, address,
                                      valid_minutes=minutes, at=at, by="o")

        def redeem(cursor, token):
            return confirm_email_change(cursor, tenant_id, token, at=LATER)

    def state_of(cursor, row_id):
        cursor.execute(f"SELECT state, cancelled_reason FROM {table} WHERE id = %s", (row_id,))
        return cursor.fetchone()

    with tenant(app, tenant_id) as cursor:
        first = issue(cursor, 120, CREATED_AT)
    app.commit()

    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            issue(cursor, 5_000_000_000, LATER)
        assert refused.value.code == f.REFUSAL_VALID_MINUTES_TOO_LARGE
        # Same transaction, before anything is committed or rolled back.
        assert state_of(cursor, first[key]) == ("issued", None), kind
        cursor.execute(f"SELECT count(*) FROM {table}")
        assert cursor.fetchone() == (1,)
    # The caller took "nothing is written" at its word.
    app.commit()

    # The control: the same read sees a supersede when one happens.
    with tenant(app, tenant_id) as cursor:
        issue(cursor, 5_000_000, LATER)
        assert state_of(cursor, first[key]) == ("cancelled", "superseded")
    app.rollback()

    with tenant(app, tenant_id) as cursor:
        redeem(cursor, first["token"])
        assert state_of(cursor, first[key]) == ("redeemed", None)
    app.commit()


@pytest.mark.guarantee("G14")
@store_test
def test_each_end_of_the_range_reads_back_in_the_widest_session_time_zones_the_database_accepts():
    """The margin is measured, not assumed. The driver reads a timestamptz in
    the session's TimeZone; PostgreSQL accepts one up to 167 hours from UTC
    either way, and 168 is refused. Each end of the range ``expiry`` allows
    reads back, unchanged, in a session at each of those extremes and at the
    widest named zones. The control: the reported expiry, 9999-12-31T20:00Z,
    does NOT read back in a session at Pacific/Kiritimati -- which is what
    made a stored row unreadable."""
    from datetime import UTC, datetime

    import psycopg

    from customer_account.tokens import FIRST_READABLE, LAST_READABLE
    from store_harness import DSN

    with psycopg.connect(DSN, autocommit=True) as connection:

        def session_at(zone: str) -> None:
            connection.execute("SELECT set_config('TimeZone', %s, false)", (zone,))

        for zone in ("XXX-167", "XXX+167", "Pacific/Kiritimati", "Etc/GMT+12"):
            session_at(zone)
            for instant in (FIRST_READABLE, LAST_READABLE):
                (back,) = connection.execute("SELECT %s::timestamptz", (instant,)).fetchone()
                assert back == instant, (zone, instant, back)
        session_at("Pacific/Kiritimati")
        with pytest.raises(psycopg.DataError):
            connection.execute("SELECT %s::timestamptz",
                               (datetime(9999, 12, 31, 20, tzinfo=UTC),)).fetchone()
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            session_at("XXX-168")


@pytest.mark.guarantee("G14")
@store_test
@pytest.mark.parametrize("command", ["start-password-reset", "start-email-change"])
def test_an_expiry_a_session_east_of_utc_cannot_read_back_is_refused_exit_3_and_writes_nothing(
    app, tenant_id, capsys, monkeypatch, command
):
    """The reported case, at the door: in a session at Pacific/Kiritimati
    (+14), 4,193,699,340 minutes from 2026-06-01T09:00-06:00 is an expiry at
    9999-12-31T20:00Z. It was accepted, exit 0, and the next read of the row
    in that session -- consume-password-reset, or show-account with the change
    pending -- exited 2 with a sentence blaming the database. Now it is refused
    by name, exit 3, with nothing written; five million minutes is accepted in
    the same session, and the account then reads back."""
    import os

    from psycopg import conninfo

    from customer_account.cli import main
    from customer_account.store.postgres import tenant
    from customer_account.store.records import set_password
    from store_harness import query
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    params = conninfo.conninfo_to_dict(os.environ["CUSTOMER_ACCOUNT_DSN"])
    monkeypatch.setenv("CUSTOMER_ACCOUNT_DSN", conninfo.make_conninfo(
        **{**params, "options": "-c timezone=Pacific/Kiritimati"}))
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="o", at=CREATED_AT)
    app.commit()
    monkeypatch.delenv("CUSTOMER_ACCOUNT_PASSWORD", raising=False)
    table = "credential_resets" if command == "start-password-reset" else "pending_email_changes"
    extra = ["--by", "o"] + (["--new-email", "alice.new@example.com"]
                             if command == "start-email-change" else [])
    T = ["--tenant", str(tenant_id), "--customer", str(customer_id)]

    def run(minutes: str):
        return _run(main, [command, *T, "--valid-minutes", minutes, *extra,
                           "--at", "2026-06-01T09:00:00-06:00"], capsys)

    status, out, err = run("4193699340")
    assert status == 3 and err == "" and "Traceback" not in out, (status, out, err)
    printed = json.loads(out)
    assert printed["refused"] == f.REFUSAL_VALID_MINUTES_TOO_LARGE, printed
    assert printed["field"] == "valid_minutes"
    assert query(app, tenant_id, f"SELECT count(*) FROM {table}") == [(0,)]
    status, out, err = run("5000000")
    assert status == 0, (out, err)
    assert query(app, tenant_id, f"SELECT count(*) FROM {table}") == [(1,)]
    status, out, err = _run(main, ["show-account", *T], capsys)
    assert status == 0 and err == "", (status, out, err)


@pytest.mark.guarantee("G14")
@store_test
@pytest.mark.parametrize("command", ["confirm-email-change", "consume-password-reset"])
@pytest.mark.parametrize("lenient", [{"PYTHONUTF8": "1"}, {"LC_ALL": "C"}],
                         ids=["PYTHONUTF8=1", "LC_ALL=C"])
def test_a_token_that_is_not_utf8_is_refused_by_name_where_python_reads_stdin_leniently(
    app, tenant_id, monkeypatch, command, lenient
):
    """In a FRESH interpreter, with the real standard input. Under the C
    locale (LANG unset: containers, cron, systemd) and under PYTHONUTF8=1,
    Python reads standard input with errors='surrogateescape', so bytes that
    are not UTF-8 raise nothing at the read; they reached the digest and
    raised there, and the operator got a traceback and exit 1. The in-process
    test below swaps in a strict reader, so it never meets this.

    The control first: the child must really read leniently, or a pass here
    would prove nothing about the case."""
    import os
    import subprocess
    import sys

    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONIOENCODING", "PYTHONUTF8", "LANG", "LC_ALL", "LC_CTYPE")}
    env.update(lenient)
    env["CUSTOMER_ACCOUNT_PASSWORD"] = A_PASSWORD
    probe = subprocess.run([sys.executable, "-c", "import sys; print(sys.stdin.errors)"],
                           input=b"", capture_output=True, env=env)
    assert probe.stdout.decode().strip() == "surrogateescape", probe
    done = subprocess.run(
        [sys.executable, "-m", "customer_account.cli", command, "--tenant", str(tenant_id),
         "--at", "2026-06-01T09:00:00-06:00"],
        cwd=ROOT, input=b"\xff\xfe not text\n", capture_output=True, env=env,
    )
    assert b"Traceback" not in done.stdout + done.stderr, done.stderr.decode(errors="replace")
    assert (done.returncode, done.stderr) == (3, b""), done
    printed = json.loads(done.stdout)
    assert (printed["refused"], printed["field"]) == (f.REFUSAL_FIELD_BLANK, "token"), printed


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
