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
from decimal import Decimal as DecimalType
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
            category, code, dr_amount, cr_amount, project
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                    transaction['Code'],
                    float(transaction['DR Amount']),
                    float(transaction['CR Amount']),
                    transaction.get('Project')
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
            category, code, dr_amount, cr_amount, project
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                            row['Code'],
                            float(row['DR Amount']),
                            float(row['CR Amount']),
                            row.get('Project')
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
            code as Code,
            dr_amount as `DR Amount`,
            cr_amount as `CR Amount`,
            project as Project
        FROM {table}
        ORDER BY transaction_date
        """
        return self.fetch_dataframe(query)

    def get_transaction_count(self, bank_code: str = 'axis') -> int:
        """Get total number of transactions for a specific bank"""
        table = self.get_table_name(bank_code)
        result = self.fetch_all(f"SELECT COUNT(*) FROM {table}")
        return result[0][0] if result else 0

    def get_paginated_transactions(self, bank_code: str = 'axis', page: int = 1, per_page: int = 50,
                                    category: str = None, project: str = None, vendor: str = None,
                                    start_date: str = None, end_date: str = None, search: str = None,
                                    sort_by: str = 'date', sort_order: str = 'desc') -> Dict:
        """
        Get paginated transactions with filters applied at database level.
        Returns dict with 'transactions' list and 'total' count.
        """
        table = self.get_table_name(bank_code)

        # Build WHERE clause
        conditions = []
        params = []

        # Category filter (supports multiple comma-separated values)
        if category and category != 'All':
            categories = [c.strip() for c in category.split(',') if c.strip()]
            if categories:
                placeholders = ','.join(['%s'] * len(categories))
                conditions.append(f"category IN ({placeholders})")
                params.extend(categories)

        # Project filter (supports multiple comma-separated values)
        if project:
            projects = [p.strip() for p in project.split(',') if p.strip()]
            if projects:
                placeholders = ','.join(['%s'] * len(projects))
                conditions.append(f"project IN ({placeholders})")
                params.extend(projects)

        # Vendor filter (supports multiple comma-separated values)
        if vendor:
            vendors = [v.strip() for v in vendor.split(',') if v.strip()]
            if vendors:
                placeholders = ','.join(['%s'] * len(vendors))
                conditions.append(f"client_vendor IN ({placeholders})")
                params.extend(vendors)

        # Date range filter
        if start_date:
            conditions.append("transaction_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("transaction_date <= %s")
            params.append(end_date)

        # Search filter
        if search:
            conditions.append("(transaction_description LIKE %s OR client_vendor LIKE %s OR category LIKE %s)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Sort clause
        sort_column = 'transaction_date'
        if sort_by == 'dr_amount':
            sort_column = 'dr_amount'
        elif sort_by == 'cr_amount':
            sort_column = 'cr_amount'

        sort_direction = 'DESC' if sort_order == 'desc' else 'ASC'

        # Get total count for pagination
        count_query = f"SELECT COUNT(*) FROM {table} WHERE {where_clause}"
        count_result = self.fetch_all(count_query, tuple(params) if params else None)
        total = count_result[0][0] if count_result else 0

        # Calculate offset
        offset = (page - 1) * per_page

        # Get paginated data
        data_query = f"""
        SELECT
            id,
            transaction_date as Date,
            transaction_description as `Transaction Description`,
            client_vendor as `Client/Vendor`,
            category as Category,
            code as Code,
            dr_amount as `DR Amount`,
            cr_amount as `CR Amount`,
            project as Project
        FROM {table}
        WHERE {where_clause}
        ORDER BY {sort_column} {sort_direction}, id {sort_direction}
        LIMIT %s OFFSET %s
        """

        # Add pagination params
        data_params = params + [per_page, offset]

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(data_query, tuple(data_params))
                rows = cursor.fetchall()
                cursor.close()

                return {
                    'transactions': rows,
                    'total': total,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0
                }
        except Error as e:
            print(f"[!] Paginated fetch error: {e}")
            return {'transactions': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 0}

    def get_filter_options(self, bank_code: str = 'axis') -> Dict:
        """Get unique categories, projects, and vendors for filter dropdowns"""
        table = self.get_table_name(bank_code)

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Get unique categories (TRIM to avoid whitespace duplicates)
                cursor.execute(f"SELECT DISTINCT TRIM(category) AS category FROM {table} WHERE TRIM(category) IS NOT NULL AND TRIM(category) != '' ORDER BY category")
                categories = [row[0] for row in cursor.fetchall()]

                # Get unique projects
                cursor.execute(f"SELECT DISTINCT TRIM(project) AS project FROM {table} WHERE TRIM(project) IS NOT NULL AND TRIM(project) != '' ORDER BY project")
                projects = [row[0] for row in cursor.fetchall()]

                # Get unique vendors
                cursor.execute(f"SELECT DISTINCT TRIM(client_vendor) AS client_vendor FROM {table} WHERE TRIM(client_vendor) IS NOT NULL AND TRIM(client_vendor) != '' AND TRIM(client_vendor) != 'Unknown' ORDER BY client_vendor")
                vendors = [row[0] for row in cursor.fetchall()]

                cursor.close()

                return {
                    'categories': categories,
                    'projects': projects,
                    'vendors': vendors
                }
        except Error as e:
            print(f"[!] Filter options fetch error: {e}")
            return {'categories': [], 'projects': [], 'vendors': []}

    def get_filtered_options(self, bank_code: str = 'axis',
                              category: str = None, project: str = None, vendor: str = None,
                              start_date: str = None, end_date: str = None, search: str = None) -> Dict:
        """Get unique categories, projects, and vendors constrained by currently active filters.
        Each dropdown's options are filtered by ALL other active filters (but not by itself)."""
        table = self.get_table_name(bank_code)

        def build_conditions(exclude_field=None):
            conditions = []
            params = []

            if category and category != 'All' and exclude_field != 'category':
                cats = [c.strip() for c in category.split(',') if c.strip()]
                if cats:
                    placeholders = ','.join(['%s'] * len(cats))
                    conditions.append(f"category IN ({placeholders})")
                    params.extend(cats)

            if project and exclude_field != 'project':
                projs = [p.strip() for p in project.split(',') if p.strip()]
                if projs:
                    placeholders = ','.join(['%s'] * len(projs))
                    conditions.append(f"project IN ({placeholders})")
                    params.extend(projs)

            if vendor and exclude_field != 'vendor':
                vends = [v.strip() for v in vendor.split(',') if v.strip()]
                if vends:
                    placeholders = ','.join(['%s'] * len(vends))
                    conditions.append(f"client_vendor IN ({placeholders})")
                    params.extend(vends)

            if start_date:
                conditions.append("transaction_date >= %s")
                params.append(start_date)
            if end_date:
                conditions.append("transaction_date <= %s")
                params.append(end_date)

            if search:
                conditions.append("(transaction_description LIKE %s OR client_vendor LIKE %s OR category LIKE %s)")
                pattern = f"%{search}%"
                params.extend([pattern, pattern, pattern])

            where = " AND ".join(conditions) if conditions else "1=1"
            return where, params

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Categories: filtered by project, vendor, date, search (not by category itself)
                w, p = build_conditions(exclude_field='category')
                cursor.execute(f"SELECT DISTINCT TRIM(category) AS category FROM {table} WHERE {w} AND TRIM(category) IS NOT NULL AND TRIM(category) != '' ORDER BY category", tuple(p))
                categories = [row[0] for row in cursor.fetchall()]

                # Projects: filtered by category, vendor, date, search (not by project itself)
                w, p = build_conditions(exclude_field='project')
                cursor.execute(f"SELECT DISTINCT TRIM(project) AS project FROM {table} WHERE {w} AND TRIM(project) IS NOT NULL AND TRIM(project) != '' ORDER BY project", tuple(p))
                projects = [row[0] for row in cursor.fetchall()]

                # Vendors: filtered by category, project, date, search (not by vendor itself)
                w, p = build_conditions(exclude_field='vendor')
                cursor.execute(f"SELECT DISTINCT TRIM(client_vendor) AS client_vendor FROM {table} WHERE {w} AND TRIM(client_vendor) IS NOT NULL AND TRIM(client_vendor) != '' AND TRIM(client_vendor) != 'Unknown' ORDER BY client_vendor", tuple(p))
                vendors = [row[0] for row in cursor.fetchall()]

                cursor.close()
                return {'categories': categories, 'projects': projects, 'vendors': vendors}
        except Error as e:
            print(f"[!] Filtered options fetch error: {e}")
            return {'categories': [], 'projects': [], 'vendors': []}

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

    # ========================================================================
    # BILL PROCESSOR DATABASE METHODS
    # ========================================================================

    def insert_bill(self, bill_data: Dict) -> Tuple[bool, Optional[int], Optional[str]]:
        """
        Insert a bill invoice and its line items into the database.

        Args:
            bill_data: Extracted bill data from Gemini Vision

        Returns:
            Tuple of (success, invoice_id, error_message)
        """
        if not bill_data.get('success') or not bill_data.get('data'):
            return False, None, "No valid bill data"

        data = bill_data['data']
        header = data.get('invoice_header', {})
        vendor = data.get('vendor', {})
        buyer = data.get('buyer', {})
        ship_to = data.get('ship_to', {})
        taxes = data.get('taxes', {})
        transport = data.get('transport', {})
        line_items = data.get('line_items', [])
        other_charges = data.get('other_charges', [])

        # Parse invoice date
        invoice_date = None
        date_str = header.get('invoice_date', '')
        if date_str:
            try:
                from dateutil import parser
                invoice_date = parser.parse(date_str, dayfirst=True).date()
            except:
                pass

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                conn.autocommit = False

                # Insert main invoice record
                invoice_query = """
                INSERT INTO bill_invoices (
                    filename, page_number, invoice_number, invoice_date, irn, ack_number, eway_bill_number,
                    vendor_name, vendor_gstin, vendor_address, vendor_state, vendor_pan, vendor_phone,
                    vendor_bank_name, vendor_bank_account, vendor_bank_ifsc,
                    buyer_name, buyer_gstin, buyer_address, buyer_state,
                    ship_to_name, ship_to_address,
                    subtotal, total_cgst, total_sgst, total_igst, other_charges, round_off, total_amount, amount_in_words,
                    vehicle_number, transporter_name
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s
                )
                """

                # Calculate other charges total
                other_charges_total = sum(c.get('amount', 0) or 0 for c in other_charges if c.get('description'))

                cursor.execute(invoice_query, (
                    bill_data.get('filename', ''),
                    bill_data.get('page', 1),
                    header.get('invoice_number', ''),
                    invoice_date,
                    header.get('irn', ''),
                    header.get('ack_number', ''),
                    header.get('eway_bill_number', ''),
                    vendor.get('name', ''),
                    vendor.get('gstin', ''),
                    vendor.get('address', ''),
                    vendor.get('state', ''),
                    vendor.get('pan', ''),
                    vendor.get('phone', ''),
                    vendor.get('bank_name', ''),
                    vendor.get('bank_account', ''),
                    vendor.get('bank_ifsc', ''),
                    buyer.get('name', ''),
                    buyer.get('gstin', ''),
                    buyer.get('address', ''),
                    buyer.get('state', ''),
                    ship_to.get('name', ''),
                    ship_to.get('address', ''),
                    float(taxes.get('subtotal', 0) or taxes.get('taxable_amount', 0) or 0),
                    float(taxes.get('total_cgst', 0) or taxes.get('cgst_amount', 0) or 0),
                    float(taxes.get('total_sgst', 0) or taxes.get('sgst_amount', 0) or 0),
                    float(taxes.get('total_igst', 0) or taxes.get('igst_amount', 0) or 0),
                    float(other_charges_total),
                    float(taxes.get('round_off', 0) or 0),
                    float(taxes.get('total_amount', 0) or 0),
                    taxes.get('amount_in_words', ''),
                    transport.get('vehicle_number', ''),
                    transport.get('transporter_name', '')
                ))

                invoice_id = cursor.lastrowid

                # Insert line items
                if line_items:
                    line_item_query = """
                    INSERT INTO bill_line_items (
                        invoice_id, sl_no, description, hsn_sac_code, quantity, uom,
                        rate_per_unit, discount_percent, discount_amount, taxable_value,
                        cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount, amount
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """

                    for item in line_items:
                        if item.get('description'):  # Only insert if has description
                            cursor.execute(line_item_query, (
                                invoice_id,
                                item.get('sl_no', 0),
                                item.get('description', ''),
                                item.get('hsn_sac_code', '') or item.get('hsn_code', ''),
                                float(item.get('quantity', 0) or 0),
                                item.get('uom', ''),
                                float(item.get('rate_per_unit', 0) or item.get('rate', 0) or 0),
                                float(item.get('discount_percent', 0) or 0),
                                float(item.get('discount_amount', 0) or 0),
                                float(item.get('taxable_value', 0) or 0),
                                float(item.get('cgst_rate', 0) or 0),
                                float(item.get('cgst_amount', 0) or 0),
                                float(item.get('sgst_rate', 0) or 0),
                                float(item.get('sgst_amount', 0) or 0),
                                float(item.get('igst_rate', 0) or 0),
                                float(item.get('igst_amount', 0) or 0),
                                float(item.get('amount', 0) or 0)
                            ))

                conn.commit()
                cursor.close()

                print(f"[+] Saved bill to DB: Invoice #{header.get('invoice_number', 'N/A')} (ID: {invoice_id})")
                return True, invoice_id, None

        except mysql.connector.IntegrityError as e:
            if e.errno == 1062:  # Duplicate key
                print(f"[!] Duplicate bill: {header.get('invoice_number', '')}")
                return False, None, "Duplicate invoice"
            return False, None, str(e)
        except Exception as e:
            print(f"[!] Error saving bill: {e}")
            import traceback
            traceback.print_exc()
            return False, None, str(e)

    def get_all_bills(self, limit: int = 100, offset: int = 0, projects: list = None,
                       date_from: str = None, date_to: str = None,
                       added_from: str = None, added_to: str = None) -> List[Dict]:
        """Get all bills from database with pagination and optional project/date filters"""
        query = """
        SELECT
            bi.id, bi.filename, bi.page_number, bi.invoice_number, bi.invoice_date,
            bi.vendor_name, bi.vendor_gstin, bi.buyer_name, bi.buyer_gstin,
            bi.subtotal, bi.total_cgst, bi.total_sgst, bi.total_igst,
            bi.total_amount, bi.vehicle_number, bi.eway_bill_number, bi.irn,
            bi.project, bi.created_at,
            COUNT(bli.id) as line_item_count
        FROM bill_invoices bi
        LEFT JOIN bill_line_items bli ON bi.id = bli.invoice_id
        WHERE 1=1
        """
        params = []

        if projects:
            placeholders = ','.join(['%s'] * len(projects))
            query += f" AND bi.project IN ({placeholders})"
            params.extend(projects)

        if date_from:
            query += " AND bi.invoice_date >= %s"
            params.append(date_from)

        if date_to:
            query += " AND bi.invoice_date <= %s"
            params.append(date_to)

        if added_from:
            query += " AND DATE(bi.created_at) >= %s"
            params.append(added_from)

        if added_to:
            query += " AND DATE(bi.created_at) <= %s"
            params.append(added_to)

        query += """
        GROUP BY bi.id
        ORDER BY bi.invoice_date DESC, bi.created_at DESC
        LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, tuple(params))
                results = cursor.fetchall()
                cursor.close()

                # Convert date objects and Decimals for JSON serialization
                for row in results:
                    if row.get('invoice_date'):
                        row['invoice_date'] = row['invoice_date'].strftime('%d-%b-%Y')
                    if row.get('created_at'):
                        row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                    # Convert Decimal fields to float
                    for key, val in row.items():
                        if isinstance(val, DecimalType):
                            row[key] = float(val)

                return results
        except Exception as e:
            print(f"[!] Error fetching bills: {e}")
            return []

    def get_bill_detail(self, invoice_id: int) -> Optional[Dict]:
        """Get full bill detail including line items"""
        try:
            with self.get_connection() as conn:
                # Get invoice
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM bill_invoices WHERE id = %s", (invoice_id,))
                invoice = cursor.fetchone()

                if not invoice:
                    cursor.close()
                    return None

                # Convert dates and Decimals
                if invoice.get('invoice_date'):
                    invoice['invoice_date'] = invoice['invoice_date'].strftime('%d-%b-%Y')
                if invoice.get('created_at'):
                    invoice['created_at'] = invoice['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                if invoice.get('updated_at'):
                    invoice['updated_at'] = invoice['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
                for key, val in invoice.items():
                    if isinstance(val, DecimalType):
                        invoice[key] = float(val)

                # Get line items
                cursor.execute("""
                    SELECT * FROM bill_line_items WHERE invoice_id = %s ORDER BY sl_no
                """, (invoice_id,))
                line_items = cursor.fetchall()
                cursor.close()

                # Convert decimals to floats for JSON
                for item in line_items:
                    for key in ['quantity', 'rate_per_unit', 'discount_percent', 'discount_amount',
                               'taxable_value', 'cgst_rate', 'cgst_amount', 'sgst_rate', 'sgst_amount',
                               'igst_rate', 'igst_amount', 'amount']:
                        if item.get(key) is not None:
                            item[key] = float(item[key])

                invoice['line_items'] = line_items
                return invoice

        except Exception as e:
            print(f"[!] Error fetching bill detail: {e}")
            return None

    def delete_bill(self, invoice_id: int) -> bool:
        """Delete a bill and its line items"""
        return self.execute_query("DELETE FROM bill_invoices WHERE id = %s", (invoice_id,))

    def update_bill_project(self, invoice_id: int, project: str) -> bool:
        """Update the project field for a bill"""
        return self.execute_query(
            "UPDATE bill_invoices SET project = %s WHERE id = %s",
            (project if project else None, invoice_id)
        )

    def get_unique_projects(self) -> List[str]:
        """Get all unique project names from bills"""
        query = """
        SELECT DISTINCT project FROM bill_invoices
        WHERE project IS NOT NULL AND project != ''
        ORDER BY project
        """
        try:
            results = self.fetch_all(query)
            return [row[0] for row in results if row[0]]
        except Exception as e:
            print(f"[!] Error fetching unique projects: {e}")
            return []

    def get_bill_count(self, projects: list = None, date_from: str = None, date_to: str = None,
                        added_from: str = None, added_to: str = None) -> int:
        """Get total number of stored bills, optionally filtered by projects and date range"""
        query = "SELECT COUNT(*) FROM bill_invoices WHERE 1=1"
        params = []

        if projects:
            placeholders = ','.join(['%s'] * len(projects))
            query += f" AND project IN ({placeholders})"
            params.extend(projects)

        if date_from:
            query += " AND invoice_date >= %s"
            params.append(date_from)

        if date_to:
            query += " AND invoice_date <= %s"
            params.append(date_to)

        if added_from:
            query += " AND DATE(created_at) >= %s"
            params.append(added_from)

        if added_to:
            query += " AND DATE(created_at) <= %s"
            params.append(added_to)

        result = self.fetch_all(query, tuple(params) if params else None)
        return result[0][0] if result else 0

    def check_duplicate_invoice(self, invoice_number: str) -> Optional[Dict]:
        """
        Check if a bill with the given invoice number already exists.

        Args:
            invoice_number: The invoice number to check

        Returns:
            Dict with existing bill details if duplicate found, None otherwise
        """
        if not invoice_number or invoice_number.strip() == '':
            return None

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT id, invoice_number, invoice_date, vendor_name, vendor_gstin,
                           total_amount, filename, created_at
                    FROM bill_invoices
                    WHERE invoice_number = %s
                    LIMIT 1
                """, (invoice_number.strip(),))
                result = cursor.fetchone()
                cursor.close()

                if result:
                    # Format dates for display
                    if result.get('invoice_date'):
                        result['invoice_date'] = result['invoice_date'].strftime('%d-%b-%Y')
                    if result.get('created_at'):
                        result['created_at'] = result['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                    return result
                return None
        except Exception as e:
            print(f"[!] Error checking duplicate invoice: {e}")
            return None

    def get_bills_for_project_summary(self, start_date=None, end_date=None,
                                       project=None, vendor=None,
                                       page=1, per_page=15):
        """Get bills for project summary with robust project matching and pagination.

        Returns:
            Tuple of (bills_list, total_count, summary_dict)
        """
        conditions = []
        params = []

        if start_date:
            conditions.append("bi.invoice_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("bi.invoice_date <= %s")
            params.append(end_date)

        # Robust project matching: stem-based, case-insensitive prefix
        if project:
            stems = []
            for p in project.split(','):
                p = p.strip()
                if p:
                    tokens = p.split()
                    first_token = tokens[0].lower() if tokens else p.lower()
                    stems.append(first_token)
            if stems:
                stem_conditions = []
                for stem in stems:
                    stem_conditions.append("LOWER(bi.project) LIKE %s")
                    params.append(f"{stem}%")
                conditions.append(f"({' OR '.join(stem_conditions)})")

        # Vendor filter: case-insensitive contains
        if vendor:
            vendors = [v.strip() for v in vendor.split(',') if v.strip()]
            if vendors:
                vendor_conditions = []
                for v in vendors:
                    vendor_conditions.append("LOWER(bi.vendor_name) LIKE %s")
                    params.append(f"%{v.lower()}%")
                conditions.append(f"({' OR '.join(vendor_conditions)})")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)

                # Count
                count_query = f"SELECT COUNT(*) as cnt FROM bill_invoices bi WHERE {where_clause}"
                cursor.execute(count_query, tuple(params) if params else None)
                total = cursor.fetchone()['cnt']

                # Summary
                summary_query = f"""
                SELECT COALESCE(SUM(bi.total_amount), 0) as total_amount,
                       COALESCE(SUM(bi.total_cgst + bi.total_sgst + bi.total_igst), 0) as total_gst
                FROM bill_invoices bi WHERE {where_clause}
                """
                cursor.execute(summary_query, tuple(params) if params else None)
                summary_row = cursor.fetchone()
                summary = {
                    'total_amount': float(summary_row['total_amount']) if summary_row else 0,
                    'total_gst': float(summary_row['total_gst']) if summary_row else 0
                }

                # Data
                offset = (page - 1) * per_page
                data_query = f"""
                SELECT
                    bi.id, bi.invoice_number, bi.invoice_date, bi.vendor_name, bi.vendor_gstin,
                    bi.buyer_name, bi.subtotal, bi.total_cgst, bi.total_sgst, bi.total_igst,
                    bi.total_amount, bi.project,
                    COUNT(bli.id) as line_item_count
                FROM bill_invoices bi
                LEFT JOIN bill_line_items bli ON bi.id = bli.invoice_id
                WHERE {where_clause}
                GROUP BY bi.id
                ORDER BY bi.invoice_date DESC, bi.id DESC
                LIMIT %s OFFSET %s
                """
                data_params = list(params) + [per_page, offset]
                cursor.execute(data_query, tuple(data_params))
                rows = cursor.fetchall()
                cursor.close()

                bills = []
                for row in rows:
                    if row.get('invoice_date'):
                        row['invoice_date'] = row['invoice_date'].strftime('%d-%b-%Y')
                    for key, val in row.items():
                        if isinstance(val, DecimalType):
                            row[key] = float(val)
                    bills.append(row)

                return bills, total, summary

        except Exception as e:
            print(f"[!] Error fetching bills for project summary: {e}")
            return [], 0, {'total_amount': 0, 'total_gst': 0}

    def get_sales_bills_for_project_summary(self, start_date=None, end_date=None,
                                            project=None, vendor=None,
                                            page=1, per_page=15):
        """Get sales bills for project summary with robust project matching and pagination.

        Returns:
            Tuple of (bills_list, total_count, summary_dict)
        """
        conditions = []
        params = []

        if start_date:
            conditions.append("si.invoice_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("si.invoice_date <= %s")
            params.append(end_date)

        # Robust project matching: stem-based, case-insensitive prefix
        if project:
            stems = []
            for p in project.split(','):
                p = p.strip()
                if p:
                    tokens = p.split()
                    first_token = tokens[0].lower() if tokens else p.lower()
                    stems.append(first_token)
            if stems:
                stem_conditions = []
                for stem in stems:
                    stem_conditions.append("LOWER(si.project) LIKE %s")
                    params.append(f"{stem}%")
                conditions.append(f"({' OR '.join(stem_conditions)})")

        # Vendor/buyer filter: case-insensitive contains
        if vendor:
            vendors = [v.strip() for v in vendor.split(',') if v.strip()]
            if vendors:
                vendor_conditions = []
                for v in vendors:
                    vendor_conditions.append("(LOWER(si.buyer_name) LIKE %s OR LOWER(si.vendor_name) LIKE %s)")
                    params.append(f"%{v.lower()}%")
                    params.append(f"%{v.lower()}%")
                conditions.append(f"({' OR '.join(vendor_conditions)})")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)

                # Count
                count_query = f"SELECT COUNT(*) as cnt FROM sales_invoices si WHERE {where_clause}"
                cursor.execute(count_query, tuple(params) if params else None)
                total = cursor.fetchone()['cnt']

                # Summary
                summary_query = f"""
                SELECT COALESCE(SUM(si.total_amount), 0) as total_amount,
                       COALESCE(SUM(COALESCE(si.total_cgst, 0) + COALESCE(si.total_sgst, 0) + COALESCE(si.total_igst, 0)), 0) as total_gst
                FROM sales_invoices si WHERE {where_clause}
                """
                cursor.execute(summary_query, tuple(params) if params else None)
                summary_row = cursor.fetchone()
                summary = {
                    'total_amount': float(summary_row['total_amount']) if summary_row else 0,
                    'total_gst': float(summary_row['total_gst']) if summary_row else 0
                }

                # Data
                offset = (page - 1) * per_page
                data_query = f"""
                SELECT
                    si.id, si.invoice_number, si.invoice_date,
                    si.vendor_name, si.vendor_gstin,
                    si.buyer_name, si.buyer_gstin,
                    si.subtotal, si.total_cgst, si.total_sgst, si.total_igst,
                    si.total_amount, si.project,
                    COUNT(sli.id) as line_item_count
                FROM sales_invoices si
                LEFT JOIN sales_line_items sli ON si.id = sli.invoice_id
                WHERE {where_clause}
                GROUP BY si.id
                ORDER BY si.invoice_date DESC, si.id DESC
                LIMIT %s OFFSET %s
                """
                data_params = list(params) + [per_page, offset]
                cursor.execute(data_query, tuple(data_params))
                rows = cursor.fetchall()
                cursor.close()

                bills = []
                for row in rows:
                    if row.get('invoice_date'):
                        row['invoice_date'] = row['invoice_date'].strftime('%d-%b-%Y')
                    for key, val in row.items():
                        if isinstance(val, DecimalType):
                            row[key] = float(val)
                    bills.append(row)

                return bills, total, summary

        except Exception as e:
            print(f"[!] Error fetching sales bills for project summary: {e}")
            return [], 0, {'total_amount': 0, 'total_gst': 0}

    def get_bills_with_line_items_for_export(self, start_date=None, end_date=None):
        """Fetch all bills with their nested line items for Excel export.

        Returns list of bill dicts, each with a 'line_items' list containing
        full line-item detail (description, hsn_sac_code, quantity, uom,
        rate_per_unit, taxable_value, cgst_amount, sgst_amount, igst_amount, amount)
        plus bill-level tax totals. No pagination - export needs all data.
        """
        conditions = []
        params = []

        if start_date:
            conditions.append("bi.invoice_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("bi.invoice_date <= %s")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
        SELECT
            bi.id as bill_id, bi.invoice_number, bi.invoice_date,
            bi.vendor_name, bi.vendor_gstin,
            bi.project, bi.subtotal,
            bi.total_cgst, bi.total_sgst, bi.total_igst,
            bi.total_amount,
            bli.description as item_description,
            bli.hsn_sac_code as item_hsn_sac,
            bli.quantity as item_quantity,
            bli.uom as item_uom,
            bli.rate_per_unit as item_rate,
            bli.taxable_value as item_taxable,
            bli.cgst_amount as item_cgst,
            bli.sgst_amount as item_sgst,
            bli.igst_amount as item_igst,
            bli.amount as item_amount
        FROM bill_invoices bi
        LEFT JOIN bill_line_items bli ON bi.id = bli.invoice_id
        WHERE {where_clause}
        ORDER BY bi.id, bli.sl_no
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, tuple(params) if params else None)
                rows = cursor.fetchall()
                cursor.close()

                # Group flat JOIN rows by bill_id using OrderedDict
                from collections import OrderedDict
                bills_map = OrderedDict()
                for row in rows:
                    bid = row['bill_id']
                    if bid not in bills_map:
                        inv_date = row.get('invoice_date')
                        if inv_date and hasattr(inv_date, 'strftime'):
                            inv_date = inv_date.strftime('%d-%b-%Y')
                        bills_map[bid] = {
                            'bill_id': bid,
                            'invoice_number': row.get('invoice_number', ''),
                            'invoice_date': inv_date,
                            'vendor_name': row.get('vendor_name', ''),
                            'vendor_gstin': row.get('vendor_gstin', ''),
                            'project': row.get('project', ''),
                            'subtotal': float(row['subtotal']) if row.get('subtotal') else 0,
                            'total_cgst': float(row['total_cgst']) if row.get('total_cgst') else 0,
                            'total_sgst': float(row['total_sgst']) if row.get('total_sgst') else 0,
                            'total_igst': float(row['total_igst']) if row.get('total_igst') else 0,
                            'total_amount': float(row['total_amount']) if row.get('total_amount') else 0,
                            'line_items': []
                        }
                    # Add line item if present
                    if row.get('item_description'):
                        bills_map[bid]['line_items'].append({
                            'description': row['item_description'],
                            'hsn_sac_code': row.get('item_hsn_sac', ''),
                            'quantity': float(row['item_quantity']) if row.get('item_quantity') else 0,
                            'uom': row.get('item_uom', ''),
                            'rate_per_unit': float(row['item_rate']) if row.get('item_rate') else 0,
                            'taxable_value': float(row['item_taxable']) if row.get('item_taxable') else 0,
                            'cgst_amount': float(row['item_cgst']) if row.get('item_cgst') else 0,
                            'sgst_amount': float(row['item_sgst']) if row.get('item_sgst') else 0,
                            'igst_amount': float(row['item_igst']) if row.get('item_igst') else 0,
                            'amount': float(row['item_amount']) if row.get('item_amount') else 0
                        })

                return list(bills_map.values())

        except Exception as e:
            print(f"[!] Error fetching bills with line items for export: {e}")
            return []

    def get_sales_bills_with_line_items_for_export(self, start_date=None, end_date=None):
        """Fetch all sales bills with their nested line items for Excel export.

        Same structure as get_bills_with_line_items_for_export but targets
        sales_invoices / sales_line_items. Returns buyer_name/buyer_gstin.
        """
        conditions = []
        params = []

        if start_date:
            conditions.append("si.invoice_date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("si.invoice_date <= %s")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
        SELECT
            si.id as bill_id, si.invoice_number, si.invoice_date,
            si.buyer_name, si.buyer_gstin,
            si.vendor_name, si.vendor_gstin,
            si.project, si.subtotal,
            si.total_cgst, si.total_sgst, si.total_igst,
            si.total_amount,
            sli.description as item_description,
            sli.hsn_sac_code as item_hsn_sac,
            sli.quantity as item_quantity,
            sli.uom as item_uom,
            sli.rate_per_unit as item_rate,
            sli.taxable_value as item_taxable,
            sli.cgst_amount as item_cgst,
            sli.sgst_amount as item_sgst,
            sli.igst_amount as item_igst,
            sli.amount as item_amount
        FROM sales_invoices si
        LEFT JOIN sales_line_items sli ON si.id = sli.invoice_id
        WHERE {where_clause}
        ORDER BY si.id, sli.sl_no
        """

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, tuple(params) if params else None)
                rows = cursor.fetchall()
                cursor.close()

                from collections import OrderedDict
                bills_map = OrderedDict()
                for row in rows:
                    bid = row['bill_id']
                    if bid not in bills_map:
                        inv_date = row.get('invoice_date')
                        if inv_date and hasattr(inv_date, 'strftime'):
                            inv_date = inv_date.strftime('%d-%b-%Y')
                        bills_map[bid] = {
                            'bill_id': bid,
                            'invoice_number': row.get('invoice_number', ''),
                            'invoice_date': inv_date,
                            'buyer_name': row.get('buyer_name', ''),
                            'buyer_gstin': row.get('buyer_gstin', ''),
                            'vendor_name': row.get('vendor_name', ''),
                            'vendor_gstin': row.get('vendor_gstin', ''),
                            'project': row.get('project', ''),
                            'subtotal': float(row['subtotal']) if row.get('subtotal') else 0,
                            'total_cgst': float(row['total_cgst']) if row.get('total_cgst') else 0,
                            'total_sgst': float(row['total_sgst']) if row.get('total_sgst') else 0,
                            'total_igst': float(row['total_igst']) if row.get('total_igst') else 0,
                            'total_amount': float(row['total_amount']) if row.get('total_amount') else 0,
                            'line_items': []
                        }
                    if row.get('item_description'):
                        bills_map[bid]['line_items'].append({
                            'description': row['item_description'],
                            'hsn_sac_code': row.get('item_hsn_sac', ''),
                            'quantity': float(row['item_quantity']) if row.get('item_quantity') else 0,
                            'uom': row.get('item_uom', ''),
                            'rate_per_unit': float(row['item_rate']) if row.get('item_rate') else 0,
                            'taxable_value': float(row['item_taxable']) if row.get('item_taxable') else 0,
                            'cgst_amount': float(row['item_cgst']) if row.get('item_cgst') else 0,
                            'sgst_amount': float(row['item_sgst']) if row.get('item_sgst') else 0,
                            'igst_amount': float(row['item_igst']) if row.get('item_igst') else 0,
                            'amount': float(row['item_amount']) if row.get('item_amount') else 0
                        })

                return list(bills_map.values())

        except Exception as e:
            print(f"[!] Error fetching sales bills with line items for export: {e}")
            return []

    # ========================================================================
    # SALES BILLS DATABASE METHODS
    # ========================================================================

    def ensure_sales_tables(self):
        """Create sales_invoices and sales_line_items tables if they don't exist"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS sales_invoices (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    filename VARCHAR(255),
                    page_number INT DEFAULT 1,
                    invoice_number VARCHAR(100),
                    invoice_date DATE,
                    irn VARCHAR(255),
                    ack_number VARCHAR(100),
                    eway_bill_number VARCHAR(100),
                    vendor_name VARCHAR(255),
                    vendor_gstin VARCHAR(20),
                    vendor_address TEXT,
                    vendor_state VARCHAR(100),
                    vendor_pan VARCHAR(20),
                    vendor_phone VARCHAR(50),
                    vendor_bank_name VARCHAR(255),
                    vendor_bank_account VARCHAR(50),
                    vendor_bank_ifsc VARCHAR(20),
                    buyer_name VARCHAR(255),
                    buyer_gstin VARCHAR(20),
                    buyer_address TEXT,
                    buyer_state VARCHAR(100),
                    ship_to_name VARCHAR(255),
                    ship_to_address TEXT,
                    subtotal DECIMAL(15, 2) DEFAULT 0,
                    total_cgst DECIMAL(15, 2) DEFAULT 0,
                    total_sgst DECIMAL(15, 2) DEFAULT 0,
                    total_igst DECIMAL(15, 2) DEFAULT 0,
                    other_charges DECIMAL(15, 2) DEFAULT 0,
                    round_off DECIMAL(10, 2) DEFAULT 0,
                    total_amount DECIMAL(15, 2) DEFAULT 0,
                    amount_in_words TEXT,
                    vehicle_number VARCHAR(50),
                    transporter_name VARCHAR(255),
                    project VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS sales_line_items (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    invoice_id INT NOT NULL,
                    sl_no INT DEFAULT 0,
                    description TEXT,
                    hsn_sac_code VARCHAR(20),
                    quantity DECIMAL(15, 3) DEFAULT 0,
                    uom VARCHAR(20),
                    rate_per_unit DECIMAL(15, 2) DEFAULT 0,
                    discount_percent DECIMAL(5, 2) DEFAULT 0,
                    discount_amount DECIMAL(15, 2) DEFAULT 0,
                    taxable_value DECIMAL(15, 2) DEFAULT 0,
                    cgst_rate DECIMAL(5, 2) DEFAULT 0,
                    cgst_amount DECIMAL(15, 2) DEFAULT 0,
                    sgst_rate DECIMAL(5, 2) DEFAULT 0,
                    sgst_amount DECIMAL(15, 2) DEFAULT 0,
                    igst_rate DECIMAL(5, 2) DEFAULT 0,
                    igst_amount DECIMAL(15, 2) DEFAULT 0,
                    amount DECIMAL(15, 2) DEFAULT 0,
                    FOREIGN KEY (invoice_id) REFERENCES sales_invoices(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)

                cursor.close()
                print("[+] Sales tables ensured")
                return True
        except Exception as e:
            print(f"[!] Error ensuring sales tables: {e}")
            return False

    def insert_sales_bill(self, bill_data: Dict) -> Tuple[bool, Optional[int], Optional[str]]:
        """Insert a sales invoice and its line items into the database."""
        if not bill_data.get('success') or not bill_data.get('data'):
            return False, None, "No valid bill data"

        data = bill_data['data']
        header = data.get('invoice_header', {})
        vendor = data.get('vendor', {})
        buyer = data.get('buyer', {})
        ship_to = data.get('ship_to', {})
        taxes = data.get('taxes', {})
        transport = data.get('transport', {})
        line_items = data.get('line_items', [])
        other_charges = data.get('other_charges', [])

        invoice_date = None
        date_str = header.get('invoice_date', '')
        if date_str:
            try:
                from dateutil import parser
                invoice_date = parser.parse(date_str, dayfirst=True).date()
            except:
                pass

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                conn.autocommit = False

                invoice_query = """
                INSERT INTO sales_invoices (
                    filename, page_number, invoice_number, invoice_date, irn, ack_number, eway_bill_number,
                    vendor_name, vendor_gstin, vendor_address, vendor_state, vendor_pan, vendor_phone,
                    vendor_bank_name, vendor_bank_account, vendor_bank_ifsc,
                    buyer_name, buyer_gstin, buyer_address, buyer_state,
                    ship_to_name, ship_to_address,
                    subtotal, total_cgst, total_sgst, total_igst, other_charges, round_off, total_amount, amount_in_words,
                    vehicle_number, transporter_name
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s
                )
                """

                other_charges_total = sum(c.get('amount', 0) or 0 for c in other_charges if c.get('description'))

                cursor.execute(invoice_query, (
                    bill_data.get('filename', ''),
                    bill_data.get('page', 1),
                    header.get('invoice_number', ''),
                    invoice_date,
                    header.get('irn', ''),
                    header.get('ack_number', ''),
                    header.get('eway_bill_number', ''),
                    vendor.get('name', ''),
                    vendor.get('gstin', ''),
                    vendor.get('address', ''),
                    vendor.get('state', ''),
                    vendor.get('pan', ''),
                    vendor.get('phone', ''),
                    vendor.get('bank_name', ''),
                    vendor.get('bank_account', ''),
                    vendor.get('bank_ifsc', ''),
                    buyer.get('name', ''),
                    buyer.get('gstin', ''),
                    buyer.get('address', ''),
                    buyer.get('state', ''),
                    ship_to.get('name', ''),
                    ship_to.get('address', ''),
                    float(taxes.get('subtotal', 0) or taxes.get('taxable_amount', 0) or 0),
                    float(taxes.get('total_cgst', 0) or taxes.get('cgst_amount', 0) or 0),
                    float(taxes.get('total_sgst', 0) or taxes.get('sgst_amount', 0) or 0),
                    float(taxes.get('total_igst', 0) or taxes.get('igst_amount', 0) or 0),
                    float(other_charges_total),
                    float(taxes.get('round_off', 0) or 0),
                    float(taxes.get('total_amount', 0) or 0),
                    taxes.get('amount_in_words', ''),
                    transport.get('vehicle_number', ''),
                    transport.get('transporter_name', '')
                ))

                invoice_id = cursor.lastrowid

                if line_items:
                    line_item_query = """
                    INSERT INTO sales_line_items (
                        invoice_id, sl_no, description, hsn_sac_code, quantity, uom,
                        rate_per_unit, discount_percent, discount_amount, taxable_value,
                        cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount, amount
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """

                    for item in line_items:
                        if item.get('description'):
                            cursor.execute(line_item_query, (
                                invoice_id,
                                item.get('sl_no', 0),
                                item.get('description', ''),
                                item.get('hsn_sac_code', '') or item.get('hsn_code', ''),
                                float(item.get('quantity', 0) or 0),
                                item.get('uom', ''),
                                float(item.get('rate_per_unit', 0) or item.get('rate', 0) or 0),
                                float(item.get('discount_percent', 0) or 0),
                                float(item.get('discount_amount', 0) or 0),
                                float(item.get('taxable_value', 0) or 0),
                                float(item.get('cgst_rate', 0) or 0),
                                float(item.get('cgst_amount', 0) or 0),
                                float(item.get('sgst_rate', 0) or 0),
                                float(item.get('sgst_amount', 0) or 0),
                                float(item.get('igst_rate', 0) or 0),
                                float(item.get('igst_amount', 0) or 0),
                                float(item.get('amount', 0) or 0)
                            ))

                conn.commit()
                cursor.close()

                print(f"[+] Saved sales bill to DB: Invoice #{header.get('invoice_number', 'N/A')} (ID: {invoice_id})")
                return True, invoice_id, None

        except mysql.connector.IntegrityError as e:
            if e.errno == 1062:
                print(f"[!] Duplicate sales bill: {header.get('invoice_number', '')}")
                return False, None, "Duplicate invoice"
            return False, None, str(e)
        except Exception as e:
            print(f"[!] Error saving sales bill: {e}")
            import traceback
            traceback.print_exc()
            return False, None, str(e)

    def get_all_sales_bills(self, limit: int = 100, offset: int = 0, projects: list = None,
                             date_from: str = None, date_to: str = None,
                             added_from: str = None, added_to: str = None) -> List[Dict]:
        """Get all sales bills from database with pagination and optional filters"""
        query = """
        SELECT
            si.id, si.filename, si.page_number, si.invoice_number, si.invoice_date,
            si.vendor_name, si.vendor_gstin, si.buyer_name, si.buyer_gstin,
            si.subtotal, si.total_cgst, si.total_sgst, si.total_igst,
            si.total_amount, si.vehicle_number, si.eway_bill_number, si.irn,
            si.project, si.created_at,
            COUNT(sli.id) as line_item_count
        FROM sales_invoices si
        LEFT JOIN sales_line_items sli ON si.id = sli.invoice_id
        WHERE 1=1
        """
        params = []

        if projects:
            placeholders = ','.join(['%s'] * len(projects))
            query += f" AND si.project IN ({placeholders})"
            params.extend(projects)

        if date_from:
            query += " AND si.invoice_date >= %s"
            params.append(date_from)

        if date_to:
            query += " AND si.invoice_date <= %s"
            params.append(date_to)

        if added_from:
            query += " AND DATE(si.created_at) >= %s"
            params.append(added_from)

        if added_to:
            query += " AND DATE(si.created_at) <= %s"
            params.append(added_to)

        query += """
        GROUP BY si.id
        ORDER BY si.invoice_date DESC, si.created_at DESC
        LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(query, tuple(params))
                results = cursor.fetchall()
                cursor.close()

                for row in results:
                    if row.get('invoice_date'):
                        row['invoice_date'] = row['invoice_date'].strftime('%d-%b-%Y')
                    if row.get('created_at'):
                        row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                    for key, val in row.items():
                        if isinstance(val, DecimalType):
                            row[key] = float(val)

                return results
        except Exception as e:
            print(f"[!] Error fetching sales bills: {e}")
            return []

    def get_sales_bill_detail(self, invoice_id: int) -> Optional[Dict]:
        """Get full sales bill detail including line items"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM sales_invoices WHERE id = %s", (invoice_id,))
                invoice = cursor.fetchone()

                if not invoice:
                    cursor.close()
                    return None

                if invoice.get('invoice_date'):
                    invoice['invoice_date'] = invoice['invoice_date'].strftime('%d-%b-%Y')
                if invoice.get('created_at'):
                    invoice['created_at'] = invoice['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                if invoice.get('updated_at'):
                    invoice['updated_at'] = invoice['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
                for key, val in invoice.items():
                    if isinstance(val, DecimalType):
                        invoice[key] = float(val)

                cursor.execute("""
                    SELECT * FROM sales_line_items WHERE invoice_id = %s ORDER BY sl_no
                """, (invoice_id,))
                line_items = cursor.fetchall()
                cursor.close()

                for item in line_items:
                    for key in ['quantity', 'rate_per_unit', 'discount_percent', 'discount_amount',
                               'taxable_value', 'cgst_rate', 'cgst_amount', 'sgst_rate', 'sgst_amount',
                               'igst_rate', 'igst_amount', 'amount']:
                        if item.get(key) is not None:
                            item[key] = float(item[key])

                invoice['line_items'] = line_items
                return invoice

        except Exception as e:
            print(f"[!] Error fetching sales bill detail: {e}")
            return None

    def delete_sales_bill(self, invoice_id: int) -> bool:
        """Delete a sales bill and its line items"""
        return self.execute_query("DELETE FROM sales_invoices WHERE id = %s", (invoice_id,))

    def update_sales_bill_project(self, invoice_id: int, project: str) -> bool:
        """Update the project field for a sales bill"""
        return self.execute_query(
            "UPDATE sales_invoices SET project = %s WHERE id = %s",
            (project if project else None, invoice_id)
        )

    def get_unique_sales_projects(self) -> List[str]:
        """Get all unique project names from sales bills"""
        query = """
        SELECT DISTINCT project FROM sales_invoices
        WHERE project IS NOT NULL AND project != ''
        ORDER BY project
        """
        try:
            results = self.fetch_all(query)
            return [row[0] for row in results if row[0]]
        except Exception as e:
            print(f"[!] Error fetching unique sales projects: {e}")
            return []

    def get_sales_bill_count(self, projects: list = None, date_from: str = None, date_to: str = None,
                              added_from: str = None, added_to: str = None) -> int:
        """Get total number of stored sales bills"""
        query = "SELECT COUNT(*) FROM sales_invoices WHERE 1=1"
        params = []

        if projects:
            placeholders = ','.join(['%s'] * len(projects))
            query += f" AND project IN ({placeholders})"
            params.extend(projects)

        if date_from:
            query += " AND invoice_date >= %s"
            params.append(date_from)

        if date_to:
            query += " AND invoice_date <= %s"
            params.append(date_to)

        if added_from:
            query += " AND DATE(created_at) >= %s"
            params.append(added_from)

        if added_to:
            query += " AND DATE(created_at) <= %s"
            params.append(added_to)

        result = self.fetch_all(query, tuple(params) if params else None)
        return result[0][0] if result else 0

    def check_duplicate_sales_invoice(self, invoice_number: str) -> Optional[Dict]:
        """Check if a sales bill with the given invoice number already exists."""
        if not invoice_number or invoice_number.strip() == '':
            return None

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT id, invoice_number, invoice_date, vendor_name, vendor_gstin,
                           total_amount, filename, created_at
                    FROM sales_invoices
                    WHERE invoice_number = %s
                    LIMIT 1
                """, (invoice_number.strip(),))
                result = cursor.fetchone()
                cursor.close()

                if result:
                    if result.get('invoice_date'):
                        result['invoice_date'] = result['invoice_date'].strftime('%d-%b-%Y')
                    if result.get('created_at'):
                        result['created_at'] = result['created_at'].strftime('%Y-%m-%d %H:%M:%S')
                    return result
                return None
        except Exception as e:
            print(f"[!] Error checking duplicate sales invoice: {e}")
            return None

    def update_sales_bill(self, invoice_id: int, bill_data: Dict) -> Tuple[bool, Optional[str]]:
        """Update a sales invoice and its line items in the database."""
        invoice_date = None
        date_str = bill_data.get('invoice_date', '')
        if date_str:
            try:
                from dateutil import parser
                invoice_date = parser.parse(date_str, dayfirst=True).date()
            except:
                pass

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                conn.autocommit = False

                update_query = """
                UPDATE sales_invoices SET
                    invoice_number = %s,
                    invoice_date = %s,
                    irn = %s,
                    ack_number = %s,
                    eway_bill_number = %s,
                    vendor_name = %s,
                    vendor_gstin = %s,
                    vendor_address = %s,
                    vendor_state = %s,
                    vendor_pan = %s,
                    vendor_phone = %s,
                    vendor_bank_name = %s,
                    vendor_bank_account = %s,
                    vendor_bank_ifsc = %s,
                    buyer_name = %s,
                    buyer_gstin = %s,
                    buyer_address = %s,
                    buyer_state = %s,
                    ship_to_name = %s,
                    ship_to_address = %s,
                    subtotal = %s,
                    total_cgst = %s,
                    total_sgst = %s,
                    total_igst = %s,
                    other_charges = %s,
                    round_off = %s,
                    total_amount = %s,
                    amount_in_words = %s,
                    vehicle_number = %s,
                    transporter_name = %s,
                    project = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """

                cursor.execute(update_query, (
                    bill_data.get('invoice_number', ''),
                    invoice_date,
                    bill_data.get('irn', ''),
                    bill_data.get('ack_number', ''),
                    bill_data.get('eway_bill_number', ''),
                    bill_data.get('vendor_name', ''),
                    bill_data.get('vendor_gstin', ''),
                    bill_data.get('vendor_address', ''),
                    bill_data.get('vendor_state', ''),
                    bill_data.get('vendor_pan', ''),
                    bill_data.get('vendor_phone', ''),
                    bill_data.get('vendor_bank_name', ''),
                    bill_data.get('vendor_bank_account', ''),
                    bill_data.get('vendor_bank_ifsc', ''),
                    bill_data.get('buyer_name', ''),
                    bill_data.get('buyer_gstin', ''),
                    bill_data.get('buyer_address', ''),
                    bill_data.get('buyer_state', ''),
                    bill_data.get('ship_to_name', ''),
                    bill_data.get('ship_to_address', ''),
                    float(bill_data.get('subtotal', 0) or 0),
                    float(bill_data.get('total_cgst', 0) or 0),
                    float(bill_data.get('total_sgst', 0) or 0),
                    float(bill_data.get('total_igst', 0) or 0),
                    float(bill_data.get('other_charges', 0) or 0),
                    float(bill_data.get('round_off', 0) or 0),
                    float(bill_data.get('total_amount', 0) or 0),
                    bill_data.get('amount_in_words', ''),
                    bill_data.get('vehicle_number', ''),
                    bill_data.get('transporter_name', ''),
                    bill_data.get('project', '') or None,
                    invoice_id
                ))

                cursor.execute("DELETE FROM sales_line_items WHERE invoice_id = %s", (invoice_id,))

                line_items = bill_data.get('line_items', [])
                if line_items:
                    line_item_query = """
                    INSERT INTO sales_line_items (
                        invoice_id, sl_no, description, hsn_sac_code, quantity, uom,
                        rate_per_unit, discount_percent, discount_amount, taxable_value,
                        cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount, amount
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """

                    for idx, item in enumerate(line_items):
                        if item.get('description'):
                            cursor.execute(line_item_query, (
                                invoice_id,
                                item.get('sl_no', idx + 1),
                                item.get('description', ''),
                                item.get('hsn_sac_code', ''),
                                float(item.get('quantity', 0) or 0),
                                item.get('uom', ''),
                                float(item.get('rate_per_unit', 0) or 0),
                                float(item.get('discount_percent', 0) or 0),
                                float(item.get('discount_amount', 0) or 0),
                                float(item.get('taxable_value', 0) or 0),
                                float(item.get('cgst_rate', 0) or 0),
                                float(item.get('cgst_amount', 0) or 0),
                                float(item.get('sgst_rate', 0) or 0),
                                float(item.get('sgst_amount', 0) or 0),
                                float(item.get('igst_rate', 0) or 0),
                                float(item.get('igst_amount', 0) or 0),
                                float(item.get('amount', 0) or 0)
                            ))

                conn.commit()
                cursor.close()

                print(f"[+] Updated sales bill ID: {invoice_id}")
                return True, None

        except Exception as e:
            print(f"[!] Error updating sales bill: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)

    # ── Salary / Attendance DB helpers ──────────────────────
    SALARY_DB_CONFIG = {
        'host': 'caboose.proxy.rlwy.net',
        'port': 47978,
        'user': 'root',
        'password': 'DZktxKRJxEMmOBBkqLjAFxcPvViPBHkH',
        'database': 'railway'
    }

    @staticmethod
    def _get_salary_connection():
        return mysql.connector.connect(**DatabaseManager.SALARY_DB_CONFIG)

    @staticmethod
    def get_labour_costs_by_project(start_date=None, end_date=None):
        """Fetch labour costs per project from the salary/attendance database.

        Uses the correct formula from the attendance app:
          per present day: base_salary_per_day
          per OT hour:     base_salary_per_day / 8
        Uses latest salary record per worker for base_salary_per_day.

        Returns dict: {project_name: total_labour_cost}
        """
        try:
            conn = DatabaseManager._get_salary_connection()
            cursor = conn.cursor(dictionary=True)

            conditions = ["a.status = 'P'", "a.project IS NOT NULL", "a.project != ''"]
            params = []

            if start_date:
                conditions.append("a.date >= %s")
                params.append(start_date)
            if end_date:
                conditions.append("a.date <= %s")
                params.append(end_date)

            where_clause = " AND ".join(conditions)

            query = f"""
            SELECT
                a.project,
                SUM(s.base_salary_per_day) as base_cost,
                SUM((s.base_salary_per_day / 8) * a.ot_hours) as ot_cost
            FROM attendance a
            JOIN (
                SELECT s1.* FROM salary s1
                INNER JOIN (
                    SELECT worker_id, MAX(year * 100 + month) AS max_period
                    FROM salary GROUP BY worker_id
                ) s2 ON s1.worker_id = s2.worker_id
                    AND (s1.year * 100 + s1.month) = s2.max_period
            ) s ON a.worker_id = s.worker_id
            WHERE {where_clause}
            GROUP BY a.project
            ORDER BY (SUM(s.base_salary_per_day) + SUM((s.base_salary_per_day / 8) * a.ot_hours)) DESC
            """

            cursor.execute(query, tuple(params) if params else None)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            result = {}
            for row in rows:
                project = row.get('project', '')
                base = float(row['base_cost'] or 0)
                ot = float(row['ot_cost'] or 0)
                cost = round(base + ot, 2)
                if project and cost > 0:
                    result[project] = cost
            return result

        except Exception as e:
            print(f"[!] Error fetching labour costs from salary DB: {e}")
            return {}

    @staticmethod
    def get_monthly_salary_and_attendance(start_date=None, end_date=None):
        """Fetch complete monthly salary + attendance data for the Labour tab export.

        Returns list of month dicts (newest first), each containing:
        - month_name, year, month_num
        - workers: list of worker dicts with salary breakdown
        - attendance: list of daily attendance records for that month
        - total_salary
        """
        import calendar as cal
        from datetime import date as date_type

        try:
            conn = DatabaseManager._get_salary_connection()
            cursor = conn.cursor(dictionary=True)

            # Determine month range from date filters
            if start_date:
                try:
                    from dateutil import parser
                    sd = parser.parse(str(start_date)).date() if not isinstance(start_date, date_type) else start_date
                except:
                    sd = date_type(2025, 1, 1)
            else:
                sd = date_type(2025, 1, 1)

            if end_date:
                try:
                    from dateutil import parser
                    ed = parser.parse(str(end_date)).date() if not isinstance(end_date, date_type) else end_date
                except:
                    ed = date_type.today()
            else:
                ed = date_type.today()

            # Build list of (year, month) tuples in range
            months_in_range = []
            y, m = sd.year, sd.month
            while (y, m) <= (ed.year, ed.month):
                months_in_range.append((y, m))
                m += 1
                if m > 12:
                    m = 1
                    y += 1

            result = []

            for year, month in reversed(months_in_range):
                # 1. Worker salary data
                cursor.execute("""
                    SELECT worker_id, name, designation, team,
                           base_salary_per_day, total_working_days, ot_hours, total_salary
                    FROM salary
                    WHERE year = %s AND month = %s
                    ORDER BY team, name
                """, (year, month))
                salary_rows = cursor.fetchall()

                if not salary_rows:
                    continue

                workers = []
                total_salary = 0
                for w in salary_rows:
                    base = float(w['base_salary_per_day'] or 0)
                    days = int(w['total_working_days'] or 0)
                    ot = float(w['ot_hours'] or 0)
                    base_pay = days * base
                    ot_pay = (base / 8) * ot if base > 0 else 0
                    ts = float(w['total_salary'] or 0)
                    total_salary += ts
                    workers.append({
                        'worker_id': w['worker_id'],
                        'name': w['name'],
                        'designation': w['designation'] or '',
                        'team': w['team'] or '',
                        'base_salary_per_day': base,
                        'working_days': days,
                        'ot_hours': ot,
                        'base_pay': round(base_pay, 2),
                        'ot_pay': round(ot_pay, 2),
                        'total_salary': ts
                    })

                # 2. Attendance records for this month
                cursor.execute("""
                    SELECT DISTINCT
                        a.id, a.worker_id, a.date, a.status, a.ot_hours, a.project,
                        s.name, s.designation, s.team
                    FROM attendance a
                    JOIN salary s ON a.worker_id = s.worker_id
                    WHERE YEAR(a.date) = %s AND MONTH(a.date) = %s
                    ORDER BY a.date, s.team, s.name
                """, (year, month))
                att_rows = cursor.fetchall()

                # Deduplicate by attendance id
                seen_ids = set()
                attendance = []
                for a in att_rows:
                    aid = a['id']
                    if aid not in seen_ids:
                        seen_ids.add(aid)
                        att_date = a['date']
                        if hasattr(att_date, 'isoformat'):
                            att_date = att_date.isoformat()
                        attendance.append({
                            'date': att_date,
                            'worker_id': a['worker_id'],
                            'name': a['name'],
                            'designation': a['designation'] or '',
                            'team': a['team'] or '',
                            'status': a['status'],
                            'ot_hours': float(a['ot_hours'] or 0),
                            'project': a['project'] or ''
                        })

                # 3. Daily headcount
                cursor.execute("""
                    SELECT date,
                           SUM(status = 'P') AS present,
                           SUM(status = 'A') AS absent,
                           SUM(status = 'H') AS holiday,
                           SUM(ot_hours) AS ot_hours
                    FROM attendance
                    WHERE YEAR(date) = %s AND MONTH(date) = %s
                    GROUP BY date ORDER BY date
                """, (year, month))
                daily_rows = cursor.fetchall()
                daily = []
                for d in daily_rows:
                    dd = d['date']
                    if hasattr(dd, 'isoformat'):
                        dd = dd.isoformat()
                    daily.append({
                        'date': dd,
                        'present': int(d['present'] or 0),
                        'absent': int(d['absent'] or 0),
                        'holiday': int(d['holiday'] or 0),
                        'ot_hours': round(float(d['ot_hours'] or 0), 2)
                    })

                # 4. Project breakdown
                cursor.execute("""
                    SELECT COALESCE(project, 'Unassigned') AS project,
                           COUNT(DISTINCT worker_id) AS workers,
                           COUNT(DISTINCT CASE WHEN status='P' THEN date END) AS working_days,
                           SUM(ot_hours) AS ot_hours
                    FROM attendance
                    WHERE YEAR(date) = %s AND MONTH(date) = %s AND status = 'P'
                    GROUP BY COALESCE(project, 'Unassigned')
                """, (year, month))
                proj_rows = cursor.fetchall()
                projects = []
                for p in proj_rows:
                    projects.append({
                        'name': p['project'],
                        'workers': int(p['workers'] or 0),
                        'working_days': int(p['working_days'] or 0),
                        'ot_hours': round(float(p['ot_hours'] or 0), 2)
                    })

                month_abbr = cal.month_abbr[month].upper()
                result.append({
                    'month': f"{year}-{month:02d}",
                    'year': year,
                    'month_num': month,
                    'month_name': f"{cal.month_name[month]} {year}",
                    'sheet_name': f"{month_abbr}-{str(year)[-2:]}",
                    'days_in_month': cal.monthrange(year, month)[1],
                    'workers': workers,
                    'attendance': attendance,
                    'daily_headcount': daily,
                    'project_breakdown': projects,
                    'total_salary': round(total_salary, 2)
                })

            cursor.close()
            conn.close()
            return result

        except Exception as e:
            print(f"[!] Error fetching monthly salary data: {e}")
            import traceback
            traceback.print_exc()
            return []

    def update_bill(self, invoice_id: int, bill_data: Dict) -> Tuple[bool, Optional[str]]:
        """
        Update a bill invoice and its line items in the database.

        Args:
            invoice_id: The ID of the invoice to update
            bill_data: Updated bill data with all fields and line_items

        Returns:
            Tuple of (success, error_message)
        """
        # Parse invoice date
        invoice_date = None
        date_str = bill_data.get('invoice_date', '')
        if date_str:
            try:
                from dateutil import parser
                invoice_date = parser.parse(date_str, dayfirst=True).date()
            except:
                pass

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                conn.autocommit = False

                # Update main invoice record
                update_query = """
                UPDATE bill_invoices SET
                    invoice_number = %s,
                    invoice_date = %s,
                    irn = %s,
                    ack_number = %s,
                    eway_bill_number = %s,
                    vendor_name = %s,
                    vendor_gstin = %s,
                    vendor_address = %s,
                    vendor_state = %s,
                    vendor_pan = %s,
                    vendor_phone = %s,
                    vendor_bank_name = %s,
                    vendor_bank_account = %s,
                    vendor_bank_ifsc = %s,
                    buyer_name = %s,
                    buyer_gstin = %s,
                    buyer_address = %s,
                    buyer_state = %s,
                    ship_to_name = %s,
                    ship_to_address = %s,
                    subtotal = %s,
                    total_cgst = %s,
                    total_sgst = %s,
                    total_igst = %s,
                    other_charges = %s,
                    round_off = %s,
                    total_amount = %s,
                    amount_in_words = %s,
                    vehicle_number = %s,
                    transporter_name = %s,
                    project = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """

                cursor.execute(update_query, (
                    bill_data.get('invoice_number', ''),
                    invoice_date,
                    bill_data.get('irn', ''),
                    bill_data.get('ack_number', ''),
                    bill_data.get('eway_bill_number', ''),
                    bill_data.get('vendor_name', ''),
                    bill_data.get('vendor_gstin', ''),
                    bill_data.get('vendor_address', ''),
                    bill_data.get('vendor_state', ''),
                    bill_data.get('vendor_pan', ''),
                    bill_data.get('vendor_phone', ''),
                    bill_data.get('vendor_bank_name', ''),
                    bill_data.get('vendor_bank_account', ''),
                    bill_data.get('vendor_bank_ifsc', ''),
                    bill_data.get('buyer_name', ''),
                    bill_data.get('buyer_gstin', ''),
                    bill_data.get('buyer_address', ''),
                    bill_data.get('buyer_state', ''),
                    bill_data.get('ship_to_name', ''),
                    bill_data.get('ship_to_address', ''),
                    float(bill_data.get('subtotal', 0) or 0),
                    float(bill_data.get('total_cgst', 0) or 0),
                    float(bill_data.get('total_sgst', 0) or 0),
                    float(bill_data.get('total_igst', 0) or 0),
                    float(bill_data.get('other_charges', 0) or 0),
                    float(bill_data.get('round_off', 0) or 0),
                    float(bill_data.get('total_amount', 0) or 0),
                    bill_data.get('amount_in_words', ''),
                    bill_data.get('vehicle_number', ''),
                    bill_data.get('transporter_name', ''),
                    bill_data.get('project', '') or None,
                    invoice_id
                ))

                # Delete existing line items
                cursor.execute("DELETE FROM bill_line_items WHERE invoice_id = %s", (invoice_id,))

                # Insert updated line items
                line_items = bill_data.get('line_items', [])
                if line_items:
                    line_item_query = """
                    INSERT INTO bill_line_items (
                        invoice_id, sl_no, description, hsn_sac_code, quantity, uom,
                        rate_per_unit, discount_percent, discount_amount, taxable_value,
                        cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount, amount
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """

                    for idx, item in enumerate(line_items):
                        if item.get('description'):  # Only insert if has description
                            cursor.execute(line_item_query, (
                                invoice_id,
                                item.get('sl_no', idx + 1),
                                item.get('description', ''),
                                item.get('hsn_sac_code', ''),
                                float(item.get('quantity', 0) or 0),
                                item.get('uom', ''),
                                float(item.get('rate_per_unit', 0) or 0),
                                float(item.get('discount_percent', 0) or 0),
                                float(item.get('discount_amount', 0) or 0),
                                float(item.get('taxable_value', 0) or 0),
                                float(item.get('cgst_rate', 0) or 0),
                                float(item.get('cgst_amount', 0) or 0),
                                float(item.get('sgst_rate', 0) or 0),
                                float(item.get('sgst_amount', 0) or 0),
                                float(item.get('igst_rate', 0) or 0),
                                float(item.get('igst_amount', 0) or 0),
                                float(item.get('amount', 0) or 0)
                            ))

                conn.commit()
                cursor.close()

                print(f"[+] Updated bill ID: {invoice_id}")
                return True, None

        except Exception as e:
            print(f"[!] Error updating bill: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)


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
