"""The customer: a stable id, an email that is an attribute on it, and the
rules every text value is held to before it is stored.

**THE EMAIL IS NOT THE KEY.** A customer has a stable id; the email is unique
per operator and CAN CHANGE, which is what makes "change email" and "forgot
password" both possible at once: a reset goes to the current address, and a
change is confirmed at the new one. An account keyed on the email is orphaned
the first time it changes.

**THE ADDRESS RULE IS COPIED, NOT INVENTED.** An ``@`` with text on both sides,
judged on the FIRST ``@`` -- an address carrying two is accepted -- the rule the
sibling pass module ships for a holder's address, and the same CHECK the
migration carries so a raw write cannot store what the module refuses. Nothing
more is checked, because nothing more can be checked without sending mail.
Uniqueness is compared WITHOUT REGARD TO CASE: ``Alice@example.com`` and
``alice@example.com`` are one customer, because mail is delivered to one
mailbox and two accounts behind it would make a reset ambiguous. The address is
stored as given.

**THE FOLD IS THE DATABASE'S, AND NOTHING HERE FOLDS.** "Without regard to
case" means ``lower(email)`` under the collation ``customers.email`` carries,
which is the expression the unique index is on and the one every door asks
(``records._address_holder``). This module once carried a Python ``lower()``
beside it with a docstring saying the two "must agree byte for byte"; they
were measured to disagree on 28 code points on CI's own database, 8 on macOS
and 1,407 under a C locale, plus Python's Final_Sigma rule, and one door
refused an address as "unchanged" that the next door then gave to a second
customer. So there is ONE fold, the store's, and the store states what it
requires of it: migration 0001 refuses to apply, by name, on a database whose
default collation folds ASCII only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from customer_account.findings import (
    REFUSAL_EMAIL_MALFORMED,
    REFUSAL_FIELD_BLANK,
    REFUSAL_INSTANT_MALFORMED,
    REFUSAL_TEXT_HAS_CONTROL_CHARACTERS,
    Refused,
)


def require_text(value: object, field: str) -> str:
    """A non-blank, one-line string, stripped -- or a refusal naming the field.

    Control characters are refused rather than stored: a name or a who-did-this
    value with a newline in it breaks the log line it is later read from.
    """
    if not isinstance(value, str):
        raise Refused(REFUSAL_FIELD_BLANK, field, f"{field} must be text, not {value!r}.")
    text = value.strip()
    if not text:
        raise Refused(REFUSAL_FIELD_BLANK, field, f"{field} is blank.")
    if any(ord(ch) < 32 or ch == "\x7f" for ch in text):
        raise Refused(
            REFUSAL_TEXT_HAS_CONTROL_CHARACTERS, field,
            f"{field} carries a control character.",
        )
    return text


def optional_text(value: object, field: str) -> str | None:
    """``None`` stays ``None``; anything else is held to ``require_text``."""
    if value is None:
        return None
    return require_text(value, field)


def require_email(value: object, field: str = "email") -> str:
    """An ``@`` with something before it and something after it -- judged on
    the FIRST ``@``, so an address carrying two is accepted, and nothing more
    is checked (a quoted local part may carry one, and nothing more can be
    checked without sending mail). The migration's CHECK on ``customers.email``
    tests the same position of the same character."""
    text = require_text(value, field)
    at = text.find("@")
    if at < 1 or at >= len(text) - 1:
        raise Refused(REFUSAL_EMAIL_MALFORMED, field, f"{field} is {text!r}.")
    return text


def require_aware(value: object, field: str) -> datetime:
    """An instant WITH an offset. A naive one would be read as the running
    machine's local time, which is a property of the server."""
    if not isinstance(value, datetime):
        raise Refused(REFUSAL_INSTANT_MALFORMED, field, f"{field} must be an instant.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise Refused(REFUSAL_INSTANT_MALFORMED, field, f"{field} carries no offset.")
    return value


@dataclass(frozen=True)
class Customer:
    """A customer as the store holds it. No credential here: the credential is
    its own row, and its absence is its own named state (``findings``)."""

    id: UUID
    tenant_id: UUID
    email: str
    external_id: str | None
    name: str | None
    phone: str | None
    created_at: datetime
