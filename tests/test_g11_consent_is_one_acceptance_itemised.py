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

**ACCEPTANCES ACCUMULATE, AND THE CHANNEL ROW IS SELF-DESCRIBING.** The fix
round measured that no door adds a channel to an existing acceptance -- the
one door writes channels for the acceptance it is creating -- so a later
acceptance is the only way later consent is recorded, and there is no
uniqueness on (customer, version) on purpose: a second acceptance of the same
version is a further row, and the current row for a version is the latest by
``accepted_at``. The same measurement found the application role CAN attach
a channel to an old acceptance by a raw insert, so every channel row carries
``consented_by`` and ``consented_at``, NOT NULL with no default; one written
with its acceptance carries the acceptance's own instant and name, and the
test below holds the two equal so nobody invents a second clock.

**THE ORDER IS STATED, AND A FULL TIE IS ORDERED BY id.** The gate measured
that two acceptances written in one transaction tie on ``accepted_at`` AND on
``created_at`` (``now()`` is the transaction's instant), and that the read
order was stable 150/150 -- behaviour, stated nowhere. ``records.
ACCEPTANCE_ORDER`` is now the one place the order is written: ``accepted_at,
created_at, id``. ``id`` is unique on every row, so a full tie reads the same
way on every read; the order it gives is ARBITRARY and the contract says so.
``clock_timestamp()`` on ``created_at`` was rejected: every table here
defaults ``created_at`` to ``now()``, and one rule in two places is the
error this project keeps paying for. The tie test below writes eight
acceptances in one transaction so the chance that insertion order happens to
equal id order, and the old ordering reads the same by luck, is 1 in 40,320.

**A REPEATED CHANNEL IS REFUSED AT THE DOOR, BEFORE THE DICT COLLAPSES IT.**
The re-gate measured that the one raise site of ``REFUSAL_CHANNEL_REPEATED``
sat inside ``build_acceptance``, whose channels arrive as a dict -- and a
dict cannot hold a repeated key -- so no door could raise it, and
``create-account --channel sms=A --channel sms=B`` exited 0 with B on the
row: the LAST one won, silently, stated nowhere. For a record whose whole
claim is "this is the text they were shown", that is a false sentence.
``cli._channels`` now refuses the repeated NAME by the published code before
anything collapses it, and the tests below drive THAT door -- the command
line, exit 3, JSON -- not the internal raise site. ``SMS`` beside ``sms`` is
not a repeat: the case is not folded, the enum is the set, and it is refused
as unknown under its own name.

Controls: the blank-text check planted away; the creation's acceptance
planted away; the channel's instant planted to a clock of its own; the
tiebreak column planted away; the door's repeat check planted away.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from customer_account import findings as f
from customer_account.consent import Channel, ChannelShown, build_acceptance
from customer_account.store.postgres import tenant
from customer_account.store.records import (
    ACCEPTANCE_ORDER,
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
        {"channel": "email", "text_shown": EMAIL_SHOWN, "consented_by": "self-registration",
         "consented_at": CREATED_AT},
        {"channel": "sms", "text_shown": SMS_SHOWN, "consented_by": "self-registration",
         "consented_at": CREATED_AT},
    ]


@pytest.mark.guarantee("G11")
def test_a_channel_written_with_its_acceptance_carries_the_acceptances_own_clock_and_name(
    app, tenant_id
):
    """ONE CLOCK. Read from the rows, joined, not from the rendered read."""
    seed_customer(app, tenant_id)
    rows = query(app, tenant_id, (
        "SELECT a.accepted_by = c.consented_by, a.accepted_at = c.consented_at, "
        "a.accepted_at, c.consented_at FROM acceptance_channels c "
        "JOIN terms_acceptances a ON a.tenant_id = c.tenant_id AND a.id = c.acceptance_id"))
    assert len(rows) == 2, "the seed writes two channel rows: the denominator"
    assert all(same_by and same_at for same_by, same_at, _, _ in rows), rows
    assert {r[3] for r in rows} == {CREATED_AT}


@pytest.mark.guarantee("G11")
def test_a_channel_row_without_its_instant_or_its_name_is_refused_by_the_schema(
    app, owner, tenant_id
):
    """NOT NULL, no default: even the OWNER cannot write an undated channel.
    The positive control is the same insert with both stated, which lands."""
    import psycopg

    customer_id = seed_customer(app, tenant_id)
    (acceptance_id,) = query(app, tenant_id, "SELECT id FROM terms_acceptances")[0]
    with owner.cursor() as cursor:
        cursor.execute(
            "DELETE FROM acceptance_channels WHERE acceptance_id = %s AND channel = 'sms'",
            (str(acceptance_id),))
        for columns, values in (
            ("channel, text_shown", "'sms', 'late text'"),
            ("channel, text_shown, consented_by", "'sms', 'late text', 'late'"),
            ("channel, text_shown, consented_at", "'sms', 'late text', now()"),
        ):
            with pytest.raises(psycopg.errors.NotNullViolation):
                cursor.execute(
                    f"INSERT INTO acceptance_channels (tenant_id, acceptance_id, {columns}) "
                    f"VALUES (%s, %s, {values})", (str(tenant_id), str(acceptance_id)))
        cursor.execute(
            "INSERT INTO acceptance_channels (tenant_id, acceptance_id, channel, text_shown, "
            "consented_by, consented_at) VALUES (%s, %s, 'sms', 'late text', 'late', %s)",
            (str(tenant_id), str(acceptance_id), LATER))
        assert cursor.rowcount == 1, "the control: stated, it lands"
    with tenant(app, tenant_id) as cursor:
        recorded = show_acceptances(cursor, tenant_id, customer_id)
    app.rollback()
    late = [c for c in recorded[0]["channels"] if c["channel"] == "sms"]
    assert late == [{"channel": "sms", "text_shown": "late text", "consented_by": "late",
                     "consented_at": LATER}], "the late channel says when and by whom"


@pytest.mark.guarantee("G11")
def test_a_second_acceptance_of_the_same_version_accumulates_and_the_latest_is_current(
    app, tenant_id
):
    """MEASURED in the fix round, then published: no door adds a channel to an
    existing acceptance, so this is how later consent is recorded. Two rows,
    oldest first, the second current; the first stands untouched."""
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        record_acceptance(cursor, tenant_id, customer_id, acceptance(
            "v1", at=LATER, by="the customer, again",
            channels=(ChannelShown(Channel.SMS, "Texts, agreed to later."),)))
        recorded = show_acceptances(cursor, tenant_id, customer_id)
        summary = show_account(cursor, tenant_id, customer_id)["acceptances"]
    app.commit()
    assert [(a["terms_version"], a["accepted_at"]) for a in recorded] == [
        ("v1", CREATED_AT), ("v1", LATER)]
    assert recorded[0]["accepted_by"] == "self-registration", "the first row stands"
    assert recorded[-1]["accepted_by"] == "the customer, again", "the latest is last"
    assert recorded[-1]["channels"] == [{"channel": "sms", "text_shown": "Texts, agreed to later.",
                                         "consented_by": "the customer, again",
                                         "consented_at": LATER}]
    assert summary == {"count": 2, "latest_accepted_at": LATER}
    assert query(app, tenant_id, "SELECT count(*) FROM terms_acceptances") == [(2,)]


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
def test_a_blank_text_and_an_unknown_channel_are_each_refused_by_name():
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
    with pytest.raises(f.Refused) as cased:
        build_acceptance(terms_version="v1", terms_shown=TERMS_V1, accepted_by="x",
                         accepted_at=CREATED_AT, channels={"sms": "a", "SMS": "b"})
    # 'SMS' beside 'sms' is NOT a repeat: the case is not folded, the enum is the set,
    # and it is refused as unknown under its own name
    assert cased.value.code == f.REFUSAL_CHANNEL_UNKNOWN
    assert [c.value for c in Channel] == ["email", "sms"]


def _cli(argv, capsys):
    from customer_account.cli import main

    status = main(argv)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def _create(tenant_id, tmp_path, *tail):
    terms = tmp_path / "terms.txt"
    terms.write_text(TERMS_V1)
    return ["create-account", "--tenant", str(tenant_id), "--by", "self",
            "--at", "2026-06-01T09:00:00-06:00", "--terms-version", "v1",
            "--terms-shown", str(terms), *tail]


@pytest.mark.guarantee("G11")
def test_a_repeated_channel_is_refused_by_name_at_the_door_before_the_dict_collapses_it(
    tmp_path
):
    """THE DOOR, not the internal raise site: ``cli._channels`` is what the
    command line hands its pairs to. The second file does not exist, so had
    the pair been READ before it was judged, the refusal would have been
    DOCUMENT_UNREADABLE -- it is the repeat that is refused, on the name."""
    from customer_account.cli import _channels

    first = tmp_path / "sms_a.txt"
    first.write_text("first sms text")
    with pytest.raises(f.Refused) as repeated:
        _channels([f"sms={first}", "sms=/nowhere/sms_b.txt"])
    assert repeated.value.code == f.REFUSAL_CHANNEL_REPEATED
    assert repeated.value.field == "--channel"
    assert "sms" in repeated.value.detail


@pytest.mark.guarantee("G11")
def test_the_command_line_refuses_a_repeated_channel_exit_3_and_writes_nothing(
    app, tenant_id, tmp_path, capsys, monkeypatch
):
    """The re-gate's own shape, driven again: exit 0 and B on the row before;
    exit 3, the published code, and NO customer row now."""
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    a, b = tmp_path / "sms_a.txt", tmp_path / "sms_b.txt"
    a.write_text("first sms text")
    b.write_text("second sms text")
    status, out, err = _cli(_create(tenant_id, tmp_path, "--email", "alice@example.com",
                                    "--channel", f"sms={a}", "--channel", f"sms={b}"), capsys)
    assert status == 3 and err == "", (out, err)
    printed = json.loads(out)
    assert printed["refused"] == f.REFUSAL_CHANNEL_REPEATED
    assert printed["field"] == "--channel"
    assert query(app, tenant_id, "SELECT count(*) FROM customers") == [(0,)]
    assert query(app, tenant_id, "SELECT count(*) FROM acceptance_channels") == [(0,)]


@pytest.mark.guarantee("G11")
def test_one_channel_and_two_different_channels_still_land_with_their_own_texts(
    app, tenant_id, tmp_path, capsys, monkeypatch
):
    """THE OVER-REACH CONTROLS, through the same door: a single channel is
    unaffected; two DIFFERENT channels both land, each with the text that
    was shown for IT, read back from the rows."""
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    email, sms = tmp_path / "email.txt", tmp_path / "sms.txt"
    email.write_text("the email text")
    sms.write_text("the sms text")
    status, out, _ = _cli(_create(tenant_id, tmp_path, "--email", "one@example.com",
                                  "--channel", f"sms={sms}"), capsys)
    assert status == 0, out
    one = json.loads(out)["customer"]
    status, out, _ = _cli(_create(tenant_id, tmp_path, "--email", "two@example.com",
                                  "--channel", f"email={email}", "--channel", f"sms={sms}"),
                          capsys)
    assert status == 0, out
    two = json.loads(out)["customer"]
    rows = query(app, tenant_id, (
        "SELECT a.customer_id::text, c.channel, c.text_shown FROM acceptance_channels c "
        "JOIN terms_acceptances a ON a.tenant_id = c.tenant_id AND a.id = c.acceptance_id "
        "ORDER BY a.customer_id::text = %s, c.channel"), (two,))
    assert rows == [(one, "sms", "the sms text"),
                    (two, "email", "the email text"), (two, "sms", "the sms text")]


@pytest.mark.guarantee("G11")
@pytest.mark.parametrize(
    "channel_pair,code,field",
    [
        ("fax=FILE", f.REFUSAL_CHANNEL_UNKNOWN, "channel"),
        ("sms=BLANK", f.REFUSAL_TERMS_TEXT_BLANK, "channel[sms]"),
    ],
    ids=["unknown channel", "blank text"],
)
def test_the_unknown_channel_and_blank_text_refusals_keep_their_names_at_the_door(
    app, tenant_id, tmp_path, capsys, monkeypatch, channel_pair, code, field
):
    """The two neighbours of the new check, driven through the same door,
    keep their names and their fields."""
    from test_g3_no_plaintext_is_stored_or_rendered_twice import dsn_for_the_app

    dsn_for_the_app(monkeypatch)
    text, blank = tmp_path / "text.txt", tmp_path / "blank.txt"
    text.write_text("a text shown")
    blank.write_text("   \n")
    pair = channel_pair.replace("FILE", str(text)).replace("BLANK", str(blank))
    status, out, _ = _cli(_create(tenant_id, tmp_path, "--email", "x@example.com",
                                  "--channel", pair), capsys)
    assert status == 3, out
    printed = json.loads(out)
    assert (printed["refused"], printed["field"]) == (code, field), printed
    assert query(app, tenant_id, "SELECT count(*) FROM customers") == [(0,)]


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
                    "text_shown, consented_by, consented_at) VALUES (%s, %s, %s, %s, 'raw', %s)",
                    (str(tenant_id), str(acceptance_id), channel, text, LATER),
                )
    assert customer_id is not None


