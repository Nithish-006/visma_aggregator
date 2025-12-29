-- ============================================================================
-- VISMA FINANCIAL APP - DATABASE SCHEMA (Multi-Bank Support)
-- ============================================================================

-- Create database
CREATE DATABASE IF NOT EXISTS visma_financial;
USE visma_financial;

-- ============================================================================
-- AXIS BANK TRANSACTIONS TABLE
-- ============================================================================
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

    -- Indexes for performance
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_broader_category (broader_category),
    INDEX idx_code (code),

    -- Unique constraint to prevent duplicate transactions
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- KARUR VYSYA BANK (KVB) TRANSACTIONS TABLE
-- ============================================================================
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

    -- Indexes for performance
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_broader_category (broader_category),
    INDEX idx_code (code),

    -- Unique constraint to prevent duplicate transactions
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- BANK UPLOAD HISTORY (supports multiple banks)
-- ============================================================================
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

-- Legacy table for backwards compatibility (keep existing data)
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

-- Create categories table for reference
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    category_code VARCHAR(10) NOT NULL UNIQUE,
    description TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default categories
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

-- Create views for easy querying (per bank)
CREATE OR REPLACE VIEW v_axis_transaction_summary AS
SELECT
    'axis' as bank_code,
    DATE_FORMAT(transaction_date, '%Y-%m') as month,
    DATE_FORMAT(transaction_date, '%M %Y') as month_name,
    category,
    broader_category,
    code,
    COUNT(*) as transaction_count,
    SUM(dr_amount) as total_debit,
    SUM(cr_amount) as total_credit,
    SUM(net) as net_amount
FROM axis_transactions
GROUP BY
    DATE_FORMAT(transaction_date, '%Y-%m'),
    DATE_FORMAT(transaction_date, '%M %Y'),
    category,
    broader_category,
    code;

CREATE OR REPLACE VIEW v_kvb_transaction_summary AS
SELECT
    'kvb' as bank_code,
    DATE_FORMAT(transaction_date, '%Y-%m') as month,
    DATE_FORMAT(transaction_date, '%M %Y') as month_name,
    category,
    broader_category,
    code,
    COUNT(*) as transaction_count,
    SUM(dr_amount) as total_debit,
    SUM(cr_amount) as total_credit,
    SUM(net) as net_amount
FROM kvb_transactions
GROUP BY
    DATE_FORMAT(transaction_date, '%Y-%m'),
    DATE_FORMAT(transaction_date, '%M %Y'),
    category,
    broader_category,
    code;

-- Legacy view for backwards compatibility
CREATE OR REPLACE VIEW v_transaction_summary AS
SELECT
    DATE_FORMAT(transaction_date, '%Y-%m') as month,
    DATE_FORMAT(transaction_date, '%M %Y') as month_name,
    category,
    broader_category,
    code,
    COUNT(*) as transaction_count,
    SUM(dr_amount) as total_debit,
    SUM(cr_amount) as total_credit,
    SUM(net) as net_amount
FROM transactions
GROUP BY
    DATE_FORMAT(transaction_date, '%Y-%m'),
    DATE_FORMAT(transaction_date, '%M %Y'),
    category,
    broader_category,
    code;

-- ============================================================================
-- MIGRATION SCRIPT: Run this to migrate existing data to axis_transactions
-- ============================================================================
-- NOTE: Run these commands manually if you have existing data in 'transactions' table
--
-- Step 1: Copy existing transactions to axis_transactions
-- INSERT INTO axis_transactions SELECT * FROM transactions;
--
-- Step 2: Copy upload history to bank_upload_history
-- INSERT INTO bank_upload_history (bank_code, filename, upload_date, records_processed,
--     records_inserted, records_duplicated, status, error_message)
-- SELECT 'axis', filename, upload_date, records_processed, records_inserted,
--     records_duplicated, status, error_message FROM upload_history;
-- ============================================================================

-- ============================================================================
-- PERSONAL TRANSACTION TRACKER TABLE
-- ============================================================================
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

-- Migration: Add transaction_type column if not exists (run this for existing databases)
-- ALTER TABLE personal_transactions ADD COLUMN transaction_type ENUM('expense', 'income') DEFAULT 'expense' AFTER amount;
-- ALTER TABLE personal_transactions ADD INDEX idx_transaction_type (transaction_type);

-- ============================================================================

-- Show summary
SELECT 'Database schema created successfully!' as status;
SELECT 'axis_transactions' as table_name, COUNT(*) as count FROM axis_transactions
UNION ALL
SELECT 'kvb_transactions' as table_name, COUNT(*) as count FROM kvb_transactions
UNION ALL
SELECT 'categories' as table_name, COUNT(*) as count FROM categories;


-- USE visma_financial;

-- ALTER TABLE personal_transactions
-- ADD COLUMN transaction_type ENUM('expense', 'income') DEFAULT 'expense' AFTER amount;

-- ALTER TABLE personal_transactions
-- ADD INDEX idx_transaction_type (transaction_type);
