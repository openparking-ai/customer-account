"""The writes and the reads: the account, the credential, the two one-time
tokens, the consent. Every function takes a cursor already inside a tenant's
context and never commits: the caller owns the transaction.

**THE TOKEN IS RETURNED EXACTLY ONCE, BY THE ISSUE CALL, AND BY NOTHING ELSE.**
``start_email_change`` and ``start_password_reset`` return the plaintext in
their result; the row holds the SHA-256 and nothing that yields the plaintext;
no read, no listing and no refusal detail carries it. A password is returned by
nothing at all: it is hashed and dropped. A test sets passwords and issues
tokens and scans every column of every table for each plaintext, with the
digest as the positive control.

**ONE TOKEN, ONE SPEND, AND THE LOCK ORDER THAT MAKES IT SO.** A token is read
unlocked ONLY to learn which customer it belongs to; then the CUSTOMER ROW is
locked, then the TOKEN ROW (``LOCK_ORDER``: one order everywhere), and
everything the write depends on is re-read and re-validated UNDER those locks
-- state, expiry, and for an email change whether the address is still free --
because at READ COMMITTED a check made before the lock is a check made on a
stale row. The BACKSTOP is the spend itself: ``UPDATE ... WHERE ... AND state =
'issued'`` asserting ROWCOUNT 1 -- 0 rows means another caller spent it, and
that is the named refusal, never a silent success.

**AT MOST ONE LIVE TOKEN OF EACH KIND PER CUSTOMER.** Issuing a new pending
change or a new reset CANCELS the customer's outstanding issued ones, with the
reason ``superseded`` and the issuer as ``cancelled_by``: the newest token is
the one that works, and an older one presented afterwards is refused as
cancelled, by name.

**THE ORDER OF THE REFUSALS IS PART OF THE CONTRACT**, and every one writes
nothing: the token (unknown; then, under the locks, already used; cancelled;
expired -- derived from ``expires_at`` against the instant given); then what
the spend would write (an address another customer took meanwhile). The first
thing that fails is the refusal; nothing after it is evaluated.

**NO EMAIL IS SENT.** This module has no network and no third-party service:
it mints a token, records that it was issued, and names the address it is FOR
-- the new one for a change, the CURRENT one for a reset -- so the caller can
deliver it. It never accepts a delivery address for a reset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from customer_account.consent import Acceptance
from customer_account.findings import (
    NO_CREDENTIAL,
    NOT_VERIFIED_MEANS,
    REFUSAL_AUTHORISATION_AMBIGUOUS,
    REFUSAL_AUTHORISATION_MISSING,
    REFUSAL_CONSTRAINT,
    REFUSAL_CUSTOMER_NOT_FOUND,
    REFUSAL_EMAIL_TAKEN,
    REFUSAL_EMAIL_UNCHANGED,
    REFUSAL_EXTERNAL_ID_TAKEN,
    REFUSAL_NO_CREDENTIAL,
    REFUSAL_PASSWORD_WRONG,
    REFUSAL_TENANT_NOT_FOUND,
    REFUSAL_TOKEN_ALREADY_USED,
    REFUSAL_TOKEN_CANCELLED,
    REFUSAL_TOKEN_EXPIRED,
    REFUSAL_TOKEN_UNKNOWN,
    VERIFICATIONS,
    VERIFIED,
    WRONG_PASSWORD,
    Refused,
)
from customer_account.identity import (
    Customer,
    optional_text,
    require_aware,
    require_email,
    require_text,
)
from customer_account.passwords import (
    KDF,
    SCRYPT,
    Credential,
    ScryptParameters,
    hash_password,
    require_password,
    verify,
)
from customer_account.tokens import (
    TokenState,
    digest,
    expiry,
    is_expired,
    mint,
    parse_state,
    require_valid_minutes,
)

#: The two ways an email change may be authorised, stored on the row.
BY_PASSWORD = "password"
BY_CALLER = "caller"

#: One order, everywhere a write takes two locks: the customer row, then the
#: token row. Two orders would be an ABBA deadlock waiting for its first
#: concurrent day.
LOCK_ORDER = ("customers", "pending_email_changes | credential_resets")

#: Why an older token was cancelled when a newer one was issued.
SUPERSEDED = "superseded"

PENDING_EMAIL_CHANGES = "pending_email_changes"
CREDENTIAL_RESETS = "credential_resets"

#: THE TIEBREAK, WRITTEN ONCE. Every history this module reads oldest first
#: ends in these two columns: ``created_at`` is the row's own clock, which
#: ties with the stated instant for two rows written in one transaction
#: (``now()`` is the transaction's instant); ``id`` is the final tiebreak,
#: unique on every row. Two rows sharing an instant are therefore ordered
#: DETERMINISTICALLY BUT ARBITRARILY -- the same order on every read, and an
#: order that means nothing. Measured in the gate on acceptances: without the
#: last column the order was stable 150/150 and stated nowhere, which is
#: behaviour, not a rule; measured again on the email history in the round
#: after: both clocks tied 8/8 and the read was heap order. One rule, one
#: place: each order below is derived from this tuple, never written out.
TIEBREAK = ("created_at", "id")

#: The order a customer's acceptances are read in, oldest first:
#: ``show_acceptances`` orders by it and the contract renders it.
#: ``accepted_at`` is the rule (the row current for a version is the latest).
ACCEPTANCE_ORDER = ("accepted_at", *TIEBREAK)

#: The order a customer's email history is read in, oldest first:
#: ``show_account`` orders by it and the contract renders it. ``changed_at``
#: is the rule (the instant the change took effect, as the caller stated it).
EMAIL_CHANGE_ORDER = ("changed_at", *TIEBREAK)


def as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def refuse_on_constraint(exc: Exception) -> Refused:
    """A database constraint the module did not catch first, as a named
    refusal carrying the constraint's name -- never a traceback."""
    diag = getattr(exc, "diag", None)
    constraint = getattr(diag, "constraint_name", None) or type(exc).__name__
    message = getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
    return Refused(REFUSAL_CONSTRAINT, constraint, message)


