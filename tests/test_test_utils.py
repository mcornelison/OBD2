################################################################################
# File Name: test_test_utils.py
# Purpose/Description: Tests for the test utilities module
# Author: Ralph Agent
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Ralph Agent. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-21    | Ralph Agent  | Initial implementation
# ================================================================================
################################################################################

"""Tests for test_utils module."""

import os
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.test_utils import (
    createTestConfig,
    createTestRecord,
    createTestRecords,
    assertDictSubset,
    assertRaisesWithMessage,
    assertWithinRange,
    temporaryEnvVars,
    temporaryFile,
    temporaryJsonFile,
    captureTime,
    createMockResponse,
    createMockCursor,
    createMockConnection,
    waitForCondition,
    retry,
    TestDataManager,
)


# ================================================================================
# Test Data Factory Tests
# ================================================================================

class TestCreateTestConfig:
    """Tests for createTestConfig factory."""

    def test_createTestConfig_noOverrides_returnsBaseConfig(self):
        """
        Given: No overrides provided
        When: createTestConfig is called
        Then: Returns base configuration with default values
        """
        config = createTestConfig()

        assert config['application']['name'] == 'TestApp'
        assert config['database']['server'] == 'localhost'
        assert config['api']['baseUrl'] == 'https://api.test.com'

    def test_createTestConfig_withOverrides_mergesCorrectly(self):
        """
        Given: Override values for nested keys
        When: createTestConfig is called with overrides
        Then: Base values are preserved, overrides are applied
        """
        config = createTestConfig({
            'database': {'port': 5432},
            'api': {'timeout': 60}
        })

        assert config['database']['port'] == 5432
        assert config['database']['server'] == 'localhost'  # preserved
        assert config['api']['timeout'] == 60

    def test_createTestConfig_newTopLevelKey_addsKey(self):
        """
        Given: New top-level key in overrides
        When: createTestConfig is called
        Then: New key is added to config
        """
        config = createTestConfig({'custom': {'setting': 'value'}})

        assert config['custom']['setting'] == 'value'


class TestCreateTestRecord:
    """Tests for createTestRecord factory."""

    def test_createTestRecord_defaults_returnsValidRecord(self):
        """
        Given: No parameters
        When: createTestRecord is called
        Then: Returns record with default values
        """
        record = createTestRecord()

        assert record['id'] == 1
        assert record['name'] == 'Test Record'
        assert record['isActive'] is True

    def test_createTestRecord_customValues_appliesValues(self):
        """
        Given: Custom id and name
        When: createTestRecord is called with custom values
        Then: Custom values are used
        """
        record = createTestRecord(recordId=42, name='Custom Record')

        assert record['id'] == 42
        assert record['name'] == 'Custom Record'

    def test_createTestRecord_extraFields_addsFields(self):
        """
        Given: Extra keyword arguments
        When: createTestRecord is called with extra fields
        Then: Extra fields are added to record
        """
        record = createTestRecord(customField='custom_value', count=5)

        assert record['customField'] == 'custom_value'
        assert record['count'] == 5


class TestCreateTestRecords:
    """Tests for createTestRecords factory."""

    def test_createTestRecords_countThree_returnsThreeRecords(self):
        """
        Given: Count of 3
        When: createTestRecords is called
        Then: Returns list of 3 records with sequential IDs
        """
        records = createTestRecords(3)

        assert len(records) == 3
        assert records[0]['id'] == 1
        assert records[1]['id'] == 2
        assert records[2]['id'] == 3

    def test_createTestRecords_customPrefix_usesPrefix(self):
        """
        Given: Custom name prefix
        When: createTestRecords is called with prefix
        Then: Records use the custom prefix
        """
        records = createTestRecords(2, namePrefix='Item')

        assert records[0]['name'] == 'Item 1'
        assert records[1]['name'] == 'Item 2'


# ================================================================================
# Assertion Helper Tests
# ================================================================================

