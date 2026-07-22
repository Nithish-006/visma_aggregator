"""Project Summary: cross-bank consolidated view page + /api/project-summary/*.

The Excel export route lives here too but delegates to
reports.project_summary_export.
"""

import traceback

import pandas as pd

from flask import Blueprint, render_template, request, jsonify

from config import VALID_BANK_CODES, now_ist
from extensions import db_manager
import salary_api
from helpers.formatting import format_indian_number
from helpers.bankdata import get_bank_df
from helpers.dataframe import (
    filter_by_date_range, filter_by_category, filter_by_vendor, robust_filter_by_project,
)
from helpers.projects import (
    build_smart_project_groups, parse_project_selection,
)
from helpers.bill_reconcile import (
    build_bill_vendor_index, is_unbilled_material_purchase,
)
# project_summary consumes the projects blueprint's PO/payments resolver.
# One-directional: blueprints.projects never imports project_summary.
from auth import login_required

bp = Blueprint('project_summary', __name__)


@bp.route('/project-summary')
@login_required
def project_summary():
    """Project Summary page - consolidated view across all banks"""
    return render_template('project_summary.html')


def _labour_monthly_for_project(project, start_date, end_date):
    """Per-month labour salary for the open canonical project, from the salary API.

    Returns the salary_api.get_labour_summary_for_project shape. When the
    selection carries no canonical id (free-text / no project), returns a benign
    empty-but-available stub so the UI shows its "no attendance" state, not an error.
    """
    ids, _ = parse_project_selection(project)
    if not ids:
        return {'available': True, 'monthly': [], 'total_cost': 0.0,
                'total_days': 0, 'total_ot_hours': 0.0, 'project_names': []}
    return salary_api.get_labour_summary_for_project(
        ids[0], project_display=project, start_date=start_date, end_date=end_date)


