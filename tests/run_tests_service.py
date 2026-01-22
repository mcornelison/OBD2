#!/usr/bin/env python3
################################################################################
# File Name: run_tests_service.py
# Purpose/Description: Test runner for service module (US-006)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation
# ================================================================================
################################################################################

"""
Manual test runner for the service module.

This allows running tests without requiring pytest to be installed.
Run with: python tests/run_tests_service.py
"""

import os
import sys
import tempfile
import shutil
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime

# Add src to path
srcPath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src')
if srcPath not in sys.path:
    sys.path.insert(0, srcPath)

from obd.service import (
    ServiceManager,
    ServiceConfig,
    ServiceStatus,
    ServiceError,
    ServiceInstallError,
    ServiceNotInstalledError,
    ServiceCommandError,
    createServiceManagerFromConfig,
    generateInstallScript,
    generateUninstallScript,
    SERVICE_TEMPLATE,
    DEFAULT_SERVICE_NAME,
    DEFAULT_SERVICE_DIR,
    DEFAULT_INSTALL_DIR,
)


class TestResult:
    """Simple test result tracker."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def addPass(self, name):
        self.passed += 1
        print(f"  [PASS] {name}")

    def addFail(self, name, reason):
        self.failed += 1
        self.errors.append((name, reason))
        print(f"  [FAIL] {name}: {reason}")


def assertEqual(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def assertTrue(value, msg=""):
    if not value:
        raise AssertionError(f"{msg}: expected True, got {value!r}")


def assertFalse(value, msg=""):
    if value:
        raise AssertionError(f"{msg}: expected False, got {value!r}")


def assertIn(item, container, msg=""):
    if item not in container:
        raise AssertionError(f"{msg}: {item!r} not in {container!r}")


def assertIsNotNone(value, msg=""):
    if value is None:
        raise AssertionError(f"{msg}: expected not None, got None")


def assertIsInstance(obj, classOrTuple, msg=""):
    if not isinstance(obj, classOrTuple):
        raise AssertionError(
            f"{msg}: expected instance of {classOrTuple}, got {type(obj)}"
        )


# ==============================================================================
# ServiceConfig Tests
# ==============================================================================

def testServiceConfigDefaults(result):
    """Test ServiceConfig has correct default values."""
    try:
        config = ServiceConfig()

        assertEqual(config.serviceName, DEFAULT_SERVICE_NAME, "serviceName default")
        assertEqual(config.user, "pi", "user default")
        assertEqual(config.group, "pi", "group default")
        assertEqual(config.workingDir, DEFAULT_INSTALL_DIR, "workingDir default")
        assertEqual(config.pythonPath, "/usr/bin/python3", "pythonPath default")
        assertEqual(config.mainScript, "src/main.py", "mainScript default")
        assertEqual(config.envFile, ".env", "envFile default")
        assertEqual(config.restartDelaySeconds, 10, "restartDelaySeconds default")
        assertEqual(config.maxRestartAttempts, 5, "maxRestartAttempts default")
        assertEqual(config.restartIntervalSeconds, 300, "restartIntervalSeconds default")

        result.addPass("testServiceConfigDefaults")
    except AssertionError as e:
        result.addFail("testServiceConfigDefaults", str(e))


def testServiceConfigCustomValues(result):
    """Test ServiceConfig with custom values."""
    try:
        config = ServiceConfig(
            serviceName="custom-service",
            user="root",
            group="root",
            workingDir="/custom/path",
            pythonPath="/usr/local/bin/python3",
            mainScript="app/main.py",
            envFile=".env.production",
            restartDelaySeconds=5,
            maxRestartAttempts=3,
            restartIntervalSeconds=600
        )

        assertEqual(config.serviceName, "custom-service", "custom serviceName")
        assertEqual(config.user, "root", "custom user")
        assertEqual(config.maxRestartAttempts, 3, "custom maxRestartAttempts")

        result.addPass("testServiceConfigCustomValues")
    except AssertionError as e:
        result.addFail("testServiceConfigCustomValues", str(e))


def testServiceConfigToDict(result):
    """Test ServiceConfig toDict method."""
    try:
        config = ServiceConfig()
        d = config.toDict()

        assertIsInstance(d, dict, "toDict returns dict")
        assertIn('serviceName', d, "has serviceName")
        assertIn('user', d, "has user")
        assertIn('maxRestartAttempts', d, "has maxRestartAttempts")
        assertEqual(d['serviceName'], DEFAULT_SERVICE_NAME, "serviceName in dict")

        result.addPass("testServiceConfigToDict")
    except AssertionError as e:
        result.addFail("testServiceConfigToDict", str(e))


# ==============================================================================
# ServiceStatus Tests
# ==============================================================================

def testServiceStatusDefaults(result):
    """Test ServiceStatus has correct default values."""
    try:
        status = ServiceStatus()

        assertFalse(status.installed, "installed default")
        assertFalse(status.enabled, "enabled default")
        assertFalse(status.active, "active default")
        assertFalse(status.running, "running default")
        assertEqual(status.serviceName, "", "serviceName default")
        assertEqual(status.serviceFilePath, "", "serviceFilePath default")
        assertEqual(status.lastChecked, None, "lastChecked default")

        result.addPass("testServiceStatusDefaults")
    except AssertionError as e:
        result.addFail("testServiceStatusDefaults", str(e))


def testServiceStatusToDict(result):
    """Test ServiceStatus toDict method."""
    try:
        now = datetime.now()
        status = ServiceStatus(
            installed=True,
            enabled=True,
            active=True,
            running=True,
            serviceName="test-service",
            serviceFilePath="/test/path",
            lastChecked=now
        )

        d = status.toDict()

        assertIsInstance(d, dict, "toDict returns dict")
        assertTrue(d['installed'], "installed in dict")
        assertTrue(d['enabled'], "enabled in dict")
        assertEqual(d['serviceName'], "test-service", "serviceName in dict")
        assertEqual(d['lastChecked'], now.isoformat(), "lastChecked in dict")

        result.addPass("testServiceStatusToDict")
    except AssertionError as e:
        result.addFail("testServiceStatusToDict", str(e))


def testServiceStatusToDictNoneLastChecked(result):
    """Test ServiceStatus toDict with None lastChecked."""
    try:
        status = ServiceStatus(lastChecked=None)
        d = status.toDict()

        assertEqual(d['lastChecked'], None, "lastChecked None in dict")

        result.addPass("testServiceStatusToDictNoneLastChecked")
    except AssertionError as e:
        result.addFail("testServiceStatusToDictNoneLastChecked", str(e))


# ==============================================================================
# ServiceManager Initialization Tests
# ==============================================================================

def testServiceManagerDefaultInit(result):
    """Test ServiceManager initialization with defaults."""
    try:
        manager = ServiceManager()

        assertIsNotNone(manager._serviceConfig, "has service config")
        assertEqual(
            manager._serviceConfig.serviceName,
            DEFAULT_SERVICE_NAME,
            "default service name"
        )

        result.addPass("testServiceManagerDefaultInit")
    except AssertionError as e:
        result.addFail("testServiceManagerDefaultInit", str(e))


def testServiceManagerConfigInit(result):
    """Test ServiceManager initialization with config dict."""
    try:
        config = {
            'autoStart': {
                'enabled': True,
                'serviceName': 'my-obd-service',
                'user': 'testuser',
                'maxRestartAttempts': 3
            }
        }

        manager = ServiceManager(config=config)

        assertEqual(
            manager._serviceConfig.serviceName,
            'my-obd-service',
            "parsed service name"
        )
        assertEqual(manager._serviceConfig.user, 'testuser', "parsed user")
        assertEqual(
            manager._serviceConfig.maxRestartAttempts,
            3,
            "parsed maxRestartAttempts"
        )

        result.addPass("testServiceManagerConfigInit")
    except AssertionError as e:
        result.addFail("testServiceManagerConfigInit", str(e))


def testServiceManagerServiceConfigOverride(result):
    """Test ServiceManager with ServiceConfig override."""
    try:
        serviceConfig = ServiceConfig(
            serviceName="override-service",
            user="override-user"
        )

        config = {
            'autoStart': {
                'serviceName': 'config-service',
                'user': 'config-user'
            }
        }

        # ServiceConfig should override config dict
        manager = ServiceManager(config=config, serviceConfig=serviceConfig)

        assertEqual(
            manager._serviceConfig.serviceName,
            'override-service',
            "ServiceConfig overrides config dict"
        )
        assertEqual(
            manager._serviceConfig.user,
            'override-user',
            "ServiceConfig user overrides"
        )

        result.addPass("testServiceManagerServiceConfigOverride")
    except AssertionError as e:
        result.addFail("testServiceManagerServiceConfigOverride", str(e))


# ==============================================================================
# Service File Generation Tests
# ==============================================================================

def testGenerateServiceFileContainsRequiredSections(result):
    """Test generated service file contains all required sections."""
    try:
        manager = ServiceManager()
        content = manager.generateServiceFile()

        assertIn('[Unit]', content, "has [Unit] section")
        assertIn('[Service]', content, "has [Service] section")
        assertIn('[Install]', content, "has [Install] section")

        result.addPass("testGenerateServiceFileContainsRequiredSections")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileContainsRequiredSections", str(e))


def testGenerateServiceFileStartsAfterNetwork(result):
    """Test service starts after network.target (US-006 requirement)."""
    try:
        manager = ServiceManager()
        content = manager.generateServiceFile()

        assertIn('After=network.target', content, "starts after network.target")

        result.addPass("testGenerateServiceFileStartsAfterNetwork")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileStartsAfterNetwork", str(e))


def testGenerateServiceFileRestartOnFailure(result):
    """Test service has restart on failure (US-006 requirement)."""
    try:
        manager = ServiceManager()
        content = manager.generateServiceFile()

        assertIn('Restart=on-failure', content, "has restart on failure")

        result.addPass("testGenerateServiceFileRestartOnFailure")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileRestartOnFailure", str(e))


def testGenerateServiceFileRestartLimit(result):
    """Test service has 5 restart attempt limit (US-006 requirement)."""
    try:
        config = ServiceConfig(maxRestartAttempts=5)
        manager = ServiceManager(serviceConfig=config)
        content = manager.generateServiceFile()

        assertIn('StartLimitBurst=5', content, "has StartLimitBurst=5")

        result.addPass("testGenerateServiceFileRestartLimit")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileRestartLimit", str(e))


def testGenerateServiceFileRestartDelay(result):
    """Test service has configurable restart delay."""
    try:
        config = ServiceConfig(restartDelaySeconds=15)
        manager = ServiceManager(serviceConfig=config)
        content = manager.generateServiceFile()

        assertIn('RestartSec=15', content, "has RestartSec=15")

        result.addPass("testGenerateServiceFileRestartDelay")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileRestartDelay", str(e))


def testGenerateServiceFileUsesCorrectPaths(result):
    """Test service file uses configured paths."""
    try:
        config = ServiceConfig(
            workingDir='/custom/obd',
            mainScript='app.py',
            pythonPath='/usr/bin/python3.11'
        )
        manager = ServiceManager(serviceConfig=config)
        content = manager.generateServiceFile()

        assertIn('WorkingDirectory=/custom/obd', content, "has custom working dir")
        assertIn('/usr/bin/python3.11', content, "has custom python path")
        assertIn('/custom/obd/app.py', content, "has correct main script path")

        result.addPass("testGenerateServiceFileUsesCorrectPaths")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileUsesCorrectPaths", str(e))


def testGenerateServiceFileHasSecurityHardening(result):
    """Test service file has security hardening options."""
    try:
        manager = ServiceManager()
        content = manager.generateServiceFile()

        assertIn('NoNewPrivileges=true', content, "has NoNewPrivileges")
        assertIn('PrivateTmp=true', content, "has PrivateTmp")

        result.addPass("testGenerateServiceFileHasSecurityHardening")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileHasSecurityHardening", str(e))


def testGenerateServiceFileWantedByMultiuser(result):
    """Test service is wanted by multi-user.target."""
    try:
        manager = ServiceManager()
        content = manager.generateServiceFile()

        assertIn('WantedBy=multi-user.target', content, "wanted by multi-user")

        result.addPass("testGenerateServiceFileWantedByMultiuser")
    except AssertionError as e:
        result.addFail("testGenerateServiceFileWantedByMultiuser", str(e))


# ==============================================================================
# Service File Write Tests
# ==============================================================================

def testWriteServiceFile(result):
    """Test writing service file to disk."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            outputPath = os.path.join(tmpdir, 'test.service')

            manager = ServiceManager()
            writtenPath = manager.writeServiceFile(outputPath)

            assertEqual(writtenPath, outputPath, "returns correct path")
            assertTrue(os.path.exists(outputPath), "file exists")

            with open(outputPath, 'r') as f:
                content = f.read()

            assertIn('[Unit]', content, "file has content")

        result.addPass("testWriteServiceFile")
    except AssertionError as e:
        result.addFail("testWriteServiceFile", str(e))