class TestAssertDictSubset:
    """Tests for assertDictSubset helper."""

    def test_assertDictSubset_validSubset_passes(self):
        """
        Given: Subset is contained in superset
        When: assertDictSubset is called
        Then: No exception is raised
        """
        subset = {'a': 1, 'b': 2}
        superset = {'a': 1, 'b': 2, 'c': 3}

        assertDictSubset(subset, superset)  # Should not raise

    def test_assertDictSubset_nestedSubset_passes(self):
        """
        Given: Nested subset is contained in superset
        When: assertDictSubset is called
        Then: No exception is raised
        """
        subset = {'outer': {'inner': 'value'}}
        superset = {'outer': {'inner': 'value', 'other': 'data'}}

        assertDictSubset(subset, superset)  # Should not raise

    def test_assertDictSubset_missingKey_raises(self):
        """
        Given: Subset has key not in superset
        When: assertDictSubset is called
        Then: AssertionError is raised
        """
        subset = {'a': 1, 'missing': 2}
        superset = {'a': 1}

        with pytest.raises(AssertionError, match="Key 'missing' not found"):
            assertDictSubset(subset, superset)

    def test_assertDictSubset_valueMismatch_raises(self):
        """
        Given: Subset has different value
        When: assertDictSubset is called
        Then: AssertionError is raised
        """
        subset = {'a': 1}
        superset = {'a': 2}

        with pytest.raises(AssertionError, match="Value mismatch"):
            assertDictSubset(subset, superset)


class TestAssertRaisesWithMessage:
    """Tests for assertRaisesWithMessage helper."""

    def test_assertRaisesWithMessage_matchingException_passes(self):
        """
        Given: Function raises expected exception with message
        When: assertRaisesWithMessage is called
        Then: No exception is raised
        """
        def raiseError():
            raise ValueError("Expected error message")

        assertRaisesWithMessage(ValueError, "Expected", raiseError)

    def test_assertRaisesWithMessage_noException_raises(self):
        """
        Given: Function does not raise exception
        When: assertRaisesWithMessage is called
        Then: AssertionError is raised
        """
        def noError():
            return "success"

        with pytest.raises(AssertionError, match="was not raised"):
            assertRaisesWithMessage(ValueError, "any", noError)

    def test_assertRaisesWithMessage_wrongMessage_raises(self):
        """
        Given: Exception raised but message doesn't match
        When: assertRaisesWithMessage is called
        Then: AssertionError is raised
        """
        def raiseError():
            raise ValueError("Different message")

        with pytest.raises(AssertionError, match="Expected message to contain"):
            assertRaisesWithMessage(ValueError, "expected text", raiseError)


class TestAssertWithinRange:
    """Tests for assertWithinRange helper."""

    def test_assertWithinRange_withinRange_passes(self):
        """
        Given: Value within range
        When: assertWithinRange is called
        Then: No exception is raised
        """
        assertWithinRange(5, 0, 10)  # Should not raise

    def test_assertWithinRange_atBoundary_passes(self):
        """
        Given: Value at range boundaries
        When: assertWithinRange is called
        Then: No exception is raised (inclusive)
        """
        assertWithinRange(0, 0, 10)  # Should not raise
        assertWithinRange(10, 0, 10)  # Should not raise

    def test_assertWithinRange_outsideRange_raises(self):
        """
        Given: Value outside range
        When: assertWithinRange is called
        Then: AssertionError is raised
        """
        with pytest.raises(AssertionError, match="not in range"):
            assertWithinRange(15, 0, 10)


# ================================================================================
# Context Manager Tests
# ================================================================================

