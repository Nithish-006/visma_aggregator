"""Application factory + entry point.

All routes live in blueprints (see blueprints/), pure helpers in helpers/, the
Excel export in reports/, and shared singletons/mutable state in extensions.py.
This module just wires them together.
"""

import os
from datetime import timedelta

from flask import Flask

from config import Config
from helpers.dataframe import reload_data


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = os.environ.get('SECRET_KEY', 'visma-finance-secret-key-2024-secure')
    # Permanent session lifetime (30 days for "Stay signed in")
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

    # Create uploads directory if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    from auth import bp as auth_bp
    from blueprints.personal import bp as personal_bp
    from blueprints.sales import bp as sales_bp
    from blueprints.bills import bp as bills_bp
    from blueprints.banks import bp as banks_bp
    from blueprints.legacy import bp as legacy_bp
    from blueprints.projects import bp as projects_bp
    from blueprints.project_summary import bp as project_summary_bp
    for bp in (auth_bp, personal_bp, sales_bp, bills_bp, banks_bp,
               legacy_bp, projects_bp, project_summary_bp):
        app.register_blueprint(bp)

    # Load legacy data at startup (populates extensions.state.df_global)
    reload_data()

    return app


# Module-level app so `gunicorn app:app` and `python app.py` keep working.
app = create_app()


if __name__ == '__main__':
    app.run(debug=True, port=5000)
