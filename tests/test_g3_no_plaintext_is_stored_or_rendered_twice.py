"""G3 -- a plaintext password or token is never stored and never rendered twice.

**THE SCAN, AND ITS CONTROLS.** Passwords are set and tokens are issued --
through the store and through the command line -- and every column of every
table in the catalogue is read as text and searched for each plaintext: zero
hits, or the guarantee is broken. The POSITIVE CONTROL runs in the same test:
the same scan, for the token's SHA-256, finds exactly the row that holds it,
so a zero is a measurement of the columns and not blindness. Then every line
the command line printed since the test began is searched for each plaintext:
a token appears in the ONE issue output, and nowhere else -- not in a read,
not in a refusal; a password appears nowhere at all.

Controls: the password planted into a stored column; the presented token
planted into the unknown-token refusal's detail.
"""

from __future__ import annotations

import json

import pytest

from customer_account import findings as f
from customer_account.store.postgres import all_tables, tenant
from customer_account.store.records import (
    confirm_email_change,
    set_password,
    start_email_change,
    start_password_reset,
)
from customer_account.tokens import digest
from store_harness import (
    A_PASSWORD,
    CREATED_AT,
    LATER,
    needs_postgres,
    new_tenant,
    seed_customer,
)

pytestmark = needs_postgres


def columns_holding(owner, needle: str) -> list[str]:
    """Every ``table.column`` in the catalogue whose text contains ``needle``,
    read as the owner (which sees every tenant's rows)."""
    hits = []
    with owner.cursor() as cursor:
        for table in all_tables(owner):
            cursor.execute(
                "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0 "
                "AND NOT attisdropped", (table,),
            )
            for (column,) in cursor.fetchall():
                cursor.execute(
                    f'SELECT count(*) FROM "{table}" WHERE "{column}"::text LIKE %s',
                    (f"%{needle}%",),
                )
                if cursor.fetchone()[0]:
                    hits.append(f"{table}.{column}")
    return hits


def dsn_for_the_app(monkeypatch):
    from psycopg import conninfo

    from customer_account.store.postgres import APP_ROLE
    from store_harness import APP_PASSWORD, DSN

    params = conninfo.conninfo_to_dict(DSN)
    monkeypatch.setenv("CUSTOMER_ACCOUNT_DSN", conninfo.make_conninfo(
        **{**params, "user": APP_ROLE, "password": APP_PASSWORD}))


@pytest.mark.guarantee("G3")
def test_the_plaintext_is_in_no_column_of_any_table_and_the_digest_is_the_control(
    app, owner, tenant_id
):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="owner", at=CREATED_AT)
        change = start_email_change(cursor, tenant_id, customer_id, "alice.new@example.com",
                                    valid_minutes=120, at=CREATED_AT, by="owner")
        reset = start_password_reset(cursor, tenant_id, customer_id, valid_minutes=120,
                                     by="owner", at=CREATED_AT)
    app.commit()
    tables = all_tables(owner)
    assert {"customer_credentials", "pending_email_changes", "credential_resets"} <= set(tables)
    assert len(tables) >= 8
    tokens = {"pending_email_changes": change["token"], "credential_resets": reset["token"]}
    for table, token in tokens.items():
        assert columns_holding(owner, token) == [], f"the {table} token is stored in plaintext"
        # THE CONTROL: the same scan finds the digest, in the one column that holds it
        assert columns_holding(owner, digest(token)) == [f"{table}.token_sha256"], table
        # and a fragment of the token is not there either (a prefix stored "for lookup")
        assert columns_holding(owner, token[:12]) == [], table
    assert columns_holding(owner, A_PASSWORD) == [], "the password is stored in plaintext"
    # the password's hash IS there, in the one column, so the scan reads that table too
    with owner.cursor() as cursor:
        cursor.execute("SELECT hash_hex FROM customer_credentials WHERE customer_id = %s",
                       (str(customer_id),))
        (hash_hex,) = cursor.fetchone()
    assert columns_holding(owner, hash_hex) == ["customer_credentials.hash_hex"]


