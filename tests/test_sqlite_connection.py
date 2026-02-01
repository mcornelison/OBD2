################################################################################
# File Name: test_sqlite_connection.py
# Purpose/Description: Test SQLite database connectivity and basic operations
# Author: Claude
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Claude       | Initial implementation
# ================================================================================
################################################################################

"""
SQLite connectivity test script.

This script verifies that:
1. Python sqlite3 module works correctly
2. The ObdDatabase class can create and initialize a database
3. Read and write operations work correctly
4. WAL mode is properly configured

Run with: python tests/test_sqlite_connection.py
"""

import os
import sys
import tempfile
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.database import ObdDatabase, DatabaseError


def printHeader(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def printResult(test: str, passed: bool, details: str = "") -> None:
    """Print a test result."""
    status = "PASS" if passed else "FAIL"
    icon = "[OK]" if passed else "[X]"
    print(f"  {icon} {test}: {status}")
    if details:
        print(f"      {details}")


def testPythonSqlite3() -> bool:
    """Test basic Python sqlite3 functionality."""
    printHeader("Test 1: Python sqlite3 Module")

    try:
        import sqlite3
        printResult("Import sqlite3", True, f"Version: {sqlite3.sqlite_version}")

        # Test in-memory database
        conn = sqlite3.connect(':memory:')
        cursor = conn.cursor()

        # Create table
        cursor.execute('CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)')
        printResult("Create table", True)

        # Insert data
        cursor.execute("INSERT INTO test (value) VALUES ('hello')")
        conn.commit()
        printResult("Insert data", True)

        # Read data
        cursor.execute('SELECT * FROM test')
        row = cursor.fetchone()
        readSuccess = row is not None and row[1] == 'hello'
        printResult("Read data", readSuccess, f"Got: {row}")

        conn.close()
        return True

    except Exception as e:
        printResult("Python sqlite3", False, str(e))
        return False


def testObdDatabaseInit() -> bool:
    """Test ObdDatabase initialization."""
    printHeader("Test 2: ObdDatabase Initialization")

    # Create temp database file
    dbPath = tempfile.mktemp(suffix='.db')

    try:
        # Create database instance
        db = ObdDatabase(dbPath, walMode=True)
        printResult("Create ObdDatabase instance", True, f"Path: {dbPath}")

        # Initialize schema
        db.initialize()
        printResult("Initialize schema", True)

        # Check tables were created
        tables = db.getTableNames()
        expectedTables = [
            'vehicle_info', 'profiles', 'static_data', 'realtime_data',
            'statistics', 'ai_recommendations', 'calibration_sessions',
            'alert_log', 'connection_log', 'battery_log', 'power_log'
        ]
        allTablesExist = all(t in tables for t in expectedTables)
        printResult("All tables created", allTablesExist, f"Found {len(tables)} tables")

        # Check indexes were created
        indexes = db.getIndexNames()
        printResult("Indexes created", len(indexes) > 0, f"Found {len(indexes)} indexes")

        # Check WAL mode
        stats = db.getStats()
        printResult("WAL mode enabled", stats['wal_mode'], f"Journal mode: {'WAL' if stats['wal_mode'] else 'DELETE'}")

        return allTablesExist

    except Exception as e:
        printResult("ObdDatabase initialization", False, str(e))
        return False

    finally:
        # Cleanup
        for ext in ['', '-wal', '-shm']:
            path = dbPath + ext
            if os.path.exists(path):
                os.unlink(path)


def testReadWriteOperations() -> bool:
    """Test read/write operations on ObdDatabase."""
    printHeader("Test 3: Read/Write Operations")

    dbPath = tempfile.mktemp(suffix='.db')

    try:
        db = ObdDatabase(dbPath, walMode=True)
        db.initialize()

        # Test 1: Insert a profile
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO profiles (id, name, description)
                VALUES ('test_profile', 'Test Profile', 'For testing')
            """)
        printResult("Insert profile", True)

        # Test 2: Read the profile back
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM profiles WHERE id = 'test_profile'")
            row = cursor.fetchone()
            profileExists = row is not None and row['name'] == 'Test Profile'
        printResult("Read profile", profileExists, f"Name: {row['name'] if row else 'None'}")

        # Test 3: Insert realtime data
        with db.connect() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, 'RPM', 2500.0, 'rpm', 'test_profile')
            """, (now,))
        printResult("Insert realtime data", True)

        # Test 4: Query realtime data with aggregation
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT parameter_name, AVG(value) as avg_value, COUNT(*) as count
                FROM realtime_data
                WHERE profile_id = 'test_profile'
                GROUP BY parameter_name
            """)
            row = cursor.fetchone()
            aggregationWorks = row is not None and row['avg_value'] == 2500.0
        printResult("Aggregation query", aggregationWorks, f"AVG(RPM): {row['avg_value'] if row else 'None'}")

        # Test 5: Insert multiple records and query
        with db.connect() as conn:
            cursor = conn.cursor()
            for rpm in [1000, 2000, 3000, 4000, 5000]:
                cursor.execute("""
                    INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (datetime('now'), 'RPM', ?, 'rpm', 'test_profile')
                """, (rpm,))

        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MIN(value) as min_val, MAX(value) as max_val, AVG(value) as avg_val
                FROM realtime_data
                WHERE parameter_name = 'RPM' AND profile_id = 'test_profile'
            """)
            row = cursor.fetchone()
            statsWork = row['min_val'] == 1000 and row['max_val'] == 5000
        printResult("Statistics query", statsWork,
                   f"MIN: {row['min_val']}, MAX: {row['max_val']}, AVG: {row['avg_val']:.1f}")

        # Test 6: Get database stats
        stats = db.getStats()
        printResult("Database stats", stats['table_counts']['realtime_data'] == 6,
                   f"realtime_data rows: {stats['table_counts']['realtime_data']}")

        return profileExists and aggregationWorks and statsWork

    except Exception as e:
        printResult("Read/Write operations", False, str(e))
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Cleanup
        for ext in ['', '-wal', '-shm']:
            path = dbPath + ext
            if os.path.exists(path):
                os.unlink(path)


