"""G7 -- every table carries a tenant column, ENABLE, FORCE and a policy, and
every customer reference is half of a composite tenant key.

**READ FROM THE CATALOGUE, NEVER FROM A LIST OF TABLE NAMES.** A check that
walked a list somebody typed cannot notice a table added without protection,
which is the entire failure it exists to catch.

**AND THE SUPERUSER TRAP IS CHECKED BEFORE ANYTHING ELSE.** A Postgres superuser
bypasses row-level security unconditionally; `FORCE` does not stop one, it only
closes the table-owner hole. So `assert_role_cannot_bypass_rls` runs first: the
test proves it is connected as a role that COULD be stopped, before it proves it
was stopped.

**THE ONE ALLOWANCE IN THE SUITE IS HERE.** There is no way to read a database
catalogue without a database, so these skip when `CUSTOMER_ACCOUNT_TEST_DSN` is
unset. CI always sets it, so CI never skips them -- and
`CUSTOMER_ACCOUNT_ALLOW_UNRUN` is empty in CI, so a run where these did not
execute FAILS rather than passing quietly.

**ISOLATION IS PROVEN ON EVERY TABLE, FROM THE CATALOGUE.** One full graph is
seeded as tenant A through the module -- every table gets a row, and a table
with no row is UNMEASURED, not clean -- then for every table carrying a tenant
column tenant B reads none of A's rows and updates none of them.

**THE PUBLISHED INSTALL STEP IS RUN, NOT DESCRIBED.** ``scripts/ensure-app-role.py``
is the README's second step -- it gives the application role its login. The
sibling module it is copied from shipped it with a bind parameter in an
``ALTER ROLE``, which PostgreSQL's utility statements cannot take, and nothing
had ever run it. The test at the end of this file runs the script against the
test cluster, logs in with the password it set, shows a wrong password refused
(the control: the cluster CHECKS passwords), and asserts the password reaches
no output.

Controls: FORCE removed from one table in the migration; a composite key
removed from one table in the migration; the install script's statement
planted back to the bind-parameter form.
"""

from __future__ import annotations

import psycopg
import pytest

from customer_account.store.postgres import (
    assert_role_cannot_bypass_rls,
    references_without_a_composite_key,
    tables_with_tenant_column,
    tables_without_rls,
    tables_without_tenant_column,
    tenant,
)
from store_harness import needs_postgres, new_tenant, seed_customer, seed_full_graph

pytestmark = needs_postgres


@pytest.mark.guarantee("G7")
def test_the_connection_could_actually_be_stopped(app):
    """THE CONTROL ON EVERY ISOLATION ASSERTION BELOW."""
    assert_role_cannot_bypass_rls(app)


@pytest.mark.guarantee("G7")
def test_the_owner_connection_would_have_failed_that_check(owner):
    """The positive control for the check itself."""
    with pytest.raises(AssertionError, match="inert"):
        assert_role_cannot_bypass_rls(owner)


@pytest.mark.guarantee("G7")
def test_no_table_ships_without_row_level_security(app):
    assert tables_without_rls(app) == []


@pytest.mark.guarantee("G7")
def test_every_table_but_tenants_carries_a_tenant_column(app):
    assert tables_without_tenant_column(app) == []


@pytest.mark.guarantee("G7")
def test_every_customer_and_acceptance_reference_is_a_composite_tenant_key(app):
    assert references_without_a_composite_key(app, "customer_id", "customers") == []
    assert references_without_a_composite_key(app, "acceptance_id", "terms_acceptances") == []


@pytest.mark.guarantee("G7")
def test_the_composite_key_scan_can_see_a_bare_reference(owner):
    """The control on the scan above: a scratch table with a bare uuid column
    named customer_id and no composite key is reported, then dropped."""
    with owner.cursor() as cursor:
        cursor.execute("CREATE TABLE _bare_ref (tenant_id uuid, customer_id uuid)")
        try:
            assert references_without_a_composite_key(owner, "customer_id", "customers") == [
                "_bare_ref"
            ]
        finally:
            cursor.execute("DROP TABLE _bare_ref")


