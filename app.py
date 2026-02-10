from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, session
from functools import wraps
import pandas as pd
import json
import io
import os
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

# Import our modules
from config import Config, allowed_file, BANK_CONFIG, VALID_BANK_CODES, get_bank_config, get_bank_table
from database import DatabaseManager
from bank_statement_processor import process_bank_statement
from bill_processor import process_bill_file, generate_excel, format_extracted_data_for_display

app = Flask(__name__)
app.config.from_object(Config)

# Secret key for session management
app.secret_key = os.environ.get('SECRET_KEY', 'visma-finance-secret-key-2024-secure')

# Permanent session lifetime (30 days for "Stay signed in")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Login credentials
VALID_USERNAME = 'visma'
VALID_PASSWORD = '1617'


def login_required(f):
    """Decorator to require login for protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # For API routes, return 401
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            # For page routes, redirect to login
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Create uploads directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database manager (singleton with connection pool)
db_manager = DatabaseManager()
db_connected = False

# Global dataframe cache for multi-bank support
df_cache = {}

# Legacy global dataframe (for backwards compatibility)
df_global = None




# ============================================================================
# DATA LOADING FUNCTIONS (Multi-Bank Support)
# ============================================================================

def load_bank_data_from_db(bank_code='axis'):
    """Load and preprocess financial data from database for a specific bank"""
    global db_manager, db_connected

    if not db_connected:
        db_connected = db_manager.connect()

    if not db_connected:

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
    global df_cache

    if bank_code not in df_cache:
        df_cache[bank_code] = load_bank_data_from_db(bank_code)

    return df_cache.get(bank_code, pd.DataFrame())


def reload_bank_data(bank_code='axis'):
    """Reload financial data for a specific bank"""
    global df_cache
    if bank_code in df_cache:
        del df_cache[bank_code]
    return get_bank_df(bank_code)


def load_financial_data_from_db():
    """Load and preprocess financial data from database (legacy - uses axis)"""
    return load_bank_data_from_db('axis')


def load_financial_data_from_excel():
    """Load and preprocess financial data from Excel file"""
    try:
        df = pd.read_excel(app.config['EXCEL_FILE'])

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
    """Reload financial data (legacy - for backwards compatibility)"""
    global df_global
    if app.config['USE_DATABASE']:
        df_global = load_financial_data_from_db()
    else:
        df_global = load_financial_data_from_excel()
    return df_global


# Load data at startup
df_global = reload_data()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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


def format_indian_number(amount):
    """Format number with Indian comma system (full numbers, no abbreviations)"""
    if pd.isna(amount) or amount == 0:
        return "₹0"

    abs_amount = abs(amount)
    sign = "-" if amount < 0 else ""

    # Format with Indian comma system (lakhs and crores)
    # Example: 12,34,567.89
    def indian_format(num):
        s = f"{num:,.2f}"
        # Convert to Indian format: 1,234,567.89 -> 12,34,567.89
        parts = s.split('.')
        integer_part = parts[0].replace(',', '')
        decimal_part = parts[1] if len(parts) > 1 else '00'

        # Apply Indian grouping
        if len(integer_part) <= 3:
            formatted = integer_part
        else:
            # First group of 3 from right, then groups of 2
            formatted = integer_part[-3:]
            remaining = integer_part[:-3]
            while remaining:
                if len(remaining) <= 2:
                    formatted = remaining + ',' + formatted
                    remaining = ''
                else:
                    formatted = remaining[-2:] + ',' + formatted
                    remaining = remaining[:-2]

        # Remove decimal if it's .00
        if decimal_part == '00':
            return formatted
        return formatted + '.' + decimal_part

    return f"{sign}₹{indian_format(abs_amount)}"


# ============================================================================
# UPLOAD ENDPOINT
# ============================================================================

@app.route('/api/upload', methods=['POST'])
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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Save the file
        file.save(filepath)


        # Process the bank statement

        df = process_bank_statement(filepath)

        # Insert into database if enabled
        if app.config['USE_DATABASE']:


            # Ensure database is connected
            global db_connected
            if not db_connected:
                connected = db_manager.connect()
                if connected:
                    db_connected = True
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


@app.route('/api/upload_history')
@login_required
def get_upload_history():
    """Get recent upload history"""
    if not app.config['USE_DATABASE'] or not db_connected:
        return jsonify({'history': []})

    try:
        history = db_manager.get_upload_history(10)
        return jsonify({'history': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    # If already logged in, redirect to dashboard
    if session.get('logged_in'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if username == VALID_USERNAME and password == VALID_PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            # Check if "Stay signed in" was selected
            if request.form.get('remember_me'):
                session.permanent = True
            return redirect(url_for('index'))
        else:
            error = 'Invalid username or password. Please try again.'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """Handle user logout"""
    session.clear()
    return redirect(url_for('login'))


# ============================================================================
# PROTECTED ROUTES
# ============================================================================

@app.route('/sw.js')
def service_worker():
    return send_file('static/sw.js', mimetype='application/javascript')


@app.route('/')
@login_required
def index():
    """Render hub page with bank selection"""
    # Get stats for each bank
    bank_stats = {}
    for bank_code in VALID_BANK_CODES:
        try:
            df = get_bank_df(bank_code)
            bank_stats[bank_code] = {
                'transaction_count': len(df),
                'name': BANK_CONFIG[bank_code]['name']
            }
        except Exception as e:

            bank_stats[bank_code] = {
                'transaction_count': 0,
                'name': BANK_CONFIG[bank_code]['name']
            }

    return render_template('hub.html', bank_stats=bank_stats)


@app.route('/dashboard/<bank_code>')
@login_required
def bank_dashboard(bank_code):
    """Render bank-specific dashboard page"""
    if bank_code not in VALID_BANK_CODES:
        return redirect(url_for('index'))

    bank_config = get_bank_config(bank_code)
    return render_template('index.html',
                         bank_code=bank_code,
                         bank_name=bank_config['name'],
                         bank_config=bank_config)


@app.route('/edit-transactions/<bank_code>')
@login_required
def edit_transactions(bank_code):
    """Render bank-specific transaction edit page"""
    if bank_code not in VALID_BANK_CODES:
        return redirect(url_for('index'))

    bank_config = get_bank_config(bank_code)
    return render_template('edit_transactions.html',
                         bank_code=bank_code,
                         bank_name=bank_config['name'],
                         bank_config=bank_config)


@app.route('/charts/<bank_code>')
@login_required
def bank_charts(bank_code):
    """Render bank-specific charts page"""
    if bank_code not in VALID_BANK_CODES:
        return redirect(url_for('index'))

    bank_config = get_bank_config(bank_code)
    return render_template('charts.html',
                         bank_code=bank_code,
                         bank_name=bank_config['name'],
                         bank_config=bank_config)


# ============================================================================
# HUB API ENDPOINTS
# ============================================================================

@app.route('/api/clear-cache', methods=['POST'])
@login_required
def clear_cache():
    """Clear in-memory dataframe cache and reload from database"""
    global df_cache, df_global
    df_cache = {}
    df_global = reload_data()
    return jsonify({'success': True, 'message': 'Cache cleared successfully'})


@app.route('/api/hub/stats')
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


# ============================================================================
# BANK-SPECIFIC API ENDPOINTS
# ============================================================================

@app.route('/api/<bank_code>/summary')
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


@app.route('/api/<bank_code>/monthly_trend')
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


@app.route('/api/<bank_code>/category_breakdown')
@login_required
def get_bank_category_breakdown(bank_code):
    """Get expense breakdown by category for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    category = request.args.get('category', 'All')
    project = request.args.get('project', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({'categories': [], 'amounts': []})

    expense_df = df[df['DR Amount'] > 0]
    if category != 'All':
        expense_df = expense_df[expense_df['Category'] == category]
    expense_df = filter_by_date_range(expense_df, start_date, end_date)
    expense_df = filter_by_project(expense_df, project)

    if expense_df.empty:
        return jsonify({'categories': [], 'amounts': []})

    category_totals = expense_df.groupby('Category')['DR Amount'].sum().sort_values(ascending=False)

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


@app.route('/api/<bank_code>/running_balance')
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


@app.route('/api/<bank_code>/top_vendors')
@login_required
def get_bank_top_vendors(bank_code):
    """Get top 10 vendors by expense for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    category = request.args.get('category', 'All')
    project = request.args.get('project', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({'vendors': [], 'amounts': []})

    expense_df = df[df['DR Amount'] > 0]
    if category != 'All':
        expense_df = expense_df[expense_df['Category'] == category]
    expense_df = filter_by_date_range(expense_df, start_date, end_date)
    expense_df = filter_by_project(expense_df, project)

    if expense_df.empty:
        return jsonify({'vendors': [], 'amounts': []})

    vendor_totals = expense_df.groupby('Client/Vendor')['DR Amount'].sum().sort_values(ascending=False).head(10)

    top_vendor = vendor_totals.index[0] if len(vendor_totals) > 0 else None
    top_vendor_amount = float(vendor_totals.iloc[0]) if len(vendor_totals) > 0 else 0
    threshold = float(vendor_totals.quantile(0.8)) if len(vendor_totals) > 0 else 0

    return jsonify({
        'vendors': vendor_totals.index.tolist(),
        'amounts': vendor_totals.values.tolist(),
        'top_vendor': top_vendor,
        'top_vendor_amount': top_vendor_amount,
        'top_vendor_amount_formatted': format_indian_number(top_vendor_amount),
        'threshold': threshold
    })


@app.route('/api/<bank_code>/categories')
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


@app.route('/api/<bank_code>/date_range')
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


@app.route('/api/<bank_code>/transactions')
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

    transactions = []
    for idx, row in df_sorted.iterrows():
        transactions.append({
            'id': int(idx) if hasattr(idx, '__int__') else idx,
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


@app.route('/api/<bank_code>/transactions/paginated')
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
            'project': row['Project'] or ''
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
        'filter_options': filter_options
    })


@app.route('/api/<bank_code>/filter-options')
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


@app.route('/api/<bank_code>/insights')
@login_required
def get_bank_insights(bank_code):
    """Get key insights for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    category = request.args.get('category', 'All')
    project = request.args.get('project', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = get_bank_df(bank_code).copy()
    if df.empty:
        return jsonify({
            'avg_monthly_expense': 0,
            'avg_monthly_expense_formatted': '₹0',
            'expense_trend_pct': 0,
            'expense_trend_direction': 'no data',
            'avg_transaction_size': 0,
            'avg_transaction_size_formatted': '₹0',
            'peak_day': None,
            'cashflow_velocity': 0,
            'total_months': 0
        })

    if category != 'All':
        df = df[df['Category'] == category]
    df = filter_by_date_range(df, start_date, end_date)
    df = filter_by_project(df, project)

    monthly_expenses = df.groupby('month')['DR Amount'].sum()
    avg_monthly_expense = float(monthly_expenses.mean()) if len(monthly_expenses) > 0 else 0

    if len(monthly_expenses) >= 3:
        last_3_months = monthly_expenses.tail(3)
        first_month = last_3_months.iloc[0]
        last_month = last_3_months.iloc[-1]
        trend_pct = ((last_month - first_month) / first_month * 100) if first_month > 0 else 0
        trend_direction = 'increasing' if trend_pct > 0 else 'decreasing' if trend_pct < 0 else 'stable'
    else:
        trend_pct = 0
        trend_direction = 'insufficient data'

    expense_df = df[df['DR Amount'] > 0]
    avg_transaction_size = float(expense_df['DR Amount'].mean()) if len(expense_df) > 0 else 0

    expense_df_with_day = expense_df.copy()
    expense_df_with_day['day_of_week'] = expense_df_with_day['date'].dt.day_name()
    day_expenses = expense_df_with_day.groupby('day_of_week')['DR Amount'].sum()
    peak_day = day_expenses.idxmax() if len(day_expenses) > 0 else None
    peak_day_amount = float(day_expenses.max()) if len(day_expenses) > 0 else 0

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


@app.route('/api/<bank_code>/upload', methods=['POST'])
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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{bank_code}_{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        file.save(filepath)



        df = process_bank_statement(filepath, bank_code, password=password)

        if app.config['USE_DATABASE']:


            global db_connected
            if not db_connected:
                connected = db_manager.connect()
                if connected:
                    db_connected = True
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


@app.route('/api/<bank_code>/transaction/update', methods=['POST'])
@login_required
def update_bank_transaction(bank_code):
    """Update a transaction's editable fields for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

    try:
        data = request.json
        table = get_bank_table(bank_code)

        transaction_date = data.get('date')
        description = data.get('description')
        # Support both field names - use proper fallback for zero values
        dr_amount = data.get('debit') if data.get('debit') is not None else data.get('dr_amount', 0)
        cr_amount = data.get('credit') if data.get('credit') is not None else data.get('cr_amount', 0)
        # Ensure amounts are never None (would cause WHERE clause to fail)
        dr_amount = float(dr_amount) if dr_amount is not None else 0.0
        cr_amount = float(cr_amount) if cr_amount is not None else 0.0

        category = data.get('category') or 'Uncategorized'
        code = data.get('code')
        vendor = data.get('vendor') or 'Unknown'
        project = data.get('project')

        # Derive code from category if not provided
        category_codes = {
            'OFFICE EXP': 'OE', 'FACTORY EXP': 'FE', 'SITE EXP': 'SE',
            'TRANSPORT EXP': 'TE', 'MATERIAL PURCHASE': 'MP',
            'DUTIES & TAX': 'DT', 'SALARY AC': 'SA', 'BANK CHARGES': 'BC',
            'AMOUNT RECEIVED': 'AR', 'Uncategorized': 'UC'
        }
        if not code:
            code = category_codes.get(category, 'UC')

        if not all([transaction_date, description is not None]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields'
            }), 400

        if app.config['USE_DATABASE']:
            with db_manager.get_connection() as conn:
                query = f"""
                UPDATE {table}
                SET
                    category = %s,
                    code = %s,
                    client_vendor = %s,
                    project = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE transaction_date = %s
                  AND transaction_description = %s
                  AND dr_amount = %s
                  AND cr_amount = %s
                LIMIT 1
                """

                cursor = conn.cursor()
                cursor.execute(query, (
                    category,
                    code,
                    vendor,
                    project,
                    transaction_date,
                    description,
                    dr_amount,
                    cr_amount
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


@app.route('/api/<bank_code>/transaction/split', methods=['POST'])
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

        if not app.config['USE_DATABASE']:
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
                            'OFFICE EXP': 'OE', 'FACTORY EXP': 'FE', 'SITE EXP': 'SE',
                            'TRANSPORT EXP': 'TE', 'MATERIAL PURCHASE': 'MP',
                            'DUTIES & TAX': 'DT', 'SALARY AC': 'SA', 'BANK CHARGES': 'BC',
                            'AMOUNT RECEIVED': 'AR', 'Uncategorized': 'UC'
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


@app.route('/api/<bank_code>/download_transactions')
@login_required
def download_bank_transactions(bank_code):
    """Download transactions as Excel for a specific bank"""
    if bank_code not in VALID_BANK_CODES:
        return jsonify({'error': 'Invalid bank code'}), 400

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
            # Use Category field
            df_final[col] = df_export.get('Category', None)
        elif col in df_export.columns:
            df_final[col] = df_export[col]
        else:
            df_final[col] = None

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_final.to_excel(writer, index=False, sheet_name='Transactions')
        worksheet = writer.sheets['Transactions']
        for idx, col in enumerate(df_final.columns):
            max_length = max(df_final[col].astype(str).apply(len).max(), len(str(col))) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)

    output.seek(0)

    bank_name = BANK_CONFIG[bank_code]['name'].replace(' ', '_')
    filename = f"{bank_name}_transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# ============================================================================
# PERSONAL TRANSACTION TRACKER API ENDPOINTS
# ============================================================================

@app.route('/personal-tracker')
@login_required
def personal_tracker():
    """Render personal transaction tracker page"""
    return render_template('personal_tracker.html')


@app.route('/personal-tracker/add')
@login_required
def add_expense_page():
    """Render add expense page"""
    return render_template('expense_form.html', transaction=None)


@app.route('/personal-tracker/edit/<int:transaction_id>')
@login_required
def edit_expense_page(transaction_id):
    """Render edit expense page"""
    if not app.config['USE_DATABASE']:
        return render_template('expense_form.html', transaction=None)

    try:
        with db_manager.get_connection() as conn:
            query = """
            SELECT id, transaction_date, vendor, description, project, amount,
                   COALESCE(transaction_type, 'expense') as transaction_type, bank
            FROM personal_transactions
            WHERE id = %s
            """
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, (transaction_id,))
            row = cursor.fetchone()
            cursor.close()

        if row:
            transaction = {
                'id': row['id'],
                'date': row['transaction_date'].strftime('%Y-%m-%d'),
                'vendor': row['vendor'],
                'description': row['description'] or '',
                'project': row['project'] or 'General',
                'amount': float(row['amount']),
                'transaction_type': row['transaction_type'] or 'expense',
                'bank': row.get('bank')
            }
            return render_template('expense_form.html', transaction=transaction)
        else:
            # Transaction not found, redirect to add page
            return redirect(url_for('add_expense_page'))
    except Exception as e:

        return redirect(url_for('add_expense_page'))


@app.route('/api/personal/transactions', methods=['GET'])
@login_required
def get_personal_transactions():
    """Get all personal transactions"""
    if not app.config['USE_DATABASE']:
        return jsonify({'transactions': []})

    # Get filter parameters
    project = request.args.get('project', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    search = request.args.get('search', '').lower()
    transaction_type = request.args.get('type', 'All')

    try:
        query = """
        SELECT id, transaction_date, vendor, description, project, amount,
               COALESCE(transaction_type, 'expense') as transaction_type, bank, created_at
        FROM personal_transactions
        WHERE 1=1
        """
        params = []

        if project and project != 'All':
            query += " AND project = %s"
            params.append(project)

        if transaction_type and transaction_type != 'All':
            query += " AND COALESCE(transaction_type, 'expense') = %s"
            params.append(transaction_type)

        if start_date:
            query += " AND transaction_date >= %s"
            params.append(start_date)

        if end_date:
            query += " AND transaction_date <= %s"
            params.append(end_date)

        if search:
            query += " AND (LOWER(vendor) LIKE %s OR LOWER(description) LIKE %s)"
            params.extend([f'%{search}%', f'%{search}%'])

        query += " ORDER BY transaction_date DESC, created_at DESC"

        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            cursor.close()

        transactions = []
        for row in rows:
            trans_type = row.get('transaction_type', 'expense') or 'expense'
            transactions.append({
                'id': row['id'],
                'date': row['transaction_date'].strftime('%Y-%m-%d'),
                'date_formatted': row['transaction_date'].strftime('%d %b %Y'),
                'vendor': row['vendor'],
                'description': row['description'] or '',
                'project': row['project'],
                'amount': float(row['amount']),
                'amount_formatted': format_indian_number(row['amount']),
                'transaction_type': trans_type,
                'bank': row.get('bank')
            })
        return jsonify({'transactions': transactions})
    except Exception as e:

        return jsonify({'transactions': []})


@app.route('/api/personal/transactions', methods=['POST'])
@login_required
def add_personal_transaction():
    """Add a new personal transaction"""
    if not app.config['USE_DATABASE']:
        return jsonify({'error': 'Database not available'}), 503

    data = request.json
    transaction_date = data.get('date')
    vendor = data.get('vendor', '').strip()
    description = data.get('description', '').strip()
    project = data.get('project', 'General').strip() or 'General'
    amount = data.get('amount')
    transaction_type = data.get('transaction_type', 'expense').strip().lower()
    bank = data.get('bank')

    # Validate transaction_type
    if transaction_type not in ['expense', 'income']:
        transaction_type = 'expense'

    # Validate bank
    if bank and bank not in ['axis', 'kvb']:
        bank = None

    if not transaction_date or not vendor or amount is None:
        return jsonify({'error': 'Missing required fields (date, vendor, amount)'}), 400

    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({'error': 'Amount must be greater than 0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid amount'}), 400

    try:
        with db_manager.get_connection() as conn:
            query = """
            INSERT INTO personal_transactions (transaction_date, vendor, description, project, amount, transaction_type, bank)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor = conn.cursor()
            cursor.execute(query, (transaction_date, vendor, description, project, amount, transaction_type, bank))
            conn.commit()
            new_id = cursor.lastrowid
            cursor.close()

        return jsonify({
            'success': True,
            'message': 'Transaction added successfully',
            'id': new_id
        })
    except Exception as e:

        return jsonify({'error': str(e)}), 500


@app.route('/api/personal/transactions/<int:transaction_id>', methods=['PUT'])
@login_required
def update_personal_transaction(transaction_id):
    """Update a personal transaction"""
    if not app.config['USE_DATABASE']:
        return jsonify({'error': 'Database not available'}), 503

    data = request.json
    transaction_date = data.get('date')
    vendor = data.get('vendor', '').strip()
    description = data.get('description', '').strip()
    project = data.get('project', 'General').strip() or 'General'
    amount = data.get('amount')
    transaction_type = data.get('transaction_type', 'expense').strip().lower()
    bank = data.get('bank')

    # Validate transaction_type
    if transaction_type not in ['expense', 'income']:
        transaction_type = 'expense'

    # Validate bank
    if bank and bank not in ['axis', 'kvb']:
        bank = None

    if not transaction_date or not vendor or amount is None:
        return jsonify({'error': 'Missing required fields (date, vendor, amount)'}), 400

    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({'error': 'Amount must be greater than 0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid amount'}), 400

    try:
        with db_manager.get_connection() as conn:
            query = """
            UPDATE personal_transactions
            SET transaction_date = %s, vendor = %s, description = %s, project = %s, amount = %s,
                transaction_type = %s, bank = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """
            cursor = conn.cursor()
            cursor.execute(query, (transaction_date, vendor, description, project, amount, transaction_type, bank, transaction_id))
            conn.commit()
            affected_rows = cursor.rowcount
            cursor.close()

        if affected_rows > 0:
            return jsonify({
                'success': True,
                'message': 'Transaction updated successfully'
            })
        else:
            return jsonify({'error': 'Transaction not found'}), 404
    except Exception as e:

        return jsonify({'error': str(e)}), 500


@app.route('/api/personal/transactions/<int:transaction_id>', methods=['DELETE'])
@login_required
def delete_personal_transaction(transaction_id):
    """Delete a personal transaction"""
    if not app.config['USE_DATABASE']:
        return jsonify({'error': 'Database not available'}), 503

    try:
        with db_manager.get_connection() as conn:
            query = "DELETE FROM personal_transactions WHERE id = %s"
            cursor = conn.cursor()
            cursor.execute(query, (transaction_id,))
            conn.commit()
            affected_rows = cursor.rowcount
            cursor.close()

        if affected_rows > 0:
            return jsonify({
                'success': True,
                'message': 'Transaction deleted successfully'
            })
        else:
            return jsonify({'error': 'Transaction not found'}), 404
    except Exception as e:

        return jsonify({'error': str(e)}), 500


@app.route('/api/personal/summary')
@login_required
def get_personal_summary():
    """Get summary statistics for personal transactions"""
    empty_response = {
        'total_expense': 0,
        'total_expense_formatted': '₹0',
        'total_income': 0,
        'total_income_formatted': '₹0',
        'net_balance': 0,
        'net_balance_formatted': '₹0',
        'this_month_expense': 0,
        'this_month_expense_formatted': '₹0',
        'this_month_income': 0,
        'this_month_income_formatted': '₹0',
        'transaction_count': 0,
        'project_breakdown': []
    }

    if not app.config['USE_DATABASE']:
        return jsonify(empty_response)

    # Get filter parameters
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)

            # Total expense and income query
            total_query = """
            SELECT
                COALESCE(SUM(CASE WHEN COALESCE(transaction_type, 'expense') = 'expense' THEN amount ELSE 0 END), 0) as total_expense,
                COALESCE(SUM(CASE WHEN COALESCE(transaction_type, 'expense') = 'income' THEN amount ELSE 0 END), 0) as total_income,
                COUNT(*) as count
            FROM personal_transactions
            WHERE 1=1
            """
            params = []

            if start_date:
                total_query += " AND transaction_date >= %s"
                params.append(start_date)
            if end_date:
                total_query += " AND transaction_date <= %s"
                params.append(end_date)

            cursor.execute(total_query, params)
            total_result = cursor.fetchone()
            total_expense = float(total_result['total_expense']) if total_result else 0
            total_income = float(total_result['total_income']) if total_result else 0
            net_balance = total_income - total_expense
            transaction_count = int(total_result['count']) if total_result else 0

            # This month query with income/expense
            this_month_query = """
            SELECT
                COALESCE(SUM(CASE WHEN COALESCE(transaction_type, 'expense') = 'expense' THEN amount ELSE 0 END), 0) as expense,
                COALESCE(SUM(CASE WHEN COALESCE(transaction_type, 'expense') = 'income' THEN amount ELSE 0 END), 0) as income
            FROM personal_transactions
            WHERE YEAR(transaction_date) = YEAR(CURRENT_DATE)
              AND MONTH(transaction_date) = MONTH(CURRENT_DATE)
            """
            cursor.execute(this_month_query)
            this_month_result = cursor.fetchone()
            this_month_expense = float(this_month_result['expense']) if this_month_result else 0
            this_month_income = float(this_month_result['income']) if this_month_result else 0

            # Project breakdown query (expenses only)
            project_query = """
            SELECT project, SUM(amount) as total, COUNT(*) as count
            FROM personal_transactions
            WHERE COALESCE(transaction_type, 'expense') = 'expense'
            """
            params = []
            if start_date:
                project_query += " AND transaction_date >= %s"
                params.append(start_date)
            if end_date:
                project_query += " AND transaction_date <= %s"
                params.append(end_date)

            project_query += " GROUP BY project ORDER BY total DESC"

            cursor.execute(project_query, params)
            project_rows = cursor.fetchall()
            cursor.close()

        project_breakdown = []
        for row in project_rows:
            pct = (float(row['total']) / total_expense * 100) if total_expense > 0 else 0
            project_breakdown.append({
                'project': row['project'],
                'amount': float(row['total']),
                'amount_formatted': format_indian_number(row['total']),
                'count': int(row['count']),
                'percentage': round(pct, 1)
            })

        return jsonify({
            'total_expense': total_expense,
            'total_expense_formatted': format_indian_number(total_expense),
            'total_income': total_income,
            'total_income_formatted': format_indian_number(total_income),
            'net_balance': net_balance,
            'net_balance_formatted': format_indian_number(abs(net_balance)),
            'net_balance_positive': net_balance >= 0,
            'this_month_expense': this_month_expense,
            'this_month_expense_formatted': format_indian_number(this_month_expense),
            'this_month_income': this_month_income,
            'this_month_income_formatted': format_indian_number(this_month_income),
            'transaction_count': transaction_count,
            'project_breakdown': project_breakdown
        })
    except Exception as e:

        return jsonify(empty_response)


@app.route('/api/personal/projects')
@login_required
def get_personal_projects():
    """Get list of unique projects from personal transactions"""
    if not app.config['USE_DATABASE']:
        return jsonify({'projects': ['General']})

    try:
        with db_manager.get_connection() as conn:
            query = "SELECT DISTINCT project FROM personal_transactions ORDER BY project"
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cursor.close()

        projects = [row[0] for row in rows if row[0]]
        if not projects:
            projects = ['General']
        return jsonify({'projects': projects})
    except Exception as e:

        return jsonify({'projects': ['General']})


@app.route('/api/personal/vendors')
@login_required
def get_personal_vendors():
    """Get list of unique vendors from personal transactions"""
    if not app.config['USE_DATABASE']:
        return jsonify({'vendors': []})

    try:
        with db_manager.get_connection() as conn:
            query = "SELECT DISTINCT vendor FROM personal_transactions ORDER BY vendor"
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cursor.close()

        vendors = [row[0] for row in rows if row[0]]
        return jsonify({'vendors': vendors})
    except Exception as e:

        return jsonify({'vendors': []})


@app.route('/api/personal/descriptions')
@login_required
def get_personal_descriptions():
    """Get list of unique descriptions from personal transactions"""
    if not app.config['USE_DATABASE']:
        return jsonify({'descriptions': []})

    try:
        with db_manager.get_connection() as conn:
            query = "SELECT DISTINCT description FROM personal_transactions WHERE description IS NOT NULL AND description != '' ORDER BY description"
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cursor.close()

        descriptions = [row[0] for row in rows if row[0]]
        return jsonify({'descriptions': descriptions})
    except Exception as e:

        return jsonify({'descriptions': []})


# ============================================================================
# BILL PROCESSOR API ENDPOINTS
# ============================================================================

@app.route('/bill-processor')
@login_required
def bill_processor_page():
    """Render bill processor page"""
    return render_template('bill_processor.html')


@app.route('/api/bills/process', methods=['POST'])
@login_required
def process_bill():
    """Process an uploaded bill image/PDF and extract data using Gemini Vision"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        # Check file extension
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf', '.webp'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400

        # Save file temporarily
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_filename = f"bill_{timestamp}_{filename}"
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)

        file.save(temp_path)


        # Process the bill

        results = process_bill_file(temp_path, filename)

        # Save to database (with duplicate check)
        db_results = []
        for bill in results:
            if bill.get('success'):
                # Extract invoice number from the bill data
                invoice_number = bill.get('data', {}).get('invoice_header', {}).get('invoice_number', '')

                # Check for duplicate invoice before saving
                existing_bill = db_manager.check_duplicate_invoice(invoice_number)
                if existing_bill:

                    db_results.append({
                        'saved': False,
                        'invoice_id': None,
                        'db_error': 'Duplicate invoice',
                        'is_duplicate': True,
                        'existing_bill': existing_bill
                    })
                    continue

                # No duplicate found, proceed with insert
                success, invoice_id, error = db_manager.insert_bill(bill)
                db_results.append({
                    'saved': success,
                    'invoice_id': invoice_id,
                    'db_error': error,
                    'is_duplicate': False
                })
            else:
                db_results.append({'saved': False, 'invoice_id': None, 'db_error': 'Extraction failed', 'is_duplicate': False})

        # Format for display
        display_data = format_extracted_data_for_display(results)

        # Add DB status to display data
        for i, display_item in enumerate(display_data):
            if i < len(db_results):
                display_item['db_saved'] = db_results[i]['saved']
                display_item['invoice_id'] = db_results[i]['invoice_id']
                display_item['is_duplicate'] = db_results[i].get('is_duplicate', False)
                if db_results[i].get('existing_bill'):
                    display_item['existing_bill'] = db_results[i]['existing_bill']

        return jsonify({
            'success': True,
            'results': results,
            'display_data': display_data,
            'db_results': db_results
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/bills/download', methods=['POST'])
@login_required
def download_bills_excel():
    """Generate and download Excel file from extracted bill data"""
    try:
        data = request.json
        results = data.get('results', [])

        if not results:
            return jsonify({'error': 'No data to download'}), 400

        # Generate Excel file
        excel_buffer = generate_excel(results)

        # Create filename with timestamp
        filename = f"bills_extracted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        return send_file(
            excel_buffer,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/bills/stored')
@login_required
def get_stored_bills():
    """Get all stored bills from database with optional filters"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        project = request.args.get('project', None)
        date_from = request.args.get('date_from', None)
        date_to = request.args.get('date_to', None)

        bills = db_manager.get_all_bills(limit=limit, offset=offset, project=project,
                                         date_from=date_from, date_to=date_to)
        total = db_manager.get_bill_count(project=project, date_from=date_from, date_to=date_to)



        return jsonify({
            'success': True,
            'bills': bills,
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/stored/<int:invoice_id>')
@login_required
def get_stored_bill_detail(invoice_id):
    """Get detailed bill information including line items"""
    try:
        bill = db_manager.get_bill_detail(invoice_id)

        if not bill:
            return jsonify({'success': False, 'error': 'Bill not found'}), 404

        return jsonify({
            'success': True,
            'bill': bill
        })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/stored/<int:invoice_id>', methods=['DELETE'])
@login_required
def delete_stored_bill(invoice_id):
    """Delete a stored bill"""
    try:
        success = db_manager.delete_bill(invoice_id)

        if success:
            return jsonify({'success': True, 'message': 'Bill deleted'})
        else:
            return jsonify({'success': False, 'error': 'Failed to delete bill'}), 500
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/stored/<int:invoice_id>/project', methods=['PUT'])
@login_required
def update_bill_project(invoice_id):
    """Update the project field for a bill"""
    try:
        data = request.json
        project = data.get('project', '').strip() if data else ''

        success = db_manager.update_bill_project(invoice_id, project)

        if success:
            return jsonify({'success': True, 'message': 'Project updated', 'project': project})
        else:
            return jsonify({'success': False, 'error': 'Failed to update project'}), 500
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/projects')
@login_required
def get_bill_projects():
    """Get all unique project names from bills"""
    try:
        projects = db_manager.get_unique_projects()
        return jsonify({
            'success': True,
            'projects': projects
        })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/summary')
@login_required
def get_bills_summary():
    """Get summary statistics for stored bills"""
    try:
        project = request.args.get('project', None)

        # Get totals with optional project filter
        if project:
            query = """
            SELECT
                COUNT(*) as cnt,
                COALESCE(SUM(total_amount), 0) as sum_value,
                COALESCE(SUM(COALESCE(total_cgst, 0) + COALESCE(total_sgst, 0) + COALESCE(total_igst, 0)), 0) as sum_gst,
                COALESCE(SUM(COALESCE(total_cgst, 0)), 0) as sum_cgst,
                COALESCE(SUM(COALESCE(total_sgst, 0)), 0) as sum_sgst,
                COALESCE(SUM(COALESCE(total_igst, 0)), 0) as sum_igst,
                COUNT(DISTINCT vendor_name) as vendor_cnt
            FROM bill_invoices
            WHERE project = %s
            """
            result = db_manager.fetch_all(query, (project,))
        else:
            query = """
            SELECT
                COUNT(*) as cnt,
                COALESCE(SUM(total_amount), 0) as sum_value,
                COALESCE(SUM(COALESCE(total_cgst, 0) + COALESCE(total_sgst, 0) + COALESCE(total_igst, 0)), 0) as sum_gst,
                COALESCE(SUM(COALESCE(total_cgst, 0)), 0) as sum_cgst,
                COALESCE(SUM(COALESCE(total_sgst, 0)), 0) as sum_sgst,
                COALESCE(SUM(COALESCE(total_igst, 0)), 0) as sum_igst,
                COUNT(DISTINCT vendor_name) as vendor_cnt
            FROM bill_invoices
            """
            result = db_manager.fetch_all(query)


        if result and len(result) > 0 and result[0] is not None:
            row = result[0]
            # Convert each value - use float() directly, don't rely on 'or' since Decimal(0) is falsy
            total_invoices = int(row[0]) if row[0] is not None else 0
            total_value = float(row[1]) if row[1] is not None else 0.0
            total_gst = float(row[2]) if row[2] is not None else 0.0
            total_cgst = float(row[3]) if row[3] is not None else 0.0
            total_sgst = float(row[4]) if row[4] is not None else 0.0
            total_igst = float(row[5]) if row[5] is not None else 0.0
            unique_vendors = int(row[6]) if row[6] is not None else 0
            return jsonify({
                'success': True,
                'summary': {
                    'total_invoices': total_invoices,
                    'total_value': total_value,
                    'total_gst': total_gst,
                    'total_cgst': total_cgst,
                    'total_sgst': total_sgst,
                    'total_igst': total_igst,
                    'unique_vendors': unique_vendors
                }
            })
        else:
            return jsonify({
                'success': True,
                'summary': {
                    'total_invoices': 0,
                    'total_value': 0,
                    'total_gst': 0,
                    'total_cgst': 0,
                    'total_sgst': 0,
                    'total_igst': 0,
                    'unique_vendors': 0
                }
            })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/stats')
@login_required
def get_bills_stats():
    """Get bill processor stats for hub page"""
    try:
        invoice_count = db_manager.get_bill_count()
        return jsonify({
            'success': True,
            'invoice_count': invoice_count
        })
    except Exception as e:

        return jsonify({
            'success': False,
            'invoice_count': 0,
            'error': str(e)
        }), 500


@app.route('/api/bills/file/<filename>')
@login_required
def serve_bill_file(filename):
    """Serve uploaded bill file (PDF or image) for preview"""
    import glob as glob_module

    try:
        # Security: Prevent path traversal attacks
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        # Build the file path
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Check if file exists directly
        if not os.path.exists(file_path):
            # Files are saved with bill_{timestamp}_ prefix, so search for matching file
            pattern = os.path.join(app.config['UPLOAD_FOLDER'], f"bill_*_{filename}")
            matches = glob_module.glob(pattern)

            if matches:
                # Use the most recent match (last in sorted order)
                file_path = sorted(matches)[-1]
            else:
                return jsonify({'success': False, 'error': 'File not found'}), 404

        # Determine MIME type based on extension
        ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
        mime_types = {
            'pdf': 'application/pdf',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'webp': 'image/webp',
            'gif': 'image/gif',
            'bmp': 'image/bmp'
        }
        mime_type = mime_types.get(ext, 'application/octet-stream')

        return send_file(file_path, mimetype=mime_type)
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/upload-files', methods=['POST'])
@login_required
def bulk_upload_bill_files():
    """
    Bulk upload bill files (PDFs/images) without processing.
    Used to restore original documents for bills already in the database.
    Files are saved with their original names to match database records.
    """
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': 'No files provided'}), 400

        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({'success': False, 'error': 'No files selected'}), 400

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf', '.webp', '.gif', '.bmp'}
        results = []
        uploaded_count = 0
        skipped_count = 0

        for file in files:
            if not file.filename:
                continue

            # Check file extension
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_extensions:
                results.append({
                    'filename': file.filename,
                    'status': 'skipped',
                    'reason': f'Unsupported file type: {ext}'
                })
                skipped_count += 1
                continue

            # Secure the filename and save
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            # Check if file already exists
            if os.path.exists(file_path):
                results.append({
                    'filename': filename,
                    'status': 'skipped',
                    'reason': 'File already exists'
                })
                skipped_count += 1
                continue

            # Save the file
            file.save(file_path)
            results.append({
                'filename': filename,
                'status': 'uploaded'
            })
            uploaded_count += 1


        return jsonify({
            'success': True,
            'message': f'Uploaded {uploaded_count} files, skipped {skipped_count}',
            'uploaded': uploaded_count,
            'skipped': skipped_count,
            'details': results
        })

    except Exception as e:

        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/bills/stored/<int:invoice_id>', methods=['PUT'])
@login_required
def update_stored_bill(invoice_id):
    """Update a stored bill with all fields and line items"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        success, error = db_manager.update_bill(invoice_id, data)

        if success:
            return jsonify({'success': True, 'message': 'Invoice updated successfully'})
        else:
            return jsonify({'success': False, 'error': error or 'Failed to update invoice'}), 500
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# LEGACY API ENDPOINTS (for backwards compatibility)
# ============================================================================

@app.route('/api/summary')
@login_required
def get_summary():
    """Get summary statistics"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    # Filter data
    df = df_global.copy()
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


# Continue with all other routes from original app.py...
# (I'll include the rest in the next part to keep this manageable)

@app.route('/api/monthly_trend')
@login_required
def get_monthly_trend():
    """Get monthly income/expense trend"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = df_global.copy()
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

@app.route('/api/category_breakdown')
@login_required
def get_category_breakdown():
    """Get expense breakdown by broader category"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = df_global.copy()
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

@app.route('/api/running_balance')
@login_required
def get_running_balance():
    """Get running balance over time"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = df_global.copy()
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

@app.route('/api/top_vendors')
@login_required
def get_top_vendors():
    """Get top 10 vendors by expense"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = df_global.copy()
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

@app.route('/api/categories')
@login_required
def get_categories():
    """Get list of all categories"""
    categories = ['All'] + sorted(df_global['Category'].unique().tolist())
    return jsonify({'categories': categories})

@app.route('/api/months')
@login_required
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


@app.route('/api/date_range')
@login_required
def get_date_range():
    """Get the min and max dates available in the data"""
    if len(df_global) == 0:
        return jsonify({
            'min_date': None,
            'max_date': None
        })

    min_date = df_global['date'].min()
    max_date = df_global['date'].max()

    return jsonify({
        'min_date': min_date.strftime('%Y-%m-%d') if pd.notna(min_date) else None,
        'max_date': max_date.strftime('%Y-%m-%d') if pd.notna(max_date) else None
    })

@app.route('/api/transactions')
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

    df = df_global.copy()
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


@app.route('/api/transaction/update', methods=['POST'])
@login_required
def update_transaction():
    """Update a transaction's editable fields"""
    try:
        data = request.json

        # Required fields
        transaction_date = data.get('date')
        description = data.get('description')

        # Support both field names - use proper fallback for zero values
        dr_amount = data.get('debit') if data.get('debit') is not None else data.get('dr_amount', 0)
        cr_amount = data.get('credit') if data.get('credit') is not None else data.get('cr_amount', 0)
        # Ensure amounts are never None (would cause WHERE clause to fail)
        dr_amount = float(dr_amount) if dr_amount is not None else 0.0
        cr_amount = float(cr_amount) if cr_amount is not None else 0.0

        # Editable fields
        category = data.get('category') or 'Uncategorized'
        code = data.get('code')
        vendor = data.get('vendor') or 'Unknown'
        project = data.get('project')

        # Derive code from category if not provided
        category_codes = {
            'OFFICE EXP': 'OE', 'FACTORY EXP': 'FE', 'SITE EXP': 'SE',
            'TRANSPORT EXP': 'TE', 'MATERIAL PURCHASE': 'MP',
            'DUTIES & TAX': 'DT', 'SALARY AC': 'SA', 'BANK CHARGES': 'BC',
            'AMOUNT RECEIVED': 'AR', 'Uncategorized': 'UC'
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
        if app.config['USE_DATABASE']:
            with db_manager.get_connection() as conn:
                query = """
                UPDATE transactions
                SET
                    category = %s,
                    code = %s,
                    client_vendor = %s,
                    project = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE transaction_date = %s
                  AND transaction_description = %s
                  AND dr_amount = %s
                  AND cr_amount = %s
                LIMIT 1
                """

                cursor = conn.cursor()
                cursor.execute(query, (
                    category,
                    code,
                    vendor,
                    project,
                    transaction_date,
                    description,
                    dr_amount,
                    cr_amount
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


@app.route('/api/download_transactions')
@login_required
def download_transactions():
    """Download transactions as Excel - matches original table schema"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = df_global.copy()
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

    # Create Excel file in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_final.to_excel(writer, index=False, sheet_name='Transactions')

        # Auto-adjust column widths
        worksheet = writer.sheets['Transactions']
        for idx, col in enumerate(df_final.columns):
            max_length = max(
                df_final[col].astype(str).apply(len).max(),
                len(str(col))
            ) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)

    output.seek(0)

    filename = f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/insights')
@login_required
def get_insights():
    """Get key insights"""
    category = request.args.get('category', 'All')
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    df = df_global.copy()
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



if __name__ == '__main__':

    app.run(debug=True, port=5000)
