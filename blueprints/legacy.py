"""Legacy (non-bank-scoped) backwards-compat API: /api/upload, /api/summary, etc.

These predate the multi-bank split and operate on the legacy combined frame
(extensions.state.df_global). Kept for backwards compatibility.
"""

import io
import os

import pandas as pd

from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

from config import Config, allowed_file, now_ist
from extensions import db_manager, state
from bank_statement_processor import process_bank_statement
from helpers.formatting import format_indian_number, sanitize_for_excel
from helpers.dataframe import reload_data, get_legacy_df, filter_by_date_range
from helpers.projects import validate_project_value
from auth import login_required

bp = Blueprint('legacy', __name__)


@bp.route('/api/upload', methods=['POST'])
@login_required
def upload_statement():
    """Upload and process bank statement"""
    try:
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']

        # Check if file is selected
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Check if file is allowed
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Only .xlsx and .xls files are allowed'}), 400

        # Secure the filename
        filename = secure_filename(file.filename)
        timestamp = now_ist().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(Config.UPLOAD_FOLDER, filename)

        # Save the file
        file.save(filepath)


        # Process the bank statement

        df = process_bank_statement(filepath)

        # Insert into database if enabled
        if Config.USE_DATABASE:


            # Ensure database is connected
            if not state.db_connected:
                connected = db_manager.connect()
                if connected:
                    state.db_connected = True
                else:
                    return jsonify({
                        'error': 'Database connection failed',
                        'details': 'Could not connect to MySQL database'
                    }), 500

            # Insert transactions
            results = db_manager.insert_transactions_bulk(df)

            # Print results


            # Log the upload
            db_manager.log_upload(
                filename=filename,
                records_processed=results['total'],
                records_inserted=results['inserted'],
                records_duplicated=results['duplicates'],
                status='success' if results['errors'] == 0 else 'partial',
                error_message='; '.join(results['error_messages'][:5]) if results['error_messages'] else None
            )

            # Reload data

            reload_data()


            return jsonify({
                'success': True,
                'message': 'Bank statement processed successfully',
                'filename': filename,
                'stats': {
                    'total': results['total'],
                    'inserted': results['inserted'],
                    'duplicates': results['duplicates'],
                    'errors': results['errors']
                }
            })
        else:
            # Excel mode - save to file
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


