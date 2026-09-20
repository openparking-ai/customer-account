"""G13 -- nothing real in the tree, swept in Python over every tracked file.

Three sweeps, one file set (``git ls-files``), no exemption for this module or
for ``tests/``:

* **no card-shaped value** -- 13 to 19 digits passing the Luhn checksum, with
  spaces and hyphens stripped first. The probe is BUILT from the checksum and
  never written down, because a specimen in the control would be a specimen
  in the tree.
* **no email address that is not obviously invented** -- backslashes stripped
  first, because a regex literal spells an address with ``\\.`` and an
  unstripped scan is blind to exactly the form a guard-shaped file uses.
* **no name from the maintainer's other software** -- tokenised and digested,
  against the digests the CI guard ships, so the two scans agree on the set;
  the control plants a digest of a word this tree will never contain.

**A PLANTED-POSITIVE CONTROL RUNS BEFORE ANY RESULT IS READ.** Each sweep is
asserted to fire on its probe before its zero over the tree is believed.

Controls: the Luhn check planted to always say no; the allowlist planted to
allow everything; the tokeniser planted to stop splitting on case.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_DIGIT_RUN = re.compile(r"(?<![0-9])(?:[0-9][ -]?){12,22}[0-9](?![0-9])")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_ALLOWED_EMAIL = (
    re.compile(r"@users\.noreply\.github\.com$", re.I),
    re.compile(r"^noreply@github\.com$", re.I),
    re.compile(r"^noreply@anthropic\.com$", re.I),
    re.compile(r"@example\.(com|org|net)$", re.I),
)
#: Neither is ours to edit, and the CI guards skip the same two.
_SKIP = re.compile(r"^(LICENSE|package-lock\.json)$")


def luhn_ok(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def card_shaped_in(text: str) -> list[str]:
    """Every run of 13-19 digits (separators stripped) that passes Luhn."""
    found = []
    for match in _DIGIT_RUN.finditer(text):
        digits = "".join(c for c in match.group(0) if c.isdigit())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            found.append(f"{digits[:4]}...{digits[-2:]} ({len(digits)} digits)")
    return found


def real_emails_in(text: str) -> list[str]:
    unescaped = text.replace("\\", "")
    return [
        address for address in _EMAIL.findall(unescaped)
        if not any(rule.search(address) for rule in _ALLOWED_EMAIL)
    ]


def tokens(text: str) -> list[str]:
    """Runs of letters, lowercased, with a case transition ending a token as
    surely as a space does -- the CI guard's tokeniser, in Python."""
    out: list[str] = []
    current = ""
    previous_was_lower = False
    for ch in text:
        if not ch.isalpha():
            if current:
                out.append(current.lower())
            current = ""
            previous_was_lower = False
            continue
        is_upper = ch.isupper()
        if is_upper and previous_was_lower and current:
            out.append(current.lower())
            current = ""
        current += ch
        previous_was_lower = not is_upper
    if current:
        out.append(current.lower())
    return out


def digest(word: str) -> str:
    return hashlib.sha256(word.strip().lower().encode()).hexdigest()


def forbidden_digests() -> frozenset[str]:
    """The digests the CI guard ships, read from its source so the two agree."""
    source = (ROOT / ".github" / "scripts" / "check-no-sibling-names.js").read_text()
    block = source.split("FORBIDDEN_DIGESTS = new Map([", 1)[1].split("]);", 1)[0]
    return frozenset(re.findall(r"'([0-9a-f]{64})'", block))


def forbidden_names_in(text: str, digests: frozenset[str]) -> list[str]:
    seen = []
    for token in tokens(text):
        d = digest(token)
        if d in digests and d not in seen:
            seen.append(d)
    return [f"sha256 {d[:16]}..." for d in seen]


def tracked_files() -> tuple[Path, ...]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return tuple(ROOT / name for name in out.split("\0") if name and not _SKIP.match(name))


def probe_card() -> str:
    """A card-shaped string, BUILT from the checksum. Never written down."""
    body = "4" + "1" * 14
    for check in "0123456789":
        if luhn_ok(body + check):
            return body + check
    raise AssertionError("no check digit satisfies Luhn, which is arithmetically impossible")


PROBE_EMAIL = "@".join(["someone.real", "a-real-company.example-not"])
INVENTED_EMAIL = "@".join(["nobody", "example.com"])
CONTROL_WORD = "zzqxcontrolword"


# ---------------------------------------------------------------------------
# the controls, first
# ---------------------------------------------------------------------------


@pytest.mark.guarantee("G13")
def test_the_card_sweep_fires_on_a_built_probe_with_and_without_separators():
    probe = probe_card()
    assert card_shaped_in(f"x {probe} y")
    grouped = " ".join(probe[i:i + 4] for i in range(0, len(probe), 4))
    assert card_shaped_in(grouped)
    assert card_shaped_in(grouped.replace(" ", "-"))
    assert card_shaped_in("an id 2026060112000000 and a uuid-ish 1234567890123456789012") == []


@pytest.mark.guarantee("G13")
def test_the_email_sweep_fires_on_a_real_looking_address_escaped_or_not():
    assert real_emails_in(f"contact {PROBE_EMAIL}")
    assert real_emails_in("re = /" + PROBE_EMAIL.replace(".", "\\.") + "/")
    assert real_emails_in(f"write to {INVENTED_EMAIL}") == []
    assert real_emails_in("re = /" + INVENTED_EMAIL.replace(".", "\\.") + "/") == []


@pytest.mark.guarantee("G13")
def test_the_name_sweep_fires_on_a_planted_digest_inside_an_identifier_too():
    digests = frozenset({digest(CONTROL_WORD)})
    assert forbidden_names_in(f"mentions {CONTROL_WORD} once", digests)
    camel = f"prefix{CONTROL_WORD[0].upper()}{CONTROL_WORD[1:]}Suffix"
    assert forbidden_names_in(f"const x = {camel};", digests)
    assert forbidden_names_in(f"xx{CONTROL_WORD}yy as one word", digests) == []
    assert forbidden_names_in("nothing of the sort", digests) == []


@pytest.mark.guarantee("G13")
def test_the_sweep_is_pointed_at_a_real_file_set():
    files = tracked_files()
    assert len(files) > 25, f"the sweep found only {len(files)} tracked files"
    assert Path(__file__).resolve() in files, "this module is outside its own sweep"
    assert ROOT / "src" / "customer_account" / "passwords.py" in files


@pytest.mark.guarantee("G13")
def test_the_digest_set_is_the_ci_guards_and_is_not_empty():
    digests = forbidden_digests()
    assert len(digests) >= 5, "the guard's digest block was not found or is nearly empty"


# ---------------------------------------------------------------------------
# then the tree
# ---------------------------------------------------------------------------


@pytest.mark.guarantee("G13")
def test_no_card_shaped_value_no_real_email_and_no_estate_name_in_any_tracked_file():
    digests = forbidden_digests()
    problems = []
    for path in tracked_files():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(ROOT)
        problems += [f"{relative}: card-shaped {hit}" for hit in card_shaped_in(text)]
        problems += [f"{relative}: email {hit}" for hit in real_emails_in(text)]
        problems += [f"{relative}: estate name {hit}" for hit in forbidden_names_in(text, digests)]
    assert problems == [], "\n".join(problems)
