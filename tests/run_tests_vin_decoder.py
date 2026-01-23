#!/usr/bin/env python3
################################################################################
# File Name: run_tests_vin_decoder.py
# Purpose/Description: Manual test runner for VIN decoder module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-013
# ================================================================================
################################################################################

"""
Test suite for VIN decoder module.

Covers:
- VinDecodeResult dataclass
- VIN validation
- NHTSA API integration
- Database caching
- Retry logic
- Error handling
- Helper functions
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, Mock
from urllib.error import HTTPError, URLError

# Add src directory to path for imports
srcPath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src')
sys.path.insert(0, srcPath)

from obd.vin_decoder import (
    VinDecoder,
    VinDecodeResult,
    ApiCallResult,
    VinDecoderError,
    VinValidationError,
    VinApiError,
    VinApiTimeoutError,
    VinStorageError,
    createVinDecoderFromConfig,
    decodeVinOnFirstConnection,
    isVinDecoderEnabled,
    getVehicleInfo,
    validateVinFormat,
    NHTSA_API_BASE_URL,
    DEFAULT_API_TIMEOUT,
    NHTSA_FIELD_MAPPING,
)
from obd.database import ObdDatabase


# ================================================================================
# Test Fixtures
# ================================================================================

def createTestConfig(overrides=None):
    """Create test configuration with optional overrides."""
    config = {
        'vinDecoder': {
            'enabled': True,
            'apiBaseUrl': NHTSA_API_BASE_URL,
            'apiTimeoutSeconds': 30,
            'cacheVinData': True
        }
    }
    if overrides:
        for key, value in overrides.items():
            if '.' in key:
                parts = key.split('.')
                d = config
                for part in parts[:-1]:
                    d = d.setdefault(part, {})
                d[parts[-1]] = value
            else:
                config[key] = value
    return config


def createTestDatabase():
    """Create an in-memory test database."""
    fd, dbPath = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = ObdDatabase(dbPath)
    db.initialize()
    return db, dbPath


def createMockNhtsaResponse(vehicleData=None):
    """Create a mock NHTSA API response."""
    if vehicleData is None:
        vehicleData = {
            'Make': 'CHEVROLET',
            'Model': 'CORVETTE',
            'ModelYear': '1998',
            'EngineModel': '5.7L V8',
            'FuelTypePrimary': 'Gasoline',
            'TransmissionStyle': 'Manual',
            'DriveType': 'Rear-Wheel Drive',
            'BodyClass': 'Coupe',
            'PlantCity': 'BOWLING GREEN',
            'PlantCountry': 'UNITED STATES',
            'ErrorCode': '0',
            'ErrorText': ''
        }
    return {
        'Count': 1,
        'Message': 'Results returned successfully',
        'SearchCriteria': 'VIN:1G1YY22G965104378',
        'Results': [vehicleData]
    }


# ================================================================================
# VinDecodeResult Tests
# ================================================================================

class TestVinDecodeResult(unittest.TestCase):
    """Tests for VinDecodeResult dataclass."""

    def test_defaultValues(self):
        """Default values should be set correctly."""
        result = VinDecodeResult(vin='TEST')
        self.assertEqual(result.vin, 'TEST')
        self.assertFalse(result.success)
        self.assertIsNone(result.make)
        self.assertIsNone(result.model)
        self.assertIsNone(result.year)
        self.assertFalse(result.fromCache)

    def test_toDict(self):
        """toDict should return all fields."""
        result = VinDecodeResult(
            vin='1G1YY22G965104378',
            success=True,
            make='CHEVROLET',
            model='CORVETTE',
            year=1998
        )
        data = result.toDict()
        self.assertEqual(data['vin'], '1G1YY22G965104378')
        self.assertTrue(data['success'])
        self.assertEqual(data['make'], 'CHEVROLET')
        self.assertEqual(data['model'], 'CORVETTE')
        self.assertEqual(data['year'], 1998)

    def test_getVehicleSummary_success(self):
        """getVehicleSummary should return formatted string for success."""
        result = VinDecodeResult(
            vin='1G1YY22G965104378',
            success=True,
            make='CHEVROLET',
            model='CORVETTE',
            year=1998
        )
        summary = result.getVehicleSummary()
        self.assertEqual(summary, '1998 CHEVROLET CORVETTE')

    def test_getVehicleSummary_failure(self):
        """getVehicleSummary should return unknown for failure."""
        result = VinDecodeResult(
            vin='INVALID',
            success=False
        )
        summary = result.getVehicleSummary()
        self.assertIn('Unknown vehicle', summary)
        self.assertIn('INVALID', summary)

    def test_getVehicleSummary_partialData(self):
        """getVehicleSummary should handle partial data."""
        result = VinDecodeResult(
            vin='TEST',
            success=True,
            make='TOYOTA'
        )
        summary = result.getVehicleSummary()
        self.assertEqual(summary, 'TOYOTA')


# ================================================================================
# ApiCallResult Tests
# ================================================================================

class TestApiCallResult(unittest.TestCase):
    """Tests for ApiCallResult dataclass."""

    def test_defaultValues(self):
        """Default values should be set correctly."""
        result = ApiCallResult()
        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertIsNone(result.statusCode)
        self.assertIsNone(result.errorMessage)

    def test_successResult(self):
        """Success result should have data."""
        result = ApiCallResult(
            success=True,
            data={'test': 'value'},
            statusCode=200
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data, {'test': 'value'})
        self.assertEqual(result.statusCode, 200)


# ================================================================================
# Exception Tests
# ================================================================================

class TestExceptions(unittest.TestCase):
    """Tests for custom exceptions."""

    def test_vinDecoderError(self):
        """VinDecoderError should store message and details."""
        error = VinDecoderError("Test error", {'key': 'value'})
        self.assertEqual(str(error), "Test error")
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.details, {'key': 'value'})

    def test_vinValidationError(self):
        """VinValidationError should inherit from base."""
        error = VinValidationError("Invalid VIN")
        self.assertIsInstance(error, VinDecoderError)

    def test_vinApiError(self):
        """VinApiError should inherit from base."""
        error = VinApiError("API failed")
        self.assertIsInstance(error, VinDecoderError)

    def test_vinApiTimeoutError(self):
        """VinApiTimeoutError should inherit from VinApiError."""
        error = VinApiTimeoutError("Timeout")
        self.assertIsInstance(error, VinApiError)

    def test_vinStorageError(self):
        """VinStorageError should inherit from base."""
        error = VinStorageError("Storage failed")
        self.assertIsInstance(error, VinDecoderError)


# ================================================================================
# VIN Validation Tests
# ================================================================================

class TestVinValidation(unittest.TestCase):
    """Tests for VIN validation."""

    def test_validateVinFormat_valid(self):
        """Valid VIN should pass validation."""
        self.assertTrue(validateVinFormat('1G1YY22G965104378'))
        self.assertTrue(validateVinFormat('WVWZZZ3CZWE000001'))

    def test_validateVinFormat_lowercase(self):
        """Lowercase VIN should be normalized and pass."""
        self.assertTrue(validateVinFormat('1g1yy22g965104378'))

    def test_validateVinFormat_withSpaces(self):
        """VIN with spaces should be normalized and pass."""
        self.assertTrue(validateVinFormat('1G1YY 22G96 5104378'))

    def test_validateVinFormat_withDashes(self):
        """VIN with dashes should be normalized and pass."""
        self.assertTrue(validateVinFormat('1G1YY-22G96-5104378'))

    def test_validateVinFormat_tooShort(self):
        """VIN too short should fail validation."""
        self.assertFalse(validateVinFormat('1G1YY22G9651'))

    def test_validateVinFormat_tooLong(self):
        """VIN too long should fail validation."""
        self.assertFalse(validateVinFormat('1G1YY22G965104378ABC'))

    def test_validateVinFormat_invalidChars_I(self):
        """VIN with I should fail (not used in VINs)."""
        self.assertFalse(validateVinFormat('1G1YY22G965I04378'))

    def test_validateVinFormat_invalidChars_O(self):
        """VIN with O should fail (not used in VINs)."""
        self.assertFalse(validateVinFormat('1G1YY22G9651O4378'))

    def test_validateVinFormat_invalidChars_Q(self):
        """VIN with Q should fail (not used in VINs)."""
        self.assertFalse(validateVinFormat('1G1YY22G965Q04378'))

    def test_validateVinFormat_empty(self):
        """Empty VIN should fail validation."""
        self.assertFalse(validateVinFormat(''))

    def test_validateVinFormat_specialChars(self):
        """VIN with special characters should fail."""
        self.assertFalse(validateVinFormat('1G1YY22G96510437#'))


# ================================================================================
# VinDecoder Initialization Tests
# ================================================================================

class TestVinDecoderInit(unittest.TestCase):
    """Tests for VinDecoder initialization."""

    def setUp(self):
        """Set up test database."""
        self.db, self.dbPath = createTestDatabase()

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.dbPath):
            os.remove(self.dbPath)

    def test_initWithDefaultConfig(self):
        """Decoder should initialize with default config."""
        config = createTestConfig()
        decoder = VinDecoder(config, self.db)
        self.assertTrue(decoder._enabled)
        self.assertEqual(decoder._apiTimeout, 30)

    def test_initWithCustomConfig(self):
        """Decoder should use custom config values."""
        config = createTestConfig({
            'vinDecoder.enabled': False,
            'vinDecoder.apiTimeoutSeconds': 60,
            'vinDecoder.cacheVinData': False
        })
        decoder = VinDecoder(config, self.db)
        self.assertFalse(decoder._enabled)
        self.assertEqual(decoder._apiTimeout, 60)
        self.assertFalse(decoder._cacheVinData)

    def test_initWithMissingConfig(self):
        """Decoder should use defaults for missing config."""
        config = {}
        decoder = VinDecoder(config, self.db)
        self.assertTrue(decoder._enabled)
        self.assertEqual(decoder._apiTimeout, DEFAULT_API_TIMEOUT)


# ================================================================================
# VinDecoder decodeVin Tests
# ================================================================================

class TestVinDecoderDecodeVin(unittest.TestCase):
    """Tests for VinDecoder.decodeVin method."""

    def setUp(self):
        """Set up test database and decoder."""
        self.db, self.dbPath = createTestDatabase()
        self.config = createTestConfig()
        self.decoder = VinDecoder(self.config, self.db)

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.dbPath):
            os.remove(self.dbPath)

    def test_decodeVin_invalidVin_tooShort(self):
        """Invalid VIN should return error result."""
        result = self.decoder.decodeVin('ABC123')
        self.assertFalse(result.success)
        self.assertIn('Invalid VIN', result.errorMessage)

    def test_decodeVin_invalidVin_invalidChars(self):
        """VIN with invalid chars should return error."""
        result = self.decoder.decodeVin('1G1YY22G965I04378')  # I not valid
        self.assertFalse(result.success)
        self.assertIn('Invalid VIN', result.errorMessage)

    def test_decodeVin_decoderDisabled(self):
        """Disabled decoder should return error."""
        config = createTestConfig({'vinDecoder.enabled': False})
        decoder = VinDecoder(config, self.db)
        result = decoder.decodeVin('1G1YY22G965104378')
        self.assertFalse(result.success)
        self.assertIn('disabled', result.errorMessage)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_decodeVin_apiSuccess(self, mockUrlopen):
        """Successful API call should return vehicle data."""
        # Mock API response
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        result = self.decoder.decodeVin('1G1YY22G965104378')

        self.assertTrue(result.success)
        self.assertEqual(result.make, 'CHEVROLET')
        self.assertEqual(result.model, 'CORVETTE')
        self.assertEqual(result.year, 1998)
        self.assertFalse(result.fromCache)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_decodeVin_usesCache(self, mockUrlopen):
        """Second call should use cache."""
        # Mock API response for first call
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        # First call - hits API
        result1 = self.decoder.decodeVin('1G1YY22G965104378')
        self.assertTrue(result1.success)
        self.assertFalse(result1.fromCache)

        # Second call - should use cache
        mockUrlopen.reset_mock()
        result2 = self.decoder.decodeVin('1G1YY22G965104378')
        self.assertTrue(result2.success)
        self.assertTrue(result2.fromCache)
        mockUrlopen.assert_not_called()  # Should not call API

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_decodeVin_forceApiCall(self, mockUrlopen):
        """forceApiCall should bypass cache."""
        # Mock API response
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        # First call
        self.decoder.decodeVin('1G1YY22G965104378')

        # Force API call
        result = self.decoder.decodeVin('1G1YY22G965104378', forceApiCall=True)
        self.assertTrue(result.success)
        self.assertFalse(result.fromCache)
        self.assertEqual(mockUrlopen.call_count, 2)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_decodeVin_normalizesVin(self, mockUrlopen):
        """VIN should be normalized before API call."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        # Call with lowercase and spaces
        result = self.decoder.decodeVin('1g1yy 22g96 5104378')
        self.assertTrue(result.success)
        self.assertEqual(result.vin, '1G1YY22G965104378')


