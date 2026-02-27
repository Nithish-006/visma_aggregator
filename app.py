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


def get_project_stems(project_str):
    """Extract first token (stem) from each project name for fuzzy matching.
    'RCH CT,SHOBA' -> ['rch', 'shoba']"""
    if not project_str:
        return []
    projects = [p.strip() for p in project_str.split(',') if p.strip()]
    stems = []
    for p in projects:
        tokens = p.split()
        first_token = tokens[0].lower() if tokens else p.lower()
        stems.append(first_token)
    return stems


NON_PROJECT_STEMS = {
    'axis', 'axi', 'kvb', 'factory', 'labour', 'labor', 'office', 'bank', 'salary',
    'tax', 'gst', 'tds', 'neft', 'rtgs', 'imps', 'upi', 'interest', 'charges',
    'unknown', 'unassigned', 'general', 'misc', 'amount', 'transfer', 'return',
    'received', 'payment', 'deposit', 'withdrawal', 'credit', 'debit'
}

PROJECT_ALIASES = {
    'palson': 'polson',
    'polsons': 'polson',
}


def normalize_project_stem(name):
    """Lowercase, strip whitespace, normalize plurals via alias lookup only."""
    s = name.lower().strip()
    # Check exact alias first
    if s in PROJECT_ALIASES:
        return PROJECT_ALIASES[s]
    # Try stripping trailing 's'/'es' and check if the base form is a known alias
    if s.endswith('es') and len(s) > 3:
        candidate = s[:-2]
        if candidate in PROJECT_ALIASES:
            return PROJECT_ALIASES[candidate]
    elif s.endswith('s') and len(s) > 2:
        candidate = s[:-1]
        if candidate in PROJECT_ALIASES:
            return PROJECT_ALIASES[candidate]
    # Return as-is (no blind plural stripping)
    return s


def build_smart_project_groups(all_project_names, bill_projects):
    """Build smart stem-based project groups from bank txn projects and bill projects.

    Returns {canonical_stem: set(original_project_names)}
    """
    # Merge all project names
    all_names = set()
    for name in all_project_names:
        s = str(name).strip()
        if s and s.lower() != 'nan':
            all_names.add(s)
    for name in bill_projects:
        s = str(name).strip()
        if s and s.lower() != 'nan':
            all_names.add(s)

    # Build candidate stems from first words of all names
    candidate_stems = set()
    for name in all_names:
        tokens = name.split()
        if tokens:
            candidate_stems.add(normalize_project_stem(tokens[0]))

    stem_groups = {}  # canonical_stem -> set of original names

    for name in all_names:
        s = name.strip()
        if not s:
            continue

        stem = None

        # Rule 1: If name contains ' - ' (dash separator), extract part AFTER dash
        if ' - ' in s:
            after_dash = s.split(' - ', 1)[1].strip()
            if after_dash:
                first_token = after_dash.split()[0] if after_dash.split() else after_dash
                candidate = normalize_project_stem(first_token)
                if candidate not in NON_PROJECT_STEMS:
                    stem = candidate

        # Rule 2: Check all tokens against candidate stems
        if stem is None:
            tokens = s.split()
            for token in tokens:
                candidate = normalize_project_stem(token)
                if candidate not in NON_PROJECT_STEMS and candidate in candidate_stems:
                    stem = candidate
                    break

        # Rule 3: Fallback - use first word
        if stem is None:
            tokens = s.split()
            first = normalize_project_stem(tokens[0]) if tokens else normalize_project_stem(s)
            if first not in NON_PROJECT_STEMS:
                stem = first

        # Skip if all tokens are non-project stems
        if stem is None or stem in NON_PROJECT_STEMS:
            continue

        stem_groups.setdefault(stem, set()).add(name)

    return stem_groups


def match_bills_to_project_groups(bills_list, stem_groups):
    """Match bills to project stem groups.

    Returns {stem: [list of bill dicts]}
    """
    # Build reverse lookup: original_name -> stem
    name_to_stem = {}
    for stem, names in stem_groups.items():
        for name in names:
            name_to_stem[name] = stem

    result = {}
    for bill in bills_list:
        project = str(bill.get('project', '') or '').strip()
        if not project or project.lower() == 'nan':
            continue

        matched_stem = name_to_stem.get(project)

        # If not directly matched, try fuzzy matching with same logic
        if matched_stem is None:
            if ' - ' in project:
                after_dash = project.split(' - ', 1)[1].strip()
                if after_dash:
                    first_token = after_dash.split()[0] if after_dash.split() else after_dash
                    candidate = normalize_project_stem(first_token)
                    if candidate in stem_groups:
                        matched_stem = candidate
            if matched_stem is None:
                tokens = project.split()
                for token in tokens:
                    candidate = normalize_project_stem(token)
                    if candidate in stem_groups:
                        matched_stem = candidate
                        break
            if matched_stem is None:
                tokens = project.split()
                first = normalize_project_stem(tokens[0]) if tokens else normalize_project_stem(project)
                if first in stem_groups:
                    matched_stem = first

        if matched_stem:
            result.setdefault(matched_stem, []).append(bill)

    return result


def match_labour_to_project_groups(labour_costs, stem_groups):
    """Match salary/attendance project names to stem groups.

    labour_costs: {project_name: cost} from salary DB
    stem_groups: {stem: set(names)} from build_smart_project_groups

    Returns {stem: total_labour_cost}
    """
    # Build reverse lookup from existing stem groups
    name_to_stem = {}
    for stem, names in stem_groups.items():
        for name in names:
            name_to_stem[name.lower().strip()] = stem

    result = {}
    for project, cost in labour_costs.items():
        p = project.strip()
        p_lower = p.lower()

        # Direct match
        matched_stem = name_to_stem.get(p_lower)

        # Fuzzy match using same logic as other matchers
        if matched_stem is None:
            if ' - ' in p:
                after_dash = p.split(' - ', 1)[1].strip()
                if after_dash:
                    candidate = normalize_project_stem(after_dash.split()[0])
                    if candidate in stem_groups:
                        matched_stem = candidate
        if matched_stem is None:
            tokens = p.split()
            for token in tokens:
                candidate = normalize_project_stem(token)
                if candidate in stem_groups:
                    matched_stem = candidate
                    break
        if matched_stem is None:
            tokens = p.split()
            first = normalize_project_stem(tokens[0]) if tokens else normalize_project_stem(p)
            if first in stem_groups:
                matched_stem = first

        if matched_stem:
            result[matched_stem] = result.get(matched_stem, 0) + cost

    return result


def robust_filter_by_project(df, project=None):
    """Filter dataframe by project using stem-based prefix matching.
    Extracts first word from each selected project and matches case-insensitively."""
    if not project or project == 'All':
        return df

    project_col = 'Project' if 'Project' in df.columns else 'project'
    if project_col not in df.columns:
        return df

    stems = get_project_stems(project)
    if not stems:
        return df

    lower_col = df[project_col].astype(str).str.lower().str.strip()
    mask = pd.Series(False, index=df.index)
    for stem in stems:
        mask = mask | lower_col.str.startswith(stem)
    return df[mask]


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
            stems = get_project_stems(project)
            if stems:
                stem_conditions = []
                for stem in stems:
                    stem_conditions.append("LOWER(project) LIKE %s")
                    params.append(f"{stem}%")
                query += f" AND ({' OR '.join(stem_conditions)})"

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
        projects_csv = request.args.get('projects', None)
        date_from = request.args.get('date_from', None)
        date_to = request.args.get('date_to', None)
        added_from = request.args.get('added_from', None)
        added_to = request.args.get('added_to', None)

        # Multi-project support: comma-separated list takes precedence
        projects_list = None
        if projects_csv:
            projects_list = [p.strip() for p in projects_csv.split(',') if p.strip()]
        elif project:
            projects_list = [project]

        bills = db_manager.get_all_bills(limit=limit, offset=offset, projects=projects_list,
                                         date_from=date_from, date_to=date_to,
                                         added_from=added_from, added_to=added_to)
        total = db_manager.get_bill_count(projects=projects_list, date_from=date_from, date_to=date_to,
                                          added_from=added_from, added_to=added_to)



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
        projects_csv = request.args.get('projects', None)
        date_from = request.args.get('date_from', None)
        date_to = request.args.get('date_to', None)
        added_from = request.args.get('added_from', None)
        added_to = request.args.get('added_to', None)

        projects_list = None
        if projects_csv:
            projects_list = [p.strip() for p in projects_csv.split(',') if p.strip()]
        elif project:
            projects_list = [project]

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
        WHERE 1=1
        """
        params = []

        if projects_list:
            placeholders = ','.join(['%s'] * len(projects_list))
            query += f" AND project IN ({placeholders})"
            params.extend(projects_list)

        if date_from:
            query += " AND invoice_date >= %s"
            params.append(date_from)

        if date_to:
            query += " AND invoice_date <= %s"
            params.append(date_to)

        if added_from:
            query += " AND DATE(created_at) >= %s"
            params.append(added_from)

        if added_to:
            query += " AND DATE(created_at) <= %s"
            params.append(added_to)

        result = db_manager.fetch_all(query, tuple(params) if params else None)


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
# SALES BILLS API ENDPOINTS
# ============================================================================

def extract_project_from_filename(filename):
    """Extract project name from filename by removing leading numbers and extension"""
    import re
    name = os.path.splitext(filename)[0]  # Remove extension
    name = re.sub(r'^\d+\s*', '', name)   # Remove leading numbers
    return name.strip()


@app.route('/sales-processor')
@login_required
def sales_processor_page():
    """Render sales processor page"""
    # Ensure sales tables exist
    db_manager.ensure_sales_tables()
    return render_template('sales_processor.html')


@app.route('/api/sales/process', methods=['POST'])
@login_required
def process_sales_bill():
    """Process an uploaded sales bill image/PDF and extract data using Gemini Vision"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf', '.webp'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400

        # Save file with sales_ prefix
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_filename = f"sales_{timestamp}_{filename}"
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)

        file.save(temp_path)

        # Auto-extract project name from original filename
        project_name = extract_project_from_filename(file.filename)

        # Process the bill (uses same AI extraction as purchase bills)
        results = process_bill_file(temp_path, filename)

        # Save to database (with duplicate check)
        db_results = []
        for bill in results:
            if bill.get('success'):
                invoice_number = bill.get('data', {}).get('invoice_header', {}).get('invoice_number', '')

                # Check for duplicate invoice before saving
                existing_bill = db_manager.check_duplicate_sales_invoice(invoice_number)
                if existing_bill:
                    db_results.append({
                        'saved': False,
                        'invoice_id': None,
                        'db_error': 'Duplicate invoice',
                        'is_duplicate': True,
                        'existing_bill': existing_bill
                    })
                    continue

                # Insert into sales tables
                success, invoice_id, error = db_manager.insert_sales_bill(bill)
                db_results.append({
                    'saved': success,
                    'invoice_id': invoice_id,
                    'db_error': error,
                    'is_duplicate': False
                })

                # Auto-assign project name from filename if bill was saved successfully
                if success and invoice_id and project_name:
                    db_manager.update_sales_bill_project(invoice_id, project_name)
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


