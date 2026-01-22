################################################################################
# File Name: run_tests_simulated_vin_decoder.py
# Purpose/Description: Tests for simulated VIN decoding (US-042)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-042
# ================================================================================
################################################################################

"""
Test suite for simulated VIN decoding functionality.

Tests:
- SimulatedVinDecoder class with profile data
- VIN query in SimulatedObdConnection
- Integration with StaticDataCollector
- Database caching of simulated VIN data
- Vehicle info display from simulated data
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# Ensure src is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.simulator.vehicle_profile import VehicleProfile, getDefaultProfile
from obd.simulator.simulated_connection import (
    SimulatedObdConnection,
    SimulatedObd,
    SimulatedResponse,
)
from obd.simulator.simulated_vin_decoder import (
    SimulatedVinDecoder,
    SimulatedVinDecodeResult,
    SimulatedVinDecoderError,
    SimulatedVinStorageError,
    createSimulatedVinDecoderFromConfig,
    createVinDecoderForSimulation,
    isSimulatedDecodeResult,
)


class TestSimulatedVinDecodeResult(unittest.TestCase):
    """Tests for SimulatedVinDecodeResult dataclass."""

    def test_init_defaults(self):
        """
        Given: Default parameters
        When: Creating SimulatedVinDecodeResult
        Then: Should have correct defaults
        """
        result = SimulatedVinDecodeResult(vin="TEST123456789VIN")

        self.assertEqual(result.vin, "TEST123456789VIN")
        self.assertFalse(result.success)
        self.assertTrue(result.fromSimulator)
        self.assertFalse(result.fromCache)
        self.assertIsNone(result.make)
        self.assertIsNone(result.model)
        self.assertIsNone(result.year)

    def test_toDict_containsAllFields(self):
        """
        Given: Populated SimulatedVinDecodeResult
        When: Converting to dict
        Then: Should contain all fields
        """
        result = SimulatedVinDecodeResult(
            vin="1G1YY22G965104378",
            success=True,
            make="Mitsubishi",
            model="Eclipse",
            year=1998,
            engine="2.0L 4-cylinder",
            fuelType="Gasoline",
            transmission="Manual",
            driveType="FWD",
            bodyClass="Coupe",
            plantCity="Simulated",
            plantCountry="Simulation",
            fromSimulator=True
        )

        d = result.toDict()

        self.assertEqual(d['vin'], "1G1YY22G965104378")
        self.assertTrue(d['success'])
        self.assertEqual(d['make'], "Mitsubishi")
        self.assertEqual(d['model'], "Eclipse")
        self.assertEqual(d['year'], 1998)
        self.assertTrue(d['fromSimulator'])

    def test_getVehicleSummary_success(self):
        """
        Given: Successful decode result
        When: Getting vehicle summary
        Then: Should return formatted string
        """
        result = SimulatedVinDecodeResult(
            vin="TEST123456789VIN",
            success=True,
            make="Honda",
            model="Civic",
            year=2020
        )

        summary = result.getVehicleSummary()

        self.assertEqual(summary, "2020 Honda Civic")

    def test_getVehicleSummary_failure(self):
        """
        Given: Failed decode result
        When: Getting vehicle summary
        Then: Should return unknown vehicle string
        """
        result = SimulatedVinDecodeResult(
            vin="TEST123456789VIN",
            success=False
        )

        summary = result.getVehicleSummary()

        self.assertIn("Unknown vehicle", summary)
        self.assertIn("TEST123456789VIN", summary)

    def test_getVehicleSummary_partialData(self):
        """
        Given: Partial decode result (missing year)
        When: Getting vehicle summary
        Then: Should return available data
        """
        result = SimulatedVinDecodeResult(
            vin="TEST123456789VIN",
            success=True,
            make="Ford",
            model="Mustang"
        )

        summary = result.getVehicleSummary()

        self.assertEqual(summary, "Ford Mustang")


class TestSimulatedVinDecoder(unittest.TestCase):
    """Tests for SimulatedVinDecoder class."""

    def setUp(self):
        """Set up test fixtures."""
        self.profile = VehicleProfile(
            vin="1G4HP52K45U123456",
            make="Mitsubishi",
            model="Eclipse GST",
            year=1998,
            engineDisplacementL=2.0,
            cylinders=4,
            fuelType="Gasoline",
            maxRpm=7500,
            redlineRpm=7000,
            idleRpm=800
        )
        self.config = {
            'vinDecoder': {
                'enabled': True,
                'cacheVinData': True
            }
        }

    def test_init_withProfile(self):
        """
        Given: VehicleProfile and config
        When: Creating SimulatedVinDecoder
        Then: Should initialize correctly
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        self.assertEqual(decoder.profile.make, "Mitsubishi")
        self.assertEqual(decoder.profile.model, "Eclipse GST")

    def test_init_withDefaultProfile(self):
        """
        Given: No profile provided
        When: Creating SimulatedVinDecoder
        Then: Should use default profile
        """
        decoder = SimulatedVinDecoder()

        self.assertEqual(decoder.profile.make, "Generic")
        self.assertEqual(decoder.profile.model, "Sedan")

    def test_decodeVin_usesProfileVin(self):
        """
        Given: SimulatedVinDecoder with profile
        When: Decoding without specifying VIN
        Then: Should use VIN from profile
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        result = decoder.decodeVin()

        self.assertTrue(result.success)
        self.assertEqual(result.vin, "1G4HP52K45U123456")
        self.assertEqual(result.make, "Mitsubishi")
        self.assertEqual(result.model, "Eclipse GST")
        self.assertEqual(result.year, 1998)

    def test_decodeVin_usesSpecifiedVin(self):
        """
        Given: SimulatedVinDecoder with profile
        When: Decoding with specified VIN
        Then: Should use specified VIN but profile data
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        result = decoder.decodeVin(vin="DIFFERENTVIN12345")

        self.assertTrue(result.success)
        self.assertEqual(result.vin, "DIFFERENTVIN12345")
        self.assertEqual(result.make, "Mitsubishi")  # Still uses profile data

    def test_decodeVin_setsFromSimulatorFlag(self):
        """
        Given: SimulatedVinDecoder
        When: Decoding VIN
        Then: Should set fromSimulator flag to True
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        result = decoder.decodeVin()

        self.assertTrue(result.fromSimulator)

    def test_decodeVin_generatesEngineDescription(self):
        """
        Given: Profile with engine specs
        When: Decoding VIN
        Then: Should generate proper engine description
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        result = decoder.decodeVin()

        self.assertEqual(result.engine, "2.0L 4-cylinder")

    def test_decodeVin_infersBodyClass_coupe(self):
        """
        Given: Profile with model name containing 'GST'
        When: Decoding VIN
        Then: Should infer body class as Coupe
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        result = decoder.decodeVin()

        self.assertEqual(result.bodyClass, "Coupe")

    def test_decodeVin_infersBodyClass_truck(self):
        """
        Given: Profile with truck model name
        When: Decoding VIN
        Then: Should infer body class as Truck
        """
        truckProfile = VehicleProfile(
            vin="1FTFW1E52KFA12345",
            make="Ford",
            model="F-150 Truck",
            year=2019
        )
        decoder = SimulatedVinDecoder(truckProfile, self.config)

        result = decoder.decodeVin()

        self.assertEqual(result.bodyClass, "Truck")

    def test_decodeVin_infersBodyClass_sedan(self):
        """
        Given: Profile with generic model name
        When: Decoding VIN
        Then: Should infer body class as Sedan
        """
        sedanProfile = VehicleProfile(
            vin="1HGBH41JXMN109186",
            make="Honda",
            model="Accord",
            year=2021
        )
        decoder = SimulatedVinDecoder(sedanProfile, self.config)

        result = decoder.decodeVin()

        self.assertEqual(result.bodyClass, "Sedan")

    def test_decodeVin_infersTransmission_manual(self):
        """
        Given: Profile with high redline (sports car)
        When: Decoding VIN
        Then: Should infer Manual transmission
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        result = decoder.decodeVin()

        self.assertEqual(result.transmission, "Manual")

    def test_decodeVin_infersTransmission_automatic(self):
        """
        Given: Profile with normal redline
        When: Decoding VIN
        Then: Should infer Automatic transmission
        """
        autoProfile = VehicleProfile(
            vin="1HGBH41JXMN109186",
            make="Honda",
            model="Accord",
            year=2021,
            redlineRpm=6000  # Below 7000 threshold
        )
        decoder = SimulatedVinDecoder(autoProfile, self.config)

        result = decoder.decodeVin()

        self.assertEqual(result.transmission, "Automatic")

    def test_getStats_tracksDecodes(self):
        """
        Given: SimulatedVinDecoder
        When: Decoding multiple VINs
        Then: Should track decode count
        """
        decoder = SimulatedVinDecoder(self.profile, self.config)

        decoder.decodeVin()
        decoder.decodeVin()
        decoder.decodeVin()

        stats = decoder.getStats()
        self.assertEqual(stats['totalDecodes'], 3)
        self.assertEqual(stats['apiCalls'], 0)  # No API calls in simulation
        self.assertTrue(stats['isSimulated'])


