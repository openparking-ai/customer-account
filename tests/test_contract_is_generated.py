"""G2 -- docs/CONTRACT.md is generated, and generation is not verification.

`scripts/generate_contract.py --check` proves the document matches its
generator. It cannot prove the generator DERIVES anything: a template whose
prose is fixed everywhere except the holes agrees with itself perfectly. So
each test here plants a value that contradicts a published sentence and
requires the rendered sentence to CHANGE. A sentence that survives its plant
is a fixed string, and this file is where that would be found out.

Every plant runs the generator in a fresh interpreter (`rendered` below), so
the module-level registries it imports are re-read from the planted files
rather than served from this process's cache.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from plant import planted

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "scripts" / "generate_contract.py"
DOC = ROOT / "docs" / "CONTRACT.md"


def rendered() -> str:
    """The document as the generator would write it now, without writing it."""
    code = (
        "import sys; sys.argv = ['generate_contract.py']\n"
        f"sys.path.insert(0, {str(GENERATOR.parent)!r})\n"
        "import generate_contract as g\n"
        "sys.stdout.write(g.render(g.DOC.read_text()))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=ROOT, check=True)
    return done.stdout


def check() -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GENERATOR), "--check"], capture_output=True,
                          text=True, cwd=ROOT)


@pytest.mark.guarantee("G2")
def test_the_document_is_the_generated_one():
    done = check()
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.guarantee("G2")
def test_a_guarantee_sentence_moved_in_the_registry_moves_the_document():
    before = rendered()
    with planted(
        "tests/_guarantees.py",
        '"G1": (\n        "Every test module contributes',
        '"G1": (\n        "PLANTED: every test module contributes',
    ):
        after = rendered()
        assert check().returncode == 1, "--check stayed green under a planted registry"
    assert "PLANTED: every test module" in after
    assert "PLANTED" not in before
    assert rendered() == before, "the plant was not restored"


@pytest.mark.guarantee("G2")
def test_the_guarantee_count_is_derived_not_typed():
    before = rendered()
    assert "\nThat is " in before
    with planted(
        "tests/_guarantees.py",
        '    "G2": (',
        '    "G99": ("PLANTED: a guarantee that exists only to move the count."),\n    "G2": (',
    ):
        after = rendered()
    count_before = before.split("\nThat is ")[1].split(" guarantees")[0]
    count_after = after.split("\nThat is ")[1].split(" guarantees")[0]
    assert int(count_after) == int(count_before) + 1, (count_before, count_after)


@pytest.mark.guarantee("G2")
def test_check_writes_nothing_even_when_it_fails():
    before = hashlib.sha256(DOC.read_bytes()).hexdigest()
    with planted("tests/_guarantees.py", '"G2": (', '"G2": (\n        "PLANTED "'):
        assert check().returncode == 1
    assert hashlib.sha256(DOC.read_bytes()).hexdigest() == before


@pytest.mark.guarantee("G2")
def test_a_refusal_sentence_moved_in_the_registry_moves_the_document():
    before = rendered()
    with planted(
        "findings.py",
        '"The new address is the customer\'s current one, as the store compares "',
        '"PLANTED: the new address is the customer\'s current one, as the store compares "',
    ):
        after = rendered()
    assert "PLANTED: the new address" in after and "PLANTED" not in before


@pytest.mark.guarantee("G2")
def test_the_stated_scrypt_parameters_move_the_document():
    before = rendered()
    with planted("passwords.py", "SCRYPT = ScryptParameters(n=2**17, r=8, p=1, dklen=64)",
                 "SCRYPT = ScryptParameters(n=2**15, r=8, p=1, dklen=64)  # PLANTED"):
        after = rendered()
    assert "n = 131072 (2^17)" in before and "n = 32768 (2^15)" in after


@pytest.mark.guarantee("G2")
def test_a_command_added_to_the_parser_moves_the_document_and_a_channel_too():
    before = rendered()
    with planted("cli.py", '    s = store("consume-password-reset", ',
                 '    store("planted-command", "PLANTED: a command nobody published")\n'
                 '    s = store("consume-password-reset", '):
        after = rendered()
    assert "`planted-command`" in after and "planted-command" not in before
    assert "That is 10 commands" in before and "That is 11 commands" in after
    with planted("consent.py", '    SMS = "sms"', '    SMS = "sms"\n    FAX = "fax"  # PLANTED'):
        after = rendered()
    assert "- `fax`" in after and "That is 3 channels" in after


@pytest.mark.guarantee("G2")
def test_the_one_tiebreak_moves_both_history_sentences():
    """Both orders derive from ``records.TIEBREAK``: one plant, two sentences
    move, and neither is a tuple written out a second time."""
    before = rendered()
    assert "in the order `accepted_at`, `created_at`, `id`" in before
    assert "in the order `changed_at`, `created_at`, `id`" in before
    assert before.count("are ordered by `id`") == 2
    with planted("store/records.py",
                 'TIEBREAK = ("created_at", "id")',
                 'TIEBREAK = ("created_at",)  # PLANTED'):
        after = rendered()
    assert "in the order `accepted_at`, `created_at`:" in after
    assert "in the order `changed_at`, `created_at`:" in after
    assert after.count("are ordered by `created_at`") == 2
    assert "are ordered by `id`" not in after


@pytest.mark.guarantee("G2")
def test_the_migrations_own_refusal_sentence_moves_the_document():
    """The install requirement is read from the migration's RAISE, so the
    sentence the installer reads is the one the pre-flight raises."""
    before = rendered()
    assert "| `MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY` | this database's default collation " in (
        before
    )
    assert "That is 2 named refusals in `0001_" in before
    with planted(
        "migrations/0001_tenants_customers_credentials_consent_and_rls.sql",
        "RAISE EXCEPTION 'MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY: this database''s default "
        "collation '",
        "RAISE EXCEPTION 'MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY: PLANTED this database''s "
        "default collation '",
    ):
        after = rendered()
        assert check().returncode == 1
    assert "| `MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY` | PLANTED this database's default " in after
