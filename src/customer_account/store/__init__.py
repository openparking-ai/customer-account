"""The Postgres store: a port, a migration and the writes.

The engine (``identity``, ``passwords``, ``tokens``, ``consent``) never imports
this package. Everything in here imports ``psycopg`` lazily, inside the function
that needs it, so that importing ``customer_account`` on a machine with no
driver is not an error and a password can be hashed and verified with nothing
but the standard library.
"""
