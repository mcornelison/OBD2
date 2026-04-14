################################################################################
# File Name: __init__.py
# Purpose/Description: Service subpackage for systemd service management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# ================================================================================
################################################################################
"""
Service Subpackage.

This subpackage contains systemd service components:
- Systemd service file generation
- Service manager
- Install/uninstall scripts

Note: During refactoring, this subpackage re-exports from the legacy service.py
module for backward compatibility. Once US-019 is complete, exports will come
from the new modular structure.
"""

import importlib.util
from pathlib import Path

# Load the sibling service.py module (not this package)
# This is necessary because Python resolves service/ before service.py
_module_path = Path(__file__).parent.parent / "service.py"
_spec = importlib.util.spec_from_file_location("_obd_service_legacy", str(_module_path))
if _spec is not None and _spec.loader is not None:
    _service_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_service_module)

    # Re-export all public symbols from the legacy module
    ServiceManager = _service_module.ServiceManager
    ServiceConfig = _service_module.ServiceConfig
    ServiceStatus = _service_module.ServiceStatus
    ServiceError = _service_module.ServiceError
    ServiceInstallError = _service_module.ServiceInstallError
    ServiceNotInstalledError = _service_module.ServiceNotInstalledError
    ServiceCommandError = _service_module.ServiceCommandError
    createServiceManagerFromConfig = _service_module.createServiceManagerFromConfig
    generateInstallScript = _service_module.generateInstallScript
    generateUninstallScript = _service_module.generateUninstallScript

    __all__ = [
        "ServiceManager",
        "ServiceConfig",
        "ServiceStatus",
        "ServiceError",
        "ServiceInstallError",
        "ServiceNotInstalledError",
        "ServiceCommandError",
        "createServiceManagerFromConfig",
        "generateInstallScript",
        "generateUninstallScript",
    ]
else:
    # Fallback: exports empty if module loading fails
    __all__: list[str] = []
