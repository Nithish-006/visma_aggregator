/* ============================================================================
   PROJECT SUMMARY - Client-Side Logic
   ============================================================================ */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────────
    const state = {
        filters: { startDate: '', endDate: '', project: [], category: [], vendor: [] },
        pagination: {
            projectBreakdown: { page: 1, perPage: 15 },
            vendorBreakdown: { page: 1, perPage: 15, showAll: false },
            axisTransactions: { page: 1, perPage: 15 },
            kvbTransactions: { page: 1, perPage: 15 },
            bills: { page: 1, perPage: 15 }
        },
        activeBankTab: 'axis',
        etBankFilter: 'all',
        data: {
            combined: null,
            personalTxns: [],
            personalSummary: null,
            bills: { bills: [], total: 0 }
        }
    };

    // ── Dropdown instances ───────────────────────────────────────────
    const dropdowns = {};

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
        if (state.filters.project.length > 0) p.set('project', state.filters.project.join(','));
        if (state.filters.category.length > 0) p.set('category', state.filters.category.join(','));
        if (state.filters.vendor.length > 0) p.set('vendor', state.filters.vendor.join(','));
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

    // ── Custom Multi-Select Dropdown ──────────────────────────────────
    class PSDropdown {
        constructor(containerId, placeholder, type) {
            this.container = document.getElementById(containerId);
            this.placeholder = placeholder;
            this.type = type;
            this.options = [];
            this.selectedValues = new Set();
            this.isOpen = false;

            if (this.container) {
                this.render();
                this.attachEvents();
            }
            dropdowns[containerId] = this;
        }

        render() {
            this.container.innerHTML = `
                <div class="ps-dd-trigger" id="${this.container.id}-trigger">
                    <span class="ps-dd-text">${this.placeholder}</span>
                    <svg class="ps-dd-arrow" width="10" height="6" viewBox="0 0 10 6" fill="none">
                        <path d="M1 1L5 5L9 1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </div>
                <div class="ps-dd-menu">
                    <div class="ps-dd-search">
                        <input type="text" placeholder="Search..." id="${this.container.id}-search">
                    </div>
                    <div class="ps-dd-options" id="${this.container.id}-options"></div>
                </div>
            `;

            this.triggerBtn = this.container.querySelector('.ps-dd-trigger');
            this.triggerText = this.container.querySelector('.ps-dd-text');
            this.menu = this.container.querySelector('.ps-dd-menu');
            this.searchInput = this.container.querySelector('input');
            this.optionsContainer = this.container.querySelector('.ps-dd-options');
        }

        attachEvents() {
            this.triggerBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleMenu();
            });

            this.searchInput.addEventListener('input', (e) => {
                this.filterOptions(e.target.value);
            });

            this.searchInput.addEventListener('click', (e) => e.stopPropagation());
        }

        setOptions(items) {
            this.options = items;
            // Auto-cleanup: remove selections no longer in the options list
            const itemSet = new Set(items);
            let changed = false;
            for (const val of this.selectedValues) {
                if (!itemSet.has(val)) {
                    this.selectedValues.delete(val);
                    changed = true;
                }
            }
            if (changed) {
                this.updateTriggerText();
                this.syncFilters();
            }
            this.renderOptions(items);
        }

        renderOptions(items) {
            this.optionsContainer.innerHTML = '';
            if (items.length === 0) {
                this.optionsContainer.innerHTML = '<div class="ps-dd-empty">No results</div>';
                return;
            }

            items.forEach(item => {
                const optionEl = document.createElement('div');
                optionEl.className = `ps-dd-option ${this.selectedValues.has(item) ? 'selected' : ''}`;
                optionEl.dataset.value = item;
                optionEl.innerHTML = `
                    <div class="ps-dd-checkbox"></div>
                    <span>${escapeHtml(item)}</span>
                `;
                optionEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleOption(item);
                });
                this.optionsContainer.appendChild(optionEl);
            });
        }

        toggleOption(value) {
            if (this.selectedValues.has(value)) {
                this.selectedValues.delete(value);
            } else {
                this.selectedValues.add(value);
            }
            this.updateUI();
            this.updateTriggerText();
            this.syncFilters();

            if (window._psFilterTimeout) clearTimeout(window._psFilterTimeout);
            window._psFilterTimeout = setTimeout(() => refreshAll(), 300);
        }

        updateUI() {
            this.optionsContainer.querySelectorAll('.ps-dd-option').forEach(opt => {
                opt.classList.toggle('selected', this.selectedValues.has(opt.dataset.value));
            });
        }

        updateTriggerText() {
            if (this.selectedValues.size === 0) {
                this.triggerText.textContent = this.placeholder;
                this.triggerBtn.classList.remove('has-selection');
            } else if (this.selectedValues.size === 1) {
                this.triggerText.textContent = Array.from(this.selectedValues)[0];
                this.triggerBtn.classList.add('has-selection');
            } else {
                this.triggerText.textContent = `${this.selectedValues.size} Selected`;
                this.triggerBtn.classList.add('has-selection');
            }
        }

        syncFilters() {
            const vals = Array.from(this.selectedValues);
            if (this.type === 'project') state.filters.project = vals;
            if (this.type === 'category') state.filters.category = vals;
            if (this.type === 'vendor') state.filters.vendor = vals;
        }

        toggleMenu() {
            this.isOpen = !this.isOpen;
            if (this.isOpen) {
                Object.values(dropdowns).forEach(d => { if (d !== this) d.closeMenu(); });
                this.container.classList.add('open');
                this.searchInput.value = '';
                this.renderOptions(this.options);
                this.searchInput.focus();
            } else {
                this.closeMenu();
            }
        }

        closeMenu() {
            this.isOpen = false;
            this.container.classList.remove('open');
        }

        filterOptions(query) {
            const q = query.toLowerCase();
            const filtered = this.options.filter(item => item.toLowerCase().includes(q));
            this.renderOptions(filtered);
        }

        clear() {
            this.selectedValues.clear();
            this.updateUI();
            this.updateTriggerText();
            this.syncFilters();
        }

        /** Programmatically toggle a single value (used by cross-filter clicks) */
        toggleValue(value) {
            if (this.selectedValues.has(value)) {
                this.selectedValues.delete(value);
            } else {
                this.selectedValues.add(value);
            }
            this.updateUI();
            this.updateTriggerText();
            this.syncFilters();
        }

        /** Check if a value is currently selected */
        hasValue(value) {
            return this.selectedValues.has(value);
        }
    }

    // Close dropdowns on outside click
    document.addEventListener('click', () => {
        Object.values(dropdowns).forEach(d => d.closeMenu());
    });

    // ── Cross-Filter Helpers ────────────────────────────────────────────
    function applyCrossFilter(type, value) {
        const dropdownMap = {
            'project': 'dropdown-project',
            'category': 'dropdown-category',
            'vendor': 'dropdown-vendor'
        };
        const dd = dropdowns[dropdownMap[type]];
        if (!dd) return;
        dd.toggleValue(value);

        // Reset pagination since filtered data changes
        state.pagination.projectBreakdown.page = 1;
        state.pagination.vendorBreakdown.page = 1;
        state.pagination.axisTransactions.page = 1;
        state.pagination.kvbTransactions.page = 1;
        state.pagination.bills.page = 1;

        refreshAll();
    }

    function isCrossFilterActive(type, value) {
        const dropdownMap = {
            'project': 'dropdown-project',
            'category': 'dropdown-category',
            'vendor': 'dropdown-vendor'
        };
        const dd = dropdowns[dropdownMap[type]];
        return dd ? dd.hasValue(value) : false;
    }

    /** Render active cross-filter chips above KPI cards */
    function renderCrossFilterChips() {
        let container = document.getElementById('cross-filter-chips');
        const hasFilters = state.filters.project.length > 0 ||
            state.filters.category.length > 0 ||
            state.filters.vendor.length > 0;

        if (!hasFilters) {
            if (container) container.innerHTML = '';
            if (container) container.classList.add('hidden');
            return;
        }

        if (!container) {
            container = document.createElement('div');
            container.id = 'cross-filter-chips';
            container.className = 'ps-cross-filter-bar';
            const kpiGrid = document.querySelector('.ps-kpi-grid');
            kpiGrid.parentNode.insertBefore(container, kpiGrid);
        }

        container.classList.remove('hidden');
        let html = '<span class="ps-cf-label">Active Filters:</span>';

        state.filters.project.forEach(val => {
            html += `<span class="ps-cf-chip project" data-type="project" data-value="${escapeHtml(val)}">
                ${escapeHtml(val)}
                <svg class="ps-cf-remove" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </span>`;
        });
        state.filters.category.forEach(val => {
            html += `<span class="ps-cf-chip category" data-type="category" data-value="${escapeHtml(val)}">
                ${escapeHtml(val)}
                <svg class="ps-cf-remove" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </span>`;
        });
        state.filters.vendor.forEach(val => {
            html += `<span class="ps-cf-chip vendor" data-type="vendor" data-value="${escapeHtml(val)}">
                ${escapeHtml(val)}
                <svg class="ps-cf-remove" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </span>`;
        });

        html += `<button class="ps-cf-clear-all" id="cf-clear-all">Clear All</button>`;
        container.innerHTML = html;

        // Bind chip remove clicks
        container.querySelectorAll('.ps-cf-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                applyCrossFilter(chip.dataset.type, chip.dataset.value);
            });
        });

        // Bind clear all
        const clearBtn = document.getElementById('cf-clear-all');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                Object.values(dropdowns).forEach(d => d.clear());
                state.filters.project = [];
                state.filters.category = [];
                state.filters.vendor = [];
                refreshAll();
            });
        }
    }

    // ── Init ───────────────────────────────────────────────────────────
    async function init() {
        showLoading();
        try {
            // Create dropdown instances
            const ddProject = new PSDropdown('dropdown-project', 'All Projects', 'project');
            const ddCategory = new PSDropdown('dropdown-category', 'All Categories', 'category');
            const ddVendor = new PSDropdown('dropdown-vendor', 'All Vendors', 'vendor');

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

            ddProject.setOptions(filterOptions.projects || []);
            ddCategory.setOptions(filterOptions.categories || []);
            ddVendor.setOptions(filterOptions.vendors || []);

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

        // Reset button
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

            // Clear all dropdowns
            Object.values(dropdowns).forEach(d => d.clear());
            state.filters.project = [];
            state.filters.category = [];
            state.filters.vendor = [];
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

        // Expense Tracker bank toggle
        $$('.ps-et-bank-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                $$('.ps-et-bank-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.etBankFilter = btn.dataset.bank;
                renderExpenseTracker();
            });
        });

        // Export button
        $('#export-btn').addEventListener('click', () => {
            const params = buildQueryParams();
            window.location.href = '/api/project-summary/export?' + params.toString();
        });
    }

    // ── Refresh All ────────────────────────────────────────────────────
    async function refreshAll() {
        state.pagination.projectBreakdown.page = 1;
        state.pagination.vendorBreakdown.page = 1;
        state.pagination.axisTransactions.page = 1;
        state.pagination.kvbTransactions.page = 1;
        state.pagination.bills.page = 1;

        const params = buildQueryParams();

        try {
            const [combined, personalTxns, filterOpts] = await Promise.all([
                fetchJSON('/api/project-summary/combined?' + params.toString()),
                fetchJSON('/api/personal/transactions?' + params.toString()),
                fetchJSON('/api/project-summary/filter-options?' + params.toString())
            ]);

            state.data.combined = combined;
            state.data.personalTxns = personalTxns.transactions || [];

            // Update dropdown options dynamically
            if (filterOpts) {
                dropdowns['dropdown-project']?.setOptions(filterOpts.projects || []);
                dropdowns['dropdown-category']?.setOptions(filterOpts.categories || []);
                dropdowns['dropdown-vendor']?.setOptions(filterOpts.vendors || []);
            }

            // Render all sections
            renderCrossFilterChips();
            renderKPI(combined.summary);
            renderBankBreakdown(combined.bank_breakdown);
            renderCategoryBars(combined.category_breakdown);
            renderProjectTable();
            renderVendorTable();
            renderExpenseTracker();

            // Fetch active bank tab transactions and bills
            fetchBankTransactions(state.activeBankTab, 1);
            fetchBills(1);
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
            const isActive = isCrossFilterActive('category', c.category);
            return `<div class="ps-cat-row ps-clickable ${isActive ? 'ps-cf-active' : ''}" data-cf-type="category" data-cf-value="${escapeHtml(c.category)}">
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

        // Bind cross-filter clicks on category rows
        container.querySelectorAll('[data-cf-type="category"]').forEach(row => {
            row.addEventListener('click', () => {
                applyCrossFilter('category', row.dataset.cfValue);
            });
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
                const isActive = isCrossFilterActive('project', p.project);
                return `<tr class="ps-clickable ${isActive ? 'ps-cf-active' : ''}" data-cf-type="project" data-cf-value="${escapeHtml(p.project)}">
                    <td>${escapeHtml(p.project)}</td>
                    <td class="text-right text-income">${p.income_formatted}</td>
                    <td class="text-right text-expense">${p.expense_formatted}</td>
                    <td class="text-right ${netClass}">${p.net_formatted}</td>
                    <td class="text-right">${p.count}</td>
                </tr>`;
            }).join('');
        }

        // Bind cross-filter clicks on project rows
        tbody.querySelectorAll('[data-cf-type="project"]').forEach(row => {
            row.addEventListener('click', () => {
                applyCrossFilter('project', row.dataset.cfValue);
            });
        });

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
            tbody.innerHTML = pageData.map(v => {
                const isActive = isCrossFilterActive('vendor', v.vendor);
                return `<tr class="ps-clickable ${isActive ? 'ps-cf-active' : ''}" data-cf-type="vendor" data-cf-value="${escapeHtml(v.vendor)}">
                    <td>${escapeHtml(v.vendor)}</td>
                    <td class="text-right text-expense">${v.amount_formatted}</td>
                    <td class="text-right">${v.count}</td>
                    <td class="text-right">${v.percentage}%</td>
                </tr>`;
            }).join('');
        }

        // Bind cross-filter clicks on vendor rows
        tbody.querySelectorAll('[data-cf-type="vendor"]').forEach(row => {
            row.addEventListener('click', () => {
                applyCrossFilter('vendor', row.dataset.cfValue);
            });
        });

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
                tbody.innerHTML = result.vendors.map(v => {
                    const isActive = isCrossFilterActive('vendor', v.vendor);
                    return `<tr class="ps-clickable ${isActive ? 'ps-cf-active' : ''}" data-cf-type="vendor" data-cf-value="${escapeHtml(v.vendor)}">
                        <td>${escapeHtml(v.vendor)}</td>
                        <td class="text-right text-expense">${v.amount_formatted}</td>
                        <td class="text-right">${v.count}</td>
                        <td class="text-right">${v.percentage}%</td>
                    </tr>`;
                }).join('');
            }

            // Bind cross-filter clicks on vendor rows
            tbody.querySelectorAll('[data-cf-type="vendor"]').forEach(row => {
                row.addEventListener('click', () => {
                    applyCrossFilter('vendor', row.dataset.cfValue);
                });
            });

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
    function renderExpenseTracker() {
        let txns = state.data.personalTxns;

        // Apply bank filter
        if (state.etBankFilter !== 'all') {
            txns = txns.filter(t => t.bank === state.etBankFilter);
        }

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

    // ── Render: Bills Table (server-side pagination) ────────────────────
    async function fetchBills(page) {
        const params = buildQueryParams();
        params.set('page', page);
        params.set('per_page', state.pagination.bills.perPage);

        try {
            const result = await fetchJSON('/api/project-summary/bills?' + params.toString());
            state.data.bills = result;
            state.pagination.bills.page = result.page;
            renderBillsTable();
        } catch (err) {
            console.error('Bills fetch error:', err);
        }
    }

    function renderBillsTable() {
        const data = state.data.bills;
        const tbody = document.getElementById('bills-table-body');
        if (!tbody) return;

        if (!data.bills || data.bills.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="ps-empty">No bills found</td></tr>';
            renderPaginationControls('bills-pagination', 1, 0, () => {});
            const summaryEl = document.getElementById('bills-summary');
            if (summaryEl) summaryEl.textContent = '';
            return;
        }

        tbody.innerHTML = data.bills.map(b => `<tr>
            <td><a href="#" class="ps-bill-link" data-bill-id="${b.id}">${escapeHtml(b.invoice_number || '-')}</a></td>
            <td>${escapeHtml(b.invoice_date || '-')}</td>
            <td class="cell-wrap">${escapeHtml(b.vendor_name || '-')}</td>
            <td>${escapeHtml(b.vendor_gstin || '-')}</td>
            <td class="text-right">${b.line_item_count || 0}</td>
            <td class="text-right text-expense">${formatIndianNumber(b.total_amount || 0)}</td>
            <td>${escapeHtml(b.project || '-')}</td>
        </tr>`).join('');

        // Bind bill detail links
        tbody.querySelectorAll('.ps-bill-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                viewBillDetail(link.dataset.billId);
            });
        });

        renderPaginationControls('bills-pagination', data.page, data.total_pages, (pg) => {
            fetchBills(pg);
        });

        // Update summary text
        const summaryEl = document.getElementById('bills-summary');
        if (summaryEl && data.summary) {
            summaryEl.textContent = `${data.total} bills | Total: ${formatIndianNumber(data.summary.total_amount)} | GST: ${formatIndianNumber(data.summary.total_gst)}`;
        }
    }

    async function viewBillDetail(id) {
        try {
            const response = await fetchJSON(`/api/bills/stored/${id}`);
            renderBillDetailModal(response.bill);
        } catch (err) {
            console.error('Bill detail error:', err);
        }
    }

    function renderBillDetailModal(bill) {
        const modal = document.getElementById('bill-detail-modal');
        if (!modal) return;

        const lineItems = bill.line_items || [];
        let lineItemsHtml = '';
        if (lineItems.length > 0) {
            lineItemsHtml = `
                <h4 style="margin-top:24px;margin-bottom:14px;font-size:0.95rem;">Line Items</h4>
                <div class="ps-table-wrap">
                <table class="ps-table">
                    <thead><tr>
                        <th>#</th><th>Description</th><th>HSN</th><th>Qty</th><th class="text-right">Rate</th><th class="text-right">Amount</th>
                    </tr></thead>
                    <tbody>${lineItems.map(item => `<tr>
                        <td>${item.sl_no || ''}</td>
                        <td class="cell-wrap">${escapeHtml(item.description || '')}</td>
                        <td>${escapeHtml(item.hsn_sac_code || '')}</td>
                        <td>${item.quantity || ''}</td>
                        <td class="text-right">${item.rate_per_unit ? formatIndianNumber(item.rate_per_unit) : ''}</td>
                        <td class="text-right">${item.amount ? formatIndianNumber(item.amount) : ''}</td>
                    </tr>`).join('')}</tbody>
                </table>
                </div>`;
        }

        modal.innerHTML = `
            <div class="ps-bill-modal-overlay" id="bill-modal-overlay">
                <div class="ps-bill-modal-content">
                    <div class="ps-bill-modal-header">
                        <h3>Invoice #${escapeHtml(bill.invoice_number || 'N/A')}</h3>
                        <button class="ps-bill-modal-close" id="bill-modal-close">&times;</button>
                    </div>
                    <div class="ps-bill-modal-body">
                        <div class="ps-bill-detail-grid">
                            <div class="ps-bill-detail-section">
                                <h4>Invoice Details</h4>
                                <div class="ps-bill-detail-row"><span>Date:</span><span>${escapeHtml(bill.invoice_date || '-')}</span></div>
                                <div class="ps-bill-detail-row"><span>IRN:</span><span style="word-break:break-all;">${escapeHtml(bill.irn || '-')}</span></div>
                                <div class="ps-bill-detail-row"><span>Project:</span><span>${escapeHtml(bill.project || '-')}</span></div>
                            </div>
                            <div class="ps-bill-detail-section">
                                <h4>Vendor</h4>
                                <div class="ps-bill-detail-row"><span>Name:</span><span>${escapeHtml(bill.vendor_name || '-')}</span></div>
                                <div class="ps-bill-detail-row"><span>GSTIN:</span><span>${escapeHtml(bill.vendor_gstin || '-')}</span></div>
                                <div class="ps-bill-detail-row"><span>Address:</span><span>${escapeHtml(bill.vendor_address || '-')}</span></div>
                            </div>
                            <div class="ps-bill-detail-section">
                                <h4>Buyer</h4>
                                <div class="ps-bill-detail-row"><span>Name:</span><span>${escapeHtml(bill.buyer_name || '-')}</span></div>
                                <div class="ps-bill-detail-row"><span>GSTIN:</span><span>${escapeHtml(bill.buyer_gstin || '-')}</span></div>
                            </div>
                        </div>
                        ${lineItemsHtml}
                        <div class="ps-bill-totals">
                            <div class="ps-bill-total-row"><span>Subtotal:</span><span>${formatIndianNumber(bill.subtotal || 0)}</span></div>
                            <div class="ps-bill-total-row"><span>CGST:</span><span>${formatIndianNumber(bill.total_cgst || 0)}</span></div>
                            <div class="ps-bill-total-row"><span>SGST:</span><span>${formatIndianNumber(bill.total_sgst || 0)}</span></div>
                            ${bill.total_igst > 0 ? `<div class="ps-bill-total-row"><span>IGST:</span><span>${formatIndianNumber(bill.total_igst)}</span></div>` : ''}
                            <div class="ps-bill-total-row total"><span>Total:</span><span>${formatIndianNumber(bill.total_amount || 0)}</span></div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        modal.classList.remove('hidden');

        document.getElementById('bill-modal-close')?.addEventListener('click', () => {
            modal.classList.add('hidden');
        });
        document.getElementById('bill-modal-overlay')?.addEventListener('click', (e) => {
            if (e.target === e.currentTarget) modal.classList.add('hidden');
        });
    }

    // ── Start ──────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);

})();
