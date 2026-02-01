################################################################################
# File Name: exceptions.py
# Purpose/Description: OBD-II configuration exception classes
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation (US-002)
# ================================================================================
################################################################################

"""
OBD-II Configuration exception classes.

Provides custom exceptions for configuration loading and validation errors.
These exceptions include typed field lists for clear debugging information.

Usage:
    from src.obd.config.exceptions import ObdConfigError

    try:
        config = loadObdConfig('path/to/config.json')
    except ObdConfigError as e:
        print(f"Config error: {e}")
        print(f"Missing fields: {e.missingFields}")
        print(f"Invalid fields: {e.invalidFields}")
"""



class ObdConfigError(Exception):
    """
    Raised when OBD configuration loading or validation fails.

    Provides typed lists of missing and invalid fields to help diagnose
    configuration problems.

    Attributes:
        missingFields: List of required field paths that are missing
        invalidFields: List of field paths with invalid values
    """

    def __init__(
        self,
        message: str,
        missingFields: list[str] | None = None,
        invalidFields: list[str] | None = None
    ):
        """
        Initialize the configuration error.

        Args:
            message: Human-readable error description
            missingFields: List of required field paths that are missing
            invalidFields: List of field paths with invalid values
        """
        super().__init__(message)
        self.missingFields = missingFields or []
        self.invalidFields = invalidFields or []
