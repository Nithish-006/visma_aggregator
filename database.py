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

                # Get unique categories
                cursor.execute(f"SELECT DISTINCT category FROM {table} WHERE category IS NOT NULL AND category != '' ORDER BY category")
                categories = [row[0] for row in cursor.fetchall()]

                # Get unique projects
                cursor.execute(f"SELECT DISTINCT project FROM {table} WHERE project IS NOT NULL AND project != '' ORDER BY project")
                projects = [row[0] for row in cursor.fetchall()]

                # Get unique vendors
                cursor.execute(f"SELECT DISTINCT client_vendor FROM {table} WHERE client_vendor IS NOT NULL AND client_vendor != '' AND client_vendor != 'Unknown' ORDER BY client_vendor")
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
                cursor.execute(f"SELECT DISTINCT category FROM {table} WHERE {w} AND category IS NOT NULL AND category != '' ORDER BY category", tuple(p))
                categories = [row[0] for row in cursor.fetchall()]

                # Projects: filtered by category, vendor, date, search (not by project itself)
                w, p = build_conditions(exclude_field='project')
                cursor.execute(f"SELECT DISTINCT project FROM {table} WHERE {w} AND project IS NOT NULL AND project != '' ORDER BY project", tuple(p))
                projects = [row[0] for row in cursor.fetchall()]

                # Vendors: filtered by category, project, date, search (not by vendor itself)
                w, p = build_conditions(exclude_field='vendor')
                cursor.execute(f"SELECT DISTINCT client_vendor FROM {table} WHERE {w} AND client_vendor IS NOT NULL AND client_vendor != '' AND client_vendor != 'Unknown' ORDER BY client_vendor", tuple(p))
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

    def get_all_bills(self, limit: int = 100, offset: int = 0, project: str = None,
                       date_from: str = None, date_to: str = None) -> List[Dict]:
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

        if project:
            query += " AND bi.project = %s"
            params.append(project)

        if date_from:
            query += " AND DATE(bi.created_at) >= %s"
            params.append(date_from)

        if date_to:
            query += " AND DATE(bi.created_at) <= %s"
            params.append(date_to)

        query += """
        GROUP BY bi.id
        ORDER BY bi.created_at DESC
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

    def get_bill_count(self, project: str = None, date_from: str = None, date_to: str = None) -> int:
        """Get total number of stored bills, optionally filtered by project and date range"""
        query = "SELECT COUNT(*) FROM bill_invoices WHERE 1=1"
        params = []

        if project:
            query += " AND project = %s"
            params.append(project)

        if date_from:
            query += " AND DATE(created_at) >= %s"
            params.append(date_from)

        if date_to:
            query += " AND DATE(created_at) <= %s"
            params.append(date_to)

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
