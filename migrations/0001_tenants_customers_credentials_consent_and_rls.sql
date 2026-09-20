-- 0001 — tenants, the customer, the credential, the two one-time tokens, the
-- recorded consent, and the row-level security foundation every later
-- migration inherits.
--
-- Run as the database OWNER. The application never connects as this role.
--
-- The shape of the tenant column, the policies, the composite customer key
-- and the app role is the one the sibling modules in this project already
-- ship, copied rather than reinvented: two shapes would mean two sets of
-- failure modes, and the second one is always the one nobody tested.
--
-- ⛔ THERE IS NO COLUMN IN THIS SCHEMA THAT HOLDS MONEY, A CARD, A PROCESSOR
-- REFERENCE OR A CHARGE, AND THERE NEVER WILL BE. This module does not know
-- whether anybody is charged. Whether a password should exist is the
-- caller's knowledge; this schema records that one was set. A test reads the
-- catalogue for money-shaped and card-shaped column names, with a planted
-- `fee_cents` as its positive control.
--
-- ⛔ NO PLAINTEXT PASSWORD AND NO PLAINTEXT TOKEN IS EVER STORED. The
-- credential row holds a scrypt hash, its salt and the parameters it was
-- made with; a token row holds the SHA-256 of the token. A test issues
-- tokens and sets passwords and scans every column of every table for the
-- plaintext, with the digest as the positive control that the scan reads the
-- column it should.

BEGIN;

-- ---------------------------------------------------------------------------
-- THE PRE-FLIGHT: what this schema requires of the database, refused BY NAME
-- where it does not hold. Nothing below is created when it fires.
--
-- The identity rule -- one address, one account per operator, compared
-- without regard to case -- is `lower(email)` under the collation
-- `customers.email` carries, which is the expression the unique index below
-- is on and the one every door asks. The column carries no COLLATE clause,
-- so that collation is the DATABASE'S DEFAULT: pg_database.datlocprovider
-- and pg_database.datctype. MEASURED (78 rows, every provider and ctype
-- shape PostgreSQL 16 offers, the fix round of 2026-09-20): under the libc
-- provider with LC_CTYPE C or POSIX, lower() folds ASCII letters only, so
-- Élodie@ and élodie@ are TWO accounts; under any other libc LC_CTYPE and
-- under ICU they are one. datctype ALONE does not predict it (ICU with
-- datctype C folds), and `current_setting('lc_ctype')` is not a parameter
-- on PostgreSQL 16 -- so the provider and the ctype are read together, from
-- the catalogue. A provider this was not measured under is refused by name
-- rather than assumed: a refusal, never a default, never an inference.
--
-- Before PostgreSQL 15 there is no datlocprovider column and every collation
-- is libc; the block reads it only where it exists.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  provider text := 'c';
  ctype    text;
