"""Bank pages + hub stats + /api/<bank_code>/* endpoints."""

import io
import os
from datetime import datetime

import pandas as pd

from flask import (
    Blueprint, render_template, request, jsonify, send_file, redirect, url_for,
)
from werkzeug.utils import secure_filename

from config import (
    Config, BANK_CONFIG, VALID_BANK_CODES, get_bank_config, get_bank_table,
    allowed_file, now_ist,
)
from extensions import db_manager, state
from bank_statement_processor import process_bank_statement
from helpers.formatting import format_indian_number, sanitize_for_excel, safe_col_width
from helpers.bankdata import get_bank_df, reload_bank_data
from helpers.dataframe import (
    reload_data, filter_by_date_range, filter_by_category, filter_by_vendor,
    filter_by_project,
)
from helpers.projects import validate_project_value
from helpers.bill_reconcile import (
    build_bill_vendor_index, is_unbilled_material_purchase,
)
from auth import login_required

bp = Blueprint('banks', __name__)


@bp.route('/dashboard/<bank_code>')
@login_required
def bank_dashboard(bank_code):
    """Render bank-specific dashboard page"""
    if bank_code not in VALID_BANK_CODES:
        return redirect(url_for('auth.index'))

    bank_config = get_bank_config(bank_code)
    return render_template('index.html',
                         bank_code=bank_code,
                         bank_name=bank_config['name'],
                         bank_config=bank_config)


@bp.route('/edit-transactions/<bank_code>')
@login_required
def edit_transactions(bank_code):
    """Render bank-specific transaction edit page"""
    if bank_code not in VALID_BANK_CODES:
        return redirect(url_for('auth.index'))

    bank_config = get_bank_config(bank_code)
    return render_template('edit_transactions.html',
                         bank_code=bank_code,
                         bank_name=bank_config['name'],
                         bank_config=bank_config)


@bp.route('/api/clear-cache', methods=['POST'])
@login_required
def clear_cache():
    """Clear in-memory dataframe cache and reload from database"""
    state.df_cache.clear()
    reload_data()
    return jsonify({'success': True, 'message': 'Cache cleared successfully'})


@bp.route('/api/hub/stats')
@login_required
def get_hub_stats():
    """Get transaction stats for all banks (for hub page)"""
    stats = {}
    for bank_code in VALID_BANK_CODES:
        try:
            df = get_bank_df(bank_code)
            stats[bank_code] = {
                'transaction_count': len(df),
                'name': BANK_CONFIG[bank_code]['name']
            }
        except Exception as e:

            stats[bank_code] = {
                'transaction_count': 0,
                'name': BANK_CONFIG[bank_code]['name']
            }

    return jsonify(stats)


