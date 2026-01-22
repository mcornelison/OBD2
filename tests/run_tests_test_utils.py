#!/usr/bin/env python
################################################################################
# File Name: run_tests_test_utils.py
# Purpose/Description: Manual test runner for test utilities tests
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
################################################################################

"""
Manual test runner for test_utils module tests.

Run with:
    python run_tests_test_utils.py
"""

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest.mock import MagicMock

# Add tests to path (current directory since this file is in tests/)
testsPath = Path(__file__).parent
sys.path.insert(0, str(testsPath))

from test_utils import (
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

# Test counters
passedTests = 0
failedTests = 0
failedTestNames = []


def runTest(testName, testFunc):
    """Run a test and track results."""
    global passedTests, failedTests, failedTestNames
    try:
        testFunc()
        passedTests += 1
        print(f"  [PASS] {testName}")
    except AssertionError as e:
        failedTests += 1
        failedTestNames.append(testName)
        print(f"  [FAIL] {testName}: {e}")
    except Exception as e:
        failedTests += 1
        failedTestNames.append(testName)
        print(f"  [ERROR] {testName}: {e}")
        traceback.print_exc()


# ================================================================================
# Test Data Factory Tests
# ================================================================================

def test_createTestConfig_noOverrides_returnsBaseConfig():
    """Test default config values."""
    config = createTestConfig()
    assert config['application']['name'] == 'TestApp', "Expected 'TestApp'"
    assert config['database']['server'] == 'localhost', "Expected 'localhost'"
    assert config['api']['baseUrl'] == 'https://api.test.com', "Expected API URL"


def test_createTestConfig_withOverrides_mergesCorrectly():
    """Test overrides are merged correctly."""
    config = createTestConfig({
        'database': {'port': 5432},
        'api': {'timeout': 60}
    })
    assert config['database']['port'] == 5432, f"Expected 5432, got {config['database']['port']}"
    assert config['database']['server'] == 'localhost', "Original value should be preserved"
    assert config['api']['timeout'] == 60, f"Expected 60, got {config['api']['timeout']}"


def test_createTestConfig_newTopLevelKey_addsKey():
    """Test new top-level keys are added."""
    config = createTestConfig({'custom': {'setting': 'value'}})
    assert config['custom']['setting'] == 'value', "Custom key should be added"


def test_createTestRecord_defaults_returnsValidRecord():
    """Test default record values."""
    record = createTestRecord()
    assert record['id'] == 1, "Expected id=1"
    assert record['name'] == 'Test Record', "Expected default name"
    assert record['isActive'] is True, "Expected isActive=True"


def test_createTestRecord_customValues_appliesValues():
    """Test custom record values."""
    record = createTestRecord(recordId=42, name='Custom Record')
    assert record['id'] == 42, f"Expected 42, got {record['id']}"
    assert record['name'] == 'Custom Record', f"Expected 'Custom Record', got {record['name']}"


def test_createTestRecord_extraFields_addsFields():
    """Test extra fields are added."""
    record = createTestRecord(customField='custom_value', count=5)
    assert record['customField'] == 'custom_value', "Custom field should be added"
    assert record['count'] == 5, "Count field should be added"


def test_createTestRecords_countThree_returnsThreeRecords():
    """Test creating multiple records."""
    records = createTestRecords(3)
    assert len(records) == 3, f"Expected 3 records, got {len(records)}"
    assert records[0]['id'] == 1, "First record should have id=1"
    assert records[2]['id'] == 3, "Last record should have id=3"


def test_createTestRecords_customPrefix_usesPrefix():
    """Test custom name prefix."""
    records = createTestRecords(2, namePrefix='Item')
    assert records[0]['name'] == 'Item 1', f"Expected 'Item 1', got {records[0]['name']}"
    assert records[1]['name'] == 'Item 2', f"Expected 'Item 2', got {records[1]['name']}"


# ================================================================================
# Assertion Helper Tests
# ================================================================================

def test_assertDictSubset_validSubset_passes():
    """Test valid subset doesn't raise."""
    subset = {'a': 1, 'b': 2}
    superset = {'a': 1, 'b': 2, 'c': 3}
    assertDictSubset(subset, superset)  # Should not raise


def test_assertDictSubset_nestedSubset_passes():
    """Test nested subset doesn't raise."""
    subset = {'outer': {'inner': 'value'}}
    superset = {'outer': {'inner': 'value', 'other': 'data'}}
    assertDictSubset(subset, superset)  # Should not raise


def test_assertDictSubset_missingKey_raises():
    """Test missing key raises AssertionError."""
    subset = {'a': 1, 'missing': 2}
    superset = {'a': 1}
    try:
        assertDictSubset(subset, superset)
        assert False, "Should have raised AssertionError"
    except AssertionError as e:
        assert 'missing' in str(e), f"Error should mention 'missing': {e}"


def test_assertDictSubset_valueMismatch_raises():
    """Test value mismatch raises AssertionError."""
    subset = {'a': 1}
    superset = {'a': 2}
    try:
        assertDictSubset(subset, superset)
        assert False, "Should have raised AssertionError"
    except AssertionError as e:
        assert 'mismatch' in str(e).lower(), f"Error should mention mismatch: {e}"


def test_assertRaisesWithMessage_matchingException_passes():
    """Test matching exception doesn't raise."""
    def raiseError():
        raise ValueError("Expected error message")
    assertRaisesWithMessage(ValueError, "Expected", raiseError)


def test_assertRaisesWithMessage_noException_raises():
    """Test no exception raises AssertionError."""
    def noError():
        return "success"
    try:
        assertRaisesWithMessage(ValueError, "any", noError)
        assert False, "Should have raised AssertionError"
    except AssertionError as e:
        assert 'not raised' in str(e).lower(), f"Error should mention not raised: {e}"


def test_assertRaisesWithMessage_wrongMessage_raises():
    """Test wrong message raises AssertionError."""
    def raiseError():
        raise ValueError("Different message")
    try:
        assertRaisesWithMessage(ValueError, "expected text", raiseError)
        assert False, "Should have raised AssertionError"
    except AssertionError as e:
        assert 'contain' in str(e).lower(), f"Error should mention contain: {e}"


def test_assertWithinRange_withinRange_passes():
    """Test value within range doesn't raise."""
    assertWithinRange(5, 0, 10)  # Should not raise


def test_assertWithinRange_atBoundary_passes():
    """Test value at boundary doesn't raise."""
    assertWithinRange(0, 0, 10)  # Should not raise
    assertWithinRange(10, 0, 10)  # Should not raise


def test_assertWithinRange_outsideRange_raises():
    """Test value outside range raises AssertionError."""
    try:
        assertWithinRange(15, 0, 10)
        assert False, "Should have raised AssertionError"
    except AssertionError as e:
        assert 'not in range' in str(e).lower(), f"Error should mention range: {e}"


# ================================================================================
# Context Manager Tests
# ================================================================================

def test_temporaryEnvVars_setsVariables():
    """Test environment variables are set."""
    with temporaryEnvVars(TEST_VAR='test_value'):
        assert os.environ.get('TEST_VAR') == 'test_value', "Var should be set"


def test_temporaryEnvVars_restoresAfterContext():
    """Test variables are removed after context."""
    assert os.environ.get('TEST_CLEANUP_VAR') is None, "Should not exist before"
    with temporaryEnvVars(TEST_CLEANUP_VAR='temp'):
        assert os.environ.get('TEST_CLEANUP_VAR') == 'temp', "Should exist in context"
    assert os.environ.get('TEST_CLEANUP_VAR') is None, "Should be removed after"


def test_temporaryEnvVars_preservesExisting():
    """Test existing variables are restored."""
    os.environ['EXISTING_VAR'] = 'original'
    try:
        with temporaryEnvVars(EXISTING_VAR='temporary'):
            assert os.environ.get('EXISTING_VAR') == 'temporary', "Should be overwritten"
        assert os.environ.get('EXISTING_VAR') == 'original', "Should be restored"
    finally:
        os.environ.pop('EXISTING_VAR', None)


def test_temporaryFile_createsFileWithContent():
    """Test file is created with content."""
    with temporaryFile("test content", suffix=".txt") as path:
        assert path.exists(), "File should exist"
        assert path.read_text() == "test content", "Content should match"


def test_temporaryFile_deletesAfterContext():
    """Test file is deleted after context."""
    with temporaryFile("content") as path:
        tempPath = path
    assert not tempPath.exists(), "File should be deleted"


def test_temporaryJsonFile_createsValidJson():
    """Test JSON file is created correctly."""
    data = {'key': 'value', 'number': 42}
    with temporaryJsonFile(data) as path:
        assert path.suffix == '.json', "Should have .json suffix"
        loaded = json.loads(path.read_text())
        assert loaded == data, f"Data should match: {loaded}"


def test_captureTime_measuresElapsed():
    """Test elapsed time is captured."""
    with captureTime() as timing:
        time.sleep(0.01)  # 10ms
    assert timing['elapsed'] >= 0.01, f"Should be >= 0.01, got {timing['elapsed']}"


# ================================================================================
# Mock Helper Tests
# ================================================================================

def test_createMockResponse_defaults_returns200():
    """Test default response is 200."""
    mock = createMockResponse()
    assert mock.status_code == 200, f"Expected 200, got {mock.status_code}"
    assert mock.json() == {}, "Should return empty dict"


def test_createMockResponse_withData_returnsData():
    """Test data is returned correctly."""
    data = {'items': [1, 2, 3]}
    mock = createMockResponse(jsonData=data)
    assert mock.json() == data, f"Data should match: {mock.json()}"


def test_createMockResponse_errorWithRaise_raisesOnCheck():
    """Test error response raises on check."""
    mock = createMockResponse(statusCode=500, raiseForStatus=True)
    try:
        mock.raise_for_status()
        assert False, "Should have raised exception"
    except Exception as e:
        assert '500' in str(e), f"Should mention status code: {e}"


def test_createMockCursor_defaults_returnsEmptyResults():
    """Test default cursor returns empty results."""
    cursor = createMockCursor()
    assert cursor.fetchall() == [], "fetchall should return []"
    assert cursor.fetchone() is None, "fetchone should return None"
    assert cursor.rowcount == 0, "rowcount should be 0"


def test_createMockCursor_withData_returnsData():
    """Test cursor returns provided data."""
    cursor = createMockCursor(
        fetchallResult=[{'id': 1}, {'id': 2}],
        fetchoneResult={'id': 1},
        rowcount=2
    )
    assert len(cursor.fetchall()) == 2, "Should have 2 results"
    assert cursor.fetchone()['id'] == 1, "fetchone should return first record"
    assert cursor.rowcount == 2, "rowcount should be 2"


def test_createMockConnection_contextManager_works():
    """Test connection works as context manager."""
    cursor = createMockCursor(rowcount=5)
    connection = createMockConnection(cursor)
    with connection.cursor() as c:
        assert c.rowcount == 5, f"rowcount should be 5, got {c.rowcount}"


# ================================================================================
# Retry and Wait Helper Tests
# ================================================================================

def test_waitForCondition_immediatelyTrue_returnsQuickly():
    """Test immediate true returns quickly."""
    with captureTime() as timing:
        waitForCondition(lambda: True)
    assert timing['elapsed'] < 0.1, f"Should be quick, took {timing['elapsed']}"


def test_waitForCondition_eventuallyTrue_waits():
    """Test waits until condition is true."""
    counter = {'value': 0}

    def condition():
        counter['value'] += 1
        return counter['value'] >= 3

    waitForCondition(condition, timeoutSeconds=1.0, pollIntervalSeconds=0.01)
    assert counter['value'] >= 3, f"Should have checked at least 3 times: {counter['value']}"


def test_waitForCondition_timeout_raises():
    """Test timeout raises TimeoutError."""
    try:
        waitForCondition(lambda: False, timeoutSeconds=0.05)
        assert False, "Should have raised TimeoutError"
    except TimeoutError:
        pass  # Expected


def test_retry_immediateSuccess_returnsResult():
    """Test immediate success returns result."""
    result = retry(lambda: 'success')
    assert result == 'success', f"Expected 'success', got {result}"


def test_retry_eventualSuccess_retries():
    """Test retries until success."""
    attempts = {'count': 0}

    def failThenSucceed():
        attempts['count'] += 1
        if attempts['count'] < 3:
            raise ValueError("Not yet")
        return 'success'

    result = retry(failThenSucceed, maxAttempts=5, delaySeconds=0.01)
    assert result == 'success', f"Expected 'success', got {result}"
    assert attempts['count'] == 3, f"Should have taken 3 attempts: {attempts['count']}"


def test_retry_allFail_raisesLastException():
    """Test raises last exception on all failures."""
    def alwaysFail():
        raise ValueError("Always fails")

    try:
        retry(alwaysFail, maxAttempts=2, delaySeconds=0.01)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert 'Always fails' in str(e), f"Should have original message: {e}"


# ================================================================================
# TestDataManager Tests
# ================================================================================

def test_testDataManager_envVarCleanup():
    """Test environment variable cleanup."""
    with TestDataManager() as manager:
        manager.setEnvVar('MANAGER_TEST_VAR', 'test_value')
        assert os.environ.get('MANAGER_TEST_VAR') == 'test_value', "Var should be set"
    assert os.environ.get('MANAGER_TEST_VAR') is None, "Var should be removed"


def test_testDataManager_fileCleanup():
    """Test file cleanup."""
    with tempfile.TemporaryDirectory() as tmpDir:
        testFile = Path(tmpDir) / 'test.txt'
        testFile.write_text('test')

        with TestDataManager() as manager:
            manager.addFile(testFile)
            assert testFile.exists(), "File should exist in context"

        assert not testFile.exists(), "File should be deleted after"


def test_testDataManager_restoresOriginalEnvVar():
    """Test original environment variable is restored."""
    os.environ['MANAGER_EXISTING'] = 'original'
    try:
        with TestDataManager() as manager:
            manager.setEnvVar('MANAGER_EXISTING', 'new_value')
            assert os.environ.get('MANAGER_EXISTING') == 'new_value', "Should be overwritten"
        assert os.environ.get('MANAGER_EXISTING') == 'original', "Should be restored"
    finally:
        os.environ.pop('MANAGER_EXISTING', None)


# ================================================================================
# Main Test Runner
# ================================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("Running test_utils.py tests")
    print("=" * 60)

    print("\nTest Data Factory Tests:")
    runTest("createTestConfig_noOverrides_returnsBaseConfig", test_createTestConfig_noOverrides_returnsBaseConfig)
    runTest("createTestConfig_withOverrides_mergesCorrectly", test_createTestConfig_withOverrides_mergesCorrectly)
    runTest("createTestConfig_newTopLevelKey_addsKey", test_createTestConfig_newTopLevelKey_addsKey)
    runTest("createTestRecord_defaults_returnsValidRecord", test_createTestRecord_defaults_returnsValidRecord)
    runTest("createTestRecord_customValues_appliesValues", test_createTestRecord_customValues_appliesValues)
    runTest("createTestRecord_extraFields_addsFields", test_createTestRecord_extraFields_addsFields)
    runTest("createTestRecords_countThree_returnsThreeRecords", test_createTestRecords_countThree_returnsThreeRecords)
    runTest("createTestRecords_customPrefix_usesPrefix", test_createTestRecords_customPrefix_usesPrefix)

    print("\nAssertion Helper Tests:")
    runTest("assertDictSubset_validSubset_passes", test_assertDictSubset_validSubset_passes)
    runTest("assertDictSubset_nestedSubset_passes", test_assertDictSubset_nestedSubset_passes)
    runTest("assertDictSubset_missingKey_raises", test_assertDictSubset_missingKey_raises)
    runTest("assertDictSubset_valueMismatch_raises", test_assertDictSubset_valueMismatch_raises)
    runTest("assertRaisesWithMessage_matchingException_passes", test_assertRaisesWithMessage_matchingException_passes)
    runTest("assertRaisesWithMessage_noException_raises", test_assertRaisesWithMessage_noException_raises)
    runTest("assertRaisesWithMessage_wrongMessage_raises", test_assertRaisesWithMessage_wrongMessage_raises)
    runTest("assertWithinRange_withinRange_passes", test_assertWithinRange_withinRange_passes)
    runTest("assertWithinRange_atBoundary_passes", test_assertWithinRange_atBoundary_passes)
    runTest("assertWithinRange_outsideRange_raises", test_assertWithinRange_outsideRange_raises)

    print("\nContext Manager Tests:")
    runTest("temporaryEnvVars_setsVariables", test_temporaryEnvVars_setsVariables)
    runTest("temporaryEnvVars_restoresAfterContext", test_temporaryEnvVars_restoresAfterContext)
    runTest("temporaryEnvVars_preservesExisting", test_temporaryEnvVars_preservesExisting)
    runTest("temporaryFile_createsFileWithContent", test_temporaryFile_createsFileWithContent)
    runTest("temporaryFile_deletesAfterContext", test_temporaryFile_deletesAfterContext)
    runTest("temporaryJsonFile_createsValidJson", test_temporaryJsonFile_createsValidJson)
    runTest("captureTime_measuresElapsed", test_captureTime_measuresElapsed)

    print("\nMock Helper Tests:")
    runTest("createMockResponse_defaults_returns200", test_createMockResponse_defaults_returns200)
    runTest("createMockResponse_withData_returnsData", test_createMockResponse_withData_returnsData)
    runTest("createMockResponse_errorWithRaise_raisesOnCheck", test_createMockResponse_errorWithRaise_raisesOnCheck)
    runTest("createMockCursor_defaults_returnsEmptyResults", test_createMockCursor_defaults_returnsEmptyResults)
    runTest("createMockCursor_withData_returnsData", test_createMockCursor_withData_returnsData)
    runTest("createMockConnection_contextManager_works", test_createMockConnection_contextManager_works)

    print("\nRetry and Wait Helper Tests:")
    runTest("waitForCondition_immediatelyTrue_returnsQuickly", test_waitForCondition_immediatelyTrue_returnsQuickly)
    runTest("waitForCondition_eventuallyTrue_waits", test_waitForCondition_eventuallyTrue_waits)
    runTest("waitForCondition_timeout_raises", test_waitForCondition_timeout_raises)
    runTest("retry_immediateSuccess_returnsResult", test_retry_immediateSuccess_returnsResult)
    runTest("retry_eventualSuccess_retries", test_retry_eventualSuccess_retries)
    runTest("retry_allFail_raisesLastException", test_retry_allFail_raisesLastException)

    print("\nTestDataManager Tests:")
    runTest("testDataManager_envVarCleanup", test_testDataManager_envVarCleanup)
    runTest("testDataManager_fileCleanup", test_testDataManager_fileCleanup)
    runTest("testDataManager_restoresOriginalEnvVar", test_testDataManager_restoresOriginalEnvVar)

    print("\n" + "=" * 60)
    print(f"Results: {passedTests} passed, {failedTests} failed")
    print("=" * 60)

    if failedTestNames:
        print("\nFailed tests:")
        for name in failedTestNames:
            print(f"  - {name}")
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)
