################################################################################
# File Name: __init__.py
# Purpose/Description: Package marker for src/server/migrations/versions/. Each
#                      schema change ships as a numbered module under this
#                      directory and is imported into the top-level registry.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial -- Sprint 16 US-213 (TD-029 closure).
# ================================================================================
################################################################################

"""Migration version modules.

Each module defines:

* ``VERSION`` -- unique string identifier, sort-order = application order
* ``DESCRIPTION`` -- one-line human summary
* ``apply(ctx: RunnerContext) -> None`` -- idempotent DDL invocation
* ``MIGRATION`` -- module-level :class:`Migration` assembled from the above,
  appended to :data:`src.server.migrations.ALL_MIGRATIONS`
"""

from __future__ import annotations
