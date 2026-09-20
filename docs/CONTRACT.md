# The contract — Open Parking AI customer account

This module answers one question and nothing else:

> **Is this person who they say they are, and what have they agreed to?**

Identity and recorded consent. No cards, no money, no passes, no vehicles, no
stays.

> **Every block below marked GENERATED is derived** — from the guarantee
> registry, the refusal and verification registries, the enums that implement
> the options, the parameters the module states, and the command line's own
> parser. No number and no sentence inside one is typed.
> `scripts/generate_contract.py --check` fails if one was edited by hand, and
> `tests/test_contract_is_generated.py` plants values contradicting the prose
> and requires the prose to change -- because generation is not verification,
> and a template whose prose is fixed everywhere except the holes agrees with
> itself perfectly.

## What is NOT in this module

Stated first, so nothing here is later read as a promise:

- **No HTTP surface, no screens.** A command line against a store, and a
  package an integrator embeds. Whatever surface exists is theirs.
- **No email and no SMS is sent.** A token is minted, recorded, and returned
  once with the address it is for. Delivering it is the caller's.
- **No cards, no processor, no money field of any kind.** This module does not
  know whether anybody is charged. A password exists because the caller set
  one; the reason is the caller's knowledge, and this module never infers it.
- **No pass, no vehicle, no stay.** Nothing here binds a person to a car or a
  car to a garage.
- **No account spanning operators.** One operator, one account. A customer
  parking with two operators has two accounts, each scoped to its tenant.
- **No one-time holder link.** The no-charge path has no account here at all;
  the sibling pass module already ships that link and it is untouched. The
  tokens here reset a password that exists and confirm a new address.

## The shape

**The email is not the key.** A customer has a stable id; the email is an
attribute on it, unique per operator without regard to case, and it can
change. That is what makes "change email" and "forgot password" both possible
at once. An account keyed on the email is orphaned the first time it changes.

**The credential is its own row, and its absence has a name.** It exists only
where the caller set a password. A customer with none is answered
`NO_CREDENTIAL` on a verification, `REFUSAL_NO_CREDENTIAL` on a reset or a
password-authorised change, `absent` on a read -- by name, never as an error,
and never as "no password required".

**The two recovery paths are not circular.** A password reset is delivered to
the CURRENT address, read from the row and never supplied. An email change
takes effect only when the NEW address presents the token back; until then
the old address is the address. Who authorised the change -- the current
password, verified here, or an explicit caller -- is stored, exactly one, and
travels onto the history row.

<!-- GENERATED:email_history -->
Email changes accumulate and are read oldest first in the order `changed_at`, `created_at`, `id`: the row for the change now in effect is the latest by `changed_at`, and two changes sharing an instant are ordered by `id` -- deterministically, the same way on every read, but ARBITRARILY: that order means nothing.
<!-- END:email_history -->

**Consent is one acceptance, itemised.** The version, the text shown, who and
when -- and for each channel consented to, the text shown for it. Append-only
by grant. An account is created with its first acceptance or not at all.

**`external_id` is optional.** An operator has a reference to supply; a
customer registering themselves has none. Unique where given.

## The guarantees

