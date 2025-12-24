# VISMA Financial App

A Flask-based web application for processing and categorizing bank statements with an intuitive interface for transaction management.

## Features

- Upload bank statements (Excel format: .xlsx, .xls)
- Automatic transaction categorization
- Edit transactions with bulk operations
- Filter and search functionality
- Mobile-responsive design
- Category-based financial insights

## Categories

- OFFICE EXP (Office Expenses)
- FACTORY EXP (Factory Expenses)
- AMOUNT RECEIVED (Income)
- SITE EXP (Site Expenses)
- TRANSPORT EXP (Transportation)
- MATERIAL PURCHASE (Materials)
- DUTIES & TAX (Taxes)
- SALARY AC (Salaries)
- BANK CHARGES (Bank Fees)

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: MySQL
- **Frontend**: HTML, CSS, JavaScript
- **Deployment**: Railway/Render/PythonAnywhere

## Quick Start

### Local Development

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Create `.env` file (use `.env.example` as template)
4. Initialize database: `python init_production_db.py`
5. Run the app: `python app.py`

### Production Deployment

See [QUICKSTART-DEPLOYMENT.md](QUICKSTART-DEPLOYMENT.md) for 15-minute deployment guide.

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment options.

## Environment Variables

Required environment variables (see `.env.example`):

- `SECRET_KEY` - Flask secret key (generate with `python generate_secret_key.py`)
- `DB_HOST` - MySQL host
- `DB_DATABASE` - Database name
- `DB_USER` - Database username
- `DB_PASSWORD` - Database password
- `DB_PORT` - Database port (default: 3306)

## Project Structure

```
├── app.py                          # Main Flask application
├── config.py                       # Configuration settings
├── database.py                     # Database utilities
├── database_schema.sql             # Database schema
├── templates/                      # HTML templates
│   ├── index.html                 # Dashboard
│   └── edit_transactions.html     # Edit page
├── static/                        # Static assets
│   ├── style.css                  # Dashboard styles
│   ├── script.js                  # Dashboard JS
│   ├── edit_transactions.css      # Edit page styles
│   └── edit_transactions.js       # Edit page JS
├── requirements.txt               # Python dependencies
├── Procfile                       # Deployment configuration
└── .env.example                   # Environment template
```

## License

Private - Personal Use

## Author

Built for personal financial management and business expense tracking.
