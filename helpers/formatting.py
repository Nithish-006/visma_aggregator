"""Pure formatting / display helpers (no app or DB state)."""

import re

import pandas as pd

ILLEGAL_XML_CHARS = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')


def sanitize_for_excel(df):
    """Remove illegal XML characters that cause openpyxl to crash"""
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].apply(
            lambda x: ILLEGAL_XML_CHARS.sub('', x) if isinstance(x, str) else x
        )
    return df


def safe_col_width(series, col_name):
    """Calculate column width safely, handling empty/mixed-type columns"""
    if series.empty:
        return len(str(col_name)) + 2
    try:
        col_max = series.fillna('').astype(str).apply(len).max()
        return min(max(int(col_max), len(str(col_name))) + 2, 50)
    except Exception:
        return len(str(col_name)) + 2


def format_indian_number(amount):
    """Format number with Indian comma system (full numbers, no abbreviations)"""
    if pd.isna(amount) or amount == 0:
        return "₹0"

    abs_amount = abs(amount)
    sign = "-" if amount < 0 else ""

    # Format with Indian comma system (lakhs and crores)
    # Example: 12,34,567.89
    def indian_format(num):
        s = f"{num:,.2f}"
        # Convert to Indian format: 1,234,567.89 -> 12,34,567.89
        parts = s.split('.')
        integer_part = parts[0].replace(',', '')
        decimal_part = parts[1] if len(parts) > 1 else '00'

        # Apply Indian grouping
        if len(integer_part) <= 3:
            formatted = integer_part
        else:
            # First group of 3 from right, then groups of 2
            formatted = integer_part[-3:]
            remaining = integer_part[:-3]
            while remaining:
                if len(remaining) <= 2:
                    formatted = remaining + ',' + formatted
                    remaining = ''
                else:
                    formatted = remaining[-2:] + ',' + formatted
                    remaining = remaining[:-2]

        # Remove decimal if it's .00
        if decimal_part == '00':
            return formatted
        return formatted + '.' + decimal_part

    return f"{sign}₹{indian_format(abs_amount)}"
