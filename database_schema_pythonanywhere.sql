-- ============================================================================
-- VISMA FINANCIAL APP - DATABASE SCHEMA (PythonAnywhere Version)
-- ============================================================================
-- Run this in PythonAnywhere MySQL console or via:
-- mysql -h nthsh6.mysql.pythonanywhere-services.com -u nthsh6 -p 'nthsh6$visma_financial' < database_schema_pythonanywhere.sql
-- ============================================================================

-- AXIS BANK TRANSACTIONS TABLE
CREATE TABLE IF NOT EXISTS axis_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    transaction_description TEXT NOT NULL,
    client_vendor VARCHAR(255) DEFAULT 'Unknown',
    category VARCHAR(100) NOT NULL,
    broader_category VARCHAR(100) NOT NULL,
    code VARCHAR(10) NOT NULL,
    dr_amount DECIMAL(15, 2) DEFAULT 0.00,
    cr_amount DECIMAL(15, 2) DEFAULT 0.00,
    running_balance DECIMAL(15, 2) NOT NULL,
    net DECIMAL(15, 2) DEFAULT 0.00,
    project VARCHAR(255) DEFAULT NULL,
    dd VARCHAR(255) DEFAULT NULL,
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_broader_category (broader_category),
    INDEX idx_code (code),
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- KARUR VYSYA BANK (KVB) TRANSACTIONS TABLE
CREATE TABLE IF NOT EXISTS kvb_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    transaction_description TEXT NOT NULL,
    client_vendor VARCHAR(255) DEFAULT 'Unknown',
    category VARCHAR(100) NOT NULL,
    broader_category VARCHAR(100) NOT NULL,
    code VARCHAR(10) NOT NULL,
    dr_amount DECIMAL(15, 2) DEFAULT 0.00,
    cr_amount DECIMAL(15, 2) DEFAULT 0.00,
    running_balance DECIMAL(15, 2) NOT NULL,
    net DECIMAL(15, 2) DEFAULT 0.00,
    project VARCHAR(255) DEFAULT NULL,
    dd VARCHAR(255) DEFAULT NULL,
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_broader_category (broader_category),
    INDEX idx_code (code),
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

-- LEGACY TRANSACTIONS TABLE
CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    transaction_description TEXT NOT NULL,
    client_vendor VARCHAR(255) DEFAULT 'Unknown',
    category VARCHAR(100) NOT NULL,
    broader_category VARCHAR(100) NOT NULL,
    code VARCHAR(10) NOT NULL,
    dr_amount DECIMAL(15, 2) DEFAULT 0.00,
    cr_amount DECIMAL(15, 2) DEFAULT 0.00,
    running_balance DECIMAL(15, 2) NOT NULL,
    net DECIMAL(15, 2) DEFAULT 0.00,
    project VARCHAR(255) DEFAULT NULL,
    dd VARCHAR(255) DEFAULT NULL,
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_broader_category (broader_category),
    INDEX idx_code (code),
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- LEGACY UPLOAD HISTORY
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

-- CATEGORIES TABLE
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    category_code VARCHAR(10) NOT NULL UNIQUE,
    description TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- INSERT DEFAULT CATEGORIES
INSERT IGNORE INTO categories (category_name, category_code, description) VALUES
('OFFICE EXP', 'OE', 'Office supplies, stationery, software, internet, phones'),
('FACTORY EXP', 'FE', 'Machinery, equipment, maintenance, spare parts'),
('SITE EXP', 'SE', 'Construction, cement, labour, contractors'),
('TRANSPORT EXP', 'TE', 'Fuel, vehicles, drivers, freight, tolls'),
('MATERIAL PURCHASE', 'MP', 'Raw materials, steel, wood, hardware'),
('DUTIES & TAX', 'DT', 'GST, TDS, government taxes'),
('SALARY AC', 'SA', 'Salaries, wages, employee payments'),
('BANK CHARGES', 'BC', 'Bank fees, ATM charges, service charges'),
('AMOUNT RECEIVED', 'AR', 'All credit transactions'),
('Uncategorized', 'UC', 'Transactions requiring manual categorization');

-- PERSONAL TRANSACTIONS TABLE
CREATE TABLE IF NOT EXISTS personal_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    vendor VARCHAR(255) NOT NULL,
    description TEXT,
    project VARCHAR(255) DEFAULT 'General',
    amount DECIMAL(15, 2) NOT NULL,
    transaction_type ENUM('expense', 'income') DEFAULT 'expense',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_project (project),
    INDEX idx_vendor (vendor),
    INDEX idx_transaction_type (transaction_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