@pytest.mark.guarantee("G11")
def test_acceptances_sharing_an_instant_tie_on_both_clocks_and_are_read_in_id_order(
    app, tenant_id
):
    """Eight acceptances in ONE transaction, all at LATER: accepted_at ties by
    construction and created_at ties because now() is the transaction's
    instant -- both measured here, not assumed -- and the read comes back in
    id order, the stated tiebreak."""
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        for n in range(8):
            record_acceptance(cursor, tenant_id, customer_id, acceptance(
                "v1", at=LATER, by=f"writer {n}",
                channels=(ChannelShown(Channel.SMS, f"Texts, agreed to again ({n})."),)))
        recorded = show_acceptances(cursor, tenant_id, customer_id)
    app.commit()
    tied = [row for row in recorded if row["accepted_at"] == LATER]
    assert len(tied) == 8 and recorded[0]["accepted_at"] == CREATED_AT
    clocks = query(app, tenant_id, "SELECT count(DISTINCT created_at) FROM terms_acceptances "
                   "WHERE customer_id = %s AND accepted_at = %s", (str(customer_id), LATER))
    assert clocks == [(1,)], "created_at did not tie, so this measured nothing about the tie"
    ids = [UUID(row["acceptance"]) for row in tied]
    assert ids == sorted(ids), "a full tie is read in id order"
    assert ACCEPTANCE_ORDER == ("accepted_at", "created_at", "id")


