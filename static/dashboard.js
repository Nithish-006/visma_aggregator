// Bank code from page context (set in template)
const BANK_CODE = window.BANK_CODE || 'axis';
const BANK_NAME = window.BANK_NAME || 'Axis Bank';

// Global state
let currentCategories = []; // Multi-select: empty array means "All"
let currentProjects = [];   // Multi-select: empty array means "All"
let currentVendors = [];    // Multi-select: empty array means "All"
let currentStartDate = null;
let currentEndDate = null;
let currentSortBy = 'date';
let currentSortOrder = 'desc';
let currentSearch = '';
let searchTimeout = null;
let dataMinDate = null;
let dataMaxDate = null;

// Pagination state
let allTransactions = [];
let currentPage = 1;
const ITEMS_PER_PAGE = 10;

// Global Dropdown Instances
const dropdowns = {};

// Custom Dropdown Class (Replaces Select2)
class CustomDropdown {
    constructor(containerId, placeholder, type) {
        this.container = document.getElementById(containerId);
        this.placeholder = placeholder;
        this.type = type; // 'category', 'project', 'vendor'
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
            <div class="dropdown-trigger" id="${this.container.id}-trigger">
                <span class="trigger-text">${this.placeholder}</span>
            </div>
            <div class="dropdown-menu">
                <div class="dropdown-search">
                    <input type="text" placeholder="Search..." id="${this.container.id}-search">
                </div>
                <div class="dropdown-options" id="${this.container.id}-options">
                    <!-- Options will be populated here -->
                </div>
            </div>
        `;

        this.triggerBtn = this.container.querySelector('.dropdown-trigger');
        this.triggerText = this.container.querySelector('.trigger-text');
        this.menu = this.container.querySelector('.dropdown-menu');
        this.searchInput = this.container.querySelector('input');
        this.optionsContainer = this.container.querySelector('.dropdown-options');
    }

    setOptions(items) {
        this.options = items; // items = ['Option 1', 'Option 2']
        this.renderOptions(items);
    }

    renderOptions(items) {
        this.optionsContainer.innerHTML = '';

        if (items.length === 0) {
            this.optionsContainer.innerHTML = '<div style="padding: 10px; color: var(--text-muted); font-size: 0.8rem;">No results found</div>';
            return;
        }

        items.forEach(item => {
            const optionEl = document.createElement('div');
            optionEl.className = `dropdown-option ${this.selectedValues.has(item) ? 'selected' : ''}`;
            optionEl.dataset.value = item;
            optionEl.innerHTML = `
                <div class="option-checkbox"></div>
                <span>${item}</span>
            `;

            optionEl.addEventListener('click', (e) => {
                e.stopPropagation(); // prevent menu close
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
        this.syncGlobals();

        // Auto-refresh with debounce
        if (window.refreshTimeout) clearTimeout(window.refreshTimeout);
        window.refreshTimeout = setTimeout(() => {
            runFullRefresh();
        }, 500); // Wait 500ms after last click
    }

    updateUI() {
        const optionsDocs = this.optionsContainer.querySelectorAll('.dropdown-option');
        optionsDocs.forEach(opt => {
            if (this.selectedValues.has(opt.dataset.value)) {
                opt.classList.add('selected');
                opt.setAttribute('aria-selected', 'true');
            } else {
                opt.classList.remove('selected');
                opt.setAttribute('aria-selected', 'false');
            }
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
            const label = this.type === 'category' ? 'Categories' : this.type === 'project' ? 'Projects' : 'Vendors';
            this.triggerText.textContent = `${this.selectedValues.size} ${label} selected`;
            this.triggerBtn.classList.add('has-selection');
        }
    }

    syncGlobals() {
        if (this.type === 'category') currentCategories = Array.from(this.selectedValues);
        if (this.type === 'project') currentProjects = Array.from(this.selectedValues);
        if (this.type === 'vendor') currentVendors = Array.from(this.selectedValues);
    }

    toggleMenu() {
        this.isOpen = !this.isOpen;
        if (this.isOpen) {
            // Close other dropdowns
            Object.values(dropdowns).forEach(d => {
                if (d !== this) d.closeMenu();
            });
            this.container.classList.add('active');
            this.searchInput.focus();
        } else {
            this.closeMenu();
        }
    }

    closeMenu() {
        this.isOpen = false;
        this.container.classList.remove('active');
    }

    filterOptions(query) {
        const lowerQuery = query.toLowerCase();
        const filtered = this.options.filter(item => item.toLowerCase().includes(lowerQuery));
        this.renderOptions(filtered);
    }

    clearSelection() {
        this.selectedValues.clear();
        this.updateUI();
        this.updateTriggerText();
        this.syncGlobals();
        this.searchInput.value = '';
        this.renderOptions(this.options);
    }

    attachEvents() {
        this.triggerBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleMenu();
        });

        this.searchInput.addEventListener('click', (e) => e.stopPropagation());
        this.searchInput.addEventListener('input', (e) => {
            this.filterOptions(e.target.value);
        });

        // Prevent closing when clicking inside menu (except options which handle propagation themselves if needed, but we handled it in option click)
        this.menu.addEventListener('click', (e) => {
            // e.stopPropagation();
            // Logic inside menu shouldn't close it unless explicit
        });
    }
}


/** Utilities **/

function formatIndianNumber(amount) {
    if (!amount || amount === 0) return '₹0';

    const absAmount = Math.abs(amount);
    const sign = amount < 0 ? '-' : '';

    if (absAmount >= 10000000) {
        return `${sign}₹${(absAmount / 10000000).toFixed(2)} Cr`;
    } else if (absAmount >= 100000) {
        return `${sign}₹${(absAmount / 100000).toFixed(2)} L`;
    } else if (absAmount >= 1000) {
        return `${sign}₹${(absAmount / 1000).toFixed(2)} K`;
    } else {
        return `${sign}₹${absAmount.toFixed(0)}`;
    }
}

function showLoading() {
    document.getElementById('loading-overlay')?.classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loading-overlay')?.classList.add('hidden');
}

function formatDateRangeForAPI(startDate, endDate) {
    // Returns object with start_date and end_date params
    const params = {};
    if (startDate) {
        params.start_date = startDate;
    }
    if (endDate) {
        params.end_date = endDate;
    }
    return params;
}

function buildApiUrl(endpoint, categories, startDate, endDate, projects = [], vendors = [], extraParams = {}) {
    // Build bank-specific API URL
    const baseUrl = `/api/${BANK_CODE}${endpoint}`;

    const params = new URLSearchParams();

    // Handle multi-select: empty array means "All"
    if (categories && categories.length > 0) {
        params.append('category', categories.join(','));
    } else {
        params.append('category', 'All');
    }

    if (projects && projects.length > 0) {
        params.append('project', projects.join(','));
    }

    if (vendors && vendors.length > 0) {
        params.append('vendor', vendors.join(','));
    }

    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    // Add any extra params
    for (const [key, value] of Object.entries(extraParams)) {
        params.append(key, value);
    }

    return `${baseUrl}?${params.toString()}`;
}

/** Filters loading **/

async function loadDateRange() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/date_range`);
        const data = await res.json();

