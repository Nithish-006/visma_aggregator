"""Legacy data loading + generic dataframe filters.

The legacy combined frame lives on ``extensions.state.df_global`` so callers
share one live object after a reload. Config values are read straight off
``config.Config`` (not ``app.config``) so these work at import time, before any
Flask app/request context exists.
"""

import pandas as pd

from config import Config
from extensions import state
from helpers.bankdata import load_bank_data_from_db
from helpers.projects import parse_project_selection


def load_financial_data_from_db():
    """Load and preprocess financial data from database (legacy - uses axis)"""
    return load_bank_data_from_db('axis')


def load_financial_data_from_excel():
    """Load and preprocess financial data from Excel file"""
    try:
        df = pd.read_excel(Config.EXCEL_FILE)

        # Parse dates - handle both formats
        def parse_date(date_str):
            if pd.isna(date_str):
                return pd.NaT
            date_str = str(date_str).strip()
            for fmt in ['%d-%m-%Y', '%d/%m/%Y', '%d-%m-%y', '%d/%m/%y']:
                try:
                    return pd.to_datetime(date_str, format=fmt)
                except:
                    continue
            try:
                return pd.to_datetime(date_str, dayfirst=True)
            except:
                return pd.NaT

        df['date'] = df['Date'].apply(parse_date)

        # Clean amounts - remove commas
        df['DR Amount'] = df['DR Amount'].astype(str).str.replace(',', '').replace('nan', '')
        df['DR Amount'] = pd.to_numeric(df['DR Amount'], errors='coerce').fillna(0)

        df['CR Amount'] = df['CR Amount'].astype(str).str.replace(',', '').replace('nan', '')
        df['CR Amount'] = pd.to_numeric(df['CR Amount'], errors='coerce').fillna(0)

        # Sort by date first
        df = df.sort_values('date')

        # Derived fields
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


def reload_data():
    """Reload legacy financial data into shared state (backwards compatibility)"""
    if Config.USE_DATABASE:
        state.df_global = load_financial_data_from_db()
    else:
        state.df_global = load_financial_data_from_excel()
    return state.df_global


def parse_month_filter(month_filter):
    """Parse month filter - handle single or multiple months"""
    if not month_filter or month_filter == 'All':
        return ['All']
    if ',' in month_filter:
        return [m.strip() for m in month_filter.split(',')]
    return [month_filter]


def filter_by_months(df, month_list):
    """Filter dataframe by list of months"""
    if month_list == ['All']:
        return df
    return df[df['month'].isin(month_list)]


def filter_by_date_range(df, start_date=None, end_date=None):
    """Filter dataframe by date range"""
    if not start_date and not end_date:
        return df

    filtered_df = df.copy()

    if start_date:
        try:
            start = pd.to_datetime(start_date)
            filtered_df = filtered_df[filtered_df['date'] >= start]
        except Exception as e:
            pass


    if end_date:
        try:
            end = pd.to_datetime(end_date)
            filtered_df = filtered_df[filtered_df['date'] <= end]
        except Exception as e:
            pass


    return filtered_df


def filter_by_project(df, project=None):
    """Filter dataframe by project (supports comma-separated multi-select)"""
    if not project or project == 'All':
        return df

    # Handle both 'Project' and 'project' column names
    project_col = 'Project' if 'Project' in df.columns else 'project'
    if project_col not in df.columns:
        return df

    # Handle comma-separated multi-select
    if ',' in project:
        projects = [p.strip() for p in project.split(',')]
        return df[df[project_col].astype(str).str.strip().isin(projects)]

    return df[df[project_col].astype(str).str.strip() == project.strip()]


def filter_by_category(df, category=None):
    """Filter dataframe by category (supports comma-separated multi-select)"""
    if not category or category == 'All':
        return df

    if 'Category' not in df.columns:
        return df

    # Handle comma-separated multi-select
    if ',' in category:
        categories = [c.strip() for c in category.split(',')]
        return df[df['Category'].isin(categories)]

    return df[df['Category'] == category]


def filter_by_vendor(df, vendor=None):
    """Filter dataframe by vendor (supports comma-separated multi-select)"""
    if not vendor or vendor == 'All':
        return df

    vendor_col = 'Client/Vendor' if 'Client/Vendor' in df.columns else 'vendor'
    if vendor_col not in df.columns:
        return df

    # Handle comma-separated multi-select
    if ',' in vendor:
        vendors = [v.strip() for v in vendor.split(',')]
        return df[df[vendor_col].isin(vendors)]

    return df[df[vendor_col] == vendor]


def robust_filter_by_project(df, project=None):
    """Filter dataframe by the selected project(s).

    Canonical selections ("659 - JAMUNA") match rows strictly by the
    "<id> -" tag prefix; free-text selections keep the legacy stem-prefix
    behaviour (also testing the segment after " - ")."""
    if not project or project == 'All':
        return df

    project_col = 'Project' if 'Project' in df.columns else 'project'
    if project_col not in df.columns:
        return df

    ids, stems = parse_project_selection(project)
    if not ids and not stems:
        return df

    s = df[project_col].astype(str).str.strip()
    mask = pd.Series(False, index=df.index)
    for pid in ids:
        mask = mask | s.str.match(rf'^{pid}\s*-')
    if stems:
        lower_col = s.str.lower()
        after_dash = lower_col.str.split(' - ', n=1).str[-1].str.strip()
        for stem in stems:
            mask = mask | lower_col.str.startswith(stem) | after_dash.str.startswith(stem)
    return df[mask]