@bp.route('/api/<bank_code>/summary')
@login_required
def get_bank_summary(bank_code):
    """Get summary statistics for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    category = request.args.get('category', 'All')
    project = request.args.get('project', None)
    vendor = request.args.get('vendor', None)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    # Get bank-specific data
    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({
            'current_balance': 0,
            'current_balance_formatted': '₹0',
            'total_income': 0,
            'total_income_formatted': '₹0',
            'total_expense': 0,
            'total_expense_formatted': '₹0',
            'net_cashflow': 0,
            'net_cashflow_formatted': '₹0',
            'expense_ratio': 0,
            'total_transactions': 0
        })

    # Apply multi-select filters
    df = filter_by_category(df, category)
    df = filter_by_date_range(df, start_date, end_date)
    df = filter_by_project(df, project)
    df = filter_by_vendor(df, vendor)

    current_balance = float(df['running_balance'].iloc[-1]) if len(df) > 0 else 0
    total_income = float(df['CR Amount'].sum())
    total_expense = float(df['DR Amount'].sum())
    net_cashflow = total_income - total_expense
    expense_ratio = (total_expense / total_income * 100) if total_income > 0 else 0

    # Calculate this period vs previous period
    if len(df) > 0:
        current_month = df['month'].max()
        last_month = df[df['month'] < current_month]['month'].max() if len(df[df['month'] < current_month]) > 0 else None

        this_month_df = df[df['month'] == current_month] if current_month else pd.DataFrame()
        last_month_df = df[df['month'] == last_month] if last_month else pd.DataFrame()

        this_month_net = float((this_month_df['CR Amount'].sum() - this_month_df['DR Amount'].sum())) if len(this_month_df) > 0 else 0
        last_month_net = float((last_month_df['CR Amount'].sum() - last_month_df['DR Amount'].sum())) if len(last_month_df) > 0 else 0

        expenses_df = df[df['DR Amount'] > 0]
        if len(expenses_df) > 0:
            biggest_category = expenses_df.groupby('Category')['DR Amount'].sum().idxmax()
            biggest_category_amount = float(expenses_df.groupby('Category')['DR Amount'].sum().max())
        else:
            biggest_category = None
            biggest_category_amount = 0
    else:
        this_month_net = 0
        last_month_net = 0
        biggest_category = None
        biggest_category_amount = 0

    net_change = this_month_net - last_month_net if last_month_net != 0 else 0
    net_change_pct = ((net_change / abs(last_month_net)) * 100) if last_month_net != 0 else 0

    return jsonify({
        'current_balance': current_balance,
        'current_balance_formatted': format_indian_number(current_balance),
        'total_income': total_income,
        'total_income_formatted': format_indian_number(total_income),
        'total_expense': total_expense,
        'total_expense_formatted': format_indian_number(total_expense),
        'net_cashflow': net_cashflow,
        'net_cashflow_formatted': format_indian_number(net_cashflow),
        'expense_ratio': round(expense_ratio, 1),
        'total_transactions': len(df),
        'this_month_net': this_month_net,
        'this_month_net_formatted': format_indian_number(this_month_net),
        'last_month_net': last_month_net,
        'last_month_net_formatted': format_indian_number(last_month_net),
        'net_change': net_change,
        'net_change_formatted': format_indian_number(net_change),
        'net_change_pct': round(net_change_pct, 1),
        'biggest_category': biggest_category,
        'biggest_category_amount': biggest_category_amount,
        'biggest_category_amount_formatted': format_indian_number(biggest_category_amount) if biggest_category_amount > 0 else '₹0'
    })


@bp.route('/api/<bank_code>/monthly_trend')
@login_required
def get_bank_monthly_trend(bank_code):
    """Get monthly income/expense trend for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    category = request.args.get('category', 'All')
    project = request.args.get('project', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({'months': [], 'income': [], 'expense': [], 'net': []})

    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)
    df = filter_by_project(df, project)

    if df.empty:
        return jsonify({'months': [], 'income': [], 'expense': [], 'net': []})

    monthly = df.groupby('month_name').agg({
        'CR Amount': 'sum',
        'DR Amount': 'sum',
        'date': 'first'
    }).reset_index().sort_values('date')

    net_values = [(inc - exp) for inc, exp in zip(monthly['CR Amount'].tolist(), monthly['DR Amount'].tolist())]

    avg_expense = monthly['DR Amount'].mean()
    highest_expense_idx = monthly['DR Amount'].idxmax()
    highest_expense_month = monthly.loc[highest_expense_idx, 'month_name'] if len(monthly) > 0 else None
    highest_expense_amount = float(monthly['DR Amount'].max()) if len(monthly) > 0 else 0
    highest_expense_pct = ((highest_expense_amount - avg_expense) / avg_expense * 100) if avg_expense > 0 else 0

    return jsonify({
        'months': monthly['month_name'].tolist(),
        'income': monthly['CR Amount'].tolist(),
        'expense': monthly['DR Amount'].tolist(),
        'net': net_values,
        'highest_expense_month': highest_expense_month,
        'highest_expense_amount': highest_expense_amount,
        'highest_expense_amount_formatted': format_indian_number(highest_expense_amount),
        'highest_expense_pct': round(highest_expense_pct, 1)
    })


