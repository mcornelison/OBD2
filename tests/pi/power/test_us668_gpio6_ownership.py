################################################################################
# File Name: test_us668_gpio6_ownership.py
# Purpose/Description: US-668 -- powerwatch owns BCM GPIO6 exclusively and
#                      publishes the power source; the collector subscribes and
#                      never opens the line. Plus the PldSensor contention-vs-
#                      absence fix, and the removal of the operator-declared
#                      power.mode.
# Author: Atlas (Architect)
# Creation Date: 2026-09-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-02    | Atlas        | US-668 initial -- written BEFORE the fix.
# ================================================================================
################################################################################

"""US-668: one owner for GPIO6, one publisher, one subscriber.

Why this exists
---------------

``eclipse-powerwatch.service`` and ``eclipse-obd.service`` both constructed
``PldSensor`` on BCM GPIO6.  A GPIO line is claimed exclusively per-process, so
the loser got ``EBUSY``, ``_dev`` went None, ``isAvailable`` went False
**forever**, and three separately-filed punch-list items followed from it:
``power.source`` reading unknown, the battery-health verdict reading stale, and
``battery_health_log`` frozen since 2026-05-16.

⚠️ **Verified, and it is why the ownership must be declared rather than
discovered:** neither unit orders against the other -- ``eclipse-powerwatch``
has ``After=local-fs.target``, ``eclipse-obd`` has
``After=network.target bluetooth.target``, and neither references the other.
**The winner of the race is not stable between boots.**

The safety property under all of this
-------------------------------------

The subscriber must **never** infer "external power is present" from an absent
or stale publication.  A missing file means *we do not know*, and reporting
"we do know, and it is fine" would suppress the very shutdown this line exists
to trigger.  Silence is not good news.
"""

from __future__ import annotations

import errno
import json
import os
import time
from pathlib import Path

import pytest

# ---- PldSensor: contention is not absence ------------------------------------


def _busyFactory(pin):
    raise OSError(errno.EBUSY, "Device or resource busy")


def _absentFactory(pin):
    raise OSError(errno.ENODEV, "No such device")


def test_pld_reports_CONTENDED_when_the_line_is_already_claimed() -> None:
    """EBUSY means someone else has it -- not that the hardware is missing.

    Before US-668 both cases set ``_dev = None`` and reported the same thing, so
    a boot-race loser was indistinguishable from a Pi with no PLD wired. That is
    why this read as absent hardware from 2026-05-16 onward.
    """
    from pi.hardware.pld_sensor import PLD_UNAVAILABLE_CONTENDED, PldSensor

    sensor = PldSensor(pin=6, deviceFactory=_busyFactory)

    assert sensor.isAvailable is False
    assert sensor.unavailableReason == PLD_UNAVAILABLE_CONTENDED


def test_pld_reports_ABSENT_when_there_is_no_such_device() -> None:
    from pi.hardware.pld_sensor import PLD_UNAVAILABLE_ABSENT, PldSensor

    sensor = PldSensor(pin=6, deviceFactory=_absentFactory)

    assert sensor.isAvailable is False
    assert sensor.unavailableReason == PLD_UNAVAILABLE_ABSENT


def test_pld_reason_is_None_when_the_line_opened() -> None:
    """A working sensor carries no unavailability reason."""
    from pi.hardware.pld_sensor import PldSensor

    class _Dev:
        value = 1

        def close(self):
            pass

    sensor = PldSensor(pin=6, deviceFactory=lambda pin: _Dev())

    assert sensor.isAvailable is True
    assert sensor.unavailableReason is None


# ---- The publish / subscribe seam --------------------------------------------


def test_published_state_round_trips_through_the_subscriber(tmp_path) -> None:
    """What powerwatch publishes is what the collector reads. One fact, one hop."""
    from pi.power.power_source_pubsub import (
        SubscribedPld,
        publishPowerSource,
    )

    path = str(tmp_path / "power-source.json")
    publishPowerSource(path, externalPowerPresent=True, available=True)

    sub = SubscribedPld(path=path, maxAgeSec=30.0)

    assert sub.isAvailable is True
    assert sub.isExternalPowerPresent() is True
    assert sub.isPowerLost() is False


def test_subscriber_reports_power_LOST_when_the_publisher_says_so(tmp_path) -> None:
    from pi.power.power_source_pubsub import SubscribedPld, publishPowerSource

    path = str(tmp_path / "power-source.json")
    publishPowerSource(path, externalPowerPresent=False, available=True)

    sub = SubscribedPld(path=path, maxAgeSec=30.0)

    assert sub.isAvailable is True
    assert sub.isPowerLost() is True


def test_a_MISSING_publication_is_unavailable_NOT_power_present(tmp_path) -> None:
    """🔴 The safety property. Silence is not good news.

    If an absent file read as "external power present", a publisher that died
    would look exactly like a healthy car -- and the graceful shutdown this line
    exists to trigger would never fire. Absence must degrade to "we do not
    know", never to "it is fine".
    """
    from pi.power.power_source_pubsub import SubscribedPld

    sub = SubscribedPld(path=str(tmp_path / "does-not-exist.json"), maxAgeSec=30.0)

    assert sub.isAvailable is False
    assert sub.isExternalPowerPresent() is False


