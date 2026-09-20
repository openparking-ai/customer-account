"""Recorded consent: one acceptance, itemised evidence.

**THE SHAPE IS THE SIBLING BILLING MODULE'S MANDATE, COPIED.** A mandate there
records who agreed, when, and the terms IN THE WORDS THEY WERE SHOWN -- not a
boolean. "They accepted" without the version and the text is worthless the
first time the terms change. So an acceptance here carries ``terms_version``,
``terms_shown``, ``accepted_by`` and ``accepted_at``, and is append-only by
grant: there is no UPDATE and no DELETE on it for the application role, and a
test reads that grant from the catalogue.

**ONE ACCEPTANCE AT ACCOUNT CREATION COVERS EVERYTHING -- AND NAMES EACH
CHANNEL CONSENTED TO WITH THE TEXT SHOWN FOR IT.** His instruction is one
acceptance covering emails, texts and responsibilities; that stands. The
acceptance is a single record, and it itemises: for each channel consent was
asked for (``email``, ``sms``), the text that was shown for that channel. One
acceptance, itemised evidence -- so "what did they agree to for texts" has an
answer without a second acceptance. There is no separate SMS acceptance.

**A CHANNEL IS A NAME, NOT FREE TEXT.** The two channels are the ones consent
is asked for by name today; a third is a migration and a contract change, not
a value somebody types. A typo in a consent record would otherwise be a channel
nobody consented to that reads as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from customer_account.findings import (
    REFUSAL_CHANNEL_REPEATED,
    REFUSAL_CHANNEL_UNKNOWN,
    REFUSAL_TERMS_NOT_ACCEPTED,
    REFUSAL_TERMS_TEXT_BLANK,
    Refused,
)
from customer_account.identity import require_aware, require_text


class Channel(Enum):
    EMAIL = "email"
    SMS = "sms"


def parse_channel(name: object) -> Channel:
    try:
        return Channel(name)
    except ValueError:
        raise Refused(
            REFUSAL_CHANNEL_UNKNOWN, "channel",
            f"{name!r}; the channels are {[c.value for c in Channel]}.",
        ) from None


@dataclass(frozen=True)
class ChannelShown:
    """One channel consent was asked for, and the text shown for it."""

    channel: Channel
    text_shown: str


@dataclass(frozen=True)
class Acceptance:
    """What a customer agreed to, in the words they were shown."""

    terms_version: str
    terms_shown: str
    accepted_by: str
    accepted_at: datetime
    channels: tuple[ChannelShown, ...]


def require_shown(value: object, field: str) -> str:
    """The text shown, which may run to many lines (it is the terms) and may
    not be blank."""
    if not isinstance(value, str) or not value.strip():
        raise Refused(REFUSAL_TERMS_TEXT_BLANK, field, f"{field} is blank.")
    return value


def build_acceptance(
    *,
    terms_version: object,
    terms_shown: object,
    accepted_by: object,
    accepted_at: object,
    channels: dict[str, str] | None,
) -> Acceptance:
    """An acceptance from what the caller gave, every part held to its rule,
    or a refusal by name. A missing part is REFUSAL_TERMS_NOT_ACCEPTED: the
    account is created with its terms accepted or not at all."""
    if terms_version is None or terms_shown is None or accepted_by is None:
        missing = [
            name for name, value in (("terms_version", terms_version),
                                     ("terms_shown", terms_shown),
                                     ("accepted_by", accepted_by))
            if value is None
        ]
        raise Refused(
            REFUSAL_TERMS_NOT_ACCEPTED, missing[0], f"{', '.join(missing)} not given."
        )
    seen: list[ChannelShown] = []
    for name, text in (channels or {}).items():
        channel = parse_channel(name)
        if any(s.channel is channel for s in seen):
            # Unreachable through any door as the module stands: ``channels``
            # is a dict, a dict cannot hold a repeated key, and ``Channel``
            # matches exact values -- so the door (``cli._channels``) refuses
            # the repeat by this name BEFORE the dict collapses it. Measured
            # by the re-gate; this guard stays as the type's own statement.
            raise Refused(REFUSAL_CHANNEL_REPEATED, "channel", f"{channel.value} given twice.")
        seen.append(ChannelShown(channel=channel, text_shown=require_shown(
            text, f"channel[{channel.value}]")))
    return Acceptance(
        terms_version=require_text(terms_version, "terms_version"),
        terms_shown=require_shown(terms_shown, "terms_shown"),
        accepted_by=require_text(accepted_by, "accepted_by"),
        accepted_at=require_aware(accepted_at, "accepted_at"),
        channels=tuple(seen),
    )