class TestSimulatedVinDecoderWithDatabase(unittest.TestCase):
    """Tests for SimulatedVinDecoder with database caching."""

    def setUp(self):
        """Set up test fixtures with mock database."""
        self.profile = VehicleProfile(
            vin="1G4HP52K45U123456",
            make="Mitsubishi",
            model="Eclipse GST",
            year=1998
        )
        self.config = {
            'vinDecoder': {
                'enabled': True,
                'cacheVinData': True
            }
        }
        # Create mock database
        self.mockDb = MagicMock()
        self.mockConn = MagicMock()
        self.mockCursor = MagicMock()
        self.mockDb.connect.return_value.__enter__ = MagicMock(
            return_value=self.mockConn
        )
        self.mockDb.connect.return_value.__exit__ = MagicMock(
            return_value=False
        )
        self.mockConn.cursor.return_value = self.mockCursor

    def test_decodeVin_storesInCache(self):
        """
        Given: Database enabled
        When: Decoding VIN
        Then: Should store result in cache
        """
        self.mockCursor.fetchone.return_value = None  # Not in cache
        decoder = SimulatedVinDecoder(self.profile, self.config, self.mockDb)

        result = decoder.decodeVin()

        # Verify INSERT OR REPLACE was called
        self.assertTrue(self.mockCursor.execute.called)
        insertCall = [
            call for call in self.mockCursor.execute.call_args_list
            if 'INSERT OR REPLACE' in str(call)
        ]
        self.assertTrue(len(insertCall) > 0)

    def test_decodeVin_checksCache(self):
        """
        Given: VIN exists in cache
        When: Decoding VIN
        Then: Should return cached result
        """
        # Simulate cache hit
        self.mockCursor.fetchone.return_value = (
            "1G4HP52K45U123456",  # vin
            "Mitsubishi",        # make
            "Eclipse",           # model
            1998,                # year
            "2.0L Turbo",        # engine
            "Gasoline",          # fuel_type
            "Manual",            # transmission
            "FWD",               # drive_type
            "Coupe",             # body_class
            "Normal",            # plant_city
            "USA",               # plant_country
            "{}"                 # raw_api_response
        )

        decoder = SimulatedVinDecoder(self.profile, self.config, self.mockDb)

        result = decoder.decodeVin()

        self.assertTrue(result.success)
        self.assertTrue(result.fromCache)
        self.assertTrue(result.fromSimulator)
        self.assertEqual(result.model, "Eclipse")

    def test_isVinCached_returnsTrueWhenCached(self):
        """
        Given: VIN exists in database
        When: Checking if cached
        Then: Should return True
        """
        self.mockCursor.fetchone.return_value = (1,)  # COUNT(*) = 1

        decoder = SimulatedVinDecoder(self.profile, self.config, self.mockDb)

        self.assertTrue(decoder.isVinCached("1G4HP52K45U123456"))

    def test_isVinCached_returnsFalseWhenNotCached(self):
        """
        Given: VIN does not exist in database
        When: Checking if cached
        Then: Should return False
        """
        self.mockCursor.fetchone.return_value = (0,)  # COUNT(*) = 0

        decoder = SimulatedVinDecoder(self.profile, self.config, self.mockDb)

        self.assertFalse(decoder.isVinCached("NONEXISTENT12345"))