def testWriteServiceFileDefaultPath(result):
    """Test writing service file with default path."""
    try:
        originalDir = os.getcwd()

        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)

            try:
                manager = ServiceManager()
                writtenPath = manager.writeServiceFile()

                assertTrue(os.path.exists(writtenPath), "file exists")
                assertIn('.service', writtenPath, "has .service extension")
            finally:
                os.chdir(originalDir)

        result.addPass("testWriteServiceFileDefaultPath")
    except AssertionError as e:
        result.addFail("testWriteServiceFileDefaultPath", str(e))


# ==============================================================================
# Service Path Tests
# ==============================================================================

def testGetServiceFilePath(result):
    """Test getting service file path."""
    try:
        manager = ServiceManager()
        path = manager.getServiceFilePath()

        expectedPath = os.path.join(
            DEFAULT_SERVICE_DIR,
            f"{DEFAULT_SERVICE_NAME}.service"
        )
        assertEqual(path, expectedPath, "correct path")

        result.addPass("testGetServiceFilePath")
    except AssertionError as e:
        result.addFail("testGetServiceFilePath", str(e))


def testGetServiceFilePathCustomName(result):
    """Test getting service file path with custom name."""
    try:
        config = ServiceConfig(serviceName="my-custom-service")
        manager = ServiceManager(serviceConfig=config)
        path = manager.getServiceFilePath()

        assertIn("my-custom-service.service", path, "uses custom name")

        result.addPass("testGetServiceFilePathCustomName")
    except AssertionError as e:
        result.addFail("testGetServiceFilePathCustomName", str(e))


