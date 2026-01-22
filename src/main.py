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
# ================================================================================
################################################################################

"""
Main application entry point.

This module provides the main entry point for the application with:
- CLI argument parsing
- Configuration loading and validation
- Workflow orchestration
- Error handling and exit codes

Usage:
    python src/main.py --help
    python src/main.py --config path/to/config.json
    python src/main.py --dry-run
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

# Add src to path for imports
srcPath = Path(__file__).parent
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))

from common.config_validator import ConfigValidator, ConfigValidationError
from common.secrets_loader import loadConfigWithSecrets
from common.logging_config import setupLogging, getLogger
from common.error_handler import handleError, ConfigurationError

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
        default='src/config.json',
        help='Path to configuration file (default: src/config.json)'
    )

    parser.add_argument(
        '--env-file', '-e',
        default='.env',
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
        '--version',
        action='version',
        version='%(prog)s 1.0.0'
    )

    return parser.parse_args()


def loadConfiguration(
    configPath: str,
    envPath: Optional[str] = None
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
        raise ConfigurationError(f"Configuration file not found: {e}")
    except ConfigValidationError as e:
        raise ConfigurationError(f"Configuration validation failed: {e}")


def runWorkflow(config: dict, dryRun: bool = False) -> bool:
    """
    Execute the main application workflow.

    Args:
        config: Validated configuration dictionary
        dryRun: If True, don't make persistent changes

    Returns:
        True if successful, False otherwise
    """
    logger = getLogger(__name__)

    if dryRun:
        logger.info("DRY RUN MODE - No changes will be made")

    logger.info("Starting workflow...")

    # =========================================================================
    # TODO: Implement your workflow here
    # =========================================================================
    #
    # Example structure:
    #
    # 1. Initialize clients/connections
    # client = createClient(config)
    #
    # 2. Execute main logic
    # result = processData(client, config)
    #
    # 3. Handle results
    # if result.success:
    #     logger.info(f"Processed {result.count} records")
    # else:
    #     logger.error(f"Workflow failed: {result.error}")
    #     return False
    #
    # =========================================================================

    logger.info("Workflow completed successfully")
    return True


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
    logger.info("=" * 60)

    try:
        # Load configuration
        config = loadConfiguration(args.config, args.env_file)

        # Run workflow
        success = runWorkflow(config, dryRun=args.dry_run)

        if success:
            logger.info("Application completed successfully")
            return EXIT_SUCCESS
        else:
            logger.error("Application completed with errors")
            return EXIT_RUNTIME_ERROR

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
