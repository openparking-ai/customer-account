-- 0002 — a one-time token is never redeemed before it was issued.
--
-- Run as the database OWNER, after 0001. It creates nothing and grants
-- nothing: one CHECK on each of the two token tables.
--
-- The module refuses, by name, a token presented at an instant before its own
-- issue (REFUSAL_INSTANT_BEFORE_ISSUE): a clock that disagrees with the one
-- that issued the token, or a confirmation replayed with an old instant. This
-- is the store's backstop for the same rule, so a raw write cannot record a
-- redemption that happened before the token existed. `redeemed_at` is NULL
-- until the token is spent, and a NULL passes the check.
--
-- Adding a CHECK validates the rows already there: on a database holding a
-- row that breaks the rule, this migration stops at that constraint's name
-- and changes nothing.

BEGIN;

ALTER TABLE pending_email_changes
  ADD CONSTRAINT pending_email_changes_redeemed_not_before_issue
  CHECK (redeemed_at IS NULL OR redeemed_at >= issued_at);

ALTER TABLE credential_resets
  ADD CONSTRAINT credential_resets_redeemed_not_before_issue
  CHECK (redeemed_at IS NULL OR redeemed_at >= issued_at);

COMMIT;