@app.route('/api/sales/download', methods=['POST'])
@login_required
def download_sales_excel():
    """Generate and download Excel file from extracted sales data"""
    try:
        data = request.json
        results = data.get('results', [])

        if not results:
            return jsonify({'error': 'No data to download'}), 400

        excel_buffer = generate_excel(results)
        filename = f"sales_extracted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

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


@app.route('/api/sales/stored')
@login_required
def get_stored_sales_bills():
    """Get all stored sales bills from database with optional filters"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        project = request.args.get('project', None)
        projects_csv = request.args.get('projects', None)
        date_from = request.args.get('date_from', None)
        date_to = request.args.get('date_to', None)
        added_from = request.args.get('added_from', None)
        added_to = request.args.get('added_to', None)

        projects_list = None
        if projects_csv:
            projects_list = [p.strip() for p in projects_csv.split(',') if p.strip()]
        elif project:
            projects_list = [project]

        bills = db_manager.get_all_sales_bills(limit=limit, offset=offset, projects=projects_list,
                                                date_from=date_from, date_to=date_to,
                                                added_from=added_from, added_to=added_to)
        total = db_manager.get_sales_bill_count(projects=projects_list, date_from=date_from, date_to=date_to,
                                                 added_from=added_from, added_to=added_to)

        return jsonify({
            'success': True,
            'bills': bills,
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sales/stored/<int:invoice_id>')
@login_required
def get_stored_sales_bill_detail(invoice_id):
    """Get detailed sales bill information including line items"""
    try:
        bill = db_manager.get_sales_bill_detail(invoice_id)

        if not bill:
            return jsonify({'success': False, 'error': 'Sales bill not found'}), 404

        return jsonify({
            'success': True,
            'bill': bill
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sales/stored/<int:invoice_id>', methods=['DELETE'])
@login_required
def delete_stored_sales_bill(invoice_id):
    """Delete a stored sales bill"""
    try:
        success = db_manager.delete_sales_bill(invoice_id)

        if success:
            return jsonify({'success': True, 'message': 'Sales bill deleted'})
        else:
            return jsonify({'success': False, 'error': 'Failed to delete sales bill'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sales/stored/<int:invoice_id>/project', methods=['PUT'])
@login_required
def update_sales_bill_project(invoice_id):
    """Update the project field for a sales bill"""
    try:
        data = request.json
        project = data.get('project', '').strip() if data else ''

        success = db_manager.update_sales_bill_project(invoice_id, project)

        if success:
            return jsonify({'success': True, 'message': 'Project updated', 'project': project})
        else:
            return jsonify({'success': False, 'error': 'Failed to update project'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sales/projects')
@login_required
def get_sales_projects():
    """Get all unique project names from sales bills"""
    try:
        projects = db_manager.get_unique_sales_projects()
        return jsonify({
            'success': True,
            'projects': projects
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sales/summary')
@login_required
def get_sales_summary():
    """Get summary statistics for stored sales bills"""
    try:
        project = request.args.get('project', None)
        projects_csv = request.args.get('projects', None)
        date_from = request.args.get('date_from', None)
        date_to = request.args.get('date_to', None)
        added_from = request.args.get('added_from', None)
        added_to = request.args.get('added_to', None)

        projects_list = None
        if projects_csv:
            projects_list = [p.strip() for p in projects_csv.split(',') if p.strip()]
        elif project:
            projects_list = [project]

        query = """
        SELECT
            COUNT(*) as cnt,
            COALESCE(SUM(total_amount), 0) as sum_value,
            COALESCE(SUM(COALESCE(total_cgst, 0) + COALESCE(total_sgst, 0) + COALESCE(total_igst, 0)), 0) as sum_gst,
            COALESCE(SUM(COALESCE(total_cgst, 0)), 0) as sum_cgst,
            COALESCE(SUM(COALESCE(total_sgst, 0)), 0) as sum_sgst,
            COALESCE(SUM(COALESCE(total_igst, 0)), 0) as sum_igst,
            COUNT(DISTINCT vendor_name) as vendor_cnt
        FROM sales_invoices
        WHERE 1=1
        """
        params = []

        if projects_list:
            placeholders = ','.join(['%s'] * len(projects_list))
            query += f" AND project IN ({placeholders})"
            params.extend(projects_list)

        if date_from:
            query += " AND invoice_date >= %s"
            params.append(date_from)

        if date_to:
            query += " AND invoice_date <= %s"
            params.append(date_to)

        if added_from:
            query += " AND DATE(created_at) >= %s"
            params.append(added_from)

        if added_to:
            query += " AND DATE(created_at) <= %s"
            params.append(added_to)

        result = db_manager.fetch_all(query, tuple(params) if params else None)

        if result and len(result) > 0 and result[0] is not None:
            row = result[0]
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


@app.route('/api/sales/stats')
@login_required
def get_sales_stats():
    """Get sales bill stats for hub page"""
    try:
        invoice_count = db_manager.get_sales_bill_count()
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


@app.route('/api/sales/file/<filename>')
@login_required
def serve_sales_file(filename):
    """Serve uploaded sales bill file (PDF or image) for preview"""
    import glob as glob_module

    try:
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if not os.path.exists(file_path):
            # Search for files with sales_ prefix
            pattern = os.path.join(app.config['UPLOAD_FOLDER'], f"sales_*_{filename}")
            matches = glob_module.glob(pattern)

            if matches:
                file_path = sorted(matches)[-1]
            else:
                return jsonify({'success': False, 'error': 'File not found'}), 404

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


@app.route('/api/sales/upload-files', methods=['POST'])
@login_required
def bulk_upload_sales_files():
    """Bulk upload sales bill files without processing."""
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

            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_extensions:
                results.append({
                    'filename': file.filename,
                    'status': 'skipped',
                    'reason': f'Unsupported file type: {ext}'
                })
                skipped_count += 1
                continue

            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            if os.path.exists(file_path):
                results.append({
                    'filename': filename,
                    'status': 'skipped',
                    'reason': 'File already exists'
                })
                skipped_count += 1
                continue

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


@app.route('/api/sales/stored/<int:invoice_id>', methods=['PUT'])
@login_required
def update_stored_sales_bill(invoice_id):
    """Update a stored sales bill with all fields and line items"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        success, error = db_manager.update_sales_bill(invoice_id, data)

        if success:
            return jsonify({'success': True, 'message': 'Sales invoice updated successfully'})
        else:
            return jsonify({'success': False, 'error': error or 'Failed to update sales invoice'}), 500
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



# ============================================================================
# PROJECT SUMMARY - Cross-Bank Consolidated View
# ============================================================================

@app.route('/project-summary')
@login_required
def project_summary():
    """Project Summary page - consolidated view across all banks"""
    return render_template('project_summary.html')


