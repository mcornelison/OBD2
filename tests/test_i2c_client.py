################################################################################
# File Name: test_i2c_client.py
# Purpose/Description: Tests for I2C communication client
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
Tests for the i2c_client module.

Tests I2C communication functionality with mocked SMBus for cross-platform testing.

Run with:
    pytest tests/test_i2c_client.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from hardware.i2c_client import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_BUS,
    DEFAULT_INITIAL_DELAY,
    DEFAULT_MAX_RETRIES,
    I2cClient,
    I2cCommunicationError,
    I2cDeviceNotFoundError,
    I2cError,
    I2cNotAvailableError,
)

# ================================================================================
# Exception Tests
# ================================================================================

class TestI2cExceptions:
    """Tests for I2C exception classes."""

    def test_i2cError_basicMessage_returnsMessage(self):
        """
        Given: I2cError with just a message
        When: Converted to string
        Then: Returns the message
        """
        # Arrange
        error = I2cError("Test error")

        # Act
        result = str(error)

        # Assert
        assert result == "Test error"

    def test_i2cError_withAddress_includesAddress(self):
        """
        Given: I2cError with address
        When: Converted to string
        Then: Includes address in hex format
        """
        # Arrange
        error = I2cError("Test error", address=0x36)

        # Act
        result = str(error)

        # Assert
        assert "Test error" in result
        assert "address=0x36" in result

    def test_i2cError_withAddressAndRegister_includesBoth(self):
        """
        Given: I2cError with address and register
        When: Converted to string
        Then: Includes both in hex format
        """
        # Arrange
        error = I2cError("Test error", address=0x36, register=0x02)

        # Act
        result = str(error)

        # Assert
        assert "Test error" in result
        assert "address=0x36" in result
        assert "register=0x02" in result

    def test_i2cNotAvailableError_defaultMessage_hasDefaultMessage(self):
        """
        Given: I2cNotAvailableError without custom message
        When: Created
        Then: Has default message
        """
        # Arrange & Act
        error = I2cNotAvailableError()

        # Assert
        assert "not available" in str(error).lower()

    def test_i2cNotAvailableError_customMessage_hasCustomMessage(self):
        """
        Given: I2cNotAvailableError with custom message
        When: Created
        Then: Has custom message
        """
        # Arrange & Act
        error = I2cNotAvailableError("Custom error message")

        # Assert
        assert "Custom error message" in str(error)

    def test_i2cCommunicationError_isSubclassOfI2cError(self):
        """
        Given: I2cCommunicationError
        When: Checked for inheritance
        Then: Is subclass of I2cError
        """
        # Assert
        assert issubclass(I2cCommunicationError, I2cError)

    def test_i2cDeviceNotFoundError_isSubclassOfI2cError(self):
        """
        Given: I2cDeviceNotFoundError
        When: Checked for inheritance
        Then: Is subclass of I2cError
        """
        # Assert
        assert issubclass(I2cDeviceNotFoundError, I2cError)


# ================================================================================
# I2C Client Initialization Tests
# ================================================================================