def _row_customer(row: tuple) -> Customer:
    cid, tid, external_id, email, name, phone, created_at = row
    return Customer(
        id=as_uuid(cid), tenant_id=as_uuid(tid), external_id=external_id, email=email,
        name=name, phone=phone, created_at=created_at,
    )


_CUSTOMER_COLUMNS = "id, tenant_id, external_id, email, name, phone, created_at"


def require_tenant(cursor: Any, tenant_id: UUID) -> None:
    """The tenant row must exist, read before the first write, so an id nobody
    seeded is refused by name rather than met at the foreign key."""
    cursor.execute("SELECT 1 FROM tenants WHERE id = %s", (str(tenant_id),))
    if cursor.fetchone() is None:
        raise Refused(REFUSAL_TENANT_NOT_FOUND, "tenant", f"no tenant {tenant_id}.")


def load_customer(
    cursor: Any, tenant_id: UUID, customer_id: UUID, *, lock: bool = False
) -> Customer:
    cursor.execute(
        f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE tenant_id = %s AND id = %s"
        + (" FOR UPDATE" if lock else ""),
        (str(tenant_id), str(customer_id)),
    )
    row = cursor.fetchone()
    if row is None:
        raise Refused(REFUSAL_CUSTOMER_NOT_FOUND, "customer", f"no customer {customer_id}.")
    return _row_customer(row)


def find_customer_by_email(cursor: Any, tenant_id: UUID, email: str) -> Customer:
    """By the address as the store folds it -- the form uniqueness is enforced
    in (see ``_address_holder``)."""
    address = require_email(email)
    cursor.execute(
        f"SELECT {_CUSTOMER_COLUMNS} FROM customers WHERE tenant_id = %s "
        "AND lower(email) = lower(%s)",
        (str(tenant_id), address),
    )
    row = cursor.fetchone()
    if row is None:
        raise Refused(REFUSAL_CUSTOMER_NOT_FOUND, "email", "no customer with that address.")
    return _row_customer(row)


def _address_holder(cursor: Any, tenant_id: UUID, email: str) -> UUID | None:
    """Which customer, if any, carries this address -- THE ONE AUTHORITY on
    whether two addresses are one. The fold is the database's ``lower()``
    under the collation ``customers.email`` carries (the database's default;
    migration 0001 refuses to apply where that folds ASCII only), the same
    expression the unique index is on, so the module and the constraint can
    never disagree. Nothing in Python folds an address."""
    cursor.execute(
        "SELECT id FROM customers WHERE tenant_id = %s AND lower(email) = lower(%s)",
        (str(tenant_id), email),
    )
    row = cursor.fetchone()
    return as_uuid(row[0]) if row else None