@pytest.mark.guarantee("G3")
def test_the_token_is_rendered_by_the_issue_call_and_by_nothing_else_and_the_password_by_nothing(
    app, owner, tenant_id, capsys, monkeypatch
):
    """Every line the command line printed holds each token in ONE issue output
    -- and nowhere else: not in a read, not in a refusal (unknown, used,
    cancelled, expired, another tenant). The password is in no output; the
    read renders neither hash, salt nor digest."""
    from customer_account.cli import main

    dsn_for_the_app(monkeypatch)
    customer_id = seed_customer(app, tenant_id)
    T = ["--tenant", str(tenant_id)]
    printed: list[tuple[str, str]] = []

    def run(argv: list[str], password: str | None = None) -> dict:
        if password is None:
            monkeypatch.delenv("CUSTOMER_ACCOUNT_PASSWORD", raising=False)
        else:
            monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", password)
        status = main(argv)
        out = capsys.readouterr()
        printed.append((argv[0], out.out + out.err))
        return {"status": status, "printed": out.out}

    at = "2026-06-01T09:00:00-06:00"
    assert run(["set-password", *T, "--customer", str(customer_id), "--by", "owner",
                "--at", at], A_PASSWORD)["status"] == 0
    issued = run(["start-email-change", *T, "--customer", str(customer_id), "--new-email",
                  "alice.new@example.com", "--valid-minutes", "30", "--at", at], A_PASSWORD)
    assert issued["status"] == 0
    token = json.loads(issued["printed"])["token"]
    reset = run(["start-password-reset", *T, "--customer", str(customer_id),
                 "--valid-minutes", "30", "--by", "owner", "--at", at])
    reset_token = json.loads(reset["printed"])["token"]
    # every door that could render it
    other = new_tenant(owner)
    unknown_here = run(["confirm-email-change", "--tenant", str(other), "--token", token,
                        "--at", at])
    assert '"REFUSAL_TOKEN_UNKNOWN"' in unknown_here["printed"]
    expired = run(["confirm-email-change", *T, "--token", token, "--at",
                   "2026-06-01T09:30:00-06:00"])
    assert '"REFUSAL_TOKEN_EXPIRED"' in expired["printed"]
    confirmed = run(["confirm-email-change", *T, "--token", token, "--at",
                     "2026-06-01T09:10:00-06:00"])
    assert confirmed["status"] == 0, confirmed
    used = run(["confirm-email-change", *T, "--token", token, "--at",
                "2026-06-01T09:11:00-06:00"])
    assert '"REFUSAL_TOKEN_ALREADY_USED"' in used["printed"]
    superseding = run(["start-password-reset", *T, "--customer", str(customer_id),
                       "--valid-minutes", "30", "--by", "owner", "--at", at])
    second_reset = json.loads(superseding["printed"])["token"]
    cancelled = run(["consume-password-reset", *T, "--token", reset_token, "--at",
                     "2026-06-01T09:05:00-06:00"], "a replacement passphrase")
    assert '"REFUSAL_TOKEN_CANCELLED"' in cancelled["printed"]
    consumed = run(["consume-password-reset", *T, "--token", second_reset, "--at",
                    "2026-06-01T09:05:00-06:00"], "a replacement passphrase")
    assert consumed["status"] == 0, consumed
    wrong = run(["verify-password", *T, "--customer", str(customer_id)], A_PASSWORD)
    assert wrong["status"] == 1
    read = run(["show-account", *T, "--customer", str(customer_id)])
    assert read["status"] == 0 and '"email_changes"' in read["printed"]
    acceptances = run(["show-acceptances", *T, "--customer", str(customer_id)])
    assert acceptances["status"] == 0

    for name, plaintext, issuer in (("change token", token, "start-email-change"),
                                    ("first reset token", reset_token, "start-password-reset"),
                                    ("second reset token", second_reset,
                                     "start-password-reset")):
        holders = [command for command, text in printed if plaintext in text]
        assert holders == [issuer], f"the {name} was rendered by {holders}"
    for password in (A_PASSWORD, "a replacement passphrase"):
        holders = [command for command, text in printed if password in text]
        assert holders == [], f"the password was rendered by {holders}"
    with owner.cursor() as cursor:
        cursor.execute("SELECT hash_hex, salt_hex FROM customer_credentials WHERE customer_id = %s",
                       (str(customer_id),))
        hash_hex, salt_hex = cursor.fetchone()
    for name, needle in (("hash", hash_hex), ("salt", salt_hex), ("change digest", digest(token)),
                         ("reset digest", digest(second_reset))):
        holders = [command for command, text in printed if needle in text]
        assert holders == [], f"the {name} was rendered by {holders}"
    assert len(printed) >= 12, "the collector saw fewer doors than this test drives"


@pytest.mark.guarantee("G3")
def test_a_refusal_naming_a_token_does_not_echo_it(app, tenant_id):
    """The refusal a wrong token earns names nothing about the token."""
    with tenant(app, tenant_id) as cursor:
        with pytest.raises(f.Refused) as refused:
            confirm_email_change(cursor, tenant_id, "not-a-token-anyone-issued", at=LATER)
    assert refused.value.code == f.REFUSAL_TOKEN_UNKNOWN
    assert "not-a-token" not in refused.value.detail
    assert "not-a-token" not in str(refused.value)