# ================================================================================
# VinDecoder API Error Handling Tests
# ================================================================================

class TestVinDecoderApiErrors(unittest.TestCase):
    """Tests for API error handling and retry logic."""

    def setUp(self):
        """Set up test database and decoder."""
        self.db, self.dbPath = createTestDatabase()
        self.config = createTestConfig()
        self.decoder = VinDecoder(self.config, self.db)

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.dbPath):
            os.remove(self.dbPath)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_apiHttpError(self, mockUrlopen):
        """HTTP error should trigger retry."""
        # First call fails, second succeeds
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)

        mockUrlopen.side_effect = [
            HTTPError(None, 500, 'Internal Server Error', {}, None),
            mockResponse
        ]

        result = self.decoder.decodeVin('1G1YY22G965104378')
        self.assertTrue(result.success)
        self.assertEqual(mockUrlopen.call_count, 2)

    @patch('obd.vehicle.vin_decoder.urlopen')
    @patch('obd.vehicle.vin_decoder.time.sleep')  # Mock sleep to speed up test
    def test_apiAllRetriesFail(self, mockSleep, mockUrlopen):
        """All retries failing should return error."""
        mockUrlopen.side_effect = HTTPError(
            None, 500, 'Internal Server Error', {}, None
        )

        result = self.decoder.decodeVin('1G1YY22G965104378')
        self.assertFalse(result.success)
        self.assertIn('API call failed', result.errorMessage)
        self.assertEqual(mockUrlopen.call_count, 2)  # Initial + 1 retry

    @patch('obd.vehicle.vin_decoder.urlopen')
    @patch('obd.vehicle.vin_decoder.time.sleep')
    def test_apiTimeoutError(self, mockSleep, mockUrlopen):
        """Timeout should be handled gracefully."""
        mockUrlopen.side_effect = URLError('timed out')

        result = self.decoder.decodeVin('1G1YY22G965104378')
        self.assertFalse(result.success)
        self.assertIn('API call failed', result.errorMessage)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_apiInvalidJson(self, mockUrlopen):
        """Invalid JSON response should be handled."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = b'not valid json'
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        result = self.decoder.decodeVin('1G1YY22G965104378')
        # Will retry, so we expect 2 calls
        self.assertFalse(result.success)


# ================================================================================
# VinDecoder Response Parsing Tests
# ================================================================================

class TestVinDecoderParsing(unittest.TestCase):
    """Tests for NHTSA response parsing."""

    def setUp(self):
        """Set up test database and decoder."""
        self.db, self.dbPath = createTestDatabase()
        self.config = createTestConfig()
        self.decoder = VinDecoder(self.config, self.db)

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.dbPath):
            os.remove(self.dbPath)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_parseAllFields(self, mockUrlopen):
        """All NHTSA fields should be parsed correctly."""
        vehicleData = {
            'Make': 'MITSUBISHI',
            'Model': 'ECLIPSE',
            'ModelYear': '1998',
            'EngineModel': '2.0L 4-Cyl',
            'FuelTypePrimary': 'Gasoline',
            'TransmissionStyle': 'Manual',
            'DriveType': 'Front-Wheel Drive',
            'BodyClass': 'Coupe',
            'PlantCity': 'NORMAL',
            'PlantCountry': 'UNITED STATES',
            'ErrorCode': '0'
        }

        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse(vehicleData)
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        result = self.decoder.decodeVin('1MEHP12R4SW123456')

        self.assertTrue(result.success)
        self.assertEqual(result.make, 'MITSUBISHI')
        self.assertEqual(result.model, 'ECLIPSE')
        self.assertEqual(result.year, 1998)
        self.assertEqual(result.engine, '2.0L 4-Cyl')
        self.assertEqual(result.fuelType, 'Gasoline')
        self.assertEqual(result.transmission, 'Manual')
        self.assertEqual(result.driveType, 'Front-Wheel Drive')
        self.assertEqual(result.bodyClass, 'Coupe')
        self.assertEqual(result.plantCity, 'NORMAL')
        self.assertEqual(result.plantCountry, 'UNITED STATES')

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_parseNotApplicableAsNull(self, mockUrlopen):
        """'Not Applicable' values should be parsed as None."""
        vehicleData = {
            'Make': 'TEST',
            'Model': 'CAR',
            'ModelYear': '2020',
            'EngineModel': 'Not Applicable',
            'FuelTypePrimary': 'N/A',
            'TransmissionStyle': '',
            'ErrorCode': '0'
        }

        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse(vehicleData)
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        result = self.decoder.decodeVin('1G1YY22G965104378')

        self.assertTrue(result.success)
        self.assertIsNone(result.engine)
        self.assertIsNone(result.fuelType)
        self.assertIsNone(result.transmission)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_parseWithErrorCode(self, mockUrlopen):
        """Non-zero error code should be recorded but still return data."""
        vehicleData = {
            'Make': 'GENERIC',
            'Model': 'CAR',
            'ModelYear': '2020',
            'ErrorCode': '1',
            'ErrorText': 'Check digit incorrect'
        }

        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse(vehicleData)
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        result = self.decoder.decodeVin('1G1YY22G965104378')

        self.assertTrue(result.success)  # Still succeeds with partial data
        self.assertEqual(result.errorCode, '1')

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_parseEmptyResults(self, mockUrlopen):
        """Empty results array should return error."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps({
            'Results': []
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        result = self.decoder.decodeVin('1G1YY22G965104378')

        self.assertFalse(result.success)
        self.assertIn('No results', result.errorMessage)


