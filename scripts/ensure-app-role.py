#!/usr/bin/env python3
"""Give the application role a login and a password from the environment.

Migration 0001 creates `customer_account_app` NOLOGIN NOSUPERUSER NOBYPASSRLS, so
the SCHEMA carries the guarantee that the application cannot bypass row-level
security. This adds the login, and it deliberately does NOT touch the three
attributes that matter: a script that could hand the app role BYPASSRLS would be
a script that could make every isolation test pass for the wrong reason.

    CUSTOMER_ACCOUNT_APP_PASSWORD=... python scripts/ensure-app-role.py "<dsn>"

Run as the database owner. The password is read from the environment and never
from an argument, because arguments are visible in `ps` to every user on the box.
It is put into the statement by ``psycopg.sql`` composition -- quoted as a
literal, never interpolated as a string -- because ``ALTER ROLE`` is a utility
statement and PostgreSQL binds no parameters into those: the first cut passed
the password as a bind parameter and the README's second install step died on
``syntax error at or near "$1"``, and nothing in the tree had ever run the
script. A test runs it against the test cluster (``tests/test_g7_...``),
and it prints nothing that contains the password.
"""

from __future__ import annotations

import os
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    password = os.environ.get("CUSTOMER_ACCOUNT_APP_PASSWORD")
    if not password:
        print(
            "CUSTOMER_ACCOUNT_APP_PASSWORD is not set. It is read from the "
            "environment rather than from an argument, because arguments are "
            "visible in `ps` to every user on the machine."
        )
        return 2

    import psycopg
    from psycopg import sql

    with psycopg.connect(argv[0]) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            # ALTER, never CREATE: the role's attributes are the migration's, and
            # this script may not be a route to changing them. A quoted LITERAL,
            # not a bind parameter: utility statements take none.
            cursor.execute(
                sql.SQL("ALTER ROLE customer_account_app LOGIN PASSWORD {}").format(
                    sql.Literal(password)
                )
            )
            cursor.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = "
                "'customer_account_app'"
            )
            is_super, bypasses = cursor.fetchone()

    if is_super or bypasses:
        print(
            "customer_account_app can bypass row-level security. Something has "
            "granted it SUPERUSER or BYPASSRLS since migration 0001 ran, and "
            "every isolation policy is inert for it."
        )
        return 1
    print("customer_account_app can log in, and still cannot bypass row-level security.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
