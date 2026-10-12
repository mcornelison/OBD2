################################################################################
# File Name: __init__.py
# Purpose/Description: EDR (Event Data Recorder) shared, tier-neutral contracts.
#                      Currently holds the single-source raw-sensor schema
#                      (sensor_schema) authored once so the Pi and the future
#                      server never diverge (A-4 anti-divergence gate).
# Author: Rex (US-408)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Rex (US-408) | Initial -- create the src/common/edr package.
# ================================================================================
################################################################################
"""Shared EDR contracts (tier-neutral, imported by both Pi and future server)."""