@bp.route('/api/<bank_code>/running_balance')
@login_required
def get_bank_running_balance(bank_code):
    """Get running balance over time for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    category = request.args.get('category', 'All')
    project = request.args.get('project', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({'dates': [], 'balance': [], 'sparkline_dates': [], 'sparkline_balance': []})

    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)
    df = filter_by_project(df, project)

    if df.empty:
        return jsonify({'dates': [], 'balance': [], 'sparkline_dates': [], 'sparkline_balance': []})

    if len(df) > 100:
        df_sample = df.iloc[::5].copy()
    else:
        df_sample = df.copy()

    lowest_balance = float(df['running_balance'].min()) if len(df) > 0 else 0
    peak_balance = float(df['running_balance'].max()) if len(df) > 0 else 0
    lowest_date_idx = df['running_balance'].idxmin() if len(df) > 0 else None
    peak_date_idx = df['running_balance'].idxmax() if len(df) > 0 else None

    lowest_date = df.loc[lowest_date_idx, 'date'].strftime('%d %b %Y') if lowest_date_idx is not None else None
    peak_date = df.loc[peak_date_idx, 'date'].strftime('%d %b %Y') if peak_date_idx is not None else None

    if len(df) > 0:
        last_date = df['date'].max()
        thirty_days_ago = last_date - pd.Timedelta(days=30)
        sparkline_df = df[df['date'] >= thirty_days_ago].sort_values('date')
        sparkline_dates = sparkline_df['date'].dt.strftime('%d %b').tolist()
        sparkline_balance = sparkline_df['running_balance'].tolist()
    else:
        sparkline_dates = []
        sparkline_balance = []

    return jsonify({
        'dates': df_sample['date'].dt.strftime('%d %b %Y').tolist(),
        'balance': df_sample['running_balance'].tolist(),
        'lowest_balance': lowest_balance,
        'lowest_date': lowest_date,
        'peak_balance': peak_balance,
        'peak_date': peak_date,
        'sparkline_dates': sparkline_dates,
        'sparkline_balance': sparkline_balance
    })


@bp.route('/api/<bank_code>/categories')
@login_required
def get_bank_categories(bank_code):
    """Get list of all categories for a specific bank (queries database directly)"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    # Check if any filter params are present - if so, return filtered options
    category = request.args.get('category', None)
    project = request.args.get('project', None)
    vendor = request.args.get('vendor', None)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    search = request.args.get('search', None)

    has_filters = any([category, project, vendor, start_date, end_date, search])

    if has_filters:
        # Use get_filtered_options which returns {categories, projects, vendors}
        # We only need categories here
        options = db_manager.get_filtered_options(
            bank_code, category=category, project=project, vendor=vendor,
            start_date=start_date, end_date=end_date, search=search
        )
    else:
        # Query database directly for distinct categories
        options = db_manager.get_filter_options(bank_code)

    categories = ['All'] + options.get('categories', [])
    return jsonify({'categories': categories})