# ==============================================================================
# Service Status Tests
# ==============================================================================

def testGetStatusServiceNotInstalled(result):
    """Test getStatus when service is not installed."""
    try:
        manager = ServiceManager()
        manager._serviceDir = '/nonexistent/path'

        status = manager.getStatus()

        assertFalse(status.installed, "not installed")
        assertFalse(status.enabled, "not enabled")
        assertFalse(status.active, "not active")
        assertFalse(status.running, "not running")

        result.addPass("testGetStatusServiceNotInstalled")
    except AssertionError as e:
        result.addFail("testGetStatusServiceNotInstalled", str(e))


def testIsInstalledFalse(result):
    """Test isInstalled returns False when not installed."""
    try:
        manager = ServiceManager()
        manager._serviceDir = '/nonexistent/path'

        assertFalse(manager.isInstalled(), "not installed")

        result.addPass("testIsInstalledFalse")
    except AssertionError as e:
        result.addFail("testIsInstalledFalse", str(e))


# ==============================================================================
# Installation Script Generation Tests
# ==============================================================================

def testGenerateInstallScript(result):
    """Test generating install script."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            outputPath = os.path.join(tmpdir, 'install.sh')

            scriptPath = generateInstallScript(outputPath=outputPath)

            assertEqual(scriptPath, outputPath, "returns correct path")
            assertTrue(os.path.exists(scriptPath), "script exists")

            with open(scriptPath, 'r') as f:
                content = f.read()

            assertIn('#!/bin/bash', content, "has shebang")
            assertIn('systemctl daemon-reload', content, "has daemon-reload")
            assertIn('systemctl enable', content, "has enable command")
            assertIn(DEFAULT_SERVICE_NAME, content, "has service name")

        result.addPass("testGenerateInstallScript")
    except AssertionError as e:
        result.addFail("testGenerateInstallScript", str(e))


def testGenerateInstallScriptIsExecutable(result):
    """Test generated install script is executable (or attempts to set on Windows)."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            outputPath = os.path.join(tmpdir, 'install.sh')

            generateInstallScript(outputPath=outputPath)

            # On Windows, executable bits may not work as expected
            # Just verify the file exists and is readable
            assertTrue(os.path.exists(outputPath), "script exists")

            # On Linux, check executable bit
            if sys.platform != 'win32':
                mode = os.stat(outputPath).st_mode
                assertTrue(mode & 0o111, "script is executable")

        result.addPass("testGenerateInstallScriptIsExecutable")
    except AssertionError as e:
        result.addFail("testGenerateInstallScriptIsExecutable", str(e))


