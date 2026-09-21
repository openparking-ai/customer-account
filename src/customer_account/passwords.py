"""The password: hashed with the standard library's scrypt, with the
parameters STATED here and STORED beside every hash.

**A KDF, NOT A DIGEST.** The sibling modules store a generated token as its
SHA-256, and that is right for 32 bytes from the operating system's CSPRNG. A
human password has a few dozen bits of entropy at best, and a plain digest of
it is cracked by enumeration. ``hashlib.scrypt`` is memory-hard, in the
standard library, and needs no dependency.

**THE PARAMETERS WERE MEASURED, NOT CHOSEN.** ``scripts/measure_scrypt.py``
times one hash across candidate cost factors on the machine it runs on and
picks the largest that stays under the budget. The value here is what that
command produced on the machine named in the round's receipt; this project has
no reference hardware, and an operator on slower hardware re-measures.

**AND THEY ARE STORED BESIDE THE HASH.** ``Credential`` carries ``n``, ``r``,
``p`` and ``dklen`` from the ROW, and ``verify`` uses the row's values, never
this module's constants -- so raising ``SCRYPT`` tomorrow invalidates no
existing row: old rows verify with old parameters, new rows are written with
new ones, and a credential is re-hashed with the current parameters the next
time its password is set. A test stores a row with different parameters and
requires it to verify.

**THE COMPARISON IS CONSTANT-TIME** (``hmac.compare_digest``), so a wrong
password takes as long to refuse as a right one takes to accept, byte for byte.

**ONE RULE ON THE PASSWORD ITSELF: A MINIMUM LENGTH**, stated below, and no
other. Character classes and dictionaries measurably hurt what they are meant
to help; length is the rule that measurably helps.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from customer_account.findings import (
    REFUSAL_KDF_UNKNOWN,
    REFUSAL_PASSWORD_NOT_GIVEN,
    REFUSAL_PASSWORD_TOO_SHORT,
    Refused,
)

KDF = "scrypt"


@dataclass(frozen=True)
class ScryptParameters:
    n: int
    r: int
    p: int
    dklen: int

    @property
    def maxmem(self) -> int:
        """What scrypt needs (128 * r * n bytes) with headroom, stated because
        CPython's default of 32 MiB refuses n above 2**14 at r=8."""
        return 128 * self.r * self.n * 2


#: Measured 2026-09-20 by scripts/measure_scrypt.py on an Apple M5 (arm64,
#: Python 3.12): one hash at n=2**17 took 176 ms median, the largest candidate
#: under the 250 ms budget. r=8 and p=1 are held at the values scrypt's own
#: paper holds them at; dklen=64.
SCRYPT = ScryptParameters(n=2**17, r=8, p=1, dklen=64)

#: The one rule on a password. Bytes of UTF-8, not characters -- the thing the
#: KDF actually receives.
MIN_PASSWORD_BYTES = 12

#: 16 bytes from the CSPRNG per hash, hex-encoded in the row.
SALT_BYTES = 16

#: The environment variables a password is read from. Never an argument.
PASSWORD_ENV = "CUSTOMER_ACCOUNT_PASSWORD"


@dataclass(frozen=True)
class Credential:
    """What the row holds: the hash, the salt, the KDF and ITS parameters."""

    kdf: str
    parameters: ScryptParameters
    salt_hex: str
    hash_hex: str


def require_password(value: object, source: str = PASSWORD_ENV) -> str:
    """A password of at least MIN_PASSWORD_BYTES bytes, or a refusal by name.
    ``source`` is where it was read from, for the refusal's field."""
    if value is None or value == "":
        raise Refused(
            REFUSAL_PASSWORD_NOT_GIVEN, source,
            f"{source} is not set or is empty.",
        )
    if not isinstance(value, str):
        raise Refused(REFUSAL_PASSWORD_NOT_GIVEN, source, f"{source} must be text.")
    if len(value.encode("utf-8")) < MIN_PASSWORD_BYTES:
        raise Refused(
            REFUSAL_PASSWORD_TOO_SHORT, source,
            f"the password is shorter than {MIN_PASSWORD_BYTES} bytes.",
        )
    return value


def hash_password(password: str, parameters: ScryptParameters = SCRYPT) -> Credential:
    """A fresh salt, and the scrypt hash of the password under ``parameters``.
    The password is used and dropped; nothing here keeps it."""
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=parameters.n, r=parameters.r,
        p=parameters.p, dklen=parameters.dklen, maxmem=parameters.maxmem,
    )
    return Credential(
        kdf=KDF, parameters=parameters, salt_hex=salt.hex(), hash_hex=derived.hex(),
    )


def verify(password: str, credential: Credential) -> bool:
    """Does ``password`` produce ``credential``'s hash under THE ROW'S
    parameters? Constant-time comparison.

    **THE ROW'S KDF IS PARSED, NOT TRUSTED.** The schema's CHECK is what stops
    anyone writing a credential this module did not make, and a schema is a
    thing an owner can alter: measured with the CHECK dropped and ``argon2id``
    written onto a live row, both doors that check a password reached the
    shell as a Python traceback with no JSON and exit 1 -- which is also
    ``verify-password``'s "not verified" status, so a caller reading the exit
    alone would have read a crash as a wrong password. A KDF this module does
    not have is refused by name here, the same shape as ``tokens.parse_state``
    for a token's state; the password is never compared."""
    if credential.kdf != KDF:
        raise Refused(
            REFUSAL_KDF_UNKNOWN, "kdf",
            f"{credential.kdf!r}; the one KDF this module has is {KDF!r}.",
        )
    parameters = credential.parameters
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=bytes.fromhex(credential.salt_hex), n=parameters.n,
        r=parameters.r, p=parameters.p, dklen=parameters.dklen, maxmem=parameters.maxmem,
    )
    return hmac.compare_digest(derived.hex(), credential.hash_hex)
