from flask import Flask, render_template, jsonify, request, send_file
import pandas as pd
import json
import io
from datetime import datetime

app = Flask(__name__)

# Load data function
def load_financial_data():
    """Load and preprocess financial data"""
    df = pd.read_excel('APR_TO_DEC_2025_AGGREGATED_FINAL_WITH_CODE.xlsx')

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

    # Derived fields
    df['month_name'] = df['date'].dt.strftime('%B %Y')
    df['month'] = df['date'].dt.to_period('M').astype(str)
    df['net'] = df['CR Amount'] - df['DR Amount']
    df = df.sort_values('date')
    df['running_balance'] = df['net'].cumsum()

    # Clean categories
    df['Broader Category'] = df['Broader Category'].fillna('Uncategorized')
    df['Category'] = df['Category'].fillna('Uncategorized')
    df['Client/Vendor'] = df['Client/Vendor'].fillna('Unknown')

    return df

# Load data at startup
df_global = load_financial_data()

# Helper function to parse month filter
def parse_month_filter(month_filter):
    """Parse month filter - handle single or multiple months"""
    if not month_filter or month_filter == 'All':
        return ['All']
    if ',' in month_filter:
        return [m.strip() for m in month_filter.split(',')]
    return [month_filter]

# Helper function to filter dataframe by months
def filter_by_months(df, month_list):
    """Filter dataframe by list of months"""
    if month_list == ['All']:
        return df
    return df[df['month'].isin(month_list)]

def format_indian_number(amount):
    """Format number in Indian system"""
    if pd.isna(amount) or amount == 0:
        return "₹0"

    abs_amount = abs(amount)
    sign = "-" if amount < 0 else ""

    if abs_amount >= 10000000:  # Crore
        return f"{sign}₹{abs_amount/10000000:.2f} Cr"
    elif abs_amount >= 100000:  # Lakh
        return f"{sign}₹{abs_amount/100000:.2f} L"
    elif abs_amount >= 1000:  # Thousand
        return f"{sign}₹{abs_amount/1000:.2f} K"
    else:
        return f"{sign}₹{abs_amount:,.0f}"

@app.route('/')
def index():
    """Render main dashboard page"""
    return render_template('index.html')

@app.route('/api/summary')
def get_summary():
    """Get summary statistics"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')

    # Handle multiple months
    if month_filter and month_filter != 'All':
        if ',' in month_filter:
            month_list = [m.strip() for m in month_filter.split(',')]
        else:
            month_list = [month_filter]
    else:
        month_list = ['All']

    # Filter data
    df = df_global.copy()
    if category != 'All':
        df = df[df['Broader Category'] == category]
    if month_list != ['All']:
        df = df[df['month'].isin(month_list)]

    current_balance = float(df['running_balance'].iloc[-1]) if len(df) > 0 else 0
    total_income = float(df['CR Amount'].sum())
    total_expense = float(df['DR Amount'].sum())
    net_cashflow = total_income - total_expense
    expense_ratio = (total_expense / total_income * 100) if total_income > 0 else 0

    # Calculate this month vs last month
    if month_filter == 'All':
        # Get current month (most recent month in data)
        current_month = df['month'].max()
        last_month = df[df['month'] < current_month]['month'].max() if len(df[df['month'] < current_month]) > 0 else None

        this_month_df = df[df['month'] == current_month] if current_month else pd.DataFrame()
        last_month_df = df[df['month'] == last_month] if last_month else pd.DataFrame()

        this_month_net = float((this_month_df['CR Amount'].sum() - this_month_df['DR Amount'].sum())) if len(this_month_df) > 0 else 0
        last_month_net = float((last_month_df['CR Amount'].sum() - last_month_df['DR Amount'].sum())) if len(last_month_df) > 0 else 0

        # Biggest category this month
        this_month_expenses = this_month_df[this_month_df['DR Amount'] > 0] if len(this_month_df) > 0 else pd.DataFrame()
        if len(this_month_expenses) > 0:
            biggest_category = this_month_expenses.groupby('Broader Category')['DR Amount'].sum().idxmax()
            biggest_category_amount = float(this_month_expenses.groupby('Broader Category')['DR Amount'].sum().max())
        else:
            biggest_category = None
            biggest_category_amount = 0
    else:
        # If specific month selected, compare with previous month
        month_df = df[df['month'] == month_filter]
        prev_month = df[df['month'] < month_filter]['month'].max() if len(df[df['month'] < month_filter]) > 0 else None
        prev_month_df = df[df['month'] == prev_month] if prev_month else pd.DataFrame()

        this_month_net = float((month_df['CR Amount'].sum() - month_df['DR Amount'].sum())) if len(month_df) > 0 else 0
        last_month_net = float((prev_month_df['CR Amount'].sum() - prev_month_df['DR Amount'].sum())) if len(prev_month_df) > 0 else 0

        month_expenses = month_df[month_df['DR Amount'] > 0] if len(month_df) > 0 else pd.DataFrame()
        if len(month_expenses) > 0:
            biggest_category = month_expenses.groupby('Broader Category')['DR Amount'].sum().idxmax()
            biggest_category_amount = float(month_expenses.groupby('Broader Category')['DR Amount'].sum().max())
        else:
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
        'selected_months': month_list if month_list != ['All'] else ['All'],
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

@app.route('/api/monthly_trend')
def get_monthly_trend():
    """Get monthly income/expense trend"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')

    month_list = parse_month_filter(month_filter)

    df = df_global.copy()
    if category != 'All':
        df = df[df['Broader Category'] == category]
    df = filter_by_months(df, month_list)

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