# ---------------------------------------------------------------------------
# The account, and the consent it is created with.
# ---------------------------------------------------------------------------


def create_account(
    cursor: Any,
    tenant_id: UUID,
    *,
    email: object,
    external_id: object,
    name: object,
    phone: object,
    at: object,
    acceptance: Acceptance,
) -> dict[str, Any]:
    """The customer row and its first terms acceptance, in one transaction:
    an account is created with its terms accepted or not at all. The
    acceptance is built and checked BEFORE this is called (``consent``), so a
    missing one never reaches here. No credential is written: that is a
    separate, explicit ``set_password``."""
    tenant_id = as_uuid(tenant_id)
    require_tenant(cursor, tenant_id)
    address = require_email(email)
    reference = optional_text(external_id, "external_id")
    created_at = require_aware(at, "at")
    if _address_holder(cursor, tenant_id, address) is not None:
        raise Refused(REFUSAL_EMAIL_TAKEN, "email", "another customer carries this address.")
    if reference is not None:
        cursor.execute(
            "SELECT 1 FROM customers WHERE tenant_id = %s AND external_id = %s",
            (str(tenant_id), reference),
        )
        if cursor.fetchone() is not None:
            raise Refused(
                REFUSAL_EXTERNAL_ID_TAKEN, "external_id",
                f"another customer carries the reference {reference!r}.",
            )
    import psycopg

    try:
        cursor.execute(
            "INSERT INTO customers (tenant_id, external_id, email, name, phone, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (str(tenant_id), reference, address, optional_text(name, "name"),
             optional_text(phone, "phone"), created_at),
        )
        (customer_id,) = cursor.fetchone()
        customer_id = as_uuid(customer_id)
        accepted = record_acceptance(cursor, tenant_id, customer_id, acceptance)
    except psycopg.errors.IntegrityError as exc:
        raise refuse_on_constraint(exc) from None
    return {"customer": str(customer_id), "email": address, "external_id": reference,
            "acceptance": accepted}


def record_acceptance(
    cursor: Any, tenant_id: UUID, customer_id: UUID, acceptance: Acceptance
) -> dict[str, Any]:
    """One acceptance row and its channel rows. Append-only by grant."""
    tenant_id, customer_id = as_uuid(tenant_id), as_uuid(customer_id)
    load_customer(cursor, tenant_id, customer_id)
    cursor.execute(
        "INSERT INTO terms_acceptances (tenant_id, customer_id, terms_version, terms_shown, "
        "accepted_by, accepted_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (str(tenant_id), str(customer_id), acceptance.terms_version, acceptance.terms_shown,
         acceptance.accepted_by, acceptance.accepted_at),
    )
    (acceptance_id,) = cursor.fetchone()
    for shown in acceptance.channels:
        # ONE CLOCK: a channel written with its acceptance carries the
        # acceptance's own instant and name. A channel row is self-describing
        # whichever way it arrives, and a test holds these two equal.
        cursor.execute(
            "INSERT INTO acceptance_channels (tenant_id, acceptance_id, channel, text_shown, "
            "consented_by, consented_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (str(tenant_id), str(acceptance_id), shown.channel.value, shown.text_shown,
             acceptance.accepted_by, acceptance.accepted_at),
        )
    return {
        "acceptance": str(acceptance_id),
        "terms_version": acceptance.terms_version,
        "accepted_by": acceptance.accepted_by,
        "accepted_at": acceptance.accepted_at,
        "channels": [s.channel.value for s in acceptance.channels],
    }


