"""
Database module for VISMA Financial App
Handles MySQL connection and transaction operations
Supports multiple banks with separate tables

Uses per-request connection pattern for thread safety.
"""

import re
import json
import mysql.connector
from mysql.connector import Error
import pandas as pd
from datetime import datetime
from decimal import Decimal as DecimalType
from typing import Dict, List, Tuple, Optional
from contextlib import contextmanager
from config import (
    Config, BANK_CONFIG, get_bank_config, get_bank_table, VALID_BANK_CODES,
    IST_MYSQL_OFFSET,
)
from extraction_validator import validate_extraction, validate_db_row, notes_from_result
from helpers.project_finance import (
    PO_LEDGER_GST_RATE, compute_ledger_amounts, resolve_contract,
)


def _parse_invoice_date(date_str):
    """Parse an invoice date string to a date object.

    The edit form's <input type="date"> submits ISO ``YYYY-MM-DD`` (e.g.
    ``2026-06-12``). dateutil with ``dayfirst=True`` MISREADS that — it treats
    the trailing two groups as day-then-month and returns ``2026-12-06``,
    swapping day and month. So parse an ISO string explicitly, and only fall
    back to day-first parsing for the ``DD-MMM-YYYY`` / ``DD/MM/YYYY`` formats
    the extractor and Indian invoices use (where day-first is correct).
    """
    if not date_str:
        return None
    date_str = str(date_str).strip()
    if not date_str:
        return None
    try:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        from dateutil import parser
        return parser.parse(date_str, dayfirst=True).date()
    except Exception:
        return None


def _fit(value, maxlen):
    """Clamp a string to a column's max width before insert.

    The vision extractor occasionally captures extra text into a short field
    (e.g. a ``vendor_bank_ifsc`` column is ``varchar(20)`` but a real IFSC is 11
    chars — an over-eager extraction can exceed it). Without clamping, MySQL
    aborts the whole row with error 1406 and the bill is lost. Truncating a
    non-critical metadata field is strictly better than dropping the invoice.
    Non-strings (and None) pass through untouched.
    """
    if not isinstance(value, str):
        return value
    return value[:maxlen] if len(value) > maxlen else value


def build_project_filter_sql(column, project, params, fuzzy=False):
    """SQL condition for a comma-separated project selection.

    Canonical selections ("659 - JAMUNA") match STRICTLY on the "<id> -"
    tag prefix; free-text selections keep stem-prefix matching (tested on
    the raw value and on the segment after " - "). Bind values are appended
    to `params`; returns the condition string, or None when the selection
    is empty.

    fuzzy=True relaxes canonical selections to ALSO stem-match the name
    part ("659 - JAMUNA" additionally matches "jamuna lunch"). Meant for
    free-hand columns like the personal expense tracker, where entries are
    typed by hand and rarely carry the canonical tag.
    """
    conds = []
    for p in (project or '').split(','):
        p = p.strip()
        if not p or p == 'All':
            continue
        m = re.match(r'^(\d+)\s*-', p)
        stem = None
        if m:
            pid = m.group(1)
            sub_conds = [f"TRIM({column}) LIKE %s", f"TRIM({column}) LIKE %s"]
            params.append(f"{pid} -%")
            params.append(f"{pid}-%")
            if fuzzy:
                # stem of the name part after the canonical "<id> - " prefix
                name_tokens = p[m.end():].strip().split()
                stem = name_tokens[0].lower() if name_tokens else None
        else:
            sub_conds = []
            tokens = p.split()
            stem = tokens[0].lower() if tokens else p.lower()
        if stem:
            sub_conds.append(f"LOWER(TRIM({column})) LIKE %s")
            params.append(f"{stem}%")
            sub_conds.append(f"LOWER(TRIM(SUBSTRING_INDEX({column}, ' - ', -1))) LIKE %s")
            params.append(f"{stem}%")
        if sub_conds:
            conds.append(f"({' OR '.join(sub_conds)})")
    return f"({' OR '.join(conds)})" if conds else None


# In-process pre-filter for intra-file duplicates, run before INSERT IGNORE.
# The DB-level unique key is `unique_transaction`
# (transaction_date, transaction_description(500), dr_amount, cr_amount) on a
# DATETIME column, so genuine same-day/same-amount rows stay distinct by their
# time-of-day. This key normalizes the description more aggressively (40-char
# alnum prefix + SPLIT tag) purely to catch obvious in-file repeats early.
_SPLIT_TAG_RE = re.compile(r'\[SPLIT\s*\d+\s*/\s*\d+\]')
_NON_ALNUM_RE = re.compile(r'[^A-Za-z0-9]')


def _txn_dedup_key(description) -> str:
    s = '' if description is None else str(description)
    norm_prefix = _NON_ALNUM_RE.sub('', s).upper()[:40]
    split_tag = _SPLIT_TAG_RE.search(s)
    return f"{norm_prefix}|{split_tag.group(0) if split_tag else ''}"


