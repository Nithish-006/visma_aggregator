"""Authentication: login_required decorator + login/logout/index/service-worker.

`login_required` lives here because every blueprint imports it. Endpoint names
are blueprint-namespaced (`auth.login`, `auth.index`), so url_for() callers use
the absolute `auth.*` form.
"""

import os
from functools import wraps

from flask import (
    Blueprint, render_template, request, session, redirect, url_for,
    jsonify, send_file,
)

from config import BANK_CONFIG, VALID_BANK_CODES
from helpers.bankdata import get_bank_df

bp = Blueprint('auth', __name__)

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
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    # If already logged in, redirect to dashboard
    if session.get('logged_in'):
        return redirect(url_for('auth.index'))

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
            return redirect(url_for('auth.index'))
        else:
            error = 'Invalid username or password. Please try again.'

    return render_template('login.html', error=error)


@bp.route('/logout')
def logout():
    """Handle user logout"""
    session.clear()
    return redirect(url_for('auth.login'))


@bp.route('/sw.js')
def service_worker():
    return send_file('static/sw.js', mimetype='application/javascript')


@bp.route('/')
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
