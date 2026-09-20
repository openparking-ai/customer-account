"""G10 -- the email history, the terms acceptances and their channels are
append-only BY GRANT, and the application role holds DELETE on no table.

**A GRANT THE CATALOGUE CAN BE ASKED ABOUT, NOT A PROMISE.** The application
role is granted SELECT and INSERT on the three history tables and nothing
else. The test reads that grant from ``information_schema`` and then TRIES
the UPDATE and the DELETE as the role, and requires ``InsufficientPrivilege``
-- both directions, because a grant check that never tries the write passes
on a typo in the table name.

**THE SET OF APPEND-ONLY TABLES IS DERIVED, AND IT IS EXACTLY THREE.** Every
table the role may only SELECT and INSERT on, read from the catalogue, must
be exactly the three published ones -- so a history added next round without
the grant shape is noticed, and so is a grant quietly widened on one of these.

**AND THE NEVER-GRANTED CONTROL RUNS IN THE SAME RUN.** A table the role CAN
update (``customers``) accepts an update as the role, in this file, so a
refusal above is a measurement of the grant and not of a connection that
cannot write anything. Then: DELETE on no table at all, every table read from
the catalogue -- a DELETE on ``customers`` or ``tenants`` would erase the
histories through the cascades.

Controls: the history grant widened to UPDATE in the migration.
"""

from __future__ import annotations

import psycopg
import pytest

from customer_account.store.postgres import all_tables, grants_on, tenant
from customer_account.store.records import set_password
from store_harness import A_PASSWORD, CREATED_AT, needs_postgres, query, seed_full_graph

pytestmark = needs_postgres

APPEND_ONLY = frozenset({"customer_email_changes", "terms_acceptances", "acceptance_channels"})


def append_only_tables(app) -> frozenset[str]:
    """Every table whose grant to the role is exactly {SELECT, INSERT}."""
    return frozenset(
        table for table in all_tables(app) if grants_on(app, table) == {"SELECT", "INSERT"}
    )


@pytest.mark.guarantee("G10")
def test_the_append_only_set_is_derived_and_is_exactly_the_three_histories(app):
    assert append_only_tables(app) == APPEND_ONLY


@pytest.mark.guarantee("G10")
@pytest.mark.parametrize("table", sorted(APPEND_ONLY))
def test_an_update_and_a_delete_on_a_history_are_refused_by_the_grant(
    app, owner, tenant_id, table
):
    seed_full_graph(app, tenant_id)
    assert query(app, tenant_id, f"SELECT count(*) FROM {table}")[0][0] >= 1, (
        f"{table} has no row to try the write on: UNMEASURED")
    assert grants_on(app, table) == {"SELECT", "INSERT"}
    for statement in (f"UPDATE {table} SET tenant_id = tenant_id",
                      f"DELETE FROM {table}"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with tenant(app, tenant_id) as cursor:
                cursor.execute(statement)
        app.rollback()


@pytest.mark.guarantee("G10")
def test_the_never_granted_control_a_table_the_role_can_update_accepts_an_update(app, tenant_id):
    """Without this, a refusal above could be a connection that cannot write
    anything at all."""
    seed_full_graph(app, tenant_id)
    assert "UPDATE" in grants_on(app, "customers")
    with tenant(app, tenant_id) as cursor:
        cursor.execute("UPDATE customers SET name = 'renamed' WHERE tenant_id = %s", (tenant_id,))
        assert cursor.rowcount == 1
    app.rollback()


@pytest.mark.guarantee("G10")
def test_the_role_holds_delete_on_no_table_in_the_schema(app):
    tables = all_tables(app)
    assert len(tables) >= 8
    assert [t for t in tables if "DELETE" in grants_on(app, t)] == []


@pytest.mark.guarantee("G10")
def test_the_module_replaces_a_credential_by_update_never_by_delete_and_insert(
    app, tenant_id, owner
):
    """The one row the module rewrites in place. Its id survives the rewrite,
    which is what an UPDATE and not a DELETE+INSERT leaves behind."""
    from store_harness import seed_customer

    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="o", at=CREATED_AT)
    app.commit()
    (before,) = query(app, tenant_id, "SELECT id FROM customer_credentials")[0]
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, "a second passphrase", by="o",
                     at=CREATED_AT)
    app.commit()
    assert query(app, tenant_id, "SELECT id FROM customer_credentials") == [(before,)]
