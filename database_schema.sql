-- ============================================================================
-- VISMA FINANCIAL APP - DATABASE SCHEMA (Multi-Bank Support)
-- ============================================================================

-- Create database
CREATE DATABASE IF NOT EXISTS visma_financial;
USE visma_financial;

-- ============================================================================
-- AXIS BANK TRANSACTIONS TABLE (Simplified Schema)
-- Fields: Date, Transaction Description, Client/Vendor, Category, Code, DR Amount, CR Amount, Project
-- ============================================================================
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

    -- Indexes for performance
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_code (code),
    INDEX idx_project (project),

    -- Unique constraint to prevent duplicate transactions
    UNIQUE KEY unique_transaction (transaction_date, transaction_description(500), dr_amount, cr_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- KARUR VYSYA BANK (KVB) TRANSACTIONS TABLE (Simplified Schema)
-- Fields: Date, Transaction Description, Client/Vendor, Category, Code, DR Amount, CR Amount, Project
-- ============================================================================
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

    -- Indexes for performance
    INDEX idx_transaction_date (transaction_date),
    INDEX idx_category (category),
    INDEX idx_client_vendor (client_vendor),
    INDEX idx_code (code),
    INDEX idx_project (project),

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

-- Legacy table for backwards compatibility (Simplified Schema)
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

-- Create views for easy querying (per bank) - Simplified Schema
CREATE OR REPLACE VIEW v_axis_transaction_summary AS
SELECT
    'axis' as bank_code,
    DATE_FORMAT(transaction_date, '%Y-%m') as month,
    DATE_FORMAT(transaction_date, '%M %Y') as month_name,
    category,
    code,
    COUNT(*) as transaction_count,
    SUM(dr_amount) as total_debit,
    SUM(cr_amount) as total_credit,
    SUM(cr_amount - dr_amount) as net_amount
FROM axis_transactions
GROUP BY
    DATE_FORMAT(transaction_date, '%Y-%m'),
    DATE_FORMAT(transaction_date, '%M %Y'),
    category,
    code;

CREATE OR REPLACE VIEW v_kvb_transaction_summary AS
SELECT
    'kvb' as bank_code,
    DATE_FORMAT(transaction_date, '%Y-%m') as month,
    DATE_FORMAT(transaction_date, '%M %Y') as month_name,
    category,
    code,
    COUNT(*) as transaction_count,
    SUM(dr_amount) as total_debit,
    SUM(cr_amount) as total_credit,
    SUM(cr_amount - dr_amount) as net_amount
FROM kvb_transactions
GROUP BY
    DATE_FORMAT(transaction_date, '%Y-%m'),
    DATE_FORMAT(transaction_date, '%M %Y'),
    category,
    code;

-- Legacy view for backwards compatibility - Simplified Schema
CREATE OR REPLACE VIEW v_transaction_summary AS
SELECT
    DATE_FORMAT(transaction_date, '%Y-%m') as month,
    DATE_FORMAT(transaction_date, '%M %Y') as month_name,
    category,
    code,
    COUNT(*) as transaction_count,
    SUM(dr_amount) as total_debit,
    SUM(cr_amount) as total_credit,
    SUM(cr_amount - dr_amount) as net_amount
FROM transactions
GROUP BY
    DATE_FORMAT(transaction_date, '%Y-%m'),
    DATE_FORMAT(transaction_date, '%M %Y'),
    category,
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
    bank ENUM('axis', 'kvb') DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_transaction_date (transaction_date),
    INDEX idx_project (project),
    INDEX idx_vendor (vendor),
    INDEX idx_transaction_type (transaction_type),
    INDEX idx_bank (bank)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration: Add transaction_type column if not exists (run this for existing databases)
-- ALTER TABLE personal_transactions ADD COLUMN transaction_type ENUM('expense', 'income') DEFAULT 'expense' AFTER amount;
-- ALTER TABLE personal_transactions ADD INDEX idx_transaction_type (transaction_type);

-- Migration: Add bank column if not exists (run this for existing databases)
-- ALTER TABLE personal_transactions ADD COLUMN bank ENUM('axis', 'kvb') DEFAULT NULL AFTER transaction_type;
-- ALTER TABLE personal_transactions ADD INDEX idx_bank (bank);

-- ============================================================================

-- Show summary
SELECT 'Database schema created successfully!' as status;
SELECT 'axis_transactions' as table_name, COUNT(*) as count FROM axis_transactions
UNION ALL
SELECT 'kvb_transactions' as table_name, COUNT(*) as count FROM kvb_transactions
UNION ALL
SELECT 'categories' as table_name, COUNT(*) as count FROM categories;


-- ============================================================================
-- BILL PROCESSOR TABLES
-- ============================================================================

-- Main invoice/bill table
CREATE TABLE IF NOT EXISTS bill_invoices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    page_number INT DEFAULT 1,
    invoice_number VARCHAR(100),
    invoice_date DATE,
    irn VARCHAR(255),
    ack_number VARCHAR(100),
    eway_bill_number VARCHAR(100),

    -- Vendor details
    vendor_name VARCHAR(255),
    vendor_gstin VARCHAR(20),
    vendor_address TEXT,
    vendor_state VARCHAR(100),
    vendor_pan VARCHAR(20),
    vendor_phone VARCHAR(50),
    vendor_bank_name VARCHAR(255),
    vendor_bank_account VARCHAR(50),
    vendor_bank_ifsc VARCHAR(20),

    -- Buyer details
    buyer_name VARCHAR(255),
    buyer_gstin VARCHAR(20),
    buyer_address TEXT,
    buyer_state VARCHAR(100),

    -- Ship to details
    ship_to_name VARCHAR(255),
    ship_to_address TEXT,

    -- Totals
    subtotal DECIMAL(15, 2) DEFAULT 0.00,
    total_cgst DECIMAL(15, 2) DEFAULT 0.00,
    total_sgst DECIMAL(15, 2) DEFAULT 0.00,
    total_igst DECIMAL(15, 2) DEFAULT 0.00,
    other_charges DECIMAL(15, 2) DEFAULT 0.00,
    round_off DECIMAL(10, 2) DEFAULT 0.00,
    total_amount DECIMAL(15, 2) DEFAULT 0.00,
    amount_in_words TEXT,

    -- Transport
    vehicle_number VARCHAR(50),
    transporter_name VARCHAR(255),

    -- Project tracking
    project VARCHAR(255) DEFAULT NULL,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_invoice_number (invoice_number),
    INDEX idx_invoice_date (invoice_date),
    INDEX idx_vendor_name (vendor_name),
    INDEX idx_vendor_gstin (vendor_gstin),
    INDEX idx_buyer_name (buyer_name),
    INDEX idx_created_at (created_at),
    INDEX idx_project (project),

    -- Unique constraint to prevent duplicate uploads
    UNIQUE KEY unique_invoice (invoice_number, invoice_date, vendor_gstin, total_amount)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Line items table (one-to-many with bill_invoices)
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

    -- Foreign key
    FOREIGN KEY (invoice_id) REFERENCES bill_invoices(id) ON DELETE CASCADE,

    -- Indexes
    INDEX idx_invoice_id (invoice_id),
    INDEX idx_hsn_code (hsn_sac_code),
    INDEX idx_description (description(100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- View for bill summary
CREATE OR REPLACE VIEW v_bill_summary AS
SELECT
    bi.id,
    bi.invoice_number,
    bi.invoice_date,
    bi.vendor_name,
    bi.vendor_gstin,
    bi.buyer_name,
    bi.total_amount,
    bi.vehicle_number,
    bi.eway_bill_number,
    bi.project,
    COUNT(bli.id) as line_item_count,
    bi.created_at
FROM bill_invoices bi
LEFT JOIN bill_line_items bli ON bi.id = bli.invoice_id
GROUP BY bi.id
ORDER BY bi.created_at DESC;

-- ============================================================================
-- MIGRATION: Add project column to bill_invoices (run this for existing databases)
-- ============================================================================
-- ALTER TABLE bill_invoices ADD COLUMN project VARCHAR(255) DEFAULT NULL AFTER transporter_name;
-- ALTER TABLE bill_invoices ADD INDEX idx_project (project);