@pytest.mark.guarantee("G7")
def test_the_coverage_check_is_not_measuring_an_empty_schema(app):
    with app.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r'"
        )
        (count,) = cursor.fetchone()
    assert count >= 8, f"only {count} tables found; the migration did not run"


@pytest.mark.guarantee("G7")
def test_one_tenant_cannot_read_another_tenants_rows(app, owner):
    assert_role_cannot_bypass_rls(app)
    alpha, beta = new_tenant(owner, "alpha"), new_tenant(owner, "beta")
    seed_customer(app, alpha, "alpha@example.com")
    seed_customer(app, beta, "beta@example.com")
    with tenant(app, alpha) as cursor:
        cursor.execute("SELECT email FROM customers")
        visible = sorted(row[0] for row in cursor.fetchall())
    app.rollback()
    assert visible == ["alpha@example.com"], f"tenant alpha saw {visible}"


@pytest.mark.guarantee("G7")
def test_a_connection_with_no_tenant_context_sees_nothing(app):
    """Fail closed. `tenant_id = NULL` is NULL, not true."""
    assert_role_cannot_bypass_rls(app)
    with app.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM customers")
        (count,) = cursor.fetchone()
    app.rollback()
    assert count == 0


@pytest.mark.guarantee("G7")
def test_a_tenant_cannot_write_a_row_attributed_to_another(app, owner):
    """WITH CHECK, not just USING."""
    alpha, beta = new_tenant(owner), new_tenant(owner)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant(app, alpha) as cursor:
            cursor.execute(
                "INSERT INTO customers (tenant_id, email) VALUES (%s, 'x@example.com')",
                (beta,),
            )
    app.rollback()


@pytest.mark.guarantee("G7")
def test_a_tenant_cannot_name_another_tenants_customer_even_by_a_raw_insert(app, owner):
    """The composite key: the foreign-key check runs past the policy, and the
    pair (tenant_id, customer_id) does not exist for tenant alpha."""
    alpha, beta = new_tenant(owner), new_tenant(owner)
    theirs = seed_customer(app, beta, "theirs@example.com")
    with tenant(app, alpha) as cursor:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                "INSERT INTO terms_acceptances (tenant_id, customer_id, terms_version, "
                "terms_shown, accepted_by, accepted_at) VALUES (%s, %s, 'v', 't', 'b', now())",
                (alpha, theirs),
            )
    app.rollback()


@pytest.mark.guarantee("G7")
def test_every_table_isolates_one_tenant_from_another_read_and_write(app, owner):
    """For EVERY table in the catalogue: tenant A has rows there (the
    denominator -- none means the seed missed the table and nothing below is
    measured), tenant B reads none of them, and tenant B's UPDATE touches
    none of them. ``tenants`` carries its tenant in ``id`` and is included."""
    assert_role_cannot_bypass_rls(app)
    alpha, beta = new_tenant(owner), new_tenant(owner)
    seed_full_graph(app, alpha)
    tables = [(name, "tenant_id") for name in tables_with_tenant_column(app)]
    tables.append(("tenants", "id"))
    assert len(tables) >= 8, f"only {len(tables)} tenant-bearing tables; the migration did not run"
    unmeasured, leaks, writes = [], [], []
    for table, column in tables:
        with tenant(app, alpha) as cursor:
            cursor.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (alpha,))
            (mine,) = cursor.fetchone()
        app.rollback()
        if mine == 0:
            unmeasured.append(table)
            continue
        with tenant(app, beta) as cursor:
            cursor.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (alpha,))
            (seen,) = cursor.fetchone()
        app.rollback()
        try:
            with tenant(app, beta) as cursor:
                cursor.execute(
                    f"UPDATE {table} SET {column} = {column} WHERE {column} = %s", (alpha,)
                )
                touched = cursor.rowcount
        except psycopg.errors.InsufficientPrivilege:
            touched = 0  # no UPDATE grant at all on this table: refused before the policy
        app.rollback()
        if seen:
            leaks.append(f"{table}: tenant beta read {seen} of alpha's {mine} rows")
        if touched:
            writes.append(f"{table}: tenant beta updated {touched} of alpha's rows")
    assert unmeasured == [], f"tenant alpha has no rows in {unmeasured}: UNMEASURED, not clean"
    assert leaks == [], leaks
    assert writes == [], writes


