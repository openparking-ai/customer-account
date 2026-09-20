"""The guard that makes a guarantee test a guarantee: it must actually RUN.

Proving a test CAN fail is half of it. A sibling repository in this project
shipped three tests proving its presence gate was wired that skipped in every
CI run for a fortnight, on a condition nobody watched, while the build stayed
green and the file's own header claimed the opposite. A test that can quietly
not run is not a guarantee.

This is the sibling modules' mechanism, copied: a SET COMPARISON against the
registry at the end of a whole-suite run, so it catches the case a per-test
hook structurally cannot -- a module that fails to import produces no test
items at all, and a guard that only inspects items it was given will never
notice the ones it was not. And it counts SKIPS per guarantee: a guarantee
half of whose tests skipped is not covered, and a binary "ran or not" cannot
say so.

Beneath it, the store-backed fixtures: one migrated database per test module,
as the owner; one application connection (NOSUPERUSER, NOBYPASSRLS); one
fresh tenant per test. See tests/store_harness.py for what each does.
"""

from __future__ import annotations

import os

import pytest

from _guarantees import ALLOW_ENV, GUARANTEES

_ran: set[str] = set()
#: Per guarantee: how many marked tests were skipped, and how many were
#: collected. A guarantee half of whose tests skipped is NOT covered.
_skipped: dict[str, int] = {}
_collected: dict[str, int] = {}


def pytest_configure(config):
    config.addinivalue_line("markers", "guarantee(id): proves a registered guarantee")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    marker = item.get_closest_marker("guarantee")
    if not marker:
        return
    if report.skipped:
        # A skipif mark skips in the SETUP phase; a pytest.skip() inside the
        # test skips in CALL. Either way the test did not run.
        for gid in marker.args:
            _skipped[gid] = _skipped.get(gid, 0) + 1
        return
    if report.when != "call":
        return
    if report.passed:
        for gid in marker.args:
            _ran.add(gid)


def pytest_collection_modifyitems(config, items):
    """Every id on a mark must be in the registry.

    The registry is the source; a mark naming an id nobody registered is a test
    claiming a guarantee the contract does not publish, which is the same defect
    as the reverse and is caught here rather than at the end of the run.
    """
    unknown: list[str] = []
    for item in items:
        marker = item.get_closest_marker("guarantee")
        if marker:
            unknown += [
                f"{item.nodeid} -> {gid}" for gid in marker.args if gid not in GUARANTEES
            ]
    if unknown:
        raise pytest.UsageError(
            "guarantee mark(s) naming an id that is not in tests/_guarantees.py:\n  "
            + "\n  ".join(unknown)
        )
    for item in items:
        marker = item.get_closest_marker("guarantee")
        if marker:
            for gid in marker.args:
                _collected[gid] = _collected.get(gid, 0) + 1


def _is_a_full_run(session) -> bool:
    """Judge a whole-suite run only.

    A developer running one file has not skipped a guarantee; they have selected
    something. Failing that would make this guard noise, and a guard people learn
    to ignore is how the last one died. CI runs the whole suite in one step, so
    that step is always judged. ``-m`` and ``-k`` are selections too: selecting
    by mark and selecting by name are the same act, and neither is a guarantee
    going unproven. What the guard is for is the run where NOTHING was selected
    and a guarantee still did not execute.
    """
    if session.config.option.keyword or session.config.option.markexpr:
        return False
    selected = [arg for arg in session.config.args if not arg.startswith("-")]
    testpaths = session.config.getini("testpaths")
    return not selected or selected == list(testpaths)


def pytest_sessionfinish(session, exitstatus):
    if not _is_a_full_run(session):
        return
    allowed = {
        part.strip() for part in os.environ.get(ALLOW_ENV, "").split(",") if part.strip()
    }
    report = unrun_report(allowed)
    if not report:
        return
    print(
        "\nREGISTERED GUARANTEES THAT DID NOT RUN AND PASS IN FULL:\n"
        f"{report}\n"
        "\nA guarantee whose test does not run is not a guarantee, and a guarantee half\n"
        "of whose tests skipped is not covered. Either make them run, or name the id in\n"
        f"{ALLOW_ENV} -- which is a decision somebody writes down, not a default.\n"
    )
    session.exitstatus = 1


def unrun_report(allowed: set[str]) -> str:
    """Every guarantee that did not run and pass IN FULL, derived: the ones
    with no passing test ("no test ran"), and the ones with skipped tests
    ("N of M tests skipped") -- one line each, so a partly-covered guarantee
    is named and not hidden behind the ones that ran."""
    lines = []
    for gid in sorted(GUARANTEES, key=lambda g: int(g[1:])):
        if gid in allowed:
            continue
        skipped = _skipped.get(gid, 0)
        if gid not in _ran:
            lines.append(f"    {gid}  no test ran and passed"
                         + (f" ({skipped} of {_collected.get(gid, skipped)} skipped)"
                            if skipped else "")
                         + f"  {GUARANTEES[gid][:80]}...")
        elif skipped:
            lines.append(f"    {gid}  {skipped} of {_collected.get(gid, skipped)} tests skipped"
                         f"  {GUARANTEES[gid][:80]}...")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The store-backed fixtures. One migrated database per test module, as the
# owner; one application connection (NOSUPERUSER, NOBYPASSRLS); one fresh
# tenant per test. See tests/store_harness.py for what each of these does.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def owner():
    from store_harness import DSN, migrate

    connection = migrate(DSN)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def app(owner):
    from store_harness import DSN, app_connection

    connection = app_connection(DSN)
    yield connection
    connection.close()


@pytest.fixture()
def tenant_id(owner):
    from store_harness import new_tenant

    return new_tenant(owner)


@pytest.fixture(autouse=True)
def _leave_the_connection_idle(request):
    """A test that raises inside a transaction must not poison the next one.

    The application connection is shared by a module's tests. A test that
    fails mid-transaction -- which is exactly what a planted defect makes tests
    do -- would otherwise leave it aborted, and every later test in the module
    would fail on "current transaction is aborted" rather than on its own
    subject. Rolled back after every test, so a red names its own cause.
    """
    yield
    if "app" in request.fixturenames:
        request.getfixturevalue("app").rollback()