# ================================================================================
# VinDecoder Database Cache Tests
# ================================================================================

class TestVinDecoderCache(unittest.TestCase):
    """Tests for database caching functionality."""

    def setUp(self):
        """Set up test database and decoder."""
        self.db, self.dbPath = createTestDatabase()
        self.config = createTestConfig()
        self.decoder = VinDecoder(self.config, self.db)

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.dbPath):
            os.remove(self.dbPath)

    def test_isVinCached_notCached(self):
        """isVinCached should return False for new VIN."""
        self.assertFalse(self.decoder.isVinCached('1G1YY22G965104378'))

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_isVinCached_afterDecode(self, mockUrlopen):
        """isVinCached should return True after decoding."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        self.decoder.decodeVin('1G1YY22G965104378')
        self.assertTrue(self.decoder.isVinCached('1G1YY22G965104378'))

    def test_getDecodedVin_notCached(self):
        """getDecodedVin should return None for uncached VIN."""
        result = self.decoder.getDecodedVin('1G1YY22G965104378')
        self.assertIsNone(result)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_getDecodedVin_cached(self, mockUrlopen):
        """getDecodedVin should return cached data."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        self.decoder.decodeVin('1G1YY22G965104378')

        # Get from cache (no API call)
        mockUrlopen.reset_mock()
        result = self.decoder.getDecodedVin('1G1YY22G965104378')

        self.assertIsNotNone(result)
        self.assertTrue(result.fromCache)
        self.assertEqual(result.make, 'CHEVROLET')
        mockUrlopen.assert_not_called()

    def test_cacheDisabled(self):
        """With caching disabled, should always call API."""
        config = createTestConfig({'vinDecoder.cacheVinData': False})
        decoder = VinDecoder(config, self.db)

        with patch('obd.vehicle.vin_decoder.urlopen') as mockUrlopen:
            mockResponse = MagicMock()
            mockResponse.status = 200
            mockResponse.read.return_value = json.dumps(
                createMockNhtsaResponse()
            ).encode('utf-8')
            mockResponse.__enter__ = MagicMock(return_value=mockResponse)
            mockResponse.__exit__ = MagicMock(return_value=False)
            mockUrlopen.return_value = mockResponse

            # First call
            decoder.decodeVin('1G1YY22G965104378')
            # Second call - should still call API
            decoder.decodeVin('1G1YY22G965104378')

            self.assertEqual(mockUrlopen.call_count, 2)