@app.route('/api/project-summary/combined')
@login_required
def get_project_summary_combined():
    """Get combined transaction data from all banks with filters"""
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
                'total_transactions': 0
            },
            'bank_breakdown': [],
            'category_breakdown': [],
            'project_breakdown': [],
            'vendor_breakdown': [],
            'monthly_trend': {'months': [], 'income': [], 'expense': [], 'net': []},
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
        'total_transactions': len(combined)
    }

    # Bank-wise breakdown
    bank_breakdown = []
    for bank_code in VALID_BANK_CODES:
        bank_df = combined[combined['bank'] == bank_code]
        if bank_df.empty:
            continue
        bank_config = get_bank_config(bank_code)
        b_income = float(bank_df['CR Amount'].sum())
        b_expense = float(bank_df['DR Amount'].sum())
        bank_breakdown.append({
            'bank_code': bank_code,
            'bank_name': bank_config['name'],
            'color': bank_config['color'],
            'income': b_income,
            'income_formatted': format_indian_number(b_income),
            'expense': b_expense,
            'expense_formatted': format_indian_number(b_expense),
            'net': b_income - b_expense,
            'net_formatted': format_indian_number(b_income - b_expense),
            'transaction_count': len(bank_df)
        })

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

    # Project breakdown — smart stem-grouped with material, other expense, labour
    project_col = 'Project' if 'Project' in combined.columns else 'project'
    v_col = 'Client/Vendor' if 'Client/Vendor' in combined.columns else 'client_vendor'
    LABOUR_CATS_API = {'LABOUR PAYMENT', 'LABOR PAYMENT', 'LABOUR', 'LABOR'}
    EXCLUDE_CATS_API = {'MATERIAL PURCHASE', 'AMOUNT RECEIVED', 'SALARY AC', 'BANK CHARGES', 'DUTIES & TAX'}

    project_breakdown = []
    try:
        # Collect project names from bank txns
        bank_proj_names = []
        if project_col in combined.columns:
            bank_proj_names = [str(p) for p in combined[project_col].dropna().unique()
                               if str(p).strip() and str(p).lower() != 'nan']

        # Fetch bills with line items
        try:
            api_bills = db_manager.get_bills_with_line_items_for_export(
                start_date=start_date, end_date=end_date)
        except:
            api_bills = []

        # Filter bills by project stems when a project filter is active
        if project and project != 'All':
            proj_stems = get_project_stems(project)
            if proj_stems:
                api_bills = [b for b in api_bills
                             if any(str(b.get('project', '')).lower().strip().startswith(s)
                                    for s in proj_stems)]

        bill_proj_names = [str(b.get('project', '')) for b in api_bills
                           if str(b.get('project', '')).strip() and str(b.get('project', '')).lower() != 'nan']

        # Build stem groups
        api_stem_groups = build_smart_project_groups(bank_proj_names, bill_proj_names)
        api_bills_by_stem = match_bills_to_project_groups(api_bills, api_stem_groups)

        # Fetch labour costs
        try:
            api_labour_raw = DatabaseManager.get_labour_costs_by_project(
                start_date=start_date, end_date=end_date)
            # Filter labour by project stems when a project filter is active
            if project and project != 'All':
                proj_stems = get_project_stems(project)
                if proj_stems:
                    api_labour_raw = {k: v for k, v in api_labour_raw.items()
                                      if any(k.lower().strip().startswith(s) for s in proj_stems)}
            api_labour_by_stem = match_labour_to_project_groups(api_labour_raw, api_stem_groups)
        except:
            api_labour_by_stem = {}

        for stem in sorted(api_stem_groups.keys()):
            project_names = api_stem_groups[stem]
            group_label = stem.upper()
            proj_list = ', '.join(sorted(str(p) for p in project_names if str(p) != 'nan'))

            # --- Material total from bills ---
            group_bills = api_bills_by_stem.get(stem, [])
            material_total = 0
            for bill in group_bills:
                if bill.get('line_items'):
                    for item in bill['line_items']:
                        material_total += item.get('amount', 0)
                else:
                    material_total += bill.get('total_amount', 0)

            # --- Income + Other expense totals from bank txns ---
            income_total = 0
            other_total = 0
            if project_col in combined.columns:
                g_mask = combined[project_col].isin(project_names)
                g_df = combined[g_mask]
                if not g_df.empty:
                    if 'CR Amount' in g_df.columns:
                        income_total = float(g_df['CR Amount'].sum())

                    exp_df = g_df[g_df['DR Amount'] > 0].copy()
                    if 'Category' in exp_df.columns:
                        upper_cats = exp_df['Category'].str.upper().str.strip()
                        labour_mask = upper_cats.isin(LABOUR_CATS_API)
                        exclude_mask = exp_df['Category'].isin(EXCLUDE_CATS_API) | labour_mask
                        exp_df = exp_df[~exclude_mask]
                    if not exp_df.empty:
                        other_total = float(exp_df['DR Amount'].sum())

            # --- Labour from salary DB ---
            labour_total = api_labour_by_stem.get(stem, 0)

            total_value = material_total + other_total + labour_total

            project_breakdown.append({
                'stem': stem,
                'project': group_label,
                'project_names': proj_list,
                'income': income_total,
                'income_formatted': format_indian_number(income_total),
                'total_value': total_value,
                'total_value_formatted': format_indian_number(total_value),
                'material_total': material_total,
                'material_total_formatted': format_indian_number(material_total),
                'other_total': other_total,
                'other_total_formatted': format_indian_number(other_total),
                'labour_total': labour_total,
                'labour_total_formatted': format_indian_number(labour_total),
            })
        project_breakdown.sort(key=lambda x: x['total_value'], reverse=True)
    except Exception as e:
        print(f"[!] Project breakdown API error: {e}")
        import traceback
        traceback.print_exc()

    # Monthly trend
    monthly_trend = {'months': [], 'income': [], 'expense': [], 'net': []}
    if not combined.empty and 'month_name' in combined.columns:
        monthly = combined.groupby('month_name').agg({
            'CR Amount': 'sum',
            'DR Amount': 'sum',
            'date': 'first'
        }).reset_index().sort_values('date')
        monthly_trend = {
            'months': monthly['month_name'].tolist(),
            'income': [float(x) for x in monthly['CR Amount'].tolist()],
            'expense': [float(x) for x in monthly['DR Amount'].tolist()],
            'net': [float(i - e) for i, e in zip(monthly['CR Amount'], monthly['DR Amount'])]
        }

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
        'bank_breakdown': bank_breakdown,
        'category_breakdown': category_breakdown,
        'project_breakdown': project_breakdown,
        'vendor_breakdown': vendor_breakdown,
        'monthly_trend': monthly_trend,
        'transactions': transactions_list,
        'bank_transactions': bank_transactions
    })


@app.route('/api/project-summary/bank-transactions')
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

    transactions = []
    for _, row in page_df.iterrows():
        transactions.append({
            'date': row['date'].strftime('%Y-%m-%d') if pd.notna(row['date']) else '',
            'description': str(row.get('Description', row.get('transaction_description', ''))),
            'vendor': str(row.get('Client/Vendor', row.get('client_vendor', 'Unknown'))),
            'category': str(row.get('Category', 'Uncategorized')),
            'dr_amount': float(row.get('DR Amount', 0)),
            'cr_amount': float(row.get('CR Amount', 0)),
            'dr_formatted': format_indian_number(float(row.get('DR Amount', 0))) if float(row.get('DR Amount', 0)) > 0 else '',
            'cr_formatted': format_indian_number(float(row.get('CR Amount', 0))) if float(row.get('CR Amount', 0)) > 0 else '',
            'project': str(row.get('Project', row.get('project', ''))) if pd.notna(row.get('Project', row.get('project', ''))) else ''
        })

    return jsonify({
        'transactions': transactions,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages
    })


@app.route('/api/project-summary/vendors')
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


@app.route('/api/project-summary/projects')
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


@app.route('/api/project-summary/filter-options')
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


@app.route('/api/project-summary/bills')
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


@app.route('/api/project-summary/sales-bills')
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


@app.route('/api/project-summary/date-range')
@login_required
def get_project_summary_date_range():
    """Get min/max date range across all banks"""
    min_date = None
    max_date = None

    for bank_code in VALID_BANK_CODES:
        df = get_bank_df(bank_code)
        if df.empty:
            continue

        bank_min = df['date'].min()
        bank_max = df['date'].max()

        if min_date is None or bank_min < min_date:
            min_date = bank_min
        if max_date is None or bank_max > max_date:
            max_date = bank_max

    return jsonify({
        'min_date': min_date.strftime('%Y-%m-%d') if min_date else None,
        'max_date': max_date.strftime('%Y-%m-%d') if max_date else None
    })