BEGIN
  SELECT datctype INTO ctype FROM pg_database WHERE datname = current_database();
  IF EXISTS (SELECT 1 FROM pg_attribute
             WHERE attrelid = 'pg_catalog.pg_database'::regclass
               AND attname = 'datlocprovider') THEN
    EXECUTE 'SELECT datlocprovider::text FROM pg_database WHERE datname = current_database()'
      INTO provider;
  END IF;
  IF provider = 'c' AND ctype IN ('C', 'POSIX') THEN
    RAISE EXCEPTION 'MIGRATION_REFUSAL_CASE_FOLD_ASCII_ONLY: this database''s default collation '
      'folds case for ASCII letters only, so two spellings of one address that differ in the '
      'case of an accented letter would be two accounts of one operator. This module requires '
      'a database whose lower() folds beyond ASCII: create it with a UTF-8 LC_CTYPE (for '
      'example en_US.UTF-8) or with the ICU locale provider, and apply this migration again. '
      'Nothing was created.'
      USING DETAIL = format('locale provider %s, LC_CTYPE %s.',
                            CASE provider WHEN 'c' THEN 'libc' ELSE provider END, ctype),
            ERRCODE = 'invalid_parameter_value';
  ELSIF provider NOT IN ('c', 'i') THEN
    RAISE EXCEPTION 'MIGRATION_REFUSAL_LOCALE_PROVIDER_UNMEASURED: this database''s default '
      'collation comes from a locale provider this module''s case fold has not been measured '
      'under (libc and ICU were). It is refused rather than assumed to fold beyond ASCII. '
      'Nothing was created.'
      USING DETAIL = format('locale provider %s, LC_CTYPE %s.', provider, ctype),
            ERRCODE = 'invalid_parameter_value';
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- The application role.
--
-- NOSUPERUSER and NOBYPASSRLS are the whole point. A superuser bypasses
-- row-level security unconditionally -- FORCE ROW LEVEL SECURITY does not stop
-- one, it only closes the table-owner hole. If the application (or a test)
-- connects as a superuser, every policy below is inert and every isolation test
-- passes for the wrong reason.
--
-- Created NOLOGIN here so the schema carries the guarantee; scripts/ensure-app-role.py
-- adds LOGIN and a password from the environment.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'customer_account_app') THEN
    CREATE ROLE customer_account_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  ELSE
    ALTER ROLE customer_account_app NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- Tenant context.
--
-- Unset resolves to NULL, and `tenant_id = NULL` is NULL, not true -- so a
-- connection that forgets to set the context sees nothing. Fail closed.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid
  LANGUAGE sql STABLE
  AS $$ SELECT NULLIF(current_setting('customer_account.tenant_id', true), '')::uuid $$;