        if (data.min_date && data.max_date) {
            dataMinDate = data.min_date;
            dataMaxDate = data.max_date;

            const startInput = document.getElementById('start-date');
            const endInput = document.getElementById('end-date');

            if (startInput && endInput) {
                // Set the min/max constraints on the date inputs
                startInput.min = data.min_date;
                startInput.max = data.max_date;
                endInput.min = data.min_date;
                endInput.max = data.max_date;

                // Default: show all data (leave inputs empty)
                startInput.value = '';
                endInput.value = '';
            }

            // Update the "Updated as of" badge with formatted date
            const updatedDateEl = document.getElementById('data-updated-date');
            if (updatedDateEl && data.max_date) {
                updatedDateEl.textContent = formatDisplayDate(data.max_date);
            }
        }
    } catch (e) {
        console.error('Error loading date range:', e);
    }
}

/** Format date for display (e.g., "05 Jan 2026") **/
function formatDisplayDate(dateStr) {
    if (!dateStr) return '--';
    const date = new Date(dateStr);
    const options = { day: '2-digit', month: 'short', year: 'numeric' };
    return date.toLocaleDateString('en-IN', options);
}

async function loadCategories() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/categories`);
        const data = await res.json();

        const items = data.categories.filter(c => c !== 'All'); // Remove 'All'

        // Init Custom Dropdown
        const dd = new CustomDropdown('category-filter', 'All Categories', 'category');
        dd.setOptions(items);

    } catch (e) {
        console.error('Error loading categories:', e);
    }
}

async function loadProjectsAndVendors() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/transactions?limit=10000`);
        const data = await res.json();

        // Extract unique projects and vendors in a single pass
        const uniqueProjects = new Set();
        const uniqueVendors = new Set();

        data.transactions.forEach((txn) => {
            const project = txn.project || txn.Project;
            if (project && project.trim()) {
                uniqueProjects.add(project.trim());
            }

            const vendor = txn.vendor || txn['Client/Vendor'];
            if (vendor && vendor.trim() && vendor.trim() !== 'Unknown') {
                uniqueVendors.add(vendor.trim());
            }
        });

        const sortedProjects = Array.from(uniqueProjects).sort();
        const sortedVendors = Array.from(uniqueVendors).sort();

        // Init Custom Dropdowns
        const projDD = new CustomDropdown('project-filter', 'All Projects', 'project');
        projDD.setOptions(sortedProjects);

        const vendDD = new CustomDropdown('vendor-filter', 'All Vendors', 'vendor');
        vendDD.setOptions(sortedVendors);
    } catch (e) {
        console.error('Error loading projects and vendors:', e);
    }
}

