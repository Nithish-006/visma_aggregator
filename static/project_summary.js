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
        },
        charts: {
            categoryChart: null,
            monthlyChart: null
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
        // Indian grouping: last 3, then groups of 2
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

    // ── Category Colors ────────────────────────────────────────────────
    const CATEGORY_COLORS = [
        '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
        '#ec4899', '#06b6d4', '#f97316', '#6366f1', '#14b8a6',
        '#e11d48', '#84cc16', '#a855f7', '#0ea5e9', '#d946ef'
    ];

    // ── Init ───────────────────────────────────────────────────────────
    async function init() {
        showLoading();
        try {
            // Fetch date range and filter options in parallel
            const [dateRange, filterOptions] = await Promise.all([
                fetchJSON('/api/project-summary/date-range'),
                fetchJSON('/api/project-summary/projects')
            ]);

            // Populate date inputs
            if (dateRange.min_date) {
                $('#filter-start-date').value = dateRange.min_date;
                state.filters.startDate = dateRange.min_date;
            }
            if (dateRange.max_date) {
                $('#filter-end-date').value = dateRange.max_date;
                state.filters.endDate = dateRange.max_date;
            }

            // Populate project dropdown
            const projSelect = $('#filter-project');
            (filterOptions.projects || []).forEach(p => {
                const opt = document.createElement('option');
                opt.value = p;
                opt.textContent = p;
                projSelect.appendChild(opt);
            });

            // Populate category dropdown
            const catSelect = $('#filter-category');
            (filterOptions.categories || []).forEach(c => {
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                catSelect.appendChild(opt);
            });

            // Bind filter events
            bindFilterEvents();

            // Initial data load
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
            // Re-fetch date range for reset
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
        // Reset pagination
        state.pagination.projectBreakdown.page = 1;
        state.pagination.vendorBreakdown.page = 1;
        state.pagination.axisTransactions.page = 1;
        state.pagination.kvbTransactions.page = 1;

        const params = buildQueryParams();

        try {
            // Fetch combined + personal data in parallel
            const [combined, personalTxns, personalSummary] = await Promise.all([
                fetchJSON('/api/project-summary/combined?' + params.toString()),
                fetchJSON('/api/personal/transactions?' + params.toString()),
                fetchJSON('/api/personal/summary?' + params.toString())
            ]);

            state.data.combined = combined;
            state.data.personalTxns = personalTxns.transactions || [];
            state.data.personalSummary = personalSummary;

            // Render all sections
            renderKPI(combined.summary);
            renderBankBreakdown(combined.bank_breakdown);
            renderCategoryChart(combined.category_breakdown);
            renderMonthlyChart(combined.monthly_trend);
            renderProjectTable();
            renderVendorTable();
            renderPersonalPanel();

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

    // ── Render: Category Doughnut Chart ────────────────────────────────
    function renderCategoryChart(categoryBreakdown) {
        if (state.charts.categoryChart) {
            state.charts.categoryChart.destroy();
            state.charts.categoryChart = null;
        }

        const canvas = document.getElementById('category-chart');
        if (!canvas || !categoryBreakdown || categoryBreakdown.length === 0) return;

        const labels = categoryBreakdown.map(c => c.category);
        const data = categoryBreakdown.map(c => c.amount);
        const colors = categoryBreakdown.map((_, i) => CATEGORY_COLORS[i % CATEGORY_COLORS.length]);

        state.charts.categoryChart = new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: '#ffffff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            boxWidth: 12,
                            padding: 8,
                            font: { size: 11, family: 'Inter' },
                            color: '#4a4a68'
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                const item = categoryBreakdown[ctx.dataIndex];
                                return `${item.category}: ${item.amount_formatted} (${item.percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    // ── Render: Monthly Trend Bar Chart ────────────────────────────────
    function renderMonthlyChart(monthlyTrend) {
        if (state.charts.monthlyChart) {
            state.charts.monthlyChart.destroy();
            state.charts.monthlyChart = null;
        }

        const canvas = document.getElementById('monthly-chart');
        if (!canvas || !monthlyTrend || !monthlyTrend.months || monthlyTrend.months.length === 0) return;

        state.charts.monthlyChart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: monthlyTrend.months,
                datasets: [
                    {
                        label: 'Income',
                        data: monthlyTrend.income,
                        backgroundColor: 'rgba(16, 185, 129, 0.7)',
                        borderColor: '#059669',
                        borderWidth: 1,
                        borderRadius: 4,
                        order: 2
                    },
                    {
                        label: 'Expense',
                        data: monthlyTrend.expense,
                        backgroundColor: 'rgba(239, 68, 68, 0.7)',
                        borderColor: '#dc2626',
                        borderWidth: 1,
                        borderRadius: 4,
                        order: 2
                    },
                    {
                        label: 'Net',
                        data: monthlyTrend.net,
                        type: 'line',
                        borderColor: '#2563eb',
                        backgroundColor: 'rgba(37, 99, 235, 0.1)',
                        borderWidth: 2,
                        pointRadius: 3,
                        pointBackgroundColor: '#2563eb',
                        tension: 0.3,
                        fill: false,
                        order: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: {
                            font: { size: 10, family: 'Inter' },
                            color: '#6b7280',
                            maxRotation: 45
                        }
                    },
                    y: {
                        grid: { color: 'rgba(0,0,0,0.04)' },
                        ticks: {
                            font: { size: 10, family: 'Inter' },
                            color: '#6b7280',
                            callback: (v) => {
                                if (Math.abs(v) >= 10000000) return '\u20B9' + (v / 10000000).toFixed(1) + 'Cr';
                                if (Math.abs(v) >= 100000) return '\u20B9' + (v / 100000).toFixed(1) + 'L';
                                if (Math.abs(v) >= 1000) return '\u20B9' + (v / 1000).toFixed(0) + 'K';
                                return '\u20B9' + v;
                            }
                        }
                    }
                },
                plugins: {
                    legend: {
                        labels: {
                            boxWidth: 12,
                            padding: 10,
                            font: { size: 11, family: 'Inter' },
                            color: '#4a4a68'
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                return ctx.dataset.label + ': ' + formatIndianNumber(ctx.raw);
                            }
                        }
                    }
                }
            }
        });
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
            // Show top 20 from combined data
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

    // ── Render: Personal Panel (Right side) ────────────────────────────
    function renderPersonalPanel() {
        const summary = state.data.personalSummary;
        const txns = state.data.personalTxns;

        // Summary
        if (summary) {
            $('#personal-income').textContent = summary.total_income_formatted || '\u20B90';
            $('#personal-expense').textContent = summary.total_expense_formatted || '\u20B90';
            const netEl = $('#personal-net');
            netEl.textContent = summary.net_balance_formatted || '\u20B90';
            netEl.className = 'ps-personal-value ' + (summary.net_balance_positive !== false ? 'income' : 'expense');
        }

        // Transaction list grouped by date
        renderPersonalTransactions(txns);

        // Project breakdown bars
        if (summary && summary.project_breakdown) {
            renderPersonalProjectBars(summary.project_breakdown);
        }
    }

    function renderPersonalTransactions(txns) {
        const container = document.getElementById('personal-txn-list');
        if (!txns || txns.length === 0) {
            container.innerHTML = '<div class="ps-empty">No personal transactions</div>';
            return;
        }

        // Group by date
        const groups = {};
        txns.forEach(t => {
            const d = t.date_formatted || t.date;
            if (!groups[d]) groups[d] = [];
            groups[d].push(t);
        });

        let html = '';
        for (const [date, items] of Object.entries(groups)) {
            html += `<div class="ps-ptxn-date-group">
                <div class="ps-ptxn-date-header">${date}</div>`;
            items.forEach(t => {
                const typeClass = t.transaction_type === 'income' ? 'income' : 'expense';
                const sign = t.transaction_type === 'income' ? '+' : '-';
                html += `<div class="ps-ptxn-row">
                    <div class="ps-ptxn-info">
                        <div class="ps-ptxn-vendor">${t.vendor}</div>
                        <div class="ps-ptxn-project">${t.project || ''}</div>
                    </div>
                    <div class="ps-ptxn-amount ${typeClass}">${sign}${t.amount_formatted}</div>
                </div>`;
            });
            html += '</div>';
        }

        container.innerHTML = html;
    }

    function renderPersonalProjectBars(projectBreakdown) {
        const container = document.getElementById('personal-project-bars');
        if (!projectBreakdown || projectBreakdown.length === 0) {
            container.innerHTML = '<div class="ps-empty">No project data</div>';
            return;
        }

        const maxAmount = Math.max(...projectBreakdown.map(p => p.amount));

        container.innerHTML = projectBreakdown.map(p => {
            const pct = maxAmount > 0 ? (p.amount / maxAmount * 100) : 0;
            return `<div class="ps-pbar-row">
                <div class="ps-pbar-header">
                    <span class="ps-pbar-name">${p.project}</span>
                    <span class="ps-pbar-amount">${p.amount_formatted}</span>
                </div>
                <div class="ps-pbar-track">
                    <div class="ps-pbar-fill" style="width: ${pct}%"></div>
                </div>
            </div>`;
        }).join('');
    }

    // ── Start ──────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);

})();
