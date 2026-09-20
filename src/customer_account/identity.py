"""The customer: a stable id, an email that is an attribute on it, and the
rules every text value is held to before it is stored.

**THE EMAIL IS NOT THE KEY.** A customer has a stable id; the email is unique
per operator and CAN CHANGE, which is what makes "change email" and "forgot
password" both possible at once: a reset goes to the current address, and a
change is confirmed at the new one. An account keyed on the email is orphaned
the first time it changes.

**THE ADDRESS RULE IS COPIED, NOT INVENTED.** One ``@`` with text on both sides
-- the rule the sibling pass module ships for a holder's address, and the same
CHECK the migration carries so a raw write cannot store what the module refuses.
Nothing more is checked, because nothing more can be checked without sending
mail. Uniqueness is compared WITHOUT REGARD TO CASE: ``Alice@example.com`` and
``alice@example.com`` are one customer, because mail is delivered to one
mailbox and two accounts behind it would make a reset ambiguous. The address is
stored as given.
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
    """One ``@`` with something before it and something after it. The same
    rule as the migration's CHECK, in the same words."""
    text = require_text(value, field)
    at = text.find("@")
    if at < 1 or at >= len(text) - 1:
        raise Refused(REFUSAL_EMAIL_MALFORMED, field, f"{field} is {text!r}.")
    return text


def folded(email: str) -> str:
    """The form two addresses are compared in. ``lower()`` and not
    ``casefold()``, because the migration's unique index is on
    ``lower(email)`` and the two must agree byte for byte: ``casefold`` turns
    an eszett into ``ss`` and Postgres's ``lower`` does not, and a comparison
    the database makes differently from the module is a refusal that arrives
    as a constraint instead of by name. Storage keeps the address as given;
    only the comparison folds."""
    return email.lower()


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
