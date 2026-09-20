# Open Parking AI — customer account

**Is this person who they say they are, and what have they agreed to?** That
one question, and nothing else. Identity and recorded consent: no cards, no
money, no passes, no vehicles, no stays.

This is the furniture: the licence, the contributor agreement, the guards, the
guard on the guarantees, the generated contract, the fail controls and the CI
that runs them — copied from the sibling modules so there is one shape and not
two. The module lands by pull request.

## What it will hold, and what it will not

A customer has a stable id; the email is an attribute on it, unique per
operator, and can change. A password exists only where the caller says a
charge does — this module has no view of charges and never infers one — and
its absence is a named state, never an error and never "no password
required". A password is stored as a `hashlib.scrypt` hash with its parameters
beside it; a one-time token is stored as its SHA-256 and returned exactly
once, by the call that minted it.

An email change takes effect only when confirmed at the new address, and who
authorised it is stored. A password reset is delivered to the current address,
never to a supplied one. Terms are accepted once, at account creation, in a
record that names the version, the text shown, and the text shown for each
channel — email, texts — so "what did they agree to" has an answer after the
terms change.

No HTTP surface. No screens. No email or SMS is sent: delivering a token is
the caller's.

## Every guarantee has a control that has been proven to fire

```
python scripts/fail_controls.py --anchors   # every anchor is live, in a second
python scripts/fail_controls.py             # break each guarantee, require RED
```

The guarantees are generated into `docs/CONTRACT.md` from the registry. No
number in it is typed.

## Install

```
pip install -e .              # the module: no dependencies at all
pip install -e '.[store]'     # plus the Postgres store
pip install -e '.[dev]'       # plus pytest and ruff
```

Python 3.11 or newer.

## Contributing

Contributions are welcome under the CLA. See `CONTRIBUTING.md` and `CLA.md`.

## Licence

AGPL-3.0-or-later. See `LICENSE`.

Built by 72 Knots Method by 72Knots.ai
