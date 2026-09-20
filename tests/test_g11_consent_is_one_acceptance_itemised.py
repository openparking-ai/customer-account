"""G11 -- consent is ONE acceptance, itemised: the version, the text shown, who
and when, and for each channel the text shown for it -- never a boolean.

His instruction is one acceptance at account creation covering everything --
emails, texts, responsibilities. That stands: the acceptance is a single
record. And it itemises: for each channel consent was asked for, the text
shown for that channel, as child rows. One acceptance, itemised evidence, so
"what did they agree to for texts" has an answer without a second
acceptance and after the terms change.

**AN ACCOUNT IS CREATED WITH ITS FIRST ACCEPTANCE OR NOT AT ALL.** The two
writes are one transaction; a missing acceptance is refused by name before
anything is written; and a failure after the customer row leaves no customer.

Controls: the blank-text check planted away; the creation's acceptance
planted away.
"""

from __future__ import annotations

import pytest

from customer_account import findings as f
from customer_account.consent import Channel, ChannelShown, build_acceptance
from customer_account.store.postgres import tenant
from customer_account.store.records import (
    create_account,
    record_acceptance,
    show_acceptances,
    show_account,
)
from store_harness import (
    CREATED_AT,
    EMAIL_SHOWN,
    LATER,
    SMS_SHOWN,
    TERMS_V1,
    acceptance,
    needs_postgres,
    query,
    seed_customer,
)

pytestmark = needs_postgres


@pytest.mark.guarantee("G11")
def test_the_first_acceptance_is_written_with_the_account_itemised_per_channel(app, tenant_id):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        recorded = show_acceptances(cursor, tenant_id, customer_id)
    app.rollback()
    assert len(recorded) == 1
    only = recorded[0]
    assert only["terms_version"] == "v1" and only["terms_shown"] == TERMS_V1
    assert only["accepted_by"] == "self-registration" and only["accepted_at"] == CREATED_AT
    assert only["channels"] == [
        {"channel": "email", "text_shown": EMAIL_SHOWN},
        {"channel": "sms", "text_shown": SMS_SHOWN},
    ]


@pytest.mark.guarantee("G11")
def test_an_account_without_an_acceptance_is_refused_by_name_and_nothing_is_written(
    app, tenant_id
):
    with pytest.raises(f.Refused) as refused:
        build_acceptance(terms_version=None, terms_shown=TERMS_V1, accepted_by="x",
                         accepted_at=CREATED_AT, channels=None)
    assert refused.value.code == f.REFUSAL_TERMS_NOT_ACCEPTED
    assert refused.value.field == "terms_version"
    assert query(app, tenant_id, "SELECT count(*) FROM customers") == [(0,)]


@pytest.mark.guarantee("G11")
def test_a_blank_text_an_unknown_channel_and_a_repeated_channel_are_each_refused_by_name():
    with pytest.raises(f.Refused) as blank:
        build_acceptance(terms_version="v1", terms_shown="   \n", accepted_by="x",
                         accepted_at=CREATED_AT, channels=None)
    assert blank.value.code == f.REFUSAL_TERMS_TEXT_BLANK
    with pytest.raises(f.Refused) as blank_channel:
        build_acceptance(terms_version="v1", terms_shown=TERMS_V1, accepted_by="x",
                         accepted_at=CREATED_AT, channels={"sms": ""})
    assert blank_channel.value.code == f.REFUSAL_TERMS_TEXT_BLANK
    assert blank_channel.value.field == "channel[sms]"
    with pytest.raises(f.Refused) as unknown:
        build_acceptance(terms_version="v1", terms_shown=TERMS_V1, accepted_by="x",
                         accepted_at=CREATED_AT, channels={"fax": "we will fax you"})
    assert unknown.value.code == f.REFUSAL_CHANNEL_UNKNOWN
    with pytest.raises(f.Refused) as repeated:
        build_acceptance(terms_version="v1", terms_shown=TERMS_V1, accepted_by="x",
                         accepted_at=CREATED_AT, channels={"sms": "a", "SMS": "b"})
    # 'SMS' is not a channel name; the case is not folded, because the enum is the set
    assert repeated.value.code == f.REFUSAL_CHANNEL_UNKNOWN
    assert [c.value for c in Channel] == ["email", "sms"]


@pytest.mark.guarantee("G11")
def test_the_migration_refuses_an_unknown_channel_and_a_blank_text_on_a_raw_write(
    app, owner, tenant_id
):
    import psycopg

    customer_id = seed_customer(app, tenant_id)
    (acceptance_id,) = query(app, tenant_id, "SELECT id FROM terms_acceptances")[0]
    for channel, text in (("fax", "we will fax you"), ("email", "   ")):
        with owner.cursor() as cursor:
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    "INSERT INTO acceptance_channels (tenant_id, acceptance_id, channel, "
                    "text_shown) VALUES (%s, %s, %s, %s)",
                    (str(tenant_id), str(acceptance_id), channel, text),
                )
    assert customer_id is not None


@pytest.mark.guarantee("G11")
def test_a_later_acceptance_is_a_second_record_and_the_first_stands(app, tenant_id):
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        record_acceptance(cursor, tenant_id, customer_id, acceptance(
            "v2", at=LATER, by="the customer, on the portal",
            channels=(ChannelShown(Channel.EMAIL, "Version 2 of the email notice."),)))
        recorded = show_acceptances(cursor, tenant_id, customer_id)
        summary = show_account(cursor, tenant_id, customer_id)["acceptances"]
    app.rollback()
    assert [a["terms_version"] for a in recorded] == ["v1", "v2"]
    assert recorded[0]["channels"][1]["text_shown"] == SMS_SHOWN, "the first record stands"
    assert [c["channel"] for c in recorded[1]["channels"]] == ["email"]
    assert summary == {"count": 2, "latest_accepted_at": LATER}


@pytest.mark.guarantee("G11")
def test_a_failure_after_the_customer_row_leaves_no_customer(app, tenant_id, monkeypatch):
    """The two writes are one transaction: the acceptance's INSERT is made to
    fail and the customer row must not survive it."""
    from customer_account.store import records

    def failing(cursor, tenant_id_, customer_id_, acceptance_):
        raise RuntimeError("planted: the acceptance could not be written")

    monkeypatch.setattr(records, "record_acceptance", failing)
    with pytest.raises(RuntimeError):
        with tenant(app, tenant_id) as cursor:
            create_account(cursor, tenant_id, email="x@example.com", external_id=None,
                           name=None, phone=None, at=CREATED_AT, acceptance=acceptance())
    app.rollback()
    assert query(app, tenant_id, "SELECT count(*) FROM customers") == [(0,)]
