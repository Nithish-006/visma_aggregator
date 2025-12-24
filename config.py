"""
Configuration file for VISMA Financial App
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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