@bp.route('/api/<bank_code>/date_range')
@login_required
def get_bank_date_range(bank_code):
    """Get the min and max dates available for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    df = get_bank_df(bank_code)
    if len(df) == 0:
        return jsonify({'min_date': None, 'max_date': None})

    min_date = df['date'].min()
    max_date = df['date'].max()

    return jsonify({
        'min_date': min_date.strftime('%Y-%m-%d') if pd.notna(min_date) else None,
        'max_date': max_date.strftime('%Y-%m-%d') if pd.notna(max_date) else None
    })


@bp.route('/api/<bank_code>/transactions')
@login_required
def get_bank_transactions(bank_code):
    """Get all transactions for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    category = request.args.get('category', 'All')
    project = request.args.get('project', None)
    vendor = request.args.get('vendor', None)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    limit = int(request.args.get('limit', 10000))
    sort_by = request.args.get('sort_by', 'date')
    sort_order = request.args.get('sort_order', 'desc')
    search_query = request.args.get('search', '').lower()

    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({'transactions': []})

    # Apply multi-select filters
    df = filter_by_category(df, category)
    df = filter_by_date_range(df, start_date, end_date)
    df = filter_by_project(df, project)
    df = filter_by_vendor(df, vendor)

    if search_query:
        df = df[
            df['Transaction Description'].astype(str).str.lower().str.contains(search_query, na=False) |
            df['Client/Vendor'].astype(str).str.lower().str.contains(search_query, na=False) |
            df['Category'].astype(str).str.lower().str.contains(search_query, na=False)
        ]

    ascending = (sort_order == 'asc')

    if sort_by == 'dr_amount':
        df_sorted = df.sort_values(['DR Amount', 'date'], ascending=[ascending, False]).head(limit)
    elif sort_by == 'cr_amount':
        df_sorted = df.sort_values(['CR Amount', 'date'], ascending=[ascending, False]).head(limit)
    else:
        df_sorted = df.sort_values('date', ascending=ascending).head(limit)

    # Cross-check MATERIAL PURCHASE debits against purchase bills (kvb only).
    bill_index = build_bill_vendor_index(
        db_manager.get_purchase_bill_vendors_by_project()) if bank_code == 'kvb' else {}

    transactions = []
    for idx, row in df_sorted.iterrows():
        dr_amount = float(row['DR Amount'])
        project = row.get('Project', '')
        no_bill_warning = dr_amount > 0 and is_unbilled_material_purchase(
            row['Category'], project, row['Client/Vendor'], bill_index, bank_code)
        transactions.append({
            'id': int(idx) if hasattr(idx, '__int__') else idx,
            'date': row['date'].strftime('%d %b %Y'),
            'date_raw': row['date'].strftime('%Y-%m-%d'),
            'description': row['Transaction Description'],
            'vendor': row['Client/Vendor'],
            'category': row['Category'],
            'code': row.get('Code', ''),
            'dr_amount': dr_amount,
            'dr_amount_formatted': format_indian_number(row['DR Amount']) if row['DR Amount'] > 0 else '',
            'cr_amount': float(row['CR Amount']),
            'cr_amount_formatted': format_indian_number(row['CR Amount']) if row['CR Amount'] > 0 else '',
            'net': float(row['net']),
            'net_formatted': format_indian_number(row['net']),
            'project': project,
            'no_bill_warning': no_bill_warning,
            'dd': row.get('DD', ''),
            'notes': row.get('Notes', '')
        })

    return jsonify({'transactions': transactions})


def _filtered_bank_df(bank_code, category, project, vendor, start_date, end_date, search):
    """Cached bank frame narrowed by the same filters the paginated endpoint uses."""
    df = get_bank_df(bank_code).copy()
    if df.empty:
        return df
    df = filter_by_category(df, category)
    df = filter_by_date_range(df, start_date, end_date)
    df = filter_by_project(df, project)
    df = filter_by_vendor(df, vendor)
    if search:
        s = str(search).lower()
        df = df[
            df['Transaction Description'].astype(str).str.lower().str.contains(s, na=False)
            | df['Client/Vendor'].astype(str).str.lower().str.contains(s, na=False)
            | df['Category'].astype(str).str.lower().str.contains(s, na=False)
        ]
    return df


def _flagged_material_purchases(df, bill_index):
    """Rows earning the no-corresponding-purchase-bill warning (kvb).

    Pre-narrows to MATERIAL PURCHASE debits before the vendor match, so the
    per-row check runs on a handful of rows rather than the whole statement.
    """
    if df.empty or 'Category' not in df.columns:
        return df.iloc[0:0]
    cat = df['Category'].astype(str).str.upper().str.strip()
    mp = df[(cat == 'MATERIAL PURCHASE') & (df['DR Amount'] > 0)]
    if mp.empty:
        return mp
    mask = mp.apply(lambda r: is_unbilled_material_purchase(
        r.get('Category', ''), r.get('Project', ''), r.get('Client/Vendor', ''),
        bill_index, 'kvb'), axis=1)
    return mp[mask]


def _serialize_flagged_row(idx, row):
    """One flagged transaction shaped like the paginated endpoint's output."""
    dr_amount = float(row.get('DR Amount', 0) or 0)
    cr_amount = float(row.get('CR Amount', 0) or 0)
    net = float(row['net']) if 'net' in row and pd.notna(row['net']) else cr_amount - dr_amount
    return {
        'id': int(idx) if hasattr(idx, '__int__') else idx,
        'date': row['date'].strftime('%d %b %Y'),
        'date_raw': row['date'].strftime('%Y-%m-%d'),
        'description': row.get('Transaction Description', '') or '',
        'vendor': row.get('Client/Vendor', '') or '',
        'category': row.get('Category', '') or '',
        'code': row.get('Code', '') or '',
        'dr_amount': dr_amount,
        'dr_amount_formatted': format_indian_number(dr_amount) if dr_amount > 0 else '',
        'cr_amount': cr_amount,
        'cr_amount_formatted': format_indian_number(cr_amount) if cr_amount > 0 else '',
        'net': net,
        'net_formatted': format_indian_number(net),
        'project': row.get('Project', '') or '',
        'no_bill_warning': True,
    }


