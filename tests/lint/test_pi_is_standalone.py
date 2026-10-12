################################################################################
# File Name: test_pi_is_standalone.py
# Purpose/Description: Standing-rule lint -- the Pi is a STANDALONE IoT device
#     (CIO 2026-08-26). It reaches exactly one peer, the OBD2 server, and only
#     during a data sync at shutdown. It mounts no network storage and receives
#     its code by deploy-script push, never by pulling from anywhere.
#     This lint guards the DEFAULTS, which is where the rule was actually broken:
#     pi.bootProgress.nasArchiveDir defaulted to a NAS path with the archive
#     ENABLED, and config.json carries no bootProgress section, so that default
#     was live on the car. Every existing boot-progress test passed the two
#     values explicitly, so not one of them exercised the default.
# Author: Claude (CIO standalone-Pi directive)
# Creation Date: 2026-08-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-26    | Claude       | Initial -- no network-storage defaults for the
#               |              | Pi tier; boot-progress archive off + Pi-local.
# ================================================================================
################################################################################

"""Lint: no Pi default may point at network storage.

A default is the dangerous case. An explicit setting is visible in config.json
and reviewable; a default is invisible until it misfires -- and this one could
not even misfire loudly, because ``archivePriorTrail`` swallows the failure into
a best-effort ``except`` that logs a warning.
"""

from __future__ import annotations

import pytest

from src.common.config.validator import DEFAULTS

# Absolute POSIX roots that only ever exist because something was mounted, plus
# UNC. A Pi-local default is RELATIVE (resolved against the systemd
# WorkingDirectory) or under a real on-box path.
NETWORK_STORAGE_PREFIXES = ("/mnt/", "/media/", "//", "\\\\", "smb:", "nfs:", "cifs:")


def _piPathDefaults() -> list[tuple[str, str]]:
    """Every pi.* default whose value looks like a filesystem path."""
    return [
        (key, value)
        for key, value in DEFAULTS.items()
        if key.startswith("pi.")
        and isinstance(value, str)
        and ("/" in value or "\\" in value)
    ]


@pytest.mark.parametrize("key,value", _piPathDefaults())
def test_piPathDefault_isNotNetworkStorage(key: str, value: str) -> None:
    """
    Given: a pi.* default that names a filesystem path
    When: its prefix is inspected
    Then: it is not network storage

    The Pi mounts nothing. A default pointing at /mnt/... cannot work on the car,
    and os.makedirs(..., exist_ok=True) will happily CREATE that path as a
    phantom local tree on the SD card rather than fail.
    """
    offending = [p for p in NETWORK_STORAGE_PREFIXES if value.startswith(p)]

    assert not offending, (
        f"Pi default {key!r} points at network storage: {value!r}. "
        f"The Pi is standalone -- it reaches only the OBD2 server, at sync. "
        f"Use a Pi-local (relative) path."
    )


def test_bootProgressArchive_isOffByDefault() -> None:
    """
    Given: pi.bootProgress.nasArchiveEnabled
    When: its DEFAULT is read
    Then: it is False

    config.json has no bootProgress section, so this default is what runs on the
    car. It shipped as True pointing at a NAS path. The archive is redundant in
    any case: the canonical one-per-boot record is the startup_log DB row, which
    is what actually syncs to the server.
    """
    assert DEFAULTS["pi.bootProgress.nasArchiveEnabled"] is False, (
        "the boot-progress archive must default OFF -- it is a redundant copy of "
        "the startup_log row and previously defaulted to writing at a NAS path"
    )


def test_bootProgressArchiveDir_isRelativeToThePi() -> None:
    """
    Given: pi.bootProgress.nasArchiveDir
    When: its DEFAULT is read
    Then: it is a relative path

    Relative means it resolves under the systemd WorkingDirectory on the Pi, so
    enabling the archive cannot reach off-box even by accident. (The key keeps
    its historical 'nas' name; renaming a published config key is its own change.)
    """
    value = DEFAULTS["pi.bootProgress.nasArchiveDir"]

    assert not value.startswith(("/", "\\")) and ":" not in value, (
        f"nasArchiveDir default {value!r} must be RELATIVE so it resolves on the "
        f"Pi itself; an absolute path can leave the box"
    )
