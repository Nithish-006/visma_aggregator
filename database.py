"""
Database module for VISMA Financial App
Handles MySQL connection and transaction operations
Supports multiple banks with separate tables

Uses per-request connection pattern for thread safety.
"""

import mysql.connector
from mysql.connector import Error
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from contextlib import contextmanager
from config import Config, BANK_CONFIG, get_bank_config, get_bank_table, VALID_BANK_CODES


class DatabaseConfig:
    """Database configuration - uses settings from config.py"""
    HOST = Config.DB_HOST
    DATABASE = Config.DB_DATABASE
    USER = Config.DB_USER
    PASSWORD = Config.DB_PASSWORD
    PORT = Config.DB_PORT


class DatabaseManager:
    """
    Manages database connections using per-request pattern.
    Each database operation gets a fresh connection to avoid concurrency issues.
    """

    def __init__(self, config: DatabaseConfig = None):
        """Initialize database manager"""
        self.config = config or DatabaseConfig()

    def _create_connection(self):
        """Create a new database connection"""
        try:
            conn = mysql.connector.connect(
                host=self.config.HOST,
                database=self.config.DATABASE,
                user=self.config.USER,
                password=self.config.PASSWORD,
                port=self.config.PORT,
                autocommit=True,
                connection_timeout=30,
                use_pure=True
            )
            return conn
        except Error as e:
            print(f"[!] MySQL connection error: {e}")
            return None

    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.
        Creates a fresh connection, yields it, then closes it.

        Usage:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ...")
        """
        conn = None
        try:
            conn = self._create_connection()
            if conn is None:
                raise Exception("Failed to create database connection")
            yield conn
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass

    def connect(self) -> bool:
        """Test if database is reachable"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
                print(f"[+] Connected to MySQL: {self.config.DATABASE}")
                return True
        except Exception as e:
            print(f"[!] Connection test failed: {e}")
            return False

    def disconnect(self):
        """No-op for compatibility - connections are closed automatically"""
        pass

    def ensure_connected(self) -> bool:
        """Test connection - for compatibility"""
        return self.connect()

    def get_cursor(self, dictionary=False):
        """
        Get a cursor with a new connection.
        DEPRECATED: Use get_connection() context manager instead.
        Kept for backwards compatibility.
        """
        conn = self._create_connection()
        if conn is None:
            raise Exception("Cannot get cursor: database not connected")
        return conn.cursor(dictionary=dictionary)

    @property
    def connection(self):
        """
        DEPRECATED: Returns a new connection for backwards compatibility.
        Use get_connection() context manager instead.
        """
        return self._create_connection()

    def execute_query(self, query: str, params: tuple = None) -> bool:
        """Execute a SQL query (INSERT, UPDATE, DELETE)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params) if params else cursor.execute(query)
                conn.commit()
                cursor.close()
                return True
        except Error as e:
            print(f"[!] Query error: {e}")
            return False

    def fetch_all(self, query: str, params: tuple = None) -> List[tuple]:
        """Fetch all results from a SELECT query"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params) if params else cursor.execute(query)
                results = cursor.fetchall()
                cursor.close()
                return results
        except Error as e:
            print(f"[!] Fetch error: {e}")
            return []

    def fetch_dataframe(self, query: str, params: tuple = None) -> pd.DataFrame:
        """Fetch query results as a pandas DataFrame"""
        try:
            with self.get_connection() as conn:
                if params:
                    return pd.read_sql(query, conn, params=params)
                return pd.read_sql(query, conn)
        except Error as e:
            print(f"[!] DataFrame fetch error: {e}")
            return pd.DataFrame()

    def get_table_name(self, bank_code: str = 'axis') -> str:
        """Get the transaction table name for a specific bank"""
        table = get_bank_table(bank_code)
        return table if table else 'transactions'

    def insert_transaction(self, transaction: Dict, bank_code: str = 'axis') -> Tuple[bool, Optional[str]]:
        """Insert a single transaction into bank-specific table"""
        table = self.get_table_name(bank_code)

        query = f"""
        INSERT INTO {table} (
            transaction_date, transaction_description, client_vendor,
            category, broader_category, code,
            dr_amount, cr_amount, running_balance, net,
            project, dd, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

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
                conn.commit()
                cursor.close()
                return True, None

        except mysql.connector.IntegrityError as e:
            if e.errno == 1062:  # Duplicate key
                return False, "Duplicate"
            return False, str(e)
        except Exception as e:
            print(f"[!] Insert error: {e}")
            return False, str(e)

    def insert_transactions_bulk(self, df: pd.DataFrame, bank_code: str = 'axis', batch_size: int = 100) -> Dict:
        """
        Insert multiple transactions from a DataFrame using batch inserts.
        Uses a single connection and INSERT IGNORE for efficient bulk operations.

        Args:
            df: DataFrame with transactions
            bank_code: Bank code for table routing
            batch_size: Number of rows per batch insert (default 100)

        Returns:
            Dict with total, inserted, duplicates, errors counts
        """
        results = {
            'total': len(df),
            'inserted': 0,
            'duplicates': 0,
            'errors': 0,
            'error_messages': []
        }

        if len(df) == 0:
            return results

        table = self.get_table_name(bank_code)

        # Use INSERT IGNORE to skip duplicates silently
        query_template = f"""
        INSERT IGNORE INTO {table} (
            transaction_date, transaction_description, client_vendor,
            category, broader_category, code,
            dr_amount, cr_amount, running_balance, net,
            project, dd, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                conn.autocommit = False  # Use transaction for better performance

                # Prepare all rows
                rows_to_insert = []
                for idx, row in df.iterrows():
                    try:
                        # Convert pandas Timestamp to Python datetime.date
                        trans_date = row['Date']
                        if hasattr(trans_date, 'date'):
                            trans_date = trans_date.date()

                        rows_to_insert.append((
                            trans_date,
                            row['Transaction Description'],
                            row['Client/Vendor'],
                            row['Category'],
                            row['Broader Category'],
                            row['Code'],
                            float(row['DR Amount']),
                            float(row['CR Amount']),
                            float(row['Running Balance']),
                            float(row['Net']),
                            row.get('Project'),
                            row.get('DD'),
                            row.get('Notes')
                        ))
                    except Exception as e:
                        results['errors'] += 1
                        if len(results['error_messages']) < 3:
                            results['error_messages'].append(f"Row {idx}: {str(e)}")

                # Insert in batches
                total_affected = 0
                for i in range(0, len(rows_to_insert), batch_size):
                    batch = rows_to_insert[i:i + batch_size]
                    try:
                        cursor.executemany(query_template, batch)
                        total_affected += cursor.rowcount

                        # Progress logging for large datasets
                        if len(rows_to_insert) > 100:
                            progress = min(i + batch_size, len(rows_to_insert))
                            print(f"[*] Inserted batch {i//batch_size + 1}: {progress}/{len(rows_to_insert)} rows")
                    except Exception as e:
                        results['errors'] += len(batch)
                        if len(results['error_messages']) < 3:
                            results['error_messages'].append(f"Batch {i//batch_size + 1}: {str(e)}")

                conn.commit()
                cursor.close()

                # Calculate results
                # INSERT IGNORE returns rowcount = number of actually inserted rows
                results['inserted'] = total_affected
                results['duplicates'] = len(rows_to_insert) - total_affected - results['errors']

                print(f"[+] Bulk insert complete: {results['inserted']} inserted, {results['duplicates']} duplicates, {results['errors']} errors")

        except Exception as e:
            print(f"[!] Bulk insert error: {e}")
            results['errors'] = results['total']
            results['error_messages'].append(str(e))

        return results

    def log_upload(self, filename: str, records_processed: int, records_inserted: int,
                   records_duplicated: int, status: str, error_message: str = None,
                   bank_code: str = 'axis') -> bool:
        """Log an upload to the bank_upload_history table"""
        query = """
        INSERT INTO bank_upload_history (
            bank_code, filename, records_processed, records_inserted,
            records_duplicated, status, error_message
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (
                    bank_code, filename, records_processed, records_inserted,
                    records_duplicated, status, error_message
                ))
                conn.commit()
                cursor.close()
                return True
        except Error as e:
            print(f"[!] Log upload error: {e}")
            return False

    def get_all_transactions(self, bank_code: str = 'axis') -> pd.DataFrame:
        """Get all transactions as DataFrame for a specific bank"""
        table = self.get_table_name(bank_code)
        query = f"""
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
        FROM {table}
        ORDER BY transaction_date
        """
        return self.fetch_dataframe(query)

    def get_transaction_count(self, bank_code: str = 'axis') -> int:
        """Get total number of transactions for a specific bank"""
        table = self.get_table_name(bank_code)
        result = self.fetch_all(f"SELECT COUNT(*) FROM {table}")
        return result[0][0] if result else 0

    def get_all_bank_stats(self) -> Dict:
        """Get transaction counts for all banks"""
        stats = {}
        for bank_code in VALID_BANK_CODES:
            try:
                stats[bank_code] = {
                    'transaction_count': self.get_transaction_count(bank_code),
                    'name': BANK_CONFIG[bank_code]['name']
                }
            except Exception as e:
                stats[bank_code] = {'transaction_count': 0, 'name': BANK_CONFIG[bank_code]['name']}
        return stats

    def get_upload_history(self, limit: int = 10, bank_code: str = None) -> List[Dict]:
        """Get recent upload history"""
        if bank_code:
            query = f"""
            SELECT bank_code, filename, upload_date, records_processed,
                   records_inserted, records_duplicated, status, error_message
            FROM bank_upload_history WHERE bank_code = %s
            ORDER BY upload_date DESC LIMIT {limit}
            """
            results = self.fetch_all(query, (bank_code,))
        else:
            query = f"""
            SELECT bank_code, filename, upload_date, records_processed,
                   records_inserted, records_duplicated, status, error_message
            FROM bank_upload_history ORDER BY upload_date DESC LIMIT {limit}
            """
            results = self.fetch_all(query)

        return [{
            'bank_code': row[0],
            'filename': row[1],
            'upload_date': row[2].strftime('%Y-%m-%d %H:%M:%S') if row[2] else None,
            'records_processed': row[3],
            'records_inserted': row[4],
            'records_duplicated': row[5],
            'status': row[6],
            'error_message': row[7]
        } for row in results]

    def clear_all_transactions(self, bank_code: str = 'axis') -> bool:
        """Clear all transactions for a specific bank (use with caution!)"""
        return self.execute_query(f"DELETE FROM {self.get_table_name(bank_code)}")


# ============================================================================
# Helper Functions
# ============================================================================

def test_connection(config: DatabaseConfig = None) -> bool:
    """Test database connection"""
    db = DatabaseManager(config)
    connected = db.connect()
    if connected:
        db.disconnect()
    return connected


def process_and_insert_statement(file_path: str, db: DatabaseManager) -> Dict:
    """Process a bank statement and insert into database"""
    from bank_statement_processor import process_bank_statement
    import os

    try:
        print(f"[*] Processing: {file_path}")
        df = process_bank_statement(file_path)

        print(f"[*] Inserting {len(df)} transactions...")
        results = db.insert_transactions_bulk(df)

        db.log_upload(
            filename=os.path.basename(file_path),
            records_processed=results['total'],
            records_inserted=results['inserted'],
            records_duplicated=results['duplicates'],
            status='success' if results['errors'] == 0 else 'partial',
            error_message='; '.join(results['error_messages'][:5]) if results['error_messages'] else None
        )

        print(f"[+] Done: {results['inserted']} inserted, {results['duplicates']} duplicates")
        return results

    except Exception as e:
        print(f"[!] Error: {e}")
        return {'total': 0, 'inserted': 0, 'duplicates': 0, 'errors': 1, 'error_messages': [str(e)]}


if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE CONNECTION TEST")
    print("=" * 60)

    if test_connection():
        print("\n[+] Connection successful!")
        db = DatabaseManager()
        if db.connect():
            print(f"[*] Transactions: {db.get_transaction_count()}")
            db.disconnect()
    else:
        print("\n[!] Connection failed!")