@bp.route('/api/<bank_code>/transactions/paginated')
@login_required
def get_bank_transactions_paginated(bank_code):
    """Get paginated transactions with server-side filtering - fast endpoint for large datasets"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    # Pagination params
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    # Filter params
    category = request.args.get('category', 'All')
    project = request.args.get('project', None)
    vendor = request.args.get('vendor', None)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    search = request.args.get('search', None)
    sort_by = request.args.get('sort_by', 'date')
    sort_order = request.args.get('sort_order', 'desc')
    only_warnings = str(request.args.get('only_warnings', '')).lower() in ('1', 'true', 'yes')

    # Cross-check MATERIAL PURCHASE debits against purchase bills (kvb only).
    bill_index = build_bill_vendor_index(
        db_manager.get_purchase_bill_vendors_by_project()) if bank_code == 'kvb' else {}

    # Live count of no-bill material-purchase debits under the current filters,
    # and — when the "show only flagged" box is ticked — serve just those rows
    # (paginated over the flagged subset, from the in-memory frame).
    warning_count = 0
    if bank_code == 'kvb':
        fdf = _filtered_bank_df(bank_code, category, project, vendor,
                                start_date, end_date, search)
        flagged = _flagged_material_purchases(fdf, bill_index)
        warning_count = len(flagged)

        if only_warnings:
            ascending = (sort_order == 'asc')
            if sort_by == 'dr_amount':
                flagged = flagged.sort_values(['DR Amount', 'date'], ascending=[ascending, False])
            elif sort_by == 'cr_amount':
                flagged = flagged.sort_values(['CR Amount', 'date'], ascending=[ascending, False])
            else:
                flagged = flagged.sort_values('date', ascending=ascending)
            total = warning_count
            total_pages = (total + per_page - 1) // per_page if total else 0
            start = (page - 1) * per_page
            page_rows = flagged.iloc[start:start + per_page]
            return jsonify({
                'transactions': [_serialize_flagged_row(idx, row)
                                 for idx, row in page_rows.iterrows()],
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages,
                'filter_options': db_manager.get_filter_options(bank_code),
                'warning_count': warning_count,
            })

    # Get paginated data directly from database
    result = db_manager.get_paginated_transactions(
        bank_code=bank_code,
        page=page,
        per_page=per_page,
        category=category,
        project=project,
        vendor=vendor,
        start_date=start_date,
        end_date=end_date,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order
    )

    # Format transactions for frontend
    transactions = []
    for row in result['transactions']:
        date_val = row['Date']
        if isinstance(date_val, str):
            date_obj = datetime.strptime(date_val, '%Y-%m-%d')
        else:
            date_obj = date_val

        dr_amount = float(row['DR Amount'] or 0)
        cr_amount = float(row['CR Amount'] or 0)
        net = cr_amount - dr_amount
        project = row['Project'] or ''
        no_bill_warning = dr_amount > 0 and is_unbilled_material_purchase(
            row['Category'], project, row['Client/Vendor'], bill_index, bank_code)

        transactions.append({
            'id': row['id'],
            'date': date_obj.strftime('%d %b %Y'),
            'date_raw': date_obj.strftime('%Y-%m-%d'),
            'description': row['Transaction Description'] or '',
            'vendor': row['Client/Vendor'] or '',
            'category': row['Category'] or '',
            'code': row['Code'] or '',
            'dr_amount': dr_amount,
            'dr_amount_formatted': format_indian_number(dr_amount) if dr_amount > 0 else '',
            'cr_amount': cr_amount,
            'cr_amount_formatted': format_indian_number(cr_amount) if cr_amount > 0 else '',
            'net': net,
            'net_formatted': format_indian_number(net),
            'project': project,
            'no_bill_warning': no_bill_warning
        })

    # Also return filtered options so dropdowns can update in the same response
    has_active_filters = any([
        category and category != 'All', project, vendor, start_date, end_date, search
    ])

    if has_active_filters:
        try:
            filter_options = db_manager.get_filtered_options(
                bank_code, category=category, project=project, vendor=vendor,
                start_date=start_date, end_date=end_date, search=search
            )
        except Exception as e:
            filter_options = db_manager.get_filter_options(bank_code)
    else:
        filter_options = db_manager.get_filter_options(bank_code)

    return jsonify({
        'transactions': transactions,
        'total': result['total'],
        'page': result['page'],
        'per_page': result['per_page'],
        'total_pages': result['total_pages'],
        'filter_options': filter_options,
        'warning_count': warning_count
    })


@bp.route('/api/<bank_code>/filter-options')
@login_required
def get_bank_filter_options(bank_code):
    """Get filter options (categories, projects, vendors) for dropdowns.
    When filter params are provided, returns only distinct values matching the active filters."""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    # Check if any filter params are present - if so, return filtered options
    category = request.args.get('category', None)
    project = request.args.get('project', None)
    vendor = request.args.get('vendor', None)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    search = request.args.get('search', None)

    has_filters = any([category, project, vendor, start_date, end_date, search])

    if has_filters:
        options = db_manager.get_filtered_options(
            bank_code, category=category, project=project, vendor=vendor,
            start_date=start_date, end_date=end_date, search=search
        )
    else:
        options = db_manager.get_filter_options(bank_code)

    return jsonify(options)


@bp.route('/api/<bank_code>/upload', methods=['POST'])
@login_required
def upload_bank_statement(bank_code):
    """Upload and process bank statement for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Only .xlsx and .xls files are allowed'}), 400

        # Get optional password for encrypted files (especially KVB)
        password = request.form.get('password', None)

        filename = secure_filename(file.filename)
        timestamp = now_ist().strftime('%Y%m%d_%H%M%S')
        filename = f"{bank_code}_{timestamp}_{filename}"
        filepath = os.path.join(Config.UPLOAD_FOLDER, filename)

        file.save(filepath)


        df = process_bank_statement(filepath, bank_code, password=password)

        if Config.USE_DATABASE:


            if not state.db_connected:
                connected = db_manager.connect()
                if connected:
                    state.db_connected = True
                else:
                    return jsonify({
                        'error': 'Database connection failed',
                        'details': 'Could not connect to MySQL database'
                    }), 500

            results = db_manager.insert_transactions_bulk(df, bank_code)


            db_manager.log_upload(
                filename=filename,
                records_processed=results['total'],
                records_inserted=results['inserted'],
                records_duplicated=results['duplicates'],
                status='success' if results['errors'] == 0 else 'partial',
                error_message='; '.join(results['error_messages'][:5]) if results['error_messages'] else None,
                bank_code=bank_code
            )


            reload_bank_data(bank_code)


            return jsonify({
                'success': True,
                'message': f'Bank statement processed successfully for {BANK_CONFIG[bank_code]["name"]}',
                'filename': filename,
                'stats': {
                    'total': results['total'],
                    'inserted': results['inserted'],
                    'duplicates': results['duplicates'],
                    'errors': results['errors']
                }
            })
        else:
            output_file = filepath.replace('.xlsx', '_PROCESSED.xlsx')
            df.to_excel(output_file, index=False)

            return jsonify({
                'success': True,
                'message': 'Bank statement processed successfully (Excel mode)',
                'filename': filename,
                'output_file': output_file,
                'stats': {
                    'total': len(df),
                    'inserted': 0,
                    'duplicates': 0,
                    'errors': 0
                }
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Error processing file',
            'details': str(e)
        }), 500


