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
# 2026-04-20    | Rex (Ralph)  | US-210: SIMULATE MODE banner + production-warning.
#                                Production systemd unit no longer passes --simulate
#                                (CIO Session 6 directive 1). Operators running the
#                                flag manually must see an obvious banner so they
#                                never mistake sim output for real-OBD capture.
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
# __file__ is src/pi/main.py — srcDir is src/, projectRoot is repo root
srcDir = Path(__file__).resolve().parent.parent
projectRoot = srcDir.parent
if str(srcDir) not in sys.path:
    sys.path.insert(0, str(srcDir))
# Some modules import shared helpers via `from src.common.time.helper ...`
# (US-203 pattern). That form only resolves when the repository root is on
# sys.path — mirror the pytest/conftest setup so the subprocess environment
# matches the test environment exactly.
if str(projectRoot) not in sys.path:
    sys.path.insert(0, str(projectRoot))

DEFAULT_CONFIG = str(projectRoot / 'config.json')
DEFAULT_ENV = str(projectRoot / '.env')

from common.config.secrets_loader import loadConfigWithSecrets  # noqa: E402
from common.config.validator import ConfigValidationError, ConfigValidator  # noqa: E402
from common.errors.handler import ConfigurationError, handleError  # noqa: E402
from common.logging.setup import getLogger, setupLogging  # noqa: E402

# Exit codes
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_RUNTIME_ERROR = 2
EXIT_UNKNOWN_ERROR = 3

# US-210 invariant: the exact sentinel string that stdout must carry when
# --simulate is active so no operator confuses sim output for real-OBD
# capture. Production systemd unit no longer passes this flag (CIO Session 6
# directive 1); only developer invocations surface it. Tests assert this
# literal appears in stdout.
SIMULATE_BANNER_SENTINEL = 'SIMULATE MODE -- NOT FOR PRODUCTION'


def _printSimulateBanner() -> None:
    """Print a high-visibility warning to stdout when --simulate is active.

    Written to stdout (not the logger) so it survives regardless of the
    logging configuration and appears in `journalctl -u eclipse-obd` output
    unambiguously. Carries the US-210 sentinel string
    ``SIMULATE MODE -- NOT FOR PRODUCTION`` exactly once so the
    tests/deploy/ + tests/pi/ assertions can match on a single token.
    """
    bar = '!' * 70
    lines = [
        bar,
        f'!!!  {SIMULATE_BANNER_SENTINEL}',
        '!!!  Running with --simulate flag. All OBD values below are',
        '!!!  synthetic, produced by SimulatedObdConnection. Do NOT',
        '!!!  treat any row written while this banner is active as',
        '!!!  real-vehicle telemetry. The eclipse-obd.service production',
        '!!!  unit does NOT carry --simulate (Sprint 16 US-210).',
        bar,
    ]
    # print() so it hits stdout before logger setup finishes configuring
    # handlers; flush to guarantee ordering vs. the logger banner below.
    print('\n'.join(lines), flush=True)


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
        help='Path to configuration file (default: config.json at repo root)'
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
    from pi.obdii.orchestrator import createOrchestratorFromConfig

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

    # US-210: print the SIMULATE MODE banner BEFORE logging is configured so
    # it lands at the top of stdout unambiguously (and reaches journalctl
    # even when someone tees or pipes the output). The logger banner below
    # still emits; this sentinel is the additional operator guard.
    if args.simulate:
        _printSimulateBanner()

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
