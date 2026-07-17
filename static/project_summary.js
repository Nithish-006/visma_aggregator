/* ============================================================================
   PROJECT SUMMARY - Client-Side Logic
   ============================================================================ */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────────────────
    const state = {
        // The page is project-scoped: the landing shows registry-fed cards
        // and every detail view is pinned to one canonical project.
        currentProject: null,      // canonical display, e.g. "659 - JAMUNA"
        // The numeric id behind that display. The filtered endpoints match on the
        // display string, but the glance reads /api/projects/<id>/insights — the
        // registry's own endpoint — so it needs the id.
        currentProjectId: null,
        registryCards: [],
        defaultDates: { min: '', max: '' },
        // month: '' = all months; otherwise 'YYYY-MM' (mapped to a date range when querying)
        filters: { month: '', project: [], category: [], vendor: [] },
        pagination: {
            vendorBreakdown: { page: 1, perPage: 15, showAll: false },
            axisTransactions: { page: 1, perPage: 15 },
            kvbTransactions: { page: 1, perPage: 15 },
            bills: { page: 1, perPage: 15 },
            salesBills: { page: 1, perPage: 15 }
        },
        activeBankTab: 'axis',
        data: {
            combined: null,
            personalSummary: null,
            bills: { bills: [], total: 0 },
            salesBills: { bills: [], total: 0 }
        }
    };

    // ── Dropdown instances ───────────────────────────────────────────
    const dropdowns = {};

    // Monotonic token for in-flight refreshes: every filter change bumps it,
    // and any response carrying an older token is dropped. Without this,
    // overlapping requests (slow combined endpoint + rapid filter clicks)
    // resolve out of order and a stale unfiltered payload overwrites the
    // filtered numbers on screen.
    let refreshSeq = 0;

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

    // Compact Indian format for tight card cells (same as the registry page):
    // 22165179 -> ₹2.22 Cr, 6640450 -> ₹66.40 L. Full value goes in a tooltip.
    function formatINRCompact(value) {
        const n = Number(value) || 0;
        const sign = n < 0 ? '-' : '';
        const abs = Math.abs(n);
        if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
        if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
        return sign + '₹' + abs.toLocaleString('en-IN', { maximumFractionDigits: 0 });
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

    // 'YYYY-MM' -> {start: 'YYYY-MM-01', end: 'YYYY-MM-<lastday>'}; null when 'All'.
    function monthToRange(month) {
        if (!month) return null;
        const [y, m] = month.split('-').map(Number);
        const last = new Date(y, m, 0).getDate(); // day 0 of next month = last day of this
        const mm = String(m).padStart(2, '0');
        return { start: `${y}-${mm}-01`, end: `${y}-${mm}-${String(last).padStart(2, '0')}` };
    }

    function buildQueryParams() {
        const p = new URLSearchParams();
        const range = monthToRange(state.filters.month);
        if (range) {
            p.set('start_date', range.start);
            p.set('end_date', range.end);
        }
        // Canonical "<id> - NAME" — the backend matches it strictly by id.
        if (state.currentProject) p.set('project', state.currentProject);
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
            // Keep current selections in the list even when the refreshed
            // option set no longer contains them (e.g. the other filters or
            // the date range exclude every matching row) — otherwise a user's
            // filter silently un-applies itself mid-session.
            const merged = [...items];
            for (const val of this.selectedValues) {
                if (!merged.includes(val)) merged.unshift(val);
            }
            this.options = merged;
            this.renderOptions(merged);
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

    /** Render active cross-filter chips, under the glance and above the sections they filter */
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
            // Below the glance, not above it: these chips describe what the
            // sections underneath are filtered to, and the glance deliberately
            // ignores them. Anchoring above would claim it was filtered too.
            const glance = document.getElementById('ps-glance');
            if (glance && glance.parentNode) {
                glance.parentNode.insertBefore(container, glance.nextSibling);
            } else {
                const left = document.querySelector('.ps-left');
                if (left) left.insertBefore(container, left.firstChild);
            }
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

    // ── Landing: registry-fed project cards ───────────────────────────
    // Mirrors the registry page's grouping so the two pages feel like one.
    const TYPE_SECTIONS = [
        { key: 'project', title: 'Projects', sub: 'Valid client / site projects', variant: 'projects' },
        { key: 'design', title: 'Designs', sub: 'Design-only work', variant: 'designs' },
        { key: 'other', title: 'Others', sub: 'Internal heads (office, factory, KVB…)', variant: 'others' },
    ];

    function renderLanding() {
        const wrap = document.getElementById('ps-cards');
        if (!state.registryCards.length) {
            wrap.innerHTML = '<div class="ps-empty">No projects in the registry yet. Add them on the Projects page first.</div>';
            return;
        }
        wrap.innerHTML = TYPE_SECTIONS.map(sec => {
            const items = state.registryCards.filter(c => (c.project_type || 'project') === sec.key);
            if (!items.length) return '';
            return `<section class="ps-proj-section ps-proj-section--${sec.variant}">
                <div class="ps-proj-section-head">
                    <h2 class="ps-proj-section-title">${sec.title} <span class="ps-proj-count">${items.length}</span></h2>
                    <span class="ps-proj-sub">${sec.sub}</span>
                </div>
                <div class="ps-proj-grid">
                    ${items.map(c => `
                    <button type="button" class="ps-proj-card" data-display="${escapeHtml(c.display)}"
                            data-title="${c.id} − ${escapeHtml(c.stem_name)}">
                        <div class="ps-proj-card-main">
                            <span class="ps-proj-card-id">${c.id}</span>
                            <span class="ps-proj-card-name">${escapeHtml(c.stem_name)}</span>
                        </div>
                        <div class="ps-proj-fin">
                            <div class="ps-proj-fin-cell"><span class="k">Income</span><span class="v income" title="${escapeHtml(c.income_formatted)}">${formatINRCompact(c.income)}</span></div>
                            <div class="ps-proj-fin-cell"><span class="k">Expense</span><span class="v expense" title="${escapeHtml(c.expense_formatted)}">${formatINRCompact(c.expense)}</span></div>
                            <div class="ps-proj-fin-cell"><span class="k">Txns</span><span class="v">${(c.txn_count || 0).toLocaleString()}</span></div>
                        </div>
                    </button>`).join('')}
                </div>
            </section>`;
        }).join('');
    }

    function bindLandingEvents() {
        document.getElementById('ps-cards').addEventListener('click', (e) => {
            const card = e.target.closest('.ps-proj-card');
            if (card) openProject(card.dataset.display, card.dataset.title);
        });
        // Header back: from a project detail return to the cards; from the
        // landing it keeps its normal link behaviour (back to the hub).
        document.getElementById('ps-back-btn').addEventListener('click', (e) => {
            if (!document.getElementById('ps-detail').classList.contains('hidden')) {
                e.preventDefault();
                showLanding();
            }
        });
    }

    function showLanding() {
        state.currentProject = null;
        refreshSeq++; // drop any in-flight detail responses
        document.getElementById('ps-detail').classList.add('hidden');
        document.getElementById('ps-landing').classList.remove('hidden');
        document.getElementById('export-btn').classList.add('hidden');
        document.getElementById('ps-title').textContent = 'Project Summary';
        window.scrollTo(0, 0);
    }

    // The canonical tag is "<id> - NAME", so the id is readable straight off the
    // display string. That matters for the deep-link case, where the registry
    // card may not be in the landing set (e.g. an inactive project).
    function projectIdFromDisplay(display) {
        const m = /^\s*(\d+)\s*-/.exec(String(display || ''));
        return m ? Number(m[1]) : null;
    }

    async function openProject(display, title) {
        state.currentProject = display;
        const card = state.registryCards.find(c => c.display === display);
        state.currentProjectId = (card && card.id) || projectIdFromDisplay(display);
        document.getElementById('ps-title').textContent = title || display;
        document.getElementById('ps-landing').classList.add('hidden');
        document.getElementById('ps-detail').classList.remove('hidden');
        document.getElementById('export-btn').classList.remove('hidden');
        // Fresh secondary filters for every project — default to All months.
        state.filters.month = '';
        renderMonthPills();
        Object.values(dropdowns).forEach(d => d.clear());
        state.filters.category = [];
        state.filters.vendor = [];
        window.scrollTo(0, 0);
        showLoading();
        try {
            // Painted once per open, alongside the filtered sections rather than
            // inside refreshAll — the filters don't reach it.
            await Promise.all([renderGlance(state.currentProjectId), refreshAll()]);
        } finally {
            hideLoading();
        }
    }

    // ── Init ───────────────────────────────────────────────────────────
    async function init() {
        try {
            new PSDropdown('dropdown-category', 'All Categories', 'category');
            new PSDropdown('dropdown-vendor', 'All Vendors', 'vendor');

            const [dateRange, cards] = await Promise.all([
                fetchJSON('/api/project-summary/date-range'),
                fetchJSON('/api/project-summary/project-cards')
            ]);
            state.defaultDates.min = dateRange.min_date || '';
            state.defaultDates.max = dateRange.max_date || '';
            state.registryCards = cards.projects || [];

            bindFilterEvents();
            bindLandingEvents();
            renderLanding();
            showLanding();

            // Deep link: /project-summary?project=<id - NAME> opens that project's
            // detail directly (used by the "View detailed breakdown" link on the
            // Projects registry). Match the registry card so the header shows a
            // clean title; fall back to the raw param if it isn't a known card.
            const wanted = new URLSearchParams(window.location.search).get('project');
            if (wanted) {
                const card = state.registryCards.find(c => c.display === wanted);
                if (card) {
                    openProject(card.display, `${card.id} − ${card.stem_name}`);
                } else {
                    openProject(wanted, wanted);
                }
            }
        } catch (err) {
            console.error('Init error:', err);
            document.getElementById('ps-cards').innerHTML =
                '<div class="ps-empty">Failed to load projects. Refresh to retry.</div>';
        }
    }

    function bindFilterEvents() {
        // Month pills are rendered dynamically; clicks are handled in renderMonthPills().

        // Reset button — back to All months and clears category/vendor;
        // the project itself stays pinned (leave via the back button).
        $('#reset-filters').addEventListener('click', () => {
            state.filters.month = '';
            renderMonthPills();
            Object.values(dropdowns).forEach(d => d.clear());
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

        // Export button
        $('#export-btn').addEventListener('click', () => {
            const params = buildQueryParams();
            window.location.href = '/api/project-summary/export?' + params.toString();
        });
    }

    // ── Refresh All ────────────────────────────────────────────────────
    async function refreshAll() {
        if (!state.currentProject) return; // landing view — nothing to refresh
        const seq = ++refreshSeq;
        state.pagination.vendorBreakdown.page = 1;
        state.pagination.axisTransactions.page = 1;
        state.pagination.kvbTransactions.page = 1;
        state.pagination.bills.page = 1;
        state.pagination.salesBills.page = 1;

        const params = buildQueryParams();

        try {
            const [combined, filterOpts] = await Promise.all([
                fetchJSON('/api/project-summary/combined?' + params.toString()),
                fetchJSON('/api/project-summary/filter-options?' + params.toString())
            ]);
            if (seq !== refreshSeq) return; // superseded by a newer filter change

            state.data.combined = combined;

            // Update dropdown options dynamically (scoped to this project)
            if (filterOpts) {
                dropdowns['dropdown-category']?.setOptions(filterOpts.categories || []);
                dropdowns['dropdown-vendor']?.setOptions(filterOpts.vendors || []);
            }

            // Render all sections. The glance is not among them: it describes
            // the whole project and is painted once per open, so a month pill
            // can't quietly reshape the contract.
            renderCrossFilterChips();
            renderCategoryBars(combined.category_breakdown);
            renderLabourMonthly();
            renderVendorTable();

            // Fetch active bank tab transactions and bills
            fetchBankTransactions(state.activeBankTab, 1);
            fetchBills(1);
            fetchSalesBills(1);
        } catch (err) {
            console.error('Refresh error:', err);
        }
    }

    // ── Render: KPI Cards ──────────────────────────────────────────────
    // The same panels as the registry pop-up, from the same module and the same
    // endpoint -- /api/projects/<id>/insights, the one place the money model
    // (helpers/project_finance) is computed. This page used to sum its own
    // figures, which is how it came to show a different picture than its own
    // Export button produced.
    //
    // Whole-project by design: /insights takes no date range, and the filter bar
    // drives only the tables below. The four KPI tiles this replaced mixed
    // period-scoped bill totals with a whole-contract PO value, so any month
    // filter left them mutually incomparable.
    async function renderGlance(projectId) {
        const el = document.getElementById('ps-glance');
        if (!el) return;
        if (!projectId) { el.innerHTML = ''; return; }
        el.innerHTML = '<div class="ps-glance-loading">Loading project figures\u2026</div>';
        try {
            // The project row carries the PO baseline/variation splits the
            // panels derive from; insights carries the money model.
            const insights = await fetchJSON(`/api/projects/${projectId}/insights`);
            if (state.currentProjectId !== projectId) return; // navigated away
            const html = ProjectGlance.render({
                project: insights.project || {},
                insights: insights,
                // Overhead is edited in the registry, where the handlers live.
                editableOverhead: false,
            });
            el.innerHTML = html === null
                ? '<div class="ps-empty">Nothing to show for this project yet.</div>'
                : html;
        } catch (err) {
            console.error('Glance error:', err);
            el.innerHTML = '<div class="ps-empty">Couldn\'t load the project figures.</div>';
        }
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

    // ── Month pills (period filter) ─────────────────────────────────────
    const MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    // List of 'YYYY-MM' between two 'YYYY-MM-DD' dates, newest first.
    function monthsInRange(minDate, maxDate) {
        if (!minDate || !maxDate) return [];
        const [y0, m0] = minDate.split('-').map(Number);
        const [y1, m1] = maxDate.split('-').map(Number);
        const out = [];
        let y = y0, m = m0;
        while (y < y1 || (y === y1 && m <= m1)) {
            out.push(`${y}-${String(m).padStart(2, '0')}`);
            m++; if (m > 12) { m = 1; y++; }
        }
        return out.reverse();
    }

    // '2026-06' -> 'Jun-2026'
    function monthPillLabel(monthKey) {
        const [y, m] = monthKey.split('-').map(Number);
        return `${MONTH_ABBR[m - 1]}-${y}`;
    }

    function renderMonthPills() {
        const container = document.getElementById('month-pills');
        if (!container) return;
        const pills = [{ key: '', label: 'All' }].concat(
            monthsInRange(state.defaultDates.min, state.defaultDates.max)
                .map(mk => ({ key: mk, label: monthPillLabel(mk) }))
        );
        container.innerHTML = pills.map(p =>
            `<button class="ps-month-pill${state.filters.month === p.key ? ' active' : ''}" data-month="${p.key}">${p.label}</button>`
        ).join('');
        container.querySelectorAll('.ps-month-pill').forEach(btn => {
            btn.addEventListener('click', () => {
                const m = btn.dataset.month || '';
                if (m === state.filters.month) return;
                state.filters.month = m;
                container.querySelectorAll('.ps-month-pill').forEach(b =>
                    b.classList.toggle('active', b.dataset.month === m));
                refreshAll();
            });
        });
    }

    // ── Render: Labour Salary (Monthly) — per-month totals from the salary API ──
    // ── Mobile: collapse a wide table into stacked "ledger cards" ───────
    // Reads the <thead> labels and stamps each <td> with data-label so the
    // CSS (max-width:768px) can render LABEL : value rows. The title column
    // becomes the card heading. Idempotent — safe to call after every render.
    function applyMobileTableCards(tableId, opts) {
        const titleCol = (opts && opts.titleCol) || 0;
        const table = document.getElementById(tableId);
        if (!table) return;
        const heads = Array.from(table.querySelectorAll('thead th'))
            .map(th => th.textContent.trim());
        table.querySelectorAll('tbody tr').forEach(tr => {
            const tds = tr.querySelectorAll('td');
            // Skip placeholder rows (empty-state / loading) that span all columns.
            if (tds.length <= 1) return;
            tds.forEach((td, i) => {
                if (heads[i]) td.setAttribute('data-label', heads[i]);
                td.classList.toggle('ps-cell-title', i === titleCol);
            });
        });
    }

    function renderLabourMonthly() {
        const lab = state.data.combined?.labour_monthly;
        const tbody = document.getElementById('labour-monthly-body');
        if (!tbody) return;

        if (!lab || lab.available === false) {
            tbody.innerHTML = '<tr><td colspan="5" class="ps-empty">Couldn’t reach the salary service — labour figures are unavailable.</td></tr>';
            return;
        }
        const months = lab.monthly || [];
        if (months.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="ps-empty">No labour recorded for this project in the selected period.</td></tr>';
            return;
        }

        const rows = months.map(m => `
            <tr>
                <td>${escapeHtml(m.label)}</td>
                <td class="text-right">${Number(m.workers).toLocaleString('en-IN')}</td>
                <td class="text-right">${Number(m.days).toLocaleString('en-IN')}</td>
                <td class="text-right">${Number(m.ot_hours).toLocaleString('en-IN', { maximumFractionDigits: 1 })}</td>
                <td class="text-right" style="color:var(--accent-color);font-weight:600;">${formatIndianNumber(m.cost)}</td>
            </tr>
        `).join('');

        tbody.innerHTML = rows;
        applyMobileTableCards('labour-monthly-table');
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
        applyMobileTableCards('vendor-table');

        renderPaginationControls('vendor-pagination', page, totalPages, (pg) => {
            state.pagination.vendorBreakdown.page = pg;
            renderVendorFromCombined();
        });
    }

    async function fetchVendorPage(page) {
        const seq = refreshSeq;
        const params = buildQueryParams();
        params.set('page', page);
        params.set('per_page', state.pagination.vendorBreakdown.perPage);

        try {
            const result = await fetchJSON('/api/project-summary/vendors?' + params.toString());
            if (seq !== refreshSeq) return; // filters changed while in flight
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
        const seq = refreshSeq;
        const params = buildQueryParams();
        params.set('bank_code', bankCode);
        params.set('page', page);
        params.set('per_page', 15);

        try {
            const result = await fetchJSON('/api/project-summary/bank-transactions?' + params.toString());
            if (seq !== refreshSeq) return; // filters changed while in flight
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
                applyMobileTableCards('bank-txn-table', { titleCol: 1 });
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

    // ── Render: Bills Table (server-side pagination) ────────────────────
    async function fetchBills(page) {
        const seq = refreshSeq;
        const params = buildQueryParams();
        params.set('page', page);
        params.set('per_page', state.pagination.bills.perPage);

        try {
            const result = await fetchJSON('/api/project-summary/bills?' + params.toString());
            if (seq !== refreshSeq) return; // filters changed while in flight
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
        applyMobileTableCards('bills-table');

        renderPaginationControls('bills-pagination', data.page, data.total_pages, (pg) => {
            fetchBills(pg);
        });

        // Update summary text
        const summaryEl = document.getElementById('bills-summary');
        if (summaryEl && data.summary) {
            summaryEl.textContent = `${data.total} bills | Total: ${formatIndianNumber(data.summary.total_amount)} | GST: ${formatIndianNumber(data.summary.total_gst)}`;
        }

    }

    // ── Render: Sales Bills Table (server-side pagination) ──────────────
    async function fetchSalesBills(page) {
        const seq = refreshSeq;
        const params = buildQueryParams();
        params.set('page', page);
        params.set('per_page', state.pagination.salesBills.perPage);

        try {
            const result = await fetchJSON('/api/project-summary/sales-bills?' + params.toString());
            if (seq !== refreshSeq) return; // filters changed while in flight
            state.data.salesBills = result;
            state.pagination.salesBills.page = result.page;
            renderSalesBillsTable();
        } catch (err) {
            console.error('Sales bills fetch error:', err);
        }
    }

    function renderSalesBillsTable() {
        const data = state.data.salesBills;
        const tbody = document.getElementById('sales-bills-table-body');
        if (!tbody) return;

        if (!data.bills || data.bills.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="ps-empty">No sales bills found</td></tr>';
            renderPaginationControls('sales-bills-pagination', 1, 0, () => {});
            const summaryEl = document.getElementById('sales-bills-summary');
            if (summaryEl) summaryEl.textContent = '';
            return;
        }

        tbody.innerHTML = data.bills.map(b => `<tr>
            <td><a href="#" class="ps-sales-bill-link" data-bill-id="${b.id}">${escapeHtml(b.invoice_number || '-')}</a></td>
            <td>${escapeHtml(b.invoice_date || '-')}</td>
            <td class="cell-wrap">${escapeHtml(b.buyer_name || '-')}</td>
            <td>${escapeHtml(b.buyer_gstin || '-')}</td>
            <td class="text-right">${b.line_item_count || 0}</td>
            <td class="text-right text-income">${formatIndianNumber(b.total_amount || 0)}</td>
            <td>${escapeHtml(b.project || '-')}</td>
        </tr>`).join('');

        // Bind sales bill detail links
        tbody.querySelectorAll('.ps-sales-bill-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                viewSalesBillDetail(link.dataset.billId);
            });
        });
        applyMobileTableCards('sales-bills-table');

        renderPaginationControls('sales-bills-pagination', data.page, data.total_pages, (pg) => {
            fetchSalesBills(pg);
        });

        // Update summary text
        const summaryEl = document.getElementById('sales-bills-summary');
        if (summaryEl && data.summary) {
            summaryEl.textContent = `${data.total} bills | Total: ${formatIndianNumber(data.summary.total_amount)} | GST: ${formatIndianNumber(data.summary.total_gst)}`;
        }

    }

    async function viewSalesBillDetail(id) {
        try {
            const response = await fetchJSON(`/api/sales/stored/${id}`);
            renderBillDetailModal(response.bill);
        } catch (err) {
            console.error('Sales bill detail error:', err);
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
    // Handle normal page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Re-initialize when page is restored from back-forward cache
    window.addEventListener('pageshow', (event) => {
        if (event.persisted) {
            init();
        }
    });

})();