def testForeignKeyConstraints() -> bool:
    """Test that foreign key constraints work."""
    printHeader("Test 4: Foreign Key Constraints")

    dbPath = tempfile.mktemp(suffix='.db')

    try:
        db = ObdDatabase(dbPath, walMode=True)
        db.initialize()

        # Test: Insert realtime data with NULL profile_id (should work)
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
                VALUES (datetime('now'), 'RPM', 1500.0, 'rpm', NULL)
            """)
        printResult("Insert with NULL FK", True)

        # Test: Insert realtime data with valid profile_id (should work)
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO profiles (id, name) VALUES ('valid_profile', 'Valid')")
            cursor.execute("""
                INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
                VALUES (datetime('now'), 'RPM', 2000.0, 'rpm', 'valid_profile')
            """)
        printResult("Insert with valid FK", True)

        # Test: Insert realtime data with invalid profile_id (should fail)
        fkFailed = False
        try:
            with db.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (datetime('now'), 'RPM', 3000.0, 'rpm', 'nonexistent_profile')
                """)
        except DatabaseError as e:
            fkFailed = 'FOREIGN KEY constraint failed' in str(e)

        printResult("FK constraint enforced", fkFailed,
                   "Invalid FK correctly rejected" if fkFailed else "FK constraint not enforced!")

        return fkFailed

    except Exception as e:
        printResult("Foreign key test", False, str(e))
        return False

    finally:
        for ext in ['', '-wal', '-shm']:
            path = dbPath + ext
            if os.path.exists(path):
                os.unlink(path)


def main() -> int:
    """Run all SQLite tests."""
    print("\n" + "=" * 60)
    print("  SQLite Connection Test Suite")
    print("  Eclipse OBD-II Project")
    print("=" * 60)

    results = []

    results.append(("Python sqlite3 Module", testPythonSqlite3()))
    results.append(("ObdDatabase Initialization", testObdDatabaseInit()))
    results.append(("Read/Write Operations", testReadWriteOperations()))
    results.append(("Foreign Key Constraints", testForeignKeyConstraints()))

    # Summary
    printHeader("Test Summary")

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        icon = "[OK]" if result else "[X]"
        print(f"  {icon} {name}: {status}")

    print(f"\n  Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n  All tests passed! SQLite is ready for use.")
        return 0
    else:
        print("\n  Some tests failed. Check output above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
