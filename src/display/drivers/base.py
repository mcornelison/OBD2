################################################################################
# File Name: base.py
# Purpose/Description: Abstract base class for display drivers
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
Abstract base class for display drivers.

All display drivers must inherit from BaseDisplayDriver and implement
the abstract methods for display operations.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from display.types import StatusInfo, AlertInfo


class BaseDisplayDriver(ABC):
    """
    Abstract base class for display drivers.

    All display drivers must implement:
    - initialize(): Initialize the display driver
    - shutdown(): Shutdown and release resources
    - showStatus(): Display status information
    - showAlert(): Display an alert
    - clearDisplay(): Clear the display
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize display driver.

        Args:
            config: Optional configuration dictionary
        """
        self._config = config or {}
        self._initialized = False
        self._lastStatus: Optional[StatusInfo] = None
        self._activeAlerts: List[AlertInfo] = []

    @property
    def isInitialized(self) -> bool:
        """Check if display is initialized."""
        return self._initialized

    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize the display driver.

        Returns:
            True if initialization successful, False otherwise
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown the display driver and release resources."""
        pass

    @abstractmethod
    def showStatus(self, status: StatusInfo) -> None:
        """
        Display status information.

        Args:
            status: StatusInfo object with current status
        """
        pass

    @abstractmethod
    def showAlert(self, alert: AlertInfo) -> None:
        """
        Display an alert.

        Args:
            alert: AlertInfo object with alert details
        """
        pass

    @abstractmethod
    def clearDisplay(self) -> None:
        """Clear the display output."""
        pass

    def getLastStatus(self) -> Optional[StatusInfo]:
        """Get the last displayed status."""
        return self._lastStatus

    def getActiveAlerts(self) -> List[AlertInfo]:
        """Get list of active alerts."""
        return self._activeAlerts.copy()