@app.route('/api/project-summary/export')
@login_required
def export_project_summary():
    """Export professional project summary report as multi-tab Excel"""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    category = request.args.get('category', None)
    vendor = request.args.get('vendor', None)

    # Gather combined data
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
        combined = pd.DataFrame()
    else:
        combined = pd.concat(combined_rows, ignore_index=True)

    # Style constants
    header_font = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
    title_font = Font(name='Calibri', bold=True, size=14, color='1A1A2E')
    subtitle_font = Font(name='Calibri', bold=True, size=11, color='4A4A68')
    currency_fmt = '#,##0.00'
    pct_fmt = '0.0%'
    thin_border = Border(
        bottom=Side(style='thin', color='E5E7EB')
    )
    income_font = Font(name='Calibri', color='059669', bold=True)
    expense_font = Font(name='Calibri', color='DC2626', bold=True)
    axis_fill = PatternFill(start_color='FDF2F8', end_color='FDF2F8', fill_type='solid')
    kvb_fill = PatternFill(start_color='EFF6FF', end_color='EFF6FF', fill_type='solid')

    def style_header_row(ws, row_num, col_count):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=row_num, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center')

    def auto_width(ws):
        for col_cells in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                try:
                    val = str(cell.value) if cell.value else ''
                    max_len = max(max_len, len(val))
                except:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 3, 40)

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # ──────────────────────────────────────────────────────────
        # TAB 1: Executive Summary
        # ──────────────────────────────────────────────────────────
        kvb_export_df = combined[combined['bank'] == 'kvb'] if not combined.empty else pd.DataFrame()
        axis_export_df = combined[combined['bank'] == 'axis'] if not combined.empty else pd.DataFrame()
        total_income = float(kvb_export_df['CR Amount'].sum()) if not kvb_export_df.empty else 0
        total_bank_transfer = float(axis_export_df['CR Amount'].sum()) if not axis_export_df.empty else 0
        total_credit_all = float(combined['CR Amount'].sum()) if not combined.empty else 0
        total_expense = float(combined['DR Amount'].sum()) if not combined.empty else 0
        txn_count = len(combined) if not combined.empty else 0

        date_label = ''
        if start_date and end_date:
            date_label = f"{start_date} to {end_date}"
        elif start_date:
            date_label = f"From {start_date}"
        elif end_date:
            date_label = f"Up to {end_date}"
        else:
            date_label = 'All Time'

        summary_data = [
            ['VISMA Financial - Project Summary Report'],
            [''],
            ['Report Period', date_label],
            ['Generated On', datetime.now().strftime('%d-%b-%Y %H:%M')],
            [''],
            ['KEY PERFORMANCE INDICATORS'],
            [''],
            ['Metric', 'Value'],
            ['Total Income (KVB)', total_income],
            ['Total Bank Transfer (Axis)', total_bank_transfer],
            ['Total Expense', total_expense],
            ['Total Transactions', txn_count],
            ['Expense Ratio', total_expense / total_income if total_income > 0 else 0],
            ['Average Transaction Size', (total_income + total_bank_transfer + total_expense) / txn_count if txn_count > 0 else 0],
        ]

        # Per-bank KPIs
        summary_data.append([''])
        summary_data.append(['BANK-WISE SUMMARY'])
        summary_data.append([''])
        summary_data.append(['Bank', 'Income / Bank Transfer', 'Expense', 'Net', 'Transactions', '% of Total Expense'])

        for bc in VALID_BANK_CODES:
            if combined.empty:
                continue
            bdf = combined[combined['bank'] == bc]
            if bdf.empty:
                continue
            b_inc = float(bdf['CR Amount'].sum())
            b_exp = float(bdf['DR Amount'].sum())
            b_net = b_inc - b_exp
            b_cnt = len(bdf)
            b_pct = b_exp / total_expense if total_expense > 0 else 0
            bank_name = get_bank_config(bc)['name']
            summary_data.append([bank_name, b_inc, b_exp, b_net, b_cnt, b_pct])

        # Active filters
        summary_data.append([''])
        summary_data.append(['APPLIED FILTERS'])
        summary_data.append([''])
        if project:
            summary_data.append(['Project Filter', project])
        if category:
            summary_data.append(['Category Filter', category])
        if vendor:
            summary_data.append(['Vendor Filter', vendor])
        if not project and not category and not vendor:
            summary_data.append(['Filters', 'None (all data)'])

        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name='Executive Summary', index=False, header=False)

        ws = writer.sheets['Executive Summary']
        ws.cell(row=1, column=1).font = title_font
        ws.cell(row=6, column=1).font = subtitle_font
        ws.cell(row=8, column=1).font = header_font
        ws.cell(row=8, column=1).fill = header_fill
        ws.cell(row=8, column=2).font = header_font
        ws.cell(row=8, column=2).fill = header_fill

        # Format currency cells
        for r in range(9, 15):
            cell = ws.cell(row=r, column=2)
            if r == 12:  # Transaction count
                pass
            elif r == 13:  # Expense ratio
                cell.number_format = pct_fmt
            else:
                cell.number_format = currency_fmt
            if r == 9:   # Total Income (KVB)
                cell.font = income_font
            elif r == 10:  # Total Bank Transfer (Axis)
                cell.font = Font(color='2563EB', bold=True)
            elif r == 11:  # Total Expense
                cell.font = expense_font

        # Style bank summary header
        bank_header_row = None
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=1):
            for cell in row:
                if cell.value == 'Bank':
                    bank_header_row = cell.row
                    break
        if bank_header_row:
            style_header_row(ws, bank_header_row, 6)
            for r in range(bank_header_row + 1, ws.max_row + 1):
                c = ws.cell(row=r, column=1)
                if c.value and ('Axis' in str(c.value) or 'KVB' in str(c.value) or 'Karur' in str(c.value)):
                    for col in range(2, 5):
                        ws.cell(row=r, column=col).number_format = currency_fmt
                    ws.cell(row=r, column=6).number_format = pct_fmt

        # Style filters header
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=1):
            for cell in row:
                if cell.value == 'BANK-WISE SUMMARY' or cell.value == 'APPLIED FILTERS':
                    cell.font = subtitle_font

        auto_width(ws)
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 20

        # ──────────────────────────────────────────────────────────
        # TAB 2: Expense Breakdown (by Category)
        # ──────────────────────────────────────────────────────────
        if not combined.empty:
            expense_df = combined[combined['DR Amount'] > 0]
            if not expense_df.empty:
                cat_data = expense_df.groupby('Category').agg(
                    Total_Expense=('DR Amount', 'sum')
                ).sort_values('Total_Expense', ascending=False).reset_index()

                total_exp = cat_data['Total_Expense'].sum()

                cat_data.columns = ['Category', 'Total Expense']

                cat_data.to_excel(writer, sheet_name='Expense Breakdown', index=False, startrow=2)
                ws2 = writer.sheets['Expense Breakdown']
                ws2.cell(row=1, column=1, value='Expense Breakdown by Category').font = title_font
                style_header_row(ws2, 3, 2)

                for r in range(4, 4 + len(cat_data)):
                    ws2.cell(row=r, column=2).number_format = currency_fmt

                # Add total row
                total_row = 4 + len(cat_data)
                ws2.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
                ws2.cell(row=total_row, column=2, value=total_exp).font = Font(bold=True)
                ws2.cell(row=total_row, column=2).number_format = currency_fmt

                auto_width(ws2)
            else:
                pd.DataFrame({'Note': ['No expense data for the selected filters']}).to_excel(
                    writer, sheet_name='Expense Breakdown', index=False)

        # ──────────────────────────────────────────────────────────
        # TAB 3: Cashflow Analysis (by Project)
        # ──────────────────────────────────────────────────────────
        if not combined.empty:
            project_col = 'Project' if 'Project' in combined.columns else 'project'
            if project_col in combined.columns:
                proj_income = combined.groupby(project_col)['CR Amount'].sum()
                proj_expense = combined.groupby(project_col)['DR Amount'].sum()
                all_projects_list = sorted(set(proj_income.index) | set(proj_expense.index))

                proj_rows = []
                for p in all_projects_list:
                    p_inc = float(proj_income.get(p, 0))
                    p_exp = float(proj_expense.get(p, 0))
                    proj_rows.append({
                        'Project': str(p) if p and str(p) != 'nan' else 'Unassigned',
                        'Income': p_inc, 'Expense': p_exp
                    })

                df_proj = pd.DataFrame(proj_rows).sort_values('Expense', ascending=False)
                df_proj.to_excel(writer, sheet_name='Cashflow Analysis', index=False, startrow=2)

                ws3 = writer.sheets['Cashflow Analysis']
                ws3.cell(row=1, column=1, value='Project Cashflow Analysis').font = title_font
                style_header_row(ws3, 3, 3)

                for r in range(4, 4 + len(df_proj)):
                    for c in [2, 3]:
                        ws3.cell(row=r, column=c).number_format = currency_fmt

                # Add total row
                total_row = 4 + len(df_proj)
                ws3.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
                ws3.cell(row=total_row, column=2, value=total_credit_all).font = Font(bold=True)
                ws3.cell(row=total_row, column=2).number_format = currency_fmt
                ws3.cell(row=total_row, column=3, value=total_expense).font = Font(bold=True)
                ws3.cell(row=total_row, column=3).number_format = currency_fmt

                auto_width(ws3)

        # ──────────────────────────────────────────────────────────
        # TAB 4: Vendor Breakdown
        # ──────────────────────────────────────────────────────────
        if not combined.empty:
            expense_df = combined[combined['DR Amount'] > 0]
            vendor_col = 'Client/Vendor' if 'Client/Vendor' in combined.columns else 'client_vendor'
            if vendor_col in combined.columns and not expense_df.empty:
                vendor_data = expense_df.groupby(vendor_col).agg(
                    Total_Expense=('DR Amount', 'sum')
                ).sort_values('Total_Expense', ascending=False).reset_index()

                total_v_exp = vendor_data['Total_Expense'].sum()

                vendor_data.columns = ['Vendor', 'Total Expense']

                vendor_data.to_excel(writer, sheet_name='Vendor Breakdown', index=False, startrow=2)

                ws4 = writer.sheets['Vendor Breakdown']
                ws4.cell(row=1, column=1, value='Vendor Expense Breakdown').font = title_font
                style_header_row(ws4, 3, 2)

                for r in range(4, 4 + len(vendor_data)):
                    ws4.cell(row=r, column=2).number_format = currency_fmt

                # Total row
                total_row = 4 + len(vendor_data)
                ws4.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
                ws4.cell(row=total_row, column=2, value=total_v_exp).font = Font(bold=True)
                ws4.cell(row=total_row, column=2).number_format = currency_fmt

                auto_width(ws4)
            else:
                pd.DataFrame({'Note': ['No vendor expense data for the selected filters']}).to_excel(
                    writer, sheet_name='Vendor Breakdown', index=False)

        # ──────────────────────────────────────────────────────────
        # TAB 5 & 6: Bank-wise Transactions (one tab per bank)
        # ──────────────────────────────────────────────────────────
        for bc in VALID_BANK_CODES:
            bank_config = get_bank_config(bc)
            sheet_name = f"{bank_config['name']} Txns"
            if len(sheet_name) > 31:
                sheet_name = sheet_name[:31]

            if combined.empty:
                pd.DataFrame({'Note': ['No data']}).to_excel(writer, sheet_name=sheet_name, index=False)
                continue

            bdf = combined[combined['bank'] == bc].sort_values('date', ascending=False).copy()
            if bdf.empty:
                pd.DataFrame({'Note': [f'No transactions for {bank_config["name"]}']}).to_excel(
                    writer, sheet_name=sheet_name, index=False)
                continue

            bdf['Date'] = bdf['date'].dt.strftime('%d-%m-%Y')
            export_cols = {
                'Date': 'Date',
                'Client/Vendor': 'Vendor',
                'Category': 'Category',
                'Project': 'Project',
                'DR Amount': 'Debit (₹)',
                'CR Amount': 'Credit (₹)'
            }

            df_export = pd.DataFrame()
            for src, dst in export_cols.items():
                if src in bdf.columns:
                    df_export[dst] = bdf[src]
                elif src.lower() in bdf.columns:
                    df_export[dst] = bdf[src.lower()]
                else:
                    df_export[dst] = None

            df_export.to_excel(writer, sheet_name=sheet_name, index=False, startrow=2)

            ws_b = writer.sheets[sheet_name]
            ws_b.cell(row=1, column=1, value=f'{bank_config["name"]} - Transaction Details').font = title_font
            style_header_row(ws_b, 3, len(df_export.columns))

            for r in range(4, 4 + len(df_export)):
                ws_b.cell(row=r, column=5).number_format = currency_fmt
                ws_b.cell(row=r, column=6).number_format = currency_fmt
                dr_val = ws_b.cell(row=r, column=5).value
                cr_val = ws_b.cell(row=r, column=6).value
                if dr_val and float(dr_val) > 0:
                    ws_b.cell(row=r, column=5).font = expense_font
                if cr_val and float(cr_val) > 0:
                    ws_b.cell(row=r, column=6).font = income_font

            # Bank subtotals
            total_row = 4 + len(df_export)
            ws_b.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
            ws_b.cell(row=total_row, column=5, value=float(bdf['DR Amount'].sum())).font = Font(bold=True)
            ws_b.cell(row=total_row, column=5).number_format = currency_fmt
            ws_b.cell(row=total_row, column=6, value=float(bdf['CR Amount'].sum())).font = Font(bold=True)
            ws_b.cell(row=total_row, column=6).number_format = currency_fmt

            auto_width(ws_b)

        # ──────────────────────────────────────────────────────────
        # TAB 7 & 8: Purchase Bills / Sales Bills (project-grouped)
        # ──────────────────────────────────────────────────────────
        # Shared auditor-format styles (reused by Project Breakdown tab too)
        green_fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        block_bg = PatternFill(start_color='FFFDE7', end_color='FFFDE7', fill_type='solid')  # mild yellow
        project_name_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        project_name_font = Font(name='Calibri', bold=True, size=14, color='FFFFFF')
        separator_fill = PatternFill(start_color='2F2F2F', end_color='2F2F2F', fill_type='solid')

        # Shared helper: writes a project-grouped bills sheet
        def write_bills_sheet(ws, bills_by_stem_local, stem_groups_local,
                              sheet_title, party_label, party_key, gstin_key,
                              total_font):
            """Write a project-grouped bills sheet with expanded line items.

            party_label: 'VENDOR' or 'BUYER'
            party_key: 'vendor_name' or 'buyer_name'
            gstin_key: 'vendor_gstin' or 'buyer_gstin'
            total_font: font colour for totals (red_amount or green_amount-like)
            """
            BILL_COLS = 14  # SL.NO, Party, GSTIN, Invoice#, Date, Description, HSN/SAC, QTY, UOM, RATE, TAXABLE, CGST, SGST, IGST
            bill_header_labels = [
                'SL.NO', party_label, 'GSTIN', 'INVOICE #', 'DATE',
                'DESCRIPTION', 'HSN/SAC', 'QTY', 'UOM', 'RATE',
                'TAXABLE AMT', 'CGST', 'SGST', 'IGST'
            ]
            bill_currency_cols = [10, 11, 12, 13, 14]  # RATE, TAXABLE, CGST, SGST, IGST

            ws.cell(row=1, column=1, value=sheet_title).font = title_font
            cr = 3  # current row
            grand_taxable = 0
            grand_cgst = 0
            grand_sgst = 0
            grand_igst = 0
            grand_total = 0
            bill_serial = 0

            for stem in sorted(stem_groups_local.keys()):
                group_bills = bills_by_stem_local.get(stem, [])
                if not group_bills:
                    continue

                project_names = stem_groups_local[stem]
                group_label = stem.upper()
                proj_list = ', '.join(sorted(str(p) for p in project_names if str(p) != 'nan'))

                block_start = cr

                # ── PROJECT HEADER (blue fill, white text) ──
                for c in range(1, BILL_COLS + 1):
                    ws.cell(row=cr, column=c).fill = project_name_fill
                ws.cell(row=cr, column=1,
                        value=f'PROJECT :  {group_label}').font = project_name_font
                cr += 1

                # Variant names
                ws.cell(row=cr, column=1,
                        value=f'({proj_list})').font = Font(
                    name='Calibri', italic=True, color='6B7280', size=9)
                cr += 2

                # ── COLUMN HEADERS ──
                for ci, lbl in enumerate(bill_header_labels, 1):
                    cell = ws.cell(row=cr, column=ci, value=lbl)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                cr += 1

                proj_taxable = 0
                proj_cgst = 0
                proj_sgst = 0
                proj_igst = 0
                proj_total = 0

                for bill in group_bills:
                    bill_serial += 1
                    line_items = bill.get('line_items', [])
                    b_taxable = float(bill.get('subtotal', 0) or 0)
                    b_cgst = float(bill.get('total_cgst', 0) or 0)
                    b_sgst = float(bill.get('total_sgst', 0) or 0)
                    b_igst = float(bill.get('total_igst', 0) or 0)
                    b_total = float(bill.get('total_amount', 0) or 0)

                    if line_items:
                        # First line item shares the row with bill header info
                        for li_idx, item in enumerate(line_items):
                            if li_idx == 0:
                                ws.cell(row=cr, column=1, value=bill_serial)
                                ws.cell(row=cr, column=2, value=bill.get(party_key, ''))
                                ws.cell(row=cr, column=3, value=bill.get(gstin_key, ''))
                                ws.cell(row=cr, column=4, value=bill.get('invoice_number', ''))
                                ws.cell(row=cr, column=5, value=bill.get('invoice_date', ''))
                            # Line item detail columns
                            ws.cell(row=cr, column=6, value=item.get('description', ''))
                            ws.cell(row=cr, column=7, value=item.get('hsn_sac_code', ''))
                            qty = item.get('quantity', 0)
                            if qty:
                                ws.cell(row=cr, column=8, value=qty)
                                ws.cell(row=cr, column=8).number_format = '#,##0.00'
                            ws.cell(row=cr, column=9, value=item.get('uom', ''))
                            rate = item.get('rate_per_unit', 0)
                            if rate:
                                ws.cell(row=cr, column=10, value=rate)
                                ws.cell(row=cr, column=10).number_format = currency_fmt
                            taxable = item.get('taxable_value', 0)
                            if taxable:
                                ws.cell(row=cr, column=11, value=taxable)
                                ws.cell(row=cr, column=11).number_format = currency_fmt
                            item_cgst = item.get('cgst_amount', 0)
                            if item_cgst:
                                ws.cell(row=cr, column=12, value=item_cgst)
                                ws.cell(row=cr, column=12).number_format = currency_fmt
                            item_sgst = item.get('sgst_amount', 0)
                            if item_sgst:
                                ws.cell(row=cr, column=13, value=item_sgst)
                                ws.cell(row=cr, column=13).number_format = currency_fmt
                            item_igst = item.get('igst_amount', 0)
                            if item_igst:
                                ws.cell(row=cr, column=14, value=item_igst)
                                ws.cell(row=cr, column=14).number_format = currency_fmt
                            cr += 1
                    else:
                        # Bill with no line items - single row with bill totals
                        ws.cell(row=cr, column=1, value=bill_serial)
                        ws.cell(row=cr, column=2, value=bill.get(party_key, ''))
                        ws.cell(row=cr, column=3, value=bill.get(gstin_key, ''))
                        ws.cell(row=cr, column=4, value=bill.get('invoice_number', ''))
                        ws.cell(row=cr, column=5, value=bill.get('invoice_date', ''))
                        ws.cell(row=cr, column=11, value=b_taxable)
                        ws.cell(row=cr, column=11).number_format = currency_fmt
                        ws.cell(row=cr, column=12, value=b_cgst)
                        ws.cell(row=cr, column=12).number_format = currency_fmt
                        ws.cell(row=cr, column=13, value=b_sgst)
                        ws.cell(row=cr, column=13).number_format = currency_fmt
                        ws.cell(row=cr, column=14, value=b_igst)
                        ws.cell(row=cr, column=14).number_format = currency_fmt
                        cr += 1

                    # ── Bill Total row ──
                    ws.cell(row=cr, column=6, value='Bill Total').font = Font(bold=True)
                    ws.cell(row=cr, column=11, value=b_taxable).font = Font(bold=True)
                    ws.cell(row=cr, column=11).number_format = currency_fmt
                    ws.cell(row=cr, column=12, value=b_cgst).font = Font(bold=True)
                    ws.cell(row=cr, column=12).number_format = currency_fmt
                    ws.cell(row=cr, column=13, value=b_sgst).font = Font(bold=True)
                    ws.cell(row=cr, column=13).number_format = currency_fmt
                    ws.cell(row=cr, column=14, value=b_igst).font = Font(bold=True)
                    ws.cell(row=cr, column=14).number_format = currency_fmt
                    # Thin bottom border on bill total row
                    for c in range(1, BILL_COLS + 1):
                        ws.cell(row=cr, column=c).border = thin_border
                    cr += 1

                    proj_taxable += b_taxable
                    proj_cgst += b_cgst
                    proj_sgst += b_sgst
                    proj_igst += b_igst
                    proj_total += b_total

                # ── PROJECT TOTAL (green fill) ──
                for c in range(1, BILL_COLS + 1):
                    ws.cell(row=cr, column=c).fill = green_fill
                ws.cell(row=cr, column=1, value=f'PROJECT TOTAL — {group_label}').font = Font(bold=True)
                ws.cell(row=cr, column=11, value=proj_taxable).font = total_font
                ws.cell(row=cr, column=11).number_format = currency_fmt
                ws.cell(row=cr, column=12, value=proj_cgst).font = total_font
                ws.cell(row=cr, column=12).number_format = currency_fmt
                ws.cell(row=cr, column=13, value=proj_sgst).font = total_font
                ws.cell(row=cr, column=13).number_format = currency_fmt
                ws.cell(row=cr, column=14, value=proj_igst).font = total_font
                ws.cell(row=cr, column=14).number_format = currency_fmt
                cr += 1

                # Yellow background on all content rows in this block
                for r in range(block_start, cr):
                    for c in range(1, BILL_COLS + 1):
                        cell = ws.cell(row=r, column=c)
                        if cell.fill == PatternFill(fill_type=None) or cell.fill == PatternFill():
                            cell.fill = block_bg

                # ── Dark separator ──
                for c in range(1, BILL_COLS + 1):
                    ws.cell(row=cr, column=c).fill = separator_fill
                cr += 2

                grand_taxable += proj_taxable
                grand_cgst += proj_cgst
                grand_sgst += proj_sgst
                grand_igst += proj_igst
                grand_total += proj_total

            # ── GRAND TOTAL ──
            if grand_total > 0:
                ws.cell(row=cr, column=1, value='GRAND TOTAL').font = Font(bold=True, size=12)
                ws.cell(row=cr, column=11, value=grand_taxable).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=11).number_format = currency_fmt
                ws.cell(row=cr, column=12, value=grand_cgst).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=12).number_format = currency_fmt
                ws.cell(row=cr, column=13, value=grand_sgst).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=13).number_format = currency_fmt
                ws.cell(row=cr, column=14, value=grand_igst).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=14).number_format = currency_fmt

            # Column widths
            col_widths = {
                'A': 8, 'B': 28, 'C': 18, 'D': 18, 'E': 14,
                'F': 35, 'G': 12, 'H': 10, 'I': 8, 'J': 12,
                'K': 15, 'L': 12, 'M': 12, 'N': 12
            }
            for col_letter, width in col_widths.items():
                ws.column_dimensions[col_letter].width = width

        # ── Fetch purchase bills and build project groups ──
        try:
            purchase_bills = db_manager.get_bills_with_line_items_for_export(
                start_date=start_date, end_date=end_date
            )
        except Exception as e:
            print(f"[!] Error fetching purchase bills for export: {e}")
            purchase_bills = []

        try:
            sales_bills = db_manager.get_sales_bills_with_line_items_for_export(
                start_date=start_date, end_date=end_date
            )
        except Exception as e:
            print(f"[!] Error fetching sales bills for export: {e}")
            sales_bills = []

        # Collect project names from bank txns, purchase bills, and sales bills
        pb_bank_projects = []
        pb_project_col = 'Project' if 'Project' in combined.columns else 'project' if not combined.empty else 'Project'
        if not combined.empty and pb_project_col in combined.columns:
            pb_bank_projects = [str(p) for p in combined[pb_project_col].dropna().unique()
                                if str(p).strip() and str(p).lower() != 'nan']
        pb_bill_projects = [str(b.get('project', '')) for b in purchase_bills
                            if str(b.get('project', '')).strip() and str(b.get('project', '')).lower() != 'nan']
        sb_bill_projects = [str(b.get('project', '')) for b in sales_bills
                            if str(b.get('project', '')).strip() and str(b.get('project', '')).lower() != 'nan']

        bills_stem_groups = build_smart_project_groups(
            pb_bank_projects, pb_bill_projects + sb_bill_projects
        )

        # Apply project filter if active
        if project:
            proj_stems = get_project_stems(project)
            bills_stem_groups = {
                s: names for s, names in bills_stem_groups.items()
                if s in proj_stems or any(normalize_project_stem(t) in proj_stems
                                          for n in names for t in str(n).split())
            }

        purchase_by_stem = match_bills_to_project_groups(purchase_bills, bills_stem_groups)
        sales_by_stem = match_bills_to_project_groups(sales_bills, bills_stem_groups)

        # TAB 7: Purchase Bills
        wb_tabs = writer.book
        if purchase_by_stem:
            ws_purchase = wb_tabs.create_sheet('Purchase Bills')
            write_bills_sheet(
                ws_purchase, purchase_by_stem, bills_stem_groups,
                sheet_title='Purchase Bills — Project Grouped',
                party_label='VENDOR', party_key='vendor_name',
                gstin_key='vendor_gstin',
                total_font=Font(name='Calibri', bold=True, color='DC2626')
            )
        else:
            pd.DataFrame({'Note': ['No purchase bills for the selected filters']}).to_excel(
                writer, sheet_name='Purchase Bills', index=False)

        # TAB 8: Sales Bills
        if sales_by_stem:
            ws_sales = wb_tabs.create_sheet('Sales Bills')
            write_bills_sheet(
                ws_sales, sales_by_stem, bills_stem_groups,
                sheet_title='Sales Bills — Project Grouped',
                party_label='BUYER', party_key='buyer_name',
                gstin_key='buyer_gstin',
                total_font=Font(name='Calibri', bold=True, color='059669')
            )
        else:
            pd.DataFrame({'Note': ['No sales bills for the selected filters']}).to_excel(
                writer, sheet_name='Sales Bills', index=False)

        # ──────────────────────────────────────────────────────────
        # TAB 9: Project Breakdown (Auditor Format)
        # ──────────────────────────────────────────────────────────
        wb = writer.book
        project_col = 'Project' if 'Project' in combined.columns else 'project' if not combined.empty else 'Project'
        v_col = 'Client/Vendor' if (not combined.empty and 'Client/Vendor' in combined.columns) else 'client_vendor'

        # Auditor-format styling (green_fill, block_bg, project_name_fill/font,
        # separator_fill already defined above for bills tabs)
        section_bold = Font(name='Calibri', bold=True, size=11)
        green_amount = Font(name='Calibri', bold=True, color='006100')
        red_amount = Font(name='Calibri', bold=True, color='DC2626')
        blue_amount = Font(name='Calibri', bold=True, color='2563EB')
        pb_currency = '#,##0.00'
        WEIGHT_UOMS = {'KGS', 'KG', 'MT', 'TONS', 'TON', 'MTS'}
        # Exclude these from Other Expense; LABOUR categories go to LABOUR PAYMENT
        EXCLUDE_CATS = {'MATERIAL PURCHASE', 'AMOUNT RECEIVED', 'SALARY AC', 'BANK CHARGES', 'DUTIES & TAX'}
        LABOUR_CATS = {'LABOUR PAYMENT', 'LABOR PAYMENT', 'LABOUR', 'LABOR'}
        NUM_COLS = 3  # A, B, C

        def pb_section_header(ws, row, text):
            """Green-filled section header spanning all columns."""
            ws.cell(row=row, column=1, value=text).font = section_bold
            for c in range(1, NUM_COLS + 1):
                ws.cell(row=row, column=c).fill = green_fill
            return row + 1

        def pb_separator(ws, row):
            """Dark separator row between project blocks."""
            for c in range(1, NUM_COLS + 1):
                ws.cell(row=row, column=c).fill = separator_fill
            return row + 1

        def pb_block_bg(ws, row):
            """Apply mild yellow background to a content row."""
            for c in range(1, NUM_COLS + 1):
                cell = ws.cell(row=row, column=c)
                if cell.fill == PatternFill(fill_type=None) or cell.fill == PatternFill():
                    cell.fill = block_bg

        try:
            export_bills = db_manager.get_bills_with_line_items_for_export(
                start_date=start_date, end_date=end_date
            )
        except Exception as e:
            print(f"[!] Error fetching bills with line items: {e}")
            export_bills = []

        # Collect project names from bank txns and bills
        bank_projects = []
        if not combined.empty and project_col in combined.columns:
            bank_projects = [str(p) for p in combined[project_col].dropna().unique()
                             if str(p).strip() and str(p).lower() != 'nan']
        bill_projects = [str(b.get('project', '')) for b in export_bills
                         if str(b.get('project', '')).strip() and str(b.get('project', '')).lower() != 'nan']

        stem_groups = build_smart_project_groups(bank_projects, bill_projects)
        bills_by_stem = match_bills_to_project_groups(export_bills, stem_groups)

        # Fetch labour costs from salary/attendance DB
        try:
            labour_costs_raw = DatabaseManager.get_labour_costs_by_project(
                start_date=start_date, end_date=end_date
            )
            labour_by_stem = match_labour_to_project_groups(labour_costs_raw, stem_groups)
        except Exception as e:
            print(f"[!] Error matching labour costs: {e}")
            labour_by_stem = {}

        if stem_groups:
            ws_pb = wb.create_sheet('Project Breakdown')
            current_row = 1

            for stem_idx, stem in enumerate(sorted(stem_groups.keys())):
                project_names = stem_groups[stem]
                group_label = stem.upper()
                group_bills = bills_by_stem.get(stem, [])
                proj_list = ', '.join(sorted(str(p) for p in project_names if str(p) != 'nan'))

                # Filter bank transactions for this project group
                if not combined.empty and project_col in combined.columns:
                    group_mask = combined[project_col].isin(project_names)
                    group_df = combined[group_mask]
                else:
                    group_df = pd.DataFrame()

                if group_df.empty and not group_bills:
                    continue

                # Track the first row of this block so we can paint background
                block_start_row = current_row

                # ════════════════════════════════════════════════════════
                # PROJECT NAME — big, bold, blue fill, white text
                # ════════════════════════════════════════════════════════
                for c in range(1, NUM_COLS + 1):
                    ws_pb.cell(row=current_row, column=c).fill = project_name_fill
                ws_pb.cell(row=current_row, column=1,
                           value=f'PROJECT :  {group_label}').font = project_name_font
                current_row += 1

                # Sub-label showing all project name variants
                ws_pb.cell(row=current_row, column=1,
                           value=f'({proj_list})').font = Font(
                    name='Calibri', italic=True, color='6B7280', size=9)
                current_row += 2  # blank row gap

                # ── OVERALL SUMMARY ──
                current_row = pb_section_header(ws_pb, current_row, 'OVERALL SUMMARY')

                # TOTAL PROJECT VALUE row (amount filled at the end)
                ws_pb.cell(row=current_row, column=1, value='TOTAL PROJECT VALUE').font = Font(bold=True)
                total_value_row = current_row
                current_row += 2  # blank row

                # ── MAIN MATERIAL PURCHASE ──
                current_row = pb_section_header(ws_pb, current_row, 'MAIN MATERIAL PURCHASE')

                # Column headers
                ws_pb.cell(row=current_row, column=2, value='WEIGHT').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3, value='AMOUNT').font = Font(bold=True)
                current_row += 1

                # Aggregate bill line items by vendor — vendor name only, total per vendor
                material_total = 0
                if group_bills:
                    vendor_agg = {}  # vendor_name -> {weight, amount}
                    for bill in group_bills:
                        vname = bill.get('vendor_name', 'Unknown Vendor')
                        if vname not in vendor_agg:
                            vendor_agg[vname] = {'weight': 0, 'amount': 0}
                        for item in bill.get('line_items', []):
                            uom = str(item.get('uom', '')).upper().strip()
                            if uom in WEIGHT_UOMS:
                                vendor_agg[vname]['weight'] += item.get('quantity', 0)
                            vendor_agg[vname]['amount'] += item.get('amount', 0)
                        if not bill.get('line_items'):
                            vendor_agg[vname]['amount'] += bill.get('total_amount', 0)

                    for vname, data in sorted(vendor_agg.items(), key=lambda x: x[1]['amount'], reverse=True):
                        ws_pb.cell(row=current_row, column=1, value=vname)
                        if data['weight'] > 0:
                            ws_pb.cell(row=current_row, column=2, value=data['weight'])
                            ws_pb.cell(row=current_row, column=2).number_format = '#,##0.00'
                        ws_pb.cell(row=current_row, column=3, value=data['amount'])
                        ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                        material_total += data['amount']
                        current_row += 1

                # Material total — just the green amount (no duplicate header)
                ws_pb.cell(row=current_row, column=3, value=material_total).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── OTHER EXPENSE ──
                current_row = pb_section_header(ws_pb, current_row, 'OTHER EXPENSE')

                other_total = 0
                if not group_df.empty:
                    expense_df = group_df[group_df['DR Amount'] > 0].copy()
                    if 'Category' in expense_df.columns:
                        # Exclude labour + standard exclusions from other expense
                        upper_cats = expense_df['Category'].str.upper().str.strip()
                        labour_mask = upper_cats.isin(LABOUR_CATS)
                        exclude_mask = expense_df['Category'].isin(EXCLUDE_CATS) | labour_mask
                        expense_df = expense_df[~exclude_mask]

                    if not expense_df.empty and v_col in expense_df.columns:
                        for (vend, cat), grp in expense_df.groupby([v_col, 'Category']):
                            amt = float(grp['DR Amount'].sum())
                            vend_str = str(vend).strip()
                            cat_str = str(cat).strip()
                            if not vend_str or vend_str.lower() in ('unknown', 'nan', '', 'unassigned'):
                                label = cat_str
                            else:
                                label = f"{cat_str} - {vend_str}"
                            ws_pb.cell(row=current_row, column=1, value=label)
                            ws_pb.cell(row=current_row, column=3, value=amt)
                            ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                            other_total += amt
                            current_row += 1
                    elif not expense_df.empty:
                        for cat, grp in expense_df.groupby('Category'):
                            amt = float(grp['DR Amount'].sum())
                            ws_pb.cell(row=current_row, column=1, value=str(cat))
                            ws_pb.cell(row=current_row, column=3, value=amt)
                            ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                            other_total += amt
                            current_row += 1

                # Other expense total (green amount only)
                ws_pb.cell(row=current_row, column=3, value=other_total).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── LABOUR PAYMENT (blue amount, from salary/attendance DB) ──
                salary_labour = labour_by_stem.get(stem, 0)
                ws_pb.cell(row=current_row, column=1, value='LABOUR PAYMENT').font = Font(bold=True)
                if salary_labour > 0:
                    ws_pb.cell(row=current_row, column=3, value=salary_labour).font = blue_amount
                    ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── BALANCE GST PAYMENT ──
                ws_pb.cell(row=current_row, column=1, value='BALANCE GST PAYMENT').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── OVER HEADS ──
                ws_pb.cell(row=current_row, column=1, value='OVER HEADS').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── TOTAL EXP ──
                ws_pb.cell(row=current_row, column=1, value='TOTAL EXP').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── BALANCE ──
                ws_pb.cell(row=current_row, column=1, value='BALANCE').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 1

                # Fill TOTAL PROJECT VALUE (material + other + labour)
                total_project = material_total + other_total + salary_labour
                ws_pb.cell(row=total_value_row, column=3, value=total_project).font = red_amount
                ws_pb.cell(row=total_value_row, column=3).number_format = pb_currency

                block_end_row = current_row

                # Paint mild yellow background on all content rows in this block
                for r in range(block_start_row, block_end_row + 1):
                    pb_block_bg(ws_pb, r)

                # ── Dark separator + gap before next project ──
                current_row += 1
                current_row = pb_separator(ws_pb, current_row)
                current_row += 2

            # Column widths
            ws_pb.column_dimensions['A'].width = 40
            ws_pb.column_dimensions['B'].width = 15
            ws_pb.column_dimensions['C'].width = 20

        # ──────────────────────────────────────────────────────────
        # TAB 10: Labour Attendance & Salary Summary (single month)
        # ──────────────────────────────────────────────────────────
        import calendar as cal
        from datetime import date as date_cls

        labour_sheet_names = []
        try:
            # Determine the single target month from date filters
            # Use end_date's month (or start_date if no end_date)
            target_date_str = end_date or start_date
            if target_date_str:
                from dateutil import parser as dp
                target_dt = dp.parse(str(target_date_str))
                t_year, t_month = target_dt.year, target_dt.month
            else:
                from datetime import date as _d
                today = _d.today()
                t_year, t_month = today.year, today.month

            # Fetch only that single month
            first_day = f"{t_year}-{t_month:02d}-01"
            last_day = f"{t_year}-{t_month:02d}-{cal.monthrange(t_year, t_month)[1]:02d}"
            monthly_data = DatabaseManager.get_monthly_salary_and_attendance(
                start_date=first_day, end_date=last_day
            )

            # Styling for labour sheets
            labour_title_font = Font(name='Calibri', bold=True, size=13, color='1A1A2E')
            labour_header_font = Font(name='Calibri', bold=True, size=10, color='FFFFFF')
            labour_header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
            summary_header_fill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
            sunday_fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')
            present_font = Font(color='006100')
            absent_font = Font(color='DC2626')
            labour_currency = '#,##0.00'

            for month_data in monthly_data[:1]:  # single month only
                sheet_name = f"Labour {month_data['sheet_name']}"
                if len(sheet_name) > 31:
                    sheet_name = sheet_name[:31]
                labour_sheet_names.append(sheet_name)

                ws_l = wb.create_sheet(sheet_name)
                days_in_month = month_data['days_in_month']
                yr = month_data['year']
                mn = month_data['month_num']

                # Build attendance lookup: worker_id -> day -> {status, ot, project}
                att_map = {}
                for a in month_data['attendance']:
                    wid = a['worker_id']
                    try:
                        from dateutil import parser as dp
                        d = dp.parse(str(a['date'])).day
                    except:
                        continue
                    if wid not in att_map:
                        att_map[wid] = {}
                    att_map[wid][d] = {
                        'status': a['status'],
                        'ot': a['ot_hours'],
                        'project': a['project']
                    }

                # ===== ROW 1: Title =====
                ws_l.cell(row=1, column=1,
                          value=f"LABOUR ATTENDANCE FOR {month_data['sheet_name']}").font = labour_title_font
                ws_l.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)

                # ===== ROW 2-3: Headers =====
                # Fixed columns
                fixed_headers = ['S.No', 'Name', 'DESIGNATION', 'TEAM']
                for ci, h in enumerate(fixed_headers, 1):
                    c = ws_l.cell(row=2, column=ci, value=h)
                    c.font = labour_header_font
                    c.fill = labour_header_fill
                    c.alignment = Alignment(horizontal='center')
                    # Row 3 empty for fixed cols
                    ws_l.cell(row=3, column=ci).fill = labour_header_fill

                # Day columns: 3 cols per day (status, OT, project)
                col = 5  # start after fixed
                day_col_starts = {}  # day -> starting column
                for day in range(1, days_in_month + 1):
                    day_col_starts[day] = col
                    dt = date_cls(yr, mn, day)
                    is_sunday = dt.weekday() == 6
                    day_label = f"{day} SUN" if is_sunday else str(day)

                    cell_h1 = ws_l.cell(row=2, column=col, value=day_label)
                    cell_h1.font = labour_header_font
                    cell_h1.fill = sunday_fill if is_sunday else labour_header_fill
                    cell_h1.alignment = Alignment(horizontal='center')
                    # Merge across 3 cols for day header
                    ws_l.merge_cells(start_row=2, start_column=col, end_row=2, end_column=col + 2)

                    # Sub-headers
                    for si, sub in enumerate(['', 'OT', 'Pr']):
                        sc = ws_l.cell(row=3, column=col + si, value=sub)
                        sc.font = Font(size=8, bold=True)
                        sc.fill = sunday_fill if is_sunday else labour_header_fill
                        if not is_sunday:
                            sc.font = Font(size=8, bold=True, color='FFFFFF')
                        sc.alignment = Alignment(horizontal='center')
                    col += 3

                # Summary column headers
                summary_start_col = col
                sum_headers = ['TOTAL PRESENT', 'TOTAL OT', 'BASE SALARY',
                               'BASE PAY', 'OT PAY', 'TOTAL SALARY']
                # Main header merged across summary cols
                ws_l.cell(row=2, column=summary_start_col,
                          value=f"{month_data['sheet_name']} MONTH LABOUR ATTENDANCE & PAYMENT").font = Font(
                    bold=True, size=9, color='FFFFFF')
                ws_l.cell(row=2, column=summary_start_col).fill = summary_header_fill
                for c in range(summary_start_col, summary_start_col + 6):
                    ws_l.cell(row=2, column=c).fill = summary_header_fill
                ws_l.merge_cells(start_row=2, start_column=summary_start_col,
                                 end_row=2, end_column=summary_start_col + 5)
                for si, sh in enumerate(sum_headers):
                    sc = ws_l.cell(row=3, column=summary_start_col + si, value=sh)
                    sc.font = Font(bold=True, size=8, color='FFFFFF')
                    sc.fill = summary_header_fill
                    sc.alignment = Alignment(horizontal='center')

                # ===== DATA ROWS (one per worker) =====
                data_row = 4
                sno = 1
                for w in month_data['workers']:
                    ws_l.cell(row=data_row, column=1, value=sno)
                    ws_l.cell(row=data_row, column=2, value=w['name'])
                    ws_l.cell(row=data_row, column=3, value=w['designation'])
                    ws_l.cell(row=data_row, column=4, value=w['team'])

                    # Day-by-day columns
                    for day in range(1, days_in_month + 1):
                        dc = day_col_starts[day]
                        att = att_map.get(w['worker_id'], {}).get(day)
                        if att:
                            status_cell = ws_l.cell(row=data_row, column=dc, value=att['status'])
                            if att['status'] == 'P':
                                status_cell.font = present_font
                            elif att['status'] == 'A':
                                status_cell.font = absent_font
                            if att['ot']:
                                ws_l.cell(row=data_row, column=dc + 1, value=att['ot'])
                            if att['project']:
                                ws_l.cell(row=data_row, column=dc + 2, value=att['project'])

                    # Summary columns
                    ws_l.cell(row=data_row, column=summary_start_col, value=w['working_days'])
                    ws_l.cell(row=data_row, column=summary_start_col + 1, value=w['ot_hours'])
                    ws_l.cell(row=data_row, column=summary_start_col + 2,
                              value=w['base_salary_per_day']).number_format = labour_currency
                    ws_l.cell(row=data_row, column=summary_start_col + 3,
                              value=w['base_pay']).number_format = labour_currency
                    ws_l.cell(row=data_row, column=summary_start_col + 4,
                              value=w['ot_pay']).number_format = labour_currency
                    ws_l.cell(row=data_row, column=summary_start_col + 5,
                              value=w['total_salary']).number_format = labour_currency

                    sno += 1
                    data_row += 1

                # ===== SUMMARY SECTIONS =====
                data_row += 1  # blank row

                # Monthly Summary
                ws_l.cell(row=data_row, column=1, value='MONTHLY SUMMARY').font = Font(bold=True, size=11)
                ws_l.cell(row=data_row, column=1).fill = PatternFill(
                    start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
                data_row += 1

                total_workers = len(month_data['workers'])
                total_present = sum(w['working_days'] for w in month_data['workers'])
                total_ot = sum(w['ot_hours'] for w in month_data['workers'])
                total_sal = month_data['total_salary']

                kpi_labels = ['Total Workers', 'Total Present Days', 'Total OT Hours', 'Total Salary']
                kpi_values = [total_workers, total_present, round(total_ot, 2), total_sal]
                for ki, (kl, kv) in enumerate(zip(kpi_labels, kpi_values)):
                    c = ki * 3
                    ws_l.cell(row=data_row, column=c + 1, value=kl).font = Font(bold=True)
                    cell = ws_l.cell(row=data_row, column=c + 2, value=kv)
                    if kl == 'Total Salary':
                        cell.number_format = labour_currency
                        cell.font = Font(bold=True, color='006100')
                data_row += 2

                # Project Breakdown
                ws_l.cell(row=data_row, column=1, value='PROJECT BREAKDOWN').font = Font(bold=True, size=11)
                ws_l.cell(row=data_row, column=1).fill = PatternFill(
                    start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
                data_row += 1

                pb_headers = ['Project', 'Workers', 'Working Days', 'OT Hours']
                for ci, h in enumerate(pb_headers, 1):
                    c = ws_l.cell(row=data_row, column=ci, value=h)
                    c.font = Font(bold=True, color='FFFFFF', size=9)
                    c.fill = labour_header_fill
                data_row += 1

                for proj in sorted(month_data['project_breakdown'], key=lambda x: x['name']):
                    ws_l.cell(row=data_row, column=1, value=proj['name'])
                    ws_l.cell(row=data_row, column=2, value=proj['workers'])
                    ws_l.cell(row=data_row, column=3, value=proj['working_days'])
                    ws_l.cell(row=data_row, column=4, value=proj['ot_hours'])
                    data_row += 1
                data_row += 1

                # Daily Headcount
                ws_l.cell(row=data_row, column=1, value='DAILY HEADCOUNT').font = Font(bold=True, size=11)
                ws_l.cell(row=data_row, column=1).fill = PatternFill(
                    start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
                data_row += 1

                dh_headers = ['Day', 'Date', 'Present', 'Absent', 'Holiday', 'OT Hours']
                for ci, h in enumerate(dh_headers, 1):
                    c = ws_l.cell(row=data_row, column=ci, value=h)
                    c.font = Font(bold=True, color='FFFFFF', size=9)
                    c.fill = labour_header_fill
                data_row += 1

                day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                for dh in month_data['daily_headcount']:
                    try:
                        from dateutil import parser as dp
                        dd = dp.parse(str(dh['date']))
                        ws_l.cell(row=data_row, column=1, value=day_names[dd.weekday()])
                        ws_l.cell(row=data_row, column=2, value=dd.strftime('%d/%m/%Y'))
                    except:
                        ws_l.cell(row=data_row, column=2, value=str(dh['date']))
                    ws_l.cell(row=data_row, column=3, value=dh['present'])
                    ws_l.cell(row=data_row, column=4, value=dh['absent'])
                    ws_l.cell(row=data_row, column=5, value=dh['holiday'])
                    ws_l.cell(row=data_row, column=6, value=dh['ot_hours'])
                    data_row += 1

                # Column widths
                ws_l.column_dimensions['A'].width = 5
                ws_l.column_dimensions['B'].width = 20
                ws_l.column_dimensions['C'].width = 12
                ws_l.column_dimensions['D'].width = 10
                # Day columns are narrow (3 per day)
                for day in range(1, days_in_month + 1):
                    dc = day_col_starts[day]
                    for offset, w in enumerate([3, 3, 8]):
                        col_letter = get_column_letter(dc + offset)
                        ws_l.column_dimensions[col_letter].width = w
                # Summary columns
                for si, sw in enumerate([13, 10, 12, 10, 10, 12]):
                    col_letter = get_column_letter(summary_start_col + si)
                    ws_l.column_dimensions[col_letter].width = sw

        except Exception as e:
            print(f"[!] Labour tab export error: {e}")
            import traceback
            traceback.print_exc()

        # ── Sheet ordering ──
        if len(wb.sheetnames) > 1:
            desired_order = [
                'Executive Summary', 'Expense Breakdown', 'Cashflow Analysis',
                'Vendor Breakdown'
            ]
            for bc in VALID_BANK_CODES:
                bank_config = get_bank_config(bc)
                sn = f"{bank_config['name']} Txns"
                if len(sn) > 31:
                    sn = sn[:31]
                desired_order.append(sn)
            desired_order.extend(['Bills', 'Project Breakdown'])
            desired_order.extend(labour_sheet_names)

            desired_order = [s for s in desired_order if s in wb.sheetnames]
            desired_order += [s for s in wb.sheetnames if s not in desired_order]

            wb._sheets = [wb[s] for s in desired_order]

    output.seek(0)
    filename = f"Project_Summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


if __name__ == '__main__':

    app.run(debug=True, port=5000)
