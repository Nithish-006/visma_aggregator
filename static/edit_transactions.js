/**
 * Edit Transactions Page - Comprehensive Edit & Bulk Operations
 */

(function () {
    'use strict';

    // Bank code from page context
    const BANK_CODE = window.BANK_CODE || 'axis';
    const BANK_NAME = window.BANK_NAME || 'Axis Bank';

    // Global state
    let allTransactions = [];           // Currently displayed transactions (current page only)
    let allTransactionsMap = new Map(); // Map of id -> transaction for tracking modifications
    let selectedTransactionIds = new Set();  // Track by ID instead of index
    let modifiedTransactions = new Map();    // Map of id -> modified transaction data
    let categories = [];
    let projects = [];

    // Pagination state (server-side)
    let currentPage = 1;
    const ITEMS_PER_PAGE = 100;  // 100 transactions per page
    let totalTransactions = 0;
    let totalPages = 0;

    // Sort state
    let currentSortOrder = 'desc'; // 'desc' = newest first, 'asc' = oldest first

    // Filter state
    let currentFilters = {
        category: [], // Empty means All
        project: [],
        vendor: [],
        search: '',
        startDate: null,
        endDate: null
    };

    // Loading state to prevent duplicate requests
    let isLoading = false;

    // Excel-like navigation state
    let focusedCell = null; // Currently focused (highlighted) editable cell
    const EDITABLE_FIELDS = ['vendor', 'category', 'project']; // Column order for left/right nav

    /**
     * Check if a category value is "Uncategorized" (case-insensitive)
     */
    function isUncategorized(category) {
        if (!category) return false;
        return category.toLowerCase() === 'uncategorized';
    }

    // Dropdown instances
    const dropdowns = {};

    // Custom Dropdown Class
    class CustomDropdown {
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
                <div class="dropdown-trigger" id="${this.container.id}-trigger">
                    <span class="trigger-text">${this.placeholder}</span>
                </div>
                <div class="dropdown-menu">
                    <div class="dropdown-search">
                        <input type="text" placeholder="Search..." id="${this.container.id}-search">
                    </div>
                    <div class="dropdown-options" id="${this.container.id}-options"></div>
                </div>
            `;

            this.triggerBtn = this.container.querySelector('.dropdown-trigger');
            this.triggerText = this.container.querySelector('.trigger-text');
            this.menu = this.container.querySelector('.dropdown-menu');
            this.searchInput = this.container.querySelector('input');
            this.optionsContainer = this.container.querySelector('.dropdown-options');
        }

        setOptions(items) {
            this.options = items;
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

            // Debounce apply filters
            if (window.filterTimeout) clearTimeout(window.filterTimeout);
            window.filterTimeout = setTimeout(() => {
                applyFilters();
                renderTable(); // Using existing render logic
                updateCounts();
            }, 300);
        }

        updateUI() {
            const optionsDocs = this.optionsContainer.querySelectorAll('.dropdown-option');
            optionsDocs.forEach(opt => {
                if (this.selectedValues.has(opt.dataset.value)) {
                    opt.classList.add('selected');
                } else {
                    opt.classList.remove('selected');
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
                this.triggerText.textContent = `${this.selectedValues.size} Selected`;
                this.triggerBtn.classList.add('has-selection');
            }
        }

        syncFilters() {
            // Update global filter state
            const vals = Array.from(this.selectedValues);
            if (this.type === 'category') currentFilters.category = vals;
            if (this.type === 'project') currentFilters.project = vals;
            if (this.type === 'vendor') currentFilters.vendor = vals;
        }

        toggleMenu() {
            this.isOpen = !this.isOpen;
            if (this.isOpen) {
                Object.values(dropdowns).forEach(d => { if (d !== this) d.closeMenu(); });
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

        clear() {
            this.selectedValues.clear();
            this.updateUI();
            this.updateTriggerText();
            this.syncFilters();
        }

        /**
         * Update available options while preserving current selections.
         * Options not in the new list are kept selected (they still match the filter).
         */
        updateOptions(newItems) {
            this.options = newItems;
            // Re-render with current search query if any
            const searchQuery = this.searchInput ? this.searchInput.value : '';
            if (searchQuery) {
                const lowerQuery = searchQuery.toLowerCase();
                this.renderOptions(newItems.filter(item => item.toLowerCase().includes(lowerQuery)));
            } else {
                this.renderOptions(newItems);
            }
        }

        attachEvents() {
            this.triggerBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleMenu();
            });
            this.searchInput.addEventListener('input', (e) => this.filterOptions(e.target.value));
            this.searchInput.addEventListener('click', (e) => e.stopPropagation());
        }
    }

    // Close dropdowns on click outside
    document.addEventListener('click', () => {
        Object.values(dropdowns).forEach(d => d.closeMenu());
    });

    // DOM Elements
    const loadingOverlay = document.getElementById('loading-overlay');
    const tableBody = document.getElementById('edit-table-body');
    const totalCountEl = document.getElementById('total-count');
    const selectedCountEl = document.getElementById('selected-count');
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const bulkEditBar = document.getElementById('bulk-edit-bar');
    const bulkCountEl = document.getElementById('bulk-count');
    const modifiedCountEl = document.getElementById('modified-count');
    const modifiedBadge = document.getElementById('modified-badge');
    const saveAllBtn = document.getElementById('save-all-btn');
    const discardAllBtn = document.getElementById('discard-all-btn');

    /**
     * Initialize the page
     */
    async function init() {
        showLoading();

        // Load categories, filter options, and date range in parallel for faster loading
        await Promise.all([
            loadCategories(),
            loadFilterOptions(),
            loadDateRange()
        ]);

        // Setup event listeners first
        setupEventListeners();

        // Load transactions (first page only - fast!)
        await loadTransactions();

        hideLoading();
    }

    /**
     * Load date range from API
     */
    async function loadDateRange() {
        try {
            const response = await fetch(`/api/${BANK_CODE}/date_range`);
            const data = await response.json();

            const startInput = document.getElementById('edit-start-date');
            const endInput = document.getElementById('edit-end-date');

            if (startInput && endInput && data.min_date && data.max_date) {
                // Set the min/max constraints on the date inputs
                startInput.min = data.min_date;
                startInput.max = data.max_date;
                endInput.min = data.min_date;
                endInput.max = data.max_date;

                // Default: show all data (leave inputs empty)
                startInput.value = '';
                endInput.value = '';
            }
        } catch (error) {
            console.error('Error loading date range:', error);
        }
    }

    /**
     * Load categories from API
     */
    async function loadCategories() {
        try {
            const response = await fetch(`/api/${BANK_CODE}/categories`);
            const data = await response.json();
            categories = data.categories;

            // Init Category Dropdown
            const dd = new CustomDropdown('edit-category-filter', 'All Categories', 'category');
            dd.setOptions(categories.filter(c => c !== 'All'));

            // Populate bulk category datalist (allows typing new categories)
            const bulkCategoryDatalist = document.getElementById('bulk-category-datalist');
            bulkCategoryDatalist.innerHTML = '';
            categories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat;
                bulkCategoryDatalist.appendChild(option);
            });

        } catch (error) {
            console.error('Error loading categories:', error);
        }
    }

    /**
     * Load transactions from paginated API
     */
    async function loadTransactions() {
        if (isLoading) return;
        isLoading = true;

        try {
            // Build query params
            const params = new URLSearchParams({
                page: currentPage,
                per_page: ITEMS_PER_PAGE,
                sort_by: 'date',
                sort_order: currentSortOrder
            });

            // Add filters
            if (currentFilters.category.length > 0) {
                params.set('category', currentFilters.category.join(','));
            }
            if (currentFilters.project.length > 0) {
                params.set('project', currentFilters.project.join(','));
            }
            if (currentFilters.vendor.length > 0) {
                params.set('vendor', currentFilters.vendor.join(','));
            }
            if (currentFilters.search) {
                params.set('search', currentFilters.search);
            }
            if (currentFilters.startDate) {
                params.set('start_date', currentFilters.startDate);
            }
            if (currentFilters.endDate) {
                params.set('end_date', currentFilters.endDate);
            }

            const response = await fetch(`/api/${BANK_CODE}/transactions/paginated?${params}`);
            const data = await response.json();

            allTransactions = data.transactions;
            totalTransactions = data.total;
            totalPages = data.total_pages;

            // Update the map for tracking
            allTransactionsMap.clear();
            allTransactions.forEach(txn => {
                // Restore any pending modifications
                if (modifiedTransactions.has(txn.id)) {
                    const modified = modifiedTransactions.get(txn.id);
                    Object.assign(txn, modified);
                }
                allTransactionsMap.set(txn.id, txn);
            });

            renderTable();
            updateCounts();
            updatePaginationControls();

            // Update dropdown options from the same response (cascading filters)
            try {
                if (data.filter_options) {
                    const cats = (data.filter_options.categories || []).filter(c => c !== 'All');
                    const projs = data.filter_options.projects || [];
                    const vends = data.filter_options.vendors || [];

                    if (dropdowns['edit-category-filter']) dropdowns['edit-category-filter'].setOptions(cats);
                    if (dropdowns['edit-project-filter']) dropdowns['edit-project-filter'].setOptions(projs);
                    if (dropdowns['edit-vendor-filter']) dropdowns['edit-vendor-filter'].setOptions(vends);
                }
            } catch (err) {
                console.error('Error updating dropdowns:', err);
            }
        } catch (error) {
            console.error('Error loading transactions:', error);
        } finally {
            isLoading = false;
        }
    }

    /**
     * Load filter options (projects, vendors) from API
     */
    async function loadFilterOptions() {
        try {
            const response = await fetch(`/api/${BANK_CODE}/filter-options`);
            const data = await response.json();

            // Store projects for autocomplete
            projects = data.projects || [];

            // Init Project Dropdown
            const projectDd = new CustomDropdown('edit-project-filter', 'All Projects', 'project');
            projectDd.setOptions(projects);

            // Populate bulk project datalist
            const bulkProjectDatalist = document.getElementById('bulk-project-datalist');
            if (bulkProjectDatalist) {
                bulkProjectDatalist.innerHTML = '';
                projects.forEach(proj => {
                    const option = document.createElement('option');
                    option.value = proj;
                    bulkProjectDatalist.appendChild(option);
                });
            }

            // Init Vendor Dropdown
            const vendorDd = new CustomDropdown('edit-vendor-filter', 'All Vendors', 'vendor');
            vendorDd.setOptions(data.vendors || []);
        } catch (error) {
            console.error('Error loading filter options:', error);
        }
    }

    /**
     * Apply current filters - triggers server-side filtering
     */
    function applyFilters() {
        // Reset to page 1 when filters change
        currentPage = 1;
        // Reload from server with new filters (response includes updated filter options for cascading dropdowns)
        loadTransactions();
    }

    /**
     * Refresh dropdown options based on currently active filters.
     * Each dropdown shows only the distinct values available given the other active filters.
     */
    async function refreshFilterOptions() {
        try {
            const params = new URLSearchParams();

            if (currentFilters.category.length > 0) {
                params.set('category', currentFilters.category.join(','));
            }
            if (currentFilters.project.length > 0) {
                params.set('project', currentFilters.project.join(','));
            }
            if (currentFilters.vendor.length > 0) {
                params.set('vendor', currentFilters.vendor.join(','));
            }
            if (currentFilters.search) {
                params.set('search', currentFilters.search);
            }
            if (currentFilters.startDate) {
                params.set('start_date', currentFilters.startDate);
            }
            if (currentFilters.endDate) {
                params.set('end_date', currentFilters.endDate);
            }

            // Only fetch filtered options if at least one filter is active
            const hasFilters = params.toString().length > 0;
            const url = hasFilters
                ? `/api/${BANK_CODE}/filter-options?${params}`
                : `/api/${BANK_CODE}/filter-options`;

            const response = await fetch(url);
            const data = await response.json();

            // Update each dropdown's available options (preserving current selections)
            const categoryDd = dropdowns['edit-category-filter'];
            if (categoryDd) {
                categoryDd.updateOptions((data.categories || []).filter(c => c !== 'All'));
            }

            const projectDd = dropdowns['edit-project-filter'];
            if (projectDd) {
                projectDd.updateOptions(data.projects || []);
            }

            const vendorDd = dropdowns['edit-vendor-filter'];
            if (vendorDd) {
                vendorDd.updateOptions(data.vendors || []);
            }
        } catch (error) {
            console.error('Error refreshing filter options:', error);
        }
    }

    /**
     * Check if mobile view is active
     */
    function isMobileView() {
        return window.innerWidth <= 768;
    }

    /**
     * Render the transactions table (scrollable list on both desktop and mobile)
     */
    function renderTable() {
        tableBody.innerHTML = '';

        // Render current page transactions (already paginated from server)
        allTransactions.forEach((txn, index) => {
            const row = document.createElement('tr');
            const txnId = txn.id;
            const isSelected = selectedTransactionIds.has(txnId);
            const isModified = modifiedTransactions.has(txnId);

            if (isSelected) {
                row.classList.add('selected');
            }
            if (isModified) {
                row.classList.add('modified');
            }

            const isCategoryUncategorized = isUncategorized(txn.category);

            const projectValue = txn.project || txn.Project || '';
            const isProjectEmpty = !projectValue;

            row.innerHTML = `
                <td data-label="">
                    <input type="checkbox" class="row-checkbox" data-id="${txnId}" ${isSelected ? 'checked' : ''}>
                </td>
                <td data-label="Date">${txn.date}</td>
                <td class="editable-cell" data-field="vendor" data-id="${txnId}" data-label="Vendor">${txn.vendor || ''}</td>
                <td class="editable-cell" data-field="category" data-id="${txnId}" data-label="Category">
                    <span class="category-badge ${isCategoryUncategorized ? 'uncategorized' : ''}">${txn.category || ''}</span>
                </td>
                <td class="description-full" data-label="Description">${escapeHtml(txn.description || txn['Transaction Description'] || '')}</td>
                <td class="text-right" data-label="Debit">${txn.dr_amount > 0 ? `<span class="monetary-pill debit">${txn.dr_amount_formatted}</span>` : ''}</td>
                <td class="text-right" data-label="Credit">${txn.cr_amount > 0 ? `<span class="monetary-pill credit">${txn.cr_amount_formatted}</span>` : ''}</td>
                <td class="editable-cell" data-field="project" data-id="${txnId}" data-label="Project">
                    <span class="project-badge ${isProjectEmpty ? 'empty' : ''}">${projectValue || '-'}</span>
                </td>
                <td style="text-align: center;" data-label="">
                    ${isModified ? '<span style="color: #f59e0b; font-size: 18px;" title="Unsaved changes">●</span>' : ''}
                </td>
            `;

            tableBody.appendChild(row);
        });

        // Attach event listeners to checkboxes
        document.querySelectorAll('.row-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', handleRowCheckboxChange);
        });

        // Attach event listeners to editable cells
        document.querySelectorAll('.editable-cell').forEach(cell => {
            cell.addEventListener('click', handleCellClick);
        });

        // Update pagination controls
        updatePaginationControls();
    }

    /**
     * Update pagination controls
     */
    function updatePaginationControls() {
        // Calculate the range being shown
        const startRecord = totalTransactions === 0 ? 0 : ((currentPage - 1) * ITEMS_PER_PAGE) + 1;
        const endRecord = Math.min(currentPage * ITEMS_PER_PAGE, totalTransactions);

        // Update display
        document.getElementById('showing-range').textContent = `${startRecord}-${endRecord}`;
        document.getElementById('total-filtered').textContent = totalTransactions;
        document.getElementById('current-page').textContent = currentPage;
        document.getElementById('total-pages').textContent = totalPages || 1;

        document.getElementById('prev-page').disabled = currentPage <= 1;
        document.getElementById('next-page').disabled = currentPage >= totalPages;
    }

    /**
     * Go to specific page - fetches new page from server
     */
    function goToPage(page) {
        if (page < 1) page = 1;
        if (page > totalPages) page = totalPages;

        if (page === currentPage) return;

        currentPage = page;
        loadTransactions();  // Fetch new page from server

        // Scroll to top of table on mobile
        document.querySelector('.edit-table-container')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Handle cell click for inline editing
     */
    function handleCellClick(e) {
        const cell = e.currentTarget;
        if (cell.classList.contains('editing')) return;

        // Set this cell as focused for keyboard navigation
        setFocusedCell(cell);

        const field = cell.dataset.field;
        const txnId = parseInt(cell.dataset.id);
        const txn = allTransactionsMap.get(txnId);

        if (!txn) return;

        // Get current value - support both field name formats
        let currentValue = '';
        if (field === 'vendor') {
            currentValue = txn.vendor || txn['Client/Vendor'] || '';
        } else if (field === 'category') {
            currentValue = txn.category || txn.Category || '';
        } else if (field === 'project') {
            currentValue = txn.project || txn.Project || '';
        } else {
            currentValue = txn[field] || '';
        }

        cell.classList.add('editing');

        let input;
        let datalist = null;

        if (field === 'category') {
            // Use input with datalist for category (allows typing new values + selection)
            input = document.createElement('input');
            input.type = 'text';
            input.value = currentValue;
            input.setAttribute('list', `category-datalist-${txnId}`);
            input.placeholder = 'Type or select category';

            // Create datalist for suggestions
            datalist = document.createElement('datalist');
            datalist.id = `category-datalist-${txnId}`;
            categories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat;
                datalist.appendChild(option);
            });
        } else if (field === 'project') {
            // Use input with datalist for project (allows typing new values + selection)
            input = document.createElement('input');
            input.type = 'text';
            input.value = currentValue;
            input.setAttribute('list', `project-datalist-${txnId}`);
            input.placeholder = 'Type or select project';

            // Create datalist for suggestions
            datalist = document.createElement('datalist');
            datalist.id = `project-datalist-${txnId}`;
            projects.forEach(proj => {
                const option = document.createElement('option');
                option.value = proj;
                datalist.appendChild(option);
            });
        } else {
            // Use input for other fields
            input = document.createElement('input');
            input.type = 'text';
            input.value = currentValue;
        }

        cell.innerHTML = '';
        cell.appendChild(input);
        if (datalist) {
            cell.appendChild(datalist);
        }
        input.focus();

        // Save on blur (only if not navigating via keyboard)
        input.addEventListener('blur', () => {
            // Delay to allow keyboard navigation to cancel the blur-save
            setTimeout(() => {
                if (cell.classList.contains('editing')) {
                    finishCellEdit(cell, input, field, txnId);
                }
            }, 50);
        });

        // Keyboard handling for Excel-like navigation while editing
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                finishCellEdit(cell, input, field, txnId, 'down');
            } else if (e.key === 'Escape') {
                e.preventDefault();
                // Cancel edit without saving - restore original value
                cell.classList.remove('editing');
                if (field === 'category') {
                    const val = allTransactionsMap.get(txnId)?.category || allTransactionsMap.get(txnId)?.Category || '';
                    const isUncat = isUncategorized(val);
                    cell.innerHTML = `<span class="category-badge ${isUncat ? 'uncategorized' : ''}">${val}</span>`;
                } else if (field === 'project') {
                    const val = allTransactionsMap.get(txnId)?.project || allTransactionsMap.get(txnId)?.Project || '';
                    const isEmpty = !val;
                    cell.innerHTML = `<span class="project-badge ${isEmpty ? 'empty' : ''}">${val || '-'}</span>`;
                } else {
                    const val = field === 'vendor' ? (allTransactionsMap.get(txnId)?.vendor || allTransactionsMap.get(txnId)?.['Client/Vendor'] || '') : '';
                    cell.textContent = val;
                }
                setFocusedCell(cell);
            } else if (e.key === 'Tab') {
                e.preventDefault();
                finishCellEdit(cell, input, field, txnId, e.shiftKey ? 'left' : 'right');
            } else if (e.key === 'ArrowDown' && field !== 'category' && field !== 'project') {
                // For non-datalist fields, allow arrow nav while editing
                e.preventDefault();
                finishCellEdit(cell, input, field, txnId, 'down');
            } else if (e.key === 'ArrowUp' && field !== 'category' && field !== 'project') {
                e.preventDefault();
                finishCellEdit(cell, input, field, txnId, 'up');
            }
        });
    }

    /**
     * Finish editing a cell, optionally navigate in a direction afterward
     * @param {string} direction - 'up', 'down', 'left', 'right', or null
     */
    function finishCellEdit(cell, input, field, txnId, direction = null) {
        const newValue = input.value.trim();
        const txn = allTransactionsMap.get(txnId);

        if (!txn) return;

        // Prevent double-processing
        if (!cell.classList.contains('editing')) return;
        cell.classList.remove('editing');

        // Update local transaction data - support both field name formats
        if (field === 'vendor') {
            txn['Client/Vendor'] = newValue;
            txn['vendor'] = newValue;
        } else if (field === 'category') {
            txn['Category'] = newValue;
            txn['category'] = newValue;
        } else if (field === 'project') {
            txn['Project'] = newValue;
            txn['project'] = newValue;
            // Add new project to suggestions list if not already present
            if (newValue && !projects.includes(newValue)) {
                projects.push(newValue);
                projects.sort();
            }
        }

        // Track modification by ID
        if (!modifiedTransactions.has(txnId)) {
            modifiedTransactions.set(txnId, {});
        }
        modifiedTransactions.get(txnId)[field] = newValue;
        modifiedTransactions.get(txnId).id = txnId;

        updateModifiedUI();

        // Re-render table to show modified indicator
        renderTable();

        // After render, navigate to the next cell if direction specified
        if (direction) {
            const targetCell = getAdjacentCell(txnId, field, direction);
            if (targetCell) {
                if (direction === 'up' || direction === 'down') {
                    // Enter on edit commits and moves focus down (like Excel)
                    setFocusedCell(targetCell);
                } else {
                    // Tab moves to next cell and starts editing (like Excel)
                    setFocusedCell(targetCell);
                    targetCell.click();
                }
            }
        } else {
            // No direction - just re-focus the same cell after re-render
            const sameCell = findCellByIdAndField(txnId, field);
            if (sameCell) {
                setFocusedCell(sameCell);
            }
        }
    }

    // ========== Excel-like Navigation Functions ==========

    /**
     * Find a cell element by transaction ID and field name
     */
    function findCellByIdAndField(txnId, field) {
        return document.querySelector(`.editable-cell[data-id="${txnId}"][data-field="${field}"]`);
    }

    /**
     * Set a cell as the focused (highlighted) cell for keyboard navigation
     */
    function setFocusedCell(cell) {
        // Remove focus from previous cell
        if (focusedCell) {
            focusedCell.classList.remove('cell-focused');
        }
        focusedCell = cell;
        if (cell) {
            cell.classList.add('cell-focused');
            // Scroll into view if needed
            cell.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    }

    /**
     * Clear the focused cell
     */
    function clearFocusedCell() {
        if (focusedCell) {
            focusedCell.classList.remove('cell-focused');
            focusedCell = null;
        }
    }

    /**
     * Get the adjacent editable cell given current position and direction
     */
    function getAdjacentCell(txnId, field, direction) {
        const allEditableCells = Array.from(document.querySelectorAll('.editable-cell'));
        if (allEditableCells.length === 0) return null;

        const currentFieldIdx = EDITABLE_FIELDS.indexOf(field);
        const currentRow = document.querySelector(`.editable-cell[data-id="${txnId}"]`)?.closest('tr');
        if (!currentRow) return null;

        const allRows = Array.from(tableBody.querySelectorAll('tr'));
        const currentRowIdx = allRows.indexOf(currentRow);

        let targetRowIdx = currentRowIdx;
        let targetFieldIdx = currentFieldIdx;

        if (direction === 'up') {
            targetRowIdx = currentRowIdx - 1;
        } else if (direction === 'down') {
            targetRowIdx = currentRowIdx + 1;
        } else if (direction === 'left') {
            targetFieldIdx = currentFieldIdx - 1;
            if (targetFieldIdx < 0) {
                // Wrap to last editable field of previous row
                targetFieldIdx = EDITABLE_FIELDS.length - 1;
                targetRowIdx = currentRowIdx - 1;
            }
        } else if (direction === 'right') {
            targetFieldIdx = currentFieldIdx + 1;
            if (targetFieldIdx >= EDITABLE_FIELDS.length) {
                // Wrap to first editable field of next row
                targetFieldIdx = 0;
                targetRowIdx = currentRowIdx + 1;
            }
        }

        // Bounds check
        if (targetRowIdx < 0 || targetRowIdx >= allRows.length) return null;

        const targetRow = allRows[targetRowIdx];
        const targetField = EDITABLE_FIELDS[targetFieldIdx];
        const targetCell = targetRow.querySelector(`.editable-cell[data-field="${targetField}"]`);

        return targetCell || null;
    }

    /**
     * Global keyboard handler for Excel-like cell navigation
     */
    function handleTableKeydown(e) {
        // Don't interfere if user is typing in a search box, bulk input, or other non-table input
        const activeEl = document.activeElement;
        const isInTableInput = activeEl && activeEl.tagName === 'INPUT' && activeEl.closest('.editable-cell');
        const isOtherInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'SELECT') && !activeEl.closest('.editable-cell');

        if (isOtherInput) return; // Don't capture keys when in search/filter inputs

        // If currently editing a cell, the input's own keydown handler manages navigation
        if (isInTableInput) return;

        // Navigation mode - a cell is focused but not being edited
        if (!focusedCell) return;

        const field = focusedCell.dataset.field;
        const txnId = parseInt(focusedCell.dataset.id);

        switch (e.key) {
            case 'ArrowUp':
                e.preventDefault();
                const upCell = getAdjacentCell(txnId, field, 'up');
                if (upCell) setFocusedCell(upCell);
                break;
            case 'ArrowDown':
                e.preventDefault();
                const downCell = getAdjacentCell(txnId, field, 'down');
                if (downCell) setFocusedCell(downCell);
                break;
            case 'ArrowLeft':
                e.preventDefault();
                const leftCell = getAdjacentCell(txnId, field, 'left');
                if (leftCell) setFocusedCell(leftCell);
                break;
            case 'ArrowRight':
                e.preventDefault();
                const rightCell = getAdjacentCell(txnId, field, 'right');
                if (rightCell) setFocusedCell(rightCell);
                break;
            case 'Enter':
                e.preventDefault();
                // Start editing the focused cell
                focusedCell.click();
                break;
            case 'Tab':
                e.preventDefault();
                const tabDir = e.shiftKey ? 'left' : 'right';
                const tabCell = getAdjacentCell(txnId, field, tabDir);
                if (tabCell) {
                    setFocusedCell(tabCell);
                    tabCell.click(); // Start editing immediately on Tab
                }
                break;
            case 'Escape':
                e.preventDefault();
                clearFocusedCell();
                break;
            case 'F2':
                // F2 to edit (like Excel)
                e.preventDefault();
                focusedCell.click();
                break;
            default:
                // If user starts typing a printable character, start editing
                if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
                    e.preventDefault();
                    focusedCell.click();
                    // After click opens the input, type the character
                    setTimeout(() => {
                        const inp = focusedCell.querySelector('input');
                        if (inp) {
                            inp.value = e.key;
                            // Move cursor to end
                            inp.setSelectionRange(inp.value.length, inp.value.length);
                        }
                    }, 10);
                }
                break;
        }
    }

    /**
     * Update modified transactions UI
     */
    function updateModifiedUI() {
        const count = modifiedTransactions.size;
        modifiedCountEl.textContent = count;

        if (count > 0) {
            modifiedBadge.style.display = 'inline-flex';
            saveAllBtn.style.display = 'inline-block';
            discardAllBtn.style.display = 'inline-block';
        } else {
            modifiedBadge.style.display = 'none';
            saveAllBtn.style.display = 'none';
            discardAllBtn.style.display = 'none';
        }
    }

    /**
     * Save all modified transactions
     */
    async function saveAllChanges() {
        if (modifiedTransactions.size === 0) {
            return;
        }

        // Get modified transactions from the map
        const transactionsToSave = [];
        for (const [txnId, modifications] of modifiedTransactions) {
            const txn = allTransactionsMap.get(txnId);
            if (txn) {
                transactionsToSave.push(txn);
            }
        }

        const totalCount = transactionsToSave.length;

        saveAllBtn.disabled = true;
        saveAllBtn.textContent = `Saving 0/${totalCount}...`;
        showLoading();

        let successCount = 0;
        let failedCount = 0;

        // Save in parallel batches of 5 for better performance
        const batchSize = 5;
        for (let i = 0; i < transactionsToSave.length; i += batchSize) {
            const batch = transactionsToSave.slice(i, i + batchSize);
            const promises = batch.map(txn => saveTransaction(txn));
            const results = await Promise.all(promises);

            results.forEach(success => {
                if (success) successCount++;
                else failedCount++;
            });

            // Update progress
            saveAllBtn.textContent = `Saving ${successCount + failedCount}/${totalCount}...`;
        }

        hideLoading();

        // Clear modified state
        modifiedTransactions.clear();
        updateModifiedUI();
        renderTable();

        saveAllBtn.disabled = false;
        saveAllBtn.textContent = 'Save All Changes';

        if (failedCount === 0) {
            showNotification(`All ${successCount} changes saved successfully!`);
        } else {
            showNotification(`Saved ${successCount}, Failed ${failedCount}`, 'error');
        }

        // Reload data to ensure consistency
        await loadTransactions();
    }

    /**
     * Discard all unsaved changes
     */
    async function discardAllChanges() {
        if (!confirm(`Discard ${modifiedTransactions.size} unsaved changes?`)) {
            return;
        }

        // Reload data from server
        showLoading();
        modifiedTransactions.clear();
        await loadTransactions();
        hideLoading();

        updateModifiedUI();

        showNotification('Changes discarded');
    }

    /**
     * Save a single transaction to the server
     */
    async function saveTransaction(txn) {
        try {
            // Build request data - handle both old and new field name formats
            const requestData = {
                date: txn.date_raw || txn.Date,
                description: txn.description || txn['Transaction Description'],
                debit: parseFloat(txn.dr_amount || txn['DR Amount'] || 0),
                credit: parseFloat(txn.cr_amount || txn['CR Amount'] || 0),
                category: txn.category || txn.Category,
                vendor: txn.vendor || txn['Client/Vendor'],
                project: txn.project || txn.Project || null,
                dd: txn.dd || txn.DD || null,
                notes: txn.notes || txn.Notes || null
            };



            const response = await fetch(`/api/${BANK_CODE}/transaction/update`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestData)
            });

            const result = await response.json();

            if (!response.ok) {
                console.error('[ERROR] Update failed:', result);
            }

            return response.ok && result.success;
        } catch (error) {
            console.error('Error saving transaction:', error);
            return false;
        }
    }

    /**
     * Handle row checkbox change
     */
    function handleRowCheckboxChange(e) {
        const txnId = parseInt(e.target.dataset.id);

        if (e.target.checked) {
            selectedTransactionIds.add(txnId);
            e.target.closest('tr').classList.add('selected');
        } else {
            selectedTransactionIds.delete(txnId);
            e.target.closest('tr').classList.remove('selected');
        }

        updateSelectionUI();
    }

    /**
     * Handle select all checkbox
     */
    function handleSelectAllChange(e) {
        const isChecked = e.target.checked;

        allTransactions.forEach(txn => {
            if (isChecked) {
                selectedTransactionIds.add(txn.id);
            } else {
                selectedTransactionIds.delete(txn.id);
            }
        });

        renderTable();
        updateSelectionUI();
    }

    /**
     * Update selection UI
     */
    function updateSelectionUI() {
        selectedCountEl.textContent = selectedTransactionIds.size;
        bulkCountEl.textContent = selectedTransactionIds.size;

        if (selectedTransactionIds.size > 0) {
            bulkEditBar.style.display = 'flex';
        } else {
            bulkEditBar.style.display = 'none';
        }

        // Update select all checkbox state
        const allCurrentSelected = allTransactions.every(txn =>
            selectedTransactionIds.has(txn.id)
        );
        selectAllCheckbox.checked = allCurrentSelected && allTransactions.length > 0;
    }

    /**
     * Apply bulk edit
     */
    async function applyBulkEdit() {
        const bulkCategory = document.getElementById('bulk-category').value;
        const bulkProject = document.getElementById('bulk-project').value.trim();

        if (!bulkCategory && !bulkProject) {
            alert('Please select at least one field to update');
            return;
        }

        showLoading();

        // Get selected transactions from IDs
        const selectedTxns = allTransactions.filter(txn => selectedTransactionIds.has(txn.id));

        for (const txn of selectedTxns) {
            // Update local data - support both field name formats
            if (bulkCategory) {
                txn.Category = bulkCategory;
                txn.category = bulkCategory;
            }
            if (bulkProject) {
                txn.Project = bulkProject;
                txn.project = bulkProject;
            }

            // Mark as modified by ID
            if (!modifiedTransactions.has(txn.id)) {
                modifiedTransactions.set(txn.id, {});
            }
            if (bulkCategory) {
                modifiedTransactions.get(txn.id).category = bulkCategory;
            }
            if (bulkProject) {
                modifiedTransactions.get(txn.id).project = bulkProject;
            }
            modifiedTransactions.get(txn.id).id = txn.id;
        }

        hideLoading();

        // Clear selection
        selectedTransactionIds.clear();
        updateSelectionUI();

        // Update modified UI
        updateModifiedUI();

        // Re-render table
        renderTable();

        // Clear bulk inputs
        document.getElementById('bulk-category').value = '';
        document.getElementById('bulk-project').value = '';

        showNotification(`Bulk update complete! ${selectedTxns.length} transactions marked for saving.`);
    }

    /**
     * Cancel bulk edit
     */
    function cancelBulkEdit() {
        selectedTransactionIds.clear();
        updateSelectionUI();
        renderTable();
    }

    /**
     * Show uncategorized transactions
     */
    function showUncategorized() {
        const dd = dropdowns['edit-category-filter'];
        if (dd) {
            dd.clear();
            dd.toggleOption('Uncategorized'); // This triggers sync and apply
        }
    }

    /**
     * Clear all filters
     */
    function clearAllFilters() {
        currentFilters = {
            category: [],
            project: [],
            vendor: [],
            search: '',
            startDate: null,
            endDate: null
        };

        // Clear dropdowns
        if (dropdowns['edit-category-filter']) dropdowns['edit-category-filter'].clear();
        if (dropdowns['edit-project-filter']) dropdowns['edit-project-filter'].clear();
        if (dropdowns['edit-vendor-filter']) dropdowns['edit-vendor-filter'].clear();

        document.getElementById('edit-search').value = '';

        // Clear date inputs
        const startInput = document.getElementById('edit-start-date');
        const endInput = document.getElementById('edit-end-date');
        if (startInput) startInput.value = '';
        if (endInput) endInput.value = '';

        // Reset to page 1 and reload (applyFilters will also refreshFilterOptions with no params, restoring all options)
        applyFilters();
    }

    /**
     * Update counts
     */
    function updateCounts() {
        totalCountEl.textContent = totalTransactions;
    }

    // Debounce timer for search
    let searchDebounceTimer = null;

    /**
     * Setup event listeners
     */
    function setupEventListeners() {
        // Excel-like keyboard navigation for editable cells
        document.addEventListener('keydown', handleTableKeydown);

        // Clear cell focus when clicking outside the table
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.editable-cell') && !e.target.closest('.edit-table-container')) {
                clearFocusedCell();
            }
        });

        // Date sort toggle
        const dateSortHeader = document.getElementById('date-sort-header');
        if (dateSortHeader) {
            dateSortHeader.addEventListener('click', async (e) => {
                e.stopPropagation();
                if (isLoading) return;

                currentSortOrder = currentSortOrder === 'desc' ? 'asc' : 'desc';
                const icon = dateSortHeader.querySelector('.sort-icon');
                if (icon) {
                    icon.textContent = currentSortOrder === 'desc' ? '↓' : '↑';
                }
                dateSortHeader.classList.add('sorting');
                currentPage = 1;
                showLoading();
                await loadTransactions();
                hideLoading();
                dateSortHeader.classList.remove('sorting');
            });
        }

        // Filters
        // Note: Category, Project, Vendor filters are now handled by CustomDropdown class events

        // Debounced search for server-side filtering
        document.getElementById('edit-search').addEventListener('input', (e) => {
            currentFilters.search = e.target.value;

            // Debounce search requests to avoid too many API calls
            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => {
                applyFilters();
            }, 300);  // 300ms debounce
        });

        document.getElementById('filter-uncategorized').addEventListener('click', showUncategorized);
        document.getElementById('clear-all-filters').addEventListener('click', clearAllFilters);

        // Date filter listeners
        const startDateInput = document.getElementById('edit-start-date');
        const endDateInput = document.getElementById('edit-end-date');

        if (startDateInput) {
            startDateInput.addEventListener('change', () => {
                currentFilters.startDate = startDateInput.value || null;
                applyFilters();
            });
        }

        if (endDateInput) {
            endDateInput.addEventListener('change', () => {
                currentFilters.endDate = endDateInput.value || null;
                applyFilters();
            });
        }

        // Select all
        selectAllCheckbox.addEventListener('change', handleSelectAllChange);

        // Bulk actions
        document.getElementById('apply-bulk-edit').addEventListener('click', applyBulkEdit);
        document.getElementById('cancel-bulk-edit').addEventListener('click', cancelBulkEdit);

        // Save/Discard all changes
        saveAllBtn.addEventListener('click', saveAllChanges);
        discardAllBtn.addEventListener('click', discardAllChanges);

        // Pagination listeners
        document.getElementById('prev-page')?.addEventListener('click', () => {
            goToPage(currentPage - 1);
        });

        document.getElementById('next-page')?.addEventListener('click', () => {
            goToPage(currentPage + 1);
        });

        // Mobile filter toggle
        const filterToggle = document.getElementById('edit-filter-toggle');
        const filterContent = document.getElementById('edit-filter-content');

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
                renderTable();
                updatePaginationControls();
            }, 250);
        });
    }

    /**
     * Utility functions
     */
    function showLoading() {
        loadingOverlay.classList.remove('hidden');
    }

    function hideLoading() {
        loadingOverlay.classList.add('hidden');
    }

    function showNotification(message, type = 'success') {
        const notification = document.createElement('div');
        notification.className = 'save-notification';
        notification.textContent = message;

        if (type === 'error') {
            notification.style.background = '#ef4444';
        }

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function truncateText(text, maxLength) {
        if (!text) return '';
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    // ========================================================================
    // SPLIT TRANSACTION FUNCTIONALITY
    // ========================================================================

    // Split modal state
    let splitOriginalTransaction = null;
    let splitRows = [];
    let isDebitSplit = true; // true if splitting debit, false if splitting credit

    // Split modal DOM elements
    const splitModal = document.getElementById('split-modal');
    const splitRowsContainer = document.getElementById('split-rows-container');
    const splitOriginalDate = document.getElementById('split-original-date');
    const splitOriginalDesc = document.getElementById('split-original-desc');
    const splitOriginalVendor = document.getElementById('split-original-vendor');
    const splitOriginalAmount = document.getElementById('split-original-amount');
    const splitTotalAmount = document.getElementById('split-total-amount');
    const splitRemaining = document.getElementById('split-remaining');
    const splitValidationMessage = document.getElementById('split-validation-message');
    const applySplitBtn = document.getElementById('apply-split');
    const splitTransactionBtn = document.getElementById('split-transaction-btn');

    /**
     * Show or hide the split button based on selection
     */
    function updateSplitButtonVisibility() {
        if (splitTransactionBtn) {
            // Show split button only when exactly 1 transaction is selected
            if (selectedTransactionIds.size === 1) {
                splitTransactionBtn.style.display = 'inline-block';
            } else {
                splitTransactionBtn.style.display = 'none';
            }
        }
    }

    /**
     * Show the split modal
     */
    function showSplitModal() {
        if (selectedTransactionIds.size !== 1) {
            alert('Please select exactly one transaction to split.');
            return;
        }

        // Get the selected transaction by ID
        const selectedId = Array.from(selectedTransactionIds)[0];
        splitOriginalTransaction = allTransactionsMap.get(selectedId);

        // Determine if we're splitting debit or credit
        const drAmount = parseFloat(splitOriginalTransaction.dr_amount || splitOriginalTransaction['DR Amount'] || 0);
        const crAmount = parseFloat(splitOriginalTransaction.cr_amount || splitOriginalTransaction['CR Amount'] || 0);

        if (drAmount <= 0 && crAmount <= 0) {
            alert('Cannot split a transaction with zero amount.');
            return;
        }

        isDebitSplit = drAmount > 0;
        const originalAmount = isDebitSplit ? drAmount : crAmount;

        // Populate original transaction summary
        splitOriginalDate.textContent = splitOriginalTransaction.date || '-';
        splitOriginalDesc.textContent = truncateText(splitOriginalTransaction.description || splitOriginalTransaction['Transaction Description'] || '-', 80);
        splitOriginalVendor.textContent = splitOriginalTransaction.vendor || splitOriginalTransaction['Client/Vendor'] || '-';
        splitOriginalAmount.textContent = `₹ ${formatIndianNumber(originalAmount)} (${isDebitSplit ? 'Debit' : 'Credit'})`;

        // Initialize with 2 split rows
        splitRows = [
            createEmptySplitRow(0),
            createEmptySplitRow(1)
        ];

        // Render split rows
        renderSplitRows();
        updateSplitValidation();

        // Show modal
        splitModal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    /**
     * Create an empty split row object
     */
    function createEmptySplitRow(index) {
        return {
            amount: '',
            vendor: splitOriginalTransaction.vendor || splitOriginalTransaction['Client/Vendor'] || '',
            category: splitOriginalTransaction.category || splitOriginalTransaction.Category || 'Uncategorized',
            project: splitOriginalTransaction.project || splitOriginalTransaction.Project || '',
            notes: ''
        };
    }

    /**
     * Render all split rows in the modal
     */
    function renderSplitRows() {
        splitRowsContainer.innerHTML = '';

        splitRows.forEach((row, index) => {
            const rowCard = document.createElement('div');
            rowCard.className = 'split-row-card';
            rowCard.dataset.index = index;

            // Build category datalist options
            let categoryDatalistOptions = categories.map(cat =>
                `<option value="${cat}">`
            ).join('');

            rowCard.innerHTML = `
                <div class="split-row-header">
                    <span class="split-row-number">Split ${index + 1}</span>
                    <button class="split-row-remove" data-index="${index}" ${splitRows.length <= 2 ? 'disabled' : ''}>Remove</button>
                </div>
                <div class="split-row-fields">
                    <div class="split-field">
                        <label>Amount *</label>
                        <input type="number" step="0.01" min="0" class="split-amount-input" data-index="${index}" value="${row.amount}" placeholder="0.00">
                    </div>
                    <div class="split-field">
                        <label>Category</label>
                        <input type="text" class="split-category-input" data-index="${index}" value="${escapeHtml(row.category)}" list="split-category-datalist-${index}" placeholder="Type or select">
                        <datalist id="split-category-datalist-${index}">${categoryDatalistOptions}</datalist>
                    </div>
                    <div class="split-field">
                        <label>Vendor</label>
                        <input type="text" class="split-vendor-input" data-index="${index}" value="${escapeHtml(row.vendor)}" placeholder="Vendor name">
                    </div>
                    <div class="split-field">
                        <label>Project</label>
                        <input type="text" class="split-project-input" data-index="${index}" value="${escapeHtml(row.project)}" placeholder="Project name">
                    </div>
                    <div class="split-field full-width">
                        <label>Notes</label>
                        <input type="text" class="split-notes-input" data-index="${index}" value="${escapeHtml(row.notes)}" placeholder="Optional notes">
                    </div>
                </div>
            `;

            splitRowsContainer.appendChild(rowCard);
        });

        // Attach event listeners
        document.querySelectorAll('.split-amount-input').forEach(input => {
            input.addEventListener('input', handleSplitAmountChange);
        });

        document.querySelectorAll('.split-category-input').forEach(input => {
            input.addEventListener('input', handleSplitFieldChange);
        });

        document.querySelectorAll('.split-vendor-input, .split-project-input, .split-notes-input').forEach(input => {
            input.addEventListener('input', handleSplitFieldChange);
        });

        document.querySelectorAll('.split-row-remove').forEach(btn => {
            btn.addEventListener('click', handleRemoveSplitRow);
        });
    }

    /**
     * Handle split amount change
     */
    function handleSplitAmountChange(e) {
        const index = parseInt(e.target.dataset.index);
        splitRows[index].amount = e.target.value;
        updateSplitValidation();
    }

    /**
     * Handle other field changes
     */
    function handleSplitFieldChange(e) {
        const index = parseInt(e.target.dataset.index);
        const field = e.target.className.includes('category') ? 'category' :
            e.target.className.includes('vendor') ? 'vendor' :
                e.target.className.includes('project') ? 'project' : 'notes';
        splitRows[index][field] = e.target.value;
    }

    /**
     * Add a new split row
     */
    function addSplitRow() {
        splitRows.push(createEmptySplitRow(splitRows.length));
        renderSplitRows();
        updateSplitValidation();
    }

    /**
     * Remove a split row
     */
    function handleRemoveSplitRow(e) {
        if (splitRows.length <= 2) return;

        const index = parseInt(e.target.dataset.index);
        splitRows.splice(index, 1);
        renderSplitRows();
        updateSplitValidation();
    }

    /**
     * Update split validation
     */
    function updateSplitValidation() {
        const drAmount = parseFloat(splitOriginalTransaction.dr_amount || splitOriginalTransaction['DR Amount'] || 0);
        const crAmount = parseFloat(splitOriginalTransaction.cr_amount || splitOriginalTransaction['CR Amount'] || 0);
        const originalAmount = isDebitSplit ? drAmount : crAmount;

        // Calculate total split amount
        let totalSplit = 0;
        let hasEmptyAmount = false;
        let hasInvalidAmount = false;

        splitRows.forEach((row, index) => {
            const amount = parseFloat(row.amount) || 0;
            totalSplit += amount;

            if (row.amount === '' || row.amount === null) {
                hasEmptyAmount = true;
            }
            if (amount < 0) {
                hasInvalidAmount = true;
            }
        });

        // Update display
        splitTotalAmount.textContent = formatIndianNumber(totalSplit);

        const remaining = originalAmount - totalSplit;
        splitRemaining.textContent = formatIndianNumber(Math.abs(remaining));

        // Validate
        const isValid = Math.abs(remaining) < 0.01 && !hasEmptyAmount && !hasInvalidAmount && splitRows.length >= 2;

        if (remaining > 0.01) {
            splitRemaining.className = 'split-remaining invalid';
            splitRemaining.textContent = `₹ ${formatIndianNumber(remaining)} remaining`;
        } else if (remaining < -0.01) {
            splitRemaining.className = 'split-remaining invalid';
            splitRemaining.textContent = `₹ ${formatIndianNumber(Math.abs(remaining))} over`;
        } else {
            splitRemaining.className = 'split-remaining valid';
            splitRemaining.textContent = '₹ 0.00 - Balanced';
        }

        // Update validation message
        if (hasEmptyAmount) {
            splitValidationMessage.textContent = 'Please enter an amount for all split rows.';
            splitValidationMessage.className = 'split-validation-message error';
        } else if (hasInvalidAmount) {
            splitValidationMessage.textContent = 'Amounts must be greater than zero.';
            splitValidationMessage.className = 'split-validation-message error';
        } else if (Math.abs(remaining) >= 0.01) {
            splitValidationMessage.textContent = `Split amounts must equal the original amount (₹ ${formatIndianNumber(originalAmount)}).`;
            splitValidationMessage.className = 'split-validation-message error';
        } else {
            splitValidationMessage.textContent = 'Ready to split!';
            splitValidationMessage.className = 'split-validation-message success';
        }

        // Enable/disable apply button
        applySplitBtn.disabled = !isValid;
    }

    /**
     * Format number in Indian format (lakhs, crores)
     */
    function formatIndianNumber(num) {
        if (num === null || num === undefined || isNaN(num)) return '0.00';
        num = parseFloat(num);
        const fixed = num.toFixed(2);
        const parts = fixed.split('.');
        let intPart = parts[0];
        const decPart = parts[1];

        // Indian number formatting
        const lastThree = intPart.slice(-3);
        const otherNumbers = intPart.slice(0, -3);
        if (otherNumbers !== '') {
            intPart = otherNumbers.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + lastThree;
        }
        return intPart + '.' + decPart;
    }

    /**
     * Close the split modal
     */
    function closeSplitModal() {
        splitModal.style.display = 'none';
        document.body.style.overflow = '';
        splitOriginalTransaction = null;
        splitRows = [];
    }

    /**
     * Apply the split - send to API
     */
    async function applySplit() {
        if (!splitOriginalTransaction || splitRows.length < 2) {
            alert('Invalid split configuration.');
            return;
        }

        // Validate one more time
        const drAmount = parseFloat(splitOriginalTransaction.dr_amount || splitOriginalTransaction['DR Amount'] || 0);
        const crAmount = parseFloat(splitOriginalTransaction.cr_amount || splitOriginalTransaction['CR Amount'] || 0);
        const originalAmount = isDebitSplit ? drAmount : crAmount;

        let totalSplit = 0;
        splitRows.forEach(row => {
            totalSplit += parseFloat(row.amount) || 0;
        });

        if (Math.abs(originalAmount - totalSplit) >= 0.01) {
            alert('Split amounts do not match the original amount.');
            return;
        }

        // Disable button and show loading
        applySplitBtn.disabled = true;
        applySplitBtn.textContent = 'Splitting...';
        showLoading();

        try {
            const response = await fetch(`/api/${BANK_CODE}/transaction/split`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    original: {
                        id: splitOriginalTransaction.id,
                        date: splitOriginalTransaction.date_raw || splitOriginalTransaction.Date,
                        description: splitOriginalTransaction.description || splitOriginalTransaction['Transaction Description'],
                        debit: drAmount,
                        credit: crAmount
                    },
                    isDebit: isDebitSplit,
                    splits: splitRows.map((row, index) => ({
                        amount: parseFloat(row.amount) || 0,
                        vendor: row.vendor,
                        category: row.category,
                        project: row.project || null,
                        notes: row.notes || null
                    }))
                })
            });

            const result = await response.json();

            if (response.ok && result.success) {
                showNotification(`Transaction split into ${splitRows.length} parts successfully!`);
                closeSplitModal();

                // Clear selection and reload
                selectedTransactionIds.clear();
                updateSelectionUI();
                await loadTransactions();
            } else {
                showNotification(result.error || 'Failed to split transaction', 'error');
            }
        } catch (error) {
            console.error('Error splitting transaction:', error);
            showNotification('Error splitting transaction. Please try again.', 'error');
        } finally {
            hideLoading();
            applySplitBtn.disabled = false;
            applySplitBtn.textContent = 'Apply Split';
        }
    }

    /**
     * Setup split event listeners
     */
    function setupSplitEventListeners() {
        // Split button in bulk edit bar
        if (splitTransactionBtn) {
            splitTransactionBtn.addEventListener('click', showSplitModal);
        }

        // Modal close buttons
        document.getElementById('close-split-modal')?.addEventListener('click', closeSplitModal);
        document.getElementById('cancel-split')?.addEventListener('click', closeSplitModal);

        // Add row button
        document.getElementById('add-split-row')?.addEventListener('click', addSplitRow);

        // Apply split button
        if (applySplitBtn) {
            applySplitBtn.addEventListener('click', applySplit);
        }

        // Close on overlay click
        if (splitModal) {
            splitModal.addEventListener('click', (e) => {
                if (e.target === splitModal) {
                    closeSplitModal();
                }
            });
        }

        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && splitModal && splitModal.style.display !== 'none') {
                closeSplitModal();
            }
        });
    }

    // Override updateSelectionUI to include split button visibility
    const originalUpdateSelectionUI = updateSelectionUI;
    updateSelectionUI = function () {
        originalUpdateSelectionUI();
        updateSplitButtonVisibility();
    };

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', () => {
        init();
        setupSplitEventListeners();
    });

})();
