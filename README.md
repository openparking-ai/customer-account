# Open Parking AI — customer account

**Is this person who they say they are, and what have they agreed to?** That
one question, and nothing else. Identity and recorded consent: no cards, no
money, no passes, no vehicles, no stays.

Standalone. It runs with no parking system around it and no platform; the
package that hashes and verifies a password has no dependencies at all, and
the store behind it is one Postgres migration.

```
$ customer-account create-account --tenant T --email alice@example.com --by self \
      --at 2026-06-01T09:00:00-06:00 --terms-version v1 --terms-shown terms.txt \
      --channel email=email.txt --channel sms=sms.txt
$ CUSTOMER_ACCOUNT_PASSWORD=... customer-account set-password --tenant T --customer ID --by ops --at ...
$ CUSTOMER_ACCOUNT_PASSWORD=... customer-account verify-password --tenant T --customer ID
$ customer-account start-password-reset --tenant T --customer ID --valid-minutes 30 --by ops --at ...
$ customer-account start-email-change --tenant T --customer ID --new-email b@example.com \
      --valid-minutes 30 --at ... [--by WHO]
$ customer-account confirm-email-change --tenant T --token TOKEN --at ...
```

Exit status 0 done or verified, 1 not verified (`verify-password` only), 2 the
machine's configuration (one sentence on stderr: no DSN, a database that does
not connect or is not migrated), 3 the request was refused — and a refusal is
always the JSON `{"refused", "field", "detail"}`, never a traceback.

## The email is not the key

A customer has a stable id. The email is an attribute on it, unique per
operator without regard to case, and it can change — which is what makes
"change email" and "forgot password" both possible at once. An account keyed
on the email is orphaned the first time it changes.

**The fold is the database's.** "Without regard to case" is `lower(email)`
under the collation the column carries — the expression the unique index is
on, and the one every door asks, `create-account` and `start-email-change`
alike. Nothing in Python folds an address: a Python `lower()` beside the
database's was measured to disagree with it on 28 code points on CI's own
database, and to make one door refuse an address as "unchanged" that the next
door handed to a second customer. What the database's fold is depends on how
the database was created, which is why migration `0001` states it and refuses
to apply where it does not hold — see *Install*.

## A password exists because the caller set one

This module has **no view of whether anybody is charged**, and never infers
one. The credential is its own row; it exists where the caller set a password,
and its absence is a named state — `NO_CREDENTIAL` on a verification,
`REFUSAL_NO_CREDENTIAL` on a reset, `absent` on a read — never an error, and
**never "no password required"**. Every such answer says so in words.

The password is hashed with the standard library's `hashlib.scrypt`. The
parameters were **measured, not chosen** (`scripts/measure_scrypt.py`, on the
machine named in the contract), and they are **stored beside every hash**, so
a row written under other values still verifies and raising them invalidates
nothing. The one rule on a password is a minimum length. A password is read
from `CUSTOMER_ACCOUNT_PASSWORD`, never from an argument: arguments are visible
in `ps` to every user on the machine.

## The two recovery paths are not circular

A **password reset** is delivered to the customer's CURRENT address, read from
the row at issue and never supplied — the command has no option for it, and a
pending, unconfirmed email change does not move it.

An **email change** takes effect only when the NEW address presents the token
back. Until then the old address is the address. Who authorised the change is
stored: the customer's current password, verified here, or an explicit caller
authorisation — exactly one, and it travels onto the history row, because "who
authorised this change" is the question asked after a disputed account
takeover.

A token is 32 bytes from the CSPRNG, stored as its SHA-256, and printed **once,
by the call that minted it**. A newer token cancels the older one for the same
customer. Expired, already used, cancelled and unknown are four refusals, by
name.

**This module sends nothing.** No email, no SMS, no network. It mints the
token and names the address it is for; delivering it is the caller's.

## Consent is one acceptance, itemised

Every customer accepts the terms when the account is created — the two writes
are one transaction, or neither happens. The acceptance records the version,
the text shown, who and when, and **for each channel consented to, the text
shown for it** — email, texts — so "what did they agree to for texts" has an
answer after the terms change. Never a boolean. Append-only by grant.