<!-- GENERATED:guarantees -->
| id | what is guaranteed |
|---|---|
| **G1** | Every test module contributes at least one registered guarantee, derived from the filesystem and read from the AST -- so a module cannot be added, skipped or deleted without a guard noticing. A module that PLANTS a defect may not be excused at all. |
| **G2** | docs/CONTRACT.md is GENERATED from this registry and from the registries that implement it, and its prose is derived rather than fixed: a value that contradicts a published sentence changes the sentence, because generation is not verification. |
| **G3** | A plaintext password or token is NEVER STORED and NEVER RENDERED TWICE. A password is stored as a scrypt hash with its salt and parameters and is returned by nothing; a token is stored as its SHA-256 and returned exactly once, by the call that minted it -- not by a read, not by a refusal. The scan reads every column of every table in the catalogue, with the digest as its positive control. |
| **G4** | NO MONEY-SHAPED, CARD-SHAPED OR CHARGE-SHAPED FIELD EXISTS ANYWHERE IN THE MODULE: not a column in the catalogue, not a field on any answer class, not a key in the command line's JSON. This module has no view of whether anybody is charged and never infers one; the word lists are the instrument and a planted fee_cents is caught. |
| **G5** | A customer with no credential row is answered BY NAME -- NO_CREDENTIAL on a verification, REFUSAL_NO_CREDENTIAL on a reset or a password-authorised change, 'absent' on a read -- never by a crash, never by a silent false, and never as 'no password required': every such answer carries the sentence saying so. |
| **G6** | An expired token and an already-used token are each refused BY NAME, distinctly from an unknown one and from a cancelled one. Expiry is derived from the stated expires_at against the instant given and is never typed; a token superseded by a newer one is cancelled with that reason; a spent token spends once, and the spend asserts one row. The state a door READS is parsed, not trusted: a row carrying 'expired', or any state this module does not have, is refused by name when presented -- never read as live, never read as spent. |
| **G7** | Every table this module's migration creates carries a tenant column, ENABLE and FORCE row-level security and an isolation policy -- read from the database catalogue, never from a list of table names -- and every customer reference is half of a composite tenant key. A second tenant reads none of the first tenant's rows and updates none of them, on every table, and the connection is proven able to be stopped before that is believed. |
| **G8** | An email change does not take effect until confirmed at the NEW address, and the old address keeps working until it does. Who authorised the change is STORED: the customer's current password, verified by this module, or an explicit caller authorisation -- exactly one, refused by name when neither or both is given -- and the authorisation travels onto the history row. The history is read in ONE STATED ORDER -- changed_at, created_at, id -- so two changes sharing an instant come back the same way on every read, ordered by id: deterministically, and ARBITRARILY, and the contract says so. |
| **G9** | A password reset is delivered to the customer's CURRENT address, read from the row at issue and never supplied by the caller: the command line has no option for it, and a pending, unconfirmed email change does not move it. A reset resets a password that exists. |
| **G10** | The email history, the terms acceptances and their channels are APPEND-ONLY BY GRANT: the application role holds SELECT and INSERT on them and nothing else, holds DELETE on no table in the schema, and the set of append-only tables is read from the catalogue and is exactly those three -- with a table the role CAN update accepting an update in the same run, as the control that the grant check can see a grant. |
| **G11** | Consent is ONE acceptance, itemised: it records the terms version, the text shown, who accepted and when, and for each channel consented to the text shown for it -- never a boolean. An account is created with its first acceptance in the same transaction or not at all; a blank text, an unknown channel and a repeated channel are each refused by name. Acceptances ACCUMULATE: a later acceptance, of a new version or of the same one again, is a further row and never a rewrite, and the row current for a version is the one with the latest accepted_at. They are read in ONE STATED ORDER -- accepted_at, created_at, id -- so two acceptances sharing an instant come back the same way on every read, ordered by id: deterministically, and ARBITRARILY, and the contract says so. Every channel row carries its own consented_by and consented_at, stated and never defaulted; a channel written with its acceptance carries the acceptance's own instant and name -- one clock. |
| **G12** | A password is hashed with the standard library's scrypt under parameters that are STATED, never defaulted, and STORED beside every hash; verification reads the row's parameters, so a row hashed under different parameters still verifies and raising them invalidates nothing. The comparison is constant-time, and the one rule on a password is a stated minimum length. |
| **G13** | Nothing real is in the tree: no card-shaped value, no email address that is not obviously invented, and no name from the maintainer's other software, in any tracked file, tests and fixtures included -- swept in Python over the file set git reports, with each sweep proven to fire on its probe first. |
| **G14** | The command line refuses, never tracebacks: every Refused reaches the boundary as {refused, field, detail} with exit 3; a machine that is not set up -- no DSN, a database that does not connect -- is one sentence on stderr with exit 2; a malformed instant, an unreadable text file and a malformed channel pair are each refused by name. |
| **G15** | This module has no HTTP surface and sends nothing: no web framework, no HTTP server and no mail or SMS client is imported anywhere in the package, read from the AST of every source file -- a planted import goes red. |
| **G16** | THE FOLD IS THE DATABASE'S, AND THE STORE STATES WHAT IT REQUIRES OF IT. Whether two addresses are one is answered by lower(email) under the collation customers.email carries -- the unique index's own expression -- and by nothing in Python, so every door gives the same answer; and migration 0001 REFUSES TO APPLY, by name and before creating anything, on a database whose default collation folds ASCII only (libc with LC_CTYPE C or POSIX, measured) or comes from a locale provider the fold was not measured under. The suite proves the refusal fires on a C-collated database in the same cluster, beside the apply that proceeds. |
| **G17** | A CONTROL THAT CRASHED DID NOT FIRE. scripts/fail_controls.py counts a plant as fired only when its target's tests RAN AND FAILED; a target that errored, failed to collect or did not run under the plant is reported NOT A CONTROL, distinctly from RED, and fails the run -- so the instrument cannot go falsely green on a plant that broke the interpreter instead of the subject. |

