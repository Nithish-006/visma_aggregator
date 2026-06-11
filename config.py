"""
Configuration file for VISMA Financial App
"""

import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ============================================================================
# TIMEZONE — always operate in Indian Standard Time (IST, UTC+05:30)
# ============================================================================
# The app may be deployed (e.g. on Railway) on hosts whose system clock is UTC.
# Anything user-facing (filenames, "generated on" stamps, and the DB session
# time_zone used for created_at defaults) must read IST, not the host TZ. Use
# now_ist() everywhere instead of datetime.now() so a server-side TZ never leaks
# a wrong date/time to the user.
IST = timezone(timedelta(hours=5, minutes=30))

# MySQL session offset string for `SET time_zone` (makes CURRENT_TIMESTAMP IST).
IST_MYSQL_OFFSET = '+05:30'


def now_ist():
    """Current wall-clock time in IST, as a naive datetime (tzinfo stripped).

    Naive so it slots into existing strftime() calls and DB columns exactly
    like the old datetime.now() did, but with IST values regardless of host TZ.
    """
    return datetime.now(IST).replace(tzinfo=None)


# ============================================================================
# BANK CONFIGURATION
# ============================================================================
BANK_CONFIG = {
    'axis': {
        'name': 'Axis Bank',
        'code': 'axis',
        'table': 'axis_transactions',
        'upload_table': 'bank_upload_history',
        'color': '#97144D',  # Axis Bank maroon
        'icon': 'axis',
        'description': 'Axis Bank Transactions'
    },
    'kvb': {
        'name': 'Karur Vysya Bank',
        'code': 'kvb',
        'table': 'kvb_transactions',
        'upload_table': 'bank_upload_history',
        'color': '#1E4785',  # KVB blue
        'icon': 'kvb',
        'description': 'Karur Vysya Bank Transactions'
    }
}

# Valid bank codes
VALID_BANK_CODES = list(BANK_CONFIG.keys())

def get_bank_config(bank_code):
    """Get configuration for a specific bank"""
    return BANK_CONFIG.get(bank_code)

def get_bank_table(bank_code):
    """Get the transaction table name for a bank"""
    config = BANK_CONFIG.get(bank_code)
    return config['table'] if config else None


class Config:
    """Application configuration"""

    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'visma-financial-app-secret-key-2025'
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16MB default
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

    # Upload settings
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

    # Database settings - Use environment variables in production
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_DATABASE = os.environ.get('DB_DATABASE', 'visma_financial')
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '12345')
    DB_PORT = int(os.environ.get('DB_PORT', 3306))

    # Application settings
    USE_DATABASE = True  # Set to False to use Excel file mode
    EXCEL_FILE = 'APR_TO_DEC_2025_AGGREGATED_FINAL_WITH_CODE.xlsx'  # Fallback if database not available


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS
