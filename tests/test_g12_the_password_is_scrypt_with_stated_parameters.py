"""G12 -- a password is hashed with the standard library's scrypt under
parameters that are stated, never defaulted, and stored beside every hash.

**VERIFICATION READS THE ROW'S PARAMETERS.** A row written under n=2**14 -- as
an operator on slower hardware, or an older version, would write it -- still
verifies after this module's stated value moved to 2**17, because ``verify``
takes ``n``, ``r``, ``p`` and ``dklen`` from the credential it is given and
never from the module's constants. That is what lets the parameters be raised
without invalidating a single existing row; the row re-hashes under the
current parameters the next time its password is set.

**THE PARAMETERS THE MODULE STATES ARE THE ONES IT WRITES**, and they are the
measured ones (``scripts/measure_scrypt.py``): the row's columns equal
``passwords.SCRYPT`` after a set.

**ONE RULE ON THE PASSWORD: A MINIMUM LENGTH IN BYTES.** Below it, refused by
name; a passphrase of spaces and lowercase letters that clears it is accepted,
because character classes are not a rule here.

**THE KDF A ROW CARRIES IS PARSED, NOT TRUSTED.** The outside review measured
that ``verify`` raised a bare ``ValueError`` on a credential whose ``kdf`` was
not ``scrypt``, and the command line's boundary catches ``Refused`` and the
driver's errors only -- so with the schema's CHECK dropped by the owner and
``argon2id`` written onto a live row, ``verify-password`` and a
password-authorised ``start-email-change`` both reached the shell as a
traceback, no JSON, exit 1. The tests below do what the schema says nobody
can -- the OWNER drops the CHECK and writes the KDF -- and require the
refusal by its name through both doors, the row untouched, nothing written;
the CHECK is put back before they return. And the over-reach controls, same
door, CHECK back in place: the correct password still verifies; a wrong one
is still WRONG_PASSWORD, an ANSWER with exit 1 and not a refusal; no
credential is still NO_CREDENTIAL.

Controls: verification planted to use the module's constants instead of the
row's; the minimum length planted away; the KDF refusal planted back to the
bare ``ValueError`` the review measured.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

import pytest

from customer_account import findings as f
from customer_account.passwords import (
    KDF,
    MIN_PASSWORD_BYTES,
    SCRYPT,
    Credential,
    ScryptParameters,
    hash_password,
    require_password,
    verify,
)
from customer_account.store.postgres import tenant
from customer_account.store.records import load_credential, set_password, verify_password
from store_harness import (
    A_PASSWORD,
    ANOTHER_PASSWORD,
    CREATED_AT,
    query,
    seed_customer,
    store_test,
)

SMALLER = ScryptParameters(n=2**14, r=8, p=1, dklen=64)


@pytest.mark.guarantee("G12")
def test_a_credential_hashed_under_other_parameters_still_verifies():
    credential = hash_password(A_PASSWORD, SMALLER)
    assert credential.parameters == SMALLER and credential.parameters != SCRYPT
    assert verify(A_PASSWORD, credential) is True
    assert verify("not the password", credential) is False
    # THE CONTROL on the claim: the same password under the row's salt and the
    # MODULE's parameters is a different hash, so a verify that used the
    # constants would fail this credential
    other = hashlib.scrypt(A_PASSWORD.encode(), salt=bytes.fromhex(credential.salt_hex),
                           n=SCRYPT.n, r=SCRYPT.r, p=SCRYPT.p, dklen=SCRYPT.dklen,
                           maxmem=SCRYPT.maxmem).hex()
    assert other != credential.hash_hex


@pytest.mark.guarantee("G12")
def test_the_stated_parameters_are_the_measured_ones_and_the_kdf_is_scrypt():
    assert KDF == "scrypt"
    assert SCRYPT == ScryptParameters(n=131072, r=8, p=1, dklen=64)
    assert SCRYPT.n & (SCRYPT.n - 1) == 0, "n is a power of two"
    assert SCRYPT.maxmem >= 128 * SCRYPT.r * SCRYPT.n


@pytest.mark.guarantee("G12")
def test_two_hashes_of_one_password_differ_by_salt_and_the_salt_is_from_the_csprng():
    first, second = hash_password(A_PASSWORD, SMALLER), hash_password(A_PASSWORD, SMALLER)
    assert first.salt_hex != second.salt_hex and first.hash_hex != second.hash_hex
    assert len(bytes.fromhex(first.salt_hex)) == 16


@pytest.mark.guarantee("G12")
def test_the_minimum_length_is_the_one_rule_and_it_is_in_bytes():
    with pytest.raises(f.Refused) as short:
        require_password("a" * (MIN_PASSWORD_BYTES - 1))
    assert short.value.code == f.REFUSAL_PASSWORD_TOO_SHORT
    assert require_password("a" * MIN_PASSWORD_BYTES) == "a" * MIN_PASSWORD_BYTES
    assert require_password("all lowercase words") == "all lowercase words"
    # bytes, not characters: four 3-byte characters clear a 12-byte minimum
    assert require_password("€€€€") == "€€€€"
    with pytest.raises(f.Refused) as none:
        require_password(None)
    assert none.value.code == f.REFUSAL_PASSWORD_NOT_GIVEN
    with pytest.raises(f.Refused) as empty:
        require_password("")
    assert empty.value.code == f.REFUSAL_PASSWORD_NOT_GIVEN


@pytest.mark.guarantee("G12")
def test_a_credential_of_another_kdf_is_refused_by_name_not_raised():
    credential = Credential(kdf="argon2id", parameters=SMALLER, salt_hex="00" * 16,
                            hash_hex="00" * 64)
    with pytest.raises(f.Refused) as refused:
        verify(A_PASSWORD, credential)
    assert refused.value.code == f.REFUSAL_KDF_UNKNOWN
    assert refused.value.field == "kdf"
    assert "argon2id" in refused.value.detail and KDF in refused.value.detail


KDF_CHECK = "customer_credentials_kdf_check"


@contextmanager
def _with_the_kdf_check_dropped(owner):
    """The owner does what the schema says nobody can, and puts it back."""
    with owner.cursor() as cursor:
        cursor.execute(f"ALTER TABLE customer_credentials DROP CONSTRAINT {KDF_CHECK}")
    try:
        yield
    finally:
        with owner.cursor() as cursor:
            cursor.execute("UPDATE customer_credentials SET kdf = %s WHERE kdf <> %s", (KDF, KDF))
            cursor.execute(f"ALTER TABLE customer_credentials ADD CONSTRAINT {KDF_CHECK} "
                           f"CHECK (kdf = '{KDF}')")


def _with_credential(app, tenant_id):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="owner", at=CREATED_AT)
    app.commit()
    return customer_id


def _door(main, argv, capsys):
    status = main(argv)
    out = capsys.readouterr()
    assert "Traceback" not in out.err and "Traceback" not in out.out, out
    return status, out


VERIFY = ["verify-password"]
CHANGE = ["start-email-change", "--new-email", "alice.new@example.com", "--valid-minutes", "30",
          "--at", "2026-01-01T12:01:00+00:00"]


@pytest.mark.guarantee("G12")
@store_test
@pytest.mark.parametrize("command", [VERIFY, CHANGE], ids=["verify-password", "start-email-change"])
def test_a_row_carrying_a_kdf_the_module_does_not_have_is_refused_by_name_through_the_door(
    owner, app, tenant_id, capsys, monkeypatch, command
):
    """Both doors that check a password, the row carrying ``argon2id``: exit 3,
    the JSON, the code, the field -- not a traceback, not an answer -- and
    nothing written: the credential row untouched, no pending change."""
    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    customer_id = _with_credential(app, tenant_id)
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", A_PASSWORD)
    argv = [command[0], "--tenant", str(tenant_id), "--customer", str(customer_id), *command[1:]]
    with _with_the_kdf_check_dropped(owner):
        with owner.cursor() as cursor:
            cursor.execute("UPDATE customer_credentials SET kdf = 'argon2id' "
                           "WHERE customer_id = %s", (str(customer_id),))
            assert cursor.rowcount == 1
        status, out = _door(main, argv, capsys)
        assert status == 3 and out.err == "", out
        printed = json.loads(out.out)
        assert printed["refused"] == f.REFUSAL_KDF_UNKNOWN
        assert printed["field"] == "kdf"
        assert "outcome" not in printed, "a refusal, not an answer"
        assert query(app, tenant_id, "SELECT kdf, changed_at FROM customer_credentials "
                     "WHERE customer_id = %s", (str(customer_id),)) == [("argon2id", CREATED_AT)]
        assert query(app, tenant_id, "SELECT count(*) FROM pending_email_changes") == [(0,)]


@pytest.mark.guarantee("G12")
@store_test
def test_the_kdf_refusal_does_not_reach_a_verified_a_wrong_or_an_absent_credential(
    owner, app, tenant_id, capsys, monkeypatch
):
    """THE OVER-REACH CONTROLS, same door, CHECK in place: the correct password
    verifies (exit 0); a wrong one is WRONG_PASSWORD -- an ANSWER, exit 1, not
    a refusal, and that distinction does not move; a customer with no
    credential is NO_CREDENTIAL, exit 1, unchanged."""
    from customer_account.cli import main
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    customer_id = _with_credential(app, tenant_id)
    nobody = seed_customer(app, tenant_id, email="nobody@example.com")
    T = ["--tenant", str(tenant_id)]
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", A_PASSWORD)
    status, out = _door(main, [*VERIFY, *T, "--customer", str(customer_id)], capsys)
    printed = json.loads(out.out)
    assert (status, printed["outcome"], printed["verified"]) == (0, f.VERIFIED, True)
    monkeypatch.setenv("CUSTOMER_ACCOUNT_PASSWORD", ANOTHER_PASSWORD)
    status, out = _door(main, [*VERIFY, *T, "--customer", str(customer_id)], capsys)
    printed = json.loads(out.out)
    assert (status, printed["outcome"], printed["verified"]) == (1, f.WRONG_PASSWORD, False)
    assert "refused" not in printed, "an answer, not a refusal"
    assert printed["means"] == f.NOT_VERIFIED_MEANS
    status, out = _door(main, [*VERIFY, *T, "--customer", str(nobody)], capsys)
    printed = json.loads(out.out)
    assert (status, printed["outcome"], printed["verified"]) == (1, f.NO_CREDENTIAL, False)
    assert "refused" not in printed
    # and the password-authorised change: a wrong password is still its own refusal
    status, out = _door(main, [CHANGE[0], *T, "--customer", str(customer_id), *CHANGE[1:]], capsys)
    assert status == 3 and json.loads(out.out)["refused"] == f.REFUSAL_PASSWORD_WRONG
    assert query(app, tenant_id, "SELECT kdf FROM customer_credentials") == [(KDF,)]


@pytest.mark.guarantee("G12")
@store_test
def test_the_row_carries_the_stated_parameters_and_a_row_under_smaller_ones_verifies_from_the_store(
    app, owner, tenant_id
):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="o", at=CREATED_AT)
    app.commit()
    assert query(app, tenant_id, "SELECT kdf, scrypt_n, scrypt_r, scrypt_p, dklen "
                 "FROM customer_credentials") == [
        ("scrypt", SCRYPT.n, SCRYPT.r, SCRYPT.p, SCRYPT.dklen)]
    # a row written under smaller parameters -- as an older version or slower hardware
    # would write it -- put there as the owner, verifies through the module
    smaller = hash_password(A_PASSWORD, SMALLER)
    with owner.cursor() as cursor:
        cursor.execute(
            "UPDATE customer_credentials SET scrypt_n = %s, salt_hex = %s, hash_hex = %s "
            "WHERE customer_id = %s",
            (SMALLER.n, smaller.salt_hex, smaller.hash_hex, str(customer_id)),
        )
    with tenant(app, tenant_id) as cursor:
        assert load_credential(cursor, tenant_id, customer_id).parameters == SMALLER
        assert verify_password(cursor, tenant_id, customer_id, A_PASSWORD).outcome == f.VERIFIED
        # and the next set re-hashes it under the current parameters
        set_password(cursor, tenant_id, customer_id, A_PASSWORD, by="o", at=CREATED_AT)
        assert load_credential(cursor, tenant_id, customer_id).parameters == SCRYPT
    app.rollback()