def test_a_STALE_publication_is_unavailable_NOT_power_present(tmp_path) -> None:
    """Same property against a publisher that stopped updating.

    A stale file is worse than a missing one: it is present, parseable and
    confidently wrong. It must expire.
    """
    from pi.power.power_source_pubsub import SubscribedPld, publishPowerSource

    path = str(tmp_path / "power-source.json")
    publishPowerSource(path, externalPowerPresent=True, available=True)

    # Age the publication well past the window.
    old = time.time() - 600
    os.utime(path, (old, old))
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["publishedAtEpoch"] = old
    Path(path).write_text(json.dumps(payload), encoding="utf-8")

    sub = SubscribedPld(path=path, maxAgeSec=30.0)

    assert sub.isAvailable is False
    assert sub.isExternalPowerPresent() is False


def test_a_CORRUPT_publication_is_unavailable_not_a_crash(tmp_path) -> None:
    """A half-written or garbage file must not take the collector down."""
    from pi.power.power_source_pubsub import SubscribedPld

    path = tmp_path / "power-source.json"
    path.write_text("{not json", encoding="utf-8")

    sub = SubscribedPld(path=str(path), maxAgeSec=30.0)

    assert sub.isAvailable is False


def test_publish_is_atomic_leaving_no_partial_file(tmp_path) -> None:
    """temp + os.replace, the convention every other emitter already uses.

    A reader polling this path must never observe a half-written document.
    """
    from pi.power.power_source_pubsub import publishPowerSource

    path = str(tmp_path / "power-source.json")
    for _ in range(5):
        publishPowerSource(path, externalPowerPresent=True, available=True)

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert json.loads(Path(path).read_text(encoding="utf-8"))


def test_publication_carries_the_unavailability_REASON(tmp_path) -> None:
    """When powerwatch itself cannot read the line, it says why.

    Publishing a bare "unavailable" would hand the collector the same
    undiscriminated blob US-668 exists to eliminate.
    """
    from pi.power.power_source_pubsub import publishPowerSource, readPowerSource

    path = str(tmp_path / "power-source.json")
    publishPowerSource(
        path, externalPowerPresent=False, available=False, reason="contended",
    )

    doc = readPowerSource(path, maxAgeSec=30.0)

    assert doc is not None
    assert doc["available"] is False
    assert doc["reason"] == "contended"


# ---- The collector must not open the line ------------------------------------


def test_lifecycle_no_longer_constructs_a_PldSensor() -> None:
    """The whole defect in one assertion.

    GPIO6 was the ONLY source in the system with two independent acquisitions.
    If this line comes back, the race comes back with it -- and it will be
    invisible again, because the loser fails silently.
    """
    source = Path("src/pi/obdii/orchestrator/lifecycle.py").read_text(
        encoding="utf-8",
    )

    assert "PldSensor(" not in source


def test_powerwatch_still_constructs_the_PldSensor() -> None:
    """The owner keeps it. A ruling that removed BOTH would fix nothing."""
    source = Path("src/pi/power/power_watch/__main__.py").read_text(
        encoding="utf-8",
    )

    assert "PldSensor(" in source


# ---- power.mode is removed ---------------------------------------------------
#
# CIO, 2026-09-02: "if I can see the screen then the power is on, it doesn't
# matter if it is car or wall, it is on."
#
# Verified before agreeing: PowerModeProvider was read by exactly ONE consumer,
# card_state_emitter, to render the card that displayed it. No shutdown policy
# and no lifecycle logic branched on it. It was an operator-declared fact that
# existed so the screen could show it back to the operator.
#
# ⚠️ power.SOURCE is NOT removed and must not be: it is sensed, and it answers
# "am I on external power or on the UPS battery?" -- which the screen being lit
# cannot tell you. During the 2026-08-31 UPS test the panel stayed lit the whole
# time the Pi ran on battery toward a graceful poweroff.


def test_power_mode_provider_module_is_gone() -> None:
    assert not Path("src/pi/power/power_mode_provider.py").exists()


def test_power_mode_provider_cannot_be_imported() -> None:
    """The module is gone, so importing it must fail.

    ⚠️ This replaced a text scan for the string "PowerModeProvider" across four
    files. That scan was testing SPELLING, not behaviour: it tripped on the
    comments that explain WHY the provider was removed -- which are exactly the
    comments a future reader needs. A guard that forbids documenting its own
    subject is a bad guard.
    """
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("pi.power.power_mode_provider")


def test_power_mode_is_not_a_live_config_key() -> None:
    """Assert the DATA, not the text.

    Two structures decide whether a key exists: the validator's defaults (does
    a config carry it) and the overlay's validator table (is it operator-
    writable -- the same table gates both the read and the US-531 write path).
    A key absent from both cannot be set, stored, or read.
    """
    from common.config import overlay as overlayMod
    from common.config import validator as validatorMod

    defaults = getattr(validatorMod, "CONFIG_DEFAULTS", None) or getattr(
        validatorMod, "DEFAULTS", {},
    )
    assert "pi.power.mode" not in defaults
    assert "pi.power.mode" not in overlayMod._VALIDATORS


def test_power_SOURCE_survives_the_mode_removal() -> None:
    """The half that is sensed stays. Deleting it would remove the only power
    fact the display cannot tell you by existing."""
    text = Path("src/pi/obdii/orchestrator/card_state_emitter.py").read_text(
        encoding="utf-8",
    )

    assert "powerSource" in text or "power_source" in text


@pytest.mark.parametrize("stateFile", ["config.json"])
def test_config_no_longer_ships_a_power_mode(stateFile) -> None:
    doc = json.loads(Path(stateFile).read_text(encoding="utf-8"))
    power = doc.get("pi", {}).get("power", {})

    assert "mode" not in power