class TestTemporaryEnvVars:
    """Tests for temporaryEnvVars context manager."""

    def test_temporaryEnvVars_setsVariables(self):
        """
        Given: Environment variables to set
        When: Inside context manager
        Then: Variables are accessible
        """
        with temporaryEnvVars(TEST_VAR='test_value'):
            assert os.environ.get('TEST_VAR') == 'test_value'

    def test_temporaryEnvVars_restoresAfterContext(self):
        """
        Given: Environment variable set temporarily
        When: Context exits
        Then: Variable is removed
        """
        assert os.environ.get('TEST_CLEANUP_VAR') is None

        with temporaryEnvVars(TEST_CLEANUP_VAR='temp'):
            assert os.environ.get('TEST_CLEANUP_VAR') == 'temp'

        assert os.environ.get('TEST_CLEANUP_VAR') is None

    def test_temporaryEnvVars_preservesExisting(self):
        """
        Given: Existing environment variable
        When: Temporarily overwritten
        Then: Original value is restored
        """
        os.environ['EXISTING_VAR'] = 'original'
        try:
            with temporaryEnvVars(EXISTING_VAR='temporary'):
                assert os.environ.get('EXISTING_VAR') == 'temporary'

            assert os.environ.get('EXISTING_VAR') == 'original'
        finally:
            os.environ.pop('EXISTING_VAR', None)


class TestTemporaryFile:
    """Tests for temporaryFile context manager."""

    def test_temporaryFile_createsFileWithContent(self):
        """
        Given: Content string
        When: Inside context manager
        Then: File exists with correct content
        """
        with temporaryFile("test content", suffix=".txt") as path:
            assert path.exists()
            assert path.read_text() == "test content"

    def test_temporaryFile_deletesAfterContext(self):
        """
        Given: Temporary file created
        When: Context exits
        Then: File is deleted
        """
        with temporaryFile("content") as path:
            tempPath = path

        assert not tempPath.exists()


class TestTemporaryJsonFile:
    """Tests for temporaryJsonFile context manager."""

    def test_temporaryJsonFile_createsValidJson(self):
        """
        Given: Dictionary data
        When: Inside context manager
        Then: File contains valid JSON
        """
        data = {'key': 'value', 'number': 42}

        with temporaryJsonFile(data) as path:
            assert path.suffix == '.json'
            loaded = json.loads(path.read_text())
            assert loaded == data


class TestCaptureTime:
    """Tests for captureTime context manager."""

    def test_captureTime_measuresElapsed(self):
        """
        Given: Code that takes time
        When: captureTime is used
        Then: Elapsed time is captured
        """
        with captureTime() as timing:
            time.sleep(0.01)  # 10ms

        assert timing['elapsed'] >= 0.01


# ================================================================================
# Mock Helper Tests
# ================================================================================

class TestCreateMockResponse:
    """Tests for createMockResponse helper."""

    def test_createMockResponse_defaults_returns200(self):
        """
        Given: No parameters
        When: createMockResponse is called
        Then: Returns mock with 200 status
        """
        mock = createMockResponse()

        assert mock.status_code == 200
        assert mock.json() == {}

    def test_createMockResponse_withData_returnsData(self):
        """
        Given: JSON data
        When: createMockResponse is called
        Then: json() returns the data
        """
        data = {'items': [1, 2, 3]}
        mock = createMockResponse(jsonData=data)

        assert mock.json() == data

    def test_createMockResponse_errorWithRaise_raisesOnCheck(self):
        """
        Given: Error status and raiseForStatus=True
        When: raise_for_status is called
        Then: Exception is raised
        """
        mock = createMockResponse(statusCode=500, raiseForStatus=True)

        with pytest.raises(Exception, match="HTTP 500"):
            mock.raise_for_status()


class TestCreateMockCursor:
    """Tests for createMockCursor helper."""

    def test_createMockCursor_defaults_returnsEmptyResults(self):
        """
        Given: No parameters
        When: createMockCursor is called
        Then: Returns cursor with empty results
        """
        cursor = createMockCursor()

        assert cursor.fetchall() == []
        assert cursor.fetchone() is None
        assert cursor.rowcount == 0

    def test_createMockCursor_withData_returnsData(self):
        """
        Given: fetchall and fetchone data
        When: createMockCursor is called
        Then: Returns data correctly
        """
        cursor = createMockCursor(
            fetchallResult=[{'id': 1}, {'id': 2}],
            fetchoneResult={'id': 1},
            rowcount=2
        )

        assert len(cursor.fetchall()) == 2
        assert cursor.fetchone()['id'] == 1
        assert cursor.rowcount == 2