class TestSimulatedObdConnectionVinQuery(unittest.TestCase):
    """Tests for VIN query in SimulatedObdConnection."""

    def setUp(self):
        """Set up test fixtures."""
        self.profile = VehicleProfile(
            vin="1G4HP52K45U123456",
            make="Mitsubishi",
            model="Eclipse GST",
            year=1998
        )

    def test_query_vin_returnsProfileVin(self):
        """
        Given: Connected SimulatedObdConnection
        When: Querying VIN
        Then: Should return VIN from profile
        """
        conn = SimulatedObdConnection(
            profile=self.profile,
            connectionDelaySeconds=0.0
        )
        conn.connect()

        response = conn.obd.query("VIN")

        self.assertFalse(response.is_null())
        self.assertEqual(response.value, "1G4HP52K45U123456")
        self.assertEqual(response.unit, "")

        conn.disconnect()

    def test_query_vin_caseInsensitive(self):
        """
        Given: Connected SimulatedObdConnection
        When: Querying VIN with different cases
        Then: Should return VIN for all cases
        """
        conn = SimulatedObdConnection(
            profile=self.profile,
            connectionDelaySeconds=0.0
        )
        conn.connect()

        # Test various cases
        response1 = conn.obd.query("VIN")
        response2 = conn.obd.query("vin")
        response3 = conn.obd.query("Vin")

        self.assertEqual(response1.value, "1G4HP52K45U123456")
        self.assertEqual(response2.value, "1G4HP52K45U123456")
        self.assertEqual(response3.value, "1G4HP52K45U123456")

        conn.disconnect()

    def test_query_vin_notConnected_returnsNull(self):
        """
        Given: Disconnected SimulatedObdConnection
        When: Querying VIN
        Then: Should return null response
        """
        conn = SimulatedObdConnection(
            profile=self.profile,
            connectionDelaySeconds=0.0
        )
        # Don't connect

        response = conn.obd.query("VIN")

        self.assertTrue(response.is_null())

    def test_query_vin_withCommand(self):
        """
        Given: Connected SimulatedObdConnection
        When: Querying VIN with command object
        Then: Should return VIN from profile
        """
        conn = SimulatedObdConnection(
            profile=self.profile,
            connectionDelaySeconds=0.0
        )
        conn.connect()

        # Create mock command object with .name attribute
        mockCmd = MagicMock()
        mockCmd.name = "VIN"

        response = conn.obd.query(mockCmd)

        self.assertFalse(response.is_null())
        self.assertEqual(response.value, "1G4HP52K45U123456")

        conn.disconnect()

    def test_query_rpm_stillWorks(self):
        """
        Given: Connected SimulatedObdConnection
        When: Querying RPM (not VIN)
        Then: Should return value from simulator
        """
        conn = SimulatedObdConnection(
            profile=self.profile,
            connectionDelaySeconds=0.0
        )
        conn.connect()

        response = conn.obd.query("RPM")

        self.assertFalse(response.is_null())
        # RPM should be from simulator (numeric)
        self.assertIsInstance(response.value, (int, float))
        self.assertEqual(response.unit, "rpm")

        conn.disconnect()


