import pandas as pd
from pathlib import Path

from aggregator import (
    find_best_column,
    parse_particulars,
    normalize_category,
)


def transform_bank_statement(bank_path: Path) -> pd.DataFrame:
    """
    Apply the same transformation logic as aggregator.py to a single
    bank statement file, returning the transformed DataFrame.
    """
    bank_df = pd.read_excel(bank_path)

    # Resolve schema for this specific bank file
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

    records: list[dict] = []

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
        from aggregator import category_code_map  # lazy import to avoid circular issues

        code_out = category_code_map.get(broader_category_out)
        if indicator == "CR":
            code_out = "AR"
        elif corrected_debit:
            code_out = "AD"

        records.append(
            {
                "Date": row[date_col],
                "Transaction Description": row[particulars_col],
                "Client/Vendor": vendor,
                "Category": category_out,
                "Broader Category": broader_category_out,
                "Code": code_out,
                "DR Amount": dr_amount,
                "CR Amount": cr_amount,
                "Project": None,
                "DD": None,
                "Source File": bank_path.name,
            }
        )

    return pd.DataFrame(records)


def main() -> None:
    base_dir = Path(__file__).resolve().parent

    # Explicit list of monthly bank statement files for Apr–Dec 2025
    bank_files = [
        base_dir / "4. APRIL" / "APRIL -25-26  BANK STATEMENT.xlsx",
        base_dir / "5. MAY" / "01.05.25 TO 25.05.25.xlsx",
        base_dir / "6. JUNE" / "AXIS BANK STATEMENT   JUNE 01 TO 30.XLSX",
        base_dir / "7. JULY" / "Axis Bank 01.07.25 to 31.07.25.XLSX",
        base_dir / "8. AUGUST" / "AXIS BANK 01-08-2025 TO 31.08.25.XLSX",
        base_dir / "9. SEPTEMBER" / "Account_Statement_01.09.25 to 30.09.25.XLSX",
        base_dir / "10. OCTOBER" / "Account_Statement_Report_31-10-2025_1607hrs.XLSX",
        base_dir / "11. NOVEMBER" / "Account_Statement_Report_NOV 01 TO 02-12-2025_1146hrs.XLSX",
        base_dir / "12. DECEMBER" / "Account_Statement_Report_22-12-2025_1141hrs.XLSX",
    ]

    all_frames: list[pd.DataFrame] = []

    for path in bank_files:
        if not path.exists():
            # Skip missing files silently; you can change this to raise if preferred
            continue
        df_month = transform_bank_statement(path)
        all_frames.append(df_month)

    if not all_frames:
        print("No monthly bank files found to aggregate.")
        return

    combined_df = pd.concat(all_frames, ignore_index=True)
    output_path = base_dir / "APR_TO_DEC_2025_AGGREGATED.xlsx"
    combined_df.to_excel(output_path, index=False)
    print(f"Aggregated file written to: {output_path}")


if __name__ == "__main__":
    main()