@bp.route('/api/project-summary/combined')
@login_required
def get_project_summary_combined():
    """Get combined transaction data from all banks with filters"""
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    category = request.args.get('category', None)
    vendor = request.args.get('vendor', None)

    # Labour salary (monthly) for the open project — sourced from the salary API.
    labour_monthly = _labour_monthly_for_project(project, start_date, end_date)

    combined_rows = []

    for bank_code in VALID_BANK_CODES:
        df = get_bank_df(bank_code).copy()
        if df.empty:
            continue

        df = filter_by_date_range(df, start_date, end_date)
        df = robust_filter_by_project(df, project)
        df = filter_by_category(df, category)
        df = filter_by_vendor(df, vendor)

        if df.empty:
            continue

        df['bank'] = bank_code
        combined_rows.append(df)

    if not combined_rows:
        return jsonify({
            'summary': {
                'total_income': 0, 'total_income_formatted': '₹0',
                'total_bank_transfer': 0, 'total_bank_transfer_formatted': '₹0',
                'total_expense': 0, 'total_expense_formatted': '₹0',
                'total_transactions': 0,
            },
            'category_breakdown': [],
            'labour_monthly': labour_monthly,
            'vendor_breakdown': [],
            'transactions': [],
            'bank_transactions': {}
        })

    combined = pd.concat(combined_rows, ignore_index=True)

    # Summary — Income = KVB credits only, Bank Transfer = Axis credits only
    kvb_df = combined[combined['bank'] == 'kvb']
    axis_df = combined[combined['bank'] == 'axis']
    total_income = float(kvb_df['CR Amount'].sum()) if not kvb_df.empty else 0
    total_bank_transfer = float(axis_df['CR Amount'].sum()) if not axis_df.empty else 0
    total_expense = float(combined['DR Amount'].sum())

    summary = {
        'total_income': total_income,
        'total_income_formatted': format_indian_number(total_income),
        'total_bank_transfer': total_bank_transfer,
        'total_bank_transfer_formatted': format_indian_number(total_bank_transfer),
        'total_expense': total_expense,
        'total_expense_formatted': format_indian_number(total_expense),
        'total_transactions': len(combined),
    }

    # Category breakdown (expenses only)
    expense_df = combined[combined['DR Amount'] > 0]
    category_breakdown = []
    if not expense_df.empty:
        cat_totals = expense_df.groupby('Category')['DR Amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
        total_exp = float(cat_totals['sum'].sum())
        for cat_name, row in cat_totals.iterrows():
            amt = float(row['sum'])
            pct = (amt / total_exp * 100) if total_exp > 0 else 0
            category_breakdown.append({
                'category': cat_name,
                'amount': amt,
                'amount_formatted': format_indian_number(amt),
                'count': int(row['count']),
                'percentage': round(pct, 1)
            })

    # NOTE: the old stem-grouped "project breakdown" was removed. Labour
    # salary is fetched up front via _labour_monthly_for_project() and
    # returned to the page as `labour_monthly` (per-month, for this project).


    # Vendor breakdown (top vendors by expense)
    vendor_col = 'Client/Vendor' if 'Client/Vendor' in combined.columns else 'client_vendor'
    vendor_breakdown = []
    if vendor_col in combined.columns and not expense_df.empty:
        vendor_totals = expense_df.groupby(vendor_col)['DR Amount'].agg(['sum', 'count']).sort_values('sum', ascending=False).head(20)
        total_vendor_exp = float(vendor_totals['sum'].sum())
        for vendor_name, row in vendor_totals.iterrows():
            v_amt = float(row['sum'])
            v_pct = (v_amt / total_vendor_exp * 100) if total_vendor_exp > 0 else 0
            vendor_breakdown.append({
                'vendor': str(vendor_name) if vendor_name and str(vendor_name) != 'nan' else 'Unknown',
                'amount': v_amt,
                'amount_formatted': format_indian_number(v_amt),
                'count': int(row['count']),
                'percentage': round(v_pct, 1)
            })

    # Per-bank transactions (separate lists for side-by-side display)
    bank_transactions = {}
    for bank_code in VALID_BANK_CODES:
        bank_df = combined[combined['bank'] == bank_code]
        if bank_df.empty:
            bank_transactions[bank_code] = []
            continue
        bank_recent = bank_df.sort_values('date', ascending=False).head(50)
        bank_txn_list = []
        for _, row in bank_recent.iterrows():
            bank_txn_list.append({
                'date': row['date'].strftime('%Y-%m-%d') if pd.notna(row['date']) else '',
                'description': str(row.get('Description', row.get('transaction_description', ''))),
                'vendor': str(row.get('Client/Vendor', row.get('client_vendor', 'Unknown'))),
                'category': str(row.get('Category', 'Uncategorized')),
                'dr_amount': float(row.get('DR Amount', 0)),
                'cr_amount': float(row.get('CR Amount', 0)),
                'dr_formatted': format_indian_number(float(row.get('DR Amount', 0))) if float(row.get('DR Amount', 0)) > 0 else '',
                'cr_formatted': format_indian_number(float(row.get('CR Amount', 0))) if float(row.get('CR Amount', 0)) > 0 else '',
                'project': str(row.get('Project', row.get('project', ''))) if pd.notna(row.get('Project', row.get('project', ''))) else '',
                'bank': bank_code
            })
        bank_transactions[bank_code] = bank_txn_list

    # Recent transactions (last 50 for combined table display)
    recent = combined.sort_values('date', ascending=False).head(50)
    transactions_list = []
    for _, row in recent.iterrows():
        transactions_list.append({
            'date': row['date'].strftime('%Y-%m-%d') if pd.notna(row['date']) else '',
            'description': str(row.get('Description', row.get('transaction_description', ''))),
            'vendor': str(row.get('Client/Vendor', row.get('client_vendor', 'Unknown'))),
            'category': str(row.get('Category', 'Uncategorized')),
            'dr_amount': float(row.get('DR Amount', 0)),
            'cr_amount': float(row.get('CR Amount', 0)),
            'dr_formatted': format_indian_number(float(row.get('DR Amount', 0))) if float(row.get('DR Amount', 0)) > 0 else '',
            'cr_formatted': format_indian_number(float(row.get('CR Amount', 0))) if float(row.get('CR Amount', 0)) > 0 else '',
            'project': str(row.get('Project', row.get('project', ''))) if pd.notna(row.get('Project', row.get('project', ''))) else '',
            'bank': row.get('bank', '')
        })

    return jsonify({
        'summary': summary,
        'category_breakdown': category_breakdown,
        'labour_monthly': labour_monthly,
        'vendor_breakdown': vendor_breakdown,
        'transactions': transactions_list,
        'bank_transactions': bank_transactions
    })


@bp.route('/api/project-summary/bank-transactions')
@login_required
def get_project_summary_bank_transactions():
    """Get paginated bank transactions for a specific bank with filters"""
    bank_code = request.args.get('bank_code', 'axis')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 15))
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    category = request.args.get('category', None)
    vendor = request.args.get('vendor', None)

    if bank_code not in VALID_BANK_CODES:
        return jsonify({'transactions': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 0})

    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({'transactions': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 0})

    df = filter_by_date_range(df, start_date, end_date)
    df = robust_filter_by_project(df, project)
    df = filter_by_category(df, category)
    df = filter_by_vendor(df, vendor)

    df = df.sort_values('date', ascending=False)
    total = len(df)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 0

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_df = df.iloc[start_idx:end_idx]

    # Cross-check MATERIAL PURCHASE debits against purchase bills (kvb only).
    bill_index = build_bill_vendor_index(
        db_manager.get_purchase_bill_vendors_by_project()) if bank_code == 'kvb' else {}

    transactions = []
    for _, row in page_df.iterrows():
        dr_amount = float(row.get('DR Amount', 0))
        vendor = str(row.get('Client/Vendor', row.get('client_vendor', 'Unknown')))
        category = str(row.get('Category', 'Uncategorized'))
        project = str(row.get('Project', row.get('project', ''))) if pd.notna(row.get('Project', row.get('project', ''))) else ''
        no_bill_warning = dr_amount > 0 and is_unbilled_material_purchase(
            category, project, vendor, bill_index, bank_code)
        transactions.append({
            'date': row['date'].strftime('%Y-%m-%d') if pd.notna(row['date']) else '',
            'description': str(row.get('Description', row.get('transaction_description', ''))),
            'vendor': vendor,
            'category': category,
            'dr_amount': dr_amount,
            'cr_amount': float(row.get('CR Amount', 0)),
            'dr_formatted': format_indian_number(dr_amount) if dr_amount > 0 else '',
            'cr_formatted': format_indian_number(float(row.get('CR Amount', 0))) if float(row.get('CR Amount', 0)) > 0 else '',
            'project': project,
            'no_bill_warning': no_bill_warning
        })

    return jsonify({
        'transactions': transactions,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@bp.route('/api/project-summary/vendors')
@login_required
def get_project_summary_vendors():
    """Get paginated vendor breakdown across all banks with filters"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 15))
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    category = request.args.get('category', None)
    vendor = request.args.get('vendor', None)

    combined_rows = []
    for bank_code in VALID_BANK_CODES:
        df = get_bank_df(bank_code).copy()
        if df.empty:
            continue
        df = filter_by_date_range(df, start_date, end_date)
        df = robust_filter_by_project(df, project)
        df = filter_by_category(df, category)
        df = filter_by_vendor(df, vendor)
        if not df.empty:
            combined_rows.append(df)

    if not combined_rows:
        return jsonify({'vendors': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 0})

    combined = pd.concat(combined_rows, ignore_index=True)
    expense_df = combined[combined['DR Amount'] > 0]

    if expense_df.empty:
        return jsonify({'vendors': [], 'total': 0, 'page': page, 'per_page': per_page, 'total_pages': 0})

    vendor_col = 'Client/Vendor' if 'Client/Vendor' in expense_df.columns else 'client_vendor'
    vendor_totals = expense_df.groupby(vendor_col)['DR Amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
    total_exp = float(vendor_totals['sum'].sum())

    total = len(vendor_totals)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 0

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_vendors = vendor_totals.iloc[start_idx:end_idx]

    vendors = []
    for vendor_name, row in page_vendors.iterrows():
        v_amt = float(row['sum'])
        v_pct = (v_amt / total_exp * 100) if total_exp > 0 else 0
        vendors.append({
            'vendor': str(vendor_name) if vendor_name and str(vendor_name) != 'nan' else 'Unknown',
            'amount': v_amt,
            'amount_formatted': format_indian_number(v_amt),
            'count': int(row['count']),
            'percentage': round(v_pct, 1)
        })

    return jsonify({
        'vendors': vendors,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@bp.route('/api/project-summary/project-cards')
@login_required
def get_project_summary_project_cards():
    """Registry-fed landing cards for the project-summary page.

    One card per canonical registry entry. Bank totals are matched by the
    "<id> -" project tag, with an exact registry-name fallback for rows that
    lack the prefix (see below). No stem fuzz, so free-text variants are still
    kept apart. Income = credits, expense = debits, across banks.
    """
    db_manager.ensure_projects_table()
    registry = db_manager.list_projects()

    # Exact-name fallback for the id-prefix match below. A row tagged with a bare
    # project name and no "<id> -" prefix (legacy data, or a tag the statement
    # parser assigned) would otherwise be silently dropped from every card. We
    # rescue it only on an EXACT match to a registry stem or display name — never
    # a fuzzy stem — so unrelated free-text variants are still kept apart.
    name_to_id = {}
    for p in registry:
        name_to_id[str(p['stem_name']).strip().lower()] = p['id']
        name_to_id[str(p['display']).strip().lower()] = p['id']

    totals = {}  # project id -> {'income', 'expense', 'count'}
    for bank_code in VALID_BANK_CODES:
        df = get_bank_df(bank_code)
        if df.empty:
            continue
        col = 'Project' if 'Project' in df.columns else 'project'
        if col not in df.columns:
            continue
        raw = df[col].astype(str).str.strip()
        # Primary: the canonical "<id> -" tag prefix.
        pid = pd.to_numeric(raw.str.extract(r'^(\d+)\s*-', expand=False), errors='coerce')
        # Fallback: rows without the prefix whose value exactly names a project.
        missing = pid.isna()
        if missing.any():
            pid.loc[missing] = raw[missing].str.lower().map(name_to_id)
        sub = df[pid.notna()]
        if sub.empty:
            continue
        grouped = sub.groupby(pid[pid.notna()].astype(int)).agg(
            income=('CR Amount', 'sum'),
            expense=('DR Amount', 'sum'),
            count=('DR Amount', 'size'),
        )
        for pid, row in grouped.iterrows():
            t = totals.setdefault(int(pid), {'income': 0.0, 'expense': 0.0, 'count': 0})
            t['income'] += float(row['income'])
            t['expense'] += float(row['expense'])
            t['count'] += int(row['count'])

    cards = []
    for p in registry:
        t = totals.get(p['id'], {'income': 0.0, 'expense': 0.0, 'count': 0})
        cards.append({
            'id': p['id'],
            'stem_name': p['stem_name'],
            'display': p['display'],
            'project_type': p.get('project_type', 'project'),
            'is_inactive': bool(p.get('is_inactive', False)),
            'income': t['income'],
            'income_formatted': format_indian_number(t['income']),
            'expense': t['expense'],
            'expense_formatted': format_indian_number(t['expense']),
            'txn_count': t['count'],
        })
    return jsonify({'projects': cards})


@bp.route('/api/project-summary/projects')
@login_required
def get_project_summary_projects():
    """Get list of unique projects, categories, and vendors across all banks"""
    all_projects = set()
    all_categories = set()
    all_vendors = set()

    for bank_code in VALID_BANK_CODES:
        df = get_bank_df(bank_code)
        if df.empty:
            continue

        project_col = 'Project' if 'Project' in df.columns else 'project'
        if project_col in df.columns:
            raw_names = [str(p) for p in df[project_col].dropna().unique()
                         if str(p).strip() and str(p).lower() != 'nan']
            stem_groups = build_smart_project_groups(raw_names, [])
            all_projects.update(stem.upper() for stem in stem_groups.keys())

        if 'Category' in df.columns:
            cats = df['Category'].dropna().unique()
            all_categories.update([str(c) for c in cats if str(c) != 'nan'])

        vendor_col = 'Client/Vendor' if 'Client/Vendor' in df.columns else 'client_vendor'
        if vendor_col in df.columns:
            vendors = df[vendor_col].dropna().unique()
            all_vendors.update([str(v) for v in vendors if str(v) != 'nan' and str(v) != 'Unknown'])

    return jsonify({
        'projects': sorted(list(all_projects)),
        'categories': sorted(list(all_categories)),
        'vendors': sorted(list(all_vendors))
    })


@bp.route('/api/project-summary/filter-options')
@login_required
def get_project_summary_filter_options():
    """Get dynamic filter options constrained by current filters (exclude-field pattern)"""
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    category = request.args.get('category', None)
    vendor = request.args.get('vendor', None)

    def get_filtered_df(exclude_field):
        """Get combined df across all banks, applying all filters except the excluded one"""
        rows = []
        for bank_code in VALID_BANK_CODES:
            df = get_bank_df(bank_code).copy()
            if df.empty:
                continue
            df = filter_by_date_range(df, start_date, end_date)
            if exclude_field != 'project':
                df = robust_filter_by_project(df, project)
            if exclude_field != 'category':
                df = filter_by_category(df, category)
            if exclude_field != 'vendor':
                df = filter_by_vendor(df, vendor)
            if not df.empty:
                rows.append(df)
        if not rows:
            return pd.DataFrame()
        return pd.concat(rows, ignore_index=True)

    # Projects: filtered by date, category, vendor (not project itself)
    # Return only cleaned stem-grouped project names (same as project breakdown)
    proj_df = get_filtered_df('project')
    all_projects = set()
    if not proj_df.empty:
        project_col = 'Project' if 'Project' in proj_df.columns else 'project'
        if project_col in proj_df.columns:
            raw_names = [str(p) for p in proj_df[project_col].dropna().unique()
                         if str(p).strip() and str(p).lower() != 'nan']
            stem_groups = build_smart_project_groups(raw_names, [])
            all_projects = {stem.upper() for stem in stem_groups.keys()}

    # Categories: filtered by date, project, vendor (not category itself)
    cat_df = get_filtered_df('category')
    all_categories = set()
    if not cat_df.empty:
        if 'Category' in cat_df.columns:
            vals = cat_df['Category'].dropna().unique()
            all_categories.update([str(c) for c in vals if str(c) != 'nan'])

    # Vendors: filtered by date, project, category (not vendor itself)
    vend_df = get_filtered_df('vendor')
    all_vendors = set()
    if not vend_df.empty:
        vendor_col = 'Client/Vendor' if 'Client/Vendor' in vend_df.columns else 'client_vendor'
        if vendor_col in vend_df.columns:
            vals = vend_df[vendor_col].dropna().unique()
            all_vendors.update([str(v) for v in vals if str(v) != 'nan' and str(v) != 'Unknown'])

    return jsonify({
        'projects': sorted(list(all_projects)),
        'categories': sorted(list(all_categories)),
        'vendors': sorted(list(all_vendors))
    })


@bp.route('/api/project-summary/bills')
@login_required
def get_project_summary_bills():
    """Get bills for project summary with filters and pagination"""
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    vendor = request.args.get('vendor', None)
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 15))

    try:
        bills, total, summary = db_manager.get_bills_for_project_summary(
            start_date=start_date,
            end_date=end_date,
            project=project,
            vendor=vendor,
            page=page,
            per_page=per_page
        )
        return jsonify({
            'bills': bills,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total > 0 else 0,
            'summary': summary
        })
    except Exception as e:
        print(f"[!] Bills fetch error: {e}")
        return jsonify({
            'bills': [],
            'total': 0,
            'page': page,
            'per_page': per_page,
            'total_pages': 0,
            'summary': {'total_amount': 0, 'total_gst': 0}
        })


@bp.route('/api/project-summary/sales-bills')
@login_required
def get_project_summary_sales_bills():
    """Get sales bills for project summary with filters and pagination"""
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    vendor = request.args.get('vendor', None)
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 15))

    try:
        bills, total, summary = db_manager.get_sales_bills_for_project_summary(
            start_date=start_date,
            end_date=end_date,
            project=project,
            vendor=vendor,
            page=page,
            per_page=per_page
        )
        return jsonify({
            'bills': bills,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total > 0 else 0,
            'summary': summary
        })
    except Exception as e:
        print(f"[!] Sales bills fetch error: {e}")
        return jsonify({
            'bills': [],
            'total': 0,
            'page': page,
            'per_page': per_page,
            'total_pages': 0,
            'summary': {'total_amount': 0, 'total_gst': 0}
        })


@bp.route('/api/project-summary/date-range')
@login_required
def get_project_summary_date_range():
    """Get the default date range for the project-summary page.

    Always returns 2026-01-01 .. today, regardless of what dates the bank
    dataframes contain. This is the post-cutover default; users can still
    pick narrower or earlier ranges manually.
    """
    today = now_ist().strftime('%Y-%m-%d')
    return jsonify({
        'min_date': '2026-01-01',
        'max_date': today,
    })


# The Excel export body lives in reports.project_summary_export (it was ~1290
# lines); this route is a thin delegator.
from reports.project_summary_export import export_project_summary as _build_export


@bp.route('/api/project-summary/export')
@login_required
def export_project_summary():
    """Export professional project summary report as multi-tab Excel."""
    return _build_export()
