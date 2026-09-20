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

Controls: verification planted to use the module's constants instead of the
row's; the minimum length planted away.
"""

from __future__ import annotations

import hashlib

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
from store_harness import A_PASSWORD, CREATED_AT, query, seed_customer, store_test

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
def test_a_credential_of_another_kdf_is_not_silently_verified():
    credential = Credential(kdf="argon2id", parameters=SMALLER, salt_hex="00" * 16,
                            hash_hex="00" * 64)
    with pytest.raises(ValueError):
        verify(A_PASSWORD, credential)


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
