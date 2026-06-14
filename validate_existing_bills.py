"""
C1 — Tier-1 arithmetic re-check of the existing bills (no Gemini, instant, free).

Reads every row from bill_invoices and sales_invoices (plus their line items),
runs the SAME reconciliation as the live extraction path
(extraction_validator.validate_db_row), writes the verdict back into the
validation_status / validation_diff / validation_notes columns, and emits an
Excel report so the bad minority can be eyeballed.

This surfaces every internally-inconsistent bill (freight-in-GST and most
wrong-totals break the header identity) using only the numbers already in the DB.

Usage (from repo root, with .env pointing at the target DB):
    python validate_existing_bills.py
    python validate_existing_bills.py --tolerance 5      # looser rounding
    python validate_existing_bills.py --dry-run          # don't write back
    python validate_existing_bills.py --no-pdf-check      # skip PDF-on-disk check

Output: validation_report_tier1.xlsx (one sheet per kind: Purchase, Sales).
"""

import os
import sys
import glob
import argparse

# When --prod is passed, load credentials from .env.prod (gitignored) BEFORE
# importing database/config, with override=True so they win over the local
# .env that config.load_dotenv() reads at import time. This lets us validate
# the prod DB without touching the local .env.
if '--prod' in sys.argv:
    from dotenv import load_dotenv
    _prod_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env.prod')
    if not os.path.exists(_prod_env):
        print(f"[!] --prod given but {_prod_env} not found.")
        sys.exit(1)
    load_dotenv(_prod_env, override=True)

from database import DatabaseManager
from extraction_validator import validate_db_row, notes_from_result
from config import Config


# (kind label, invoice table, line-item table, file prefix)
SOURCES = [
    ('purchase', 'bill_invoices', 'bill_line_items', 'bill'),
    ('sales', 'sales_invoices', 'sales_line_items', 'sales'),
]


def find_pdf(filename, prefix, upload_folder):
    """Locate the source file on disk. Files are stored as
    <prefix>_<timestamp>_<originalname>; the DB keeps the original filename.
    Mirrors the serve route's glob approach. Returns the path or None.

    NOTE: duplicate original filenames can yield multiple matches; we return the
    most recent (last sorted) and flag the ambiguity count for manual mapping.
    """
    if not filename:
        return None, 0
    direct = os.path.join(upload_folder, filename)
    if os.path.exists(direct):
        return direct, 1
    pattern = os.path.join(upload_folder, f"{prefix}_*_{filename}")
    matches = sorted(glob.glob(pattern))
    if matches:
        return matches[-1], len(matches)
    return None, 0


def fetch_rows(db, invoice_table, line_table):
    """Return (invoices, line_items_by_invoice_id) for one source."""
    with db.get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM {invoice_table} ORDER BY id")
        invoices = cursor.fetchall()

        cursor.execute(
            f"SELECT * FROM {line_table} ORDER BY invoice_id, sl_no"
        )
        line_rows = cursor.fetchall()
        cursor.close()

    by_invoice = {}
    for li in line_rows:
        by_invoice.setdefault(li['invoice_id'], []).append(li)
    return invoices, by_invoice


def write_back(db, invoice_table, invoice_id, validation):
    """Persist a validation verdict onto the stored invoice row."""
    db.execute_query(
        f"UPDATE {invoice_table} SET validation_status = %s, "
        f"validation_diff = %s, validation_notes = %s WHERE id = %s",
        (validation['status'], validation['diff'],
         notes_from_result(validation), invoice_id)
    )


def run(tolerance, dry_run, pdf_check):
    db = DatabaseManager()
    if not db.ensure_connected():
        print("[!] Could not connect to the database. Check your .env settings.")
        sys.exit(1)

    # Make sure the target columns exist before we write back. Skipped on a
    # dry-run so it stays 100% read-only (the ALTER is only needed to persist).
    if not dry_run:
        db.ensure_validation_columns()

    upload_folder = Config.UPLOAD_FOLDER

    try:
        import pandas as pd
    except ImportError:
        print("[!] pandas is required for the Excel report.")
        sys.exit(1)

    report_sheets = {}
    grand_total = grand_review = 0

    for kind, invoice_table, line_table, prefix in SOURCES:
        try:
            invoices, by_invoice = fetch_rows(db, invoice_table, line_table)
        except Exception as e:
            print(f"[!] Skipping {kind} ({invoice_table}): {e}")
            continue

        rows = []
        review_count = 0
        for inv in invoices:
            line_items = by_invoice.get(inv['id'], [])
            validation = validate_db_row(inv, line_items, tolerance=tolerance)

            if validation['status'] == 'review':
                review_count += 1

            if not dry_run:
                write_back(db, invoice_table, inv['id'], validation)

            pdf_found, match_count = (None, 0)
            if pdf_check:
                path, match_count = find_pdf(inv.get('filename'), prefix, upload_folder)
                pdf_found = 'Y' if path else 'N'

            rows.append({
                'ID': inv['id'],
                'Invoice Number': inv.get('invoice_number', ''),
                'Invoice Date': inv.get('invoice_date', ''),
                'Vendor/Buyer': inv.get('vendor_name', '') or inv.get('buyer_name', ''),
                'Total Amount': float(inv.get('total_amount') or 0),
                'Status': validation['status'],
                'Score': validation['score'],
                'Header Gap': validation['diff'],
                'Line Items': len(line_items),
                'Failures': notes_from_result(validation),
                'PDF Found': pdf_found if pdf_check else 'n/a',
                'PDF Matches': match_count if pdf_check else '',
            })

        report_sheets[kind.capitalize()] = pd.DataFrame(rows)
        grand_total += len(invoices)
        grand_review += review_count
        print(f"[+] {kind}: {len(invoices)} bills checked, "
              f"{review_count} flagged 'review'"
              + (" (dry-run, not written)" if dry_run else ""))

    # Emit the report.
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'validation_report_tier1.xlsx')
    with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
        wrote_any = False
        for sheet_name, df in report_sheets.items():
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                wrote_any = True
        if not wrote_any:
            pd.DataFrame([{'note': 'no bills found'}]).to_excel(
                writer, sheet_name='Empty', index=False)

    print(f"\n[+] Tier-1 complete: {grand_total} bills, {grand_review} flagged "
          f"'review' ({100 * grand_review / grand_total:.0f}%)"
          if grand_total else "\n[+] Tier-1 complete: no bills found")
    print(f"[+] Report written to {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Tier-1 arithmetic re-check of existing bills")
    parser.add_argument('--tolerance', type=float, default=2.0,
                        help="INR rounding tolerance (default 2.0)")
    parser.add_argument('--dry-run', action='store_true',
                        help="compute and report but do not write back to the DB")
    parser.add_argument('--no-pdf-check', dest='pdf_check', action='store_false',
                        help="skip the 'is the source PDF on disk' check")
    parser.add_argument('--prod', action='store_true',
                        help="load credentials from .env.prod (handled at import time)")
    args = parser.parse_args()
    run(args.tolerance, args.dry_run, args.pdf_check)


if __name__ == '__main__':
    main()
