"""Every refusal and every named answer, as a code with a plain-English sentence.

**The registries are the single source.** ``docs/CONTRACT.md`` is generated from
them, a refusal carries its code, and the tests derive their lists from here
rather than walking hand-written ones -- so a code added without a sentence
fails at the raise site, and a sentence published for a code nothing raises is
an orphan the contract check can see.

Two vocabularies live here and they are deliberately not one:

* **REFUSALS** -- the module will not do what it was asked: an account with a
  malformed address is not created, a token that has expired is not spent, an
  email change nobody authorised is not started. Each names the field or the
  thing that would have to change. A refusal is an exception, and it writes
  nothing.

* **VERIFICATIONS** -- the password check CAN answer, and the answer is one of
  three named states. The one that matters most: **a customer with no
  credential is answered by name, and that name is never "no password
  required".** This module has no view of whether anybody is charged; it
  records that a password was set and never infers why one was not.
"""

from __future__ import annotations


class Refused(Exception):
    """The module will not do this, and says which field is why.

    Carries the code so a caller can branch on it without parsing prose, the
    field it names so an operator's screen can point at it, and the sentence so
    a person reading a log does not have to look the code up.
    """

    def __init__(self, code: str, field: str, detail: str) -> None:
        if code not in REFUSALS:
            raise KeyError(
                f"{code!r} is not a registered refusal. Add it to findings.REFUSALS "
                "with the sentence an operator should read; the contract document "
                "and its test are generated from that registry, so a code invented "
                "at the raise site would be published nowhere and tested by nothing."
            )
        self.code = code
        self.field = field
        self.detail = detail
        super().__init__(f"{code} [{field}]: {REFUSALS[code]} — {detail}")


# --------------------------------------------------------------------------
# Refusals. The module will not do what it was asked, and names the field.
# --------------------------------------------------------------------------

REFUSAL_EMAIL_MALFORMED = "REFUSAL_EMAIL_MALFORMED"
REFUSAL_EMAIL_TAKEN = "REFUSAL_EMAIL_TAKEN"
REFUSAL_EMAIL_UNCHANGED = "REFUSAL_EMAIL_UNCHANGED"
REFUSAL_EXTERNAL_ID_TAKEN = "REFUSAL_EXTERNAL_ID_TAKEN"
REFUSAL_FIELD_BLANK = "REFUSAL_FIELD_BLANK"
REFUSAL_TEXT_HAS_CONTROL_CHARACTERS = "REFUSAL_TEXT_HAS_CONTROL_CHARACTERS"
REFUSAL_CUSTOMER_NOT_FOUND = "REFUSAL_CUSTOMER_NOT_FOUND"
REFUSAL_TENANT_NOT_FOUND = "REFUSAL_TENANT_NOT_FOUND"
REFUSAL_TERMS_NOT_ACCEPTED = "REFUSAL_TERMS_NOT_ACCEPTED"
REFUSAL_TERMS_TEXT_BLANK = "REFUSAL_TERMS_TEXT_BLANK"
REFUSAL_CHANNEL_UNKNOWN = "REFUSAL_CHANNEL_UNKNOWN"
REFUSAL_CHANNEL_REPEATED = "REFUSAL_CHANNEL_REPEATED"
REFUSAL_PASSWORD_NOT_GIVEN = "REFUSAL_PASSWORD_NOT_GIVEN"
REFUSAL_PASSWORD_TOO_SHORT = "REFUSAL_PASSWORD_TOO_SHORT"
REFUSAL_PASSWORD_WRONG = "REFUSAL_PASSWORD_WRONG"
REFUSAL_NO_CREDENTIAL = "REFUSAL_NO_CREDENTIAL"
REFUSAL_AUTHORISATION_MISSING = "REFUSAL_AUTHORISATION_MISSING"
REFUSAL_AUTHORISATION_AMBIGUOUS = "REFUSAL_AUTHORISATION_AMBIGUOUS"
REFUSAL_VALID_MINUTES_NOT_STATED = "REFUSAL_VALID_MINUTES_NOT_STATED"
REFUSAL_VALID_MINUTES_NOT_POSITIVE = "REFUSAL_VALID_MINUTES_NOT_POSITIVE"
REFUSAL_TOKEN_UNKNOWN = "REFUSAL_TOKEN_UNKNOWN"
REFUSAL_TOKEN_ALREADY_USED = "REFUSAL_TOKEN_ALREADY_USED"
REFUSAL_TOKEN_CANCELLED = "REFUSAL_TOKEN_CANCELLED"
REFUSAL_TOKEN_EXPIRED = "REFUSAL_TOKEN_EXPIRED"
REFUSAL_EXPIRED_IS_DERIVED = "REFUSAL_EXPIRED_IS_DERIVED"
REFUSAL_STATE_UNKNOWN = "REFUSAL_STATE_UNKNOWN"
REFUSAL_INSTANT_MALFORMED = "REFUSAL_INSTANT_MALFORMED"
REFUSAL_DOCUMENT_UNREADABLE = "REFUSAL_DOCUMENT_UNREADABLE"
REFUSAL_CONSTRAINT = "REFUSAL_CONSTRAINT"

