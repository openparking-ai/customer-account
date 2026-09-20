"""The command line: the account, the credential, the two recovery paths and
the consent, against the store. No HTTP surface, no screens: the house
pattern, and the standalone claim in one sentence.

    customer-account create-account --tenant T --email a@example.com [--external-id R]
        [--name N] [--phone P] --by WHO --at INSTANT
        --terms-version v3 --terms-shown terms.txt
        [--channel email=email.txt] [--channel sms=sms.txt]
    customer-account show-account --tenant T (--customer ID | --email a@example.com)
    customer-account show-acceptances --tenant T --customer ID
    customer-account record-terms-acceptance --tenant T --customer ID --by WHO --at INSTANT
        --terms-version v4 --terms-shown terms.txt [--channel NAME=FILE ...]
    customer-account set-password --tenant T --customer ID --by WHO --at INSTANT
    customer-account verify-password --tenant T --customer ID
    customer-account start-email-change --tenant T --customer ID --new-email b@example.com
        --valid-minutes M --at INSTANT [--by WHO]
    customer-account confirm-email-change --tenant T --token TOKEN --at INSTANT
    customer-account start-password-reset --tenant T --customer ID --valid-minutes M
        --by WHO --at INSTANT
    customer-account consume-password-reset --tenant T --token TOKEN --at INSTANT

**A PASSWORD IS READ FROM THE ENVIRONMENT, NEVER FROM AN ARGUMENT**
(``CUSTOMER_ACCOUNT_PASSWORD``): arguments are visible in ``ps`` to every user
on the machine and land in the shell's history. ``set-password`` and
``consume-password-reset`` read the NEW password from it; ``verify-password``
reads the password to check; ``start-email-change`` reads it as the
customer's authorisation -- and where ``--by`` is given instead, the caller's
authorisation is what is stored, and giving both is refused by name.

**THE TOKEN IS PRINTED ONCE, BY THE CALL THAT MINTED IT, AND BY NOTHING
ELSE.** ``start-email-change`` and ``start-password-reset`` print it, with
``deliver_to``: the new address for a change, the customer's CURRENT address
for a reset -- read from the row, never accepted as an argument. This module
sends nothing; delivering it is the caller's.

Exit status: 0 done, or verified; 1 not verified (``verify-password`` only:
a wrong password, or NO CREDENTIAL -- answered by name, and the JSON says
that is not "no password required"); 2 the machine's configuration (a
sentence on stderr: no DSN, a database that does not connect or is not
migrated, a role without its grants); 3 the request was refused.

**A REFUSAL IS RENDERED, NEVER A TRACEBACK.** Every ``Refused`` the module
raises reaches this boundary and is printed as ``{"refused": code, "field":
..., "detail": ...}`` with exit 3. What the libraries this boundary calls can
raise is mapped here too: a text file that cannot be read (``_text_file``), an
instant that does not parse or carries no offset (``_at``), a whole number
that is not one. What the database driver raises that the module did not name
is the machine's configuration: one sentence on stderr naming the SQLSTATE,
exit 2 -- the LAST resort, after every named refusal has had its chance.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import stat
import sys
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from customer_account.consent import build_acceptance
from customer_account.findings import (
    REFUSAL_DOCUMENT_UNREADABLE,
    REFUSAL_FIELD_BLANK,
    REFUSAL_INSTANT_MALFORMED,
    Refused,
)
from customer_account.identity import require_aware
from customer_account.passwords import PASSWORD_ENV

DSN_ENV = "CUSTOMER_ACCOUNT_DSN"
EXIT_DONE = 0
EXIT_NOT_VERIFIED = 1
EXIT_CONFIGURATION = 2
EXIT_REFUSED_REQUEST = 3


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {k: _plain(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(v) for v in value]
    return value


def _print(value: Any) -> None:
    print(json.dumps(_plain(value), indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="customer-account", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def store(name: str, help_: str) -> argparse.ArgumentParser:
        s = sub.add_parser(name, help=help_)
        s.add_argument("--tenant", required=True, type=UUID, help="the tenant's uuid")
        return s

    def acceptance(s: argparse.ArgumentParser) -> None:
        s.add_argument("--terms-version", help="the version of the terms shown")
        s.add_argument("--terms-shown", help="a text file: the terms, in the words shown")
        s.add_argument("--channel", action="append", default=[], metavar="NAME=FILE",
                       help="a channel consented to (email, sms) and a text file with the "
                            "words shown for it; repeatable")

    s = store("create-account", "the customer row and its first terms acceptance, together")
    s.add_argument("--email", required=True)
    s.add_argument("--external-id", help="the operator's own reference; optional")
    s.add_argument("--name")
    s.add_argument("--phone")
    s.add_argument("--by", required=True, help="who accepted the terms: the customer, or who "
                   "recorded it for them")
    s.add_argument("--at", required=True, help="when, as an ISO instant with an offset")
    acceptance(s)

    s = store("show-account", "read an account; renders no hash, no salt, no token")
    s.add_argument("--customer", type=UUID, help="the customer's uuid")
    s.add_argument("--email", help="or the customer's address")

    s = store("show-acceptances", "every acceptance the customer has made, texts included")
    s.add_argument("--customer", required=True, type=UUID)

    s = store("record-terms-acceptance", "a later acceptance, when the terms change")
    s.add_argument("--customer", required=True, type=UUID)
    s.add_argument("--by", required=True)
    s.add_argument("--at", required=True)
    acceptance(s)

    s = store("set-password", f"set or replace the credential; the password is read from "
              f"{PASSWORD_ENV}")
    s.add_argument("--customer", required=True, type=UUID)
    s.add_argument("--by", required=True, help="who decided a password exists now")
    s.add_argument("--at", required=True)

    s = store("verify-password", f"check the password in {PASSWORD_ENV}: exit 0 verified, "
              "1 not -- a wrong password or no credential, each by name")
    s.add_argument("--customer", required=True, type=UUID)

    s = store("start-email-change", "mint the token the new address presents back; authorised "
              f"by the current password in {PASSWORD_ENV} or by --by, exactly one")
    s.add_argument("--customer", required=True, type=UUID)
    s.add_argument("--new-email", required=True)
    s.add_argument("--valid-minutes", help="how many minutes the token may wait; stated, never "
                   "defaulted")
    s.add_argument("--at", required=True)
    s.add_argument("--by", help="the caller's explicit authorisation, stored as such")

    s = store("confirm-email-change", "the new address presents the token: the change takes "
              "effect now")
    s.add_argument("--token", required=True)
    s.add_argument("--at", required=True)

    s = store("start-password-reset", "mint the token the CURRENT address receives; it resets "
              "a password that exists")
    s.add_argument("--customer", required=True, type=UUID)
    s.add_argument("--valid-minutes", help="how many minutes the token may wait; stated, never "
                   "defaulted")
    s.add_argument("--by", required=True, help="who issued it")
    s.add_argument("--at", required=True)

    s = store("consume-password-reset", "present the reset token with the new password in "
              f"{PASSWORD_ENV}")
    s.add_argument("--token", required=True)
    s.add_argument("--at", required=True)
    return p


# ---- the boundary: what the libraries raise, rendered as refusals ----------


def _at(text: str, option: str = "--at") -> datetime:
    """An ISO instant WITH an offset, or a refusal naming the option and the
    value."""
    try:
        return require_aware(datetime.fromisoformat(text), option)
    except (TypeError, ValueError) as exc:
        raise Refused(
            REFUSAL_INSTANT_MALFORMED, option,
            f"{option} must be an ISO instant with an offset, such as "
            f"2026-06-01T09:00:00-06:00, not {text!r}: {exc}",
        ) from None


def _whole_number(text: str | None, option: str) -> int | None:
    """A whole number, or ``None`` when the option was not given (the module
    refuses an absent window by name), or a refusal naming the option."""
    if text is None:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        raise Refused(
            REFUSAL_FIELD_BLANK, option, f"{option} must be a whole number, not {text!r}."
        ) from None


def _text_file(path: str | None, option: str) -> str | None:
    """The text at ``path``, with a file the boundary cannot read refused by
    name -- never raised. ``None`` when the option was not given, so the
    module refuses the absence by its own name.

    THE CHECK AND THE READ ARE THE SAME FILE: the path is resolved once, by
    ``os.open`` with ``O_NONBLOCK``; ``fstat`` on that descriptor says whether
    it is a regular file, and the bytes are read from the same descriptor. A
    check on the name and a read on the name is a race whatever the check
    says (the sibling pass module measured a writer swapping the file for a
    named pipe between the two); a check on the descriptor is not.
    """
    if path is None:
        return None
    try:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except FileNotFoundError:
            raise Refused(
                REFUSAL_DOCUMENT_UNREADABLE, option,
                f"{option} {path!r} could not be read: it does not exist.",
            ) from None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise Refused(
                    REFUSAL_DOCUMENT_UNREADABLE, option,
                    f"{option} {path!r} could not be read: it is not a regular file "
                    f"(a directory, a device, a pipe or a socket).",
                )
            handle = os.fdopen(fd, "r", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            return handle.read()
    except (OSError, ValueError) as exc:
        raise Refused(
            REFUSAL_DOCUMENT_UNREADABLE, option,
            f"{option} {path!r} could not be read: {exc}",
        ) from None


def _channels(pairs: list[str]) -> dict[str, str | None]:
    """``NAME=FILE`` pairs into channel -> text shown. A pair without ``=`` is
    refused naming the option; an unknown NAME is refused by the module."""
    out: dict[str, str | None] = {}
    for pair in pairs:
        name, sep, path = pair.partition("=")
        if not sep or not name:
            raise Refused(
                REFUSAL_FIELD_BLANK, "--channel",
                f"--channel takes NAME=FILE, not {pair!r}.",
            )
        out[name] = _text_file(path, f"--channel {name}")
    return out


def _acceptance(args: argparse.Namespace, at: datetime):
    return build_acceptance(
        terms_version=args.terms_version,
        terms_shown=_text_file(args.terms_shown, "--terms-shown"),
        accepted_by=args.by,
        accepted_at=at,
        channels=_channels(args.channel),
    )


def _refusal(refused: Refused) -> dict[str, Any]:
    """The JSON refusal the operator reads -- THE ONE PLACE a ``Refused``
    becomes output."""
    return {"refused": refused.code, "field": refused.field, "detail": refused.detail}


def _values_that_start_with_a_dash(parser: argparse.ArgumentParser, argv: list[str]) -> list[str]:
    """``--name -x`` reaches the MODULE, not argparse's usage error: where an
    option that takes one value is followed by a token that starts with ``-``
    and is not itself an option of that command, the two are joined as
    ``--option=value``, which argparse always accepts. Copied from the sibling
    pass module, where an operator found the third shape."""
    commands = {
        name: sub for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
        for name, sub in action.choices.items()
    }
    sub = commands.get(argv[0]) if argv else None
    if sub is None:
        return argv
    options = {opt for action in sub._actions for opt in action.option_strings}
    takes_one = {
        opt for action in sub._actions if action.nargs in (None, 1)
        and not isinstance(action, argparse._StoreConstAction)
        for opt in action.option_strings
    }
    joined: list[str] = []
    skip = False
    for i, token in enumerate(argv):
        if skip:
            skip = False
            continue
        following = argv[i + 1] if i + 1 < len(argv) else None
        if (
            token in takes_one and following is not None
            and following.startswith("-") and following not in options
        ):
            joined.append(f"{token}={following}")
            skip = True
        else:
            joined.append(token)
    return joined


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(_values_that_start_with_a_dash(parser, argv))
    try:
        return _run(args)
    except Refused as refused:
        print(json.dumps(_refusal(refused), indent=2))
        return EXIT_REFUSED_REQUEST


#: What a SQLSTATE class says about WHOSE problem it is, in the operator's
#: words. Derived from the class digits the standard defines, not from a list
#: of the errors somebody has met; every class not named here is the last line.
_SQLSTATE_CLASSES = {
    "08": "the connection to the database failed",
    "28": "the database refused the login",
    "3D": "the database named does not exist",
    "40": "the database rolled this command back to break a deadlock or a serialization "
          "failure; nothing was written -- run it again",
    "42": "the database is not set up for this command (a missing table or function, or a "
          "role without its grants): the machine's configuration, not the request",
    "53": "the database is out of a resource (connections, disk, memory)",
    "57": "the database is shutting down or cancelled the command",
}


def _driver_sentence(exc: Exception) -> str:
    """One line for a database error the store did not name: what class of
    problem it is, the driver's class and SQLSTATE, the first line of its
    message. The DSN is never in it."""
    state = getattr(exc, "sqlstate", None) or "?"
    what = _SQLSTATE_CLASSES.get(state[:2], "the database could not run this command")
    message = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
    return f"{what}: {type(exc).__name__} (SQLSTATE {state}): {message}"


def _run(args: argparse.Namespace) -> int:
    from customer_account.store import records
    from customer_account.store.postgres import connect, tenant

    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        print(f"{DSN_ENV} is not set.", file=sys.stderr)
        return EXIT_CONFIGURATION
    import psycopg

    try:
        connection = connect(dsn)
    except psycopg.Error as exc:
        # Configuration, not a refusal of the request: one sentence, exit 2,
        # like the unset DSN above. The DSN itself is not echoed.
        print(f"{DSN_ENV} did not connect: {exc}".strip(), file=sys.stderr)
        return EXIT_CONFIGURATION
    connection.autocommit = False
    password = os.environ.get(PASSWORD_ENV)
    try:
        with tenant(connection, args.tenant) as cursor:
            if args.command == "create-account":
                at = _at(args.at)
                out: Any = records.create_account(
                    cursor, args.tenant, email=args.email, external_id=args.external_id,
                    name=args.name, phone=args.phone, at=at, acceptance=_acceptance(args, at),
                )
            elif args.command == "show-account":
                if args.customer is None and args.email is None:
                    raise Refused(REFUSAL_FIELD_BLANK, "--customer",
                                  "give --customer or --email.")
                customer_id = (args.customer if args.customer is not None
                               else records.find_customer_by_email(cursor, args.tenant,
                                                                   args.email).id)
                out = records.show_account(cursor, args.tenant, customer_id)
            elif args.command == "show-acceptances":
                out = records.show_acceptances(cursor, args.tenant, args.customer)
            elif args.command == "record-terms-acceptance":
                at = _at(args.at)
                out = records.record_acceptance(cursor, args.tenant, args.customer,
                                                _acceptance(args, at))
            elif args.command == "set-password":
                out = records.set_password(cursor, args.tenant, args.customer, password,
                                           by=args.by, at=_at(args.at))
            elif args.command == "verify-password":
                verification = records.verify_password(cursor, args.tenant, args.customer,
                                                       password)
                connection.rollback()
                _print(verification)
                return EXIT_DONE if verification.verified else EXIT_NOT_VERIFIED
            elif args.command == "start-email-change":
                out = records.start_email_change(
                    cursor, args.tenant, args.customer, args.new_email,
                    valid_minutes=_whole_number(args.valid_minutes, "--valid-minutes"),
                    at=_at(args.at), password=password, by=args.by,
                )
            elif args.command == "confirm-email-change":
                out = records.confirm_email_change(cursor, args.tenant, args.token,
                                                   at=_at(args.at))
            elif args.command == "start-password-reset":
                out = records.start_password_reset(
                    cursor, args.tenant, args.customer,
                    valid_minutes=_whole_number(args.valid_minutes, "--valid-minutes"),
                    by=args.by, at=_at(args.at),
                )
            elif args.command == "consume-password-reset":
                out = records.consume_password_reset(cursor, args.tenant, args.token, password,
                                                     at=_at(args.at))
            else:  # pragma: no cover - argparse refuses unknown commands
                raise SystemExit(2)
        connection.commit()
        _print(out)
        return EXIT_DONE
    except Refused:
        connection.rollback()
        raise
    except psycopg.Error as exc:
        # THE LAST RESORT, deliberately after Refused: a driver error the store
        # did not turn into a named refusal is one sentence with its SQLSTATE,
        # exit 2, never a traceback -- and never a refusal of the request's
        # content, because nothing about the content was judged.
        connection.rollback()
        print(_driver_sentence(exc), file=sys.stderr)
        return EXIT_CONFIGURATION
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
