################################################################################
# File Name: __init__.py
# Purpose/Description: Canonical timestamp helper package.  See helper.py.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-202 (TD-027 fix)
# ================================================================================
################################################################################

"""Canonical ISO-8601 UTC timestamp helpers.

Every capture-table writer on the Pi tier must route through
:func:`src.common.time.helper.utcIsoNow` (or :func:`toCanonicalIso` when a
caller-supplied :class:`datetime.datetime` must be preserved).  See
``specs/standards.md`` 'Canonical Timestamp Format' for the rule.
"""

from .helper import CANONICAL_ISO_FORMAT, CANONICAL_ISO_REGEX, toCanonicalIso, utcIsoNow

__all__ = [
    'CANONICAL_ISO_FORMAT',
    'CANONICAL_ISO_REGEX',
    'utcIsoNow',
    'toCanonicalIso',
]