@bp.route('/api/upload_history')
@login_required
def get_upload_history():
    """Get recent upload history"""
    if not Config.USE_DATABASE or not state.db_connected:
        return jsonify({'history': []})

    try:
        history = db_manager.get_upload_history(10)
        return jsonify({'history': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/summary')
@login_required
def get_summary():
    """Get summary statistics"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    # Filter data
    df = get_legacy_df().copy()
    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)

    current_balance = float(df['running_balance'].iloc[-1]) if len(df) > 0 else 0
    total_income = float(df['CR Amount'].sum())
    total_expense = float(df['DR Amount'].sum())
    net_cashflow = total_income - total_expense
    expense_ratio = (total_expense / total_income * 100) if total_income > 0 else 0

    # Calculate this period vs previous period (for comparison)
    # Get the most recent month in the filtered data for comparison
    if len(df) > 0:
        current_month = df['month'].max()
        last_month = df[df['month'] < current_month]['month'].max() if len(df[df['month'] < current_month]) > 0 else None

        this_month_df = df[df['month'] == current_month] if current_month else pd.DataFrame()
        last_month_df = df[df['month'] == last_month] if last_month else pd.DataFrame()

        this_month_net = float((this_month_df['CR Amount'].sum() - this_month_df['DR Amount'].sum())) if len(this_month_df) > 0 else 0
        last_month_net = float((last_month_df['CR Amount'].sum() - last_month_df['DR Amount'].sum())) if len(last_month_df) > 0 else 0

        # Biggest category in the filtered period
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


@bp.route('/api/monthly_trend')
@login_required
def get_monthly_trend():
    """Get monthly income/expense trend"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_legacy_df().copy()
    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)

    monthly = df.groupby('month_name').agg({
        'CR Amount': 'sum',
        'DR Amount': 'sum',
        'date': 'first'
    }).reset_index().sort_values('date')

    # Calculate net for each month
    net_values = [(inc - exp) for inc, exp in zip(monthly['CR Amount'].tolist(), monthly['DR Amount'].tolist())]

    # Find highest expense month
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


@bp.route('/api/category_breakdown')
@login_required
def get_category_breakdown():
    """Get expense breakdown by broader category"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_legacy_df().copy()
    expense_df = df[df['DR Amount'] > 0]

    if category != 'All':
        expense_df = expense_df[expense_df['Category'] == category]
    expense_df = filter_by_date_range(expense_df, start_date, end_date)

    category_totals = expense_df.groupby('Category')['DR Amount'].sum().sort_values(ascending=False)

    # Find top category
    top_category = category_totals.index[0] if len(category_totals) > 0 else None
    top_category_amount = float(category_totals.iloc[0]) if len(category_totals) > 0 else 0
    total_expenses = float(category_totals.sum())
    top_category_pct = (top_category_amount / total_expenses * 100) if total_expenses > 0 else 0

    return jsonify({
        'categories': category_totals.index.tolist(),
        'amounts': category_totals.values.tolist(),
        'top_category': top_category,
        'top_category_amount': top_category_amount,
        'top_category_amount_formatted': format_indian_number(top_category_amount),
        'top_category_pct': round(top_category_pct, 1)
    })


@bp.route('/api/running_balance')
@login_required
def get_running_balance():
    """Get running balance over time"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_legacy_df().copy()
    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)

    # Sample data for performance (take every 5th point if more than 100 points)
    if len(df) > 100:
        df_sample = df.iloc[::5].copy()
    else:
        df_sample = df.copy()

    # Calculate lowest and peak balance
    lowest_balance = float(df['running_balance'].min()) if len(df) > 0 else 0
    peak_balance = float(df['running_balance'].max()) if len(df) > 0 else 0
    lowest_date_idx = df['running_balance'].idxmin() if len(df) > 0 else None
    peak_date_idx = df['running_balance'].idxmax() if len(df) > 0 else None

    lowest_date = df.loc[lowest_date_idx, 'date'].strftime('%d %b %Y') if lowest_date_idx is not None else None
    peak_date = df.loc[peak_date_idx, 'date'].strftime('%d %b %Y') if peak_date_idx is not None else None

    # Calculate last 30 days for sparkline
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