class TestI2cClientInitialization:
    """Tests for I2cClient initialization."""

    def test_init_notRaspberryPi_raisesNotAvailable(self):
        """
        Given: Not running on Raspberry Pi
        When: I2cClient is created
        Then: Raises I2cNotAvailableError
        """
        # Arrange
        with patch('hardware.i2c_client.isRaspberryPi', return_value=False):
            # Act & Assert
            with pytest.raises(I2cNotAvailableError) as excInfo:
                I2cClient()

            assert "not running on Raspberry Pi" in str(excInfo.value)

    def test_init_smbus2NotInstalled_raisesNotAvailable(self):
        """
        Given: Running on Pi but smbus2 not installed
        When: I2cClient is created
        Then: Raises I2cNotAvailableError
        """
        # Arrange
        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': None}):
                # Simulate ImportError when importing smbus2
                def mockImport(name, *args, **kwargs):
                    if name == 'smbus2':
                        raise ImportError("No module named 'smbus2'")
                    return MagicMock()

                with patch('builtins.__import__', side_effect=mockImport):
                    # Act & Assert
                    with pytest.raises(I2cNotAvailableError) as excInfo:
                        I2cClient()

                    assert "smbus2" in str(excInfo.value).lower()

    def test_init_busFailed_raisesNotAvailable(self):
        """
        Given: Running on Pi but I2C bus cannot be opened
        When: I2cClient is created
        Then: Raises I2cNotAvailableError
        """
        # Arrange
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.side_effect = OSError("Device not found")

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                # Act & Assert
                with pytest.raises(I2cNotAvailableError) as excInfo:
                    I2cClient()

                assert "Failed to open I2C bus" in str(excInfo.value)

    def test_init_success_storesConfiguration(self):
        """
        Given: Running on Pi with I2C available
        When: I2cClient is created with custom config
        Then: Stores the configuration
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                # Act
                client = I2cClient(bus=2, maxRetries=5, initialDelay=0.5, backoffMultiplier=3.0)

                # Assert
                assert client.bus == 2
                assert client._maxRetries == 5
                assert client._initialDelay == 0.5
                assert client._backoffMultiplier == 3.0
                assert client.isConnected is True

    def test_init_defaultValues_usesDefaults(self):
        """
        Given: Running on Pi with I2C available
        When: I2cClient is created without arguments
        Then: Uses default values
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                # Act
                client = I2cClient()

                # Assert
                assert client.bus == DEFAULT_BUS
                assert client._maxRetries == DEFAULT_MAX_RETRIES
                assert client._initialDelay == DEFAULT_INITIAL_DELAY
                assert client._backoffMultiplier == DEFAULT_BACKOFF_MULTIPLIER


# ================================================================================
# I2C Client Read Tests
# ================================================================================

class TestI2cClientRead:
    """Tests for I2cClient read operations."""

    @pytest.fixture
    def mockClient(self):
        """Create a mock I2C client for testing."""
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient(maxRetries=3, initialDelay=0.01)
                yield client, mockSMBusInstance

    def test_readByte_success_returnsValue(self, mockClient):
        """
        Given: I2C device responds with byte value
        When: readByte is called
        Then: Returns the byte value
        """
        # Arrange
        client, mockSmbus = mockClient
        mockSmbus.read_byte_data.return_value = 75

        # Act
        result = client.readByte(0x36, 0x06)

        # Assert
        assert result == 75
        mockSmbus.read_byte_data.assert_called_once_with(0x36, 0x06)

    def test_readByte_busNotInitialized_raisesNotAvailable(self):
        """
        Given: SMBus is None
        When: readByte is called
        Then: Raises I2cNotAvailableError
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient()
                client._smbus = None

                # Act & Assert
                with pytest.raises(I2cNotAvailableError):
                    client.readByte(0x36, 0x06)

    def test_readByte_deviceNotFound_raisesDeviceNotFound(self, mockClient):
        """
        Given: I2C device not found (errno 121)
        When: readByte is called
        Then: Raises I2cDeviceNotFoundError
        """
        # Arrange
        client, mockSmbus = mockClient
        error = OSError(121, "Remote I/O error")
        error.errno = 121
        mockSmbus.read_byte_data.side_effect = error

        # Act & Assert
        with pytest.raises(I2cDeviceNotFoundError) as excInfo:
            client.readByte(0x36, 0x06)

        assert "0x36" in str(excInfo.value)

    def test_readByte_transientError_retriesAndSucceeds(self, mockClient):
        """
        Given: I2C device fails once then succeeds
        When: readByte is called
        Then: Retries and returns success value
        """
        # Arrange
        client, mockSmbus = mockClient
        mockSmbus.read_byte_data.side_effect = [
            OSError("Bus error"),
            50
        ]

        # Act
        result = client.readByte(0x36, 0x06)

        # Assert
        assert result == 50
        assert mockSmbus.read_byte_data.call_count == 2

    def test_readByte_allRetriesFail_raisesCommunicationError(self, mockClient):
        """
        Given: I2C device fails on all retry attempts
        When: readByte is called
        Then: Raises I2cCommunicationError after max retries
        """
        # Arrange
        client, mockSmbus = mockClient
        mockSmbus.read_byte_data.side_effect = OSError("Bus error")

        # Act & Assert
        with pytest.raises(I2cCommunicationError):
            client.readByte(0x36, 0x06)

        # Should attempt initial + maxRetries times
        assert mockSmbus.read_byte_data.call_count == 4

    def test_readWord_success_returnsValue(self, mockClient):
        """
        Given: I2C device responds with word value
        When: readWord is called
        Then: Returns the 16-bit value
        """
        # Arrange
        client, mockSmbus = mockClient
        mockSmbus.read_word_data.return_value = 3700  # 3.7V in mV

        # Act
        result = client.readWord(0x36, 0x02)

        # Assert
        assert result == 3700
        mockSmbus.read_word_data.assert_called_once_with(0x36, 0x02)

    def test_readWord_busNotInitialized_raisesNotAvailable(self):
        """
        Given: SMBus is None
        When: readWord is called
        Then: Raises I2cNotAvailableError
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient()
                client._smbus = None

                # Act & Assert
                with pytest.raises(I2cNotAvailableError):
                    client.readWord(0x36, 0x02)


