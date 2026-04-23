################################################################################
# File Name: test_journald_persistent.py
# Purpose/Description: US-210 static-content assertions on
#                      deploy/journald-persistent.conf. Drop-in installs to
#                      /etc/systemd/journald.conf.d/99-obd-persistent.conf on
#                      the Pi via deploy-pi.sh step_install_journald_persistent.
#                      Test locks the [Journal] section + Storage=persistent
#                      invariant so a future operator tweak can't silently
#                      flip persistence off.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex          | Initial implementation (Sprint 16 US-210)
# ================================================================================
################################################################################

"""Static assertions for the systemd-journald persistent-storage drop-in."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DROP_IN = REPO_ROOT / "deploy" / "journald-persistent.conf"


def _text() -> str:
    assert DROP_IN.is_file(), f"Missing journald drop-in: {DROP_IN}"
    return DROP_IN.read_text(encoding="utf-8")


def test_journaldPersistent_exists():
    assert DROP_IN.is_file()


def test_journaldPersistent_hasJournalSection():
    """The drop-in must declare [Journal]; settings under any other section are ignored."""
    assert re.search(r"^\[Journal\]\s*$", _text(), re.MULTILINE), (
        "Missing [Journal] section header"
    )


def test_journaldPersistent_setsStoragePersistent():
    """US-210 grounding ref: Storage=persistent on /etc/systemd/journald.conf."""
    assert re.search(r"^Storage=persistent\s*$", _text(), re.MULTILINE), (
        "Storage=persistent not set; journald default is 'auto' which is NOT a persistent journal"
    )


def test_journaldPersistent_noForbiddenStorageModes():
    """Guard: the drop-in MUST NOT accidentally declare volatile/none/auto.

    A stray `Storage=volatile` left in after a debug session would silently
    make every subsequent drop-in reinstall re-volatize the journal.
    """
    text = _text()
    for forbidden in ("Storage=volatile", "Storage=none", "Storage=auto"):
        assert re.search(rf"^{re.escape(forbidden)}\s*$", text, re.MULTILINE) is None, (
            f"{forbidden} must not appear in the persistent drop-in"
        )