# ---------------------------------------------------------------------------
# The install step: scripts/ensure-app-role.py, RUN.
# ---------------------------------------------------------------------------


def _ensure_app_role(dsn: str, password: str | None, env_extra: dict | None = None):
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "ensure-app-role.py"
    env = {k: v for k, v in os.environ.items() if k != "CUSTOMER_ACCOUNT_APP_PASSWORD"}
    if password is not None:
        env["CUSTOMER_ACCOUNT_APP_PASSWORD"] = password
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(script), dsn], capture_output=True, text=True, env=env,
    )


@pytest.mark.guarantee("G7")
def test_the_published_install_step_runs_and_the_password_it_sets_logs_in(owner):
    """Runs the script the README publishes, as the owner, against the test
    cluster; then logs in as the application role with that password."""
    from uuid import uuid4

    from psycopg import conninfo

    from customer_account.store.postgres import APP_ROLE, connect
    from store_harness import APP_PASSWORD, DSN

    password = f"install-{uuid4().hex}"
    run = _ensure_app_role(DSN, password)
    assert run.returncode == 0, (run.stdout, run.stderr)
    assert "can log in, and still cannot bypass row-level security" in run.stdout
    assert password not in run.stdout and password not in run.stderr, (
        "the password reached the script's output"
    )
    params = conninfo.conninfo_to_dict(DSN)
    app_dsn = conninfo.make_conninfo(**{**params, "user": APP_ROLE, "password": password})
    try:
        with connect(app_dsn) as fresh:
            with fresh.cursor() as cursor:
                cursor.execute("SELECT current_user, rolsuper, rolbypassrls, rolcanlogin "
                               "FROM pg_roles WHERE rolname = current_user")
                assert cursor.fetchone() == (APP_ROLE, False, False, True)
        # THE CONTROL: the cluster checks passwords, so the login above proves the
        # password and not merely the LOGIN attribute. A cluster on trust auth
        # would accept anything, and this test would then measure nothing.
        wrong = conninfo.make_conninfo(**{**params, "user": APP_ROLE,
                                          "password": f"wrong-{password}"})
        with pytest.raises(psycopg.OperationalError):
            connect(wrong).close()
    finally:
        # Put the harness's password back -- through the same script, which is
        # a second run of the install step and must succeed too.
        restore = _ensure_app_role(DSN, APP_PASSWORD)
        assert restore.returncode == 0, (restore.stdout, restore.stderr)


@pytest.mark.guarantee("G7")
def test_the_install_step_refuses_to_run_without_a_password_and_never_prints_one(owner):
    """No password in the environment: exit 2 and a sentence, not a traceback.
    A failing run (a database that does not exist) prints no password either."""
    from psycopg import conninfo

    from store_harness import DSN

    run = _ensure_app_role(DSN, None)
    assert run.returncode == 2 and "CUSTOMER_ACCOUNT_APP_PASSWORD is not set" in run.stdout
    params = conninfo.conninfo_to_dict(DSN)
    nowhere = conninfo.make_conninfo(**{**params, "dbname": "customer_account_no_such_database"})
    password = "must-not-be-printed-4f9c"
    run = _ensure_app_role(nowhere, password)
    assert run.returncode != 0
    assert password not in run.stdout and password not in run.stderr, (run.stdout, run.stderr)