def show_acceptances(cursor: Any, tenant_id: UUID, customer_id: UUID) -> list[dict[str, Any]]:
    """Every acceptance the customer has made, oldest first, the text shown
    included: this is the read that answers "what did they agree to".
    Acceptances ACCUMULATE -- a later one is a further entry, never a
    rewrite -- so the last entry for a version is the current one; each
    channel carries its own consented_by and consented_at. The order is
    ``ACCEPTANCE_ORDER``, ending in ``id`` so that a full tie still reads the
    same way twice."""
    tenant_id, customer_id = as_uuid(tenant_id), as_uuid(customer_id)
    load_customer(cursor, tenant_id, customer_id)
    cursor.execute(
        "SELECT id, terms_version, terms_shown, accepted_by, accepted_at FROM terms_acceptances "
        f"WHERE tenant_id = %s AND customer_id = %s ORDER BY {', '.join(ACCEPTANCE_ORDER)}",
        (str(tenant_id), str(customer_id)),
    )
    out = []
    for aid, version, shown, by, at in cursor.fetchall():
        cursor.execute(
            "SELECT channel, text_shown, consented_by, consented_at FROM acceptance_channels "
            "WHERE tenant_id = %s AND acceptance_id = %s ORDER BY channel",
            (str(tenant_id), str(aid)),
        )
        channels = [
            {"channel": c, "text_shown": t, "consented_by": b, "consented_at": w}
            for c, t, b, w in cursor.fetchall()
        ]
        out.append({"acceptance": str(aid), "terms_version": version, "terms_shown": shown,
                    "accepted_by": by, "accepted_at": at, "channels": channels})
    return out


def show_account(cursor: Any, tenant_id: UUID, customer_id: UUID) -> dict[str, Any]:
    """The one read of an account. It renders NO hash, NO salt and NO token
    digest: the credential is described by its parameters and when it was
    set, or by its absence, BY NAME. The email history is oldest first in
    ``EMAIL_CHANGE_ORDER``, ending in ``id`` so that a full tie still reads
    the same way twice; the pending list is at most one row through every
    door (a new change supersedes the old under the customer's lock), so its
    order has nothing to tie."""
    tenant_id, customer_id = as_uuid(tenant_id), as_uuid(customer_id)
    customer = load_customer(cursor, tenant_id, customer_id)
    credential = _credential_row(cursor, tenant_id, customer_id)
    if credential is None:
        described: dict[str, Any] = {"state": "absent", "sentence": VERIFICATIONS[NO_CREDENTIAL]}
    else:
        _cred, set_by, changed_at = credential
        described = {
            "state": "set", "kdf": _cred.kdf, "scrypt_n": _cred.parameters.n,
            "scrypt_r": _cred.parameters.r, "scrypt_p": _cred.parameters.p,
            "dklen": _cred.parameters.dklen, "set_by": set_by, "changed_at": changed_at,
        }
    cursor.execute(
        "SELECT new_email, authorisation, authorised_by, issued_at, expires_at "
        "FROM pending_email_changes WHERE tenant_id = %s AND customer_id = %s "
        "AND state = 'issued' ORDER BY issued_at DESC",
        (str(tenant_id), str(customer_id)),
    )
    pending = [
        {"new_email": e, "authorisation": a, "authorised_by": b, "issued_at": i, "expires_at": x}
        for e, a, b, i, x in cursor.fetchall()
    ]
    cursor.execute(
        "SELECT from_email, to_email, authorisation, authorised_by, changed_at "
        "FROM customer_email_changes WHERE tenant_id = %s AND customer_id = %s "
        f"ORDER BY {', '.join(EMAIL_CHANGE_ORDER)}",
        (str(tenant_id), str(customer_id)),
    )
    history = [
        {"from_email": f, "to_email": t, "authorisation": a, "authorised_by": b, "changed_at": c}
        for f, t, a, b, c in cursor.fetchall()
    ]
    cursor.execute(
        "SELECT count(*), max(accepted_at) FROM terms_acceptances "
        "WHERE tenant_id = %s AND customer_id = %s",
        (str(tenant_id), str(customer_id)),
    )
    count, latest = cursor.fetchone()
    return {
        "customer": str(customer.id),
        "email": customer.email,
        "external_id": customer.external_id,
        "name": customer.name,
        "phone": customer.phone,
        "created_at": customer.created_at,
        "credential": described,
        "pending_email_changes": pending,
        "email_changes": history,
        "acceptances": {"count": count, "latest_accepted_at": latest},
    }


# ---------------------------------------------------------------------------
# The credential.
# ---------------------------------------------------------------------------


