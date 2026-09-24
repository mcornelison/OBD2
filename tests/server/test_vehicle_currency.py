################################################################################
# File Name: test_vehicle_currency.py
# Purpose/Description: US-795-b -- vehicle currency answers in exactly three
#                      states, each carrying the timestamp of the contact it
#                      describes, and never the word "synced". Staleness is not
#                      a fault; a residual that will not drain is the only one.
# Author: Ralph (US-795-b)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-795-b) | Initial -- three states, no alarm on age,
#               |                  | one alarm on a flat residual.
# ================================================================================
################################################################################
"""Vehicle currency answers in three states, never "synced" (US-795-b).

🔴 THE LITERAL QUESTION IS UNDECIDABLE, and this module must not pretend
otherwise. Rows created after the last contact are invisible to the server BY
CONSTRUCTION. The server can say what was true AT LAST CONTACT; it cannot say
what is true now. Every state therefore carries the timestamp of the contact it
describes, and the word "synced" -- which is a claim about NOW -- appears in no
state name and no rendered answer.

⚠️ STALENESS IS NOT A FAULT. A parked car last heard from on Friday reads
UNKNOWN SINCE Friday. That is correct, it is the normal weekend state, and an
alarm on it would train everyone to ignore the one alarm that means something.

🔴 THE ONE LEGITIMATE ALARM: a car that IS talking and still not draining. Its
residual is flat across consecutive contacts -- 400, then 400, then 400. Age
alone is never that.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.server.api.currency import (
    CURRENCY_MODULE_PATH,
    ContactRecord,
    CurrencyState,
    assessVehicleCurrency,
    renderCurrency,
)

#: Built rather than written so the AST scan above needs no carve-out
#: for this file: the literal never appears as one string.
_BANNED_WORD = "sy" + "nced"

_NOW = datetime(2026, 9, 23, 19, 35, 30, tzinfo=UTC)
_FRIDAY = _NOW - timedelta(days=2)


def _contact(
    at: datetime, residual: int | None, complete: bool | None = True
) -> ContactRecord:
    return ContactRecord(contactedAt=at, residualRows=residual, residualComplete=complete)


class TestThreeStatesEachCarryingItsOwnTimestamp:
    """Acceptance 1 -- exactly three states, each stamped."""

    def test_caughtUpAtLastContact_isCurrentAsOfThatContact(self) -> None:
        """
        Given: a Pi that owed nothing at its last contact
        When:  currency is assessed
        Then:  CURRENT, stamped with that contact -- not with now
        """
        answer = assessVehicleCurrency([_contact(_NOW, 0)])

        assert answer.state is CurrencyState.CURRENT
        assert answer.asOf == _NOW
        assert renderCurrency(answer) == "CURRENT AS OF 2026-09-23T19:35:30Z"

    def test_holdingRowsAtLastContact_isHoldingAtLeastN(self) -> None:
        """
        Given: a Pi still holding rows at its last contact
        When:  currency is assessed
        Then:  HOLDING, with the count and that contact's timestamp

        Rendered as '>= N' because the count is a lower bound whenever any
        table was unreadable, and because MORE rows may have been created
        since -- the server cannot see them.
        """
        answer = assessVehicleCurrency([_contact(_NOW, 400)])

        assert answer.state is CurrencyState.HOLDING
        assert answer.outstandingRows == 400
        assert answer.asOf == _NOW
        assert renderCurrency(answer) == "HOLDING >= 400 AS OF 2026-09-23T19:35:30Z"

    def test_neverHeardFrom_isUnknown_withNoTimestampToGive(self) -> None:
        """
        Given: no contacts at all
        When:  currency is assessed
        Then:  UNKNOWN, and it says so rather than inventing a time
        """
        answer = assessVehicleCurrency([])

        assert answer.state is CurrencyState.UNKNOWN
        assert answer.asOf is None
        assert renderCurrency(answer) == "UNKNOWN SINCE never"

    def test_contactThatCouldNotMeasure_isUnknownSinceThatContact(self) -> None:
        """
        Given: a contact that reported no residual at all
        When:  currency is assessed
        Then:  UNKNOWN, stamped with that contact

        A contact happened, so 'since' has a real timestamp -- but nothing was
        learned about what the car held. That is different from CURRENT and
        must not be rendered as it.
        """
        answer = assessVehicleCurrency([_contact(_FRIDAY, None, None)])

        assert answer.state is CurrencyState.UNKNOWN
        assert answer.asOf == _FRIDAY
        assert renderCurrency(answer) == "UNKNOWN SINCE 2026-09-21T19:35:30Z"

    def test_theStatesAreExactlyThree(self) -> None:
        """
        Given: the CurrencyState enum
        When:  its members are listed
        Then:  there are exactly three

        A fourth state added later without a rendering is how 'synced' gets
        back in through the side door.
        """
        assert {s.name for s in CurrencyState} == {"CURRENT", "HOLDING", "UNKNOWN"}


class TestTheWordSyncedAppearsNowhere:
    """Acceptance 2 -- 'synced' is a claim about now, and is not ours to make."""

    def test_noStringThatCanReachAUserSaysIt(self) -> None:
        """
        Given: every state name, state value, rendered answer and fault text
        When:  each is scanned case-insensitively
        Then:  none contains the banned word

        SCOPED TO WHAT REACHES A USER, which is what the criterion says: "no
        match in any user-facing string or state name". An earlier draft of
        this guard scanned the raw source of the module AND of this test file,
        and it was incoherent -- a test that describes a banned word must
        NAME it, so the guard reddened on a correct tree and would have been
        deleted rather than fixed. The lesson twice over this sprint: a text
        scan that cannot tell prose from behaviour is not a guard.
        """
        answers = [
            assessVehicleCurrency([_contact(_NOW, 0)]),
            assessVehicleCurrency([_contact(_NOW, 400)]),
            assessVehicleCurrency([]),
            assessVehicleCurrency([_contact(_FRIDAY, None, None)]),
            assessVehicleCurrency([
                _contact(_NOW - timedelta(hours=2), 400),
                _contact(_NOW - timedelta(hours=1), 400),
                _contact(_NOW, 400),
            ]),
        ]

        surfaces: list[str] = [s.name for s in CurrencyState]
        surfaces += [str(s.value) for s in CurrencyState]
        surfaces += [renderCurrency(a) for a in answers]
        surfaces += [a.fault for a in answers if a.fault]

        for text in surfaces:
            assert _BANNED_WORD not in text.lower(), text

    def test_theModuleHasNoSuchStringLiteralInItsCode(self) -> None:
        """
        Given: the currency module
        When:  its AST is walked with docstrings stripped
        Then:  no string constant contains the banned word

        Docstrings stripped for the reason US-773 and US-809-c both found: a
        module is entitled to EXPLAIN a rule in prose without tripping the
        guard that enforces it. What may not exist is a literal that could be
        rendered.
        """
        tree = ast.parse(Path(CURRENCY_MODULE_PATH).read_text(encoding="utf-8"))

        docstrings = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))

        offenders = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and _BANNED_WORD in node.value.lower()
            and id(node) not in docstrings
        ]

        assert not offenders, offenders


class TestStalenessIsNotAFault:
    """Acceptance 3 -- silence is the normal parked state."""

    def test_anAncientContact_carriesNoFaultHoweverOld(self) -> None:
        """
        Given: contacts a day, a week and a year old
        When:  currency is assessed
        Then:  no fault, no severity, at any age

        A parked car is the ordinary case. Alarming on it would train everyone
        to ignore the one alarm that means something.
        """
        for age in (timedelta(days=1), timedelta(days=7), timedelta(days=365)):
            answer = assessVehicleCurrency([_contact(_NOW - age, 0)])

            assert answer.fault is None, f"age {age} raised a fault"

    def test_neverHeardFrom_isNotAFault(self) -> None:
        """
        Given: no contact has ever happened
        When:  currency is assessed
        Then:  UNKNOWN, and still no fault
        """
        assert assessVehicleCurrency([]).fault is None


class TestTheOneLegitimateAlarm:
    """Acceptance 4 -- talking and still not draining."""

    def test_residualFlatAcrossContacts_isAFault(self) -> None:
        """
        Given: three consecutive contacts each holding 400 rows
        When:  currency is assessed
        Then:  a fault is reported

        The car IS talking -- so this is not staleness -- and the backlog is
        not moving. That is the only alarm in this story.
        """
        contacts = [
            _contact(_NOW - timedelta(hours=2), 400),
            _contact(_NOW - timedelta(hours=1), 400),
            _contact(_NOW, 400),
        ]

        answer = assessVehicleCurrency(contacts)

        assert answer.fault is not None
        assert "synced" not in answer.fault.lower()

    def test_residualDraining_isNotAFault(self) -> None:
        """
        Given: three contacts whose residual falls
        When:  currency is assessed
        Then:  no fault -- this is the system working
        """
        contacts = [
            _contact(_NOW - timedelta(hours=2), 400),
            _contact(_NOW - timedelta(hours=1), 250),
            _contact(_NOW, 90),
        ]

        assert assessVehicleCurrency(contacts).fault is None

    def test_residualGrowing_isAFault(self) -> None:
        """
        Given: contacts whose residual climbs
        When:  currency is assessed
        Then:  a fault -- 'fails to decrease' includes getting worse
        """
        contacts = [
            _contact(_NOW - timedelta(hours=2), 400),
            _contact(_NOW - timedelta(hours=1), 500),
            _contact(_NOW, 650),
        ]

        assert assessVehicleCurrency(contacts).fault is not None

    def test_oldContactAlone_isNotTheFault(self) -> None:
        """
        Given: one very old contact that was holding rows
        When:  currency is assessed
        Then:  HOLDING, and NO fault

        The discriminator the story asks for: a merely OLD contact is not the
        alarm. Without more contacts there is no evidence the drain stalled --
        only that we have not heard since.
        """
        answer = assessVehicleCurrency([_contact(_NOW - timedelta(days=30), 400)])

        assert answer.state is CurrencyState.HOLDING
        assert answer.fault is None

    def test_twoFlatContacts_areNotYetAFault(self) -> None:
        """
        Given: only two contacts at the same residual
        When:  currency is assessed
        Then:  no fault yet

        One non-decrease is not evidence of a stall: rows can be created
        between contacts at the same rate they drain, which looks identical.
        The fault needs a run, and the story's own example is three.
        """
        contacts = [
            _contact(_NOW - timedelta(hours=1), 400),
            _contact(_NOW, 400),
        ]

        assert assessVehicleCurrency(contacts).fault is None

    def test_zeroResidualRepeated_isNotAFault(self) -> None:
        """
        Given: three contacts all reporting nothing outstanding
        When:  currency is assessed
        Then:  CURRENT, no fault

        A residual pinned at 0 'fails to decrease' arithmetically and is the
        healthiest possible state. Reading the rule literally without this case
        would alarm on a perfectly working car every hour.
        """
        contacts = [
            _contact(_NOW - timedelta(hours=2), 0),
            _contact(_NOW - timedelta(hours=1), 0),
            _contact(_NOW, 0),
        ]

        answer = assessVehicleCurrency(contacts)

        assert answer.state is CurrencyState.CURRENT
        assert answer.fault is None