class TestSimulatedVinDecoderHelperFunctions(unittest.TestCase):
    """Tests for helper functions."""

    def test_createSimulatedVinDecoderFromConfig_withProfilePath(self):
        """
        Given: Config with profile path
        When: Creating decoder from config
        Then: Should load profile
        """
        # Create a temp profile file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as f:
            profile = {
                'vin': '1HGBH41JXMN109186',  # Valid VIN (no I, O, Q)
                'make': 'Toyota',
                'model': 'Camry',
                'year': 2020,
                'engineDisplacementL': 2.5,
                'cylinders': 4,
                'fuelType': 'Gasoline',
                'maxRpm': 7000,
                'redlineRpm': 6500,
                'idleRpm': 800,
                'maxSpeedKph': 240,
                'normalCoolantTempC': 90,
                'maxCoolantTempC': 120
            }
            json.dump(profile, f)
            tempPath = f.name

        try:
            config = {
                'simulator': {
                    'profilePath': tempPath
                },
                'vinDecoder': {
                    'cacheVinData': True
                }
            }

            decoder = createSimulatedVinDecoderFromConfig(config)

            self.assertEqual(decoder.profile.make, "Toyota")
            self.assertEqual(decoder.profile.model, "Camry")
        finally:
            os.unlink(tempPath)

    def test_createSimulatedVinDecoderFromConfig_noProfilePath(self):
        """
        Given: Config without profile path
        When: Creating decoder from config
        Then: Should use default profile
        """
        config = {
            'simulator': {},
            'vinDecoder': {}
        }

        decoder = createSimulatedVinDecoderFromConfig(config)

        self.assertEqual(decoder.profile.make, "Generic")
        self.assertEqual(decoder.profile.model, "Sedan")

    def test_createVinDecoderForSimulation(self):
        """
        Given: VehicleProfile
        When: Creating decoder for simulation
        Then: Should return configured decoder
        """
        profile = VehicleProfile(
            vin="1G4HP52K45U123456",
            make="Mitsubishi",
            model="Eclipse",
            year=1998
        )

        decoder = createVinDecoderForSimulation(profile)

        self.assertEqual(decoder.profile.make, "Mitsubishi")
        result = decoder.decodeVin()
        self.assertTrue(result.success)
        self.assertTrue(result.fromSimulator)

    def test_isSimulatedDecodeResult_trueForSimulated(self):
        """
        Given: SimulatedVinDecodeResult
        When: Checking if simulated
        Then: Should return True
        """
        result = SimulatedVinDecodeResult(
            vin="TEST123456789VIN",
            success=True,
            fromSimulator=True
        )

        self.assertTrue(isSimulatedDecodeResult(result))

    def test_isSimulatedDecodeResult_falseForRealResult(self):
        """
        Given: Result without fromSimulator flag
        When: Checking if simulated
        Then: Should return False
        """
        # Create a mock result without fromSimulator attribute
        mockResult = MagicMock()
        delattr(mockResult, 'fromSimulator')  # Remove the attribute

        self.assertFalse(isSimulatedDecodeResult(mockResult))