// Aliases for backwards compatibility
async function loadProjects() {
    await loadProjectsAndVendors();
}

async function loadVendors() {
    // Already loaded by loadProjectsAndVendors, no-op
}

/** Summary (for transaction count) **/

async function loadSummary(categories = [], startDate = null, endDate = null, projects = [], vendors = []) {
    try {
        const url = buildApiUrl('/summary', categories, startDate, endDate, projects, vendors);
        const res = await fetch(url);
        const data = await res.json();

        // Header count
        document.getElementById('total-transactions').textContent = `${data.total_transactions} Transactions`;
    } catch (e) {
        console.error('Error loading summary:', e);
    }
}

/** Transactions **/

async function loadTransactions(categories = [], startDate = null, endDate = null, projects = [], vendors = []) {
    try {
        const url = buildApiUrl('/transactions', categories, startDate, endDate, projects, vendors, {
            limit: '10000',
            sort_by: currentSortBy,
            sort_order: currentSortOrder,
            search: currentSearch
        });
        const res = await fetch(url);
        const data = await res.json();

        // Store all transactions and reset to page 1
        allTransactions = data.transactions;
        currentPage = 1;

        renderTransactionsPage();
        updatePaginationControls();
    } catch (e) {
        console.error('Error loading transactions:', e);
    }
}

/** Check if mobile view is active **/
function isMobileView() {
    return window.innerWidth <= 768;
}

