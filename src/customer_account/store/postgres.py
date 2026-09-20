"""Connecting, setting the tenant, and asking the catalogue what is protected.

**THE APPLICATION NEVER CONNECTS AS THE OWNER, AND NEVER AS A SUPERUSER.** A
superuser bypasses row-level security unconditionally; ``FORCE`` does not stop
one, it only closes the table-owner hole. So an isolation test run as the stock
``postgres`` service user sees every tenant's rows whether the policies exist or
not -- it fails on correct code, and the tempting fix is to weaken the assertion.
``assert_role_cannot_bypass_rls`` is run BEFORE any isolation assertion for
exactly that reason: the test proves it is connected as a role that could be
stopped, before it proves it was stopped.

**EVERY COVERAGE CHECK ASKS THE CATALOGUE, NOT A LIST.** ``tables_without_rls``
reads ``pg_class`` and ``pg_policy``; ``references_without_a_composite_key``
reads ``pg_attribute`` and ``pg_constraint``; ``grants_on`` reads
``information_schema``; ``columns_named_like`` reads ``pg_attribute``. A check
that walked a list of table names somebody typed could not notice a table added
without protection, which is the entire failure each exists to catch.

This module imports ``psycopg`` at call time. The engine never imports this
file, so a machine with no driver can still hash and verify a password.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

APP_ROLE = "customer_account_app"
TENANT_SETTING = "customer_account.tenant_id"


def connect(dsn: str) -> Any:
    """A connection, with the driver imported here rather than at module scope."""
    import psycopg  # imported lazily: not a runtime dependency of the engine

    return psycopg.connect(dsn)


def set_tenant(cursor: Any, tenant_id: Any) -> None:
    """Put this TRANSACTION into one tenant's context.

    ``set_config(..., true)`` is transaction-local, so the context cannot leak
    into the next statement on a pooled connection -- which is how one tenant
    ends up reading another's rows through a connection that was reused. The
    corollary binds every caller that commits: a commit ends the transaction and
    the context with it, so the next transaction sets it again or reads nothing.
    """
    cursor.execute(f"SELECT set_config('{TENANT_SETTING}', %s, true)", (str(tenant_id),))


@contextmanager
def tenant(connection: Any, tenant_id: Any) -> Iterator[Any]:
    """A cursor inside one tenant's context, for the current transaction."""
    with connection.cursor() as cursor:
        set_tenant(cursor, tenant_id)
        yield cursor


def assert_role_cannot_bypass_rls(connection: Any) -> None:
    """Refuse to proceed unless this connection could actually be stopped.

    Called at the top of every isolation assertion. Without it, a green isolation
    test proves the connection is a superuser and nothing else.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        row = cursor.fetchone()
    if row is None:
        raise AssertionError("current_user is not in pg_roles, which should be impossible.")
    is_super, bypasses = row
    if is_super or bypasses:
        raise AssertionError(
            f"this connection is {'a superuser' if is_super else 'BYPASSRLS'}, so every "
            "row-level security policy is inert for it and an isolation test would "
            f"pass for the wrong reason. Connect as {APP_ROLE}, which migration 0001 "
            "creates NOSUPERUSER NOBYPASSRLS."
        )


def tables_without_rls(connection: Any) -> list[str]:
    """Every ordinary table in `public` missing ENABLE, FORCE or a policy."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname,
                   c.relrowsecurity,
                   c.relforcerowsecurity,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY c.relname
            """
        )
        rows = cursor.fetchall()

    failures = []
    for name, enabled, forced, policies in rows:
        missing = []
        if not enabled:
            missing.append("ENABLE ROW LEVEL SECURITY")
        if not forced:
            missing.append("FORCE ROW LEVEL SECURITY")
        if not policies:
            missing.append("a policy")
        if missing:
            failures.append(f"{name}: missing {', '.join(missing)}")
    return failures


def tables_without_tenant_column(connection: Any) -> list[str]:
    """Every ordinary table in `public` with no ``tenant_id``, except ``tenants``."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND c.relname <> 'tenants'
              AND NOT EXISTS (
                    SELECT 1 FROM pg_attribute a
                    WHERE a.attrelid = c.oid
                      AND a.attname = 'tenant_id'
                      AND a.attnum > 0
                      AND NOT a.attisdropped)
            ORDER BY c.relname
            """
        )
        return [row[0] for row in cursor.fetchall()]


def references_without_a_composite_key(connection: Any, column: str, target: str) -> list[str]:
    """Every table carrying ``column`` with no foreign key (tenant_id, column)
    at ``target`` (tenant_id, id). Read from the catalogue, never from a list."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = %s AND a.attnum > 0
                 AND NOT a.attisdropped
            WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> %s
              AND NOT EXISTS (
                SELECT 1 FROM pg_constraint k
                JOIN pg_class t ON t.oid = k.confrelid
                WHERE k.conrelid = c.oid AND k.contype = 'f' AND t.relname = %s
                  AND (SELECT array_agg(att.attname ORDER BY ord)
                       FROM unnest(k.conkey) WITH ORDINALITY AS u(attnum, ord)
                       JOIN pg_attribute att ON att.attrelid = c.oid AND att.attnum = u.attnum)
                      = ARRAY['tenant_id', %s]::name[]
                  AND (SELECT array_agg(att.attname ORDER BY ord)
                       FROM unnest(k.confkey) WITH ORDINALITY AS u(attnum, ord)
                       JOIN pg_attribute att ON att.attrelid = t.oid AND att.attnum = u.attnum)
                      = ARRAY['tenant_id', 'id']::name[])
            ORDER BY c.relname
            """,
            (column, target, target, column),
        )
        return [row[0] for row in cursor.fetchall()]


def grants_on(connection: Any, table: str, role: str = APP_ROLE) -> frozenset[str]:
    """The privileges ``role`` holds on ``table``, from the catalogue."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND table_name = %s AND grantee = %s",
            (table, role),
        )
        return frozenset(row[0] for row in cursor.fetchall())


def columns_named_like(connection: Any, words: tuple[str, ...]) -> list[str]:
    """Every column in `public` whose name contains one of ``words`` -- the
    catalogue's answer to "is there a money-shaped column", as table.column."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, a.attname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY 1, 2
            """
        )
        return [
            f"{table}.{column}"
            for table, column in cursor.fetchall()
            if any(word in column.lower() for word in words)
        ]


def all_tables(connection: Any) -> list[str]:
    """Every ordinary table in `public` -- the denominator of "the application
    role holds DELETE on no table", read from the catalogue so a table added
    tomorrow is in the set the day it lands."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY c.relname
            """
        )
        return [row[0] for row in cursor.fetchall()]


def tables_with_tenant_column(connection: Any) -> list[str]:
    """Every ordinary table in `public` carrying a ``tenant_id`` column -- the
    denominator of the isolation test, read from the catalogue."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id'
                 AND a.attnum > 0 AND NOT a.attisdropped
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY c.relname
            """
        )
        return [row[0] for row in cursor.fetchall()]