def _credential_row(
    cursor: Any, tenant_id: UUID, customer_id: UUID, *, lock: bool = False
) -> tuple[Credential, str, datetime] | None:
    cursor.execute(
        "SELECT kdf, scrypt_n, scrypt_r, scrypt_p, dklen, salt_hex, hash_hex, set_by, changed_at "
        "FROM customer_credentials WHERE tenant_id = %s AND customer_id = %s"
        + (" FOR UPDATE" if lock else ""),
        (str(tenant_id), str(customer_id)),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    kdf, n, r, p, dklen, salt_hex, hash_hex, set_by, changed_at = row
    credential = Credential(
        kdf=kdf, parameters=ScryptParameters(n=n, r=r, p=p, dklen=dklen),
        salt_hex=salt_hex, hash_hex=hash_hex,
    )
    return credential, set_by, changed_at


def load_credential(cursor: Any, tenant_id: UUID, customer_id: UUID) -> Credential | None:
    """The row's credential, with THE ROW'S parameters -- or ``None``, which
    the callers answer by name."""
    row = _credential_row(cursor, as_uuid(tenant_id), as_uuid(customer_id))
    return None if row is None else row[0]


def _write_credential(
    cursor: Any, tenant_id: UUID, customer_id: UUID, password: str, *, by: str, at: datetime
) -> dict[str, Any]:
    """Hash under the CURRENT parameters and write: an INSERT where no row
    exists, an UPDATE where one does (which is how a row re-hashes under
    raised parameters the next time its password is set)."""
    credential = hash_password(password, SCRYPT)
    parameters = credential.parameters
    cursor.execute(
        "UPDATE customer_credentials SET kdf = %s, scrypt_n = %s, scrypt_r = %s, scrypt_p = %s, "
        "dklen = %s, salt_hex = %s, hash_hex = %s, set_by = %s, changed_at = %s "
        "WHERE tenant_id = %s AND customer_id = %s",
        (KDF, parameters.n, parameters.r, parameters.p, parameters.dklen, credential.salt_hex,
         credential.hash_hex, by, at, str(tenant_id), str(customer_id)),
    )
    replaced = cursor.rowcount == 1
    if not replaced:
        cursor.execute(
            "INSERT INTO customer_credentials (tenant_id, customer_id, kdf, scrypt_n, scrypt_r, "
            "scrypt_p, dklen, salt_hex, hash_hex, set_by, changed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (str(tenant_id), str(customer_id), KDF, parameters.n, parameters.r, parameters.p,
             parameters.dklen, credential.salt_hex, credential.hash_hex, by, at),
        )
    return {"customer": str(customer_id), "credential": "replaced" if replaced else "set",
            "kdf": KDF, "scrypt_n": parameters.n, "scrypt_r": parameters.r,
            "scrypt_p": parameters.p, "dklen": parameters.dklen, "set_by": by, "changed_at": at}


def set_password(
    cursor: Any, tenant_id: UUID, customer_id: UUID, password: object, *, by: object, at: object
) -> dict[str, Any]:
    """The caller says a credential exists now. ``by`` is stored: who decided
    a password should exist is a fact this module records and never infers."""
    tenant_id, customer_id = as_uuid(tenant_id), as_uuid(customer_id)
    who = require_text(by, "by")
    when = require_aware(at, "at")
    secret = require_password(password)
    load_customer(cursor, tenant_id, customer_id, lock=True)
    return _write_credential(cursor, tenant_id, customer_id, secret, by=who, at=when)


@dataclass(frozen=True)
class Verification:
    """The password check's answer. Three named outcomes, and every one that
    is not VERIFIED carries the sentence saying what not-verified means."""

    customer: str
    outcome: str
    verified: bool
    sentence: str
    means: str | None


def verify_password(
    cursor: Any, tenant_id: UUID, customer_id: UUID, password: object
) -> Verification:
    """Never a crash, never a silent false: a customer with no credential is
    answered NO_CREDENTIAL, by name, with the sentence that it is not "no
    password required"."""
    tenant_id, customer_id = as_uuid(tenant_id), as_uuid(customer_id)
    load_customer(cursor, tenant_id, customer_id)
    secret = require_password(password)
    credential = load_credential(cursor, tenant_id, customer_id)
    if credential is None:
        outcome = NO_CREDENTIAL
    elif verify(secret, credential):
        outcome = VERIFIED
    else:
        outcome = WRONG_PASSWORD
    return Verification(
        customer=str(customer_id), outcome=outcome, verified=outcome == VERIFIED,
        sentence=VERIFICATIONS[outcome],
        means=None if outcome == VERIFIED else NOT_VERIFIED_MEANS,
    )


