"""
Migration script to simplify the bank transaction tables.

New simplified schema:
- id (PRIMARY KEY)
- transaction_date
- transaction_description
- client_vendor
- category
- code
- dr_amount
- cr_amount
- project
- created_at
- updated_at

Fields being removed:
- broader_category
- running_balance
- net
- dd
- notes

Usage:
  python migrate_schema.py --dry-run   # Preview changes
  python migrate_schema.py             # Execute migration
"""

import mysql.connector
from mysql.connector import Error
import sys

# Database connection settings
DB_CONFIG = {
    'host': 'yamanote.proxy.rlwy.net',
    'port': 57844,
    'user': 'root',
    'password': 'uxozNadQzagwhWazsWnfDZMSNvKHRwvi',
    'database': 'visma_financial'
}

TABLES_TO_MIGRATE = ['axis_transactions', 'kvb_transactions', 'transactions']

COLUMNS_TO_DROP = ['broader_category', 'running_balance', 'net', 'dd', 'notes']


def get_connection():
    """Create database connection."""
    try:
        connection = mysql.connector.connect(**DB_CONFIG, connection_timeout=30)
        if connection.is_connected():
            return connection
    except Error as e:
        print(f"Connection error: {e}")
    return None


def get_existing_columns(cursor, table_name):
    """Get list of existing columns in a table."""
    cursor.execute(f"SHOW COLUMNS FROM {table_name}")
    return [row[0] for row in cursor.fetchall()]


def migrate_table(cursor, table_name, dry_run=True):
    """Migrate a single table by dropping unnecessary columns."""
    print(f"\n{'='*50}")
    print(f"Migrating table: {table_name}")
    print(f"{'='*50}")

    # Check if table exists
    cursor.execute(f"SHOW TABLES LIKE '{table_name}'")
    if not cursor.fetchone():
        print(f"  Table {table_name} does not exist. Skipping.")
        return

    existing_columns = get_existing_columns(cursor, table_name)
    print(f"  Existing columns: {existing_columns}")

    columns_dropped = []
    for col in COLUMNS_TO_DROP:
        if col in existing_columns:
            if dry_run:
                print(f"  [DRY-RUN] Would drop column: {col}")
            else:
                try:
                    # First drop any indexes on this column
                    cursor.execute(f"SHOW INDEX FROM {table_name} WHERE Column_name = '{col}'")
                    indexes = cursor.fetchall()
                    for idx in indexes:
                        idx_name = idx[2]  # Key_name is at index 2
                        if idx_name != 'PRIMARY':
                            print(f"  Dropping index: {idx_name}")
                            cursor.execute(f"DROP INDEX {idx_name} ON {table_name}")

                    # Now drop the column
                    print(f"  Dropping column: {col}")
                    cursor.execute(f"ALTER TABLE {table_name} DROP COLUMN {col}")
                    columns_dropped.append(col)
                except Error as e:
                    print(f"  Error dropping {col}: {e}")
        else:
            print(f"  Column {col} not found (already removed or never existed)")

    if not dry_run and columns_dropped:
        print(f"  Successfully dropped columns: {columns_dropped}")

    # Show final schema
    final_columns = get_existing_columns(cursor, table_name)
    print(f"  Final columns: {final_columns}")


def main():
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv

    print("="*60)
    print("DATABASE SCHEMA MIGRATION")
    print("Simplifying bank transaction tables")
    print("="*60)

    if dry_run:
        print("\n*** DRY-RUN MODE - No changes will be made ***\n")
    else:
        print("\n*** EXECUTING MIGRATION ***\n")
        confirm = input("This will permanently modify the database. Continue? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Migration cancelled.")
            return

    connection = get_connection()
    if not connection:
        print("Failed to connect to database.")
        return

    try:
        cursor = connection.cursor()

        for table in TABLES_TO_MIGRATE:
            migrate_table(cursor, table, dry_run)

        if not dry_run:
            connection.commit()
            print("\n*** Migration completed successfully! ***")
        else:
            print("\n*** DRY-RUN complete. Run without --dry-run to execute. ***")

    except Exception as e:
        print(f"\nError during migration: {e}")
        if not dry_run:
            connection.rollback()
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()
            print("\nDatabase connection closed.")


if __name__ == "__main__":
    main()