@app.route('/api/category_breakdown')
def get_category_breakdown():
    """Get expense breakdown by broader category"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')

    month_list = parse_month_filter(month_filter)

    df = df_global.copy()
    expense_df = df[df['DR Amount'] > 0]

    if category != 'All':
        expense_df = expense_df[expense_df['Broader Category'] == category]
    expense_df = filter_by_months(expense_df, month_list)

    category_totals = expense_df.groupby('Broader Category')['DR Amount'].sum().sort_values(ascending=False)

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

@app.route('/api/running_balance')
def get_running_balance():
    """Get running balance over time"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')

    month_list = parse_month_filter(month_filter)

    df = df_global.copy()
    if category != 'All':
        df = df[df['Broader Category'] == category]
    df = filter_by_months(df, month_list)

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

@app.route('/api/top_vendors')
def get_top_vendors():
    """Get top 10 vendors by expense"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')

    month_list = parse_month_filter(month_filter)

    df = df_global.copy()
    expense_df = df[df['DR Amount'] > 0]

    if category != 'All':
        expense_df = expense_df[expense_df['Broader Category'] == category]
    expense_df = filter_by_months(expense_df, month_list)

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

@app.route('/api/categories')
def get_categories():
    """Get list of all broader categories"""
    categories = ['All'] + sorted(df_global['Broader Category'].unique().tolist())
    return jsonify({'categories': categories})

@app.route('/api/months')
def get_months():
    """Get list of all available months"""
    # Create unique pairs of (month_code, month_name) sorted by month_code
    pairs = df_global[['month', 'month_name']].drop_duplicates().sort_values('month')

    months_data = [{'value': 'All', 'label': 'All'}]
    for _, row in pairs.iterrows():
        months_data.append({
            'value': row['month'],
            'label': row['month_name']
        })

    return jsonify({'months_data': months_data})

@app.route('/api/transactions')
def get_transactions():
    """Get all transactions"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')
    limit = int(request.args.get('limit', 10000))  # Very high limit to get all

    # New parameters for sorting and searching
    sort_by = request.args.get('sort_by', 'date')   # date, dr_amount, cr_amount
    sort_order = request.args.get('sort_order', 'desc') # asc, desc
    search_query = request.args.get('search', '').lower()

    month_list = parse_month_filter(month_filter)

    df = df_global.copy()
    if category != 'All':
        df = df[df['Broader Category'] == category]
    df = filter_by_months(df, month_list)

    # Apply Search
    if search_query:
        # Search in description, vendor, and category
        df = df[
            df['Transaction Description'].astype(str).str.lower().str.contains(search_query, na=False) |
            df['Client/Vendor'].astype(str).str.lower().str.contains(search_query, na=False) |
            df['Broader Category'].astype(str).str.lower().str.contains(search_query, na=False)
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
    for _, row in df_sorted.iterrows():
        transactions.append({
            'date': row['date'].strftime('%d %b %Y'),
            'description': row['Transaction Description'],
            'vendor': row['Client/Vendor'],
            'category': row['Broader Category'],
            'dr_amount': float(row['DR Amount']),
            'dr_amount_formatted': format_indian_number(row['DR Amount']) if row['DR Amount'] > 0 else '',
            'cr_amount': float(row['CR Amount']),
            'cr_amount_formatted': format_indian_number(row['CR Amount']) if row['CR Amount'] > 0 else '',
            'net': float(row['net']),
            'net_formatted': format_indian_number(row['net'])
        })

    return jsonify({'transactions': transactions})


@app.route('/api/download_transactions')
def download_transactions():
    """Download transactions as Excel"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')

    month_list = parse_month_filter(month_filter)

    df = df_global.copy()
    if category != 'All':
        df = df[df['Broader Category'] == category]
    df = filter_by_months(df, month_list)

    # Sort and prepare for export
    df_export = df.sort_values('date', ascending=False).copy()

    # Select and rename columns for user friendliness
    columns_map = {
        'date': 'Date',
        'Client/Vendor': 'Vendor',
        'Broader Category': 'Category',
        'Transaction Description': 'Description',
        'DR Amount': 'Debit',
        'CR Amount': 'Credit',
        'net': 'Net Amount',
        'running_balance': 'Running Balance'
    }

    # Add formatted date for export
    df_export['date'] = df_export['date'].dt.strftime('%d-%m-%Y')

    # Select columns if they exist
    export_cols = [c for c in columns_map.keys() if c in df_export.columns]
    df_export = df_export[export_cols].rename(columns=columns_map)

    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False, sheet_name='Transactions')

    output.seek(0)

    filename = f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/insights')
def get_insights():
    """Get key insights"""
    category = request.args.get('category', 'All')
    month_filter = request.args.get('month', 'All')

    month_list = parse_month_filter(month_filter)

    df = df_global.copy()
    if category != 'All':
        df = df[df['Broader Category'] == category]
    df = filter_by_months(df, month_list)

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

if __name__ == '__main__':
    print("=" * 60)
    print("💰 Financial Analytics Dashboard")
    print("=" * 60)
    print("\n🚀 Starting server...")
    print("\n📊 Open your browser and go to:")
    print("\n    http://localhost:5000")
    print("\n⏹️  Press Ctrl+C to stop the server")
    print("=" * 60)
    print()
    app.run(debug=True, port=5000)