def testGenerateInstallScriptContainsServiceFile(result):
    """Test install script embeds the service file content."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            outputPath = os.path.join(tmpdir, 'install.sh')

            config = ServiceConfig(serviceName="test-embed")
            generateInstallScript(serviceConfig=config, outputPath=outputPath)

            with open(outputPath, 'r') as f:
                content = f.read()

            assertIn('[Unit]', content, "embeds service file")
            assertIn('Description=Eclipse OBD-II', content, "has description")

        result.addPass("testGenerateInstallScriptContainsServiceFile")
    except AssertionError as e:
        result.addFail("testGenerateInstallScriptContainsServiceFile", str(e))


def testGenerateUninstallScript(result):
    """Test generating uninstall script."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            outputPath = os.path.join(tmpdir, 'uninstall.sh')

            scriptPath = generateUninstallScript(outputPath=outputPath)

            assertTrue(os.path.exists(scriptPath), "script exists")

            with open(scriptPath, 'r') as f:
                content = f.read()

            assertIn('#!/bin/bash', content, "has shebang")
            assertIn('systemctl stop', content, "has stop command")
            assertIn('systemctl disable', content, "has disable command")
            assertIn('rm', content, "has remove command")

        result.addPass("testGenerateUninstallScript")
    except AssertionError as e:
        result.addFail("testGenerateUninstallScript", str(e))


