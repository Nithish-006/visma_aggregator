"""
Robust Bank Statement Processor for Financial App
Handles Axis Bank and KVB statements with flexible column detection, date parsing, and categorization
"""

import re
import io
import pandas as pd
from datetime import datetime
from difflib import get_close_matches
from typing import Optional, Tuple, Dict, List

# Try to import msoffcrypto for encrypted file support
try:
    import msoffcrypto
    HAS_MSOFFCRYPTO = True
except ImportError:
    HAS_MSOFFCRYPTO = False


# ============================================================================
# CONFIGURATION: Define Categories and their Codes
# ============================================================================

CATEGORIES = {
    "OFFICE EXPENSES": "OE",
    "FACTORY EXPENSES": "FE",
    "AMOUNT RECEIVED": "AR",
    "SITE EXPENSES": "SE",
    "TRANSPORT EXPENSES": "TE",
    "MATERIAL PURCHASE": "MP",
    "DUTIES & TAX": "DT",
    "SALARY AC": "SA",
    "BANK CHARGES": "BC"
}

# Category detection patterns (keywords to look for in transaction descriptions)
CATEGORY_PATTERNS = {
    "OFFICE EXPENSES": [
        "office", "stationery", "printer", "paper", "pen", "supplies",
        "furniture", "computer", "laptop", "software", "internet", "phone",
        "mobile", "postage", "courier", "xerox", "photocopy"
    ],
    "FACTORY EXPENSES": [
        "factory", "machinery", "equipment", "maintenance", "repair",
        "spare parts", "tools", "workshop", "industrial"
    ],
    "SITE EXPENSES": [
        "site", "construction", "building", "cement", "sand", "labour",
        "labor", "worker", "contractor", "excavation", "painting"
    ],
    "TRANSPORT EXPENSES": [
        "transport", "truck", "vehicle", "fuel", "diesel", "petrol",
        "filling station", "driver", "logistics", "freight", "cargo",
        "weighment", "weigh", "toll", "lpg"
    ],
    "MATERIAL PURCHASE": [
        "material", "purchase", "supplier", "vendor", "buy", "procurement",
        "steel", "iron", "metal", "wood", "timber", "hardware", "stickers"
    ],
    "DUTIES & TAX": [
        "tax", "gst", "tds", "duty", "cess", "vat", "income tax",
        "professional tax", "govt", "government"
    ],
    "SALARY AC": [
        "salary", "wages", "payroll", "employee", "staff", "payment to",
        "pay to", "advance", "bonus", "incentive"
    ],
    "BANK CHARGES": [
        "bank charges", "service charge", "sms charges", "atm", "debit card",
        "annual fee", "processing fee", "interest", "penalty"
    ],
    "AMOUNT RECEIVED": [
        "received", "deposit", "credit", "transfer in", "imps/p2a",
        "neft in", "rtgs in", "collection"
    ]
}


# ============================================================================
# HELPER FUNCTIONS: Column Detection & Normalization
# ============================================================================

