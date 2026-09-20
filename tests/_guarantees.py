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
}


def guarantee_ids() -> tuple[str, ...]:
    """Sorted numerically, not lexically -- G10 follows G9, not G1."""
    return tuple(sorted(GUARANTEES, key=lambda g: int(g[1:])))


#: Naming an id here lets the suite finish with that guarantee unproven. It is a
#: DECISION somebody writes down, never a default -- CI names nothing, and a
#: guarantee that did not run and pass fails the run.
ALLOW_ENV = "CUSTOMER_ACCOUNT_ALLOW_UNRUN"