def _require_password_verified(
    cursor: Any, tenant_id: UUID, customer_id: UUID, password: str
) -> None:
    """For a write that the current password authorises: no credential and a
    wrong password are each a REFUSAL here, by name, because the request is
    to write."""
    credential = load_credential(cursor, tenant_id, customer_id)
    if credential is None:
        raise Refused(REFUSAL_NO_CREDENTIAL, "customer", "no password has been set.")
    if not verify(password, credential):
        raise Refused(REFUSAL_PASSWORD_WRONG, "password", "the password does not match.")


# ---------------------------------------------------------------------------
# The two one-time tokens.
# ---------------------------------------------------------------------------


def _supersede(
    cursor: Any, table: str, tenant_id: UUID, customer_id: UUID, *, by: str, at: datetime
) -> int:
    """Cancel the customer's outstanding issued tokens of one kind."""
    cursor.execute(
        f"UPDATE {table} SET state = 'cancelled', cancelled_by = %s, cancelled_at = %s, "
        "cancelled_reason = %s WHERE tenant_id = %s AND customer_id = %s AND state = 'issued'",
        (by, at, SUPERSEDED, str(tenant_id), str(customer_id)),
    )
    return cursor.rowcount


def start_email_change(
    cursor: Any,
    tenant_id: UUID,
    customer_id: UUID,
    new_email: object,
    *,
    valid_minutes: object,
    at: object,
    password: str | None = None,
    by: object = None,
) -> dict[str, Any]:
    """Mint the token the NEW address will present back. Authorised by EXACTLY
    ONE of: the current password, verified here; a caller's stated ``by``.
    Which one is stored. Nothing on ``customers`` moves."""
    tenant_id, customer_id = as_uuid(tenant_id), as_uuid(customer_id)
    when = require_aware(at, "at")
    address = require_email(new_email, "new_email")
    minutes = require_valid_minutes(valid_minutes)
    caller = optional_text(by, "by")
    has_password = password is not None and password != ""
    if has_password and caller is not None:
        raise Refused(
            REFUSAL_AUTHORISATION_AMBIGUOUS, "by", "both a password and --by were given."
        )
    if not has_password and caller is None:
        raise Refused(
            REFUSAL_AUTHORISATION_MISSING, "by", "neither a password nor --by was given."
        )
    # The row is locked here (LOCK_ORDER: the customer first) and an unknown
    # customer is refused by name; nothing on the row is read in Python.
    load_customer(cursor, tenant_id, customer_id, lock=True)
    if has_password:
        _require_password_verified(cursor, tenant_id, customer_id, require_password(password))
        authorisation, authorised_by = BY_PASSWORD, str(customer_id)
    else:
        authorisation, authorised_by = BY_CALLER, caller
    # "Is this already your address" is answered by the STORE, the same
    # authority create_account and confirm_email_change use, and by nothing
    # in Python: the gate measured Python's lower() and the database's
    # disagreeing on 28 code points on CI's own database, so a comparison
    # made here said "unchanged" for an address the next door would then
    # hand to a second customer.
    holder = _address_holder(cursor, tenant_id, address)
    if holder == customer_id:
        raise Refused(REFUSAL_EMAIL_UNCHANGED, "new_email", "it is the current address.")
    if holder is not None:
        raise Refused(REFUSAL_EMAIL_TAKEN, "new_email", "another customer carries this address.")
    superseded = _supersede(cursor, PENDING_EMAIL_CHANGES, tenant_id, customer_id,
                            by=authorised_by, at=when)
    minted = mint()
    expires_at = expiry(when, minutes)
    cursor.execute(
        "INSERT INTO pending_email_changes (tenant_id, customer_id, new_email, token_sha256, "
        "authorisation, authorised_by, issued_at, expires_at, state) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'issued') RETURNING id",
        (str(tenant_id), str(customer_id), address, minted.sha256, authorisation, authorised_by,
         when, expires_at),
    )
    (change_id,) = cursor.fetchone()
    return {
        "pending_email_change": str(change_id),
        "customer": str(customer_id),
        "new_email": address,
        "deliver_to": address,
        "authorisation": authorisation,
        "authorised_by": authorised_by,
        "issued_at": when,
        "expires_at": expires_at,
        "superseded": superseded,
        # THE ONE RETURN of the plaintext.
        "token": minted.token,
    }


