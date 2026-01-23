################################################################################
# File Name: headless.py
# Purpose/Description: Headless display driver - no display output, logs only
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation (US-005) - extracted from display_manager.py
# ================================================================================
################################################################################
"""
Headless display driver implementation.

Used for background service operation where no visual output is needed.
All operations are logged at appropriate levels for monitoring.
"""

import logging
from typing import Any, Dict, Optional

from display.types import StatusInfo, AlertInfo
from .base import BaseDisplayDriver


logger = logging.getLogger(__name__)


class HeadlessDisplayDriver(BaseDisplayDriver):
    """
    Headless display driver - no display output, logs only.

    Used for background service operation where no visual output is needed.
    All operations are logged at appropriate levels for monitoring.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize headless display driver.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(config)
        self._logLevel = logging.INFO

    def initialize(self) -> bool:
        """
        Initialize headless display driver.

        Always succeeds as no hardware is required.

        Returns:
            True (always successful)
        """
        logger.info("Headless display driver initialized - no visual output")
        self._initialized = True
        return True

    def shutdown(self) -> None:
        """Shutdown headless display driver."""
        logger.debug("Headless display driver shutdown")
        self._initialized = False

    def showStatus(self, status: StatusInfo) -> None:
        """
        Log status information.

        Args:
            status: StatusInfo object with current status
        """
        self._lastStatus = status
        logger.debug(
            f"Status: connection={status.connectionStatus}, "
            f"db={status.databaseStatus}, rpm={status.currentRpm}, "
            f"temp={status.coolantTemp}, profile={status.profileName}"
        )

    def showAlert(self, alert: AlertInfo) -> None:
        """
        Log alert information.

        Args:
            alert: AlertInfo object with alert details
        """
        if not alert.acknowledged:
            self._activeAlerts.append(alert)

        # Log at appropriate level based on priority
        if alert.priority <= 2:
            logger.warning(f"ALERT [P{alert.priority}]: {alert.message}")
        else:
            logger.info(f"Alert [P{alert.priority}]: {alert.message}")

    def clearDisplay(self) -> None:
        """Clear active alerts (no visual display to clear)."""
        self._activeAlerts.clear()
        logger.debug("Display cleared")
