/**
 * Hub Page JavaScript
 * Handles dynamic content for the multi-bank hub dashboard
 */

document.addEventListener('DOMContentLoaded', function () {
    // Refresh stats periodically (optional)
    // refreshBankStats();

    // Load personal tracker count
    loadPersonalTrackerCount();

    // Load bill processor count
    loadBillProcessorCount();

    // Load sales bill count
    loadSalesBillCount();

    // Add animation on card hover
    initCardAnimations();
});

/**
 * Initialize card hover animations
 */
function initCardAnimations() {
    const cards = document.querySelectorAll('.bank-card');

    cards.forEach(card => {
        card.addEventListener('mouseenter', function () {
            this.style.transform = 'translateY(-4px)';
        });

        card.addEventListener('mouseleave', function () {
            this.style.transform = 'translateY(0)';
        });
    });
}

/**
 * Refresh bank statistics from the API
 */
async function refreshBankStats() {
    try {
        const response = await fetch('/api/hub/stats');
        if (!response.ok) {
            throw new Error('Failed to fetch stats');
        }

        const data = await response.json();

        // Update Axis count
        if (data.axis) {
            const axisCount = document.getElementById('axis-count');
            if (axisCount) {
                axisCount.textContent = formatNumber(data.axis.transaction_count);
            }
        }

        // Update KVB count
        if (data.kvb) {
            const kvbCount = document.getElementById('kvb-count');
            if (kvbCount) {
                kvbCount.textContent = formatNumber(data.kvb.transaction_count);
            }
        }
    } catch (error) {
        console.error('Error refreshing bank stats:', error);
    }
}

/**
 * Load personal tracker transaction count
 */
async function loadPersonalTrackerCount() {
    try {
        const response = await fetch('/api/personal/summary');
        if (!response.ok) {
            throw new Error('Failed to fetch personal summary');
        }

        const data = await response.json();
        const personalCount = document.getElementById('personal-count');
        if (personalCount && data.transaction_count !== undefined) {
            personalCount.textContent = formatNumber(data.transaction_count);
        }
    } catch (error) {
        console.error('Error loading personal tracker count:', error);
        const personalCount = document.getElementById('personal-count');
        if (personalCount) {
            personalCount.textContent = '0';
        }
    }
}

/**
 * Load bill processor invoice count
 */
async function loadBillProcessorCount() {
    try {
        const response = await fetch('/api/bills/stats');
        if (!response.ok) {
            throw new Error('Failed to fetch bill stats');
        }

        const data = await response.json();
        const billCount = document.getElementById('bill-count');
        if (billCount && data.invoice_count !== undefined) {
            billCount.textContent = formatNumber(data.invoice_count);
        }
    } catch (error) {
        console.error('Error loading bill processor count:', error);
        const billCount = document.getElementById('bill-count');
        if (billCount) {
            billCount.textContent = '0';
        }
    }
}

/**
 * Load sales bill invoice count
 */
async function loadSalesBillCount() {
    try {
        const response = await fetch('/api/sales/stats');
        if (!response.ok) {
            throw new Error('Failed to fetch sales stats');
        }

        const data = await response.json();
        const salesCount = document.getElementById('sales-count');
        if (salesCount && data.invoice_count !== undefined) {
            salesCount.textContent = formatNumber(data.invoice_count);
        }
    } catch (error) {
        console.error('Error loading sales bill count:', error);
        const salesCount = document.getElementById('sales-count');
        if (salesCount) {
            salesCount.textContent = '0';
        }
    }
}

/**
 * Clear server cache and reload hub stats
 */
async function refreshCache() {
    const btn = document.getElementById('refresh-cache-btn');
    const icon = btn.querySelector('svg');
    btn.disabled = true;
    icon.style.animation = 'spin 0.8s linear infinite';

    try {
        const response = await fetch('/api/clear-cache', { method: 'POST' });
        if (!response.ok) throw new Error('Failed to clear cache');

        await refreshBankStats();
        await loadPersonalTrackerCount();
        await loadBillProcessorCount();
        await loadSalesBillCount();

        btn.querySelector('span').textContent = 'Done!';
        setTimeout(() => { btn.querySelector('span').textContent = 'Refresh'; }, 1500);
    } catch (error) {
        console.error('Error clearing cache:', error);
        btn.querySelector('span').textContent = 'Error';
        setTimeout(() => { btn.querySelector('span').textContent = 'Refresh'; }, 1500);
    } finally {
        btn.disabled = false;
        icon.style.animation = '';
    }
}

/**
 * Format number with commas
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '0';
    return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}
