################################################################################
# File Name: currency.py
# Purpose/Description: US-795-b -- answer whether the vehicle is current in
#                      exactly three states, each carrying the timestamp of the
#                      contact it describes. Read-only: it reads the residual
#                      US-795-a persists and writes nothing.
# Author: Ralph (US-795-b)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-795-b) | Initial -- three states, age is never a
#               |                  | fault, a flat residual is the only one.
# 2026-10-06    | Atlas (US-795a)  | CIO-ruled sentence: last contact + age +
#               |                  | N queued (exact|at least) + drive/sensor
#               |                  | split + alarm. States/stall unchanged.
# ================================================================================
################################################################################
"""Vehicle currency, answered honestly.

🔴 **THE LITERAL QUESTION IS UNDECIDABLE AND THIS MODULE DOES NOT PRETEND
OTHERWISE.**  "Is the car current *now*" cannot be answered from here: rows
created after the last contact are invisible to the server **by
construction**.  What the server can say is what was true **at last contact**,
so every state carries the timestamp of the contact it describes.

**That is why the obvious one-word answer is banned here.**  The word this
module may not use is a claim in the PRESENT TENSE built out of a fact about
the past.  The three state names and every rendered answer avoid it
deliberately -- not as a style rule, but because it asserts something the data
cannot support.  (The banned word is not written even in this docstring, so the
guard in ``tests/server/test_vehicle_currency.py`` can stay a plain
case-insensitive scan: a guard that has to carve out its own documentation is a
guard someone eventually widens by accident.)

⚠️ **STALENESS IS NOT A FAULT.**  A parked car last heard from on Friday reads
``last contact <Friday> (2 d ... ago) ... nothing known since``.  That is
correct and it is the ordinary weekend state.  Alarming on it would train everyone to ignore the one alarm that means
something.

🔴 **The one legitimate alarm is a car that IS talking and still not
draining** -- a residual flat or rising across a run of consecutive contacts.
Age alone is never that, and the two are distinguishable precisely because a
stalled drain requires contacts to have happened.

⚠️ **Worked case, and the limit of what this can tell you.**  At 19:35:30Z
session 216962 completed: 216 rows, zero errors, and the Pi genuinely was
caught up.  The CIO then drove, and the Pi never contacted the server again.
``last contact 19:35:30Z (...): 0 queued (exact); nothing known since`` is the
correct answer and it says nothing at all about the drive that followed.  The timestamp is not decoration; it is the
entire qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

__all__ = [
    'CURRENCY_MODULE_PATH',
    'DEFAULT_STALLED_RUN_LENGTH',
    'ContactRecord',
    'CurrencyAnswer',
    'CurrencyState',
    'assessVehicleCurrency',
    'formatAge',
    'renderCurrency',
]

#: This module's own path, so a guard can scan it without hardcoding a path
#: that silently stops matching when the file moves.
CURRENCY_MODULE_PATH: str = __file__

#: How many consecutive contacts must fail to reduce the backlog before it is
#: called a stall.  THREE, and the length matters: ONE non-decrease is not
#: evidence of anything, because rows can be created between contacts at the
#: same rate they drain and that looks identical to a stall.  A run of three
#: is the story's own worked example (400, 400, 400) and is the shortest run
#: that distinguishes a stalled drain from a busy one.  A parameter rather
#: than a literal at the call site, per the Developer Rules.
DEFAULT_STALLED_RUN_LENGTH: int = 3

_ISO_FORMAT: str = '%Y-%m-%dT%H:%M:%SZ'



class CurrencyState(Enum):
    """What the server knows about the car, as of its last contact.

    Exactly three, and a fourth must not be added casually: an unrendered
    state is how a present-tense claim gets back in through the side door.
    """

    #: Owed nothing at last contact.
    CURRENT = 'current'
    #: Still held rows at last contact -- a LOWER bound on what it holds now.
    HOLDING = 'holding'
    #: Never heard from, or the last contact could not measure what it held.
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ContactRecord:
    """One completed sync session, as the server recorded it.

    Attributes:
        contactedAt: When the session closed.
        residualRows: What the car still held, or None when unmeasured.
        residualComplete: False when the count is a LOWER bound because some
            table was unreadable; None when nothing was measured at all.
    """

    contactedAt: datetime
    residualRows: int | None
    residualComplete: bool | None
    #: US-795(a): the split of residualRows, None when the Pi did not send it.
    residualDriveRows: int | None = None
    residualSensorRows: int | None = None


@dataclass(frozen=True)
class CurrencyAnswer:
    """The answer, with the qualification attached rather than implied.

    Attributes:
        state: One of :class:`CurrencyState`.
        asOf: The contact this describes, or None when there has never been
            one. NEVER the current time -- that would be the undecidable
            question wearing the shape of an answer.
        outstandingRows: The lower bound on what the car held, when known.
        exact: False when the count is a lower bound (a table was unreadable).
        fault: The single legitimate alarm, or None. Age never sets this.
    """

    state: CurrencyState
    asOf: datetime | None
    outstandingRows: int | None = None
    exact: bool | None = None
    fault: str | None = None
    #: US-795(a): the split of outstandingRows, when the contact carried one.
    driveRows: int | None = None
    sensorRows: int | None = None


def assessVehicleCurrency(
    contacts: list[ContactRecord],
    stalledRunLength: int = DEFAULT_STALLED_RUN_LENGTH,
) -> CurrencyAnswer:
    """Answer what was true at the car's last contact.

    Args:
        contacts: Completed sessions in ascending time order; the last entry
            is the most recent.
        stalledRunLength: How many consecutive contacts must fail to reduce a
            NON-ZERO backlog before it is reported as a fault.

    Returns:
        The state, its timestamp, and a fault only when the backlog is
        provably not draining.
    """
    if not contacts:
        # No contact has ever happened. There is no instant to name and none
        # is invented; and this is NOT a fault -- a car that has never been
        # heard from may simply be new.
        return CurrencyAnswer(state=CurrencyState.UNKNOWN, asOf=None)

    latest = contacts[-1]
    fault = _stalledDrainFault(contacts, stalledRunLength)

    if latest.residualRows is None:
        # A contact happened, so 'since' is real -- but nothing was learned
        # about what the car held. Reporting that as CURRENT would claim a
        # measurement that did not occur.
        return CurrencyAnswer(
            state=CurrencyState.UNKNOWN, asOf=latest.contactedAt, fault=fault,
        )

    if latest.residualRows == 0 and latest.residualComplete:
        # Owed nothing, and every table could be read. This is the only shape
        # that earns CURRENT: a 0 whose completeness is unknown is a 0 we
        # cannot stand behind.
        return CurrencyAnswer(
            state=CurrencyState.CURRENT, asOf=latest.contactedAt,
            outstandingRows=0, exact=True, fault=fault,
            driveRows=latest.residualDriveRows, sensorRows=latest.residualSensorRows,
        )

    return CurrencyAnswer(
        state=CurrencyState.HOLDING,
        asOf=latest.contactedAt,
        outstandingRows=latest.residualRows,
        exact=latest.residualComplete,
        fault=fault,
        driveRows=latest.residualDriveRows,
        sensorRows=latest.residualSensorRows,
    )


def _stalledDrainFault(
    contacts: list[ContactRecord], runLength: int
) -> str | None:
    """Report a backlog that is not draining, and nothing else.

    A stall needs contacts to have HAPPENED, which is exactly what makes it
    distinguishable from staleness: an old car that has said nothing since
    cannot be shown to have stalled, only to have gone quiet.

    A backlog pinned at ZERO is excluded. It "fails to decrease" arithmetically
    and is the healthiest state there is; reading the rule literally without
    that carve-out would alarm on a perfectly working car at every contact.

    Args:
        contacts: Sessions in ascending time order.
        runLength: How many consecutive contacts must fail to reduce it.

    Returns:
        A description of the stall, or None.
    """
    measured = [c for c in contacts if c.residualRows is not None][-runLength:]
    if len(measured) < runLength:
        return None

    counts = [c.residualRows for c in measured]
    if all(count == 0 for count in counts):
        return None
    # strict=False is deliberate: this is a PAIRWISE walk, so the second
    # sequence is shorter by exactly one and that is the intended shape.
    if any(later < earlier for earlier, later in zip(counts, counts[1:], strict=False)):
        return None

    return (
        f'backlog has not decreased across {runLength} consecutive contacts '
        f'({" -> ".join(str(c) for c in counts)}): the car is reachable and '
        'the queue is not draining'
    )


def formatAge(seconds: float) -> str:
    """Render an elapsed time for a reader, at the coarsest useful scale.

    A negative value (the reader's clock behind the contact) renders as the
    smallest bucket rather than as a negative age.
    """
    total = max(0, int(seconds))
    if total < 60:
        return 'under 1 min'
    minutes, _ = divmod(total, 60)
    if minutes < 60:
        return f'{minutes} min'
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f'{hours} h {minutes} min'
    days, hours = divmod(hours, 24)
    return f'{days} d {hours} h'


def renderCurrency(answer: CurrencyAnswer, *, now: datetime) -> str:
    """Render the answer as the CIO-ruled sentence (US-795(a), 2026-10-06).

    ``last contact <ts> (<age> ago): N queued (exact | at least) - drive D,
    sensor S; nothing known since``, plus `` | ALARM: <fault>`` when the
    backlog is not draining. No online/offline verdict, ever: the server only
    knows what was true at the contact, and "nothing known since" says so.

    Args:
        answer: The assessed currency.
        now: The reader's clock, used ONLY to state the contact's age.

    Returns:
        The one-line statement.
    """
    if answer.asOf is None:
        return 'no contact recorded; nothing known'

    head = (
        f'last contact {answer.asOf.strftime(_ISO_FORMAT)} '
        f'({formatAge((now - answer.asOf).total_seconds())} ago): '
    )
    if answer.state is CurrencyState.UNKNOWN:
        body = 'queued unknown'
    else:
        qualifier = 'exact' if answer.exact else 'at least'
        body = f'{answer.outstandingRows} queued ({qualifier})'
        if answer.driveRows is not None and answer.sensorRows is not None:
            body += f' - drive {answer.driveRows}, sensor {answer.sensorRows}'
    sentence = f'{head}{body}; nothing known since'
    if answer.fault:
        sentence += f' | ALARM: {answer.fault}'
    return sentence
