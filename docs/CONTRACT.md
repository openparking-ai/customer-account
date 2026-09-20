# The contract — Open Parking AI customer account

This module answers one question and nothing else:

> **Is this person who they say they are, and what have they agreed to?**

Identity and recorded consent. No cards, no money, no passes, no vehicles, no
stays.

> **Every block below marked GENERATED is derived** — from the guarantee
> registry today, and from the module's own registries when it lands. No number
> and no sentence inside one is typed. `scripts/generate_contract.py --check`
> fails if one was edited by hand, and `tests/test_contract_is_generated.py`
> plants values contradicting the prose and requires the prose to change --
> because generation is not verification, and a template whose prose is fixed
> everywhere except the holes agrees with itself perfectly.

`main` carries the furniture: the guard on the guarantees, the generated
contract, the fail controls and the CI that runs them. The module itself lands
by pull request, and its own registries join the blocks below when it does.

## The guarantees

<!-- GENERATED:guarantees -->
| id | what is guaranteed |
|---|---|
| **G1** | Every test module contributes at least one registered guarantee, derived from the filesystem and read from the AST -- so a module cannot be added, skipped or deleted without a guard noticing. A module that PLANTS a defect may not be excused at all. |
| **G2** | docs/CONTRACT.md is GENERATED from this registry and from the registries that implement it, and its prose is derived rather than fixed: a value that contradicts a published sentence changes the sentence, because generation is not verification. |

That is 2 guarantees. Every one of them has a fail control that has been proven to fire, and the count above is derived from the registry rather than typed here.
<!-- END:guarantees -->

---

Built by 72 Knots Method by 72Knots.ai