That is 17 guarantees. Every one of them has a fail control that has been proven to fire, and the count above is derived from the registry rather than typed here.
<!-- END:guarantees -->

## The password

<!-- GENERATED:password -->
- **KDF:** `scrypt`, from the standard library (`hashlib.scrypt`); no dependency.
- **Parameters written today:** n = 131072 (2^17), r = 8, p = 1, dklen = 64; salt 16 bytes from the CSPRNG. Measured by `scripts/measure_scrypt.py`, not chosen; stored beside every hash, so a row written under other values still verifies and raising them invalidates nothing.
- **The one rule on a password:** at least 12 bytes of UTF-8. No character classes, no dictionary.
- **Where a password is read from:** the environment variable `CUSTOMER_ACCOUNT_PASSWORD`, never an argument.
- **A token's typed states:** `issued`, `redeemed`, `cancelled`; `expired` is derived from `expires_at` and cannot be typed.
<!-- END:password -->

## The verification answer

`verify-password` answers with one of three named outcomes. It is the only
command whose exit status carries an answer rather than a result: 0 verified,
1 not.

<!-- GENERATED:verifications -->
| outcome | what it means |
|---|---|
| `VERIFIED` | The password matches the customer's credential. |
| `WRONG_PASSWORD` | The password does not match the customer's credential. |
| `NO_CREDENTIAL` | This customer has no credential: no password has been set. Not verified -- and NOT 'no password required'. Whether a password should exist is the caller's knowledge; this module records that one was set and never infers why one was not. |

Every outcome but the first carries this sentence: *Not verified means the person has not proven they are this customer. It never means the check may be skipped.*
<!-- END:verifications -->

## Consent channels

<!-- GENERATED:channels -->
One acceptance, itemised. The channels consent may be recorded for, by name:

- `email`
- `sms`

That is 2 channels. A third is a migration and a contract change, not a value somebody types.

Acceptances accumulate and are read oldest first in the order `accepted_at`, `created_at`, `id`: the row current for a version is the latest by `accepted_at`, and two acceptances sharing an instant are ordered by `id` -- deterministically, the same way on every read, but ARBITRARILY: that order means nothing.
<!-- END:channels -->

## Refusals

The module refuses when it cannot do what it was asked without guessing, and
names the field. A refusal is a first-class result, not an error, and it
writes nothing: every one is the JSON `{"refused", "field", "detail"}` on
the command line with exit 3, never a traceback.