# ================================================================================
# VinDecoder Statistics Tests
# ================================================================================

class TestVinDecoderStats(unittest.TestCase):
    """Tests for decoder statistics."""

    def setUp(self):
        """Set up test database and decoder."""
        self.db, self.dbPath = createTestDatabase()
        self.config = createTestConfig()
        self.decoder = VinDecoder(self.config, self.db)

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.dbPath):
            os.remove(self.dbPath)

    def test_initialStats(self):
        """Initial stats should be zero."""
        stats = self.decoder.getStats()
        self.assertEqual(stats['totalDecodes'], 0)
        self.assertEqual(stats['cacheHits'], 0)
        self.assertEqual(stats['apiCalls'], 0)
        self.assertEqual(stats['apiErrors'], 0)
        self.assertEqual(stats['cacheHitRate'], 0.0)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_statsAfterDecode(self, mockUrlopen):
        """Stats should update after decode."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        self.decoder.decodeVin('1G1YY22G965104378')
        self.decoder.decodeVin('1G1YY22G965104378')  # Cache hit

        stats = self.decoder.getStats()
        self.assertEqual(stats['totalDecodes'], 2)
        self.assertEqual(stats['cacheHits'], 1)
        self.assertEqual(stats['apiCalls'], 1)
        self.assertEqual(stats['cacheHitRate'], 0.5)


# ================================================================================
# Helper Function Tests
# ================================================================================

class TestHelperFunctions(unittest.TestCase):
    """Tests for module-level helper functions."""

    def setUp(self):
        """Set up test database."""
        self.db, self.dbPath = createTestDatabase()

    def tearDown(self):
        """Clean up test database."""
        if os.path.exists(self.dbPath):
            os.remove(self.dbPath)

    def test_createVinDecoderFromConfig(self):
        """createVinDecoderFromConfig should create decoder."""
        config = createTestConfig()
        decoder = createVinDecoderFromConfig(config, self.db)
        self.assertIsInstance(decoder, VinDecoder)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_decodeVinOnFirstConnection(self, mockUrlopen):
        """decodeVinOnFirstConnection should decode VIN."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        config = createTestConfig()
        result = decodeVinOnFirstConnection('1G1YY22G965104378', config, self.db)

        self.assertTrue(result.success)
        self.assertEqual(result.make, 'CHEVROLET')

    def test_isVinDecoderEnabled_enabled(self):
        """isVinDecoderEnabled should return True when enabled."""
        config = createTestConfig({'vinDecoder.enabled': True})
        self.assertTrue(isVinDecoderEnabled(config))

    def test_isVinDecoderEnabled_disabled(self):
        """isVinDecoderEnabled should return False when disabled."""
        config = createTestConfig({'vinDecoder.enabled': False})
        self.assertFalse(isVinDecoderEnabled(config))

    def test_isVinDecoderEnabled_missing(self):
        """isVinDecoderEnabled should default to True."""
        config = {}
        self.assertTrue(isVinDecoderEnabled(config))

    def test_getVehicleInfo_notFound(self):
        """getVehicleInfo should return None for unknown VIN."""
        result = getVehicleInfo(self.db, 'UNKNOWN123456789')
        self.assertIsNone(result)

    @patch('obd.vehicle.vin_decoder.urlopen')
    def test_getVehicleInfo_found(self, mockUrlopen):
        """getVehicleInfo should return data for known VIN."""
        mockResponse = MagicMock()
        mockResponse.status = 200
        mockResponse.read.return_value = json.dumps(
            createMockNhtsaResponse()
        ).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        config = createTestConfig()
        decoder = VinDecoder(config, self.db)
        decoder.decodeVin('1G1YY22G965104378')

        result = getVehicleInfo(self.db, '1G1YY22G965104378')

        self.assertIsNotNone(result)
        self.assertEqual(result['vin'], '1G1YY22G965104378')
        self.assertEqual(result['make'], 'CHEVROLET')
        self.assertEqual(result['model'], 'CORVETTE')


# ================================================================================
# Test Runner
# ================================================================================

def runTests():
    """Run all tests and report results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    testClasses = [
        TestVinDecodeResult,
        TestApiCallResult,
        TestExceptions,
        TestVinValidation,
        TestVinDecoderInit,
        TestVinDecoderDecodeVin,
        TestVinDecoderApiErrors,
        TestVinDecoderParsing,
        TestVinDecoderCache,
        TestVinDecoderStats,
        TestHelperFunctions,
    ]

    for testClass in testClasses:
        tests = loader.loadTestsFromTestCase(testClass)
        suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print('\n' + '=' * 70)
    print('VIN DECODER TEST SUMMARY')
    print('=' * 70)
    print(f'Tests run: {result.testsRun}')
    print(f'Failures: {len(result.failures)}')
    print(f'Errors: {len(result.errors)}')
    print(f'Skipped: {len(result.skipped)}')
    print(f'Success: {result.wasSuccessful()}')

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(runTests())