/** Render all transactions as scrollable list **/
function renderTransactionsPage() {
    const tbody = document.getElementById('transactions-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    // Render all transactions as scrollable list (both desktop and mobile)
    allTransactions.forEach((txn) => {
        const row = document.createElement('tr');

        // Build mobile metadata (project and category)
        const project = txn.project || '';
        const category = txn.category || '';
        let metaParts = [];
        if (project) metaParts.push(project);
        if (category && category !== 'All') metaParts.push(category);
        const metaText = metaParts.join(' • ');

        row.innerHTML = `
            <td data-label="Date">${txn.date}</td>
            <td data-label="Vendor">
                <span class="vendor-name">${txn.vendor}</span>
                ${metaText ? `<span class="vendor-meta">${metaText}</span>` : ''}
            </td>
            <td data-label="Category">${txn.category}</td>
            <td data-label="Description">${txn.description || ''}</td>
            <td data-label="Project">${txn.project || ''}</td>
            <td class="text-right" data-label="Debit">${txn.dr_amount > 0 ? `<span class="monetary-pill debit">${txn.dr_amount_formatted}</span>` : ''}</td>
            <td class="text-right" data-label="Credit">${txn.cr_amount > 0 ? `<span class="monetary-pill credit">${txn.cr_amount_formatted}</span>` : ''}</td>
        `;
        tbody.appendChild(row);
    });
}

/** Update pagination controls **/
function updatePaginationControls() {
    const totalPages = Math.ceil(allTransactions.length / ITEMS_PER_PAGE) || 1;

    document.getElementById('current-page').textContent = currentPage;
    document.getElementById('total-pages').textContent = totalPages;

    document.getElementById('prev-page').disabled = currentPage <= 1;
    document.getElementById('next-page').disabled = currentPage >= totalPages;
}

/** Go to specific page **/
function goToPage(page) {
    const totalPages = Math.ceil(allTransactions.length / ITEMS_PER_PAGE) || 1;

    if (page < 1) page = 1;
    if (page > totalPages) page = totalPages;

    currentPage = page;
    renderTransactionsPage();
    updatePaginationControls();

    // Scroll to top of table on mobile
    document.querySelector('.transactions-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** Refresh **/

async function runFullRefresh() {
    showLoading();
    await Promise.all([
        loadSummary(currentCategories, currentStartDate, currentEndDate, currentProjects, currentVendors),
        loadTransactions(currentCategories, currentStartDate, currentEndDate, currentProjects, currentVendors)
    ]);
    hideLoading();
}

// Alias for edit.js compatibility
window.loadDashboardData = runFullRefresh;

/** Init **/

document.addEventListener('DOMContentLoaded', async () => {
    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        Object.values(dropdowns).forEach(d => d.closeMenu());
    });

    showLoading();

    await Promise.all([loadCategories(), loadDateRange(), loadProjects(), loadVendors()]);

    // Date Inputs Auto-Refresh
    const startInput = document.getElementById('start-date');
    const endInput = document.getElementById('end-date');

    [startInput, endInput].forEach(input => {
        if (input) {
            input.addEventListener('change', () => {
                currentStartDate = startInput.value || null;
                currentEndDate = endInput.value || null;
                runFullRefresh();
            });
        }
    });

    document.getElementById('clear-filters').addEventListener('click', () => {
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');

        currentCategories = [];
        currentProjects = [];
        currentVendors = [];
        currentStartDate = null;
        currentEndDate = null;

        // Clear Custom Dropdowns
        Object.values(dropdowns).forEach(d => d.clearSelection());

        startInput.value = '';
        endInput.value = '';

        runFullRefresh();
    });

    // Download Transactions
    document.getElementById('download-transactions')?.addEventListener('click', () => {
        const params = new URLSearchParams();
        if (currentCategories.length > 0) {
            params.append('category', currentCategories.join(','));
        } else {
            params.append('category', 'All');
        }
        if (currentProjects.length > 0) params.append('project', currentProjects.join(','));
        if (currentVendors.length > 0) params.append('vendor', currentVendors.join(','));
        if (currentStartDate) params.append('start_date', currentStartDate);
        if (currentEndDate) params.append('end_date', currentEndDate);

        window.location.href = `/api/${BANK_CODE}/download_transactions?${params.toString()}`;
    });

    // Search listener
    const searchInput = document.getElementById('transaction-search');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            currentSearch = e.target.value;
            if (searchTimeout) clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                loadTransactions(currentCategories, currentStartDate, currentEndDate, currentProjects, currentVendors);
            }, 300);
        });
    }

    // Sort listeners
    document.querySelectorAll('.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const field = th.dataset.sort;
            if (currentSortBy === field) {
                // Toggle order
                currentSortOrder = currentSortOrder === 'desc' ? 'asc' : 'desc';
            } else {
                currentSortBy = field;
                currentSortOrder = 'desc'; // Default to desc for new field
            }

            // Update UI
            document.querySelectorAll('.sortable').forEach(h => {
                h.classList.remove('header-sort-active');
                h.querySelector('.sort-icon').textContent = '';
            });
            th.classList.add('header-sort-active');
            th.querySelector('.sort-icon').textContent = currentSortOrder === 'desc' ? '↓' : '↑';

            loadTransactions(currentCategories, currentStartDate, currentEndDate, currentProjects, currentVendors);
        });
    });

    // Pagination listeners
    document.getElementById('prev-page')?.addEventListener('click', () => {
        goToPage(currentPage - 1);
    });

    document.getElementById('next-page')?.addEventListener('click', () => {
        goToPage(currentPage + 1);
    });

    // Mobile filter toggle
    const filterToggle = document.getElementById('filter-toggle');
    const filterContent = document.getElementById('filter-content');

    if (filterToggle && filterContent) {
        filterToggle.addEventListener('click', () => {
            filterToggle.classList.toggle('active');
            filterContent.classList.toggle('expanded');
        });
    }

    // Sticky Header Logic
    const filterBar = document.querySelector('.filter-bar');
    if (filterBar) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 10) {
                filterBar.classList.add('sticky');
            } else {
                filterBar.classList.remove('sticky');
            }
        });
    }

    // Re-render on window resize
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            renderTransactionsPage();
            updatePaginationControls();
        }, 250);
    });

    await runFullRefresh();
});