class TestStaticDataCollectorIntegration(unittest.TestCase):
    """Tests for integration with StaticDataCollector."""

    def test_staticDataCollector_queriesVinFromSimulator(self):
        """
        Given: StaticDataCollector with SimulatedObdConnection
        When: Querying VIN
        Then: Should return VIN from profile
        """
        from obd.static_data_collector import StaticDataCollector

        profile = VehicleProfile(
            vin="1G4HP52K45U123456",
            make="Mitsubishi",
            model="Eclipse",
            year=1998
        )
        conn = SimulatedObdConnection(
            profile=profile,
            connectionDelaySeconds=0.0
        )
        conn.connect()

        # Mock database
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(
            return_value=mockConn
        )
        mockDb.connect.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mockConn.cursor.return_value = mockCursor
        # Simulate VIN not in database
        mockCursor.fetchone.return_value = (0,)

        config = {
            'staticData': {
                'parameters': ['FUEL_TYPE', 'ENGINE_COOLANT_TEMP'],
                'queryOnFirstConnection': True
            }
        }

        collector = StaticDataCollector(config, conn, mockDb)

        # Query VIN directly
        vin = collector._queryVin()

        self.assertEqual(vin, "1G4HP52K45U123456")

        conn.disconnect()


class TestSimulatedResponseValueTypes(unittest.TestCase):
    """Tests for SimulatedResponse value type handling."""

    def test_response_handlesStringValue(self):
        """
        Given: String value (like VIN)
        When: Creating SimulatedResponse
        Then: Should store string correctly
        """
        response = SimulatedResponse(
            value="1G4HP52K45U123456",
            unit=""
        )

        self.assertEqual(response.value, "1G4HP52K45U123456")
        self.assertIsInstance(response.value, str)

    def test_response_handlesFloatValue(self):
        """
        Given: Float value (like RPM)
        When: Creating SimulatedResponse
        Then: Should store float correctly
        """
        response = SimulatedResponse(
            value=3500.0,
            unit="rpm"
        )

        self.assertEqual(response.value, 3500.0)
        self.assertIsInstance(response.value, float)

    def test_response_null_hasNoneValue(self):
        """
        Given: Null response
        When: Checking value
        Then: Should be None
        """
        response = SimulatedResponse.null()

        self.assertTrue(response.is_null())
        self.assertIsNone(response.value)


def runTests():
    """Run all tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestSimulatedVinDecodeResult))
    suite.addTests(loader.loadTestsFromTestCase(TestSimulatedVinDecoder))
    suite.addTests(loader.loadTestsFromTestCase(
        TestSimulatedVinDecoderWithDatabase
    ))
    suite.addTests(loader.loadTestsFromTestCase(
        TestSimulatedObdConnectionVinQuery
    ))
    suite.addTests(loader.loadTestsFromTestCase(
        TestSimulatedVinDecoderHelperFunctions
    ))
    suite.addTests(loader.loadTestsFromTestCase(
        TestStaticDataCollectorIntegration
    ))
    suite.addTests(loader.loadTestsFromTestCase(
        TestSimulatedResponseValueTypes
    ))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == '__main__':
    result = runTests()
    sys.exit(0 if result.wasSuccessful() else 1)
