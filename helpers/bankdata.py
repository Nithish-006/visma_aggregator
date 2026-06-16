"""Per-bank data loading + cache (multi-bank support).

State (DB connection flag, dataframe cache) lives on ``extensions.state`` so it
is shared live across every blueprint instead of being a rebound module global.
"""

import pandas as pd

from extensions import db_manager, state


def load_bank_data_from_db(bank_code='axis'):
    """Load and preprocess financial data from database for a specific bank"""
    if not state.db_connected:
        state.db_connected = db_manager.connect()

    if not state.db_connected:

        return pd.DataFrame()

    try:
        df = db_manager.get_all_transactions(bank_code)

        if df.empty:

            return pd.DataFrame()

        # Ensure date column is datetime
        if 'Date' in df.columns:
            df['date'] = pd.to_datetime(df['Date'])
        else:
            df['date'] = pd.to_datetime(df['transaction_date'])

        # Ensure numeric columns
        df['DR Amount'] = pd.to_numeric(df['DR Amount'], errors='coerce').fillna(0)
        df['CR Amount'] = pd.to_numeric(df['CR Amount'], errors='coerce').fillna(0)

        # Sort by date first
        df = df.sort_values('date')

        # Compute derived fields
        df['month_name'] = df['date'].dt.strftime('%B %Y')
        df['month'] = df['date'].dt.to_period('M').astype(str)
        df['net'] = df['CR Amount'] - df['DR Amount']
        df['running_balance'] = df['net'].cumsum()

        # Clean categories
        df['Category'] = df['Category'].fillna('Uncategorized')
        df['Client/Vendor'] = df['Client/Vendor'].fillna('Unknown')


        return df

    except Exception as e:

        return pd.DataFrame()


def get_bank_df(bank_code='axis'):
    """Get dataframe for a specific bank (with caching)"""
    if bank_code not in state.df_cache:
        state.df_cache[bank_code] = load_bank_data_from_db(bank_code)

    return state.df_cache.get(bank_code, pd.DataFrame())


def reload_bank_data(bank_code='axis'):
    """Reload financial data for a specific bank"""
    if bank_code in state.df_cache:
        del state.df_cache[bank_code]
    return get_bank_df(bank_code)
