"""
Insert December transactions from ToAdd_for_Dec.xlsx into axis_transactions table.
"""

import pandas as pd
import mysql.connector
from mysql.connector import Error
from datetime import datetime

# Remote MySQL instance (Railway)
DB_CONFIG = {
    'host': 'yamanote.proxy.rlwy.net',
    'port': 57844,
    'user': 'root',
    'password': 'uxozNadQzagwhWazsWnfDZMSNvKHRwvi',
    'database': 'visma_financial'
}

def main():
    print("=" * 60)
    print("Insert December Transactions to Remote DB")
    print("=" * 60)

    # Load Excel file
    print("\nLoading ToAdd_for_Dec.xlsx...")
    df = pd.read_excel('ToAdd_for_Dec.xlsx')

    # Clean up - remove unnamed columns
    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

    print(f"Found {len(df)} records to insert")

    # Connect to database
    print(f"\nConnecting to remote database...")
    try:
        conn = mysql.connector.connect(**DB_CONFIG, connection_timeout=30)
        cursor = conn.cursor()
        print("Connected!")

        # Get current count
        cursor.execute("SELECT COUNT(*) FROM axis_transactions")
        before_count = cursor.fetchone()[0]
        print(f"Current axis_transactions count: {before_count}")

        # Prepare insert statement
        insert_sql = """
        INSERT INTO axis_transactions
        (transaction_date, transaction_description, client_vendor, category, code, dr_amount, cr_amount, project)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        inserted = 0
        duplicates = 0
        errors = 0

        print("\nInserting records...")
        for idx, row in df.iterrows():
            try:
                # Parse date (DD/MM/YYYY format)
                date_str = str(row['Date']).strip()
                try:
                    trans_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                except:
                    # Try alternative format
                    trans_date = pd.to_datetime(row['Date']).date()

                # Get values
                description = str(row['DESCRIPTION']).strip() if pd.notna(row['DESCRIPTION']) else ''
                client_vendor = str(row['Client/vendor']).strip() if pd.notna(row['Client/vendor']) else 'Unknown'
                category = str(row['CATEGORY']).strip() if pd.notna(row['CATEGORY']) else 'Uncategorized'
                code = str(row['CODE']).strip() if pd.notna(row['CODE']) else 'UC'
                project = str(row['PROJECT']).strip() if pd.notna(row['PROJECT']) else None

                # Amount - check if DR or CR
                amount = float(str(row['Amount']).replace(',', '')) if pd.notna(row['Amount']) else 0
                dd_type = str(row['dd']).strip().upper() if pd.notna(row['dd']) else 'DR'

                if dd_type == 'CR':
                    dr_amount = 0
                    cr_amount = amount
                else:  # DR or default
                    dr_amount = amount
                    cr_amount = 0

                # Execute insert
                cursor.execute(insert_sql, (
                    trans_date,
                    description,
                    client_vendor,
                    category,
                    code,
                    dr_amount,
                    cr_amount,
                    project
                ))
                inserted += 1

            except mysql.connector.IntegrityError as e:
                if 'Duplicate' in str(e):
                    duplicates += 1
                else:
                    errors += 1
                    print(f"  Row {idx + 1}: {e}")
            except Exception as e:
                errors += 1
                print(f"  Row {idx + 1} error: {e}")

        # Commit
        conn.commit()

        # Get new count
        cursor.execute("SELECT COUNT(*) FROM axis_transactions")
        after_count = cursor.fetchone()[0]

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Records processed: {len(df)}")
        print(f"  Inserted: {inserted}")
        print(f"  Duplicates skipped: {duplicates}")
        print(f"  Errors: {errors}")
        print(f"\n  Before count: {before_count}")
        print(f"  After count: {after_count}")
        print(f"  Net added: {after_count - before_count}")

        cursor.close()
        conn.close()
        print("\nDone!")

    except Error as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    main()