class TestCreateMockConnection:
    """Tests for createMockConnection helper."""

    def test_createMockConnection_contextManager_works(self):
        """
        Given: Mock connection
        When: Used as context manager for cursor
        Then: Cursor is accessible
        """
        cursor = createMockCursor(rowcount=5)
        connection = createMockConnection(cursor)

        with connection.cursor() as c:
            assert c.rowcount == 5


# ================================================================================
# Retry and Wait Helper Tests
# ================================================================================

class TestWaitForCondition:
    """Tests for waitForCondition helper."""

    def test_waitForCondition_immediatelyTrue_returnsQuickly(self):
        """
        Given: Condition that is immediately true
        When: waitForCondition is called
        Then: Returns without delay
        """
        with captureTime() as timing:
            waitForCondition(lambda: True)

        assert timing['elapsed'] < 0.1

    def test_waitForCondition_eventuallyTrue_waits(self):
        """
        Given: Condition that becomes true
        When: waitForCondition is called
        Then: Waits until condition is true
        """
        counter = {'value': 0}

        def condition():
            counter['value'] += 1
            return counter['value'] >= 3

        waitForCondition(condition, timeoutSeconds=1.0, pollIntervalSeconds=0.01)
        assert counter['value'] >= 3

    def test_waitForCondition_timeout_raises(self):
        """
        Given: Condition that never becomes true
        When: waitForCondition times out
        Then: TimeoutError is raised
        """
        with pytest.raises(TimeoutError):
            waitForCondition(lambda: False, timeoutSeconds=0.05)


class TestRetry:
    """Tests for retry helper."""

    def test_retry_immediateSuccess_returnsResult(self):
        """
        Given: Function that succeeds immediately
        When: retry is called
        Then: Returns result
        """
        result = retry(lambda: 'success')
        assert result == 'success'

    def test_retry_eventualSuccess_retries(self):
        """
        Given: Function that fails then succeeds
        When: retry is called
        Then: Retries until success
        """
        attempts = {'count': 0}

        def failThenSucceed():
            attempts['count'] += 1
            if attempts['count'] < 3:
                raise ValueError("Not yet")
            return 'success'

        result = retry(failThenSucceed, maxAttempts=5, delaySeconds=0.01)
        assert result == 'success'
        assert attempts['count'] == 3

    def test_retry_allFail_raisesLastException(self):
        """
        Given: Function that always fails
        When: retry exhausts attempts
        Then: Raises last exception
        """
        def alwaysFail():
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            retry(alwaysFail, maxAttempts=2, delaySeconds=0.01)


# ================================================================================
# TestDataManager Tests
# ================================================================================

class TestTestDataManager:
    """Tests for TestDataManager class."""

    def test_testDataManager_envVarCleanup(self):
        """
        Given: Environment variable set via manager
        When: Manager cleanup is called
        Then: Variable is removed
        """
        with TestDataManager() as manager:
            manager.setEnvVar('MANAGER_TEST_VAR', 'test_value')
            assert os.environ.get('MANAGER_TEST_VAR') == 'test_value'

        assert os.environ.get('MANAGER_TEST_VAR') is None

    def test_testDataManager_fileCleanup(self, tmp_path):
        """
        Given: File tracked by manager
        When: Manager cleanup is called
        Then: File is deleted
        """
        testFile = tmp_path / 'test.txt'
        testFile.write_text('test')

        with TestDataManager() as manager:
            manager.addFile(testFile)
            assert testFile.exists()

        assert not testFile.exists()

    def test_testDataManager_restoresOriginalEnvVar(self):
        """
        Given: Existing environment variable
        When: Temporarily overwritten via manager
        Then: Original value is restored
        """
        os.environ['MANAGER_EXISTING'] = 'original'
        try:
            with TestDataManager() as manager:
                manager.setEnvVar('MANAGER_EXISTING', 'new_value')
                assert os.environ.get('MANAGER_EXISTING') == 'new_value'

            assert os.environ.get('MANAGER_EXISTING') == 'original'
        finally:
            os.environ.pop('MANAGER_EXISTING', None)