CREATE TABLE tenants (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        text        NOT NULL UNIQUE,
  name        text        NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenants_self_only ON tenants
  USING      (id = current_tenant_id())
  WITH CHECK (id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- customers — a stable id, and the email as an ATTRIBUTE on it.
--
-- The email is not the key. It is unique per tenant and it can change (a
-- confirmed change rewrites this column and records the change below); the
-- id is what every other row points at, so a change orphans nothing.
--
-- `email` carries the SAME check the sibling pass module's holder address
-- carries, copied: one @ with text on both sides. Uniqueness is on the
-- CASE-FOLDED address -- `Alice@` and `alice@` are one mailbox, and two
-- accounts behind one mailbox would make a password reset ambiguous. The
-- address is stored as given. THE FOLD IS lower(email) UNDER THIS COLUMN'S
-- COLLATION, which is the database's default (no COLLATE clause here, on
-- purpose: the pre-flight above judges the database's default, and a clause
-- here would take the column out from under it). The module folds nothing in
-- Python; every door asks this expression.
--
-- `external_id` is OPTIONAL, and that is a decision: the sibling modules'
-- rows are created by an operator who has a reference to supply, while a
-- customer registering themselves has none, and a NOT NULL here would block
-- that path for the module's convenience. Unique where given; PostgreSQL
-- treats NULLs as distinct, so many customers may carry none.
--
-- (tenant_id, id) is UNIQUE so that every customer reference below can be
-- half of a COMPOSITE TENANT KEY: a foreign-key check runs past row-level
-- security, so a bare `customer_id REFERENCES customers(id)` would let a
-- tenant-A row name tenant B's customer by a raw insert. A composite key does
-- not.
-- ---------------------------------------------------------------------------
CREATE TABLE customers (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  external_id  text        CHECK (external_id IS NULL OR length(btrim(external_id)) > 0),
  email        text        NOT NULL CHECK (
                 position('@' in email) > 1
                 AND position('@' in email) < length(email)
               ),
  name         text        CHECK (name IS NULL OR length(btrim(name)) > 0),
  phone        text        CHECK (phone IS NULL OR length(btrim(phone)) > 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_id),
  CONSTRAINT customers_tenant_id_id_key UNIQUE (tenant_id, id)
);

CREATE UNIQUE INDEX customers_one_address_per_tenant ON customers (tenant_id, lower(email));
CREATE INDEX customers_tenant_id_idx ON customers (tenant_id);
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers FORCE  ROW LEVEL SECURITY;
CREATE POLICY customers_tenant_isolation ON customers
  USING      (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- customer_credentials — the password, as a scrypt hash with ITS parameters.
--
-- ONE ROW PER CUSTOMER, AND THE ROW EXISTS ONLY WHERE THE CALLER SET ONE.
-- Its absence is a valid, expected state that the module answers BY NAME
-- (NO_CREDENTIAL) and never as an error -- and never as "no password
-- required": this module has no view of charges and never infers one.
--
-- THE PARAMETERS ARE STORED BESIDE THE HASH so they can be raised later
-- without invalidating existing rows: verification reads the row's values,
-- never the module's constants. The values the module writes today, measured
-- by scripts/measure_scrypt.py and stated in customer_account/passwords.py:
-- n = 131072 (2^17), r = 8, p = 1, dklen = 64. Nothing here defaults them;
-- the module states them on every write.
--
-- `changed_at` is when the password was last set, by any of the three routes
-- (set-password, a consumed reset); `set_by` is who -- the caller's stated
-- name, or the reset's own id.
-- ---------------------------------------------------------------------------
CREATE TABLE customer_credentials (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id   uuid        NOT NULL,
  kdf           text        NOT NULL CHECK (kdf = 'scrypt'),
  scrypt_n      integer     NOT NULL CHECK (scrypt_n >= 2 AND (scrypt_n & (scrypt_n - 1)) = 0),
  scrypt_r      integer     NOT NULL CHECK (scrypt_r > 0),
  scrypt_p      integer     NOT NULL CHECK (scrypt_p > 0),
  dklen         integer     NOT NULL CHECK (dklen >= 32),
  salt_hex      text        NOT NULL CHECK (salt_hex ~ '^[0-9a-f]{32}$'),
  hash_hex      text        NOT NULL CHECK (hash_hex ~ '^[0-9a-f]+$' AND length(hash_hex) = dklen * 2),
  set_by        text        NOT NULL CHECK (length(btrim(set_by)) > 0),
  changed_at    timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, customer_id),
  CONSTRAINT customer_credentials_customer_in_tenant
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX customer_credentials_tenant_id_idx ON customer_credentials (tenant_id);
ALTER TABLE customer_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_credentials FORCE  ROW LEVEL SECURITY;
CREATE POLICY customer_credentials_tenant_isolation ON customer_credentials
  USING      (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- pending_email_changes — the new address and the one-time token the NEW
-- address receives and presents back. Nothing on `customers` moves until it
-- is presented: the old address keeps working until then.
--
-- WHO AUTHORISED THE CHANGE IS STORED. `authorisation` says which of the two
-- routes was used -- the customer's current password, verified by the module
-- ('password'), or an explicit caller authorisation ('caller') -- and
-- `authorised_by` names who: the customer's id under the first, the caller's
-- stated name under the second. "Who authorised this change" is the question
-- asked after a disputed account takeover, and both halves are carried onto
-- the history row when the change takes effect.
--
-- ⛔ THE TOKEN IS NEVER STORED. Only its SHA-256 goes in the row. The plaintext
-- is returned exactly once, by the call that issued it, and by nothing else.
--
-- `expires_at` is STATED: NOT NULL with NO DEFAULT, from a window the caller
-- states in minutes. `expired` is DERIVED from it against the instant asked
-- about; the CHECK on `state` refuses it so nobody can type it. The typed
-- states and the all-or-nothing constraints are the sibling pass module's
-- credential vocabulary, copied.
-- ---------------------------------------------------------------------------
CREATE TABLE pending_email_changes (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id       uuid        NOT NULL,
  new_email         text        NOT NULL CHECK (
                      position('@' in new_email) > 1
                      AND position('@' in new_email) < length(new_email)
                    ),
  token_sha256      text        NOT NULL CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
  authorisation     text        NOT NULL CHECK (authorisation IN ('password', 'caller')),
  authorised_by     text        NOT NULL CHECK (length(btrim(authorised_by)) > 0),
  issued_at         timestamptz NOT NULL,
  expires_at        timestamptz NOT NULL,
  state             text        NOT NULL
                    CHECK (state IN ('issued', 'redeemed', 'cancelled')),
  redeemed_at       timestamptz,
  cancelled_by      text        CHECK (cancelled_by IS NULL OR length(btrim(cancelled_by)) > 0),
  cancelled_at      timestamptz,
  cancelled_reason  text        CHECK (cancelled_reason IS NULL
                                       OR length(btrim(cancelled_reason)) > 0),
  created_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT pending_email_changes_window_is_ordered CHECK (expires_at > issued_at),
  CONSTRAINT pending_email_changes_redeemed_iff_redeemed_at CHECK (
    (state = 'redeemed') = (redeemed_at IS NOT NULL)
  ),
  CONSTRAINT pending_email_changes_cancellation_is_all_or_nothing CHECK (
    (cancelled_by IS NULL) = (cancelled_at IS NULL)
    AND (cancelled_reason IS NULL) = (cancelled_at IS NULL)
  ),
  CONSTRAINT pending_email_changes_cancelled_iff_cancelled_at CHECK (
    (state = 'cancelled') = (cancelled_at IS NOT NULL)
  ),
  UNIQUE (tenant_id, token_sha256),
  CONSTRAINT pending_email_changes_customer_in_tenant
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX pending_email_changes_tenant_id_idx ON pending_email_changes (tenant_id);
CREATE INDEX pending_email_changes_customer_idx
  ON pending_email_changes (tenant_id, customer_id, state);
ALTER TABLE pending_email_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_email_changes FORCE  ROW LEVEL SECURITY;
CREATE POLICY pending_email_changes_tenant_isolation ON pending_email_changes
  USING      (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- customer_email_changes — from, to, when, by. APPEND-ONLY: the application
-- role is granted SELECT and INSERT on this table and nothing else, below,
-- and a test reads that grant from the catalogue and tries the UPDATE.
--
-- One row per change that TOOK EFFECT, written in the same transaction as the
-- rewrite of `customers.email`, carrying the authorisation from the pending
-- row that was confirmed.
-- ---------------------------------------------------------------------------
CREATE TABLE customer_email_changes (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id     uuid        NOT NULL,
  from_email      text        NOT NULL,
  to_email        text        NOT NULL,
  authorisation   text        NOT NULL CHECK (authorisation IN ('password', 'caller')),
  authorised_by   text        NOT NULL CHECK (length(btrim(authorised_by)) > 0),
  changed_at      timestamptz NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT customer_email_changes_customer_in_tenant
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX customer_email_changes_tenant_id_idx ON customer_email_changes (tenant_id);
CREATE INDEX customer_email_changes_customer_idx
  ON customer_email_changes (tenant_id, customer_id, changed_at);
ALTER TABLE customer_email_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_email_changes FORCE  ROW LEVEL SECURITY;
CREATE POLICY customer_email_changes_tenant_isolation ON customer_email_changes
  USING      (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- credential_resets — the one-time token the CURRENT address receives. It
-- resets a password that exists: issuing one onto a customer with no
-- credential is refused by name (there is nothing to reset, and the no-charge
-- path has no account here at all). The same primitive as the pending change:
-- a hash stored, the plaintext returned once, a stated window, a single use.
--
-- The address it is delivered to is READ FROM THE CUSTOMER ROW at issue and
-- never supplied by the caller; a pending, unconfirmed email change does not
-- move it. That is what keeps the two recovery paths from being circular.
-- ---------------------------------------------------------------------------
CREATE TABLE credential_resets (
  id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id       uuid        NOT NULL,
  token_sha256      text        NOT NULL CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
  issued_by         text        NOT NULL CHECK (length(btrim(issued_by)) > 0),
  issued_at         timestamptz NOT NULL,
  expires_at        timestamptz NOT NULL,
  state             text        NOT NULL
                    CHECK (state IN ('issued', 'redeemed', 'cancelled')),
  redeemed_at       timestamptz,
  cancelled_by      text        CHECK (cancelled_by IS NULL OR length(btrim(cancelled_by)) > 0),
  cancelled_at      timestamptz,
  cancelled_reason  text        CHECK (cancelled_reason IS NULL
                                       OR length(btrim(cancelled_reason)) > 0),
  created_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT credential_resets_window_is_ordered CHECK (expires_at > issued_at),
  CONSTRAINT credential_resets_redeemed_iff_redeemed_at CHECK (
    (state = 'redeemed') = (redeemed_at IS NOT NULL)
  ),
  CONSTRAINT credential_resets_cancellation_is_all_or_nothing CHECK (
    (cancelled_by IS NULL) = (cancelled_at IS NULL)
    AND (cancelled_reason IS NULL) = (cancelled_at IS NULL)
  ),
  CONSTRAINT credential_resets_cancelled_iff_cancelled_at CHECK (
    (state = 'cancelled') = (cancelled_at IS NOT NULL)
  ),
  UNIQUE (tenant_id, token_sha256),
  CONSTRAINT credential_resets_customer_in_tenant
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX credential_resets_tenant_id_idx ON credential_resets (tenant_id);
CREATE INDEX credential_resets_customer_idx ON credential_resets (tenant_id, customer_id, state);
ALTER TABLE credential_resets ENABLE ROW LEVEL SECURITY;
ALTER TABLE credential_resets FORCE  ROW LEVEL SECURITY;
CREATE POLICY credential_resets_tenant_isolation ON credential_resets
  USING      (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- terms_acceptances — who accepted, when, which version, and THE TEXT SHOWN.
-- APPEND-ONLY by the same grant as the email history. The shape is the
-- sibling billing module's mandate, copied: a record of what was displayed,
-- not a boolean.
--
-- ONE ACCEPTANCE COVERS EVERYTHING, AND IT IS ITEMISED: the channels consent
-- was asked for, each with the text shown for it, are the child rows in
-- acceptance_channels below. There is no separate SMS acceptance.
--
-- The first acceptance is written in the same transaction as the customer
-- row: an account is created with its terms accepted or not at all.
--
-- ACCEPTANCES ACCUMULATE. A later acceptance -- of a new version, or of the
-- same version again -- is a further row, never a rewrite, and there is no
-- uniqueness on (customer, version) on purpose: the row that is current for
-- a version is the one with the latest accepted_at. The fix round measured
-- that no door adds a channel to an existing acceptance, so a second
-- acceptance is the only way later consent is recorded, and a UNIQUE here
-- would forbid a real flow.
--
-- `created_at` defaults to now(), like every other table here: it is the
-- TRANSACTION'S instant, so two acceptances written in one transaction tie
-- on it as well as on accepted_at. The module reads acceptances in the order
-- accepted_at, created_at, id -- `id` last, unique on every row -- so a full
-- tie is ordered deterministically but ARBITRARILY, and the contract says so.
-- clock_timestamp() here was considered and REJECTED: one rule held in two
-- places is the error this project keeps paying for.
-- ---------------------------------------------------------------------------
CREATE TABLE terms_acceptances (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id    uuid        NOT NULL,
  terms_version  text        NOT NULL CHECK (length(btrim(terms_version)) > 0),
  terms_shown    text        NOT NULL CHECK (length(btrim(terms_shown)) > 0),
  accepted_by    text        NOT NULL CHECK (length(btrim(accepted_by)) > 0),
  accepted_at    timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT terms_acceptances_tenant_id_id_key UNIQUE (tenant_id, id),
  CONSTRAINT terms_acceptances_customer_in_tenant
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers (tenant_id, id) ON DELETE CASCADE
);

CREATE INDEX terms_acceptances_tenant_id_idx ON terms_acceptances (tenant_id);
CREATE INDEX terms_acceptances_customer_idx
  ON terms_acceptances (tenant_id, customer_id, accepted_at);
ALTER TABLE terms_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE terms_acceptances FORCE  ROW LEVEL SECURITY;
CREATE POLICY terms_acceptances_tenant_isolation ON terms_acceptances
  USING      (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- acceptance_channels — per acceptance, each channel consented to and the
-- text shown for it. A channel is a NAME from a fixed set: a new one is a
-- migration. Append-only, with its parent.
--
-- EVERY CHANNEL ROW CARRIES ITS OWN WHO AND WHEN. The application role holds
-- INSERT here, so a channel can be attached to an acceptance that already
-- exists (measured in the fix round: there is no door that does it, and a
-- raw insert as the role is accepted). Nothing here forbids that; this makes
-- it SELF-DESCRIBING, which is this module's rule for every other record
-- (accepted_by, issued_by, set_by, authorised_by). A channel written with its
-- acceptance carries the acceptance's own instant and name -- one clock, and
-- a test holds the two equal -- so "when did they agree to texts" is answered
-- by the channel row whichever way it arrived. NOT NULL with NO DEFAULT: the
-- instant is stated by the writer, never supplied by the database.
-- ---------------------------------------------------------------------------
CREATE TABLE acceptance_channels (
  tenant_id      uuid         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  acceptance_id  uuid         NOT NULL,
  channel        text         NOT NULL CHECK (channel IN ('email', 'sms')),
  text_shown     text         NOT NULL CHECK (length(btrim(text_shown)) > 0),
  consented_by   text         NOT NULL CHECK (length(btrim(consented_by)) > 0),
  consented_at   timestamptz  NOT NULL,
  PRIMARY KEY (tenant_id, acceptance_id, channel),
  CONSTRAINT acceptance_channels_acceptance_in_tenant
    FOREIGN KEY (tenant_id, acceptance_id)
    REFERENCES terms_acceptances (tenant_id, id) ON DELETE CASCADE
);

ALTER TABLE acceptance_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE acceptance_channels FORCE  ROW LEVEL SECURITY;
CREATE POLICY acceptance_channels_tenant_isolation ON acceptance_channels
  USING      (tenant_id = current_tenant_id())
  WITH CHECK (tenant_id = current_tenant_id());

-- ---------------------------------------------------------------------------
-- Grants. The app role gets DML and nothing structural -- and on the three
-- histories it gets SELECT and INSERT only, which is what "append-only" means
-- here: a grant the catalogue can be asked about, not a promise. On `tenants`
-- it gets SELECT only: this module reads the tenant row and never writes one.
--
-- NO DELETE ANYWHERE. The module issues no DELETE (measured), and a DELETE on
-- `customers` or `tenants` would erase the append-only histories through the
-- ON DELETE CASCADE keys above. The cascades stay: they are correct for an
-- OWNER-run deletion, and retention in this project is redaction, not
-- deletion. A test asserts the application role holds DELETE on no table in
-- the schema, every table read from the catalogue.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO customer_account_app;
GRANT SELECT ON tenants TO customer_account_app;
GRANT SELECT, INSERT, UPDATE ON
  customers, customer_credentials, pending_email_changes, credential_resets
TO customer_account_app;
GRANT SELECT, INSERT ON
  customer_email_changes, terms_acceptances, acceptance_channels
TO customer_account_app;
GRANT EXECUTE ON FUNCTION current_tenant_id() TO customer_account_app;

COMMIT;