def _locate_token(cursor: Any, table: str, tenant_id: UUID, token: object) -> UUID:
    """Which customer the token belongs to -- read UNLOCKED, only to learn
    which row to lock first. Unknown is refused here, by name, and the
    presented token is not in the refusal."""
    presented = require_text(token, "token")
    cursor.execute(
        f"SELECT customer_id FROM {table} WHERE tenant_id = %s AND token_sha256 = %s",
        (str(tenant_id), digest(presented)),
    )
    row = cursor.fetchone()
    if row is None:
        raise Refused(REFUSAL_TOKEN_UNKNOWN, "token", "no token of this operator matches.")
    return as_uuid(row[0])


def _locked_token(cursor: Any, table: str, tenant_id: UUID, token: str, at: datetime) -> tuple:
    """The token row, locked and re-read under the customer lock, and judged:
    already used, cancelled, expired -- each by name, in that order."""
    cursor.execute(
        f"SELECT id, customer_id, state, redeemed_at, cancelled_at, cancelled_reason, "
        f"expires_at FROM {table} WHERE tenant_id = %s AND token_sha256 = %s FOR UPDATE",
        (str(tenant_id), digest(token)),
    )
    row = cursor.fetchone()
    if row is None:  # pragma: no cover - located a moment ago; nothing deletes rows
        raise Refused(REFUSAL_TOKEN_UNKNOWN, "token", "no token of this operator matches.")
    token_id, customer_id, state, redeemed_at, cancelled_at, cancelled_reason, expires_at = row
    # THE STATE READ IS PARSED, NOT TRUSTED. The schema's CHECK is what stops
    # anyone typing a state, and a schema is a thing an owner can alter:
    # measured with the CHECK dropped and 'expired' written onto a live row,
    # the door below fell through to the spend and refused it as "spent by
    # another caller meanwhile" -- a false sentence. A state this module
    # does not have is refused by name here; 'expired' by its own.
    state = parse_state(state).value
    if state == TokenState.REDEEMED.value:
        raise Refused(REFUSAL_TOKEN_ALREADY_USED, "token", f"used at {redeemed_at.isoformat()}.")
    if state == TokenState.CANCELLED.value:
        raise Refused(
            REFUSAL_TOKEN_CANCELLED, "token",
            f"cancelled at {cancelled_at.isoformat()}: {cancelled_reason}.",
        )
    if is_expired(expires_at, at):
        raise Refused(
            REFUSAL_TOKEN_EXPIRED, "token",
            f"expires at {expires_at.isoformat()}, and it is {at.isoformat()}.",
        )
    return as_uuid(token_id), as_uuid(customer_id), expires_at


def _spend(cursor: Any, table: str, tenant_id: UUID, token_id: UUID, at: datetime) -> None:
    """THE BACKSTOP: mark redeemed only from ``issued``, asserting one row."""
    cursor.execute(
        f"UPDATE {table} SET state = 'redeemed', redeemed_at = %s "
        "WHERE tenant_id = %s AND id = %s AND state = 'issued'",
        (at, str(tenant_id), str(token_id)),
    )
    if cursor.rowcount != 1:
        raise Refused(REFUSAL_TOKEN_ALREADY_USED, "token", "spent by another caller meanwhile.")


