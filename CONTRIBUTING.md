# Contributing to Open Parking AI

Contributions are welcome. This page is short on purpose; everything on it is
enforced mechanically, so there is nothing to remember.

## Before your first pull request: sign the CLA

Read [CLA.md](CLA.md), then open a pull request that adds one entry to
`cla/signatures.json` and changes nothing else:

```json
{ "github": "your-github-login", "name": "Your Full Legal Name", "date": "YYYY-MM-DD" }
```

That pull request is your signature. Once it is merged, your later pull requests
pass the CLA check automatically.

The CLA grants 72 Knots the right to relicense contributions. Section 3 of
[CLA.md](CLA.md) explains why in plain terms. If you are not comfortable with
that clause, please do not contribute — it is not negotiable, and it is better
to know before you spend time on a change.

## How a change gets in

1. Open an issue first for anything larger than a fix. Agreeing on the approach
   is cheaper than reviewing the wrong one.
2. Branch from `main`. Nobody pushes to `main` directly; the branch protection
   refuses it.
3. Open a pull request. Every check must be green before it can merge: `lint`,
   `test` on each interpreter, `controls`, `docs`, `cla` and `emails`.
4. A maintainer reviews and merges. Opening the pull request is not merging it.

## What gets rejected on sight

**Real personal data, anywhere in the repository.** Fixtures, tests and
examples use invented values — `example.com` addresses, made-up names, phone
numbers that belong to nobody. This applies to git metadata too: commit with a
masked address, not a personal one. The running system stores real customers;
that is the product, it is governed by retention, and it is a different thing
from what is committed here. The CI guards enforce it and every one ships with
a self-test that proves it can fail.

**A plaintext password or token, stored or rendered twice.** A password is
stored as a `hashlib.scrypt` hash with its parameters beside it and nothing
else; a token is stored as its SHA-256 and the plaintext is returned exactly
once, by the call that minted it. A guarantee scans every column of every
table for the plaintext, with the digest as its positive control.

**Money, anywhere.** This module does not know whether anybody is charged. No
fee, no amount, no balance, no card, no processor — not in the schema, not on
any answer, not in a document. A guarantee reads the catalogue's columns and
the answer classes' fields for it. Whether a charge exists is the caller's
knowledge; this module records that a password was set and never infers why.

**A boolean where a record belongs.** "They accepted the terms" is worthless
the first time the terms change. An acceptance records the version and the
text that was shown, itemised per channel, and is append-only by grant.

**A recovery path that is circular.** A password reset is delivered to the
CURRENT address and never to a supplied one; an email change takes effect only
when confirmed at the NEW address, and who authorised it is stored.

**A dependency on Open Parking AI's platform, or on any hosted service.** This
module is standalone by definition. It sends no email and no SMS; delivering a
token is the caller's.

**A test that has never been seen to fail.** If you add a guarantee, register it
in `tests/_guarantees.py` and add a control to `scripts/fail_controls.py` that
breaks the thing it guards and requires red. The suite refuses to finish with a
registered guarantee unproven, and the controls job refuses to run with one
uncontrolled.

**A silent guess.** Where the module cannot answer without guessing — a
customer with no credential asked to verify a password, a token that has
expired — it answers by name. It does not pick the likely answer and present
it as a fact, and it never answers "no credential" as "no password required".

**A consumer-visible change to the answer without a version bump.**
`docs/CONTRACT.md` is the public surface. Adding a field is additive and does
not bump it; removing, renaming or redefining one does.

## Style

Match the code already there — its naming, its comment density, its idioms. A
change that reads like the file it lands in is easier to review than a better
one that does not.

Comments should say why, not what.

---

Built by 72 Knots Method by 72Knots.ai