# ==============================================================================
# Factory Function Tests
# ==============================================================================

def testCreateServiceManagerFromConfig(result):
    """Test factory function creates manager."""
    try:
        config = {
            'autoStart': {
                'serviceName': 'factory-test',
                'maxRestartAttempts': 7
            }
        }

        manager = createServiceManagerFromConfig(config)

        assertIsInstance(manager, ServiceManager, "returns ServiceManager")
        assertEqual(
            manager._serviceConfig.serviceName,
            'factory-test',
            "parses service name"
        )
        assertEqual(
            manager._serviceConfig.maxRestartAttempts,
            7,
            "parses maxRestartAttempts"
        )

        result.addPass("testCreateServiceManagerFromConfig")
    except AssertionError as e:
        result.addFail("testCreateServiceManagerFromConfig", str(e))


# ==============================================================================
# Exception Tests
# ==============================================================================

def testServiceErrorHasDetails(result):
    """Test ServiceError includes details."""
    try:
        details = {'code': 42, 'reason': 'test'}
        error = ServiceError("Test error", details)

        assertEqual(error.message, "Test error", "has message")
        assertEqual(error.details['code'], 42, "has details code")
        assertEqual(error.details['reason'], 'test', "has details reason")

        result.addPass("testServiceErrorHasDetails")
    except AssertionError as e:
        result.addFail("testServiceErrorHasDetails", str(e))