def confirm_email_change(
    cursor: Any, tenant_id: UUID, token: object, *, at: object
) -> dict[str, Any]:
    """The new address presents the token: the change takes effect NOW, in one
    transaction -- the customer's email rewritten, the history row written
    carrying the authorisation, the token spent. Until this call the old
    address is the address."""
    tenant_id = as_uuid(tenant_id)
    when = require_aware(at, "at")
    presented = require_text(token, "token")
    customer_id = _locate_token(cursor, PENDING_EMAIL_CHANGES, tenant_id, presented)
    customer = load_customer(cursor, tenant_id, customer_id, lock=True)
    token_id, _owner, _expires = _locked_token(cursor, PENDING_EMAIL_CHANGES, tenant_id,
                                               presented, when)
    cursor.execute(
        "SELECT new_email, authorisation, authorised_by FROM pending_email_changes "
        "WHERE tenant_id = %s AND id = %s",
        (str(tenant_id), str(token_id)),
    )
    new_email, authorisation, authorised_by = cursor.fetchone()
    holder = _address_holder(cursor, tenant_id, new_email)
    if holder is not None and holder != customer_id:
        raise Refused(
            REFUSAL_EMAIL_TAKEN, "new_email",
            "another customer took this address after the change was started.",
        )
    import psycopg

    try:
        _spend(cursor, PENDING_EMAIL_CHANGES, tenant_id, token_id, when)
        cursor.execute(
            "UPDATE customers SET email = %s WHERE tenant_id = %s AND id = %s",
            (new_email, str(tenant_id), str(customer_id)),
        )
        cursor.execute(
            "INSERT INTO customer_email_changes (tenant_id, customer_id, from_email, to_email, "
            "authorisation, authorised_by, changed_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (str(tenant_id), str(customer_id), customer.email, new_email, authorisation,
             authorised_by, when),
        )
        (change_id,) = cursor.fetchone()
    except psycopg.errors.IntegrityError as exc:
        raise refuse_on_constraint(exc) from None
    return {
        "customer": str(customer_id),
        "email_change": str(change_id),
        "from_email": customer.email,
        "to_email": new_email,
        "authorisation": authorisation,
        "authorised_by": authorised_by,
        "changed_at": when,
    }


def start_password_reset(
    cursor: Any,
    tenant_id: UUID,
    customer_id: UUID,
    *,
    valid_minutes: object,
    by: object,
    at: object,
) -> dict[str, Any]:
    """Mint the token the CURRENT address receives. It resets a password that
    exists: a customer with no credential is refused by name. ``deliver_to``
    is read from the customer row and cannot be supplied."""
    tenant_id, customer_id = as_uuid(tenant_id), as_uuid(customer_id)
    when = require_aware(at, "at")
    minutes = require_valid_minutes(valid_minutes)
    who = require_text(by, "by")
    customer = load_customer(cursor, tenant_id, customer_id, lock=True)
    if load_credential(cursor, tenant_id, customer_id) is None:
        raise Refused(REFUSAL_NO_CREDENTIAL, "customer", "no password has been set to reset.")
    superseded = _supersede(cursor, CREDENTIAL_RESETS, tenant_id, customer_id, by=who, at=when)
    minted = mint()
    expires_at = expiry(when, minutes)
    cursor.execute(
        "INSERT INTO credential_resets (tenant_id, customer_id, token_sha256, issued_by, "
        "issued_at, expires_at, state) VALUES (%s, %s, %s, %s, %s, %s, 'issued') RETURNING id",
        (str(tenant_id), str(customer_id), minted.sha256, who, when, expires_at),
    )
    (reset_id,) = cursor.fetchone()
    return {
        "credential_reset": str(reset_id),
        "customer": str(customer_id),
        # THE CURRENT ADDRESS, from the row. Never an argument.
        "deliver_to": customer.email,
        "issued_by": who,
        "issued_at": when,
        "expires_at": expires_at,
        "superseded": superseded,
        # THE ONE RETURN of the plaintext.
        "token": minted.token,
    }


def consume_password_reset(
    cursor: Any, tenant_id: UUID, token: object, password: object, *, at: object
) -> dict[str, Any]:
    """The current address presents the token with the new password: the
    credential is replaced and the token spent, in one transaction."""
    tenant_id = as_uuid(tenant_id)
    when = require_aware(at, "at")
    presented = require_text(token, "token")
    secret = require_password(password)
    customer_id = _locate_token(cursor, CREDENTIAL_RESETS, tenant_id, presented)
    load_customer(cursor, tenant_id, customer_id, lock=True)
    token_id, _owner, _expires = _locked_token(cursor, CREDENTIAL_RESETS, tenant_id,
                                               presented, when)
    _spend(cursor, CREDENTIAL_RESETS, tenant_id, token_id, when)
    written = _write_credential(cursor, tenant_id, customer_id, secret,
                                by=f"credential_reset:{token_id}", at=when)
    written["credential_reset"] = str(token_id)
    return written