# ================================================================================
# I2C Client Write Tests
# ================================================================================

class TestI2cClientWrite:
    """Tests for I2cClient write operations."""

    @pytest.fixture
    def mockClient(self):
        """Create a mock I2C client for testing."""
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient(maxRetries=3, initialDelay=0.01)
                yield client, mockSMBusInstance

    def test_writeByte_success_callsSmbus(self, mockClient):
        """
        Given: I2C device accepts write
        When: writeByte is called
        Then: Calls smbus write_byte_data
        """
        # Arrange
        client, mockSmbus = mockClient

        # Act
        client.writeByte(0x36, 0x10, 0x01)

        # Assert
        mockSmbus.write_byte_data.assert_called_once_with(0x36, 0x10, 0x01)

    def test_writeByte_busNotInitialized_raisesNotAvailable(self):
        """
        Given: SMBus is None
        When: writeByte is called
        Then: Raises I2cNotAvailableError
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient()
                client._smbus = None

                # Act & Assert
                with pytest.raises(I2cNotAvailableError):
                    client.writeByte(0x36, 0x10, 0x01)

    def test_writeByte_invalidValue_raisesValueError(self, mockClient):
        """
        Given: Value out of byte range
        When: writeByte is called
        Then: Raises ValueError
        """
        # Arrange
        client, mockSmbus = mockClient

        # Act & Assert
        with pytest.raises(ValueError) as excInfo:
            client.writeByte(0x36, 0x10, 256)

        assert "0-255" in str(excInfo.value)

    def test_writeByte_negativeValue_raisesValueError(self, mockClient):
        """
        Given: Negative value
        When: writeByte is called
        Then: Raises ValueError
        """
        # Arrange
        client, mockSmbus = mockClient

        # Act & Assert
        with pytest.raises(ValueError):
            client.writeByte(0x36, 0x10, -1)

    def test_writeByte_transientError_retriesAndSucceeds(self, mockClient):
        """
        Given: I2C device fails once then succeeds
        When: writeByte is called
        Then: Retries and succeeds
        """
        # Arrange
        client, mockSmbus = mockClient
        mockSmbus.write_byte_data.side_effect = [
            OSError("Bus error"),
            None
        ]

        # Act
        client.writeByte(0x36, 0x10, 0x01)

        # Assert
        assert mockSmbus.write_byte_data.call_count == 2

    def test_writeWord_success_callsSmbus(self, mockClient):
        """
        Given: I2C device accepts write
        When: writeWord is called
        Then: Calls smbus write_word_data
        """
        # Arrange
        client, mockSmbus = mockClient

        # Act
        client.writeWord(0x36, 0x10, 0x1234)

        # Assert
        mockSmbus.write_word_data.assert_called_once_with(0x36, 0x10, 0x1234)

    def test_writeWord_invalidValue_raisesValueError(self, mockClient):
        """
        Given: Value out of word range
        When: writeWord is called
        Then: Raises ValueError
        """
        # Arrange
        client, mockSmbus = mockClient

        # Act & Assert
        with pytest.raises(ValueError) as excInfo:
            client.writeWord(0x36, 0x10, 65536)

        assert "0-65535" in str(excInfo.value)


# ================================================================================
# I2C Client Lifecycle Tests
# ================================================================================

class TestI2cClientLifecycle:
    """Tests for I2cClient lifecycle management."""

    def test_close_closesSmbus(self):
        """
        Given: Connected I2C client
        When: close is called
        Then: Closes the SMBus connection
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient()

                # Act
                client.close()

                # Assert
                mockSMBusInstance.close.assert_called_once()
                assert client.isConnected is False

    def test_close_multipleCallsSafe(self):
        """
        Given: I2C client
        When: close is called multiple times
        Then: No error is raised
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient()

                # Act
                client.close()
                client.close()  # Should not raise

                # Assert
                assert client.isConnected is False

    def test_contextManager_closesOnExit(self):
        """
        Given: I2C client used as context manager
        When: Exiting the context
        Then: Closes the SMBus connection
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                # Act
                with I2cClient() as client:
                    assert client.isConnected is True

                # Assert
                mockSMBusInstance.close.assert_called_once()

    def test_contextManager_returnsClient(self):
        """
        Given: I2C client used as context manager
        When: Entering the context
        Then: Returns the client instance
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                # Act
                with I2cClient() as client:
                    # Assert
                    assert isinstance(client, I2cClient)


# ================================================================================
# I2C Client Retry Logic Tests
# ================================================================================

class TestI2cClientRetryLogic:
    """Tests for I2C client retry and backoff logic."""

    def test_retry_usesExponentialBackoff(self):
        """
        Given: I2C device fails multiple times
        When: Operation is retried
        Then: Uses exponential backoff delays
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance
        mockSMBusInstance.read_byte_data.side_effect = [
            OSError("Error 1"),
            OSError("Error 2"),
            OSError("Error 3"),
            42
        ]

        sleepCalls = []
        __import__('time').sleep

        def mockSleep(delay):
            sleepCalls.append(delay)

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                with patch('time.sleep', side_effect=mockSleep):
                    client = I2cClient(maxRetries=3, initialDelay=1.0, backoffMultiplier=2.0)

                    # Act
                    result = client.readByte(0x36, 0x06)

                    # Assert
                    assert result == 42
                    assert len(sleepCalls) == 3
                    assert sleepCalls[0] == 1.0
                    assert sleepCalls[1] == 2.0
                    assert sleepCalls[2] == 4.0

    def test_retry_deviceNotFound_noRetry(self):
        """
        Given: Device not found error (errno 121)
        When: readByte is called
        Then: Does not retry, raises immediately
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance
        error = OSError(121, "Remote I/O error")
        error.errno = 121
        mockSMBusInstance.read_byte_data.side_effect = error

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient(maxRetries=3)

                # Act & Assert
                with pytest.raises(I2cDeviceNotFoundError):
                    client.readByte(0x36, 0x06)

                # Should only call once (no retry)
                assert mockSMBusInstance.read_byte_data.call_count == 1

    def test_retry_unexpectedException_noRetry(self):
        """
        Given: Unexpected exception (not OSError)
        When: readByte is called
        Then: Does not retry, raises I2cCommunicationError immediately
        """
        # Arrange
        mockSMBusInstance = MagicMock()
        mockSmbus2 = MagicMock()
        mockSmbus2.SMBus.return_value = mockSMBusInstance
        mockSMBusInstance.read_byte_data.side_effect = ValueError("Unexpected")

        with patch('hardware.i2c_client.isRaspberryPi', return_value=True):
            with patch.dict('sys.modules', {'smbus2': mockSmbus2}):
                client = I2cClient(maxRetries=3)

                # Act & Assert
                with pytest.raises(I2cCommunicationError):
                    client.readByte(0x36, 0x06)

                # Should only call once (no retry)
                assert mockSMBusInstance.read_byte_data.call_count == 1


# ================================================================================
# I2C Constants Tests
# ================================================================================

class TestI2cConstants:
    """Tests for I2C module constants."""

    def test_defaultBus_isOne(self):
        """
        Given: Default bus constant
        When: Checked
        Then: Is 1 (standard for Raspberry Pi)
        """
        assert DEFAULT_BUS == 1

    def test_defaultMaxRetries_isThree(self):
        """
        Given: Default max retries constant
        When: Checked
        Then: Is 3
        """
        assert DEFAULT_MAX_RETRIES == 3

    def test_defaultInitialDelay_isOne(self):
        """
        Given: Default initial delay constant
        When: Checked
        Then: Is 1.0 seconds
        """
        assert DEFAULT_INITIAL_DELAY == 1.0

    def test_defaultBackoffMultiplier_isTwo(self):
        """
        Given: Default backoff multiplier constant
        When: Checked
        Then: Is 2.0
        """
        assert DEFAULT_BACKOFF_MULTIPLIER == 2.0
