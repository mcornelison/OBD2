################################################################################
# File Name: conftest.py (tests/server/)
# Purpose/Description: Skip server-side tests when SQLAlchemy is not installed
# Author: Rex (Ralph)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex (Ralph)  | US-182: stop Pi pytest collection from erroring
#               |              | when sqlalchemy (server-only dep) is missing
# ================================================================================
################################################################################

"""
Collection guard for ``tests/server/``.

These tests exercise the chi-srv-01 tier (SQLAlchemy models, /sync/, analytics,
reports) and require server-only dependencies (``sqlalchemy``, ``pydantic-settings``,
etc.). Those deps live in ``requirements-server.txt`` and are intentionally NOT
installed on the Raspberry Pi (``requirements-pi.txt``).

On a Pi run, ``pytest tests/`` would previously abort with a collection error
(``ModuleNotFoundError: No module named 'sqlalchemy'``). This conftest flips
that into a clean directory skip: if ``sqlalchemy`` can't be imported, the
entire ``tests/server/`` tree is excluded from collection.

Platforms with ``sqlalchemy`` installed (Windows dev, Chi-Srv-01) see no change.
"""

from __future__ import annotations

import importlib.util

collect_ignore_glob: list[str] = []

if importlib.util.find_spec('sqlalchemy') is None:
    # Linux: Pi — requirements-pi.txt does not pull sqlalchemy. Skip the
    # entire tests/server/ subtree to keep the Pi baseline clean.
    collect_ignore_glob = ['test_*.py']