<!-- GENERATED:refusals -->
| code | when, and what to do about it |
|---|---|
| `REFUSAL_AUTHORISATION_AMBIGUOUS` | Both a password and a caller authorisation (--by) were given for one email change. Exactly one is stored as the authorisation, so exactly one may be given; give the one that is true. |
| `REFUSAL_AUTHORISATION_MISSING` | An email change requires EITHER the customer's current password, verified by this module, OR an explicit caller authorisation stated in --by. Neither was given. Which of the two was used is stored, because 'who authorised this change' is the question asked after a disputed account takeover. |
| `REFUSAL_CHANNEL_REPEATED` | The same consent channel was given twice in one acceptance. Each channel carries one text shown. |
| `REFUSAL_CHANNEL_UNKNOWN` | A consent channel was named that this module does not have. The channels are published in the contract; a channel is a thing consent is asked for by name, and a new one is a migration, not a free-text value. |
| `REFUSAL_CONSTRAINT` | The database refused the write by a constraint the module did not catch first. Named by its constraint so it is a refusal and not a traceback; two writers racing end here. |
| `REFUSAL_CUSTOMER_NOT_FOUND` | No customer of this operator has the id or the address given. |
| `REFUSAL_DOCUMENT_UNREADABLE` | A file named on the command line -- the text shown for the terms or for a channel -- could not be read: missing, not a regular file, unreadable, or not text. The detail names the path and what went wrong. |
| `REFUSAL_EMAIL_MALFORMED` | The email address does not look like one -- it needs an @ with something before it and something after it. The rule is the one the sibling pass module ships for a holder's address, copied; nothing more is checked, because nothing more can be checked without sending mail. |
| `REFUSAL_EMAIL_TAKEN` | Another customer of this operator already carries this email address, compared without regard to case -- the database's lower() under the collation the column carries, the same expression the unique index is on; nothing in Python folds an address. One address, one account per operator: the address is how a customer is found, and two accounts behind it would make a password reset ambiguous. Nothing is written. |
| `REFUSAL_EMAIL_UNCHANGED` | The new address is the customer's current one, as the store compares addresses -- the same answer create-account would give. There is nothing to confirm and nothing to change. |
| `REFUSAL_EXPIRED_IS_DERIVED` | A token's 'expired' is derived from its expires_at against the instant asked about and is never typed by anyone. A token row found carrying 'expired' as its state -- which the schema's CHECK refuses, and an owner can alter a schema -- is refused by this name when presented, never read as live and never read as spent. Nothing is written. |
| `REFUSAL_EXTERNAL_ID_TAKEN` | Another customer of this operator already carries this operator-facing reference. It is optional -- a customer registering themselves has none -- and unique where given. |
| `REFUSAL_FIELD_BLANK` | A required value is blank or malformed. The field is named beside this code, with what was expected. |
| `REFUSAL_INSTANT_MALFORMED` | An instant does not parse as ISO 8601 with an offset, or carries none. A naive instant would be read as the running machine's local time, which is a property of the server and not of the customer. |
| `REFUSAL_NO_CREDENTIAL` | This customer has no credential: no password has been set. A password reset resets a password that exists, and an email change authorised by the current password needs one -- so both are refused by name here. THIS IS NOT 'NO PASSWORD REQUIRED': whether a password should exist is the caller's knowledge, not this module's. Set one with set-password. |
| `REFUSAL_PASSWORD_NOT_GIVEN` | No password was given. It is read from the environment variable named beside this code, never from an argument: arguments are visible in `ps` to every user on the machine, and a password on a command line is a password in the shell's history. |
| `REFUSAL_PASSWORD_TOO_SHORT` | The password is shorter than the minimum this module states. There is no other rule -- no character classes, no dictionary -- because length is the only rule that measurably helps and the others measurably hurt. |
| `REFUSAL_PASSWORD_WRONG` | The password given does not match the customer's credential. Compared in constant time against the stored scrypt hash with the parameters stored beside it; the hash and the password appear in no output. |
| `REFUSAL_STATE_UNKNOWN` | A token row found carrying a state this module does not have -- not issued, redeemed or cancelled -- is refused by this name when presented. The states are published in the contract; a row outside them was written past the schema, and the module says so rather than guessing which state it meant. Nothing is written. |
| `REFUSAL_TENANT_NOT_FOUND` | No tenant row has the id given. The first write for a tenant -- create-account -- reads the tenant row before it writes, so an id nobody seeded is refused by name rather than met at the database's foreign key. |
| `REFUSAL_TERMS_NOT_ACCEPTED` | An account is created with its terms accepted, in the same transaction, and no acceptance was given: the version, the text shown, or who accepted is missing. Every customer accepts the terms when the account is created; an account with no acceptance would be an account nobody agreed to. |
| `REFUSAL_TERMS_TEXT_BLANK` | The text shown for the terms, or for one of the channels, is blank. An acceptance records WHAT was shown, in the words shown; a blank is a boolean in disguise and is worth nothing the first time the terms change. |
| `REFUSAL_TEXT_HAS_CONTROL_CHARACTERS` | A text value carries a control character (a newline, a tab, a NUL). Names, phones, references and who-did-this fields are one line each; a value that would break a log line or a screen is refused rather than stored. |
| `REFUSAL_TOKEN_ALREADY_USED` | This token was already used. A token is used once; the detail names when. Nothing is written. Distinct from an unknown token on purpose: a second use of a real token is the shape of a replay, and an operator reading the log should be able to tell the two apart. |
| `REFUSAL_TOKEN_CANCELLED` | This token was cancelled -- superseded by a later one for the same customer, or cancelled by name. The detail names when and why. Nothing is written. |
| `REFUSAL_TOKEN_EXPIRED` | This token's window has passed: the instant given is at or past its expires_at. Derived; nobody typed it. Nothing is written; issue a new one. |
| `REFUSAL_TOKEN_UNKNOWN` | No pending email change or password reset of this operator matches the token presented. The token itself is never rendered and never stored: only its SHA-256 is compared. |
| `REFUSAL_VALID_MINUTES_NOT_POSITIVE` | The token's window is zero or negative minutes, so there is no instant at which it could be used. State a positive whole number of minutes. |
| `REFUSAL_VALID_MINUTES_NOT_STATED` | How long the token may wait to be used is not stated. It is refused rather than defaulted: this module refuses guessed defaults, and the window is the caller's to state. |

That is 29 refusals, every one raised somewhere in the package and none raised anywhere that is not here (a test reads the raise sites from the AST).
<!-- END:refusals -->

