################################################################################
# File Name: cli_input.py
# Purpose/Description: Non-blocking character input for the simulator CLI
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-043
# 2026-04-14    | Sweep 5       | Extracted from simulator_cli.py (task 4 split)
# ================================================================================
################################################################################

"""
Non-blocking single-character input for the simulator CLI.

Uses msvcrt on Windows and select() on Unix. Returns None when no input
is pending. Platform detection happens on each call — neither dependency
is loaded at import time.
"""

from typing import Any


def readChar(inputStream: Any) -> str | None:
    """
    Read a single character from an input stream without blocking.

    Args:
        inputStream: Input stream (e.g., sys.stdin)

    Returns:
        Lowercased character if available, None otherwise
    """
    # Try to use msvcrt on Windows for non-blocking input
    try:
        import msvcrt
        if msvcrt.kbhit():
            char = msvcrt.getch().decode('utf-8', errors='ignore')
            return char.lower()
    except (ImportError, AttributeError):
        pass

    # Try to use select on Unix
    try:
        import select
        if select.select([inputStream], [], [], 0.1)[0]:
            char = inputStream.read(1)
            if char:
                return char.lower()
    except (ImportError, OSError, TypeError):
        pass

    return None