def testServiceInstallErrorInheritsFromServiceError(result):
    """Test ServiceInstallError is a ServiceError."""
    try:
        error = ServiceInstallError("Install failed")

        assertIsInstance(error, ServiceError, "inherits from ServiceError")
        assertIsInstance(error, Exception, "inherits from Exception")

        result.addPass("testServiceInstallErrorInheritsFromServiceError")
    except AssertionError as e:
        result.addFail("testServiceInstallErrorInheritsFromServiceError", str(e))


def testServiceCommandErrorInheritsFromServiceError(result):
    """Test ServiceCommandError is a ServiceError."""
    try:
        error = ServiceCommandError("Command failed")

        assertIsInstance(error, ServiceError, "inherits from ServiceError")

        result.addPass("testServiceCommandErrorInheritsFromServiceError")
    except AssertionError as e:
        result.addFail("testServiceCommandErrorInheritsFromServiceError", str(e))


# ==============================================================================
# Systemctl Mock Tests
# ==============================================================================

def testRunSystemctlSuccess(result):
    """Test _runSystemctl with successful command."""
    try:
        manager = ServiceManager()

        with patch('subprocess.run') as mockRun:
            mockRun.return_value = MagicMock(
                returncode=0,
                stdout='',
                stderr=''
            )

            success = manager._runSystemctl(['status', 'test.service'])

            assertTrue(success, "returns True on success")
            mockRun.assert_called_once()

        result.addPass("testRunSystemctlSuccess")
    except AssertionError as e:
        result.addFail("testRunSystemctlSuccess", str(e))


def testRunSystemctlNotFound(result):
    """Test _runSystemctl when systemctl not found."""
    try:
        manager = ServiceManager()

        with patch('subprocess.run') as mockRun:
            mockRun.side_effect = FileNotFoundError("systemctl not found")

            try:
                manager._runSystemctl(['status', 'test.service'])
                result.addFail("testRunSystemctlNotFound", "Should have raised error")
                return
            except ServiceCommandError as e:
                assertIn('systemctl not found', str(e), "error message")

        result.addPass("testRunSystemctlNotFound")
    except AssertionError as e:
        result.addFail("testRunSystemctlNotFound", str(e))


# ==============================================================================
# Integration Tests
# ==============================================================================

def testFullWorkflow(result):
    """Test full workflow: generate, write, verify."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create manager
            config = ServiceConfig(
                serviceName="integration-test",
                user="testuser",
                workingDir="/opt/test",
                maxRestartAttempts=5
            )
            manager = ServiceManager(serviceConfig=config)

            # Generate content
            content = manager.generateServiceFile()
            assertIn('[Unit]', content, "generated content")

            # Write to file
            outputPath = os.path.join(tmpdir, 'test.service')
            writtenPath = manager.writeServiceFile(outputPath)

            # Verify file
            assertTrue(os.path.exists(writtenPath), "file written")

            with open(writtenPath, 'r') as f:
                fileContent = f.read()

            assertEqual(content, fileContent, "content matches")
            assertIn('User=testuser', fileContent, "has custom user")
            assertIn('StartLimitBurst=5', fileContent, "has restart limit")

        result.addPass("testFullWorkflow")
    except AssertionError as e:
        result.addFail("testFullWorkflow", str(e))


def testGenerateBothScripts(result):
    """Test generating both install and uninstall scripts."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            installPath = os.path.join(tmpdir, 'install.sh')
            uninstallPath = os.path.join(tmpdir, 'uninstall.sh')

            config = ServiceConfig(serviceName="script-test")

            generateInstallScript(serviceConfig=config, outputPath=installPath)
            generateUninstallScript(serviceConfig=config, outputPath=uninstallPath)

            assertTrue(os.path.exists(installPath), "install script exists")
            assertTrue(os.path.exists(uninstallPath), "uninstall script exists")

            with open(installPath, 'r') as f:
                installContent = f.read()
            with open(uninstallPath, 'r') as f:
                uninstallContent = f.read()

            assertIn('script-test', installContent, "install has service name")
            assertIn('script-test', uninstallContent, "uninstall has service name")

        result.addPass("testGenerateBothScripts")
    except AssertionError as e:
        result.addFail("testGenerateBothScripts", str(e))


