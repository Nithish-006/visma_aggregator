import pandas as pd
import numpy as np

# Load the spreadsheet
file_path = 'APR_TO_DEC_2025_AGGREGATED_FINAL_WITH_CODE.xlsx'

try:
    df = pd.read_excel(file_path)
    print("File loaded successfully.")

    # 1. Format 'Date' as datetime object
    def parse_date(date_str):
        if pd.isna(date_str):
            return pd.NaT

        # Normalize to string
        clean_str = str(date_str).strip()

        # Handle mixed separators (e.g. 12-04-2025 vs 12/10/2025)
        # Replacing commonly used separators with / makes pandas parser happier
        clean_str = clean_str.replace('-', '/').replace('.', '/')

        try:
            return pd.to_datetime(clean_str, dayfirst=True)
        except (ValueError, TypeError):
             return pd.NaT

    df['Date'] = df['Date'].apply(parse_date)

    # Check for failure count
    nat_count = df['Date'].isna().sum()
    if nat_count > 0:
        print(f"\nWarning: {nat_count} rows have invalid dates. First few invalid values:")
        # We need to reload or look at original column to see what failed,
        # but here we just report the count.


    # 2. Format 'DR Amount' and 'CR Amount' as floats (monetary numbers)
    # We define a helper function to clean string currency values (removing commas)
    def clean_currency(x):
        if pd.isna(x) or x == '':
            return 0.0
        if isinstance(x, (int, float)):
            return float(x)
        # Convert to string, remove commas and whitespace
        clean_str = str(x).replace(',', '').strip()
        try:
            return float(clean_str)
        except ValueError:
            return 0.0

    df['DR Amount'] = df['DR Amount'].apply(clean_currency)
    df['CR Amount'] = df['CR Amount'].apply(clean_currency)

    # Verification
    print("\nData Types:")
    print(df.dtypes)

    print("\nFirst 5 rows:")
    print(df[['Date', 'DR Amount', 'CR Amount']].head())

    # Optional: Save the cleaned data back to a new file to preserve the formatting/types
    df.to_excel("cleaned_financial_data.xlsx", index=False)

except FileNotFoundError:
    print(f"Error: The file '{file_path}' was not found.")
except Exception as e:
    print(f"An error occurred: {e}")