@pytest.mark.guarantee("G11")
def test_the_tiebreak_changes_nothing_for_acceptances_that_do_not_tie(app, tenant_id):
    """THE OVER-REACH CONTROL: on a pair with distinct accepted_at the old
    ordering and the stated one read identically -- the current row is still
    the latest accepted_at."""
    customer_id = seed_customer(app, tenant_id)
    with tenant(app, tenant_id) as cursor:
        record_acceptance(cursor, tenant_id, customer_id, acceptance(
            "v1", at=LATER, by="the customer, again",
            channels=(ChannelShown(Channel.SMS, "Texts, agreed to later."),)))
    app.commit()
    select = "SELECT id FROM terms_acceptances WHERE customer_id = %s ORDER BY "
    old = query(app, tenant_id, select + "accepted_at, created_at", (str(customer_id),))
    stated = query(app, tenant_id, select + ", ".join(ACCEPTANCE_ORDER), (str(customer_id),))
    assert old == stated and len(stated) == 2
    with tenant(app, tenant_id) as cursor:
        recorded = show_acceptances(cursor, tenant_id, customer_id)
    app.rollback()
    assert [str(row[0]) for row in stated] == [row["acceptance"] for row in recorded]
    assert recorded[-1]["accepted_at"] == LATER, "the current row is the latest accepted_at"


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
