################################################################################
# File Name: __init__.py
# Purpose/Description: F-103 Pi splash backend package -- the boot/shutdown
#   splash "required-first runtime": a boot-state emitter, a localhost state
#   HTTP server (the only IPC chromium can fetch), and the auth-token SSOT.
#   The splash is a pure CONSUMER of state (specs/ssot-design-pattern.md): it
#   renders what the emitters write and never decides system condition.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# ================================================================================
################################################################################

"""F-103 Pi splash backend (boot-state emitter + localhost state server)."""
