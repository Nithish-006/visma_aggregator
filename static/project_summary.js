/* ============================================================================
   PROJECT SUMMARY - Client-Side Logic
   ============================================================================ */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────────
    const state = {
        filters: { startDate: '', endDate: '', project: '', category: '' },
        pagination: {
            projectBreakdown: { page: 1, perPage: 15 },
            vendorBreakdown: { page: 1, perPage: 15, showAll: false },
            axisTransactions: { page: 1, perPage: 15 },
            kvbTransactions: { page: 1, perPage: 15 }
        },
        activeBankTab: 'axis',
        data: {
            combined: null,
            personalTxns: [],
            personalSummary: null
        }
    };

    // ── DOM Refs ───────────────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    // ── Utilities ──────────────────────────────────────────────────────
    function formatIndianNumber(amount) {
        if (amount == null || isNaN(amount) || amount === 0) return '\u20B90';
        const abs = Math.abs(amount);
        const sign = amount < 0 ? '-' : '';
        const parts = abs.toFixed(2).split('.');
        let intPart = parts[0];
        const decPart = parts[1];
        if (intPart.length > 3) {
            const last3 = intPart.slice(-3);
            let rest = intPart.slice(0, -3);
            const groups = [];
            while (rest.length > 2) {
                groups.unshift(rest.slice(-2));
                rest = rest.slice(0, -2);
            }
            if (rest) groups.unshift(rest);
            intPart = groups.join(',') + ',' + last3;
        }
        return sign + '\u20B9' + intPart + '.' + decPart;
    }

    function formatAmount(amount) {
        return new Intl.NumberFormat('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(amount);
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function debounce(fn, ms) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    }

    function buildQueryParams() {
        const p = new URLSearchParams();
        if (state.filters.startDate) p.set('start_date', state.filters.startDate);
        if (state.filters.endDate) p.set('end_date', state.filters.endDate);
        if (state.filters.project) p.set('project', state.filters.project);
        if (state.filters.category) p.set('category', state.filters.category);
        return p;
    }

    async function fetchJSON(url) {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    function showLoading() {
        const el = $('#loading-overlay');
        if (el) { el.classList.remove('hidden'); }
    }

    function hideLoading() {
        const el = $('#loading-overlay');
        if (el) { el.classList.add('hidden'); }
    }

    function renderPaginationControls(containerId, currentPage, totalPages, onPageChange) {
        const container = document.getElementById(containerId);
        if (!container) return;
        if (totalPages <= 1) { container.innerHTML = ''; return; }
        container.innerHTML = `
            <button class="ps-page-btn" ${currentPage <= 1 ? 'disabled' : ''} data-page="${currentPage - 1}">&laquo; Prev</button>
            <span class="ps-page-info">Page ${currentPage} of ${totalPages}</span>
            <button class="ps-page-btn" ${currentPage >= totalPages ? 'disabled' : ''} data-page="${currentPage + 1}">Next &raquo;</button>
        `;
        container.querySelectorAll('.ps-page-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const pg = parseInt(btn.dataset.page);
                if (!isNaN(pg)) onPageChange(pg);
            });
        });
    }

    // ── Category Colors (for horizontal bars) ──────────────────────────
    const CATEGORY_COLORS = [
        '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
        '#ec4899', '#06b6d4', '#f97316', '#6366f1', '#14b8a6',
        '#e11d48', '#84cc16', '#a855f7', '#0ea5e9', '#d946ef'
    ];

    // ── Category icons (same as expense tracker) ───────────────────────
    const categoryIcons = {
        'Salary': { icon: '\uD83D\uDCB0', name: 'Salary' },
        'Food': { icon: '\uD83C\uDF54', name: 'Food' },
        'Transport': { icon: '\uD83D\uDE97', name: 'Transport' },
        'Shopping': { icon: '\uD83D\uDED2', name: 'Shopping' },
        'Bills': { icon: '\uD83D\uDCC4', name: 'Bills' },
        'Entertainment': { icon: '\uD83C\uDFAC', name: 'Entertain' },
        'Health': { icon: '\uD83D\uDC8A', name: 'Health' },
        'Social Life': { icon: '\uD83C\uDF89', name: 'Social' },
        'Investment': { icon: '\uD83D\uDCC8', name: 'Invest' },
        'default_income': { icon: '\uD83D\uDCB5', name: 'Income' },
        'default_expense': { icon: '\uD83D\uDCB8', name: 'Expense' }
    };

    function getCategoryInfo(transaction) {
        const vendor = (transaction.vendor || '').toLowerCase();
        if (transaction.transaction_type === 'income') {
            if (vendor.includes('salary') || vendor.includes('wage')) return categoryIcons['Salary'];
            return categoryIcons['default_income'];
        }
        if (vendor.includes('food') || vendor.includes('restaurant') || vendor.includes('cafe') || vendor.includes('swiggy') || vendor.includes('zomato')) return categoryIcons['Food'];
        if (vendor.includes('uber') || vendor.includes('ola') || vendor.includes('petrol') || vendor.includes('fuel') || vendor.includes('transport')) return categoryIcons['Transport'];
        if (vendor.includes('amazon') || vendor.includes('flipkart') || vendor.includes('shop') || vendor.includes('mall')) return categoryIcons['Shopping'];
        if (vendor.includes('bill') || vendor.includes('electric') || vendor.includes('water') || vendor.includes('gas') || vendor.includes('rent')) return categoryIcons['Bills'];
        if (vendor.includes('movie') || vendor.includes('netflix') || vendor.includes('spotify') || vendor.includes('game')) return categoryIcons['Entertainment'];
        if (vendor.includes('hospital') || vendor.includes('doctor') || vendor.includes('pharmacy') || vendor.includes('medical')) return categoryIcons['Health'];
        if (vendor.includes('party') || vendor.includes('dinner') || vendor.includes('friend') || vendor.includes('split')) return categoryIcons['Social Life'];
        if (vendor.includes('invest') || vendor.includes('stock') || vendor.includes('mutual') || vendor.includes('sip')) return categoryIcons['Investment'];
        return categoryIcons['default_expense'];
    }

    // ── Init ───────────────────────────────────────────────────────────
    async function init() {
        showLoading();
        try {
            const [dateRange, filterOptions] = await Promise.all([
                fetchJSON('/api/project-summary/date-range'),
                fetchJSON('/api/project-summary/projects')
            ]);

            if (dateRange.min_date) {
                $('#filter-start-date').value = dateRange.min_date;
                state.filters.startDate = dateRange.min_date;
            }
            if (dateRange.max_date) {
                $('#filter-end-date').value = dateRange.max_date;
                state.filters.endDate = dateRange.max_date;
            }

            const projSelect = $('#filter-project');
            (filterOptions.projects || []).forEach(p => {
                const opt = document.createElement('option');
                opt.value = p;
                opt.textContent = p;
                projSelect.appendChild(opt);
            });

            const catSelect = $('#filter-category');
            (filterOptions.categories || []).forEach(c => {
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                catSelect.appendChild(opt);
            });

            bindFilterEvents();
            await refreshAll();
        } catch (err) {
            console.error('Init error:', err);
        } finally {
            hideLoading();
        }
    }

    function bindFilterEvents() {
        const debouncedRefresh = debounce(() => refreshAll(), 300);

        $('#filter-start-date').addEventListener('change', (e) => {
            state.filters.startDate = e.target.value;
            debouncedRefresh();
        });
        $('#filter-end-date').addEventListener('change', (e) => {
            state.filters.endDate = e.target.value;
            debouncedRefresh();
        });
        $('#filter-project').addEventListener('change', (e) => {
            state.filters.project = e.target.value;
            debouncedRefresh();
        });
        $('#filter-category').addEventListener('change', (e) => {
            state.filters.category = e.target.value;
            debouncedRefresh();
        });
        $('#reset-filters').addEventListener('click', async () => {
            try {
                const dateRange = await fetchJSON('/api/project-summary/date-range');
                state.filters.startDate = dateRange.min_date || '';
                state.filters.endDate = dateRange.max_date || '';
                $('#filter-start-date').value = state.filters.startDate;
                $('#filter-end-date').value = state.filters.endDate;
            } catch (e) {
                state.filters.startDate = '';
                state.filters.endDate = '';
                $('#filter-start-date').value = '';
                $('#filter-end-date').value = '';
            }
            state.filters.project = '';
            state.filters.category = '';
            $('#filter-project').value = '';
            $('#filter-category').value = '';
            refreshAll();
        });

        // Bank transaction tabs
        $$('.ps-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                $$('.ps-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.activeBankTab = btn.dataset.bank;
                state.pagination[btn.dataset.bank + 'Transactions'].page = 1;
                fetchBankTransactions(btn.dataset.bank, 1);
            });
        });

        // Vendor show-all toggle
        $('#vendor-show-all').addEventListener('click', () => {
            state.pagination.vendorBreakdown.showAll = !state.pagination.vendorBreakdown.showAll;
            state.pagination.vendorBreakdown.page = 1;
            const btn = $('#vendor-show-all');
            btn.classList.toggle('active', state.pagination.vendorBreakdown.showAll);
            btn.textContent = state.pagination.vendorBreakdown.showAll ? 'Top 20' : 'Show All';
            renderVendorTable();
        });
    }

    // ── Refresh All ────────────────────────────────────────────────────
    async function refreshAll() {
        state.pagination.projectBreakdown.page = 1;
        state.pagination.vendorBreakdown.page = 1;
        state.pagination.axisTransactions.page = 1;
        state.pagination.kvbTransactions.page = 1;

        const params = buildQueryParams();

        try {
            const [combined, personalTxns] = await Promise.all([
                fetchJSON('/api/project-summary/combined?' + params.toString()),
                fetchJSON('/api/personal/transactions?' + params.toString())
            ]);

            state.data.combined = combined;
            state.data.personalTxns = personalTxns.transactions || [];

            // Render all sections
            renderKPI(combined.summary);
            renderBankBreakdown(combined.bank_breakdown);
            renderCategoryBars(combined.category_breakdown);
            renderProjectTable();
            renderVendorTable();
            renderExpenseTracker();

            // Fetch active bank tab transactions
            fetchBankTransactions(state.activeBankTab, 1);
        } catch (err) {
            console.error('Refresh error:', err);
        }
    }

    // ── Render: KPI Cards ──────────────────────────────────────────────
    function renderKPI(summary) {
        if (!summary) return;
        $('#kpi-income').textContent = summary.total_income_formatted || '\u20B90';
        $('#kpi-expense').textContent = summary.total_expense_formatted || '\u20B90';
        $('#kpi-net').textContent = summary.net_cashflow_formatted || '\u20B90';
        $('#kpi-count').textContent = (summary.total_transactions || 0).toLocaleString();
    }

    // ── Render: Bank Breakdown ─────────────────────────────────────────
    function renderBankBreakdown(bankBreakdown) {
        const container = document.getElementById('bank-breakdown');
        if (!bankBreakdown || bankBreakdown.length === 0) {
            container.innerHTML = '<div class="ps-empty">No bank data available</div>';
            return;
        }
        container.innerHTML = bankBreakdown.map(b => `
            <div class="ps-bank-card bank-${b.bank_code}">
                <div class="ps-bank-name">${b.bank_name}</div>
                <div class="ps-bank-stats">
                    <div class="ps-bank-stat-row">
                        <span class="ps-bank-stat-label">Income</span>
                        <span class="ps-bank-stat-value income">${b.income_formatted}</span>
                    </div>
                    <div class="ps-bank-stat-row">
                        <span class="ps-bank-stat-label">Expense</span>
                        <span class="ps-bank-stat-value expense">${b.expense_formatted}</span>
                    </div>
                    <div class="ps-bank-stat-row">
                        <span class="ps-bank-stat-label">Net</span>
                        <span class="ps-bank-stat-value net">${b.net_formatted}</span>
                    </div>
                </div>
                <div class="ps-bank-count">${b.transaction_count} transactions</div>
            </div>
        `).join('');
    }

    // ── Render: Category Horizontal Bars ───────────────────────────────
    function renderCategoryBars(categoryBreakdown) {
        const container = document.getElementById('category-bars');
        if (!categoryBreakdown || categoryBreakdown.length === 0) {
            container.innerHTML = '<div class="ps-empty">No category data</div>';
            return;
        }

        const maxAmount = Math.max(...categoryBreakdown.map(c => c.amount));

        container.innerHTML = categoryBreakdown.map((c, i) => {
            const pct = maxAmount > 0 ? (c.amount / maxAmount * 100) : 0;
            const color = CATEGORY_COLORS[i % CATEGORY_COLORS.length];
            return `<div class="ps-cat-row">
                <div class="ps-cat-label" title="${escapeHtml(c.category)}">${escapeHtml(c.category)}</div>
                <div class="ps-cat-bar-wrap">
                    <div class="ps-cat-bar-track">
                        <div class="ps-cat-bar-fill" style="width: ${pct}%; background: ${color};"></div>
                    </div>
                    <div class="ps-cat-amount">${c.amount_formatted}</div>
                    <div class="ps-cat-pct">${c.percentage}%</div>
                </div>
            </div>`;
        }).join('');
    }

    // ── Render: Project Table (client-side pagination) ─────────────────
    function renderProjectTable() {
        const data = state.data.combined?.project_breakdown || [];
        const { page, perPage } = state.pagination.projectBreakdown;
        const totalPages = Math.ceil(data.length / perPage) || 1;
        const start = (page - 1) * perPage;
        const pageData = data.slice(start, start + perPage);

        const tbody = document.getElementById('project-table-body');
        if (pageData.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="ps-empty">No project data</td></tr>';
        } else {
            tbody.innerHTML = pageData.map(p => {
                const netClass = p.net >= 0 ? 'text-net-positive' : 'text-net-negative';
                return `<tr>
                    <td>${p.project}</td>
                    <td class="text-right text-income">${p.income_formatted}</td>
                    <td class="text-right text-expense">${p.expense_formatted}</td>
                    <td class="text-right ${netClass}">${p.net_formatted}</td>
                    <td class="text-right">${p.count}</td>
                </tr>`;
            }).join('');
        }

        renderPaginationControls('project-pagination', page, totalPages, (pg) => {
            state.pagination.projectBreakdown.page = pg;
            renderProjectTable();
        });
    }

    // ── Render: Vendor Table ───────────────────────────────────────────
    function renderVendorTable() {
        if (state.pagination.vendorBreakdown.showAll) {
            fetchVendorPage(state.pagination.vendorBreakdown.page);
        } else {
            renderVendorFromCombined();
        }
    }

    function renderVendorFromCombined() {
        const data = state.data.combined?.vendor_breakdown || [];
        const { page, perPage } = state.pagination.vendorBreakdown;
        const totalPages = Math.ceil(data.length / perPage) || 1;
        const start = (page - 1) * perPage;
        const pageData = data.slice(start, start + perPage);

        const tbody = document.getElementById('vendor-table-body');
        if (pageData.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="ps-empty">No vendor data</td></tr>';
        } else {
            tbody.innerHTML = pageData.map(v => `<tr>
                <td>${v.vendor}</td>
                <td class="text-right text-expense">${v.amount_formatted}</td>
                <td class="text-right">${v.count}</td>
                <td class="text-right">${v.percentage}%</td>
            </tr>`).join('');
        }

        renderPaginationControls('vendor-pagination', page, totalPages, (pg) => {
            state.pagination.vendorBreakdown.page = pg;
            renderVendorFromCombined();
        });
    }

    async function fetchVendorPage(page) {
        const params = buildQueryParams();
        params.set('page', page);
        params.set('per_page', state.pagination.vendorBreakdown.perPage);

        try {
            const result = await fetchJSON('/api/project-summary/vendors?' + params.toString());
            const tbody = document.getElementById('vendor-table-body');
            if (!result.vendors || result.vendors.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="ps-empty">No vendor data</td></tr>';
            } else {
                tbody.innerHTML = result.vendors.map(v => `<tr>
                    <td>${v.vendor}</td>
                    <td class="text-right text-expense">${v.amount_formatted}</td>
                    <td class="text-right">${v.count}</td>
                    <td class="text-right">${v.percentage}%</td>
                </tr>`).join('');
            }

            state.pagination.vendorBreakdown.page = result.page;
            renderPaginationControls('vendor-pagination', result.page, result.total_pages, (pg) => {
                state.pagination.vendorBreakdown.page = pg;
                fetchVendorPage(pg);
            });
        } catch (err) {
            console.error('Vendor fetch error:', err);
        }
    }

    // ── Render: Bank Transactions (server-side pagination) ─────────────
    async function fetchBankTransactions(bankCode, page) {
        const params = buildQueryParams();
        params.set('bank_code', bankCode);
        params.set('page', page);
        params.set('per_page', 15);

        try {
            const result = await fetchJSON('/api/project-summary/bank-transactions?' + params.toString());
            const tbody = document.getElementById('bank-txn-body');

            if (!result.transactions || result.transactions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="ps-empty">No transactions</td></tr>';
            } else {
                tbody.innerHTML = result.transactions.map(t => `<tr>
                    <td>${t.date}</td>
                    <td>${t.vendor}</td>
                    <td>${t.category}</td>
                    <td>${t.project || '-'}</td>
                    <td class="text-right ${t.dr_amount > 0 ? 'text-expense' : ''}">${t.dr_formatted}</td>
                    <td class="text-right ${t.cr_amount > 0 ? 'text-income' : ''}">${t.cr_formatted}</td>
                </tr>`).join('');
            }

            const paginationKey = bankCode + 'Transactions';
            state.pagination[paginationKey].page = result.page;

            renderPaginationControls('bank-txn-pagination', result.page, result.total_pages, (pg) => {
                state.pagination[paginationKey].page = pg;
                fetchBankTransactions(bankCode, pg);
            });
        } catch (err) {
            console.error('Bank txn fetch error:', err);
        }
    }

    // ── Render: Expense Tracker (Right Panel) ──────────────────────────
    // Replicates the exact personal tracker daily view
    function renderExpenseTracker() {
        const txns = state.data.personalTxns;

        // Update summary
        let income = 0;
        let expense = 0;
        txns.forEach(t => {
            if (t.transaction_type === 'income') {
                income += parseFloat(t.amount);
            } else {
                expense += parseFloat(t.amount);
            }
        });
        $('#personal-income').textContent = formatAmount(income);
        $('#personal-expense').textContent = formatAmount(expense);

        // Render daily view
        const container = document.getElementById('personal-daily-view');
        if (!txns || txns.length === 0) {
            container.innerHTML = '<div class="ps-empty">No transactions for this period</div>';
            return;
        }

        // Group by date
        const grouped = {};
        txns.forEach(t => {
            const d = t.date;
            if (!grouped[d]) grouped[d] = [];
            grouped[d].push(t);
        });

        const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const MONTHS = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'];

        let html = '';
        Object.keys(grouped).sort((a, b) => new Date(b) - new Date(a)).forEach(dateStr => {
            const dayTxns = grouped[dateStr];
            const date = new Date(dateStr);
            const dayIncome = dayTxns.filter(t => t.transaction_type === 'income').reduce((s, t) => s + parseFloat(t.amount), 0);
            const dayExpense = dayTxns.filter(t => t.transaction_type === 'expense').reduce((s, t) => s + parseFloat(t.amount), 0);

            html += `<div class="ps-et-date-group">
                <div class="ps-et-date-header">
                    <div class="ps-et-date-info">
                        <span class="ps-et-date-day">${String(date.getDate()).padStart(2, '0')}</span>
                        <span class="ps-et-date-weekday">${DAYS[date.getDay()]}</span>
                        <span class="ps-et-date-month">${MONTHS[date.getMonth()]}.${date.getFullYear()}</span>
                    </div>
                    <div class="ps-et-date-totals">
                        ${dayIncome > 0 ? `<span class="ps-et-date-income">${formatAmount(dayIncome)}</span>` : ''}
                        ${dayExpense > 0 ? `<span class="ps-et-date-expense">${formatAmount(dayExpense)}</span>` : ''}
                    </div>
                </div>`;

            dayTxns.forEach(t => {
                const cat = getCategoryInfo(t);
                const typeClass = t.transaction_type === 'income' ? 'income' : 'expense';
                const projectText = escapeHtml(t.project || 'General');
                const descText = t.description ? escapeHtml(t.description) : '';
                const metaText = descText ? `${projectText} &bull; ${descText}` : projectText;

                let bankBadge = '';
                if (t.bank) {
                    const bankClass = t.bank === 'axis' ? 'bank-axis' : 'bank-kvb';
                    bankBadge = `<span class="ps-et-bank-badge ${bankClass}">${t.bank.toUpperCase()}</span>`;
                }

                html += `<div class="ps-et-txn-row">
                    <div class="ps-et-txn-category">
                        <span class="ps-et-cat-icon">${cat.icon}</span>
                        <span class="ps-et-cat-name">${cat.name}</span>
                    </div>
                    <div class="ps-et-txn-details">
                        <div class="ps-et-txn-vendor">${escapeHtml(t.vendor)}${bankBadge}</div>
                        <div class="ps-et-txn-meta">${metaText}</div>
                    </div>
                    <div class="ps-et-txn-amount ${typeClass}">${formatAmount(t.amount)}</div>
                </div>`;
            });

            html += '</div>';
        });

        container.innerHTML = html;
    }

    // ── Start ──────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);

})();
