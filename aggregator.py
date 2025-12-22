import re
import pandas as pd
from difflib import get_close_matches


# -----------------------------
# 0. Helpers for robust schema & text mapping
# -----------------------------
def _normalise_name(name: str) -> str:
    """
    Normalise a column name for fuzzy matching:
    - lower case
    - remove spaces and common separators
    - remove punctuation
    """
    if not isinstance(name, str):
        name = str(name)
    name = name.lower()
    # Replace some separators with space then strip punctuation/whitespace
    name = re.sub(r"[|/,_\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    # Drop all non-alphanumeric characters
    name = re.sub(r"[^0-9a-z]+", "", name)
    return name


def _normalise_label(label: str | None) -> str:
    """
    Normalise a generic label (category/vendor) for comparison.
    Uses the same rules as _normalise_name but is semantically separate
    so we can tweak behaviour later if needed.
    """
    if label is None:
        return ""
    return _normalise_name(str(label))


def find_best_column(df: pd.DataFrame, logical_name: str, candidates=None, required=True) -> str | None:
    """
    Map a logical column (e.g. 'amount', 'drcr') to the best matching
    column in df using normalisation and fuzzy matching.

    - logical_name: a label only for error messages
    - candidates: list of *expected* raw names / patterns
    """
    if candidates is None:
        candidates = []

    # Build normalised lookup for actual columns
    col_map = {col: _normalise_name(col) for col in df.columns}

    # 1) Direct normalised match against candidate names
    normalised_candidates = [_normalise_name(c) for c in candidates]

    # Try exact normalised match
    for col, norm_col in col_map.items():
        if norm_col in normalised_candidates:
            return col

    # 2) Substring / heuristic match
    # Some generic patterns per logical type
    logical_patterns = {
        "amount": ["amount", "amt", "inr", "debit", "credit"],
        "drcr": ["drcr", "dr", "cr", "debitcredit", "debit/credit"],
        "date": ["trandate", "date", "transactiondate", "txndate", "valuedate"],
        "particulars": ["particulars", "description", "details", "narration"],
        "vendor": ["vendor", "client", "party", "name", "customer", "supplier"],
        "code": ["code", "categorycode", "catcode"],
    }

    patterns = logical_patterns.get(logical_name.lower(), [])
    for col, norm_col in col_map.items():
        if any(p in norm_col for p in patterns):
            return col

    # 3) Fuzzy match against candidate list and all columns
    all_norms = list(col_map.values())
    target_pool = normalised_candidates or patterns or [logical_name.lower()]
    for target in target_pool:
        matches = get_close_matches(target, all_norms, n=1, cutoff=0.6)
        if matches:
            # Find original column name for this normalised value
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


# -----------------------------
# 1. Load files
# -----------------------------
bank_df = pd.read_excel(r"4. APRIL\APRIL -25-26  BANK STATEMENT.xlsx")

expenses_xls = pd.ExcelFile(r"EXPENSES - NOV  25-26.xlsx")

# Read all sheets to collect categories, codes and known vendors
expense_categories: set[str] = set()
known_vendors: set[str] = set()
# Map from normalised vendor name -> a "best" category (from expenses file)
vendor_category_map: dict[str, str] = {}
# Map from normalised category name -> explicit code from expenses file (if available)
category_code_raw_map: dict[str, str] = {}

for sheet in expenses_xls.sheet_names:
    df = pd.read_excel(expenses_xls, sheet_name=sheet)

    # Categories
    if "Category" in df.columns:
        df_cat = df["Category"].dropna().astype(str).str.strip()
        expense_categories.update(df_cat.unique())

        # If there is a code column in this sheet, capture explicit codes
        try:
            code_col = find_best_column(
                df,
                logical_name="code",
                candidates=[
                    "Code",
                    "Category Code",
                    "Category_Code",
                    "CATEGORY CODE",
                ],
                required=False,
            )
        except KeyError:
            code_col = None

        if code_col:
            for _, r in df[["Category", code_col]].dropna(subset=["Category"]).iterrows():
                cat_val = str(r["Category"]).strip()
                code_val = str(r[code_col]).strip()
                if not cat_val or not code_val:
                    continue
                c_norm = _normalise_label(cat_val)
                # Prefer first seen explicit mapping
                if c_norm not in category_code_raw_map:
                    category_code_raw_map[c_norm] = code_val

    # Try to infer vendor / client column (optional)
    try:
        vendor_col = find_best_column(
            df,
            logical_name="vendor",
            candidates=[
                "Vendor",
                "Client/Vendor",
                "Client",
                "Party",
                "Name",
            ],
            required=False,
        )
    except KeyError:
        vendor_col = None

    if vendor_col and "Category" in df.columns:
        for _, r in df[[vendor_col, "Category"]].dropna(subset=[vendor_col]).iterrows():
            v = str(r[vendor_col]).strip()
            c = str(r["Category"]).strip()
            if not v or not c:
                continue
            v_norm = _normalise_label(v)
            known_vendors.add(v)
            # Simple mapping: prefer first non-empty, otherwise overwrite
            if v_norm not in vendor_category_map:
                vendor_category_map[v_norm] = c

# Build a canonical category lookup: normalised -> canonical label
canonical_category_map: dict[str, str] = {}
for cat in expense_categories:
    key = _normalise_label(cat)
    if key and key not in canonical_category_map:
        canonical_category_map[key] = str(cat).strip()

# Then build the public mapping from Broader Category (UPPERCASE canonical label) to code.
category_code_map: dict[str, str] = {}

if category_code_raw_map:
    # Use explicit codes from the expenses workbook wherever available.
    for norm_key, canonical_label in canonical_category_map.items():
        code = category_code_raw_map.get(norm_key)
        if code:
            category_code_map[canonical_label.upper()] = str(code).strip()
else:
    # Fallback: synthetic codes if the expenses sheets don't define any
    for i, category in enumerate(sorted(expense_categories)):
        label = str(category).strip().upper()
        category_code_map[label] = f"C{str(i+1).zfill(3)}"

# -----------------------------
# 3. Resolve bank statement schema robustly
# -----------------------------
amount_col = find_best_column(
    bank_df,
    logical_name="amount",
    candidates=[
        "Amount(INR)",
        "Amount (INR)",
        "Amount",
        "AMOUNT(INR)",
        "AMOUNT",
    ],
)

drcr_col = find_best_column(
    bank_df,
    logical_name="drcr",
    candidates=[
        "DR|CR",
        "Dr/Cr",
        "DR CR",
        "Debit/Credit",
        "Debit / Credit",
    ],
)

date_col = find_best_column(
    bank_df,
    logical_name="date",
    candidates=[
        "Tran Date",
        "Transaction Date",
        "Date",
        "Txn Date",
        "Value Date",
    ],
)

particulars_col = find_best_column(
    bank_df,
    logical_name="particulars",
    candidates=[
        "Transaction Particulars",
        "Particulars",
        "Description",
        "Details",
        "Narration",
    ],
)


# -----------------------------
# 4. Helper function to parse particulars (robust / fuzzy)
# -----------------------------
def parse_particulars(text):
    """
    Try to infer vendor and category from a (possibly unstructured)
    transaction description using multiple strategies:
    - substring search against known categories from the expenses file
    - substring search against known vendors from the expenses file
    - vendor → category mapping from expenses, when category not explicit
    - legacy '/'-split fallback for structured descriptions
    """
    if not isinstance(text, str):
        return None, None

    raw_text = text.strip()
    if not raw_text:
        return None, None

    lowered = raw_text.lower()

    # 1) Try to detect category by substring match (longest first)
    detected_category = None
    if expense_categories:
        for cat in sorted(
            (str(c).strip() for c in expense_categories if str(c).strip()),
            key=len,
            reverse=True,
        ):
            if cat.lower() in lowered:
                detected_category = cat
                break

    # 2) Try to detect vendor by substring match against known vendors
    detected_vendor = None
    if known_vendors:
        for vendor in sorted(
            (v for v in known_vendors if v),
            key=len,
            reverse=True,
        ):
            if vendor.lower() in lowered:
                detected_vendor = vendor
                break

    # 3) If vendor found but category not, consult vendor → category map
    if detected_vendor and not detected_category:
        mapped_cat = vendor_category_map.get(_normalise_label(detected_vendor))
        if mapped_cat:
            detected_category = mapped_cat

    # 4) Legacy fallback: split by '/' and take positions if still missing
    if not detected_vendor or not detected_category:
        parts = [p.strip() for p in raw_text.split("/") if p.strip()]
        if not detected_vendor and len(parts) > 3:
            detected_vendor = detected_vendor or parts[3]
        if not detected_category and len(parts) > 4:
            detected_category = detected_category or parts[4]

    return detected_vendor or None, detected_category or None


# -----------------------------
# 5. Category normalisation
# -----------------------------
def normalize_category(vendor: str | None, raw_category: str | None) -> str | None:
    """
    Map any raw / fuzzy category signal to a single canonical category.

    Sources of truth (in order of precedence):
    1. Direct or fuzzy match of raw_category against categories from expenses_xls
    2. Vendor → category mapping from expenses_xls (using fuzzy vendor match)
    3. Fallback: title-cased raw_category if we have nothing better
    """
    if not raw_category and not vendor:
        return None

    # 1) Direct / fuzzy match on raw_category
    if raw_category:
        key = _normalise_label(raw_category)
        if key in canonical_category_map:
            return canonical_category_map[key].upper()

        # Fuzzy match on canonical keys
        if canonical_category_map:
            keys = list(canonical_category_map.keys())
            match = get_close_matches(key, keys, n=1, cutoff=0.7)
            if match:
                return canonical_category_map[match[0]].upper()

    # 2) Vendor → category mapping
    if vendor and vendor_category_map:
        v_key = _normalise_label(vendor)
        # Direct match
        if v_key in vendor_category_map:
            return str(vendor_category_map[v_key]).strip().upper()

        # Fuzzy vendor → approximate mapping
        v_keys = list(vendor_category_map.keys())
        v_match = get_close_matches(v_key, v_keys, n=1, cutoff=0.75)
        if v_match:
            return str(vendor_category_map[v_match[0]]).strip().upper()

    # 3) Fallback: clean up raw_category text a bit
    if raw_category:
        return str(raw_category).strip().upper()

    return None


# -----------------------------
# 6. Transform bank statement
# -----------------------------
records = []

for _, row in bank_df.iterrows():
    indicator = str(row[drcr_col]).strip().upper()
    amount_value = row[amount_col]

    # Parse raw vendor & category signals from description
    vendor, raw_category = parse_particulars(row[particulars_col])
    broader_category = normalize_category(vendor, raw_category)

    # Default behaviour: keep original parsed category and broader category
    category_out = raw_category
    broader_category_out = broader_category

    # Track whether we corrected a mislabelled debit
    corrected_debit = False

    # Fix only the inconsistent cases where debits are shown as "AMOUNT RECEIVED"
    if indicator == "DR":
        # If the fine-grained category says AMOUNT RECEIVED, flip it to AMOUNT DEBITED
        if category_out and str(category_out).strip().upper() == "AMOUNT RECEIVED":
            category_out = "AMOUNT DEBITED"
            corrected_debit = True
        # If the broader category says AMOUNT RECEIVED, flip that too
        if broader_category_out and str(broader_category_out).strip().upper() == "AMOUNT RECEIVED":
            broader_category_out = "AMOUNT DEBITED"
            corrected_debit = True

    # For credits, enforce AMOUNT RECEIVED consistently
    if indicator == "CR":
        category_out = "AMOUNT RECEIVED"
        broader_category_out = "AMOUNT RECEIVED"

    dr_amount = None
    cr_amount = None

    if indicator == "DR":
        dr_amount = amount_value
    elif indicator == "CR":
        cr_amount = amount_value

    # Decide code with overrides for special cases
    code_out = category_code_map.get(broader_category_out)
    if indicator == "CR":
        code_out = "AR"
    elif corrected_debit:
        code_out = "AD"

    records.append({
        "Date": row[date_col],
        "Transaction Description": row[particulars_col],
        "Client/Vendor": vendor,
        "Category": category_out,
        "Broader Category": broader_category_out,
        "Code": code_out,
        "DR Amount": dr_amount,
        "CR Amount": cr_amount,
        "Project": None,
        "DD": None
    })

# -----------------------------
# 7. Final DataFrame
# -----------------------------
final_df = pd.DataFrame(records)

# Optional: save output
final_df.to_excel(r"4. APRIL\APRIL_TRANSFORMED_EXPENSES.xlsx", index=False)

print("Transformation completed successfully.")