Acceptances **accumulate**: a later acceptance, of a new version or of the
same one again, is a further row and never a rewrite, and the row current for
a version is the latest by `accepted_at`. They are read oldest first in the
order `accepted_at`, `created_at`, `id` — two acceptances written in one
transaction tie on the first two, and `id` orders them deterministically but
**arbitrarily**; the contract says so rather than implying an order that does
not exist. Every channel row carries its own `consented_by` and
`consented_at`; one written with its acceptance carries the acceptance's own
instant and name.

## Every guarantee has a control that has been proven to fire

```
python scripts/fail_controls.py --anchors   # every anchor is live, in a second
python scripts/fail_controls.py             # break each guarantee, require RED
```

A test that has never failed is a decoration. The script breaks the thing each
guarantee guards and requires its tests to go red; a guarantee with no control
fails the run, and a target already failing before anything was planted is
reported UNMEASURED rather than counted.

The guarantees, the refusal codes, the verification outcomes, the consent
channels, the password parameters and the command line itself are generated
into `docs/CONTRACT.md` from the registries and from the parser. No number in
it is typed.

## Install

```
pip install -e .              # the package: no dependencies at all
pip install -e '.[store]'     # plus the Postgres store
pip install -e '.[dev]'       # plus pytest and ruff
```

Python 3.11 or newer.

**The database must fold case beyond ASCII, and migration `0001` refuses to
apply where it does not — by name, before it creates anything.** The identity
rule is the database's `lower()` under its default collation. Measured on
PostgreSQL 16 across every locale provider and `LC_CTYPE` shape it offers: with
the libc provider and `LC_CTYPE` `C` or `POSIX`, `lower()` folds ASCII letters
only, so `Élodie@example.com` and `élodie@example.com` would be two accounts
of one operator; every other libc `LC_CTYPE` and the ICU provider fold beyond
ASCII. So create the database with a UTF-8 `LC_CTYPE` (`en_US.UTF-8`, for
example) or with the ICU provider:

```
createdb --locale=en_US.UTF-8 --template=template0 customer_account
```

On a database whose default collation is libc `C`/`POSIX`, `0001` stops at
`MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY` with nothing created; on a locale
provider the fold was not measured under, at
`MIGRATION_REFUSAL_LOCALE_PROVIDER_UNMEASURED`. No extension is required and
none is used — not `citext`, not a custom collation. The property judged is
`pg_database.datlocprovider` with `pg_database.datctype`, because `datctype`
alone does not predict the fold (ICU with `datctype = C` folds) and
`lc_ctype` is not a parameter on PostgreSQL 16. `customers.email` carries no
collation of its own on purpose: the pre-flight judges the database's default,
and a `COLLATE` clause on the column would take it out from under that
judgement. The suite proves the refusal fires by creating a `C`-collated
database in the same cluster and applying `0001` to it, beside the apply that
proceeds.

## The store

Row-level security from migration 0001: every table carries a tenant column,
`ENABLE`, `FORCE` and an isolation policy, and every customer reference is
half of a composite tenant key. The application connects as a role created
`NOSUPERUSER NOBYPASSRLS`, and the isolation tests assert they are connected
as a role that COULD be stopped before they assert that it was — a superuser
bypasses row-level security unconditionally, and `FORCE` does not stop one.

```
psql "$DSN" -f migrations/0001_tenants_customers_credentials_consent_and_rls.sql
CUSTOMER_ACCOUNT_APP_PASSWORD=... python scripts/ensure-app-role.py "$DSN"
```

Tenant rows are seeded by the owner; this module reads them and never writes
one. The application's DSN (`CUSTOMER_ACCOUNT_DSN`) connects as
`customer_account_app`.

## What is not here

No HTTP surface and no screens. No email or SMS is sent. No cards, no
processor, no money field of any kind. No pass, no vehicle, no stay. No
account spanning operators — one operator, one account. No one-time holder
link: the no-charge path has no account here at all.

## Contributing

Contributions are welcome under the CLA. See `CONTRIBUTING.md` and `CLA.md`.

## Licence

AGPL-3.0-or-later. See `LICENSE`.

Built by 72 Knots Method by 72Knots.ai
