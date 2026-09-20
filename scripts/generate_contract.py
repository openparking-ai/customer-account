#!/usr/bin/env python3
"""Generate docs/CONTRACT.md from the registries, and check it has not drifted.

    python scripts/generate_contract.py            # write the document
    python scripts/generate_contract.py --check    # fail if it would change

**EVERY MARKED BLOCK IS DERIVED.** The guarantees come from
``tests/_guarantees.py``; the refusal codes and the verification outcomes from
``findings.py``; the consent channels from the enum that implements them and
the orders the two histories are read in from ``records.ACCEPTANCE_ORDER``
and ``records.EMAIL_CHANGE_ORDER``, both derived from the one
``records.TIEBREAK``; the password parameters from ``passwords.SCRYPT``; the
command line from the parser itself, so a command added without being
published is caught; and what
the store REQUIRES of its database from the migration's own pre-flight -- the
``RAISE EXCEPTION`` sentences of ``0001``, read from the file, so the
requirement the installer meets is the one the migration enforces. A number
or a sentence edited by hand turns ``--check`` red.

**AND GENERATION IS NOT VERIFICATION.** Moving a sentence from a document into a
template does not stop it being hand-written -- everywhere except the holes it is
still prose nobody checks. A generated block asserts only what it DERIVES from
its values. So ``tests/test_contract_is_generated.py`` plants values that
contradict the prose and requires the prose to change; anything that survives
that plant is a fixed string, and a fixed string is marked as design
documentation rather than left looking measured.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from _guarantees import GUARANTEES, guarantee_ids  # noqa: E402
from customer_account.cli import (  # noqa: E402
    DSN_ENV,
    EXIT_CONFIGURATION,
    EXIT_DONE,
    EXIT_NOT_VERIFIED,
    EXIT_REFUSED_REQUEST,
    _parser,
)
from customer_account.consent import Channel  # noqa: E402
from customer_account.findings import NOT_VERIFIED_MEANS, REFUSALS, VERIFICATIONS  # noqa: E402
from customer_account.passwords import (  # noqa: E402
    KDF,
    MIN_PASSWORD_BYTES,
    PASSWORD_ENV,
    SALT_BYTES,
    SCRYPT,
)
from customer_account.store.postgres import APP_ROLE, TENANT_SETTING  # noqa: E402
from customer_account.store.records import (  # noqa: E402
    ACCEPTANCE_ORDER,
    EMAIL_CHANGE_ORDER,
    TIEBREAK,
)
from customer_account.tokens import TokenState  # noqa: E402

DOC = ROOT / "docs" / "CONTRACT.md"
MIGRATION = next(iter(sorted((ROOT / "migrations").glob("0001_*.sql"))))
BEGIN = "<!-- GENERATED:{name} -->"
END = "<!-- END:{name} -->"


def block_guarantees() -> str:
    rows = ["| id | what is guaranteed |", "|---|---|"]
    for gid in guarantee_ids():
        rows.append(f"| **{gid}** | {GUARANTEES[gid]} |")
    rows.append("")
    rows.append(
        f"That is {len(GUARANTEES)} guarantees. Every one of them has a fail control "
        "that has been proven to fire, and the count above is derived from the "
        "registry rather than typed here."
    )
    return "\n".join(rows)


def block_refusals() -> str:
    rows = ["| code | when, and what to do about it |", "|---|---|"]
    for code, sentence in sorted(REFUSALS.items()):
        rows.append(f"| `{code}` | {sentence} |")
    rows.append("")
    rows.append(
        f"That is {len(REFUSALS)} refusals, every one raised somewhere in the package and "
        "none raised anywhere that is not here (a test reads the raise sites from the AST)."
    )
    return "\n".join(rows)


def block_verifications() -> str:
    rows = ["| outcome | what it means |", "|---|---|"]
    for code, sentence in VERIFICATIONS.items():
        rows.append(f"| `{code}` | {sentence} |")
    rows.append("")
    rows.append(f"Every outcome but the first carries this sentence: *{NOT_VERIFIED_MEANS}*")
    return "\n".join(rows)


def block_password() -> str:
    return "\n".join([
        f"- **KDF:** `{KDF}`, from the standard library (`hashlib.scrypt`); no dependency.",
        f"- **Parameters written today:** n = {SCRYPT.n} (2^{SCRYPT.n.bit_length() - 1}), "
        f"r = {SCRYPT.r}, p = {SCRYPT.p}, dklen = {SCRYPT.dklen}; salt {SALT_BYTES} bytes "
        "from the CSPRNG. Measured by `scripts/measure_scrypt.py`, not chosen; stored "
        "beside every hash, so a row written under other values still verifies and "
        "raising them invalidates nothing.",
        f"- **The one rule on a password:** at least {MIN_PASSWORD_BYTES} bytes of UTF-8. "
        "No character classes, no dictionary.",
        f"- **Where a password is read from:** the environment variable `{PASSWORD_ENV}`, "
        "never an argument.",
        f"- **A token's typed states:** {', '.join('`' + s.value + '`' for s in TokenState)}; "
        "`expired` is derived from `expires_at` and cannot be typed.",
    ])


def block_channels() -> str:
    lines = ["One acceptance, itemised. The channels consent may be recorded for, by name:", ""]
    for channel in Channel:
        lines.append(f"- `{channel.value}`")
    lines += ["", f"That is {len(Channel)} channels. A third is a migration and a contract "
              "change, not a value somebody types."]
    lines += ["", order_sentence("Acceptances accumulate and", "acceptances", ACCEPTANCE_ORDER,
                                 "the row current for a version is the latest")]
    return "\n".join(lines)


def order_sentence(subject: str, noun: str, order: tuple[str, ...], rule: str) -> str:
    """ONE sentence for every history read oldest first: the order it is read
    in, what its first column means, and that a tie on the instant is broken
    by the last column -- deterministically, and arbitrarily. Both histories
    render through here, so the contract says for one exactly what it says
    for the other, and both orders end in the one ``TIEBREAK``."""
    assert order[-len(TIEBREAK):] == TIEBREAK, (order, TIEBREAK)
    columns = ", ".join(f"`{column}`" for column in order)
    return (
        f"{subject} are read oldest first in the order {columns}: {rule} by `{order[0]}`, "
        f"and two {noun} sharing an instant are ordered by `{order[-1]}` -- deterministically, "
        "the same way on every read, but ARBITRARILY: that order means nothing."
    )


def block_email_history() -> str:
    return order_sentence("Email changes accumulate and", "changes", EMAIL_CHANGE_ORDER,
                          "the row for the change now in effect is the latest")


#: One ``RAISE EXCEPTION`` in the migration: its message, written as one or
#: more adjacent string literals, followed by its USING clause.
_RAISE = re.compile(r"RAISE EXCEPTION\s+((?:'(?:[^']|'')*'\s*)+)USING", re.S)


def migration_refusals() -> list[tuple[str, str]]:
    """Every refusal the migration's pre-flight can raise, as (name, sentence),
    read from the migration file -- so the requirement published here is the
    one the migration enforces, and one edited without the other is caught."""
    out = []
    for literals in _RAISE.findall(MIGRATION.read_text()):
        parts = re.findall(r"'((?:[^']|'')*)'", literals)
        message = "".join(parts).replace("''", "'")
        name, _colon, sentence = message.partition(": ")
        out.append((name, sentence.strip()))
    return out


def block_install() -> str:
    rows = ["| the migration refuses, by name | when |", "|---|---|"]
    for name, sentence in migration_refusals():
        rows.append(f"| `{name}` | {sentence} |")
    rows += [
        "",
        f"That is {len(rows) - 2} named refusals in `{MIGRATION.name}`'s pre-flight, read from "
        "the file. Each is raised BEFORE anything is created, inside the migration's own "
        "transaction, so a refused apply leaves the database as it found it. The requirement "
        "is an install requirement and not a caveat: `customers.email` carries no collation of "
        "its own, so the fold that makes one address one account is the database's default "
        "collation, and the pre-flight judges exactly that.",
    ]
    return "\n".join(rows)


def block_commands() -> str:
    """Derived from argparse itself: every command and every option it takes."""
    parser = _parser()
    commands = {
        name: sub for action in parser._actions
        if isinstance(action, argparse.__dict__["_SubParsersAction"])
        for name, sub in action.choices.items()
    }
    rows = ["| command | options | what it does |", "|---|---|---|"]
    for name, sub in commands.items():
        options = [
            opt for action in sub._actions for opt in action.option_strings
            if opt.startswith("--") and opt != "--help"
        ]
        help_ = next(
            (choice.help for action in parser._actions
             if isinstance(action, argparse.__dict__["_SubParsersAction"])
             for choice in action._choices_actions if choice.dest == name),
            "",
        )
        rows.append(f"| `{name}` | {' '.join('`' + o + '`' for o in options)} | {help_} |")
    rows += [
        "",
        f"That is {len(commands)} commands, every one against the store (`{DSN_ENV}`), and "
        "none an HTTP surface. The application connects as the role "
        f"`{APP_ROLE}` and sets `{TENANT_SETTING}` per transaction.",
        "",
        f"Exit status: {EXIT_DONE} done or verified; {EXIT_NOT_VERIFIED} not verified "
        f"(`verify-password` only); {EXIT_CONFIGURATION} the machine's configuration, one "
        f"sentence on stderr; {EXIT_REFUSED_REQUEST} the request was refused, as JSON.",
    ]
    return "\n".join(rows)


BLOCKS = {
    "guarantees": block_guarantees,
    "refusals": block_refusals,
    "verifications": block_verifications,
    "password": block_password,
    "channels": block_channels,
    "email_history": block_email_history,
    "commands": block_commands,
    "install": block_install,
}


def render(template: str) -> str:
    out = template
    for name, builder in BLOCKS.items():
        begin, end = BEGIN.format(name=name), END.format(name=name)
        if begin not in out or end not in out:
            raise SystemExit(f"docs/CONTRACT.md has no {begin} ... {end} block")
        head, rest = out.split(begin, 1)
        _stale, tail = rest.split(end, 1)
        out = f"{head}{begin}\n{builder()}\n{end}{tail}"
    return out


def main(argv: list[str]) -> int:
    current = DOC.read_text()
    generated = render(current)
    if "--check" in argv:
        if current != generated:
            print(
                "docs/CONTRACT.md does not match its generator. A number or a "
                "sentence inside a generated block was edited by hand, or the "
                "registry it comes from moved. Run this script with no arguments."
            )
            return 1
        print("docs/CONTRACT.md is the generated one.")
        return 0
    DOC.write_text(generated)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
