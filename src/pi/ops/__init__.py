################################################################################
# File Name: __init__.py
# Purpose/Description: US-492 [F-122] `pi.ops` -- on-Pi OPERATOR tooling. Code
#   here is for a human doing maintenance at a terminal, not for the running
#   application: it is stdlib-only and imports nothing from the rest of the app
#   so it still works when the venv, the config or the orchestrator is broken --
#   which is exactly when the operator reaches for it.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial implementation (US-492 obdctl).
# ================================================================================
################################################################################

"""On-Pi operator tooling (US-492): stdlib-only, app-independent by design."""