@bp.route('/api/<bank_code>/transaction/update', methods=['POST'])
@login_required
def update_bank_transaction(bank_code):
    """Update a transaction's editable fields for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    try:
        data = request.json
        table = get_bank_table(bank_code)

        transaction_id = data.get('id')
        transaction_date = data.get('date')
        description = data.get('description')
        # Support both field names - use proper fallback for zero values
        dr_amount = data.get('debit') if data.get('debit') is not None else data.get('dr_amount', 0)
        cr_amount = data.get('credit') if data.get('credit') is not None else data.get('cr_amount', 0)
        # Ensure amounts are never None (would cause WHERE clause to fail)
        dr_amount = float(dr_amount) if dr_amount is not None else 0.0
        cr_amount = float(cr_amount) if cr_amount is not None else 0.0

        category = (data.get('category') or 'Uncategorized').strip().upper()
        code = data.get('code')
        vendor = (data.get('vendor') or 'Unknown').strip()
        ok, project, perr = validate_project_value(data.get('project'))
        if not ok:
            return jsonify({'success': False, 'error': perr}), 400

        # Derive code from category if not provided
        category_codes = {
            'OFFICE EXPENSES': 'OE', 'FACTORY EXPENSES': 'FE', 'SITE EXPENSES': 'SE',
            'TRANSPORT EXPENSES': 'TE', 'MATERIAL PURCHASE': 'MP',
            'DUTIES & TAX': 'DT', 'SALARY AC': 'SA', 'BANK CHARGES': 'BC',
            'AMOUNT RECEIVED': 'AR', 'UNCATEGORIZED': 'UC'
        }
        if not code:
            code = category_codes.get(category, 'UC')

        if not all([transaction_date, description is not None]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields'
            }), 400

        if Config.USE_DATABASE:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                # Prefer matching by primary key id (unambiguous, and robust to the
                # DATETIME transaction_date column). Fall back to the legacy value
                # match only when no id is supplied.
                if transaction_id is not None:
                    query = f"""
                    UPDATE {table}
                    SET
                        category = %s,
                        code = %s,
                        client_vendor = %s,
                        project = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    LIMIT 1
                    """
                    cursor.execute(query, (category, code, vendor, project, transaction_id))
                else:
                    query = f"""
                    UPDATE {table}
                    SET
                        category = %s,
                        code = %s,
                        client_vendor = %s,
                        project = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE DATE(transaction_date) = %s
                      AND transaction_description = %s
                      AND dr_amount = %s
                      AND cr_amount = %s
                    LIMIT 1
                    """
                    cursor.execute(query, (
                        category, code, vendor, project,
                        transaction_date, description, dr_amount, cr_amount
                    ))
                conn.commit()
                affected_rows = cursor.rowcount
                cursor.close()

            if affected_rows > 0:
                reload_bank_data(bank_code)
                return jsonify({
                    'success': True,
                    'message': 'Transaction updated successfully'
                })
            else:
                return jsonify({
                    'error': 'Transaction not found or no changes made'
                }), 404
        else:
            return jsonify({
                'error': 'Database not available'
            }), 503

    except Exception as e:

        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Error updating transaction',
            'details': str(e)
        }), 500


@bp.route('/api/<bank_code>/transaction/split', methods=['POST'])
@login_required
def split_bank_transaction(bank_code):
    """Split a transaction into multiple transactions"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    try:
        data = request.json
        table = get_bank_table(bank_code)

        original = data.get('original', {})
        splits = data.get('splits', [])
        is_debit = data.get('isDebit', True)

        # Validate input
        if not original or not splits or len(splits) < 2:
            return jsonify({
                'success': False,
                'error': 'Invalid split data. Need original transaction and at least 2 splits.'
            }), 400

        original_id = original.get('id')
        original_date = original.get('date')
        original_desc = original.get('description')
        original_debit = float(original.get('debit', 0) or 0)
        original_credit = float(original.get('credit', 0) or 0)

        # Validate that we have the transaction ID
        if not original_id:
            return jsonify({
                'success': False,
                'error': 'Transaction ID is required for split operation.'
            }), 400

        # Validate amounts
        original_amount = original_debit if is_debit else original_credit
        total_split = sum(float(s.get('amount', 0) or 0) for s in splits)

        if abs(original_amount - total_split) >= 0.01:
            return jsonify({
                'success': False,
                'error': f'Split amounts ({total_split}) do not match original ({original_amount})'
            }), 400

        if not Config.USE_DATABASE:
            return jsonify({'error': 'Database not available'}), 503

        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            conn.autocommit = False

            try:
                # Step 1: Delete the original transaction by ID
                delete_query = f"DELETE FROM {table} WHERE id = %s"
                cursor.execute(delete_query, (original_id,))

                if cursor.rowcount == 0:
                    conn.rollback()
                    return jsonify({
                        'success': False,
                        'error': 'Original transaction not found'
                    }), 404

                # Step 2: Insert split transactions
                insert_query = f"""
                INSERT INTO {table} (
                    transaction_date, transaction_description, client_vendor,
                    category, code, dr_amount, cr_amount, project
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """

                for idx, split in enumerate(splits):
                    split_amount = float(split.get('amount', 0) or 0)
                    split_vendor = split.get('vendor', 'Unknown')
                    split_category = split.get('category', 'Uncategorized')
                    split_project = split.get('project')
                    split_code = split.get('code')

                    # Create unique description for each split
                    split_desc = f"{original_desc} [SPLIT {idx + 1}/{len(splits)}]"

                    # Determine category code if not provided
                    if not split_code:
                        category_codes = {
                            'OFFICE EXPENSES': 'OE', 'FACTORY EXPENSES': 'FE', 'SITE EXPENSES': 'SE',
                            'TRANSPORT EXPENSES': 'TE', 'MATERIAL PURCHASE': 'MP',
                            'DUTIES & TAX': 'DT', 'SALARY AC': 'SA', 'BANK CHARGES': 'BC',
                            'AMOUNT RECEIVED': 'AR', 'UNCATEGORIZED': 'UC'
                        }
                        split_code = category_codes.get(split_category, 'UC')

                    # Set debit/credit based on original
                    if is_debit:
                        dr_amount = split_amount
                        cr_amount = 0.0
                    else:
                        dr_amount = 0.0
                        cr_amount = split_amount

                    cursor.execute(insert_query, (
                        original_date,
                        split_desc,
                        split_vendor,
                        split_category,
                        split_code,
                        dr_amount,
                        cr_amount,
                        split_project
                    ))

                conn.commit()
                cursor.close()

                # Reload bank data cache
                reload_bank_data(bank_code)

                return jsonify({
                    'success': True,
                    'message': f'Transaction split into {len(splits)} parts successfully'
                })

            except Exception as e:
                conn.rollback()
                raise e

    except Exception as e:

        import traceback
        traceback.print_exc()
        return jsonify({
            'error': 'Error splitting transaction',
            'details': str(e)
        }), 500