@bp.route('/api/top_vendors')
@login_required
def get_top_vendors():
    """Get top 10 vendors by expense"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_legacy_df().copy()
    expense_df = df[df['DR Amount'] > 0]

    if category != 'All':
        expense_df = expense_df[expense_df['Category'] == category]
    expense_df = filter_by_date_range(expense_df, start_date, end_date)

    vendor_totals = expense_df.groupby('Client/Vendor')['DR Amount'].sum().sort_values(ascending=False).head(10)

    # Find top vendor
    top_vendor = vendor_totals.index[0] if len(vendor_totals) > 0 else None
    top_vendor_amount = float(vendor_totals.iloc[0]) if len(vendor_totals) > 0 else 0

    # Calculate threshold for high spend (top 20% of vendors)
    threshold = float(vendor_totals.quantile(0.8)) if len(vendor_totals) > 0 else 0

    return jsonify({
        'vendors': vendor_totals.index.tolist(),
        'amounts': vendor_totals.values.tolist(),
        'top_vendor': top_vendor,
        'top_vendor_amount': top_vendor_amount,
        'top_vendor_amount_formatted': format_indian_number(top_vendor_amount),
        'threshold': threshold
    })


@bp.route('/api/categories')
@login_required
def get_categories():
    """Get list of all categories"""
    categories = ['All'] + sorted(get_legacy_df()['Category'].str.strip().unique().tolist())
    return jsonify({'categories': categories})


@bp.route('/api/months')
@login_required
def get_months():
    """Get list of all available months"""
    # Create unique pairs of (month_code, month_name) sorted by month_code
    pairs = get_legacy_df()[['month', 'month_name']].drop_duplicates().sort_values('month')

    months_data = [{'value': 'All', 'label': 'All'}]
    for _, row in pairs.iterrows():
        months_data.append({
            'value': row['month'],
            'label': row['month_name']
        })

    return jsonify({'months_data': months_data})


@bp.route('/api/date_range')
@login_required
def get_date_range():
    """Get the min and max dates available in the data"""
    legacy_df = get_legacy_df()
    if len(legacy_df) == 0:
        return jsonify({
            'min_date': None,
            'max_date': None
        })

    min_date = legacy_df['date'].min()
    max_date = legacy_df['date'].max()

    return jsonify({
        'min_date': min_date.strftime('%Y-%m-%d') if pd.notna(min_date) else None,
        'max_date': max_date.strftime('%Y-%m-%d') if pd.notna(max_date) else None
    })


@bp.route('/api/transactions')
@login_required
def get_transactions():
    """Get all transactions"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    limit = int(request.args.get('limit', 10000))  # Very high limit to get all

    # New parameters for sorting and searching
    sort_by = request.args.get('sort_by', 'date')   # date, dr_amount, cr_amount
    sort_order = request.args.get('sort_order', 'desc') # asc, desc
    search_query = request.args.get('search', '').lower()

    df = get_legacy_df().copy()
    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)

    # Apply Search
    if search_query:
        # Search in description, vendor, and category
        df = df[
            df['Transaction Description'].astype(str).str.lower().str.contains(search_query, na=False) |
            df['Client/Vendor'].astype(str).str.lower().str.contains(search_query, na=False) |
            df['Category'].astype(str).str.lower().str.contains(search_query, na=False)
        ]

    # Apply Sorting
    ascending = (sort_order == 'asc')

    if sort_by == 'dr_amount':
        # Secondary sort by date
        df_sorted = df.sort_values(['DR Amount', 'date'], ascending=[ascending, False]).head(limit)
    elif sort_by == 'cr_amount':
        df_sorted = df.sort_values(['CR Amount', 'date'], ascending=[ascending, False]).head(limit)
    else:
        # Default to date sort
        df_sorted = df.sort_values('date', ascending=ascending).head(limit)

    transactions = []
    for idx, row in df_sorted.iterrows():
        transactions.append({
            'id': int(idx) if hasattr(idx, '__int__') else idx,  # Transaction ID for editing
            'date': row['date'].strftime('%d %b %Y'),
            'date_raw': row['date'].strftime('%Y-%m-%d'),
            'description': row['Transaction Description'],
            'vendor': row['Client/Vendor'],
            'category': row['Category'],
            'code': row.get('Code', ''),
            'dr_amount': float(row['DR Amount']),
            'dr_amount_formatted': format_indian_number(row['DR Amount']) if row['DR Amount'] > 0 else '',
            'cr_amount': float(row['CR Amount']),
            'cr_amount_formatted': format_indian_number(row['CR Amount']) if row['CR Amount'] > 0 else '',
            'net': float(row['net']),
            'net_formatted': format_indian_number(row['net']),
            'project': row.get('Project', ''),
            'dd': row.get('DD', ''),
            'notes': row.get('Notes', '')
        })

    return jsonify({'transactions': transactions})


@bp.route('/api/transaction/update', methods=['POST'])
@login_required
def update_transaction():
    """Update a transaction's editable fields"""
    try:
        data = request.json

        # Required fields
        transaction_id = data.get('id')
        transaction_date = data.get('date')
        description = data.get('description')

        # Support both field names - use proper fallback for zero values
        dr_amount = data.get('debit') if data.get('debit') is not None else data.get('dr_amount', 0)
        cr_amount = data.get('credit') if data.get('credit') is not None else data.get('cr_amount', 0)
        # Ensure amounts are never None (would cause WHERE clause to fail)
        dr_amount = float(dr_amount) if dr_amount is not None else 0.0
        cr_amount = float(cr_amount) if cr_amount is not None else 0.0

        # Editable fields - normalize to uppercase and trim
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
                'error': 'Missing required fields',
                'details': f'date={transaction_date}, description={description}'
            }), 400

        # Update in database
        if Config.USE_DATABASE:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                # Prefer matching by primary key id (unambiguous, and robust to the
                # DATETIME transaction_date column). Fall back to the legacy value
                # match only when no id is supplied.
                if transaction_id is not None:
                    query = """
                    UPDATE transactions
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
                    query = """
                    UPDATE transactions
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
                # Reload data
                reload_data()

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