# ==============================================================================
# Run All Tests
# ==============================================================================

def runAllTests():
    """Run all tests and report results."""
    result = TestResult()

    print("=" * 60)
    print("Running Service Module Tests (US-006)")
    print("=" * 60)

    # ServiceConfig tests
    print("\n--- ServiceConfig Tests ---")
    testServiceConfigDefaults(result)
    testServiceConfigCustomValues(result)
    testServiceConfigToDict(result)

    # ServiceStatus tests
    print("\n--- ServiceStatus Tests ---")
    testServiceStatusDefaults(result)
    testServiceStatusToDict(result)
    testServiceStatusToDictNoneLastChecked(result)

    # ServiceManager initialization tests
    print("\n--- ServiceManager Initialization Tests ---")
    testServiceManagerDefaultInit(result)
    testServiceManagerConfigInit(result)
    testServiceManagerServiceConfigOverride(result)

    # Service file generation tests
    print("\n--- Service File Generation Tests ---")
    testGenerateServiceFileContainsRequiredSections(result)
    testGenerateServiceFileStartsAfterNetwork(result)
    testGenerateServiceFileRestartOnFailure(result)
    testGenerateServiceFileRestartLimit(result)
    testGenerateServiceFileRestartDelay(result)
    testGenerateServiceFileUsesCorrectPaths(result)
    testGenerateServiceFileHasSecurityHardening(result)
    testGenerateServiceFileWantedByMultiuser(result)

    # Service file write tests
    print("\n--- Service File Write Tests ---")
    testWriteServiceFile(result)
    testWriteServiceFileDefaultPath(result)

    # Service path tests
    print("\n--- Service Path Tests ---")
    testGetServiceFilePath(result)
    testGetServiceFilePathCustomName(result)

    # Service status tests
    print("\n--- Service Status Tests ---")
    testGetStatusServiceNotInstalled(result)
    testIsInstalledFalse(result)

    # Installation script tests
    print("\n--- Installation Script Tests ---")
    testGenerateInstallScript(result)
    testGenerateInstallScriptIsExecutable(result)
    testGenerateInstallScriptContainsServiceFile(result)
    testGenerateUninstallScript(result)

    # Factory function tests
    print("\n--- Factory Function Tests ---")
    testCreateServiceManagerFromConfig(result)

    # Exception tests
    print("\n--- Exception Tests ---")
    testServiceErrorHasDetails(result)
    testServiceInstallErrorInheritsFromServiceError(result)
    testServiceCommandErrorInheritsFromServiceError(result)

    # Systemctl mock tests
    print("\n--- Systemctl Mock Tests ---")
    testRunSystemctlSuccess(result)
    testRunSystemctlNotFound(result)

    # Integration tests
    print("\n--- Integration Tests ---")
    testFullWorkflow(result)
    testGenerateBothScripts(result)

    # Summary (format matches run_all_tests.py parser)
    print("\n" + "=" * 60)
    print(f"Tests completed: {result.passed + result.failed}")
    print(f"  {result.passed} passed, {result.failed} failed")
    print("=" * 60)

    if result.errors:
        print("\nFailed tests:")
        for name, reason in result.errors:
            print(f"  - {name}: {reason}")

    return result.failed == 0


if __name__ == '__main__':
    success = runAllTests()
    sys.exit(0 if success else 1)