@bp.route('/api/<bank_code>/download_transactions')
@login_required
def download_bank_transactions(bank_code):
    """Download transactions as Excel for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    try:
        category = request.args.get('category', 'All')
        project = request.args.get('project', None)
        vendor = request.args.get('vendor', None)
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)

        df = get_bank_df(bank_code).copy()

        # Apply multi-select filters
        df = filter_by_category(df, category)
        df = filter_by_date_range(df, start_date, end_date)
        df = filter_by_project(df, project)
        df = filter_by_vendor(df, vendor)

        df_export = df.sort_values('date', ascending=False).copy()
        df_export['Date'] = df_export['date'].dt.strftime('%d-%m-%Y')

        export_columns = [
            'Date', 'Transaction Description', 'Client/Vendor',
            'Category', 'Code', 'DR Amount', 'CR Amount', 'Project'
        ]

        df_final = pd.DataFrame()
        for col in export_columns:
            if col == 'Category':
                df_final[col] = df_export.get('Category', None)
            elif col in df_export.columns:
                df_final[col] = df_export[col]
            else:
                df_final[col] = None

        df_final = sanitize_for_excel(df_final)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_final.to_excel(writer, index=False, sheet_name='Transactions')
            worksheet = writer.sheets['Transactions']
            for idx, col in enumerate(df_final.columns):
                worksheet.column_dimensions[chr(65 + idx)].width = safe_col_width(df_final[col], col)

        output.seek(0)

        bank_name = BANK_CONFIG[bank_code]['name'].replace(' ', '_')
        filename = f"{bank_name}_transactions_{now_ist().strftime('%Y%m%d_%H%M%S')}.xlsx"

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Export failed: {str(e)}'}), 500