REFUSALS: dict[str, str] = {
    REFUSAL_EMAIL_MALFORMED: (
        "The email address does not look like one -- it needs an @ with something "
        "before it and something after it. The rule is the one the sibling pass "
        "module ships for a holder's address, copied; nothing more is checked, "
        "because nothing more can be checked without sending mail."
    ),
    REFUSAL_EMAIL_TAKEN: (
        "Another customer of this operator already carries this email address, "
        "compared without regard to case -- the database's lower() under the "
        "collation the column carries, the same expression the unique index is on; "
        "nothing in Python folds an address. One address, one account per operator: "
        "the address is how a customer is found, and two accounts behind it would "
        "make a password reset ambiguous. Nothing is written."
    ),
    REFUSAL_EMAIL_UNCHANGED: (
        "The new address is the customer's current one, as the store compares "
        "addresses -- the same answer create-account would give. There is nothing "
        "to confirm and nothing to change."
    ),
    REFUSAL_EXTERNAL_ID_TAKEN: (
        "Another customer of this operator already carries this operator-facing "
        "reference. It is optional -- a customer registering themselves has none "
        "-- and unique where given."
    ),
    REFUSAL_FIELD_BLANK: (
        "A required value is blank or malformed. The field is named beside this "
        "code, with what was expected."
    ),
    REFUSAL_TEXT_HAS_CONTROL_CHARACTERS: (
        "A text value carries a control character (a newline, a tab, a NUL). Names, "
        "phones, references and who-did-this fields are one line each; a value that "
        "would break a log line or a screen is refused rather than stored."
    ),
    REFUSAL_CUSTOMER_NOT_FOUND: (
        "No customer of this operator has the id or the address given."
    ),
    REFUSAL_TENANT_NOT_FOUND: (
        "No tenant row has the id given. The first write for a tenant -- "
        "create-account -- reads the tenant row before it writes, so an id nobody "
        "seeded is refused by name rather than met at the database's foreign key."
    ),
    REFUSAL_TERMS_NOT_ACCEPTED: (
        "An account is created with its terms accepted, in the same transaction, "
        "and no acceptance was given: the version, the text shown, or who accepted "
        "is missing. Every customer accepts the terms when the account is created; "
        "an account with no acceptance would be an account nobody agreed to."
    ),
    REFUSAL_TERMS_TEXT_BLANK: (
        "The text shown for the terms, or for one of the channels, is blank. An "
        "acceptance records WHAT was shown, in the words shown; a blank is a "
        "boolean in disguise and is worth nothing the first time the terms change."
    ),
    REFUSAL_CHANNEL_UNKNOWN: (
        "A consent channel was named that this module does not have. The channels "
        "are published in the contract; a channel is a thing consent is asked for "
        "by name, and a new one is a migration, not a free-text value."
    ),
    REFUSAL_CHANNEL_REPEATED: (
        "The same consent channel was given twice in one acceptance. Each channel "
        "carries one text shown."
    ),
    REFUSAL_PASSWORD_NOT_GIVEN: (
        "No password was given. It is read from the environment variable named "
        "beside this code, never from an argument: arguments are visible in `ps` "
        "to every user on the machine, and a password on a command line is a "
        "password in the shell's history."
    ),
    REFUSAL_PASSWORD_TOO_SHORT: (
        "The password is shorter than the minimum this module states. There is no "
        "other rule -- no character classes, no dictionary -- because length is the "
        "only rule that measurably helps and the others measurably hurt."
    ),
    REFUSAL_PASSWORD_WRONG: (
        "The password given does not match the customer's credential. Compared in "
        "constant time against the stored scrypt hash with the parameters stored "
        "beside it; the hash and the password appear in no output."
    ),
    REFUSAL_NO_CREDENTIAL: (
        "This customer has no credential: no password has been set. A password "
        "reset resets a password that exists, and an email change authorised by "
        "the current password needs one -- so both are refused by name here. THIS "
        "IS NOT 'NO PASSWORD REQUIRED': whether a password should exist is the "
        "caller's knowledge, not this module's. Set one with set-password."
    ),
    REFUSAL_AUTHORISATION_MISSING: (
        "An email change requires EITHER the customer's current password, verified "
        "by this module, OR an explicit caller authorisation stated in --by. Neither "
        "was given. Which of the two was used is stored, because 'who authorised "
        "this change' is the question asked after a disputed account takeover."
    ),
    REFUSAL_AUTHORISATION_AMBIGUOUS: (
        "Both a password and a caller authorisation (--by) were given for one email "
        "change. Exactly one is stored as the authorisation, so exactly one may be "
        "given; give the one that is true."
    ),
    REFUSAL_VALID_MINUTES_NOT_STATED: (
        "How long the token may wait to be used is not stated. It is refused rather "
        "than defaulted: this module refuses guessed defaults, and the window is the "
        "caller's to state."
    ),
    REFUSAL_VALID_MINUTES_NOT_POSITIVE: (
        "The token's window is zero or negative minutes, so there is no instant at "
        "which it could be used. State a positive whole number of minutes."
    ),
    REFUSAL_TOKEN_UNKNOWN: (
        "No pending email change or password reset of this operator matches the "
        "token presented. The token itself is never rendered and never stored: "
        "only its SHA-256 is compared."
    ),
    REFUSAL_TOKEN_ALREADY_USED: (
        "This token was already used. A token is used once; the detail names when. "
        "Nothing is written. Distinct from an unknown token on purpose: a second "
        "use of a real token is the shape of a replay, and an operator reading the "
        "log should be able to tell the two apart."
    ),
    REFUSAL_TOKEN_CANCELLED: (
        "This token was cancelled -- superseded by a later one for the same "
        "customer, or cancelled by name. The detail names when and why. Nothing is "
        "written."
    ),
    REFUSAL_TOKEN_EXPIRED: (
        "This token's window has passed: the instant given is at or past its "
        "expires_at. Derived; nobody typed it. Nothing is written; issue a new one."
    ),
    REFUSAL_EXPIRED_IS_DERIVED: (
        "A token's 'expired' is derived from its expires_at against the instant "
        "asked about and is never typed by anyone."
    ),
    REFUSAL_STATE_UNKNOWN: (
        "The state named is not one this module has."
    ),
    REFUSAL_INSTANT_MALFORMED: (
        "An instant does not parse as ISO 8601 with an offset, or carries none. A "
        "naive instant would be read as the running machine's local time, which is "
        "a property of the server and not of the customer."
    ),
    REFUSAL_DOCUMENT_UNREADABLE: (
        "A file named on the command line -- the text shown for the terms or for a "
        "channel -- could not be read: missing, not a regular file, unreadable, or "
        "not text. The detail names the path and what went wrong."
    ),
    REFUSAL_CONSTRAINT: (
        "The database refused the write by a constraint the module did not catch "
        "first. Named by its constraint so it is a refusal and not a traceback; two "
        "writers racing end here."
    ),
}


# --------------------------------------------------------------------------
# Verifications. The password check answers, and the answer has a name.
# --------------------------------------------------------------------------

VERIFIED = "VERIFIED"
WRONG_PASSWORD = "WRONG_PASSWORD"
NO_CREDENTIAL = "NO_CREDENTIAL"

VERIFICATIONS: dict[str, str] = {
    VERIFIED: "The password matches the customer's credential.",
    WRONG_PASSWORD: "The password does not match the customer's credential.",
    NO_CREDENTIAL: (
        "This customer has no credential: no password has been set. Not verified -- "
        "and NOT 'no password required'. Whether a password should exist is the "
        "caller's knowledge; this module records that one was set and never infers "
        "why one was not."
    ),
}

#: The sentence every non-verified answer carries, so a caller reading the JSON
#: cannot read a named non-answer as permission.
NOT_VERIFIED_MEANS = (
    "Not verified means the person has not proven they are this customer. It never "
    "means the check may be skipped."
)
