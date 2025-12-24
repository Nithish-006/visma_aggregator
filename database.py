"""
Database module for VISMA Financial App
Handles MySQL connection and transaction operations
"""

import mysql.connector
from mysql.connector import Error
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import json
from config import Config


class DatabaseConfig:
    """Database configuration - uses settings from config.py"""
    HOST = Config.DB_HOST
    DATABASE = Config.DB_DATABASE
    USER = Config.DB_USER
    PASSWORD = Config.DB_PASSWORD
    PORT = Config.DB_PORT


class DatabaseManager:
    """Manages database connections and operations"""

    def __init__(self, config: DatabaseConfig = None):
        """Initialize database manager"""
        self.config = config or DatabaseConfig()
        self.connection = None

    def connect(self) -> bool:
        """
        Establish database connection

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.connection = mysql.connector.connect(
                host=self.config.HOST,
                database=self.config.DATABASE,
                user=self.config.USER,
                password=self.config.PASSWORD,
                port=self.config.PORT
            )
            if self.connection.is_connected():
                print(f"[+] Connected to MySQL database: {self.config.DATABASE}")
                return True
        except Error as e:
            print(f"[!] Error connecting to MySQL: {e}")
            return False

    def disconnect(self):
        """Close database connection"""
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("[+] MySQL connection closed")

    def execute_query(self, query: str, params: tuple = None) -> bool:
        """
        Execute a SQL query (INSERT, UPDATE, DELETE)

        Args:
            query: SQL query string
            params: Query parameters (optional)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            cursor = self.connection.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            self.connection.commit()
            cursor.close()
            return True
        except Error as e:
            print(f"[!] Error executing query: {e}")
            return False

    def fetch_all(self, query: str, params: tuple = None) -> List[tuple]:
        """
        Fetch all results from a SELECT query

        Args:
            query: SQL query string
            params: Query parameters (optional)

        Returns:
            List of tuples containing query results
        """
        try:
            cursor = self.connection.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            results = cursor.fetchall()
            cursor.close()
            return results
        except Error as e:
            print(f"[!] Error fetching data: {e}")
            return []

    def fetch_dataframe(self, query: str, params: tuple = None) -> pd.DataFrame:
        """
        Fetch query results as a pandas DataFrame

        Args:
            query: SQL query string
            params: Query parameters (optional)

        Returns:
            pandas DataFrame
        """
        try:
            if params:
                return pd.read_sql(query, self.connection, params=params)
            else:
                return pd.read_sql(query, self.connection)
        except Error as e:
            print(f"[!] Error fetching dataframe: {e}")
            return pd.DataFrame()

    def insert_transaction(self, transaction: Dict) -> Tuple[bool, Optional[str]]:
        """
        Insert a single transaction

        Args:
            transaction: Dictionary containing transaction data

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        query = """
        INSERT INTO transactions (
            transaction_date, transaction_description, client_vendor,
            category, broader_category, code,
            dr_amount, cr_amount, running_balance, net,
            project, dd, notes
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """

        try:
            cursor = self.connection.cursor()

            # Convert pandas Timestamp to Python datetime.date
            trans_date = transaction['Date']
            if hasattr(trans_date, 'date'):
                trans_date = trans_date.date()

            cursor.execute(query, (
                trans_date,
                transaction['Transaction Description'],
                transaction['Client/Vendor'],
                transaction['Category'],
                transaction['Broader Category'],
                transaction['Code'],
                float(transaction['DR Amount']),
                float(transaction['CR Amount']),
                float(transaction['Running Balance']),
                float(transaction['Net']),
                transaction.get('Project'),
                transaction.get('DD'),
                transaction.get('Notes')
            ))
            self.connection.commit()
            cursor.close()
            return True, None
        except mysql.connector.IntegrityError as e:
            # Duplicate entry
            if e.errno == 1062:  # Duplicate key error
                return False, "Duplicate"
            else:
                print(f"[!] IntegrityError: {e}")
                return False, str(e)
        except Error as e:
            print(f"[!] Database Error inserting transaction: {e}")
            print(f"    Transaction data: {transaction}")
            return False, str(e)
        except Exception as e:
            print(f"[!] Unexpected Error: {e}")
            print(f"    Transaction data: {transaction}")
            return False, str(e)

    def insert_transactions_bulk(self, df: pd.DataFrame) -> Dict:
        """
        Insert multiple transactions from a DataFrame

        Args:
            df: DataFrame containing transaction data

        Returns:
            Dictionary with insertion statistics
        """
        results = {
            'total': len(df),
            'inserted': 0,
            'duplicates': 0,
            'errors': 0,
            'error_messages': []
        }

        for idx, row in df.iterrows():
            transaction = row.to_dict()
            success, error = self.insert_transaction(transaction)

            if success:
                results['inserted'] += 1
            elif error == "Duplicate":
                results['duplicates'] += 1
            else:
                results['errors'] += 1
                # Only store first 3 error messages to avoid clutter
                if len(results['error_messages']) < 3:
                    results['error_messages'].append(f"Row {idx}: {error}")

        # Print sample of errors if any occurred
        if results['errors'] > 0:
            print(f"\n[!] Insertion errors occurred:")
            for err_msg in results['error_messages'][:3]:
                print(f"    {err_msg}")
            if results['errors'] > 3:
                print(f"    ... and {results['errors'] - 3} more errors")

        return results

    def log_upload(self, filename: str, records_processed: int, records_inserted: int,
                   records_duplicated: int, status: str, error_message: str = None) -> bool:
        """
        Log an upload to the upload_history table

        Args:
            filename: Name of the uploaded file
            records_processed: Total records processed
            records_inserted: Records successfully inserted
            records_duplicated: Duplicate records skipped
            status: Upload status (success/error)
            error_message: Error message if any

        Returns:
            bool: True if successful
        """
        query = """
        INSERT INTO upload_history (
            filename, records_processed, records_inserted,
            records_duplicated, status, error_message
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """

        try:
            cursor = self.connection.cursor()
            cursor.execute(query, (
                filename,
                records_processed,
                records_inserted,
                records_duplicated,
                status,
                error_message
            ))
            self.connection.commit()
            cursor.close()
            return True
        except Error as e:
            print(f"[!] Error logging upload: {e}")
            return False

    def get_all_transactions(self) -> pd.DataFrame:
        """Get all transactions as DataFrame"""
        query = """
        SELECT
            id,
            transaction_date as Date,
            transaction_description as `Transaction Description`,
            client_vendor as `Client/Vendor`,
            category as Category,
            broader_category as `Broader Category`,
            code as Code,
            dr_amount as `DR Amount`,
            cr_amount as `CR Amount`,
            running_balance as `Running Balance`,
            net as Net,
            project as Project,
            dd as DD,
            notes as Notes
        FROM transactions
        ORDER BY transaction_date
        """
        return self.fetch_dataframe(query)

    def get_transaction_count(self) -> int:
        """Get total number of transactions"""
        query = "SELECT COUNT(*) as count FROM transactions"
        result = self.fetch_all(query)
        return result[0][0] if result else 0

    def get_upload_history(self, limit: int = 10) -> List[Dict]:
        """
        Get recent upload history

        Args:
            limit: Number of recent uploads to retrieve

        Returns:
            List of dictionaries containing upload history
        """
        query = f"""
        SELECT
            filename,
            upload_date,
            records_processed,
            records_inserted,
            records_duplicated,
            status,
            error_message
        FROM upload_history
        ORDER BY upload_date DESC
        LIMIT {limit}
        """

        results = self.fetch_all(query)
        history = []

        for row in results:
            history.append({
                'filename': row[0],
                'upload_date': row[1].strftime('%Y-%m-%d %H:%M:%S') if row[1] else None,
                'records_processed': row[2],
                'records_inserted': row[3],
                'records_duplicated': row[4],
                'status': row[5],
                'error_message': row[6]
            })

        return history

    def clear_all_transactions(self) -> bool:
        """Clear all transactions (use with caution!)"""
        query = "DELETE FROM transactions"
        return self.execute_query(query)


# ============================================================================
# Helper Functions
# ============================================================================

def test_connection(config: DatabaseConfig = None) -> bool:
    """
    Test database connection

    Args:
        config: Database configuration (optional)

    Returns:
        bool: True if connection successful
    """
    db = DatabaseManager(config)
    connected = db.connect()
    if connected:
        db.disconnect()
    return connected


def process_and_insert_statement(file_path: str, db: DatabaseManager) -> Dict:
    """
    Process a bank statement and insert into database

    Args:
        file_path: Path to bank statement Excel file
        db: DatabaseManager instance

    Returns:
        Dictionary with processing results
    """
    from bank_statement_processor import process_bank_statement

    try:
        # Process the bank statement
        print(f"[*] Processing bank statement: {file_path}")
        df = process_bank_statement(file_path)

        # Insert into database
        print(f"[*] Inserting {len(df)} transactions into database...")
        results = db.insert_transactions_bulk(df)

        # Log the upload
        import os
        filename = os.path.basename(file_path)
        db.log_upload(
            filename=filename,
            records_processed=results['total'],
            records_inserted=results['inserted'],
            records_duplicated=results['duplicates'],
            status='success' if results['errors'] == 0 else 'partial',
            error_message='; '.join(results['error_messages'][:5]) if results['error_messages'] else None
        )

        print(f"[+] Processing complete!")
        print(f"    Total: {results['total']}")
        print(f"    Inserted: {results['inserted']}")
        print(f"    Duplicates: {results['duplicates']}")
        print(f"    Errors: {results['errors']}")

        return results

    except Exception as e:
        print(f"[!] Error processing statement: {e}")
        return {
            'total': 0,
            'inserted': 0,
            'duplicates': 0,
            'errors': 1,
            'error_messages': [str(e)]
        }


# ============================================================================
# Main - For testing
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("DATABASE CONNECTION TEST")
    print("=" * 80)

    # Test connection
    if test_connection():
        print("\n[+] Database connection successful!")

        # Create database manager
        db = DatabaseManager()
        if db.connect():
            # Get transaction count
            count = db.get_transaction_count()
            print(f"\n[*] Current transactions in database: {count}")

            # Get upload history
            history = db.get_upload_history(5)
            if history:
                print("\n[*] Recent uploads:")
                for upload in history:
                    print(f"    - {upload['filename']} ({upload['upload_date']}): "
                          f"{upload['records_inserted']} inserted, "
                          f"{upload['records_duplicated']} duplicates")

            db.disconnect()
    else:
        print("\n[!] Database connection failed!")
        print("\n[*] Please ensure:")
        print("    1. MySQL is running")
        print("    2. Database 'visma_financial' exists")
        print("    3. Credentials in database.py are correct")
        print("\n[*] To create the database, run:")
        print("    mysql -u root -p < database_schema.sql")
