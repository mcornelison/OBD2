################################################################################
# File Name: i2c_client.py
# Purpose/Description: I2C communication client for Raspberry Pi hardware
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-005
# ================================================================================
################################################################################

"""
I2C communication client for Raspberry Pi hardware.

This module provides a high-level interface for I2C communication with devices
like the X1209 UPS HAT. It includes retry logic with exponential backoff for
transient errors.

Usage:
    from hardware.i2c_client import I2cClient, I2cNotAvailableError

    try:
        client = I2cClient(bus=1)
        voltage = client.readWord(0x36, 0x02)
        print(f"Battery voltage: {voltage}mV")
    except I2cNotAvailableError:
        print("I2C not available on this system")

Note:
    This module requires the smbus2 library and I2C hardware support.
    On non-Pi systems, creating an I2cClient will raise I2cNotAvailableError.
"""

import logging
import time

from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)


# ================================================================================
# I2C Exceptions
# ================================================================================

class I2cError(Exception):
    """Base exception for I2C errors."""

    def __init__(self, message: str, address: int | None = None,
                 register: int | None = None):
        """
        Initialize I2C error.

        Args:
            message: Error message
            address: I2C device address (optional)
            register: Register being accessed (optional)
        """
        super().__init__(message)
        self.message = message
        self.address = address
        self.register = register

    def __str__(self) -> str:
        parts = [self.message]
        if self.address is not None:
            parts.append(f"address=0x{self.address:02x}")
        if self.register is not None:
            parts.append(f"register=0x{self.register:02x}")
        return ' | '.join(parts)


class I2cNotAvailableError(I2cError):
    """Exception raised when I2C is not available on the system."""

    def __init__(self, message: str = "I2C not available on this system"):
        """
        Initialize I2C not available error.

        Args:
            message: Error message
        """
        super().__init__(message)


class I2cCommunicationError(I2cError):
    """Exception raised when I2C communication fails (retryable)."""
    pass


class I2cDeviceNotFoundError(I2cError):
    """Exception raised when I2C device is not found at address."""
    pass


# ================================================================================
# I2C Client Constants
# ================================================================================

DEFAULT_BUS = 1
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY = 1.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0


# ================================================================================
# I2C Client Class
# ================================================================================

