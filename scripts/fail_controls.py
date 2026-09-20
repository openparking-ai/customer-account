#!/usr/bin/env python3
"""Every guarantee, proven able to FAIL.

A test that has never failed is a decoration. For each registered guarantee this
script breaks the thing the guarantee guards, runs that guarantee's tests in a
fresh interpreter, and requires them to go RED. If a test stays green with its
subject broken, it was not measuring its subject and this script says so.

    python scripts/fail_controls.py            # every control
    python scripts/fail_controls.py G2 G9      # a subset
    python scripts/fail_controls.py --anchors  # anchors only, in a second

**The anchor pre-flight.** ``--anchors`` counts every plant's ``from`` string in
its file without running a single test. An anchor is a string in a source file,
and editing the line it sits on silently retires the control that depends on it --
a sibling repository in this project had five dead controls killed exactly that
way, by a fix round that edited the anchor lines and reported the result as
controls that worked. The pre-flight answers that whole failure mode in a second
where the full run takes a minute, and run against an older tree it is its own
positive control.

**Restores are written back, never `git checkout`.** Each plant is a context
manager whose ``finally`` writes the original bytes and verifies them. `checkout`
has been broken twice on this project and would take a co-resident session's
uncommitted work with it.

**AND A CONTROL THAT REPORTS UNMEASURED IS REPORTING ON THE RUNNER.** If a target
is already red before anything is planted, or ran no tests at all, this says
UNMEASURED rather than counting a pass -- because a suite that cannot run cannot
tell you whether a control fired. Check the runner (is the package installed? is
a database reachable for the ones that need one?) before reading anything into
the subject.

**A CONTROL THAT CRASHED DID NOT FIRE, AND IS NOT COUNTED.** A plant fires only
when its target's tests RAN AND FAILED: pytest's exit status 1, a summary naming
``N failed`` and naming no error. A target that errored under the plant (a
fixture that could not set up, ``N errors``), failed to collect (a syntax error
or a broken import, exit 2), or hit anything else that is not a failed
assertion is reported **NOT A CONTROL (crashed)** -- distinctly from RED, and
distinctly from the green kind of NOT A CONTROL -- and fails the run. The first
form of this script read a non-zero exit as fired, so a plant that broke the
interpreter instead of the subject was reported as a control that worked: the
merge gate measured two such plants of its own reading "RED, as required -- 1
error". That failed OPEN, which is the one failure this project has never
accepted from an instrument; ``verdict`` below is the fix, and G17 holds it.

**A TARGET WHOSE TESTS ALL SKIP IS REPORTED "NOT A CONTROL", NOT UNMEASURED, AND
THAT IS THIS SCRIPT'S OWN LIMIT RATHER THAN A JUDGEMENT.** `_NOTHING_RAN` matches
"0 passed", "no tests ran" and "collected 0 items"; an all-skipped target prints
none of those -- it prints "8 skipped" -- so the run proceeds, the target stays
green with its subject broken, and the verdict is DEAD. That is what happens to
a database-backed control on a machine with no database. The exit status is 1
either way, so nothing goes falsely green; the word is simply the wrong one, and
it is recorded here rather than in a comment that promises otherwise. Read a
DEAD verdict on a database-backed control as "check whether you gave it a
database" first.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from _guarantees import GUARANTEES  # noqa: E402
from plant import planted, resolve  # noqa: E402


def source(*lines: str) -> str:
    """A block of source code, one argument per line.

    An anchor is frequently several lines long, and written as a single literal
    with escaped newlines it becomes a three-hundred-character line that nobody
    can read and no diff can review. Same string, legible.
    """
    return "\n".join(lines)


def guarantee_of(control_id: str) -> str:
    """The guarantee a control id names. ``G4/expired`` -> ``G4``.

    One guarantee can need more than one plant: two claims that fail in
    different code, planted together, would go red if EITHER were caught --
    which is the arrangement that lets one half sit unmeasured behind the
    other.
    """
    return control_id.split("/", 1)[0]


#: control id -> (test target, source file, anchor, replacement, what breaks)
CONTROLS: dict[str, tuple[str, str, str, str, str]] = {
    "G1": (
        "tests/test_guarantee_guard.py",
        "tests/test_guarantee_guard.py",
        "        elif name not in UNGUARANTEED_MODULES:",
        "        elif False:  # PLANTED: a module with no mark is accepted",
        "a test module carrying no guarantee mark stops being reported, which is "
        "the hole that hid 16 tests in one sibling repository and 21 in another "
        "-- skip or delete such a module and every gate stays green",
    ),
    "G2": (
        "tests/test_contract_is_generated.py",
        "scripts/generate_contract.py",
        '        f"That is {len(GUARANTEES)} guarantees. Every one of them has a fail control "',
        '        f"That is 2 guarantees. Every one of them has a fail control "  # PLANTED',
        "the published guarantee COUNT stops being derived and becomes a typed "
        "number, which is the shape that goes stale silently: the document keeps "
        "agreeing with itself while the registry moves underneath it",
    ),
    "G3/stored": (
        "tests/test_g3_no_plaintext_is_stored_or_rendered_twice.py",
        "store/records.py",
        "    return _write_credential(cursor, tenant_id, customer_id, secret, by=who, at=when)",
        "    return _write_credential(cursor, tenant_id, customer_id, secret, by=secret, at=when)"
        "  # PLANTED",
        "the plaintext password is written into a text column (set_by) beside the "
        "hash -- the column scan must find it whichever column it lands in",
    ),
    "G3/rendered": (
        "tests/test_g3_no_plaintext_is_stored_or_rendered_twice.py",
        "store/records.py",
        source(
            "    if row is None:",
            '        raise Refused(REFUSAL_TOKEN_UNKNOWN, "token", "no token of this operator '
            'matches.")',
            "    return as_uuid(row[0])",
        ),
        source(
            "    if row is None:",
            '        raise Refused(REFUSAL_TOKEN_UNKNOWN, "token", f"no token of this operator '
            'matches {presented}.")  # PLANTED',
            "    return as_uuid(row[0])",
        ),
        "the unknown-token refusal echoes the token presented, so a token typed at "
        "the wrong tenant is rendered a second time, in a log line",
    ),
    "G4/column": (
        "tests/test_g4_no_money_shaped_field_anywhere.py",
        "migrations/0001_tenants_customers_credentials_consent_and_rls.sql",
        "  phone        text        CHECK (phone IS NULL OR length(btrim(phone)) > 0),",
        source(
            "  phone        text        CHECK (phone IS NULL OR length(btrim(phone)) > 0),",
            "  fee_cents    integer,  -- PLANTED: a money-shaped column",
        ),
        "a money-shaped column is planted into the schema -- the brief's own positive "
        "control, fee_cents -- and the catalogue read must find it",
    ),
    "G4/field": (
        "tests/test_g4_no_money_shaped_field_anywhere.py",
        "store/records.py",
        source(
            "    sentence: str",
            "    means: str | None",
        ),
        source(
            "    sentence: str",
            "    means: str | None",
            "    balance_cents: int = 0  # PLANTED: a money field on the verification answer",
        ),
        "a money field is added to the verification answer; the dataclass walk "
        "derives the field set from the package, so this is caught the day it is added",
    ),
    # The four doors the JSON instrument never drove before the fix round, each
    # planted alone: the derived instrument must find a key on every one.
    "G4/json-create-account": (
        "tests/test_g4_no_money_shaped_field_anywhere.py",
        "store/records.py",
        source(
            '    return {"customer": str(customer_id), "email": address, "external_id": reference,',
            '            "acceptance": accepted}',
        ),
        source(
            '    return {"customer": str(customer_id), "email": address, "external_id": reference,',
            '            "acceptance": accepted, "fee_cents": 0}  # PLANTED',
        ),
        "a money key on create-account's output -- the door the L3 planted and found the old "
        "instrument green on",
    ),
    "G4/json-record-terms-acceptance": (
        "tests/test_g4_no_money_shaped_field_anywhere.py",
        "store/records.py",
        source(
            '    return {',
            '        "acceptance": str(acceptance_id),',
        ),
        source(
            '    return {',
            '        "acceptance": str(acceptance_id),',
            '        "tariff": "standard",  # PLANTED: a money-shaped key on the acceptance record',
        ),
        "a money-shaped key on record-terms-acceptance's output",
    ),
    "G4/json-confirm-email-change": (
        "tests/test_g4_no_money_shaped_field_anywhere.py",
        "store/records.py",
        '        "email_change": str(change_id),',
        '        "email_change": str(change_id),\n        "balance": 0,  # PLANTED',
        "a money-shaped key on confirm-email-change's output",
    ),
    "G4/json-consume-password-reset": (
        "tests/test_g4_no_money_shaped_field_anywhere.py",
        "store/records.py",
        '    written["credential_reset"] = str(token_id)\n    return written',
        '    written["credential_reset"] = str(token_id)\n'
        '    written["amount_minor"] = 0  # PLANTED\n    return written',
        "a money-shaped key on consume-password-reset's output -- the other door the L3 "
        "planted and found green",
    ),
    "G5": (
        "tests/test_g5_no_credential_is_answered_by_name.py",
        "store/records.py",
        "    if credential is None:\n        outcome = NO_CREDENTIAL",
        "    if credential is None:\n        outcome = WRONG_PASSWORD  # PLANTED",
        "a customer with no credential is answered WRONG_PASSWORD -- a silent false "
        "that says a password exists when none does, and loses the sentence that "
        "this is not 'no password required'",
    ),
    "G6/expiry": (
        "tests/test_g6_expired_and_used_tokens_are_refused_by_name.py",
        "tokens.py",
        "    return at >= expires_at",
        "    return False  # PLANTED: nothing ever expires",
        "the expiry derivation never fires, so a token issued for thirty minutes "
        "works forever",
    ),
    "G6/read-state": (
        "tests/test_g6_expired_and_used_tokens_are_refused_by_name.py",
        "store/records.py",
        "    state = parse_state(state).value",
        "    state = state  # PLANTED: the state read is trusted",
        "the locked read stops parsing the state it finds, so a row carrying 'expired' "
        "or a state this module does not have falls through to the spend and is refused "
        "as 'spent by another caller' -- the false sentence the unraisable round measured; "
        "the tests require the state's own name and an untouched row",
    ),
    "G6/used": (
        "tests/test_g6_expired_and_used_tokens_are_refused_by_name.py",
        "store/records.py",
        source(
            "    if state == TokenState.REDEEMED.value:",
            '        raise Refused(REFUSAL_TOKEN_ALREADY_USED, "token", f"used at '
            '{redeemed_at.isoformat()}.")',
        ),
        source(
            "    if state == TokenState.REDEEMED.value:",
            '        raise Refused(REFUSAL_TOKEN_UNKNOWN, "token", "no token of this operator '
            'matches.")  # PLANTED',
        ),
        "a token presented twice reads as unknown the second time, so a replay is "
        "indistinguishable from a typo in the log",
    ),
    "G7/force": (
        "tests/test_g7_rls_from_migration_0001.py",
        "migrations/0001_tenants_customers_credentials_consent_and_rls.sql",
        "ALTER TABLE customers FORCE  ROW LEVEL SECURITY;",
        "-- PLANTED: FORCE removed from customers",
        "one table ships without FORCE ROW LEVEL SECURITY. The coverage check reads "
        "the catalogue rather than a list of table names, so it finds this without "
        "anybody adding the table to anything",
    ),
    "G7/composite-key": (
        "tests/test_g7_rls_from_migration_0001.py",
        "migrations/0001_tenants_customers_credentials_consent_and_rls.sql",
        source(
            "  UNIQUE (tenant_id, token_sha256),",
            "  CONSTRAINT credential_resets_customer_in_tenant",
            "    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers (tenant_id, id) "
            "ON DELETE CASCADE",
        ),
        source(
            "  UNIQUE (tenant_id, token_sha256),",
            "  CONSTRAINT credential_resets_customer_in_tenant",
            "    FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE"
            "  -- PLANTED",
        ),
        "one customer reference loses its composite tenant key, so a raw insert as "
        "tenant A can name tenant B's customer -- the foreign-key check runs past the "
        "policy",
    ),
    "G7/install-step": (
        "tests/test_g7_rls_from_migration_0001.py",
        "scripts/ensure-app-role.py",
        source(
            '                sql.SQL("ALTER ROLE customer_account_app LOGIN PASSWORD {}").format(',
            "                    sql.Literal(password)",
            "                )",
        ),
        source(
            '                "ALTER ROLE customer_account_app LOGIN PASSWORD %s", (password,)'
            "  # PLANTED",
        ),
        "the install step goes back to a bind parameter in a utility statement, which "
        "PostgreSQL refuses -- the defect a sibling module shipped because nothing ran "
        "the script",
    ),
    "G8/immediate": (
        "tests/test_g8_an_email_change_takes_effect_only_when_confirmed.py",
        "store/records.py",
        source(
            "    (change_id,) = cursor.fetchone()",
            "    return {",
            '        "pending_email_change": str(change_id),',
        ),
        source(
            "    (change_id,) = cursor.fetchone()",
            '    cursor.execute("UPDATE customers SET email = %s WHERE tenant_id = %s AND id = %s",'
            "  # PLANTED",
            "                   (address, str(tenant_id), str(customer_id)))",
            "    return {",
            '        "pending_email_change": str(change_id),',
        ),
        "the address is rewritten when the change is STARTED, before the new address "
        "has confirmed anything -- the circular path: a reset would now go to an "
        "address nobody proved they hold",
    ),
    "G8/unauthorised": (
        "tests/test_g8_an_email_change_takes_effect_only_when_confirmed.py",
        "store/records.py",
        source(
            "    if not has_password and caller is None:",
            "        raise Refused(",
            '            REFUSAL_AUTHORISATION_MISSING, "by", "neither a password nor --by was '
            'given."',
            "        )",
        ),
        source(
            "    if not has_password and caller is None:",
            '        caller = "unstated"  # PLANTED: a change nobody authorised goes through',
        ),
        "an email change with neither the password nor a caller's authorisation is "
        "started anyway, with 'unstated' stored as who authorised it",
    ),
    "G8/tie": (
        "tests/test_g8_an_email_change_takes_effect_only_when_confirmed.py",
        "store/records.py",
        'TIEBREAK = ("created_at", "id")',
        'TIEBREAK = ("created_at",)  # PLANTED: no tiebreak',
        "the same plant as G11/tie, on the same line: the email history's order ends in "
        "the one tuple too, so eight changes confirmed in one transaction come back in "
        "heap order -- measured before this was built -- and the test requires id order",
    ),
    "G9": (
        "tests/test_g9_a_reset_goes_to_the_current_address.py",
        "store/records.py",
        '        "deliver_to": customer.email,',
        source(
            '        "deliver_to": (cursor.execute(  # PLANTED: deliver to the latest address',
            '            "SELECT new_email FROM pending_email_changes WHERE tenant_id = %s AND "',
            '            "customer_id = %s AND state = \'issued\'", (str(tenant_id), '
            "str(customer_id))) or cursor.fetchone() or (customer.email,))[0],",
        ),
        "the reset is delivered to the address of a pending, UNCONFIRMED email change "
        "-- the plausible defect 'deliver to the latest address', and exactly the "
        "circular path: whoever started a change to an address they control receives "
        "the reset there",
    ),
    "G10": (
        "tests/test_g10_histories_are_append_only_by_grant.py",
        "migrations/0001_tenants_customers_credentials_consent_and_rls.sql",
        source(
            "GRANT SELECT, INSERT ON",
            "  customer_email_changes, terms_acceptances, acceptance_channels",
        ),
        source(
            "GRANT SELECT, INSERT, UPDATE ON  -- PLANTED: the histories can be rewritten",
            "  customer_email_changes, terms_acceptances, acceptance_channels",
        ),
        "the grant on the three histories is widened to UPDATE, so an acceptance can "
        "be rewritten after the fact and 'append-only' is a comment",
    ),
    "G11/blank": (
        "tests/test_g11_consent_is_one_acceptance_itemised.py",
        "consent.py",
        "    if not isinstance(value, str) or not value.strip():",
        "    if not isinstance(value, str):  # PLANTED: a blank text is accepted",
        "a blank text shown is accepted, so an acceptance can record that nothing was "
        "shown -- a boolean in disguise",
    ),
    "G11/no-acceptance": (
        "tests/test_g11_consent_is_one_acceptance_itemised.py",
        "store/records.py",
        "        accepted = record_acceptance(cursor, tenant_id, customer_id, acceptance)",
        "        accepted = {}  # PLANTED: the account is created with no acceptance",
        "the account is created without its acceptance, so a customer exists who "
        "agreed to nothing",
    ),
    "G11/channel-clock": (
        "tests/test_g11_consent_is_one_acceptance_itemised.py",
        "store/records.py",
        "             acceptance.accepted_by, acceptance.accepted_at),",
        "             acceptance.accepted_by, acceptance.accepted_at.replace(second=59)),"
        "  # PLANTED: a second clock",
        "a channel written with its acceptance carries an instant of its own instead of the "
        "acceptance's -- two clocks for one consent",
    ),
    "G11/tie": (
        "tests/test_g11_consent_is_one_acceptance_itemised.py",
        "store/records.py",
        'TIEBREAK = ("created_at", "id")',
        'TIEBREAK = ("created_at",)  # PLANTED: no tiebreak',
        "the tiebreak column is dropped from the ONE tuple every history's order ends in, "
        "so eight acceptances sharing an instant come back in whatever order the heap gives "
        "-- the gate measured it stable and stated nowhere; the test requires id order",
    ),
    "G11/repeated": (
        "tests/test_g11_consent_is_one_acceptance_itemised.py",
        "cli.py",
        "        if name in out:",
        "        if False:  # PLANTED: the last --channel of a name wins, silently",
        "the door stops refusing a repeated channel name, so `--channel sms=A --channel "
        "sms=B` exits 0 and the consent row records B as the text shown -- the re-gate's "
        "measured shape, a false sentence in a consent record; the door tests require exit 3 "
        "by the published name",
    ),
    "G12/row-parameters": (
        "tests/test_g12_the_password_is_scrypt_with_stated_parameters.py",
        "passwords.py",
        source(
            "    parameters = credential.parameters",
            "    derived = hashlib.scrypt(",
            '        password.encode("utf-8"), salt=bytes.fromhex(credential.salt_hex), '
            "n=parameters.n,",
        ),
        source(
            "    parameters = SCRYPT  # PLANTED: the module's constants, not the row's",
            "    derived = hashlib.scrypt(",
            '        password.encode("utf-8"), salt=bytes.fromhex(credential.salt_hex), '
            "n=parameters.n,",
        ),
        "verification uses the module's constants instead of the row's parameters, so "
        "raising the parameters invalidates every existing credential",
    ),
    "G12/kdf": (
        "tests/test_g12_the_password_is_scrypt_with_stated_parameters.py",
        "passwords.py",
        source(
            "        raise Refused(",
            '            REFUSAL_KDF_UNKNOWN, "kdf",',
            '            f"{credential.kdf!r}; the one KDF this module has is {KDF!r}.",',
            "        )",
        ),
        source(
            "        raise ValueError(  # PLANTED: the bare raise the outside review measured",
            '            f"a credential with kdf {credential.kdf!r} cannot be verified here"',
            "        )",
        ),
        "a credential row carrying a KDF this module does not have raises a bare "
        "ValueError again instead of the named refusal, so both doors that check a "
        "password reach the shell as a traceback with no JSON and exit 1 -- the exit "
        "verify-password uses for 'not verified'; the door tests require exit 3 by name",
    ),
    "G12/minimum": (
        "tests/test_g12_the_password_is_scrypt_with_stated_parameters.py",
        "passwords.py",
        '    if len(value.encode("utf-8")) < MIN_PASSWORD_BYTES:',
        "    if False:  # PLANTED: no minimum",
        "the minimum length stops being enforced, so a one-character password is "
        "hashed and stored",
    ),
    "G13/luhn": (
        "tests/test_g13_nothing_real_in_the_tree.py",
        "tests/test_g13_nothing_real_in_the_tree.py",
        "    return total % 10 == 0",
        "    return False  # PLANTED: nothing is card-shaped",
        "the card sweep cannot fire on anything",
    ),
    "G13/allowlist": (
        "tests/test_g13_nothing_real_in_the_tree.py",
        "tests/test_g13_nothing_real_in_the_tree.py",
        "        if not any(rule.search(address) for rule in _ALLOWED_EMAIL)",
        "        if False  # PLANTED: every address is allowed",
        "the email sweep cannot fire on anything",
    ),
    "G13/tokens": (
        "tests/test_g13_nothing_real_in_the_tree.py",
        "tests/test_g13_nothing_real_in_the_tree.py",
        "        if is_upper and previous_was_lower and current:",
        "        if False:  # PLANTED: no split on a case transition",
        "a name hidden inside an identifier is not found",
    ),
    "G14": (
        "tests/test_g14_the_command_line_refuses_never_tracebacks.py",
        "cli.py",
        "    except Refused as refused:\n        print(json.dumps(_refusal(refused), indent=2))",
        "    except KeyboardInterrupt as refused:  # PLANTED: a Refused is no longer caught\n"
        "        print(json.dumps(_refusal(refused), indent=2))",
        "the boundary stops catching Refused, so every refusal is a traceback and exit 1",
    ),
    "G15": (
        "tests/test_g15_no_http_surface_and_nothing_is_sent.py",
        "cli.py",
        "import argparse\nimport dataclasses",
        "import argparse\nimport dataclasses\nimport smtplib  # PLANTED: a mail client",
        "a mail client is imported into the command line, and the AST walk must see it",
    ),
    "G16/pre-flight": (
        "tests/test_g16_the_fold_is_the_databases_and_0001_states_what_it_requires.py",
        "migrations/0001_tenants_customers_credentials_consent_and_rls.sql",
        "  IF provider = 'c' AND ctype IN ('C', 'POSIX') THEN",
        "  IF false THEN  -- PLANTED: the requirement is never judged",
        "the pre-flight's condition never holds, so 0001 applies on a C-collated database "
        "and Élodie@ and élodie@ become two accounts of one operator -- the test creates "
        "that database in the cluster and requires the named refusal",
    ),
    "G16/python-fold": (
        "tests/test_g16_the_fold_is_the_databases_and_0001_states_what_it_requires.py",
        "store/records.py",
        source(
            "    holder = _address_holder(cursor, tenant_id, address)",
            "    if holder == customer_id:",
        ),
        source(
            "    holder = _address_holder(cursor, tenant_id, address)",
            "    if address.lower() == load_customer(cursor, tenant_id, customer_id).email"
            ".lower():  # PLANTED: a second authority",
        ),
        "the gate's blocker, planted back: start_email_change judges 'unchanged' by "
        "Python's lower() while create_account judges by the database's, and the two "
        "disagree on İ on every libc measured -- one door refuses an address as yours, "
        "the next hands it to somebody else",
    ),
    "G17": (
        "tests/test_g17_a_crashed_control_is_not_a_control.py",
        "scripts/fail_controls.py",
        "    if red.returncode != _TESTS_FAILED or not _FAILED.search(summary) or "
        "_ERRORS.search(summary):",
        "    if False:  # PLANTED: any non-zero exit is a fired control",
        "the crash branch is removed, so a plant that broke the interpreter reads 'RED, as "
        "required' again -- the instrument fails open, which is what the gate measured",
    ),
}


def check_anchors() -> int:
    """Count every anchor. Zero or two is a dead control, and it is silent."""
    bad = 0
    for gid, (_target, path, anchor, _to, _why) in sorted(CONTROLS.items()):
        count = resolve(path).read_text().count(anchor)
        status = "ok" if count == 1 else "DEAD"
        if count != 1:
            bad += 1
        print(f"  {status:4}  {gid}  {path}  anchor appears {count}x")
    if bad:
        print(
            f"\n{bad} control(s) have no live anchor. An anchor that matches zero times "
            "plants nothing, and the control then reports green against unmodified "
            "source. Fix the anchors before trusting any result from this script."
        )
        return 1
    print(f"\nall {len(CONTROLS)} anchors live.")
    return 0


def _pytest(target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


#: ``"0 passed" in stdout`` was the first form of this in a sibling repository
#: and it was WRONG: "10 passed" contains it, so three live controls reported
#: UNMEASURED and the run said 14/17. A substring match confirms only that a
#: substring was present -- the rule this project already has, broken inside
#: the machinery built to enforce it.
_NOTHING_RAN = re.compile(r"(?<!\d)0 passed|no tests ran|collected 0 items")

#: pytest's exit status when tests ran and some failed. 2 is "interrupted" (a
#: collection error, a syntax error in a test module), 3 an internal error, 4
#: a usage error, 5 nothing collected -- none of those is a fired assertion.
_TESTS_FAILED = 1
_FAILED = re.compile(r"(?<!\d)\d+ failed")
_ERRORS = re.compile(r"(?<!\d)\d+ errors?(?!\w)")

FIRED = "FIRED"
GREEN = "GREEN"
CRASHED = "CRASHED"


def verdict(red: subprocess.CompletedProcess) -> tuple[str, str]:
    """What a planted run proves: ``FIRED`` (its tests ran and failed), ``GREEN``
    (nothing noticed the plant) or ``CRASHED`` (the plant broke the runner, not
    the subject -- which proves nothing about the subject either way).

    The three are judged from pytest's exit status AND its summary line, both:
    an exit of 1 with ``N failed`` and no ``N error(s)`` is the only shape that
    is a fired assertion. A crash can also exit 1 (a fixture error is ``1
    error`` at exit 1), which is why the status alone was never enough."""
    lines = red.stdout.strip().splitlines()
    summary = lines[-1] if lines else ""
    if red.returncode == 0:
        return GREEN, summary
    if red.returncode != _TESTS_FAILED or not _FAILED.search(summary) or _ERRORS.search(summary):
        return CRASHED, f"exit {red.returncode}, {summary!r}"
    return FIRED, summary


def run_control(gid: str) -> bool:
    target, path, anchor, replacement, why = CONTROLS[gid]
    print(f"\n=== {gid} — {GUARANTEES[guarantee_of(gid)]}")
    print(f"    plant: {path}")
    print(f"    breaks: {why}")

    green = _pytest(target)
    if green.returncode != 0:
        print(f"    UNMEASURED: {target} is already failing before anything was planted.")
        print(green.stdout[-1500:])
        return False
    if _NOTHING_RAN.search(green.stdout):
        print(f"    UNMEASURED: {target} ran no tests, so nothing here can go red.")
        print(green.stdout[-800:])
        return False

    with planted(path, anchor, replacement):
        red = _pytest(target)

    tail = [ln for ln in red.stdout.splitlines() if ln.startswith(("FAILED", "ERROR"))]
    outcome, summary = verdict(red)
    if outcome == GREEN:
        print(f"    NOT A CONTROL: {target} stayed GREEN with its subject broken.")
        return False
    if outcome == CRASHED:
        print(f"    NOT A CONTROL (crashed): {target} did not run to a failed assertion under "
              f"the plant — {summary}. A run that crashed proves nothing about the subject.")
        for line in tail[:6]:
            print(f"      {line}")
        print(red.stdout[-600:] if not tail else "")
        return False
    print(f"    RED, as required — {summary}")
    for line in tail[:6]:
        print(f"      {line}")
    return True


def main(argv: list[str]) -> int:
    if "--anchors" in argv:
        return check_anchors()

    named = [a for a in argv if not a.startswith("-")]
    wanted = [c for c in sorted(CONTROLS) if c in named or guarantee_of(c) in named]
    unknown = [
        a for a in named
        if a not in CONTROLS and a not in {guarantee_of(c) for c in CONTROLS}
    ]
    if unknown:
        print(f"no such control: {', '.join(unknown)}")
        return 2
    wanted = wanted or sorted(CONTROLS)

    missing = sorted(set(GUARANTEES) - {guarantee_of(c) for c in CONTROLS})
    if missing:
        print(
            f"registered guarantees with no fail-control: {', '.join(missing)}. "
            "Every guarantee is proven able to fail, or it is not a guarantee."
        )
        return 1

    if check_anchors():
        return 1

    results = {gid: run_control(gid) for gid in wanted}
    dead = [gid for gid, ok in results.items() if not ok]
    print(f"\n{len(results) - len(dead)}/{len(results)} controls fired.")
    if dead:
        print(f"DEAD CONTROLS: {', '.join(dead)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