def _normalize_name(name: str) -> str:
    """
    Normalize a column name for fuzzy matching:
    - lowercase
    - remove spaces and common separators
    - remove punctuation
    """
    if not isinstance(name, str):
        name = str(name)
    name = name.lower()
    # Replace separators with space then strip punctuation/whitespace
    name = re.sub(r"[|/,_\-()]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Drop all non-alphanumeric characters
    name = re.sub(r"[^0-9a-z]+", "", name)
    return name


def find_best_column(df: pd.DataFrame, logical_name: str, candidates: List[str] = None, required: bool = True) -> Optional[str]:
    """
    Map a logical column (e.g. 'amount', 'drcr') to the best matching
    column in df using normalization and fuzzy matching.

    Args:
        df: DataFrame to search
        logical_name: Label for error messages
        candidates: List of expected raw column names
        required: Whether to raise error if not found

    Returns:
        Actual column name from DataFrame, or None if not found and not required
    """
    if candidates is None:
        candidates = []

    # Build normalized lookup for actual columns
    col_map = {col: _normalize_name(col) for col in df.columns}

    # 1) Direct normalized match against candidate names
    normalized_candidates = [_normalize_name(c) for c in candidates]

    for col, norm_col in col_map.items():
        if norm_col in normalized_candidates:
            return col

    # 2) Substring / heuristic match
    logical_patterns = {
        "amount": ["amount", "amt", "inr"],
        "drcr": ["drcr", "dr", "cr", "debitcredit", "debit/credit", "debit credit"],
        "date": ["trandate", "date", "transactiondate", "txndate", "valuedate"],
        "particulars": ["particulars", "description", "details", "narration"],
        "balance": ["balance", "bal"],
        "cheque": ["cheque", "chq", "chqno", "chequenumber"],
        "serial": ["srl", "srno", "sno", "serialno", "serial"],
    }

    patterns = logical_patterns.get(logical_name.lower(), [])
    for col, norm_col in col_map.items():
        if any(p in norm_col for p in patterns):
            return col

    # 3) Fuzzy match
    all_norms = list(col_map.values())
    target_pool = normalized_candidates or patterns or [logical_name.lower()]
    for target in target_pool:
        matches = get_close_matches(target, all_norms, n=1, cutoff=0.6)
        if matches:
            for col, norm_col in col_map.items():
                if norm_col == matches[0]:
                    return col

    if required:
        raise KeyError(
            f"Could not find a column for logical field '{logical_name}'. "
            f"Expected something like: {candidates or patterns}. "
            f"Available columns: {list(df.columns)}"
        )
    return None


# ============================================================================
# DATE PARSING: Handle both / and - separators
# ============================================================================

def parse_date_robust(date_value) -> Optional[pd.Timestamp]:
    """
    Parse date with multiple format attempts, handling / and - separators

    Args:
        date_value: Date string or pandas datetime

    Returns:
        Pandas Timestamp or None if parsing fails
    """
    if pd.isna(date_value):
        return pd.NaT

    # Already a datetime
    if isinstance(date_value, (pd.Timestamp, datetime)):
        return pd.Timestamp(date_value)

    date_str = str(date_value).strip()

    # Common formats with both / and - separators
    formats = [
        '%d-%m-%Y',    # 01-07-2025
        '%d/%m/%Y',    # 01/07/2025
        '%d-%m-%y',    # 01-07-25
        '%d/%m/%y',    # 01/07/25
        '%Y-%m-%d',    # 2025-07-01
        '%Y/%m/%d',    # 2025/07/01
        '%d %b %Y',    # 01 Jul 2025
        '%d %B %Y',    # 01 July 2025
    ]

    for fmt in formats:
        try:
            return pd.to_datetime(date_str, format=fmt)
        except:
            continue

    # Fallback: Let pandas infer with dayfirst=True (Indian format)
    try:
        return pd.to_datetime(date_str, dayfirst=True)
    except:
        return pd.NaT


# ============================================================================
# MONETARY VALUE PARSING
# ============================================================================

def parse_amount_robust(amount_value) -> float:
    """
    Parse monetary value, handling commas, spaces, and converting to float

    Args:
        amount_value: Amount string or number

    Returns:
        Float value or 0.0 if parsing fails
    """
    if pd.isna(amount_value):
        return 0.0

    # Already a number
    if isinstance(amount_value, (int, float)):
        return float(amount_value)

    # String processing
    amount_str = str(amount_value).strip()

    # Remove common formatting characters
    amount_str = amount_str.replace(',', '')  # Remove commas
    amount_str = amount_str.replace(' ', '')  # Remove spaces
    amount_str = amount_str.replace('₹', '')  # Remove rupee symbol
    amount_str = amount_str.replace('INR', '')  # Remove INR

    # Handle empty or 'nan' strings
    if amount_str in ['', 'nan', 'NaN', 'None']:
        return 0.0

    try:
        return float(amount_str)
    except ValueError:
        return 0.0


# ============================================================================
# CATEGORIZATION LOGIC
# ============================================================================

def categorize_transaction(particulars: str, dr_cr_indicator: str, vendor: Optional[str] = None) -> Tuple[str, str]:
    """
    Categorize a transaction based on its description, debit/credit indicator, and vendor

    Args:
        particulars: Transaction description
        dr_cr_indicator: 'DR' or 'CR'
        vendor: Vendor/client name (optional)

    Returns:
        Tuple of (category_name, category_code)
    """
    # All credits are AMOUNT RECEIVED
    if dr_cr_indicator and str(dr_cr_indicator).strip().upper() in ['CR', 'CREDIT', 'C']:
        return "AMOUNT RECEIVED", "AR"

    # For debits, analyze the description
    if not particulars or not isinstance(particulars, str):
        return "UNCATEGORIZED", "UC"

    particulars_lower = particulars.lower()

    # Score each category based on keyword matches
    category_scores = {}
    for category, keywords in CATEGORY_PATTERNS.items():
        if category == "AMOUNT RECEIVED":  # Skip this for debit transactions
            continue

        score = 0
        for keyword in keywords:
            if keyword in particulars_lower:
                # Longer keywords get higher weight
                score += len(keyword)

        if score > 0:
            category_scores[category] = score

    # If vendor name is provided, check it too
    if vendor and isinstance(vendor, str):
        vendor_lower = vendor.lower()
        for category, keywords in CATEGORY_PATTERNS.items():
            if category == "AMOUNT RECEIVED":
                continue
            for keyword in keywords:
                if keyword in vendor_lower:
                    category_scores[category] = category_scores.get(category, 0) + len(keyword)

    # Return category with highest score
    if category_scores:
        best_category = max(category_scores, key=category_scores.get)
        return best_category, CATEGORIES[best_category]

    # Default for unmatched debits
    return "UNCATEGORIZED", "UC"


def extract_vendor_from_particulars(particulars: str, bank_code: str = 'axis') -> Optional[str]:
    """
    Extract vendor/client name from transaction particulars
    Handles UPI, IMPS, NEFT patterns common in bank statements

    Args:
        particulars: Transaction description
        bank_code: Bank code ('axis' or 'kvb') for bank-specific patterns

    Returns:
        Vendor name or None
    """
    if not particulars or not isinstance(particulars, str):
        return None

    particulars = particulars.strip()

    # KVB-specific patterns (different format from Axis)
    if bank_code == 'kvb':
        # KVB IMPS: IMPS-509113479708-VISMAASSOCIATES-UTIB-xxxxxxxxxxx
        kvb_imps = re.search(r'IMPS-\d+-([A-Za-z\s]+)-[A-Z]{4}-', particulars)
        if kvb_imps:
            return kvb_imps.group(1).strip()

        # KVB NEFT CR: NEFT CR-CNRB0000967-SV CONSTRUCTIONS-VISMA ASSOCIA
        kvb_neft_cr = re.search(r'NEFT CR-[A-Z0-9]+-([^-]+)-', particulars)
        if kvb_neft_cr:
            return kvb_neft_cr.group(1).strip()

        # KVB NEFT DR: NEFT DR-KVBLH00232446439-VISMAASSOCIATES-UTIB00004
        kvb_neft_dr = re.search(r'NEFT DR-[A-Z0-9]+-([^-]+)-', particulars)
        if kvb_neft_dr:
            return kvb_neft_dr.group(1).strip()

        # KVB UPI-CR: UPI-CR-102477049440-SRIRAM R-HDFC-50100004440849-U
        kvb_upi = re.search(r'UPI-(?:CR|DR)-\d+-([^-]+)-[A-Z]{4}-', particulars)
        if kvb_upi:
            return kvb_upi.group(1).strip()

        # CASH DEP: CASH DEP-SELF-SEETHALAKSHMI-CBE-RAMANATH
        cash_dep = re.search(r'CASH DEP-[^-]+-([^-]+)-', particulars)
        if cash_dep:
            return cash_dep.group(1).strip()

        # ECS/NACH: To Clg:ECS BD-TATA MF - NACH
        ecs_match = re.search(r'ECS (?:BD|TP ACH)\s*-?\s*([^-]+)\s*-?\s*NACH', particulars, re.IGNORECASE)
        if ecs_match:
            return ecs_match.group(1).strip()

        # MB-WITHIN (internal transfers): MB-WITHIN-DR:XXXX4008-CR:XXXX0334-...
        if 'MB-WITHIN' in particulars:
            return 'Internal Transfer'

        # Fallback: Extract name from hyphen-separated parts
        parts = [p.strip() for p in particulars.split('-') if p.strip()]
        if len(parts) >= 3:
            # Skip transaction type and ID, look for name
            for part in parts[2:]:
                # Skip account numbers, codes, and numeric parts
                if part and not part.isdigit() and len(part) > 2:
                    if not re.match(r'^[A-Z]{4}\d*$', part) and not re.match(r'^x+\d*$', part, re.IGNORECASE):
                        return part
        return None

    # Axis Bank patterns (original logic)
    # UPI patterns: UPI/P2M/xxx/VENDOR NAME/...
    upi_match = re.search(r'UPI/P2[AM]/\d+/([^/]+)', particulars)
    if upi_match:
        vendor = upi_match.group(1).strip()
        # Clean up common suffixes
        vendor = re.sub(r'\s+(UPI|MERCHANT|PAY TO|PAYMENT).*$', '', vendor, flags=re.IGNORECASE)
        return vendor

    # IMPS patterns: IMPS/P2A/xxx/VENDOR/...
    imps_match = re.search(r'IMPS/P2A/\d+/([^/]+)', particulars)
    if imps_match:
        vendor = imps_match.group(1).strip()
        return vendor

    # NEFT/RTGS patterns
    neft_match = re.search(r'(?:NEFT|RTGS)[^/]*/([^/]+)', particulars)
    if neft_match:
        vendor = neft_match.group(1).strip()
        return vendor

    # Fallback: Take first meaningful part before /
    parts = [p.strip() for p in particulars.split('/') if p.strip()]
    if len(parts) >= 2:
        # Skip transaction type (UPI, IMPS, etc) and ID, get the vendor
        for part in parts[2:]:
            if part and not part.isdigit() and len(part) > 3:
                return part

    return None


# ============================================================================
# ENCRYPTED FILE HANDLING
# ============================================================================

def decrypt_excel_file(file_path: str, password: str = None) -> io.BytesIO:
    """
    Decrypt a password-protected Excel file

    Args:
        file_path: Path to the encrypted Excel file
        password: Password for decryption (optional, will try common passwords)

    Returns:
        BytesIO object containing decrypted file data

    Raises:
        ValueError: If file cannot be decrypted
    """
    if not HAS_MSOFFCRYPTO:
        raise ImportError("msoffcrypto-tool is required for encrypted files. Install with: pip install msoffcrypto-tool")

    with open(file_path, 'rb') as f:
        office_file = msoffcrypto.OfficeFile(f)

        if not office_file.is_encrypted():
            # File is not encrypted, return as-is
            f.seek(0)
            return io.BytesIO(f.read())

        # Try provided password first
        passwords_to_try = []
        if password:
            passwords_to_try.append(password)

        for pwd in passwords_to_try:
            try:
                office_file.load_key(password=pwd)
                decrypted = io.BytesIO()
                office_file.decrypt(decrypted)
                decrypted.seek(0)
                return decrypted
            except Exception:
                continue

        raise ValueError("Could not decrypt file. Please provide the correct password.")


def is_file_encrypted(file_path: str) -> bool:
    """Check if an Excel file is encrypted"""
    if not HAS_MSOFFCRYPTO:
        return False

    try:
        with open(file_path, 'rb') as f:
            office_file = msoffcrypto.OfficeFile(f)
            return office_file.is_encrypted()
    except Exception:
        return False


# ============================================================================
# MAIN PROCESSING FUNCTION
# ============================================================================

def safe_print(text: str):
    """Print text with fallback for Unicode errors"""
    try:
        print(text)
    except UnicodeEncodeError:
        # Fallback: remove non-ASCII characters
        print(text.encode('ascii', 'ignore').decode('ascii'))


def detect_header_row(file_path: str, bank_code: str = 'axis', file_data: io.BytesIO = None) -> int:
    """
    Detect which row contains the column headers in the Excel file

    Args:
        file_path: Path to Excel file
        bank_code: Bank code ('axis' or 'kvb')
        file_data: Optional BytesIO for already-read/decrypted file

    Returns:
        Row number (0-indexed) where headers are found
    """
    # Read first 30 rows without headers
    if file_data:
        file_data.seek(0)
        df_sample = pd.read_excel(file_data, header=None, nrows=30, engine='openpyxl')
        file_data.seek(0)
    else:
        df_sample = pd.read_excel(file_path, header=None, nrows=30)

    # Bank-specific header keywords
    if bank_code == 'kvb':
        # KVB headers: Transaction Date, Value Date, Particulars, Ref.No., Debit, Credit
        header_keywords = ['transaction date', 'value date', 'particulars', 'debit', 'credit']
        min_matches = 3  # Need at least 3 keywords to confirm header
    else:
        # Axis headers: Tran Date, Particulars, Amount(INR), DR/CR, Balance
        header_keywords = ['tran date', 'transaction date', 'particulars', 'amount', 'dr/cr', 'debit/credit']
        min_matches = 2

    for idx, row in df_sample.iterrows():
        row_text = ' '.join([str(x).lower() for x in row.values if not pd.isna(x)])
        matches = sum(1 for keyword in header_keywords if keyword in row_text)
        if matches >= min_matches:
            return idx

    # Bank-specific defaults
    if bank_code == 'kvb':
        return 0  # KVB typically has header at row 0
    return 19  # Axis default


def process_bank_statement(
    file_path: str,
    bank_code: str = 'axis',
    auto_detect_header: bool = True,
    header_row: Optional[int] = None,
    password: Optional[str] = None,
    opening_balance: Optional[float] = None
) -> pd.DataFrame:
    """
    Process a bank statement Excel file into standardized format

    Args:
        file_path: Path to Excel file
        bank_code: Bank code ('axis', 'kvb') - determines processing logic
        auto_detect_header: Whether to automatically detect header row
        header_row: Manual header row number (0-indexed) if auto_detect is False
        password: Password for encrypted Excel files (KVB files are often encrypted)
        opening_balance: Opening balance for KVB (since KVB doesn't provide running balance)

    Returns:
        Processed DataFrame with standardized columns
    """
    safe_print(f"[*] Processing {bank_code.upper()} bank statement...")

    # Step 0: Handle encrypted files
    file_data = None
    if is_file_encrypted(file_path):
        safe_print("[*] File is encrypted, attempting decryption...")
        if not password:
            raise ValueError("File is encrypted. Please provide a password.")
        file_data = decrypt_excel_file(file_path, password)
        safe_print("[+] File decrypted successfully")

    # Route to bank-specific processor
    if bank_code == 'kvb':
        return _process_kvb_statement(file_path, file_data, auto_detect_header, header_row, opening_balance)
    else:
        return _process_axis_statement(file_path, file_data, auto_detect_header, header_row)


def _process_axis_statement(
    file_path: str,
    file_data: io.BytesIO = None,
    auto_detect_header: bool = True,
    header_row: Optional[int] = None
) -> pd.DataFrame:
    """Process Axis Bank statement"""
    safe_print("[*] Using Axis Bank processing logic...")

    # Step 1: Detect or use provided header row
    if auto_detect_header:
        skip_rows = detect_header_row(file_path, 'axis', file_data)
        safe_print(f"[*] Detected header at row {skip_rows}")
    else:
        skip_rows = header_row if header_row is not None else 19

    # Step 2: Read Excel file
    safe_print(f"[*] Reading Excel file: {file_path}")
    if file_data:
        file_data.seek(0)
        df = pd.read_excel(file_data, skiprows=skip_rows, engine='openpyxl')
    else:
        df = pd.read_excel(file_path, skiprows=skip_rows)
    safe_print(f"[+] Loaded {len(df)} rows")

    # Step 3: Detect columns robustly
    safe_print("[*] Detecting columns...")

    date_col = find_best_column(
        df,
        logical_name="date",
        candidates=["Tran Date", "Transaction Date", "Date", "Txn Date"],
        required=True
    )
    safe_print(f"  [+] Date column: {date_col}")

    particulars_col = find_best_column(
        df,
        logical_name="particulars",
        candidates=["PARTICULARS", "Particulars", "Description", "Transaction Particulars"],
        required=True
    )
    safe_print(f"  [+] Particulars column: {particulars_col}")

    amount_col = find_best_column(
        df,
        logical_name="amount",
        candidates=["Amount(INR)", "Amount", "AMOUNT(INR)"],
        required=True
    )
    safe_print(f"  [+] Amount column: {amount_col}")

    drcr_col = find_best_column(
        df,
        logical_name="drcr",
        candidates=["DR/CR", "DR|CR", "Debit/Credit", "Debit Credit"],
        required=True
    )
    safe_print(f"  [+] DR/CR column: {drcr_col}")

    # Balance column - REQUIRED for accurate financial tracking
    balance_col = find_best_column(
        df,
        logical_name="balance",
        candidates=["Balance(INR)", "Balance"],
        required=True
    )
    safe_print(f"  [+] Balance column: {balance_col}")

    # Step 4: Process each transaction
    safe_print("[*] Processing transactions...")
    records = []

    for idx, row in df.iterrows():
        # Skip opening balance and closing balance rows
        particulars_text = str(row[particulars_col]).strip() if pd.notna(row[particulars_col]) else ""
        if "OPENING BALANCE" in particulars_text.upper() or "CLOSING BALANCE" in particulars_text.upper():
            continue

        # Parse date
        date_value = parse_date_robust(row[date_col])
        if pd.isna(date_value):
            continue  # Skip rows without valid dates

        # Parse amount
        amount = parse_amount_robust(row[amount_col])
        if amount == 0:
            continue  # Skip zero amount transactions

        # Get DR/CR indicator
        dr_cr = str(row[drcr_col]).strip().upper() if pd.notna(row[drcr_col]) else ""

        # Extract vendor
        vendor = extract_vendor_from_particulars(particulars_text, 'axis')

        # Categorize transaction
        category, code = categorize_transaction(particulars_text, dr_cr, vendor)

        # Determine DR and CR amounts
        dr_amount = amount if dr_cr in ['DR', 'DEBIT', 'D'] else 0.0
        cr_amount = amount if dr_cr in ['CR', 'CREDIT', 'C'] else 0.0

        # Get running balance from bank statement - this is the source of truth
        running_balance = parse_amount_robust(row[balance_col])

        records.append({
            'Date': date_value,
            'Transaction Description': particulars_text,
            'Client/Vendor': vendor if vendor else 'Unknown',
            'Category': category,
            'Broader Category': category,
            'Code': code,
            'DR Amount': dr_amount,
            'CR Amount': cr_amount,
            'Running Balance': running_balance,
            'Project': None,
            'DD': None,
            'Notes': None
        })

    # Step 5: Create final DataFrame
    final_df = pd.DataFrame(records)

    # Sort by date
    final_df = final_df.sort_values('Date').reset_index(drop=True)

    # Add Net column for reference (CR - DR), but Running Balance comes from bank
    final_df['Net'] = final_df['CR Amount'] - final_df['DR Amount']

    # Verify data integrity
    if len(final_df) > 1:
        balance_changes = final_df['Running Balance'].diff()
        mismatches = abs(balance_changes - final_df['Net']).fillna(0) > 0.01
        if mismatches.any():
            safe_print(f"\n[!] Warning: {mismatches.sum()} transactions have balance discrepancies")

    _print_summary(final_df)
    return final_df


def _process_kvb_statement(
    file_path: str,
    file_data: io.BytesIO = None,
    auto_detect_header: bool = True,
    header_row: Optional[int] = None,
    opening_balance: Optional[float] = None
) -> pd.DataFrame:
    """
    Process KVB (Karur Vysya Bank) statement

    KVB Format:
    - Columns: Transaction Date, Value Date, Particulars, Ref.No., Debit, Credit
    - No Balance column (calculated from transactions)
    - Date format: DD-MMM-YYYY or DD-MMM-YYYY HH:MM:SS
    - Amounts: Indian format with lakhs separator (1,00,000.00)
    - B/F row indicates brought forward balance
    """
    safe_print("[*] Using KVB Bank processing logic...")

    # Step 1: Detect header row
    if auto_detect_header:
        skip_rows = detect_header_row(file_path, 'kvb', file_data)
        safe_print(f"[*] Detected header at row {skip_rows}")
    else:
        skip_rows = header_row if header_row is not None else 0

    # Step 2: Read Excel file
    safe_print(f"[*] Reading Excel file: {file_path}")
    if file_data:
        file_data.seek(0)
        df = pd.read_excel(file_data, skiprows=skip_rows, engine='openpyxl')
    else:
        df = pd.read_excel(file_path, skiprows=skip_rows)

    # Clean column names (remove 'Unnamed:' prefixes if present)
    if any('Unnamed' in str(col) for col in df.columns):
        # First row is likely the actual header
        df.columns = df.iloc[0].values
        df = df.iloc[1:].reset_index(drop=True)

    safe_print(f"[+] Loaded {len(df)} rows")
    safe_print(f"[*] Columns found: {list(df.columns)}")

    # Step 3: Detect columns robustly
    safe_print("[*] Detecting columns...")

    date_col = find_best_column(
        df,
        logical_name="date",
        candidates=["Transaction Date", "Tran Date", "Date", "Txn Date"],
        required=True
    )
    safe_print(f"  [+] Date column: {date_col}")

    particulars_col = find_best_column(
        df,
        logical_name="particulars",
        candidates=["Particulars", "PARTICULARS", "Description", "Narration"],
        required=True
    )
    safe_print(f"  [+] Particulars column: {particulars_col}")

    # KVB has separate Debit and Credit columns instead of Amount + DR/CR
    debit_col = find_best_column(
        df,
        logical_name="debit",
        candidates=["Debit", "DEBIT", "Dr", "DR"],
        required=True
    )
    safe_print(f"  [+] Debit column: {debit_col}")

    credit_col = find_best_column(
        df,
        logical_name="credit",
        candidates=["Credit", "CREDIT", "Cr", "CR"],
        required=True
    )
    safe_print(f"  [+] Credit column: {credit_col}")

    # Step 4: Find opening balance from B/F row
    bf_balance = opening_balance or 0.0
    bf_row_idx = None

    for idx, row in df.iterrows():
        particulars_text = str(row[particulars_col]).strip() if pd.notna(row[particulars_col]) else ""
        if 'B/F' in particulars_text.upper() or 'BROUGHT FORWARD' in particulars_text.upper():
            bf_row_idx = idx
            safe_print(f"[*] Found B/F (Brought Forward) row at index {idx}")
            break

    if bf_balance == 0.0 and opening_balance is None:
        safe_print("[!] Warning: No opening balance found. Running balance will start from 0.")
        safe_print("    Consider providing opening_balance parameter for accurate balance tracking.")

    # Step 5: Process each transaction
    safe_print("[*] Processing transactions...")
    records = []
    running_balance = bf_balance

    for idx, row in df.iterrows():
        # Skip B/F row
        if idx == bf_row_idx:
            continue

        particulars_text = str(row[particulars_col]).strip() if pd.notna(row[particulars_col]) else ""

        # Skip empty rows and balance rows
        if not particulars_text or 'CLOSING BALANCE' in particulars_text.upper():
            continue

        # Parse date (KVB format: DD-MMM-YYYY or DD-MMM-YYYY HH:MM:SS)
        date_value = parse_date_robust(row[date_col])
        if pd.isna(date_value):
            continue

        # Parse debit and credit amounts separately
        dr_amount = parse_amount_robust(row[debit_col])
        cr_amount = parse_amount_robust(row[credit_col])

        # Skip rows with no transaction (both debit and credit are 0)
        if dr_amount == 0 and cr_amount == 0:
            continue

        # Calculate running balance
        running_balance = running_balance - dr_amount + cr_amount

        # Determine DR/CR indicator for categorization
        dr_cr = 'DR' if dr_amount > 0 else 'CR'

        # Extract vendor using KVB patterns
        vendor = extract_vendor_from_particulars(particulars_text, 'kvb')

        # Categorize transaction
        category, code = categorize_transaction(particulars_text, dr_cr, vendor)

        records.append({
            'Date': date_value,
            'Transaction Description': particulars_text,
            'Client/Vendor': vendor if vendor else 'Unknown',
            'Category': category,
            'Broader Category': category,
            'Code': code,
            'DR Amount': dr_amount,
            'CR Amount': cr_amount,
            'Running Balance': running_balance,
            'Project': None,
            'DD': None,
            'Notes': None
        })

    # Step 6: Create final DataFrame
    final_df = pd.DataFrame(records)

    if len(final_df) == 0:
        safe_print("[!] Warning: No transactions found in the statement")
        return final_df

    # Sort by date
    final_df = final_df.sort_values('Date').reset_index(drop=True)

    # Recalculate running balance after sorting
    running_balance = bf_balance
    for idx in final_df.index:
        running_balance = running_balance - final_df.loc[idx, 'DR Amount'] + final_df.loc[idx, 'CR Amount']
        final_df.loc[idx, 'Running Balance'] = running_balance

    # Add Net column
    final_df['Net'] = final_df['CR Amount'] - final_df['DR Amount']

    _print_summary(final_df, bf_balance)
    return final_df


def _print_summary(final_df: pd.DataFrame, opening_balance: float = None):
    """Print processing summary"""
    safe_print(f"[+] Processing complete! {len(final_df)} transactions processed")
    safe_print(f"\n[*] Summary:")
    safe_print(f"  * Total Credits: Rs.{final_df['CR Amount'].sum():,.2f}")
    safe_print(f"  * Total Debits: Rs.{final_df['DR Amount'].sum():,.2f}")
    safe_print(f"  * Net: Rs.{(final_df['CR Amount'].sum() - final_df['DR Amount'].sum()):,.2f}")

    if len(final_df) > 0:
        if opening_balance is not None:
            safe_print(f"  * Opening Balance: Rs.{opening_balance:,.2f}")
        closing_balance = final_df.iloc[-1]['Running Balance']
        safe_print(f"  * Closing Balance: Rs.{closing_balance:,.2f}")

    safe_print(f"\n[*] Categories breakdown:")
    if len(final_df[final_df['DR Amount'] > 0]) > 0:
        category_summary = final_df[final_df['DR Amount'] > 0].groupby('Category')['DR Amount'].sum().sort_values(ascending=False)
        for cat, amt in category_summary.items():
            safe_print(f"  * {cat}: Rs.{amt:,.2f}")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def process_and_save(input_file: str, output_file: str) -> pd.DataFrame:
    """
    Process a bank statement and save to Excel

    Args:
        input_file: Input Excel file path
        output_file: Output Excel file path

    Returns:
        Processed DataFrame
    """
    df = process_bank_statement(input_file)
    df.to_excel(output_file, index=False)
    safe_print(f"\n[+] Saved to: {output_file}")
    return df


def get_category_list() -> List[str]:
    """Get list of all available categories"""
    return list(CATEGORIES.keys())


def get_category_code(category: str) -> str:
    """Get code for a specific category"""
    return CATEGORIES.get(category, "UC")


# ============================================================================
# MAIN - For testing
# ============================================================================

if __name__ == "__main__":
    import sys

    safe_print("=" * 80)
    safe_print("BANK STATEMENT PROCESSOR")
    safe_print("=" * 80)
    safe_print("")

    # Test with provided files
    test_files = [
        "Axis Bank 01.07.25 to 31.07.25.XLSX",
        "AXIS BANK 01-08-2025 TO 31.08.25.XLSX"
    ]

    for test_file in test_files:
        try:
            safe_print(f"\n{'='*80}")
            safe_print(f"Processing: {test_file}")
            safe_print(f"{'='*80}\n")

            output_file = test_file.replace('.XLSX', '_PROCESSED.xlsx').replace('.xlsx', '_PROCESSED.xlsx')
            df = process_and_save(test_file, output_file)

        except FileNotFoundError:
            safe_print(f"[!] File not found: {test_file}")
        except Exception as e:
            safe_print(f"[!] Error processing {test_file}: {str(e)}")
            import traceback
            traceback.print_exc()