class I2cClient:
    """
    High-level I2C communication client with retry logic.

    This client provides methods for reading and writing bytes/words to I2C
    devices with automatic retry on transient errors.

    Attributes:
        bus: I2C bus number (default: 1)
        maxRetries: Maximum number of retry attempts (default: 3)
        initialDelay: Initial delay in seconds before retry (default: 1.0)
        backoffMultiplier: Multiplier for exponential backoff (default: 2.0)

    Example:
        client = I2cClient(bus=1, maxRetries=3)
        voltage = client.readWord(0x36, 0x02)
    """

    def __init__(
        self,
        bus: int = DEFAULT_BUS,
        maxRetries: int = DEFAULT_MAX_RETRIES,
        initialDelay: float = DEFAULT_INITIAL_DELAY,
        backoffMultiplier: float = DEFAULT_BACKOFF_MULTIPLIER
    ):
        """
        Initialize I2C client.

        Args:
            bus: I2C bus number (default: 1 for Raspberry Pi)
            maxRetries: Maximum number of retry attempts on error
            initialDelay: Initial delay in seconds before first retry
            backoffMultiplier: Multiplier for exponential backoff

        Raises:
            I2cNotAvailableError: If I2C is not available on this system
        """
        self._bus = bus
        self._maxRetries = maxRetries
        self._initialDelay = initialDelay
        self._backoffMultiplier = backoffMultiplier
        self._smbus: object | None = None

        # Initialize the SMBus connection
        self._initializeBus()

    def _initializeBus(self) -> None:
        """
        Initialize the SMBus connection.

        Raises:
            I2cNotAvailableError: If I2C is not available
        """
        # Check if we're on a Raspberry Pi first
        if not isRaspberryPi():
            raise I2cNotAvailableError(
                f"I2C bus {self._bus} not available - not running on Raspberry Pi"
            )

        # Try to import smbus2
        try:
            import smbus2
        except ImportError as e:
            raise I2cNotAvailableError(
                f"smbus2 library not available: {e}"
            ) from e

        # Try to open the I2C bus
        try:
            self._smbus = smbus2.SMBus(self._bus)
            logger.info(f"I2C client initialized on bus {self._bus}")
        except (OSError, FileNotFoundError) as e:
            raise I2cNotAvailableError(
                f"Failed to open I2C bus {self._bus}: {e}"
            ) from e

    def _executeWithRetry(self, operation: str, address: int, register: int,
                          func: callable, *args) -> int:
        """
        Execute an I2C operation with retry logic.

        Args:
            operation: Description of the operation (for logging)
            address: I2C device address
            register: Register being accessed
            func: Function to call for the I2C operation
            *args: Arguments to pass to the function

        Returns:
            Result of the I2C operation

        Raises:
            I2cCommunicationError: If all retries are exhausted
            I2cDeviceNotFoundError: If device is not found at address
        """
        lastError: Exception | None = None
        delay = self._initialDelay

        for attempt in range(self._maxRetries + 1):
            try:
                result = func(*args)
                if attempt > 0:
                    logger.info(
                        f"I2C {operation} succeeded on attempt {attempt + 1}"
                    )
                return result

            except OSError as e:
                lastError = e
                errorCode = getattr(e, 'errno', None)

                # Check for device not found (ENODEV = 19, ENXIO = 6)
                if errorCode in (6, 19, 121):
                    raise I2cDeviceNotFoundError(
                        f"No I2C device found at address 0x{address:02x}",
                        address=address,
                        register=register
                    ) from e

                # Retryable error - attempt retry
                if attempt < self._maxRetries:
                    logger.warning(
                        f"I2C {operation} failed (attempt {attempt + 1}/{self._maxRetries + 1}), "
                        f"retrying in {delay}s | error={e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoffMultiplier
                else:
                    logger.error(
                        f"I2C {operation} failed after {self._maxRetries + 1} attempts"
                    )

            except Exception as e:
                # Unexpected error - don't retry
                logger.error(f"Unexpected error during I2C {operation}: {e}")
                raise I2cCommunicationError(
                    f"I2C {operation} failed: {e}",
                    address=address,
                    register=register
                ) from e

        # All retries exhausted
        raise I2cCommunicationError(
            f"I2C {operation} failed after {self._maxRetries + 1} attempts: {lastError}",
            address=address,
            register=register
        )

    def readByte(self, address: int, register: int) -> int:
        """
        Read a single byte from an I2C device register.

        Args:
            address: I2C device address (0x00-0x7F)
            register: Register address to read from

        Returns:
            Byte value read (0-255)

        Raises:
            I2cCommunicationError: If read fails after retries
            I2cDeviceNotFoundError: If device is not found at address
            I2cNotAvailableError: If I2C is not available

        Example:
            percentage = client.readByte(0x36, 0x06)  # Read battery percentage
        """
        if self._smbus is None:
            raise I2cNotAvailableError("I2C bus not initialized")

        def _readOperation():
            return self._smbus.read_byte_data(address, register)

        result = self._executeWithRetry(
            f"readByte(0x{address:02x}, 0x{register:02x})",
            address,
            register,
            _readOperation
        )

        logger.debug(f"I2C read byte: addr=0x{address:02x} reg=0x{register:02x} value=0x{result:02x}")
        return result

    def writeByte(self, address: int, register: int, value: int) -> None:
        """
        Write a single byte to an I2C device register.

        Args:
            address: I2C device address (0x00-0x7F)
            register: Register address to write to
            value: Byte value to write (0-255)

        Raises:
            I2cCommunicationError: If write fails after retries
            I2cDeviceNotFoundError: If device is not found at address
            I2cNotAvailableError: If I2C is not available
            ValueError: If value is out of range

        Example:
            client.writeByte(0x36, 0x10, 0x01)  # Write config register
        """
        if self._smbus is None:
            raise I2cNotAvailableError("I2C bus not initialized")

        if not 0 <= value <= 255:
            raise ValueError(f"Byte value must be 0-255, got {value}")

        def _writeOperation():
            self._smbus.write_byte_data(address, register, value)
            return None

        self._executeWithRetry(
            f"writeByte(0x{address:02x}, 0x{register:02x}, 0x{value:02x})",
            address,
            register,
            _writeOperation
        )

        logger.debug(f"I2C write byte: addr=0x{address:02x} reg=0x{register:02x} value=0x{value:02x}")

    def readWord(self, address: int, register: int) -> int:
        """
        Read a 16-bit word from an I2C device register.

        Reads two consecutive bytes and combines them as a 16-bit value.
        Uses little-endian byte order as is standard for SMBus.

        Args:
            address: I2C device address (0x00-0x7F)
            register: Register address to read from

        Returns:
            16-bit word value (0-65535)

        Raises:
            I2cCommunicationError: If read fails after retries
            I2cDeviceNotFoundError: If device is not found at address
            I2cNotAvailableError: If I2C is not available

        Example:
            voltage_mv = client.readWord(0x36, 0x02)  # Read battery voltage in mV
        """
        if self._smbus is None:
            raise I2cNotAvailableError("I2C bus not initialized")

        def _readOperation():
            return self._smbus.read_word_data(address, register)

        result = self._executeWithRetry(
            f"readWord(0x{address:02x}, 0x{register:02x})",
            address,
            register,
            _readOperation
        )

        logger.debug(f"I2C read word: addr=0x{address:02x} reg=0x{register:02x} value={result}")
        return result

    def writeWord(self, address: int, register: int, value: int) -> None:
        """
        Write a 16-bit word to an I2C device register.

        Writes two consecutive bytes as a 16-bit value.
        Uses little-endian byte order as is standard for SMBus.

        Args:
            address: I2C device address (0x00-0x7F)
            register: Register address to write to
            value: 16-bit word value to write (0-65535)

        Raises:
            I2cCommunicationError: If write fails after retries
            I2cDeviceNotFoundError: If device is not found at address
            I2cNotAvailableError: If I2C is not available
            ValueError: If value is out of range

        Example:
            client.writeWord(0x36, 0x10, 0x1234)  # Write config word
        """
        if self._smbus is None:
            raise I2cNotAvailableError("I2C bus not initialized")

        if not 0 <= value <= 65535:
            raise ValueError(f"Word value must be 0-65535, got {value}")

        def _writeOperation():
            self._smbus.write_word_data(address, register, value)
            return None

        self._executeWithRetry(
            f"writeWord(0x{address:02x}, 0x{register:02x}, 0x{value:04x})",
            address,
            register,
            _writeOperation
        )

        logger.debug(f"I2C write word: addr=0x{address:02x} reg=0x{register:02x} value={value}")

    def close(self) -> None:
        """
        Close the I2C bus connection.

        Safe to call multiple times or on an uninitialized client.
        """
        if self._smbus is not None:
            try:
                self._smbus.close()
                logger.debug(f"I2C bus {self._bus} closed")
            except Exception as e:
                logger.warning(f"Error closing I2C bus: {e}")
            finally:
                self._smbus = None

    def __enter__(self) -> 'I2cClient':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close the bus."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure bus is closed."""
        self.close()

    @property
    def bus(self) -> int:
        """Get the I2C bus number."""
        return self._bus

    @property
    def isConnected(self) -> bool:
        """Check if the I2C bus is connected."""
        return self._smbus is not None
