"""The canonical registry of what this module guarantees.

**ONE SOURCE, THREE CONSUMERS.** ``conftest.py`` requires every registered id to
have RUN; ``scripts/fail_controls.py`` requires every registered id to have a
control PROVEN TO FAIL and refuses to run if one has none; ``docs/CONTRACT.md``
is generated from this file. A guarantee therefore cannot be quietly dropped from
any of the three, and a number of them cannot go stale in a comment, because
nothing types the number anywhere.

**A GUARANTEE IS A SENTENCE SOMEBODY COULD ACT ON.** Not "the loader validates
input" -- that is a description of a mechanism. "A plaintext password or token
is never stored and never returned twice" is a claim with a failing case, and
the failing case is what the control plants.
"""

from __future__ import annotations

GUARANTEES: dict[str, str] = {
    "G1": (
        "Every test module contributes at least one registered guarantee, derived "
        "from the filesystem and read from the AST -- so a module cannot be added, "
        "skipped or deleted without a guard noticing. A module that PLANTS a defect "
        "may not be excused at all."
    ),
    "G2": (
        "docs/CONTRACT.md is GENERATED from this registry and from the registries "
        "that implement it, and its prose is derived rather than fixed: a value that "
        "contradicts a published sentence changes the sentence, because generation "
        "is not verification."
    ),
    "G3": (
        "A plaintext password or token is NEVER STORED and NEVER RENDERED TWICE. A "
        "password is stored as a scrypt hash with its salt and parameters and is "
        "returned by nothing; a token is stored as its SHA-256 and returned exactly "
        "once, by the call that minted it -- not by a read, not by a refusal. The "
        "scan reads every column of every table in the catalogue, with the digest as "
        "its positive control."
    ),
    "G4": (
        "NO MONEY-SHAPED, CARD-SHAPED OR CHARGE-SHAPED FIELD EXISTS ANYWHERE IN THE "
        "MODULE: not a column in the catalogue, not a field on any answer class, not "
        "a key in the command line's JSON. This module has no view of whether anybody "
        "is charged and never infers one; the word lists are the instrument and a "
        "planted fee_cents is caught."
    ),
    "G5": (
        "A customer with no credential row is answered BY NAME -- NO_CREDENTIAL on a "
        "verification, REFUSAL_NO_CREDENTIAL on a reset or a password-authorised "
        "change, 'absent' on a read -- never by a crash, never by a silent false, and "
        "never as 'no password required': every such answer carries the sentence "
        "saying so."
    ),
    "G6": (
        "An expired token and an already-used token are each refused BY NAME, "
        "distinctly from an unknown one and from a cancelled one. Expiry is derived "
        "from the stated expires_at against the instant given and is never typed; a "
        "token superseded by a newer one is cancelled with that reason; a spent token "
        "spends once, and the spend asserts one row. The state a door READS is parsed, "
        "not trusted: a row carrying 'expired', or any state this module does not have, "
        "is refused by name when presented -- never read as live, never read as spent."
    ),
    "G7": (
        "Every table this module's migration creates carries a tenant column, ENABLE "
        "and FORCE row-level security and an isolation policy -- read from the "
        "database catalogue, never from a list of table names -- and every customer "
        "reference is half of a composite tenant key. A second tenant reads none of "
        "the first tenant's rows and updates none of them, on every table, and the "
        "connection is proven able to be stopped before that is believed."
    ),
    "G8": (
        "An email change does not take effect until confirmed at the NEW address, and "
        "the old address keeps working until it does. Who authorised the change is "
        "STORED: the customer's current password, verified by this module, or an "
        "explicit caller authorisation -- exactly one, refused by name when neither "
        "or both is given -- and the authorisation travels onto the history row. The "
        "history is read in ONE STATED ORDER -- published in this contract from the "
        "code that reads it, never written out here -- so two changes sharing an "
        "instant come back the same way on every read, ordered by the last column of "
        "that order: deterministically, and ARBITRARILY, and the contract says so."
    ),
    "G9": (
        "A password reset is delivered to the customer's CURRENT address, read from "
        "the row at issue and never supplied by the caller: the command line has no "
        "option for it, and a pending, unconfirmed email change does not move it. A "
        "reset resets a password that exists."
    ),
    "G10": (
        "The email history, the terms acceptances and their channels are APPEND-ONLY "
        "BY GRANT: the application role holds SELECT and INSERT on them and nothing "
        "else, holds DELETE on no table in the schema, and the set of append-only "
        "tables is read from the catalogue and is exactly those three -- with a table "
        "the role CAN update accepting an update in the same run, as the control that "
        "the grant check can see a grant."
    ),
    "G11": (
        "Consent is ONE acceptance, itemised: it records the terms version, the text "
        "shown, who accepted and when, and for each channel consented to the text "
        "shown for it -- never a boolean. An account is created with its first "
        "acceptance in the same transaction or not at all; a blank text, an unknown "
        "channel and a repeated channel are each refused by name. Acceptances "
        "ACCUMULATE: a later acceptance, of a new version or of the same one again, is "
        "a further row and never a rewrite, and the row current for a version is the "
        "one with the latest accepted_at. They are read in ONE STATED ORDER -- "
        "published in this contract from the code that reads them, never written out "
        "here -- so two acceptances sharing an instant come back the same way on every "
        "read, ordered by the last column of that order: deterministically, and "
        "ARBITRARILY, and the contract says so. Every channel row carries its own "
        "consented_by and consented_at, stated and never defaulted; a channel written "
        "with its acceptance carries the acceptance's own instant and name -- one clock."
    ),
    "G12": (
        "A password is hashed with the standard library's scrypt under parameters "
        "that are STATED, never defaulted, and STORED beside every hash; verification "
        "reads the row's parameters, so a row hashed under different parameters still "
        "verifies and raising them invalidates nothing. The comparison is "
        "constant-time, and the one rule on a password is a stated minimum length. "
        "The KDF a row carries is parsed, not trusted: a credential row carrying a KDF "
        "this module does not have is refused BY NAME when a password is checked "
        "against it, through both doors that check one -- never a traceback, never "
        "an answer."
    ),
    "G13": (
        "Nothing real is in the tree: no card-shaped value, no email address that is "
        "not obviously invented, and no name from the maintainer's other software, in "
        "any tracked file, tests and fixtures included -- swept in Python over the file "
        "set git reports, with each sweep proven to fire on its probe first."
    ),
    "G14": (
        "The command line refuses, never tracebacks: every Refused reaches the "
        "boundary as {refused, field, detail} with exit 3; a machine that is not set "
        "up -- no DSN, a database that does not connect -- is one sentence on stderr "
        "with exit 2; a malformed instant, an unreadable text file and a malformed "
        "channel pair are each refused by name."
    ),
    "G15": (
        "This module has no HTTP surface and sends nothing: no web framework, no HTTP "
        "server and no mail or SMS client is imported anywhere in the package, read "
        "from the AST of every source file -- a planted import goes red."
    ),
    "G16": (
        "THE FOLD IS THE DATABASE'S, AND THE STORE STATES WHAT IT REQUIRES OF IT. "
        "Whether two addresses are one is answered by lower(email) under the collation "
        "customers.email carries -- the unique index's own expression -- and by nothing "
        "in Python, so every door gives the same answer; and migration 0001 REFUSES TO "
        "APPLY, by name and before creating anything, on a database whose default "
        "collation folds ASCII only (libc with LC_CTYPE C or POSIX, measured) or comes "
        "from a locale provider the fold was not measured under. The suite proves the "
        "refusal fires on a C-collated database in the same cluster, beside the apply "
        "that proceeds."
    ),
    "G17": (
        "A CONTROL THAT CRASHED DID NOT FIRE. scripts/fail_controls.py counts a plant as "
        "fired only when its target's tests RAN AND FAILED; a target that errored, "
        "failed to collect or did not run under the plant is reported NOT A CONTROL, "
        "distinctly from RED, and fails the run -- so the instrument cannot go falsely "
        "green on a plant that broke the interpreter instead of the subject."
    ),
}


def guarantee_ids() -> tuple[str, ...]:
    """Sorted numerically, not lexically -- G10 follows G9, not G1."""
    return tuple(sorted(GUARANTEES, key=lambda g: int(g[1:])))


#: Naming an id here lets the suite finish with that guarantee unproven. It is a
#: DECISION somebody writes down, never a default -- CI names nothing, and a
#: guarantee that did not run and pass fails the run.
ALLOW_ENV = "CUSTOMER_ACCOUNT_ALLOW_UNRUN"
