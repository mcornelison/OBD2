################################################################################
# File Name: main.py
# Purpose/Description: Main application entry point
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-21    | M. Cornelison | Initial implementation
# 2026-01-22    | M. Cornelison | Added --simulate/-s flag for simulation mode (US-033)
# 2026-01-23    | Ralph Agent  | US-OSC-004: Added signal handler registration
# 2026-01-23    | Ralph Agent  | US-OSC-005: Use orchestrator.runLoop() for main loop
# ================================================================================
################################################################################

"""
Main application entry point.

This module provides the main entry point for the application with:
- CLI argument parsing
- Configuration loading and validation
- Workflow orchestration
- Signal handling for graceful shutdown (SIGINT/SIGTERM)
- Error handling and exit codes
- Simulation mode for testing without hardware

Usage:
    python src/main.py --help
    python src/main.py --config path/to/config.json
    python src/main.py --dry-run
    python src/main.py --simulate
"""

import argparse
import sys
from pathlib import Path

# Resolve project paths relative to this script (not CWD)
srcPath = Path(__file__).resolve().parent
projectRoot = srcPath.parent
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))

DEFAULT_CONFIG = str(srcPath / 'obd_config.json')
DEFAULT_ENV = str(projectRoot / '.env')

from common.config_validator import ConfigValidationError, ConfigValidator
from common.error_handler import ConfigurationError, handleError
from common.logging_config import getLogger, setupLogging
from common.secrets_loader import loadConfigWithSecrets

# Exit codes
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_RUNTIME_ERROR = 2
EXIT_UNKNOWN_ERROR = 3


def parseArgs() -> argparse.Namespace:
    """
    Parse command line arguments.

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description='Application description here',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python main.py                    Run with default config
  python main.py --config my.json   Run with custom config
  python main.py --dry-run          Run without making changes
  python main.py --verbose          Run with debug logging
        '''
    )

    parser.add_argument(
        '--config', '-c',
        default=DEFAULT_CONFIG,
        help='Path to configuration file (default: src/obd_config.json)'
    )

    parser.add_argument(
        '--env-file', '-e',
        default=DEFAULT_ENV,
        help='Path to environment file (default: .env)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without making changes'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose (debug) logging'
    )

    parser.add_argument(
        '--simulate', '-s',
        action='store_true',
        help='Run in simulation mode using SimulatedObdConnection instead of real hardware'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )

    return parser.parse_args()


def loadConfiguration(
    configPath: str,
    envPath: str | None = None
) -> dict:
    """
    Load and validate configuration.

    Args:
        configPath: Path to configuration file
        envPath: Path to environment file

    Returns:
        Validated configuration dictionary

    Raises:
        ConfigurationError: If configuration is invalid
    """
    logger = getLogger(__name__)

    try:
        # Load config with secret resolution
        config = loadConfigWithSecrets(configPath, envPath)

        # Validate configuration
        validator = ConfigValidator()
        config = validator.validate(config)

        logger.info(f"Configuration loaded from {configPath}")
        return config

    except FileNotFoundError as e:
        raise ConfigurationError(f"Configuration file not found: {e}") from e
    except ConfigValidationError as e:
        raise ConfigurationError(f"Configuration validation failed: {e}") from e


def runWorkflow(
    config: dict,
    dryRun: bool = False,
    simulate: bool = False
) -> int:
    """
    Execute the main application workflow using the ApplicationOrchestrator.

    Registers signal handlers before starting the orchestrator, then waits
    for shutdown signal. On shutdown, restores original signal handlers.

    Args:
        config: Validated configuration dictionary
        dryRun: If True, validate config but don't start orchestrator
        simulate: If True, use simulated OBD-II connection

    Returns:
        Exit code: 0 for clean shutdown, non-zero for errors
    """
    from obd.orchestrator import createOrchestratorFromConfig

    logger = getLogger(__name__)

    if dryRun:
        logger.info("DRY RUN MODE - Validating config without starting orchestrator")
        logger.info("Configuration is valid")
        return EXIT_SUCCESS

    logger.info("Starting workflow...")

    # Create orchestrator
    orchestrator = createOrchestratorFromConfig(config, simulate=simulate)

    # Register signal handlers BEFORE starting orchestrator
    logger.debug("Registering signal handlers...")
    orchestrator.registerSignalHandlers()

    try:
        # Start the orchestrator
        orchestrator.start()

        # Run the main application loop
        # This handles component callbacks, health checks, and waits for shutdown
        orchestrator.runLoop()

        # Stop the orchestrator gracefully
        exitCode = orchestrator.stop()

    except KeyboardInterrupt:
        # Handle Ctrl+C during startup
        logger.warning("Startup interrupted by user")
        exitCode = orchestrator.stop()

    except Exception as e:
        logger.error(f"Workflow error: {e}")
        exitCode = orchestrator.stop()
        if exitCode == EXIT_SUCCESS:
            exitCode = EXIT_RUNTIME_ERROR

    finally:
        # Restore original signal handlers
        logger.debug("Restoring signal handlers...")
        orchestrator.restoreSignalHandlers()

    logger.info("Workflow completed")
    return exitCode


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    # Parse arguments
    args = parseArgs()

    # Setup logging
    logLevel = 'DEBUG' if args.verbose else 'INFO'
    setupLogging(level=logLevel)
    logger = getLogger(__name__)

    logger.info("=" * 60)
    logger.info("Application starting...")
    if args.simulate:
        logger.info("*** Running in SIMULATION MODE ***")
    logger.info("=" * 60)

    try:
        # Load configuration
        config = loadConfiguration(args.config, args.env_file)

        # Run workflow with orchestrator
        exitCode = runWorkflow(
            config,
            dryRun=args.dry_run,
            simulate=args.simulate
        )

        if exitCode == EXIT_SUCCESS:
            logger.info("Application completed successfully")
        else:
            logger.warning(f"Application completed with exit code {exitCode}")

        return exitCode

    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        return EXIT_CONFIG_ERROR

    except KeyboardInterrupt:
        logger.warning("Application interrupted by user")
        return EXIT_RUNTIME_ERROR

    except Exception as e:
        handleError(e, reraise=False)
        logger.error(f"Unexpected error: {e}")
        return EXIT_UNKNOWN_ERROR

    finally:
        logger.info("=" * 60)
        logger.info("Application finished")
        logger.info("=" * 60)


if __name__ == '__main__':
    sys.exit(main())
