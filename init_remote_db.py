"""
Initialize the remote Railway MySQL database with required tables.
"""

import mysql.connector
from mysql.connector import Error

# Remote MySQL instance (Railway)
DB_CONFIG = {
    'host': 'yamanote.proxy.rlwy.net',
    'port': 57844,
    'user': 'root',
    'password': 'uxozNadQzagwhWazsWnfDZMSNvKHRwvi',
    'database': 'railway'
}

SCHEMA_SQL = """
-- AXIS BANK TRANSACTIONS TABLE
CREATE TABLE IF NOT EXISTS axis_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    transaction_description TEXT NOT NULL,
    client_vendor VARCHAR(255) DEFAULT 'Unknown',
    category VARCHAR(100) NOT NULL,
    code VARCHAR(10) NOT NULL,
    dr_amount DECIMAL(15, 2) DEFAULT 0.00,
    cr_amount DECIMAL(15, 2) DEFAULT 0.00,
    project VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_code (code),
    INDEX idx_project (project),
    INDEX idx_filter_combo (category, transaction_date, project),
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- KVB TRANSACTIONS TABLE
CREATE TABLE IF NOT EXISTS kvb_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    transaction_description TEXT NOT NULL,
    client_vendor VARCHAR(255) DEFAULT 'Unknown',
    category VARCHAR(100) NOT NULL,
    code VARCHAR(10) NOT NULL,
    dr_amount DECIMAL(15, 2) DEFAULT 0.00,
    cr_amount DECIMAL(15, 2) DEFAULT 0.00,
    project VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_code (code),
    INDEX idx_project (project),
    INDEX idx_filter_combo (category, transaction_date, project),
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- BANK UPLOAD HISTORY
CREATE TABLE IF NOT EXISTS bank_upload_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bank_code VARCHAR(20) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    records_processed INT NOT NULL,
    records_inserted INT NOT NULL,
    records_duplicated INT DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    error_message TEXT DEFAULT NULL,
    INDEX idx_bank_code (bank_code),
    INDEX idx_upload_date (upload_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Legacy transactions table
CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    transaction_description TEXT NOT NULL,
    client_vendor VARCHAR(255) DEFAULT 'Unknown',
    category VARCHAR(100) NOT NULL,
    code VARCHAR(10) NOT NULL,
    dr_amount DECIMAL(15, 2) DEFAULT 0.00,
    cr_amount DECIMAL(15, 2) DEFAULT 0.00,
    project VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_code (code),
    INDEX idx_project (project),
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Legacy upload history table
CREATE TABLE IF NOT EXISTS upload_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    records_processed INT NOT NULL,
    records_inserted INT NOT NULL,
    records_duplicated INT DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    error_message TEXT DEFAULT NULL,
    INDEX idx_upload_date (upload_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Categories table
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    category_code VARCHAR(10) NOT NULL UNIQUE,
    description TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Personal transactions table
CREATE TABLE IF NOT EXISTS personal_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    vendor VARCHAR(255) NOT NULL,
    description TEXT,
    project VARCHAR(255) DEFAULT 'General',
    amount DECIMAL(15, 2) NOT NULL,
    transaction_type ENUM('expense', 'income') DEFAULT 'expense',
    bank ENUM('axis', 'kvb') DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_project (project),
    INDEX idx_vendor (vendor),
    INDEX idx_transaction_type (transaction_type),
    INDEX idx_bank (bank)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bill invoices table
CREATE TABLE IF NOT EXISTS bill_invoices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    page_number INT DEFAULT 1,
    invoice_number VARCHAR(100),
    invoice_date DATE,
    irn VARCHAR(255),
    ack_number VARCHAR(100),
    eway_bill_number VARCHAR(100),
    vendor_name VARCHAR(255),
    vendor_gstin VARCHAR(20),
    vendor_address TEXT,
    vendor_state VARCHAR(100),
    vendor_pan VARCHAR(20),
    vendor_phone VARCHAR(50),
    vendor_bank_name VARCHAR(255),
    vendor_bank_account VARCHAR(50),
    vendor_bank_ifsc VARCHAR(20),
    buyer_name VARCHAR(255),
    buyer_gstin VARCHAR(20),
    buyer_address TEXT,
    buyer_state VARCHAR(100),
    ship_to_name VARCHAR(255),
    ship_to_address TEXT,
    subtotal DECIMAL(15, 2) DEFAULT 0.00,
    total_cgst DECIMAL(15, 2) DEFAULT 0.00,
    total_sgst DECIMAL(15, 2) DEFAULT 0.00,
    total_igst DECIMAL(15, 2) DEFAULT 0.00,
    other_charges DECIMAL(15, 2) DEFAULT 0.00,
    round_off DECIMAL(10, 2) DEFAULT 0.00,
    total_amount DECIMAL(15, 2) DEFAULT 0.00,
    amount_in_words TEXT,
    vehicle_number VARCHAR(50),
    transporter_name VARCHAR(255),
    project VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_invoice_number (invoice_number),
    INDEX idx_invoice_date (invoice_date),
    INDEX idx_vendor_name (vendor_name),
    INDEX idx_vendor_gstin (vendor_gstin),
    INDEX idx_buyer_name (buyer_name),
    INDEX idx_created_at (created_at),
    INDEX idx_project (project),
    UNIQUE KEY unique_invoice (invoice_number, invoice_date, vendor_gstin, total_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bill line items table
CREATE TABLE IF NOT EXISTS bill_line_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id INT NOT NULL,
    sl_no INT,
    description TEXT NOT NULL,
    hsn_sac_code VARCHAR(20),
    quantity DECIMAL(15, 3) DEFAULT 0,
    uom VARCHAR(20),
    rate_per_unit DECIMAL(15, 2) DEFAULT 0.00,
    discount_percent DECIMAL(5, 2) DEFAULT 0.00,
    discount_amount DECIMAL(15, 2) DEFAULT 0.00,
    taxable_value DECIMAL(15, 2) DEFAULT 0.00,
    cgst_rate DECIMAL(5, 2) DEFAULT 0.00,
    cgst_amount DECIMAL(15, 2) DEFAULT 0.00,
    sgst_rate DECIMAL(5, 2) DEFAULT 0.00,
    sgst_amount DECIMAL(15, 2) DEFAULT 0.00,
    igst_rate DECIMAL(5, 2) DEFAULT 0.00,
    igst_amount DECIMAL(15, 2) DEFAULT 0.00,
    amount DECIMAL(15, 2) DEFAULT 0.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES bill_invoices(id) ON DELETE CASCADE,
    INDEX idx_invoice_id (invoice_id),
    INDEX idx_hsn_code (hsn_sac_code),
    INDEX idx_description (description(100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

INSERT_CATEGORIES = """
INSERT INTO categories (category_name, category_code, description) VALUES
('OFFICE EXP', 'OE', 'Office supplies, stationery, software, internet, phones'),
('FACTORY EXP', 'FE', 'Machinery, equipment, maintenance, spare parts'),
('SITE EXP', 'SE', 'Construction, cement, labour, contractors'),
('TRANSPORT EXP', 'TE', 'Fuel, vehicles, drivers, freight, tolls'),
('MATERIAL PURCHASE', 'MP', 'Raw materials, steel, wood, hardware'),
('DUTIES & TAX', 'DT', 'GST, TDS, government taxes'),
('SALARY AC', 'SA', 'Salaries, wages, employee payments'),
('BANK CHARGES', 'BC', 'Bank fees, ATM charges, service charges'),
('AMOUNT RECEIVED', 'AR', 'All credit transactions'),
('Uncategorized', 'UC', 'Transactions requiring manual categorization')
ON DUPLICATE KEY UPDATE description=VALUES(description);
"""

def main():
    print("=" * 60)
    print("Initializing Remote Railway MySQL Database")
    print("=" * 60)
    print(f"\nConnecting to: {DB_CONFIG['host']}:{DB_CONFIG['port']}")

    try:
        connection = mysql.connector.connect(**DB_CONFIG, connection_timeout=30)

        if connection.is_connected():
            print("Connected successfully!\n")
            cursor = connection.cursor()

            # Execute each statement separately
            statements = [s.strip() for s in SCHEMA_SQL.split(';') if s.strip()]

            for i, stmt in enumerate(statements, 1):
                if stmt:
                    try:
                        cursor.execute(stmt)
                        print(f"  [{i}/{len(statements)}] Executed successfully")
                    except Error as e:
                        print(f"  [{i}/{len(statements)}] Warning: {e}")

            connection.commit()
            print("\nSchema created!")

            # Insert categories
            print("\nInserting default categories...")
            try:
                cursor.execute(INSERT_CATEGORIES)
                connection.commit()
                print("Categories inserted!")
            except Error as e:
                print(f"Categories warning: {e}")

            # Verify tables
            print("\nVerifying tables:")
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                count = cursor.fetchone()[0]
                print(f"  - {table[0]}: {count} rows")

            cursor.close()
            connection.close()
            print("\n" + "=" * 60)
            print("Database initialization complete!")
            print("=" * 60)

    except Error as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
