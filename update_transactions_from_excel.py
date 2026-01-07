"""
Standalone script to update Category, Code, and Project fields in
axis_transactions and kvb_transactions tables from Excel files.

Features:
- Parallel processing for AXIS and KVB updates
- Batch updates for efficiency
- Retry logic for resilience
- Transaction safety with rollback on errors
- Progress tracking

Excel Files:
- AXIS (APR-OCT).xlsx - Sheet: "AXIS APRIL -25 "
- KVB (APR - NOV).xlsx - First sheet

Matching: Exact match on DESCRIPTION (Excel) <-> transaction_description (DB)

Usage:
  python update_transactions_from_excel.py             # Execute real updates
  python update_transactions_from_excel.py --dry-run   # Dry run (no changes)
"""

import pandas as pd
import mysql.connector
from mysql.connector import Error
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Database connection settings
DB_CONFIG = {
    'host': 'yamanote.proxy.rlwy.net',
    'port': 57844,
    'user': 'root',
    'password': 'uxozNadQzagwhWazsWnfDZMSNvKHRwvi',
    'database': 'visma_financial'
}

# File paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AXIS_EXCEL = os.path.join(BASE_DIR, 'AXIS (APR-OCT).xlsx')
KVB_EXCEL = os.path.join(BASE_DIR, 'KVB (APR - NOV).xlsx')

# Sheet names
AXIS_SHEET = 'AXIS APRIL -25 '

# Configuration
BATCH_SIZE = 100  # Number of updates per batch commit
MAX_RETRIES = 3   # Max retries for failed operations
RETRY_DELAY = 2   # Seconds to wait between retries


