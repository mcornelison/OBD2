#!/bin/bash
# ==============================================================================
# File: setup-mariadb.sh
# Purpose: Create MariaDB databases and user for the Eclipse OBD-II server
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Usage:
#   sudo ./setup-mariadb.sh [OPTIONS]
#
# Options:
#   --dry-run      Print SQL statements without executing
#   --password PW  Set the database user password (prompted if omitted)
#   --help         Show this help message
#
# Creates:
#   - Database: obd2db (production)
#   - Database: obd2db_test (testing)
#   - User: obd2@10.27.27.% with full privileges on both databases
# ==============================================================================

set -e

# ---- Configuration -----------------------------------------------------------

DB_NAME="obd2db"
DB_TEST_NAME="obd2db_test"
DB_USER="obd2"
DB_HOST_PATTERN="10.27.27.%"
DRY_RUN=false
DB_PASSWORD=""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ---- Argument Parsing --------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --password)
            DB_PASSWORD="$2"
            shift 2
            ;;
        --help)
            echo "Usage: sudo ./setup-mariadb.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run      Print SQL statements without executing"
            echo "  --password PW  Set the database user password"
            echo "  --help         Show this help message"
            echo ""
            echo "Creates obd2db and obd2db_test databases with user obd2@${DB_HOST_PATTERN}"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# ---- Password Prompt ---------------------------------------------------------

if [ -z "$DB_PASSWORD" ] && [ "$DRY_RUN" = false ]; then
    read -sp "Enter password for MariaDB user '${DB_USER}': " DB_PASSWORD
    echo
    if [ -z "$DB_PASSWORD" ]; then
        echo -e "${RED}Error: Password cannot be empty${NC}"
        exit 1
    fi
fi

# ---- SQL Statements ----------------------------------------------------------

SQL_STATEMENTS=$(cat <<EOSQL
-- Create production database
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Create test database
CREATE DATABASE IF NOT EXISTS \`${DB_TEST_NAME}\`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

-- Create user and grant privileges on production database
CREATE USER IF NOT EXISTS '${DB_USER}'@'${DB_HOST_PATTERN}'
    IDENTIFIED BY '${DB_PASSWORD}';

GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'${DB_HOST_PATTERN}';
GRANT ALL PRIVILEGES ON \`${DB_TEST_NAME}\`.* TO '${DB_USER}'@'${DB_HOST_PATTERN}';

-- Also allow localhost access for scripts run directly on Chi-Srv-01
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost'
    IDENTIFIED BY '${DB_PASSWORD}';

GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
GRANT ALL PRIVILEGES ON \`${DB_TEST_NAME}\`.* TO '${DB_USER}'@'localhost';

FLUSH PRIVILEGES;
EOSQL
)

# ---- Execute or Print --------------------------------------------------------

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}=== DRY RUN — SQL statements that would be executed ===${NC}"
    echo ""
    echo "$SQL_STATEMENTS"
    echo ""
    echo -e "${YELLOW}=== End of dry run ===${NC}"
else
    echo -e "${GREEN}Setting up MariaDB for Eclipse OBD-II Server...${NC}"
    echo ""

    # Execute SQL via mariadb client
    echo "$SQL_STATEMENTS" | mariadb -u root

    echo ""
    echo -e "${GREEN}=== Setup Complete ===${NC}"
    echo "  Production DB:  ${DB_NAME}"
    echo "  Test DB:        ${DB_TEST_NAME}"
    echo "  User:           ${DB_USER}@${DB_HOST_PATTERN}"
    echo "  User:           ${DB_USER}@localhost"
    echo ""
    echo "Connection URL for .env:"
    echo "  DATABASE_URL=mysql+aiomysql://${DB_USER}:<password>@localhost/${DB_NAME}"
fi
