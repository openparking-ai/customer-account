"""G17 -- a control that crashed did not fire, and scripts/fail_controls.py
says so, distinctly from RED.

**THE INSTRUMENT'S ONE FORBIDDEN FAILURE IS A FALSE GREEN.** The merge gate
planted two defects of its own that broke the interpreter rather than the
subject -- a syntax error, an unresolvable import -- and the script read both
as "RED, as required -- 1 error" and counted them as fired. Its only
NOT-A-CONTROL branch was ``returncode == 0``, and a crash is not zero. A
control set that cannot tell a fired assertion from a crash fails OPEN: the
day a plant's anchor drifts onto a line whose edit no longer parses, the
control reports success against a subject it never reached.

**WHAT IS PROVEN HERE, IN ONE RUN.** Through the script's own ``run_control``
and in fresh interpreters, an ORDINARY plant (the shipped ``G13/luhn``) reads
RED and counts, while two CRASH-SHAPED plants -- a syntax error in the test
module (pytest exits 2, "1 error" at collection) and an autouse fixture that
raises (pytest exits 1, "N errors": the shape the exit status alone cannot
see) -- each read NOT A CONTROL (crashed) and do not count. One without the
other would prove nothing: a script that called everything NOT A CONTROL
would pass the crash half.

The plants here are the test's OWN, on files it restores; the shipped control
table is read, not written. ``verdict`` is also held to its table of shapes
directly, so the boundary between a fired assertion and a crash is stated in
one place and checked in two.

Control: the crash branch of ``verdict`` planted to ``False`` -- a crash reads
FIRED again -- and the crash-shaped plants above are counted, which this
module refuses.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fail_controls  # noqa: E402

G13 = "tests/test_g13_nothing_real_in_the_tree.py"

#: A plant whose test module no longer parses: pytest cannot collect it.
SYNTAX_ERROR = (
    G13, G13,
    "    return total % 10 == 0",
    "    return total % 10 == 0 (  # PLANTED: a syntax error, the module cannot be collected",
    "the test module does not parse",
)
#: A plant whose fixture raises: every test ERRORS at setup and pytest exits 1,
#: which the exit status alone reads exactly like tests that failed.
FIXTURE_ERROR = (
    G13, "tests/conftest.py",
    '    yield\n    if "app" in request.fixturenames:',
    '    raise RuntimeError("PLANTED: the fixture crashes before the test runs")\n'
    '    yield\n    if "app" in request.fixturenames:',
    "every test errors at setup",
)


def _completed(returncode: int, summary: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=f"...\n{summary}\n", stderr="")


@pytest.mark.guarantee("G17")
def test_verdict_calls_a_fired_assertion_fired_and_every_crash_shape_crashed():
    fired = _completed(1, "2 failed, 4 passed in 0.31s")
    assert fail_controls.verdict(fired) == (fail_controls.FIRED, "2 failed, 4 passed in 0.31s")
    assert fail_controls.verdict(_completed(0, "6 passed in 0.30s"))[0] == fail_controls.GREEN
    crashes = {
        "a collection error": _completed(2, "1 error in 0.12s"),
        "an interrupted run naming a failure too": _completed(2, "1 failed, 1 error in 0.2s"),
        "a fixture error at exit 1": _completed(1, "6 errors in 0.20s"),
        "a fixture error beside a failure at exit 1": _completed(1, "1 failed, 5 errors in 0.2s"),
        "a fixture error beside passes at exit 1": _completed(1, "1 error, 5 passed in 0.2s"),
        "an internal error": _completed(3, "INTERNALERROR> ..."),
        "a usage error": _completed(4, "ERROR: usage: ..."),
        "nothing collected": _completed(5, "no tests ran in 0.01s"),
        "no output at all": _completed(1, ""),
    }
    for shape, run in crashes.items():
        assert fail_controls.verdict(run)[0] == fail_controls.CRASHED, shape


def _run(control: tuple) -> tuple[bool, str]:
    """One control through the script's own run_control, its report captured."""
    gid = "G17/probe"
    fail_controls.CONTROLS[gid] = control
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            counted = fail_controls.run_control(gid)
    finally:
        del fail_controls.CONTROLS[gid]
    # The verdict lines only: the header quotes the guarantee's own sentence,
    # which names both words.
    verdict = "\n".join(ln for ln in out.getvalue().splitlines() if ln.startswith("    "))
    return counted, verdict


@pytest.mark.guarantee("G17")
def test_an_ordinary_plant_reads_red_and_a_crash_shaped_plant_reads_not_a_control_in_one_run():
    ordinary, ordinary_report = _run(fail_controls.CONTROLS["G13/luhn"])
    assert ordinary is True, ordinary_report
    assert "RED, as required" in ordinary_report and "NOT A CONTROL" not in ordinary_report

    for shape in (SYNTAX_ERROR, FIXTURE_ERROR):
        counted, report = _run(shape)
        assert counted is False, (shape[4], report)
        assert "NOT A CONTROL (crashed)" in report, (shape[4], report)
        assert "RED, as required" not in report, (shape[4], report)
        assert "did not run to a failed assertion" in report

    # The plants restored: the target is green again, in a fresh interpreter.
    assert fail_controls._pytest(G13).returncode == 0


@pytest.mark.guarantee("G17")
def test_the_whole_run_fails_when_a_crashed_control_is_among_the_results(monkeypatch):
    """A crash is not counted, and the run's exit status says so."""
    monkeypatch.setitem(fail_controls.CONTROLS, "G17/probe", SYNTAX_ERROR)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = fail_controls.main(["G17/probe"])
    assert status == 1
    assert "0/1 controls fired" in out.getvalue()
    assert "DEAD CONTROLS: G17/probe" in out.getvalue()