def get_db_connection(max_retries=MAX_RETRIES):
    """Create and return a database connection with retry logic."""
    for attempt in range(max_retries):
        try:
            connection = mysql.connector.connect(
                **DB_CONFIG,
                connection_timeout=30,
                autocommit=False
            )
            if connection.is_connected():
                return connection
        except Error as e:
            print(f"  Connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(RETRY_DELAY)

    print("Failed to connect after all retries")
    return None


def load_axis_excel():
    """Load AXIS Excel data from specific sheet."""
    print(f"\n[AXIS] Loading Excel from: {AXIS_EXCEL}")
    print(f"[AXIS] Sheet: {AXIS_SHEET}")

    try:
        df = pd.read_excel(AXIS_EXCEL, sheet_name=AXIS_SHEET)
        df = df.loc[:, df.columns.notna()]  # Remove NaN columns

        print(f"[AXIS] Columns: {df.columns.tolist()}")
        print(f"[AXIS] Total rows: {len(df)}")

        mapping = {}
        for _, row in df.iterrows():
            description = str(row.get('DESCRIPTION', '')).strip()
            if description and description != 'nan':
                mapping[description] = {
                    'category': str(row.get('CATEGORY', '')).strip() if pd.notna(row.get('CATEGORY')) else None,
                    'code': str(row.get('CODE', '')).strip() if pd.notna(row.get('CODE')) else None,
                    'project': str(row.get('PROJECT', '')).strip() if pd.notna(row.get('PROJECT')) else None
                }

        print(f"[AXIS] Loaded {len(mapping)} unique descriptions")
        return mapping
    except Exception as e:
        print(f"[AXIS] Error loading Excel: {e}")
        return {}


def load_kvb_excel():
    """Load KVB Excel data from first sheet."""
    print(f"\n[KVB] Loading Excel from: {KVB_EXCEL}")

    try:
        df = pd.read_excel(KVB_EXCEL)
        print(f"[KVB] Columns: {df.columns.tolist()}")
        print(f"[KVB] Total rows: {len(df)}")

        mapping = {}
        for _, row in df.iterrows():
            description = str(row.get('DESCRIPTION', '')).strip()
            if description and description != 'nan':
                mapping[description] = {
                    'category': str(row.get('CATEGORY', '')).strip() if pd.notna(row.get('CATEGORY')) else None,
                    'code': str(row.get('CODE', '')).strip() if pd.notna(row.get('CODE')) else None,
                    'project': str(row.get('PROJECT', '')).strip() if pd.notna(row.get('PROJECT')) else None
                }

        print(f"[KVB] Loaded {len(mapping)} unique descriptions")
        return mapping
    except Exception as e:
        print(f"[KVB] Error loading Excel: {e}")
        return {}


def update_bank_transactions(bank_name, table_name, mapping, dry_run=False):
    """
    Update transactions for a specific bank with batch processing and retry logic.
    Returns a dict with statistics.
    """
    result = {
        'bank': bank_name,
        'total_in_db': 0,
        'matched': 0,
        'updated': 0,
        'failed': 0,
        'errors': []
    }

    print(f"\n{'='*60}")
    print(f"[{bank_name}] UPDATING {table_name.upper()}")
    print(f"{'='*60}")

    # Get a fresh connection for this bank
    connection = get_db_connection()
    if not connection:
        result['errors'].append("Failed to connect to database")
        return result

    try:
        cursor = connection.cursor(dictionary=True)

        # Fetch all transactions
        cursor.execute(f"SELECT id, transaction_description FROM {table_name}")
        transactions = cursor.fetchall()
        result['total_in_db'] = len(transactions)
        print(f"[{bank_name}] Found {len(transactions)} transactions in DB")

        # Prepare batch updates
        updates_to_execute = []

        for txn in transactions:
            txn_id = txn['id']
            txn_desc = txn['transaction_description'].strip() if txn['transaction_description'] else ''

            if txn_desc in mapping:
                result['matched'] += 1
                excel_data = mapping[txn_desc]

                # Build update parts
                update_parts = []
                values = []

                if excel_data['category']:
                    update_parts.append("category = %s")
                    values.append(excel_data['category'])

                if excel_data['code']:
                    update_parts.append("code = %s")
                    values.append(excel_data['code'])

                if excel_data['project']:
                    update_parts.append("project = %s")
                    values.append(excel_data['project'])

                if update_parts:
                    values.append(txn_id)
                    updates_to_execute.append((update_parts, values))

        print(f"[{bank_name}] Matched {result['matched']} transactions")
        print(f"[{bank_name}] Preparing to update {len(updates_to_execute)} records...")

        if dry_run:
            print(f"[{bank_name}] DRY-RUN: Would update {len(updates_to_execute)} records")
            result['updated'] = len(updates_to_execute)
            cursor.close()
            connection.close()
            return result

        # Execute batch updates with progress
        batch_count = 0
        for i, (update_parts, values) in enumerate(updates_to_execute, 1):
            try:
                update_sql = f"UPDATE {table_name} SET {', '.join(update_parts)} WHERE id = %s"
                cursor.execute(update_sql, values)
                result['updated'] += 1
                batch_count += 1

                # Commit in batches
                if batch_count >= BATCH_SIZE:
                    connection.commit()
                    print(f"[{bank_name}] Progress: {i}/{len(updates_to_execute)} ({(i/len(updates_to_execute)*100):.1f}%)")
                    batch_count = 0

            except Error as e:
                result['failed'] += 1
                if len(result['errors']) < 10:  # Limit error messages stored
                    result['errors'].append(f"ID {values[-1]}: {str(e)}")

        # Final commit for remaining batch
        if batch_count > 0:
            connection.commit()

        print(f"[{bank_name}] Completed: {result['updated']} updated, {result['failed']} failed")

    except Exception as e:
        result['errors'].append(f"Fatal error: {str(e)}")
        print(f"[{bank_name}] Fatal error: {e}")
        try:
            connection.rollback()
        except:
            pass

    finally:
        try:
            if connection.is_connected():
                cursor.close()
                connection.close()
        except:
            pass

    return result


def main():
    """Main function to run the update process."""
    print("="*60)
    print("TRANSACTION UPDATE SCRIPT (Parallel & Resilient)")
    print("Updating Category, Code, and Project from Excel files")
    print("="*60)

    # Check for command-line argument
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv

    if dry_run:
        print("\n*** RUNNING IN DRY-RUN MODE - NO CHANGES WILL BE MADE ***")
    else:
        print("\n*** EXECUTING REAL UPDATES ***")

    print(f"\nConfiguration:")
    print(f"  - Batch size: {BATCH_SIZE}")
    print(f"  - Max retries: {MAX_RETRIES}")

    # Load Excel data (sequential - fast enough)
    axis_mapping = load_axis_excel()
    kvb_mapping = load_kvb_excel()

    if not axis_mapping and not kvb_mapping:
        print("\nERROR: No data loaded from Excel files. Exiting.")
        return

    # Run updates in parallel
    print("\n" + "="*60)
    print("RUNNING PARALLEL UPDATES")
    print("="*60)

    start_time = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}

        if axis_mapping:
            futures[executor.submit(
                update_bank_transactions,
                'AXIS',
                'axis_transactions',
                axis_mapping,
                dry_run
            )] = 'AXIS'

        if kvb_mapping:
            futures[executor.submit(
                update_bank_transactions,
                'KVB',
                'kvb_transactions',
                kvb_mapping,
                dry_run
            )] = 'KVB'

        for future in as_completed(futures):
            bank = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"[{bank}] Thread error: {e}")
                results.append({
                    'bank': bank,
                    'total_in_db': 0,
                    'matched': 0,
                    'updated': 0,
                    'failed': 0,
                    'errors': [str(e)]
                })

    elapsed_time = time.time() - start_time

    # Final summary
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)

    total_updated = 0
    total_failed = 0
    total_matched = 0

    for r in results:
        print(f"\n{r['bank']}:")
        print(f"  - Total in DB: {r['total_in_db']}")
        print(f"  - Matched: {r['matched']}")
        print(f"  - Updated: {r['updated']}")
        print(f"  - Failed: {r['failed']}")
        if r['errors']:
            print(f"  - Errors: {len(r['errors'])}")
            for err in r['errors'][:5]:  # Show first 5 errors
                print(f"    * {err}")

        total_updated += r['updated']
        total_failed += r['failed']
        total_matched += r['matched']

    print(f"\n{'='*60}")
    print(f"TOTALS:")
    print(f"  - Total matched: {total_matched}")
    print(f"  - Total updated: {total_updated}")
    print(f"  - Total failed: {total_failed}")
    print(f"  - Time elapsed: {elapsed_time:.2f} seconds")

    if dry_run:
        print("\n*** This was a DRY-RUN. Run without --dry-run to apply changes. ***")
    else:
        if total_failed == 0:
            print("\n*** SUCCESS: All updates committed to database. ***")
        else:
            print(f"\n*** PARTIAL SUCCESS: {total_updated} updated, {total_failed} failed. ***")


if __name__ == "__main__":
    main()
