"""The one-time token: minted from the CSPRNG, stored as its SHA-256, returned
exactly once.

Two things carry one: a pending email change (the token is what the NEW
address receives and presents back) and a password reset (what the CURRENT
address receives). The primitive is the sibling pass module's, copied: 32
bytes from ``secrets``, URL-safe, and only the hex SHA-256 in the row. A
database read never yields a working token.

**THIS MODULE SENDS NOTHING.** No email, no SMS, no network. It mints the
token, records that it was issued, and returns the plaintext once, from the
call that minted it. Delivering it is the caller's.

**EXPIRY IS DERIVED, NEVER TYPED.** A token carries ``expires_at``, stated at
issue from a window the caller states in minutes (``require_valid_minutes``:
no default). "Expired" is ``expires_at`` against the instant asked about; the
typed states are ``issued``, ``redeemed`` and ``cancelled``, the sibling
module's vocabulary, and the migration's CHECK refuses anything else.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from customer_account.findings import (
    REFUSAL_EXPIRED_IS_DERIVED,
    REFUSAL_STATE_UNKNOWN,
    REFUSAL_VALID_MINUTES_NOT_POSITIVE,
    REFUSAL_VALID_MINUTES_NOT_STATED,
    Refused,
)


class TokenState(Enum):
    ISSUED = "issued"
    REDEEMED = "redeemed"
    CANCELLED = "cancelled"


#: Derived from expires_at; nobody types it.
EXPIRED = "expired"


@dataclass(frozen=True)
class MintedToken:
    """The plaintext, and the only thing about it that is ever stored."""

    token: str
    sha256: str


def mint() -> MintedToken:
    """A fresh token: 32 bytes from the operating system's CSPRNG, URL-safe,
    and its SHA-256 hex digest."""
    token = secrets.token_urlsafe(32)
    return MintedToken(token=token, sha256=digest(token))


def digest(token: str) -> str:
    """The SHA-256 hex digest of a token -- the only form the store compares."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_state(name: object) -> TokenState:
    """A typed state by name. ``expired`` is refused by its own code, because
    somebody typing it is the mistake the derivation exists to prevent.

    Called by the store on every token row it reads under lock: the schema's
    CHECK is the first line, and an owner can alter a schema, so what comes
    back from the database is parsed here rather than trusted."""
    if name == EXPIRED:
        raise Refused(REFUSAL_EXPIRED_IS_DERIVED, "state", "'expired' was typed.")
    try:
        return TokenState(name)
    except ValueError:
        raise Refused(
            REFUSAL_STATE_UNKNOWN, "state",
            f"{name!r}; the typed token states are {[s.value for s in TokenState]}.",
        ) from None


def require_valid_minutes(value: object) -> int:
    """A stated, positive whole number of minutes -- or a refusal by name.
    ``None`` is refused as NOT STATED, never read as a default."""
    if value is None:
        raise Refused(
            REFUSAL_VALID_MINUTES_NOT_STATED, "valid_minutes", "valid_minutes is not stated."
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise Refused(
            REFUSAL_VALID_MINUTES_NOT_POSITIVE, "valid_minutes",
            f"valid_minutes must be a positive whole number of minutes, not {value!r}.",
        )
    if value <= 0:
        raise Refused(
            REFUSAL_VALID_MINUTES_NOT_POSITIVE, "valid_minutes", f"valid_minutes is {value}."
        )
    return value


def expiry(issued_at: datetime, valid_minutes: int) -> datetime:
    return issued_at + timedelta(minutes=valid_minutes)


def is_expired(expires_at: datetime, at: datetime) -> bool:
    """Derived, in one place: the window has passed when ``at`` is at or past
    ``expires_at``."""
    return at >= expires_at
