// Bank code from page context (set in template)
const BANK_CODE = window.BANK_CODE || 'axis';
const BANK_NAME = window.BANK_NAME || 'Axis Bank';

// Global state
let currentCategory = 'All';
let currentProject = 'All';
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

function buildApiUrl(endpoint, category, startDate, endDate, project = 'All', extraParams = {}) {
    // Build bank-specific API URL
    const baseUrl = `/api/${BANK_CODE}${endpoint}`;

    const params = new URLSearchParams();
    params.append('category', category || 'All');
    if (project && project !== 'All') params.append('project', project);
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
        }
    } catch (e) {
        console.error('Error loading date range:', e);
    }
}

async function loadCategories() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/categories`);
        const data = await res.json();
        const select = document.getElementById('category-filter');
        if (!select) return;

        select.innerHTML = '';
        data.categories.forEach((cat) => {
            const option = document.createElement('option');
            option.value = cat;
            option.textContent = cat;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('Error loading categories:', e);
    }
}

async function loadProjects() {
    try {
        // Fetch all transactions to extract unique projects
        const res = await fetch(`/api/${BANK_CODE}/transactions?limit=10000`);
        const data = await res.json();
        const select = document.getElementById('project-filter');
        if (!select) return;

        // Extract unique projects
        const uniqueProjects = new Set();
        data.transactions.forEach((txn) => {
            const project = txn.project || txn.Project;
            if (project && project.trim()) {
                uniqueProjects.add(project.trim());
            }
        });

        // Sort projects alphabetically
        const sortedProjects = Array.from(uniqueProjects).sort();

        // Populate dropdown
        select.innerHTML = '<option value="All">All Projects</option>';
        sortedProjects.forEach((proj) => {
            const option = document.createElement('option');
            option.value = proj;
            option.textContent = proj;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('Error loading projects:', e);
    }
}

/** Summary (for transaction count) **/

async function loadSummary(category = 'All', startDate = null, endDate = null, project = 'All') {
    try {
        const url = buildApiUrl('/summary', category, startDate, endDate, project);
        const res = await fetch(url);
        const data = await res.json();

        // Header count
        document.getElementById('total-transactions').textContent = `${data.total_transactions} Transactions`;
    } catch (e) {
        console.error('Error loading summary:', e);
    }
}

/** Transactions **/

async function loadTransactions(category = 'All', startDate = null, endDate = null, project = 'All') {
    try {
        const url = buildApiUrl('/transactions', category, startDate, endDate, project, {
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

        row.innerHTML = `
            <td data-label="Date">${txn.date}</td>
            <td data-label="Vendor">${txn.vendor}</td>
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
        loadSummary(currentCategory, currentStartDate, currentEndDate, currentProject),
        loadTransactions(currentCategory, currentStartDate, currentEndDate, currentProject)
    ]);
    hideLoading();
}

// Alias for edit.js compatibility
window.loadDashboardData = runFullRefresh;

/** Init **/

document.addEventListener('DOMContentLoaded', async () => {
    showLoading();

    await Promise.all([loadCategories(), loadDateRange(), loadProjects()]);

    // default filter state
    currentCategory = 'All';
    currentProject = 'All';
    currentStartDate = null;
    currentEndDate = null;

    // Helper function to get date N days ago
    function getDateNDaysAgo(n) {
        const date = new Date();
        date.setDate(date.getDate() - n);
        return date.toISOString().split('T')[0];
    }

    // Helper function to get first day of current month
    function getFirstDayOfMonth() {
        const date = new Date();
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-01`;
    }

    // Helper function to get today's date
    function getToday() {
        return new Date().toISOString().split('T')[0];
    }

    // Scenario chips for date ranges
    document.querySelectorAll('.chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            document
                .querySelectorAll('.chip')
                .forEach((c) => c.classList.remove('chip-active'));
            chip.classList.add('chip-active');
            const scenario = chip.dataset.scenario;

            const startInput = document.getElementById('start-date');
            const endInput = document.getElementById('end-date');

            if (scenario === 'all') {
                currentStartDate = null;
                currentEndDate = null;
                startInput.value = '';
                endInput.value = '';
            } else if (scenario === 'last7') {
                currentStartDate = getDateNDaysAgo(7);
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            } else if (scenario === 'last14') {
                currentStartDate = getDateNDaysAgo(14);
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            } else if (scenario === 'last30') {
                currentStartDate = getDateNDaysAgo(30);
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            } else if (scenario === 'thisMonth') {
                currentStartDate = getFirstDayOfMonth();
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            }
            runFullRefresh();
        });
    });


    // Apply / Clear
    document.getElementById('apply-filters').addEventListener('click', () => {
        const catSelect = document.getElementById('category-filter');
        const projSelect = document.getElementById('project-filter');
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');

        currentCategory = catSelect.value || 'All';
        currentProject = projSelect.value || 'All';
        currentStartDate = startInput.value || null;
        currentEndDate = endInput.value || null;

        // Clear chip selection when manually applying filters
        document
            .querySelectorAll('.chip')
            .forEach((c) => c.classList.remove('chip-active'));

        runFullRefresh();
    });

    document.getElementById('clear-filters').addEventListener('click', () => {
        const catSelect = document.getElementById('category-filter');
        const projSelect = document.getElementById('project-filter');
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');

        currentCategory = 'All';
        currentProject = 'All';
        currentStartDate = null;
        currentEndDate = null;

        catSelect.value = 'All';
        projSelect.value = 'All';
        startInput.value = '';
        endInput.value = '';

        document
            .querySelectorAll('.chip')
            .forEach((c) => c.classList.remove('chip-active'));
        document
            .querySelector('.chip[data-scenario="all"]')
            ?.classList.add('chip-active');

        runFullRefresh();
    });

    // Download Transactions
    document.getElementById('download-transactions')?.addEventListener('click', () => {
        const params = new URLSearchParams();
        params.append('category', currentCategory || 'All');
        if (currentProject && currentProject !== 'All') params.append('project', currentProject);
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
                loadTransactions(currentCategory, currentStartDate, currentEndDate, currentProject);
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

            loadTransactions(currentCategory, currentStartDate, currentEndDate, currentProject);
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

    // Re-render on window resize (for mobile/desktop switching)
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