def _split_parent_key(description) -> str:
    """Normalized signature of a transaction's *base* description (split tag removed).

    A split child is stored as ``"<original description> [SPLIT n/m]"``. Stripping the
    tag and normalizing yields the same value as the original (untagged) description,
    so this key lets us recognize when an incoming upload row is the parent of an
    already-existing split group. Returns '' for blank descriptions.
    """
    s = '' if description is None else str(description)
    base = _SPLIT_TAG_RE.sub('', s)
    return _NON_ALNUM_RE.sub('', base).upper()


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
            # Force every connection's session timezone to IST so that
            # `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` columns (the
            # "date added" the user sees) are stamped in Indian time, no matter
            # what timezone the deployment host / MySQL server runs in.
            try:
                cur = conn.cursor()
                cur.execute("SET time_zone = %s", (IST_MYSQL_OFFSET,))
                cur.close()
            except Error as tz_err:
                # Numeric offsets don't need the TZ tables loaded, so this should
                # always work; if it somehow fails, keep the connection usable.
                print(f"[!] Could not set IST session time_zone: {tz_err}")
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

                # Preserve full datetime (incl. time-of-day) so same-day,
                # same-amount, same-description transactions stay distinct.
                trans_date = transaction['Date']
                if hasattr(trans_date, 'to_pydatetime'):
                    trans_date = trans_date.to_pydatetime()

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

        # Defense-in-depth: collapse intra-file duplicates before they hit MySQL.
        # Keyed on (Date incl. time, DR, CR, normalized-description) so that genuine
        # same-day/same-amount transactions with different timestamps are KEPT, while
        # a single Excel containing a truly identical row twice is caught here instead
        # of being silently swallowed by INSERT IGNORE and missing from the report.
        intra_dupes = 0
        if len(df) > 1:
            pre = len(df)
            df = df.assign(_dedup_key=df['Transaction Description'].map(_txn_dedup_key))
            df = df.drop_duplicates(subset=['Date', 'DR Amount', 'CR Amount', '_dedup_key'])
            df = df.drop(columns=['_dedup_key'])
            intra_dupes = pre - len(df)
            if intra_dupes:
                print(f"[*] Filtered {intra_dupes} intra-file duplicate(s) before insert")

        # Guard against resurrecting already-split originals.
        # When a transaction is split, the original row is deleted and replaced by
        # child rows tagged "[SPLIT n/m]" (with smaller amounts). The dedup key
        # (uk_txn_dedup) intentionally distinguishes those children from the original,
        # so a later re-upload of the same statement would re-insert the untagged
        # original and create a double entry. Detect incoming untagged rows that match
        # an existing split group (same date + base description) and drop them.
        resurrected = 0
        try:
            split_parents = set()
            with self.get_connection() as conn:
                pc = conn.cursor()
                pc.execute(
                    f"SELECT transaction_date, transaction_description FROM {table} "
                    f"WHERE transaction_description LIKE %s",
                    ('%[SPLIT%',))
                for pdate, pdesc in pc.fetchall():
                    # Compare at DATE granularity: split children may have been
                    # created date-only, while a re-uploaded original now carries time.
                    pdate_d = pdate.date() if hasattr(pdate, 'date') else pdate
                    split_parents.add((str(pdate_d), _split_parent_key(pdesc)))
                pc.close()

            if split_parents and len(df) > 0:
                def _is_resurrected_original(row):
                    desc = row['Transaction Description']
                    desc_s = '' if desc is None else str(desc)
                    if _SPLIT_TAG_RE.search(desc_s):
                        return False  # this row is itself a split child, leave it
                    rdate = row['Date']
                    rdate = rdate.date() if hasattr(rdate, 'date') else rdate
                    return (str(rdate), _split_parent_key(desc_s)) in split_parents

                pre = len(df)
                mask = df.apply(_is_resurrected_original, axis=1)
                resurrected = int(mask.sum())
                if resurrected:
                    df = df[~mask]
                    print(f"[*] Skipped {resurrected} already-split original(s) to prevent double entries")
        except Exception as e:
            # Never let the guard block a legitimate upload; just log and continue.
            print(f"[!] Split-parent guard skipped due to error: {e}")

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
                        # Preserve full datetime (incl. time-of-day) so same-day,
                        # same-amount, same-description transactions stay distinct.
                        trans_date = row['Date']
                        if hasattr(trans_date, 'to_pydatetime'):
                            trans_date = trans_date.to_pydatetime()

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
                db_dupes = len(rows_to_insert) - total_affected - results['errors']
                results['duplicates'] = intra_dupes + db_dupes + resurrected

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
        invoice_date = _parse_invoice_date(header.get('invoice_date', ''))

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
                    vehicle_number, transporter_name,
                    validation_status, validation_diff, validation_notes
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s
                )
                """

                # Reconcile the extracted numbers against each other before save.
                # Internally inconsistent bills (freight-in-GST, wrong totals) are
                # flagged 'review' so the UI can surface only the bad minority.
                # Reuse the verdict computed during extraction when present.
                validation = bill_data.get('validation') or validate_extraction(data)

                # Calculate other charges total
                other_charges_total = sum(c.get('amount', 0) or 0 for c in other_charges if c.get('description'))

                cursor.execute(invoice_query, (
                    _fit(bill_data.get('filename', ''), 255),
                    bill_data.get('page', 1),
                    _fit(header.get('invoice_number', ''), 100),
                    invoice_date,
                    _fit(header.get('irn', ''), 255),
                    _fit(header.get('ack_number', ''), 100),
                    _fit(header.get('eway_bill_number', ''), 100),
                    _fit(vendor.get('name', ''), 255),
                    _fit(vendor.get('gstin', ''), 20),
                    vendor.get('address', ''),
                    _fit(vendor.get('state', ''), 100),
                    _fit(vendor.get('pan', ''), 20),
                    _fit(vendor.get('phone', ''), 50),
                    _fit(vendor.get('bank_name', ''), 255),
                    _fit(vendor.get('bank_account', ''), 50),
                    _fit(vendor.get('bank_ifsc', ''), 20),
                    _fit(buyer.get('name', ''), 255),
                    _fit(buyer.get('gstin', ''), 20),
                    buyer.get('address', ''),
                    _fit(buyer.get('state', ''), 100),
                    _fit(ship_to.get('name', ''), 255),
                    ship_to.get('address', ''),
                    float(taxes.get('subtotal', 0) or taxes.get('taxable_amount', 0) or 0),
                    float(taxes.get('total_cgst', 0) or taxes.get('cgst_amount', 0) or 0),
                    float(taxes.get('total_sgst', 0) or taxes.get('sgst_amount', 0) or 0),
                    float(taxes.get('total_igst', 0) or taxes.get('igst_amount', 0) or 0),
                    float(other_charges_total),
                    float(taxes.get('round_off', 0) or 0),
                    float(taxes.get('total_amount', 0) or 0),
                    taxes.get('amount_in_words', ''),
                    _fit(transport.get('vehicle_number', ''), 50),
                    _fit(transport.get('transporter_name', ''), 255),
                    validation['status'],
                    validation['diff'],
                    notes_from_result(validation)
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
                                _fit(item.get('hsn_sac_code', '') or item.get('hsn_code', ''), 20),
                                float(item.get('quantity', 0) or 0),
                                _fit(item.get('uom', ''), 20),
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
            bi.validation_status, bi.validation_diff, bi.validation_notes,
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

    def check_duplicate_invoice(self, invoice_number: str, vendor_name: str = None) -> Optional[Dict]:
        """
        Check if a bill with the given invoice number already exists.

        The same invoice number can legitimately be reused by different vendors,
        so a bill is only a duplicate when BOTH the invoice number and the vendor
        name match an existing record. When vendor_name is omitted the check falls
        back to invoice-number-only matching (legacy behaviour).

        Args:
            invoice_number: The invoice number to check
            vendor_name: The vendor name to scope the check to (case-insensitive)

        Returns:
            Dict with existing bill details if duplicate found, None otherwise
        """
        if not invoice_number or invoice_number.strip() == '':
            return None

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if vendor_name and vendor_name.strip():
                    cursor.execute("""
                        SELECT id, invoice_number, invoice_date, vendor_name, vendor_gstin,
                               total_amount, filename, created_at
                        FROM bill_invoices
                        WHERE invoice_number = %s
                          AND LOWER(TRIM(vendor_name)) = LOWER(TRIM(%s))
                        LIMIT 1
                    """, (invoice_number.strip(), vendor_name.strip()))
                else:
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

        # Project matching: strict "<id> -" prefix for canonical selections,
        # stem prefix for legacy free-text ones.
        if project:
            proj_cond = build_project_filter_sql('bi.project', project, params)
            if proj_cond:
                conditions.append(proj_cond)

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

        # Project matching: strict "<id> -" prefix for canonical selections,
        # stem prefix for legacy free-text ones.
        if project:
            proj_cond = build_project_filter_sql('si.project', project, params)
            if proj_cond:
                conditions.append(proj_cond)

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

    def get_bills_for_canonical_project(self, project_id: int,
                                        kind: str = 'purchase', limit: int = 300):
        """Bills tagged with one canonical registry project.

        Strict match on the canonical "<id> - <Stem>" form (what
        normalize-projects writes / proper ingestion uses).

        kind: 'purchase' (bill_invoices) or 'sales' (sales_invoices).
        Returns (rows, {'count', 'total_taxable', 'total_gst', 'total_amount'}).

        total_taxable is the pre-tax basic value; total_amount is gross. The
        three form the basic / GST / total ladder the registry modal shows.
        """
        if kind == 'sales':
            table, items_table = 'sales_invoices', 'sales_line_items'
        else:
            table, items_table = 'bill_invoices', 'bill_line_items'

        conds = ["TRIM(b.project) LIKE %s", "TRIM(b.project) LIKE %s"]
        params = [f"{project_id} -%", f"{project_id}-%"]
        where_clause = " OR ".join(conds)

        empty_summary = {'count': 0, 'total_taxable': 0.0,
                         'total_gst': 0.0, 'total_amount': 0.0}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)

                cursor.execute(
                    f"SELECT COUNT(*) AS cnt, "
                    f"COALESCE(SUM(b.subtotal), 0) AS total_taxable, "
                    f"COALESCE(SUM(b.total_amount), 0) AS total_amount, "
                    f"COALESCE(SUM(COALESCE(b.total_cgst, 0) + COALESCE(b.total_sgst, 0) + COALESCE(b.total_igst, 0)), 0) AS total_gst "
                    f"FROM {table} b WHERE {where_clause}",
                    tuple(params)
                )
                agg = cursor.fetchone() or {}
                summary = {
                    'count': int(agg.get('cnt') or 0),
                    'total_taxable': float(agg.get('total_taxable') or 0),
                    'total_gst': float(agg.get('total_gst') or 0),
                    'total_amount': float(agg.get('total_amount') or 0),
                }

                cursor.execute(
                    f"""
                    SELECT b.id, b.invoice_number, b.invoice_date,
                           b.vendor_name, b.buyer_name,
                           b.subtotal, b.total_cgst, b.total_sgst, b.total_igst,
                           b.total_amount, b.project,
                           COUNT(li.id) AS line_item_count
                    FROM {table} b
                    LEFT JOIN {items_table} li ON b.id = li.invoice_id
                    WHERE {where_clause}
                    GROUP BY b.id
                    ORDER BY b.invoice_date DESC, b.id DESC
                    LIMIT %s
                    """,
                    tuple(params + [limit])
                )
                rows = cursor.fetchall()
                cursor.close()

                for row in rows:
                    if row.get('invoice_date'):
                        row['invoice_date'] = row['invoice_date'].strftime('%d-%b-%Y')
                    for key, val in row.items():
                        if isinstance(val, DecimalType):
                            row[key] = float(val)
                return rows, summary
        except Exception as e:
            print(f"[!] Error fetching {kind} bills for project {project_id}: {e}")
            return [], empty_summary

    def get_purchase_bill_vendors_by_project(self):
        """(project, vendor_name) for every purchase bill — cheap and unpaged.

        Feeds the material-purchase-vs-bill reconciliation on pages that list
        transactions across many projects (bank views, edit grid), where a
        per-project bills query would be N+1. One small scan of bill_invoices;
        the caller turns these rows into a project-id -> vendor-token index via
        helpers.bill_reconcile.build_bill_vendor_index.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT project, vendor_name FROM bill_invoices "
                    "WHERE project IS NOT NULL AND project <> ''"
                )
                rows = cursor.fetchall()
                cursor.close()
                return rows
        except Exception as e:
            print(f"[!] Error fetching purchase-bill vendors by project: {e}")
            return []

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

    def ensure_validation_columns(self):
        """Additive migration: add the reconciliation/validation columns to
        bill_invoices and sales_invoices. Safe on existing rows — they default
        to 'review' until re-checked by the validator or the C1 batch script.

        - validation_status ENUM('ok','review')  whether the numbers reconcile
        - validation_diff   DECIMAL(12,2)         signed header-identity gap (INR)
        - validation_notes  TEXT                  human-readable failure list
        """
        specs = [
            ("validation_status",
             "ALTER TABLE {t} ADD COLUMN validation_status "
             "ENUM('ok','review') DEFAULT 'review' AFTER total_amount"),
            ("validation_diff",
             "ALTER TABLE {t} ADD COLUMN validation_diff "
             "DECIMAL(12,2) DEFAULT 0 AFTER validation_status"),
            ("validation_notes",
             "ALTER TABLE {t} ADD COLUMN validation_notes "
             "TEXT AFTER validation_diff"),
        ]
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for table in ('bill_invoices', 'sales_invoices'):
                    for column, alter_sql in specs:
                        cursor.execute(
                            "SELECT COUNT(*) FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
                            "AND COLUMN_NAME = %s",
                            (table, column)
                        )
                        if cursor.fetchone()[0] == 0:
                            cursor.execute(alter_sql.format(t=table))
                    # Upgrade the status ENUM to allow a sticky manual 'approved'
                    # verdict (user-confirmed despite the auto-reconciliation flag).
                    # Idempotent: only runs when 'approved' isn't already allowed.
                    cursor.execute(
                        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
                        "AND COLUMN_NAME = 'validation_status'",
                        (table,)
                    )
                    row = cursor.fetchone()
                    if row and 'approved' not in (row[0] or ''):
                        cursor.execute(
                            f"ALTER TABLE {table} MODIFY COLUMN validation_status "
                            f"ENUM('ok','review','approved') DEFAULT 'review'"
                        )
                cursor.close()
                print("[+] Validation columns ensured")
                return True
        except Exception as e:
            print(f"[!] Error ensuring validation columns: {e}")
            return False

    def revalidate_existing_bills(self) -> Dict:
        """Server-side Tier-1 re-check: run the reconciliation over every stored
        bill (purchase + sales) and write the verdict back into the validation
        columns. The in-app equivalent of validate_existing_bills.py, so the
        review queue can be populated without any external script.

        Returns a summary dict: {purchase: {total, review}, sales: {...}}.
        """
        self.ensure_validation_columns()
        summary = {}
        for kind, inv_t, li_t in (
            ('purchase', 'bill_invoices', 'bill_line_items'),
            ('sales', 'sales_invoices', 'sales_line_items'),
        ):
            total = review = 0
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute(f"SELECT * FROM {inv_t}")
                    invoices = cursor.fetchall()
                    cursor.execute(f"SELECT * FROM {li_t} ORDER BY invoice_id, sl_no")
                    line_rows = cursor.fetchall()

                    by_invoice = {}
                    for li in line_rows:
                        by_invoice.setdefault(li['invoice_id'], []).append(li)

                    upd = cursor  # reuse same cursor/connection for the writes
                    for inv in invoices:
                        total += 1
                        # Manual approval is sticky — never overwrite it on a
                        # bulk re-check, so the user's decision survives.
                        if inv.get('validation_status') == 'approved':
                            continue
                        v = validate_db_row(inv, by_invoice.get(inv['id'], []))
                        if v['status'] == 'review':
                            review += 1
                        upd.execute(
                            f"UPDATE {inv_t} SET validation_status=%s, "
                            f"validation_diff=%s, validation_notes=%s WHERE id=%s",
                            (v['status'], v['diff'], notes_from_result(v), inv['id'])
                        )
                    conn.commit()
                    cursor.close()
            except Exception as e:
                print(f"[!] revalidate {kind} error: {e}")
            summary[kind] = {'total': total, 'review': review}
        print(f"[+] Revalidated existing bills: {summary}")
        return summary

    def approve_bill_validation(self, invoice_id: int, kind: str = 'purchase') -> Tuple[bool, Optional[str]]:
        """Manually mark a bill's reconciliation verdict as 'approved' — a
        human-confirmed OK that the auto-reconciliation couldn't certify. This
        is sticky: revalidate_existing_bills skips approved rows, so it survives
        future re-checks. The original failure notes are left intact for audit.
        """
        inv_t = 'sales_invoices' if kind == 'sales' else 'bill_invoices'
        try:
            self.ensure_validation_columns()
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE {inv_t} SET validation_status='approved', "
                    f"updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (invoice_id,)
                )
                affected = cursor.rowcount
                conn.commit()
                cursor.close()
            if affected == 0:
                return False, 'Bill not found'
            return True, None
        except Exception as e:
            print(f"[!] approve_bill_validation error: {e}")
            return False, str(e)

    def recheck_bill_validation(self, invoice_id: int, kind: str = 'purchase') -> Tuple[bool, Optional[str]]:
        """Recompute one stored bill's reconciliation verdict and write it back,
        clearing any manual approval. The single-row version of
        revalidate_existing_bills. Returns (True, new_status) on success.
        """
        inv_t = 'sales_invoices' if kind == 'sales' else 'bill_invoices'
        li_t = 'sales_line_items' if kind == 'sales' else 'bill_line_items'
        try:
            self.ensure_validation_columns()
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(f"SELECT * FROM {inv_t} WHERE id=%s", (invoice_id,))
                inv = cursor.fetchone()
                if not inv:
                    cursor.close()
                    return False, 'Bill not found'
                cursor.execute(
                    f"SELECT * FROM {li_t} WHERE invoice_id=%s ORDER BY sl_no",
                    (invoice_id,)
                )
                items = cursor.fetchall()
                v = validate_db_row(inv, items)
                cursor.execute(
                    f"UPDATE {inv_t} SET validation_status=%s, validation_diff=%s, "
                    f"validation_notes=%s WHERE id=%s",
                    (v['status'], v['diff'], notes_from_result(v), invoice_id)
                )
                conn.commit()
                cursor.close()
            return True, v['status']
        except Exception as e:
            print(f"[!] recheck_bill_validation error: {e}")
            return False, str(e)

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

        invoice_date = _parse_invoice_date(header.get('invoice_date', ''))

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
                    vehicle_number, transporter_name,
                    validation_status, validation_diff, validation_notes
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s
                )
                """

                # Same reconciliation as purchase bills (see insert_bill).
                validation = bill_data.get('validation') or validate_extraction(data)

                other_charges_total = sum(c.get('amount', 0) or 0 for c in other_charges if c.get('description'))

                cursor.execute(invoice_query, (
                    _fit(bill_data.get('filename', ''), 255),
                    bill_data.get('page', 1),
                    _fit(header.get('invoice_number', ''), 100),
                    invoice_date,
                    _fit(header.get('irn', ''), 255),
                    _fit(header.get('ack_number', ''), 100),
                    _fit(header.get('eway_bill_number', ''), 100),
                    _fit(vendor.get('name', ''), 255),
                    _fit(vendor.get('gstin', ''), 20),
                    vendor.get('address', ''),
                    _fit(vendor.get('state', ''), 100),
                    _fit(vendor.get('pan', ''), 20),
                    _fit(vendor.get('phone', ''), 50),
                    _fit(vendor.get('bank_name', ''), 255),
                    _fit(vendor.get('bank_account', ''), 50),
                    _fit(vendor.get('bank_ifsc', ''), 20),
                    _fit(buyer.get('name', ''), 255),
                    _fit(buyer.get('gstin', ''), 20),
                    buyer.get('address', ''),
                    _fit(buyer.get('state', ''), 100),
                    _fit(ship_to.get('name', ''), 255),
                    ship_to.get('address', ''),
                    float(taxes.get('subtotal', 0) or taxes.get('taxable_amount', 0) or 0),
                    float(taxes.get('total_cgst', 0) or taxes.get('cgst_amount', 0) or 0),
                    float(taxes.get('total_sgst', 0) or taxes.get('sgst_amount', 0) or 0),
                    float(taxes.get('total_igst', 0) or taxes.get('igst_amount', 0) or 0),
                    float(other_charges_total),
                    float(taxes.get('round_off', 0) or 0),
                    float(taxes.get('total_amount', 0) or 0),
                    taxes.get('amount_in_words', ''),
                    _fit(transport.get('vehicle_number', ''), 50),
                    _fit(transport.get('transporter_name', ''), 255),
                    validation['status'],
                    validation['diff'],
                    notes_from_result(validation)
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
                                _fit(item.get('hsn_sac_code', '') or item.get('hsn_code', ''), 20),
                                float(item.get('quantity', 0) or 0),
                                _fit(item.get('uom', ''), 20),
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
            si.validation_status, si.validation_diff, si.validation_notes,
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

    def check_duplicate_sales_invoice(self, invoice_number: str, vendor_name: str = None) -> Optional[Dict]:
        """Check if a sales bill with the given invoice number already exists.

        A bill is only a duplicate when BOTH the invoice number and the vendor
        name match, since different vendors can reuse the same invoice number.
        When vendor_name is omitted the check falls back to invoice-number-only
        matching (legacy behaviour).
        """
        if not invoice_number or invoice_number.strip() == '':
            return None

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                if vendor_name and vendor_name.strip():
                    cursor.execute("""
                        SELECT id, invoice_number, invoice_date, vendor_name, vendor_gstin,
                               total_amount, filename, created_at
                        FROM sales_invoices
                        WHERE invoice_number = %s
                          AND LOWER(TRIM(vendor_name)) = LOWER(TRIM(%s))
                        LIMIT 1
                    """, (invoice_number.strip(), vendor_name.strip()))
                else:
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
        invoice_date = _parse_invoice_date(bill_data.get('invoice_date', ''))

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
                    validation_status = %s,
                    validation_diff = %s,
                    validation_notes = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """

                # Re-validate from the updated numbers so every edit / reprocess
                # refreshes the reconciliation verdict (validate_db_row reads the
                # same flat keys this update writes).
                validation = validate_db_row(bill_data, bill_data.get('line_items', []))

                cursor.execute(update_query, (
                    _fit(bill_data.get('invoice_number', ''), 100),
                    invoice_date,
                    _fit(bill_data.get('irn', ''), 255),
                    _fit(bill_data.get('ack_number', ''), 100),
                    _fit(bill_data.get('eway_bill_number', ''), 100),
                    _fit(bill_data.get('vendor_name', ''), 255),
                    _fit(bill_data.get('vendor_gstin', ''), 20),
                    bill_data.get('vendor_address', ''),
                    _fit(bill_data.get('vendor_state', ''), 100),
                    _fit(bill_data.get('vendor_pan', ''), 20),
                    _fit(bill_data.get('vendor_phone', ''), 50),
                    _fit(bill_data.get('vendor_bank_name', ''), 255),
                    _fit(bill_data.get('vendor_bank_account', ''), 50),
                    _fit(bill_data.get('vendor_bank_ifsc', ''), 20),
                    _fit(bill_data.get('buyer_name', ''), 255),
                    _fit(bill_data.get('buyer_gstin', ''), 20),
                    bill_data.get('buyer_address', ''),
                    _fit(bill_data.get('buyer_state', ''), 100),
                    _fit(bill_data.get('ship_to_name', ''), 255),
                    bill_data.get('ship_to_address', ''),
                    float(bill_data.get('subtotal', 0) or 0),
                    float(bill_data.get('total_cgst', 0) or 0),
                    float(bill_data.get('total_sgst', 0) or 0),
                    float(bill_data.get('total_igst', 0) or 0),
                    float(bill_data.get('other_charges', 0) or 0),
                    float(bill_data.get('round_off', 0) or 0),
                    float(bill_data.get('total_amount', 0) or 0),
                    bill_data.get('amount_in_words', ''),
                    _fit(bill_data.get('vehicle_number', ''), 50),
                    _fit(bill_data.get('transporter_name', ''), 255),
                    bill_data.get('project', '') or None,
                    validation['status'],
                    validation['diff'],
                    notes_from_result(validation),
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
                                _fit(item.get('hsn_sac_code', ''), 20),
                                float(item.get('quantity', 0) or 0),
                                _fit(item.get('uom', ''), 20),
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

    # ========================================================================
    # PROJECTS REFERENCE TABLE (canonical source of project ids + stem names)
    # ========================================================================

    def ensure_projects_table(self):
        """Create the projects reference table if it doesn't exist."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS projects (
                        id           INT PRIMARY KEY,
                        stem_name    VARCHAR(255) NOT NULL,
                        po_filename  VARCHAR(255) DEFAULT NULL,
                        po_path      VARCHAR(500) DEFAULT NULL,
                        description  TEXT DEFAULT NULL,
                        is_project   TINYINT(1) NOT NULL DEFAULT 1,
                        project_type VARCHAR(16) NOT NULL DEFAULT 'project',
                        is_inactive  TINYINT(1) NOT NULL DEFAULT 0,
                        overhead     DECIMAL(15, 2) NOT NULL DEFAULT 0,
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_stem_ci (stem_name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                # Additive migration: add is_project to tables created before the
                # column existed. is_project = 1 -> a real project, 0 -> an internal
                # expense head / "other" (office, factory, KVB, sridhar, ...).
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' "
                    "AND COLUMN_NAME = 'is_project'"
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "ALTER TABLE projects "
                        "ADD COLUMN is_project TINYINT(1) NOT NULL DEFAULT 1 AFTER description"
                    )
                    # Seed the known internal "others" by name (case-insensitive).
                    # GHEE FACTORY etc. stay projects because we match exact stems.
                    cursor.execute(
                        "UPDATE projects SET is_project = 0 "
                        "WHERE UPPER(TRIM(stem_name)) IN "
                        "('OFFICE EXPENSE', 'FACTORY EXPENSE', 'KVB', 'SRIDHAR')"
                    )
                # Additive migration: project_type supersedes the is_project boolean
                # with a third option ("design"). is_project is kept in sync (1 only
                # for real projects) so any older reader still works.
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' "
                    "AND COLUMN_NAME = 'project_type'"
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "ALTER TABLE projects "
                        "ADD COLUMN project_type VARCHAR(16) NOT NULL DEFAULT 'project' AFTER is_project"
                    )
                    cursor.execute("UPDATE projects SET project_type = 'project' WHERE is_project = 1")
                    cursor.execute("UPDATE projects SET project_type = 'other' WHERE is_project = 0")
                # Additive migration: is_inactive marks a closed project. Closed
                # entries keep their type but are grouped into a separate "Closed"
                # section at the bottom of the registry.
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' "
                    "AND COLUMN_NAME = 'is_inactive'"
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "ALTER TABLE projects "
                        "ADD COLUMN is_inactive TINYINT(1) NOT NULL DEFAULT 0 AFTER project_type"
                    )
                # Additive migration: overhead is a manually entered cost the bank
                # data can't know about (the client types it into their sheet). It
                # feeds the project's cost total alongside material/labour/GST.
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' "
                    "AND COLUMN_NAME = 'overhead'"
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "ALTER TABLE projects "
                        "ADD COLUMN overhead DECIMAL(15, 2) NOT NULL DEFAULT 0 AFTER is_inactive"
                    )
                cursor.close()
            # The PO gist table is joined by list/get; keep it alongside.
            self.ensure_project_pos_table()
            # Cash client payments live in their own ledger table.
            self.ensure_project_cash_table()
            # The two contract ledgers, joined by list/get the same way.
            self.ensure_po_ledger_tables()
            return True
        except Exception as e:
            print(f"[!] Error ensuring projects table: {e}")
            return False

    def ensure_project_pos_table(self):
        """Create the project_pos table (PO gist, 1:1 with projects)."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS project_pos (
                        project_id        INT PRIMARY KEY,
                        po_number         VARCHAR(100) DEFAULT NULL,
                        po_date           DATE DEFAULT NULL,
                        client_name       VARCHAR(255) DEFAULT NULL,
                        currency          VARCHAR(8) DEFAULT 'INR',
                        taxable_value     DECIMAL(15, 2) DEFAULT 0,
                        total_tax         DECIMAL(15, 2) DEFAULT 0,
                        total_value       DECIMAL(15, 2) DEFAULT 0,
                        amount_in_words   TEXT DEFAULT NULL,
                        line_item_count   INT DEFAULT 0,
                        line_items        LONGTEXT DEFAULT NULL,
                        payment_terms     TEXT DEFAULT NULL,
                        source_filename   VARCHAR(255) DEFAULT NULL,
                        extracted_model   VARCHAR(100) DEFAULT NULL,
                        extraction_status ENUM('success', 'failed', 'manual') DEFAULT 'success',
                        extraction_error  TEXT DEFAULT NULL,
                        raw_json          LONGTEXT DEFAULT NULL,
                        created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        CONSTRAINT fk_projectpo_project FOREIGN KEY (project_id)
                            REFERENCES projects(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                # Additive migration: add line_items to tables created before it
                # existed (e.g. the local table from the backfill).
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'project_pos' "
                    "AND COLUMN_NAME = 'line_items'"
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "ALTER TABLE project_pos "
                        "ADD COLUMN line_items LONGTEXT DEFAULT NULL AFTER line_item_count"
                    )
                cursor.close()
                return True
        except Exception as e:
            print(f"[!] Error ensuring project_pos table: {e}")
            return False

    # ── The two PO ledgers ──────────────────────────────────────────────────
    # A signed contract moves in two quite different ways, and each gets its own
    # N:1 ledger of identically-shaped priced lines (description / quantity /
    # unit / rate, priced to basic / tax / total by compute_ledger_amounts):
    #
    #   variation  a change agreed after signing — extra tonnage, or scope
    #              dropped. These are *deltas* and add to the PO. A reduction is
    #              a negative quantity, so negatives are legal here.
    #   actual     the work as finally measured on completion. This is an
    #              *absolute restatement* and replaces the PO outright, because
    #              a project that came in under its PO can't honestly be written
    #              as a delta (see resolve_contract). A measurement can't be
    #              negative, so negatives are rejected here.
    #
    # Either way project_pos is left exactly as extracted: it mirrors the PDF
    # still sitting behind "View PO document", and *why* the value moved stays
    # answerable. Everything the two ledgers share — DDL, pricing, CRUD — is one
    # implementation parameterised by this spec rather than two that drift.
    PO_LEDGERS = {
        'variation': {'table': 'project_po_variations', 'date_col': 'variation_date',
                      'fk': 'ppv', 'allow_negative_qty': True},
        'actual':    {'table': 'project_po_actuals',    'date_col': 'actual_date',
                      'fk': 'ppa', 'allow_negative_qty': False},
    }

    @classmethod
    def _ledger(cls, kind: str) -> Dict:
        try:
            return cls.PO_LEDGERS[kind]
        except KeyError:
            raise ValueError(f"unknown PO ledger {kind!r}")

    def ensure_po_ledger_tables(self) -> bool:
        """Create both PO ledger tables (N:1 with projects). See PO_LEDGERS."""
        return all(self.ensure_po_ledger_table(k) for k in self.PO_LEDGERS)

    def ensure_po_ledger_table(self, kind: str) -> bool:
        spec = self._ledger(kind)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {spec['table']} (
                        id             INT AUTO_INCREMENT PRIMARY KEY,
                        project_id     INT NOT NULL,
                        description    VARCHAR(500) DEFAULT NULL,
                        quantity       DECIMAL(15, 3) NOT NULL DEFAULT 0,
                        unit           VARCHAR(32) DEFAULT NULL,
                        rate           DECIMAL(15, 2) NOT NULL DEFAULT 0,
                        gst_rate       DECIMAL(5, 2) NOT NULL DEFAULT 18.00,
                        basic_amount   DECIMAL(15, 2) NOT NULL DEFAULT 0,
                        tax_amount     DECIMAL(15, 2) NOT NULL DEFAULT 0,
                        total_amount   DECIMAL(15, 2) NOT NULL DEFAULT 0,
                        {spec['date_col']:<14} DATE DEFAULT NULL,
                        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_{spec['fk']}_project (project_id),
                        CONSTRAINT fk_{spec['fk']}_project FOREIGN KEY (project_id)
                            REFERENCES projects(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                cursor.close()
                return True
        except Exception as e:
            print(f"[!] Error ensuring {spec['table']} table: {e}")
            return False

    def ensure_project_cash_table(self):
        """Create the project_cash_payments ledger (N:1 with projects).

        Client money arrives two ways: bank transfers to KVB (captured from the
        statement and summed in get_kvb_credit_by_project) and cash handed over
        outside the bank. Cash never shows up in a statement, so we record each
        cash receipt here as its own row; the project's received total is the
        bank credits plus the sum of these rows.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS project_cash_payments (
                        id           INT AUTO_INCREMENT PRIMARY KEY,
                        project_id   INT NOT NULL,
                        amount       DECIMAL(15, 2) NOT NULL,
                        payment_date DATE DEFAULT NULL,
                        note         VARCHAR(500) DEFAULT NULL,
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_pcp_project (project_id),
                        CONSTRAINT fk_pcp_project FOREIGN KEY (project_id)
                            REFERENCES projects(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                cursor.close()
                return True
        except Exception as e:
            print(f"[!] Error ensuring project_cash_payments table: {e}")
            return False

    # SELECT that augments each project row with a compact PO summary (the
    # gist columns the cards/detail need) via a LEFT JOIN on project_pos, plus
    # both contract ledgers rolled up from project_po_variations and
    # project_po_actuals.
    #
    # The ledgers are folded into po_total_value & friends by
    # _decorate_project_row, so every caller — registry list, detail insights,
    # Excel export — reads the contract *actually in force* without having to
    # know either ledger exists. The untouched baseline stays addressable as
    # po_base_*, and the rollups as po_var_* / po_act_*, for the places that
    # show the ladder itself (the PO section, the glance, the export).
    _PROJECT_SELECT = (
        "SELECT p.id, p.stem_name, p.po_filename, p.po_path, p.description, p.is_project, p.project_type, p.is_inactive, p.overhead, p.created_at, "
        "       pp.po_number AS po_number, pp.total_value AS po_base_total_value, "
        "       pp.taxable_value AS po_base_taxable_value, pp.total_tax AS po_base_total_tax, "
        "       pp.extraction_status AS po_extraction_status, "
        "       COALESCE(pv.var_taxable, 0) AS po_var_taxable, "
        "       COALESCE(pv.var_tax, 0) AS po_var_tax, "
        "       COALESCE(pv.var_total, 0) AS po_var_total, "
        "       COALESCE(pv.var_count, 0) AS po_var_count, "
        "       COALESCE(pa.act_taxable, 0) AS po_act_taxable, "
        "       COALESCE(pa.act_tax, 0) AS po_act_tax, "
        "       COALESCE(pa.act_total, 0) AS po_act_total, "
        "       COALESCE(pa.act_count, 0) AS po_act_count "
        "FROM projects p LEFT JOIN project_pos pp ON pp.project_id = p.id "
        "LEFT JOIN (SELECT project_id, "
        "                  SUM(basic_amount) AS var_taxable, "
        "                  SUM(tax_amount)   AS var_tax, "
        "                  SUM(total_amount) AS var_total, "
        "                  COUNT(*)          AS var_count "
        "           FROM project_po_variations GROUP BY project_id) pv "
        "  ON pv.project_id = p.id "
        "LEFT JOIN (SELECT project_id, "
        "                  SUM(basic_amount) AS act_taxable, "
        "                  SUM(tax_amount)   AS act_tax, "
        "                  SUM(total_amount) AS act_total, "
        "                  COUNT(*)          AS act_count "
        "           FROM project_po_actuals GROUP BY project_id) pa "
        "  ON pa.project_id = p.id"
    )

    # The three registry buckets. is_project is kept for backward compatibility
    # and is true only for the canonical "project" type.
    VALID_PROJECT_TYPES = ('project', 'design', 'other')

    @staticmethod
    def _decorate_project_row(r: Dict) -> Dict:
        r['display'] = f"{r['id']} - {r['stem_name']}"
        r['has_po'] = bool(r['po_filename'])
        # project_type is the source of truth; fall back to the legacy boolean
        # for any row that predates the column.
        ptype = (r.get('project_type') or
                 ('project' if r.get('is_project', 1) else 'other'))
        if ptype not in DatabaseManager.VALID_PROJECT_TYPES:
            ptype = 'project'
        r['project_type'] = ptype
        r['is_project'] = (ptype == 'project')
        r['is_inactive'] = bool(r.get('is_inactive', 0))
        if r.get('created_at') and hasattr(r['created_at'], 'isoformat'):
            r['created_at'] = r['created_at'].isoformat()
        # Coerce DECIMAL -> float for JSON
        for key in ('po_base_total_value', 'po_base_taxable_value', 'po_base_total_tax',
                    'po_var_taxable', 'po_var_tax', 'po_var_total',
                    'po_act_taxable', 'po_act_tax', 'po_act_total'):
            if r.get(key) is not None:
                r[key] = float(r[key])
        r['po_var_count'] = int(r.get('po_var_count') or 0)
        r['po_act_count'] = int(r.get('po_act_count') or 0)
        # Fold both ledgers into the headline PO figures. None means "no value
        # here at all" and has to survive per-field — callers lean on `or 0`,
        # but the export tells a missing figure apart from a zero one, so a
        # component that was never present must not acquire a spurious 0.00.
        # Each of the three keys is decided against its *own* base column, so a
        # gist that extracted a total but no taxable/tax split keeps those two
        # None while the total stands. A contribution from either ledger ends a
        # field's None: a hand-entered scope can be varied or measured with no
        # PO document behind it at all.
        contract = resolve_contract(
            {'taxable': r.get('po_base_taxable_value'),
             'tax': r.get('po_base_total_tax'),
             'total': r.get('po_base_total_value')},
            {'taxable': r['po_var_taxable'], 'tax': r['po_var_tax'],
             'total': r['po_var_total']},
            {'taxable': r['po_act_taxable'], 'tax': r['po_act_tax'],
             'total': r['po_act_total']},
            has_actuals=bool(r['po_act_count']),
        )
        final = contract['final']
        has_ledger = bool(r['po_var_count'] or r['po_act_count'])
        for out_key, base_key, comp in (
            ('po_total_value', 'po_base_total_value', 'total'),
            ('po_taxable_value', 'po_base_taxable_value', 'taxable'),
            ('po_total_tax', 'po_base_total_tax', 'tax'),
        ):
            r[out_key] = (None if (r.get(base_key) is None and not has_ledger)
                          else final[comp])
        # overhead is NOT NULL DEFAULT 0, but older rows read through a cached
        # connection can still surface None — normalise to a plain float.
        r['overhead'] = float(r.get('overhead') or 0)
        return r

    def list_projects(self) -> List[Dict]:
        """Return all canonical projects ordered by id, with PO gist summary."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(self._PROJECT_SELECT + " ORDER BY p.is_inactive, p.id")
                rows = cursor.fetchall()
                cursor.close()
                return [self._decorate_project_row(r) for r in rows]
        except Exception as e:
            print(f"[!] Error listing projects: {e}")
            return []

    def get_kvb_credit_by_project(self) -> List[Tuple[str, float]]:
        """Sum incoming client payments (KVB credit amounts) grouped by the
        raw project string on each transaction.

        Returns [(project_string, total_credit), ...]. The caller maps these
        free-text project strings onto canonical projects by stem. Only credit
        (cr_amount > 0) rows count — those are money received from clients.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT TRIM(project) AS project, COALESCE(SUM(cr_amount), 0) AS received "
                    "FROM kvb_transactions "
                    "WHERE cr_amount IS NOT NULL AND cr_amount > 0 "
                    "  AND project IS NOT NULL AND TRIM(project) != '' "
                    "GROUP BY TRIM(project)"
                )
                rows = cursor.fetchall()
                cursor.close()
                return [(r[0], float(r[1] or 0)) for r in rows]
        except Exception as e:
            print(f"[!] Error fetching KVB credit by project: {e}")
            return []

    def get_cash_total_by_project(self) -> Dict[int, float]:
        """Sum recorded cash client payments grouped by project id.

        Returns {project_id: total_cash}. Mirrors get_kvb_credit_by_project but
        keyed directly by the canonical project id (no string parsing needed —
        cash rows are tagged with the project id at entry time).
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT project_id, COALESCE(SUM(amount), 0) "
                    "FROM project_cash_payments GROUP BY project_id"
                )
                rows = cursor.fetchall()
                cursor.close()
                return {int(r[0]): float(r[1] or 0) for r in rows}
        except Exception as e:
            print(f"[!] Error fetching cash totals by project: {e}")
            return {}

    def list_cash_payments(self, project_id: int) -> List[Dict]:
        """Return individual cash payment rows for a project, newest first."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id, project_id, amount, payment_date, note, created_at "
                    "FROM project_cash_payments WHERE project_id = %s "
                    "ORDER BY COALESCE(payment_date, DATE(created_at)) DESC, id DESC",
                    (project_id,)
                )
                rows = cursor.fetchall()
                cursor.close()
                for r in rows:
                    r['amount'] = float(r['amount'] or 0)
                    if r.get('payment_date') and hasattr(r['payment_date'], 'isoformat'):
                        r['payment_date'] = r['payment_date'].isoformat()
                    if r.get('created_at') and hasattr(r['created_at'], 'isoformat'):
                        r['created_at'] = r['created_at'].isoformat()
                return rows
        except Exception as e:
            print(f"[!] Error listing cash payments for {project_id}: {e}")
            return []

    def add_cash_payment(self, project_id: int, amount: float,
                         payment_date=None, note: str = None) -> Tuple[bool, Optional[str], Optional[int]]:
        """Record one cash client payment. Returns (ok, error, new_id)."""
        try:
            pay_date = self._parse_po_date(payment_date) if payment_date else None
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO project_cash_payments (project_id, amount, payment_date, note) "
                    "VALUES (%s, %s, %s, %s)",
                    (project_id, amount, pay_date, note)
                )
                conn.commit()
                new_id = cursor.lastrowid
                cursor.close()
                return True, None, new_id
        except mysql.connector.errors.IntegrityError:
            return False, 'project_not_found', None
        except Exception as e:
            return False, str(e), None

    def delete_cash_payment(self, project_id: int, payment_id: int) -> Tuple[bool, Optional[str]]:
        """Delete a single cash payment row, scoped to its project."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM project_cash_payments WHERE id = %s AND project_id = %s",
                    (payment_id, project_id)
                )
                conn.commit()
                affected = cursor.rowcount
                cursor.close()
                if affected == 0:
                    return False, 'not_found'
                return True, None
        except Exception as e:
            return False, str(e)

    def get_project(self, project_id: int) -> Optional[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(self._PROJECT_SELECT + " WHERE p.id = %s", (project_id,))
                row = cursor.fetchone()
                cursor.close()
                if row:
                    self._decorate_project_row(row)
                return row
        except Exception as e:
            print(f"[!] Error fetching project {project_id}: {e}")
            return None

    def find_project_by_stem(self, stem_name: str) -> Optional[Dict]:
        """Case-insensitive stem lookup."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id, stem_name FROM projects WHERE LOWER(stem_name) = LOWER(%s)",
                    (stem_name,)
                )
                row = cursor.fetchone()
                cursor.close()
                return row
        except Exception as e:
            print(f"[!] Error finding project by stem: {e}")
            return None

    def create_project(self, project_id: int, stem_name: str,
                       po_filename: str = None, po_path: str = None,
                       project_type: str = 'project') -> Tuple[bool, Optional[str]]:
        """Insert a new project. Returns (ok, error_message).

        project_type is one of 'project' (a real client/site project),
        'design' (design-only work), or 'other' (internal expense head like
        office/factory/KVB/sridhar). is_project is stored in sync (1 only for
        'project') for backward compatibility.
        """
        if project_type not in self.VALID_PROJECT_TYPES:
            project_type = 'project'
        is_project = 1 if project_type == 'project' else 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO projects (id, stem_name, po_filename, po_path, is_project, project_type) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (project_id, stem_name, po_filename, po_path, is_project, project_type)
                )
                conn.commit()
                cursor.close()
                return True, None
        except mysql.connector.errors.IntegrityError as e:
            msg = str(e)
            if 'PRIMARY' in msg:
                return False, 'duplicate_id'
            if 'uk_stem_ci' in msg or 'stem_name' in msg:
                return False, 'duplicate_stem'
            return False, msg
        except Exception as e:
            return False, str(e)

    def set_project_type(self, project_id: int, project_type: str) -> Tuple[bool, Optional[str]]:
        """Change a registry entry's type to 'project', 'design' or 'other'.
        Keeps the legacy is_project boolean in sync (1 only for 'project')."""
        if project_type not in self.VALID_PROJECT_TYPES:
            return False, 'invalid_type'
        is_project = 1 if project_type == 'project' else 0
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE projects SET project_type = %s, is_project = %s WHERE id = %s",
                    (project_type, is_project, project_id)
                )
                conn.commit()
                affected = cursor.rowcount
                cursor.close()
                if affected == 0:
                    return False, 'not_found'
                return True, None
        except Exception as e:
            return False, str(e)

    def set_project_inactive(self, project_id: int, is_inactive: bool) -> Tuple[bool, Optional[str]]:
        """Mark a registry entry closed (inactive) or reopen it. Closed entries
        keep their type but sink into the registry's "Closed" section."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE projects SET is_inactive = %s WHERE id = %s",
                    (1 if is_inactive else 0, project_id)
                )
                conn.commit()
                affected = cursor.rowcount
                cursor.close()
                if affected == 0:
                    return False, 'not_found'
                return True, None
        except Exception as e:
            return False, str(e)

    def set_project_overhead(self, project_id: int, overhead: float) -> Tuple[bool, Optional[str]]:
        """Set a project's manually entered overhead cost.

        Overhead is money the bank/bill data can't account for (the client
        types it into their own sheet), so it is entered by hand and feeds the
        project's cost total.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Existence is checked via SELECT rather than rowcount: MySQL
                # reports 0 affected rows when the value written equals the one
                # already stored, so re-saving an unchanged overhead would
                # otherwise look like a missing project.
                cursor.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
                if cursor.fetchone() is None:
                    cursor.close()
                    return False, 'not_found'
                cursor.execute(
                    "UPDATE projects SET overhead = %s WHERE id = %s",
                    (overhead, project_id)
                )
                conn.commit()
                cursor.close()
                return True, None
        except Exception as e:
            return False, str(e)

    def attach_project_po(self, project_id: int, po_filename: str, po_path: str) -> Tuple[bool, Optional[str]]:
        """Set the PO file for a project, only if one isn't already attached."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE projects SET po_filename = %s, po_path = %s "
                    "WHERE id = %s AND po_filename IS NULL",
                    (po_filename, po_path, project_id)
                )
                affected = cursor.rowcount
                conn.commit()
                cursor.close()
                if affected == 0:
                    return False, 'po_already_attached_or_missing_project'
                return True, None
        except Exception as e:
            return False, str(e)

    # ── Project PO gist (project_pos) ────────────────────────

    @staticmethod
    def _parse_po_date(value):
        """Accept 'DD-MMM-YYYY' (or a few common forms) -> date / None."""
        if not value:
            return None
        s = str(value).strip()
        for fmt in ('%d-%b-%Y', '%d-%B-%Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def upsert_project_po(self, project_id: int, data: dict, *,
                          model: Optional[str] = None,
                          status: str = 'success',
                          error: Optional[str] = None,
                          raw_json: Optional[str] = None,
                          source_filename: Optional[str] = None,
                          force: bool = False) -> Tuple[bool, Optional[str]]:
        """Insert or update the PO gist for a project.

        A row previously edited by hand (extraction_status='manual') is left
        untouched unless force=True, so a reprocess can't silently clobber a
        manual correction.
        """
        self.ensure_project_pos_table()
        data = data or {}
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                if not force:
                    cursor.execute(
                        "SELECT extraction_status FROM project_pos WHERE project_id = %s",
                        (project_id,)
                    )
                    existing = cursor.fetchone()
                    if existing and existing[0] == 'manual':
                        cursor.close()
                        return False, 'manual_locked'

                cursor.execute(
                    """
                    INSERT INTO project_pos
                        (project_id, po_number, po_date, client_name, currency,
                         taxable_value, total_tax, total_value, amount_in_words,
                         line_item_count, line_items, payment_terms, source_filename,
                         extracted_model, extraction_status, extraction_error, raw_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        po_number = VALUES(po_number),
                        po_date = VALUES(po_date),
                        client_name = VALUES(client_name),
                        currency = VALUES(currency),
                        taxable_value = VALUES(taxable_value),
                        total_tax = VALUES(total_tax),
                        total_value = VALUES(total_value),
                        amount_in_words = VALUES(amount_in_words),
                        line_item_count = VALUES(line_item_count),
                        line_items = VALUES(line_items),
                        payment_terms = VALUES(payment_terms),
                        source_filename = VALUES(source_filename),
                        extracted_model = VALUES(extracted_model),
                        extraction_status = VALUES(extraction_status),
                        extraction_error = VALUES(extraction_error),
                        raw_json = VALUES(raw_json)
                    """,
                    (
                        project_id,
                        data.get('po_number') or None,
                        self._parse_po_date(data.get('po_date')),
                        data.get('client_name') or None,
                        data.get('currency') or 'INR',
                        data.get('taxable_value') or 0,
                        data.get('total_tax') or 0,
                        data.get('total_value') or 0,
                        data.get('amount_in_words') or None,
                        int(data.get('line_item_count') or 0),
                        (json.dumps(data.get('line_items'), ensure_ascii=False)
                         if data.get('line_items') else None),
                        data.get('payment_terms') or None,
                        source_filename,
                        model,
                        status,
                        error,
                        raw_json,
                    )
                )
                conn.commit()
                cursor.close()
                return True, None
        except Exception as e:
            return False, str(e)

    def get_project_po(self, project_id: int) -> Optional[Dict]:
        """Return the full PO gist row for a project (or None)."""
        self.ensure_project_pos_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT project_id, po_number, po_date, client_name, currency, "
                    "       taxable_value, total_tax, total_value, amount_in_words, "
                    "       line_item_count, line_items, payment_terms, source_filename, "
                    "       extracted_model, extraction_status, extraction_error, "
                    "       created_at, updated_at "
                    "FROM project_pos WHERE project_id = %s",
                    (project_id,)
                )
                row = cursor.fetchone()
                cursor.close()
                if not row:
                    return None
                for k in ('taxable_value', 'total_tax', 'total_value'):
                    if row.get(k) is not None:
                        row[k] = float(row[k])
                for k in ('po_date', 'created_at', 'updated_at'):
                    if row.get(k) is not None and hasattr(row[k], 'isoformat'):
                        row[k] = row[k].isoformat()
                # line_items is stored as a JSON string -> hand back a list.
                if row.get('line_items'):
                    try:
                        row['line_items'] = json.loads(row['line_items'])
                    except (ValueError, TypeError):
                        row['line_items'] = []
                else:
                    row['line_items'] = []
                return row
        except Exception as e:
            print(f"[!] Error fetching project PO {project_id}: {e}")
            return None

    def update_project_po_fields(self, project_id: int, fields: dict) -> Tuple[bool, Optional[str]]:
        """Apply user-corrected gist fields; flips extraction_status to 'manual'.

        Only a whitelist of gist columns is writable.
        """
        self.ensure_project_pos_table()
        allowed = {
            'po_number': lambda v: (str(v).strip() or None),
            'po_date': self._parse_po_date,
            'client_name': lambda v: (str(v).strip() or None),
            'currency': lambda v: (str(v).strip() or 'INR'),
            'taxable_value': lambda v: float(v or 0),
            'total_tax': lambda v: float(v or 0),
            'total_value': lambda v: float(v or 0),
            'amount_in_words': lambda v: (str(v).strip() or None),
            'line_item_count': lambda v: int(v or 0),
            'payment_terms': lambda v: (str(v).strip() or None),
        }
        sets, params = [], []
        for key, coerce in allowed.items():
            if key in fields:
                try:
                    params.append(coerce(fields[key]))
                except (ValueError, TypeError):
                    return False, f'invalid value for {key}'
                sets.append(f"{key} = %s")
        if not sets:
            return False, 'no_editable_fields'
        sets.append("extraction_status = 'manual'")

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Ensure a row exists (e.g. extraction never produced one).
                cursor.execute(
                    "INSERT IGNORE INTO project_pos (project_id, extraction_status) "
                    "VALUES (%s, 'manual')",
                    (project_id,)
                )
                cursor.execute(
                    f"UPDATE project_pos SET {', '.join(sets)} WHERE project_id = %s",
                    tuple(params) + (project_id,)
                )
                conn.commit()
                cursor.close()
                return True, None
        except Exception as e:
            return False, str(e)

    # ── PO ledger CRUD: one implementation for variations and actuals ───────
    # See PO_LEDGERS for what the two are and why they share everything below.
    # `kind` is never user input — the routes map a fixed URL slug onto it — so
    # interpolating spec['table'] into these statements can't be reached by a
    # caller. _ledger() raises on anything unknown regardless.

    @staticmethod
    def _ledger_row(kind: str, r: Dict) -> Dict:
        for k in ('quantity', 'rate', 'gst_rate', 'basic_amount', 'tax_amount', 'total_amount'):
            if r.get(k) is not None:
                r[k] = float(r[k])
        for k in (DatabaseManager._ledger(kind)['date_col'], 'created_at', 'updated_at'):
            if r.get(k) is not None and hasattr(r[k], 'isoformat'):
                r[k] = r[k].isoformat()
        return r

    @classmethod
    def _ledger_select(cls, kind: str) -> str:
        spec = cls._ledger(kind)
        return (
            "SELECT id, project_id, description, quantity, unit, rate, gst_rate, "
            f"       basic_amount, tax_amount, total_amount, {spec['date_col']}, "
            "       created_at, updated_at "
            f"FROM {spec['table']}"
        )

    def list_po_ledger(self, project_id: int, kind: str) -> List[Dict]:
        """Every row of one ledger for a project, oldest first (the order added).

        No ensure-table here: both ledgers are created at startup (the
        ensure_projects_table chain), and this read runs twice per
        _po_summary_for_response — i.e. on every committed cell edit in the
        grid — so a CREATE TABLE IF NOT EXISTS round trip on each would double
        that hot path's latency for a table that always already exists. The
        write paths still ensure, so a genuinely cold table self-heals on first
        insert; a read against one simply returns [] via the except below.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    self._ledger_select(kind) + " WHERE project_id = %s ORDER BY id",
                    (project_id,)
                )
                rows = cursor.fetchall()
                cursor.close()
                return [self._ledger_row(kind, r) for r in rows]
        except Exception as e:
            print(f"[!] Error listing PO {kind}s for {project_id}: {e}")
            return []

    def _coerce_ledger_row(self, kind: str, fields: dict) -> Tuple[Optional[Dict], Optional[str]]:
        """Validate + price one ledger payload. Returns (values, error)."""
        spec = self._ledger(kind)
        try:
            quantity = float(fields.get('quantity') or 0)
            rate = float(fields.get('rate') or 0)
        except (ValueError, TypeError):
            return None, 'quantity and rate must be numbers'
        gst_rate = fields.get('gst_rate')
        try:
            gst_rate = PO_LEDGER_GST_RATE if gst_rate in (None, '') else float(gst_rate)
        except (ValueError, TypeError):
            return None, 'gst_rate must be a number'
        # A rate below zero would make a reduction read as an addition (two
        # negatives). Direction is the quantity's job and only the quantity's.
        if rate < 0:
            return None, ('rate must be zero or more — use a negative quantity to reduce scope'
                          if spec['allow_negative_qty'] else 'rate must be zero or more')
        # Actuals are a measurement, not a change: negative tonnage would be
        # nonsense, and it is also how someone reaching for the variations habit
        # would try to express an under-run here. The under-run is already
        # expressed — by the actuals totalling less than the PO.
        if quantity < 0 and not spec['allow_negative_qty']:
            return None, ('quantity must be zero or more — actuals are the work as measured, '
                          'so a project coming in under its PO is simply a smaller total')
        description = str(fields.get('description') or '').strip()
        if not description:
            return None, 'description is required'
        basic, tax, total = compute_ledger_amounts(quantity, rate, gst_rate)
        return {
            'description': description[:500],
            'quantity': quantity,
            'unit': (str(fields.get('unit') or '').strip() or None),
            'rate': rate,
            'gst_rate': gst_rate,
            'basic_amount': basic,
            'tax_amount': tax,
            'total_amount': total,
            'entry_date': self._parse_po_date(
                fields.get(spec['date_col']) or fields.get('entry_date')),
        }, None

    def add_po_ledger_row(self, project_id: int, kind: str,
                          fields: dict) -> Tuple[Optional[Dict], Optional[str]]:
        """Record one ledger row. Returns (row, error)."""
        spec = self._ledger(kind)
        self.ensure_po_ledger_table(kind)
        values, err = self._coerce_ledger_row(kind, fields)
        if err:
            return None, err
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"INSERT INTO {spec['table']} "
                    "(project_id, description, quantity, unit, rate, gst_rate, "
                    f" basic_amount, tax_amount, total_amount, {spec['date_col']}) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (project_id, values['description'], values['quantity'], values['unit'],
                     values['rate'], values['gst_rate'], values['basic_amount'],
                     values['tax_amount'], values['total_amount'], values['entry_date'])
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor.close()
        except Exception as e:
            return None, str(e)
        return self.get_po_ledger_row(kind, new_id), None

    def get_po_ledger_row(self, kind: str, row_id: int) -> Optional[Dict]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(self._ledger_select(kind) + " WHERE id = %s", (row_id,))
                row = cursor.fetchone()
                cursor.close()
                return self._ledger_row(kind, row) if row else None
        except Exception as e:
            print(f"[!] Error fetching PO {kind} {row_id}: {e}")
            return None

    def update_po_ledger_row(self, project_id: int, kind: str, row_id: int,
                             fields: dict) -> Tuple[Optional[Dict], Optional[str]]:
        """Re-price and save one ledger row. Scoped by project_id so a stale
        modal can't reach a row belonging to some other project."""
        spec = self._ledger(kind)
        self.ensure_po_ledger_table(kind)
        existing = self.get_po_ledger_row(kind, row_id)
        if not existing or existing['project_id'] != project_id:
            return None, 'not_found'
        # Merge over the stored row: the grid sends one field at a time, and the
        # amounts have to be re-derived from the *combined* qty/rate, not from
        # whichever half happens to be in this request.
        merged = {**existing, **fields}
        values, err = self._coerce_ledger_row(kind, merged)
        if err:
            return None, err
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE {spec['table']} SET description = %s, quantity = %s, "
                    "unit = %s, rate = %s, gst_rate = %s, basic_amount = %s, "
                    f"tax_amount = %s, total_amount = %s, {spec['date_col']} = %s "
                    "WHERE id = %s AND project_id = %s",
                    (values['description'], values['quantity'], values['unit'], values['rate'],
                     values['gst_rate'], values['basic_amount'], values['tax_amount'],
                     values['total_amount'], values['entry_date'], row_id, project_id)
                )
                conn.commit()
                cursor.close()
        except Exception as e:
            return None, str(e)
        return self.get_po_ledger_row(kind, row_id), None

    def delete_po_ledger_row(self, project_id: int, kind: str,
                             row_id: int) -> Tuple[bool, Optional[str]]:
        spec = self._ledger(kind)
        self.ensure_po_ledger_table(kind)
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM {spec['table']} WHERE id = %s AND project_id = %s",
                    (row_id, project_id)
                )
                deleted = cursor.rowcount
                conn.commit()
                cursor.close()
                # Unlike an UPDATE, a DELETE's rowcount is unambiguous: 0 rows
                # means the row genuinely wasn't there.
                return (True, None) if deleted else (False, 'not_found')
        except Exception as e:
            return False, str(e)

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
        invoice_date = _parse_invoice_date(bill_data.get('invoice_date', ''))

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
                    validation_status = %s,
                    validation_diff = %s,
                    validation_notes = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """

                # Re-validate from the updated numbers so every edit / reprocess
                # refreshes the reconciliation verdict (validate_db_row reads the
                # same flat keys this update writes).
                validation = validate_db_row(bill_data, bill_data.get('line_items', []))

                cursor.execute(update_query, (
                    _fit(bill_data.get('invoice_number', ''), 100),
                    invoice_date,
                    _fit(bill_data.get('irn', ''), 255),
                    _fit(bill_data.get('ack_number', ''), 100),
                    _fit(bill_data.get('eway_bill_number', ''), 100),
                    _fit(bill_data.get('vendor_name', ''), 255),
                    _fit(bill_data.get('vendor_gstin', ''), 20),
                    bill_data.get('vendor_address', ''),
                    _fit(bill_data.get('vendor_state', ''), 100),
                    _fit(bill_data.get('vendor_pan', ''), 20),
                    _fit(bill_data.get('vendor_phone', ''), 50),
                    _fit(bill_data.get('vendor_bank_name', ''), 255),
                    _fit(bill_data.get('vendor_bank_account', ''), 50),
                    _fit(bill_data.get('vendor_bank_ifsc', ''), 20),
                    _fit(bill_data.get('buyer_name', ''), 255),
                    _fit(bill_data.get('buyer_gstin', ''), 20),
                    bill_data.get('buyer_address', ''),
                    _fit(bill_data.get('buyer_state', ''), 100),
                    _fit(bill_data.get('ship_to_name', ''), 255),
                    bill_data.get('ship_to_address', ''),
                    float(bill_data.get('subtotal', 0) or 0),
                    float(bill_data.get('total_cgst', 0) or 0),
                    float(bill_data.get('total_sgst', 0) or 0),
                    float(bill_data.get('total_igst', 0) or 0),
                    float(bill_data.get('other_charges', 0) or 0),
                    float(bill_data.get('round_off', 0) or 0),
                    float(bill_data.get('total_amount', 0) or 0),
                    bill_data.get('amount_in_words', ''),
                    _fit(bill_data.get('vehicle_number', ''), 50),
                    _fit(bill_data.get('transporter_name', ''), 255),
                    bill_data.get('project', '') or None,
                    validation['status'],
                    validation['diff'],
                    notes_from_result(validation),
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
                                _fit(item.get('hsn_sac_code', ''), 20),
                                float(item.get('quantity', 0) or 0),
                                _fit(item.get('uom', ''), 20),
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
