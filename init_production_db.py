"""
Initialize Production Database
Run this script after deploying to create database schema
"""

import mysql.connector
from config import Config
import sys

def init_database():
    """Initialize the production database with schema"""

    print("=" * 60)
    print("VISMA Financial App - Database Initialization")
    print("=" * 60)
    print()

    # Show configuration (hide password)
    print(f"Connecting to database:")
    print(f"  Host: {Config.DB_HOST}")
    print(f"  Database: {Config.DB_DATABASE}")
    print(f"  User: {Config.DB_USER}")
    print(f"  Port: {Config.DB_PORT}")
    print()

    try:
        # Connect to MySQL server (without specifying database)
        print("Connecting to MySQL server...")
        conn = mysql.connector.connect(
            host=Config.DB_HOST,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            port=Config.DB_PORT
        )
        cursor = conn.cursor()
        print("✓ Connected successfully!")
        print()

        # Read schema file
        print("Reading database schema...")
        with open('database_schema.sql', 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        print("✓ Schema file loaded")
        print()

        # Execute schema statements
        print("Creating database and tables...")
        statements = schema_sql.split(';')

        for i, statement in enumerate(statements, 1):
            statement = statement.strip()
            if statement:
                try:
                    cursor.execute(statement)
                    print(f"  [{i}/{len(statements)}] Executed")
                except mysql.connector.Error as err:
                    print(f"  [{i}/{len(statements)}] Warning: {err}")

        conn.commit()
        print()
        print("✓ Database initialized successfully!")
        print()

        # Verify tables
        cursor.execute(f"USE {Config.DB_DATABASE}")
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()

        print("Created tables:")
        for table in tables:
            print(f"  ✓ {table[0]}")

        cursor.close()
        conn.close()

        print()
        print("=" * 60)
        print("Database initialization complete!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Upload your bank statements via the web interface")
        print("  2. Start categorizing transactions")
        print("  3. Enjoy your financial insights!")
        print()

    except mysql.connector.Error as err:
        print()
        print("❌ Database Error:")
        print(f"   {err}")
        print()
        print("Troubleshooting:")
        print("  1. Check your database credentials in .env file")
        print("  2. Ensure MySQL server is running")
        print("  3. Verify network connectivity to database host")
        print()
        sys.exit(1)

    except FileNotFoundError:
        print()
        print("❌ Error: database_schema.sql not found!")
        print("   Make sure you're running this script from the project root")
        print()
        sys.exit(1)

    except Exception as e:
        print()
        print("❌ Unexpected Error:")
        print(f"   {e}")
        print()
        sys.exit(1)

if __name__ == "__main__":
    init_database()