@bp.route('/api/download_transactions')
@login_required
def download_transactions():
    """Download transactions as Excel - matches original table schema"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_legacy_df().copy()
    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)

    # Sort and prepare for export
    df_export = df.sort_values('date', ascending=False).copy()

    # Format date as DD-MM-YYYY to match original format
    df_export['Date'] = df_export['date'].dt.strftime('%d-%m-%Y')

    # Select columns in the simplified schema
    export_columns = [
        'Date',
        'Transaction Description',
        'Client/Vendor',
        'Category',
        'Code',
        'DR Amount',
        'CR Amount',
        'Project'
    ]

    # Create export dataframe with only existing columns
    df_final = pd.DataFrame()
    for col in export_columns:
        if col == 'Category':
            # Use Category field
            df_final[col] = df_export.get('Category', None)
        elif col == 'Date':
            df_final[col] = df_export['Date']
        elif col in df_export.columns:
            df_final[col] = df_export[col]
        else:
            df_final[col] = None

    df_final = sanitize_for_excel(df_final)

    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_final.to_excel(writer, index=False, sheet_name='Transactions')

        # Auto-adjust column widths
        worksheet = writer.sheets['Transactions']
        for idx, col in enumerate(df_final.columns):
            col_max = df_final[col].astype(str).apply(len).max() if not df_final.empty else 0
            max_length = max(col_max if pd.notna(col_max) else 0, len(str(col))) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)

    output.seek(0)

    filename = f"transactions_{now_ist().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@bp.route('/api/insights')
@login_required
def get_insights():
    """Get key insights"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_legacy_df().copy()
    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)

    # Calculate average monthly expense
    monthly_expenses = df.groupby('month')['DR Amount'].sum()
    avg_monthly_expense = float(monthly_expenses.mean()) if len(monthly_expenses) > 0 else 0

    # Expense trend (last 3 months)
    if len(monthly_expenses) >= 3:
        last_3_months = monthly_expenses.tail(3)
        first_month = last_3_months.iloc[0]
        last_month = last_3_months.iloc[-1]
        trend_pct = ((last_month - first_month) / first_month * 100) if first_month > 0 else 0
        trend_direction = 'increasing' if trend_pct > 0 else 'decreasing' if trend_pct < 0 else 'stable'
    else:
        trend_pct = 0
        trend_direction = 'insufficient data'

    # Average transaction size
    expense_df = df[df['DR Amount'] > 0]
    avg_transaction_size = float(expense_df['DR Amount'].mean()) if len(expense_df) > 0 else 0

    # Peak spending day of week
    expense_df_with_day = expense_df.copy()
    expense_df_with_day['day_of_week'] = expense_df_with_day['date'].dt.day_name()
    day_expenses = expense_df_with_day.groupby('day_of_week')['DR Amount'].sum()
    peak_day = day_expenses.idxmax() if len(day_expenses) > 0 else None
    peak_day_amount = float(day_expenses.max()) if len(day_expenses) > 0 else 0

    # Cash flow velocity (transactions per month)
    total_months = len(df['month'].unique())
    transactions_per_month = len(df) / total_months if total_months > 0 else 0

    return jsonify({
        'avg_monthly_expense': avg_monthly_expense,
        'avg_monthly_expense_formatted': format_indian_number(avg_monthly_expense),
        'expense_trend_pct': round(trend_pct, 1),
        'expense_trend_direction': trend_direction,
        'avg_transaction_size': avg_transaction_size,
        'avg_transaction_size_formatted': format_indian_number(avg_transaction_size),
        'peak_day': peak_day,
        'peak_day_amount': peak_day_amount,
        'peak_day_amount_formatted': format_indian_number(peak_day_amount),
        'cashflow_velocity': round(transactions_per_month, 0),
        'total_months': total_months
    })