## The command line

<!-- GENERATED:commands -->
| command | options | what it does |
|---|---|---|
| `create-account` | `--tenant` `--email` `--external-id` `--name` `--phone` `--by` `--at` `--terms-version` `--terms-shown` `--channel` | the customer row and its first terms acceptance, together |
| `show-account` | `--tenant` `--customer` `--email` | read an account; renders no hash, no salt, no token |
| `show-acceptances` | `--tenant` `--customer` | every acceptance the customer has made, texts included |
| `record-terms-acceptance` | `--tenant` `--customer` `--by` `--at` `--terms-version` `--terms-shown` `--channel` | a later acceptance, when the terms change |
| `set-password` | `--tenant` `--customer` `--by` `--at` | set or replace the credential; the password is read from CUSTOMER_ACCOUNT_PASSWORD |
| `verify-password` | `--tenant` `--customer` | check the password in CUSTOMER_ACCOUNT_PASSWORD: exit 0 verified, 1 not -- a wrong password or no credential, each by name |
| `start-email-change` | `--tenant` `--customer` `--new-email` `--valid-minutes` `--at` `--by` | mint the token the new address presents back; authorised by the current password in CUSTOMER_ACCOUNT_PASSWORD or by --by, exactly one |
| `confirm-email-change` | `--tenant` `--token` `--at` | the new address presents the token: the change takes effect now |
| `start-password-reset` | `--tenant` `--customer` `--valid-minutes` `--by` `--at` | mint the token the CURRENT address receives; it resets a password that exists |
| `consume-password-reset` | `--tenant` `--token` `--at` | present the reset token with the new password in CUSTOMER_ACCOUNT_PASSWORD |

That is 10 commands, every one against the store (`CUSTOMER_ACCOUNT_DSN`), and none an HTTP surface. The application connects as the role `customer_account_app` and sets `customer_account.tenant_id` per transaction.

Exit status: 0 done or verified; 1 not verified (`verify-password` only); 2 the machine's configuration, one sentence on stderr; 3 the request was refused, as JSON.
<!-- END:commands -->

## The store

Row-level security from migration 0001: every table carries a tenant column,
`ENABLE`, `FORCE` and an isolation policy, and every customer reference is
half of a composite tenant key. The application connects as a role created
`NOSUPERUSER NOBYPASSRLS`; the isolation tests assert they are connected as a
role that COULD be stopped before they assert that it was. The three
histories -- email changes, acceptances, their channels -- are append-only by
grant, and the role holds DELETE on no table.

**The fold is the database's.** "Unique per operator without regard to case"
is `lower(email)` under the collation `customers.email` carries -- the
expression the unique index is on and the one every door asks. Nothing in
Python folds an address. What that fold is depends on the database: measured
on PostgreSQL 16, the libc provider with `LC_CTYPE` `C` or `POSIX` folds ASCII
letters only, so `Élodie@` and `élodie@` would be two accounts there; every
other libc `LC_CTYPE` and the ICU provider fold beyond ASCII. Which code
points fold, beyond that, differs between platforms and providers (the gate
measured `İ` folding differently on glibc, macOS and ICU) -- the module
promises the database's answer, not a table of its own.

### What the migration requires of the database

<!-- GENERATED:install -->
| the migration refuses, by name | when |
|---|---|
| `MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY` | this database's default collation folds case for ASCII letters only, so two spellings of one address that differ in the case of an accented letter would be two accounts of one operator. This module requires a database whose lower() folds beyond ASCII: create it with a UTF-8 LC_CTYPE (for example en_US.UTF-8) or with the ICU locale provider, and apply this migration again. Nothing was created. |
| `MIGRATION_REFUSAL_LOCALE_PROVIDER_UNMEASURED` | this database's default collation comes from a locale provider this module's case fold has not been measured under (libc and ICU were). It is refused rather than assumed to fold beyond ASCII. Nothing was created. |

That is 2 named refusals in `0001_tenants_customers_credentials_consent_and_rls.sql`'s pre-flight, read from the file. Each is raised BEFORE anything is created, inside the migration's own transaction, so a refused apply leaves the database as it found it. The requirement is an install requirement and not a caveat: `customers.email` carries no collation of its own, so the fold that makes one address one account is the database's default collation, and the pre-flight judges exactly that.
<!-- END:install -->

## Versioning

This is version 1 of the contract. Adding a field, a command or a refusal is
additive and does not bump it; removing, renaming or redefining one does.

---

Built by 72 Knots Method by 72Knots.ai
