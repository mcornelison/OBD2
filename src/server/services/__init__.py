################################################################################
# File Name: __init__.py
# Purpose/Description: src.server.services package — service-layer orchestration
#                      between the FastAPI routers and the analytics/AI/DB
#                      modules. Introduced by US-CMP-005.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial package marker for US-CMP-005
# ================================================================================
################################################################################

"""Server service layer.

Each service bundles a multi-step workflow (DB reads, analytics calls,
external I/O, persistence) behind a simple function the API layer calls. The
pattern keeps :mod:`src.server.api` thin and testable.
"""
