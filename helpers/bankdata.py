"""Per-bank data loading (multi-bank support).

Reads always come straight from the database. The old design kept a long-lived
``state.df_cache[bank_code]`` dataframe that only the worker handling an edit
would refresh — so with ``gunicorn --workers 2`` the *other* worker kept serving
stale totals, and aggregates flip-flopped between fresh and stale on every
refresh. There is no cross-worker cache to invalidate now, so an edit committed
by any worker is immediately visible from all of them.

To avoid reloading the same bank twice inside one request, the frame is memoised
on Flask's per-request ``g`` object only (never across requests). Outside a
request context (e.g. startup, exports) we just load fresh.
"""

import pandas as pd
from flask import g, has_request_context

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
    """Return a fresh dataframe for a bank, memoised only within this request.

    Cross-request there is no cache, so every request (on any gunicorn worker)
    reflects the latest committed edits.
    """
    if has_request_context():
        cache = getattr(g, '_bank_df_cache', None)
        if cache is None:
            cache = g._bank_df_cache = {}
        if bank_code not in cache:
            cache[bank_code] = load_bank_data_from_db(bank_code)
        return cache[bank_code]
    return load_bank_data_from_db(bank_code)


def reload_bank_data(bank_code='axis'):
    """Back-compat shim for the write paths.

    Reads are always fresh now, so there is no persistent cache to rebuild. We
    only drop this request's memo (so a re-read later in the same request sees
    the write) and return a freshly loaded frame.
    """
    if has_request_context():
        cache = getattr(g, '_bank_df_cache', None)
        if cache is not None:
            cache.pop(bank_code, None)
    return load_bank_data_from_db(bank_code)
