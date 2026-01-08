/**
 * Edit Transactions Page - Comprehensive Edit & Bulk Operations
 */

(function () {
    'use strict';

    // Bank code from page context
    const BANK_CODE = window.BANK_CODE || 'axis';
    const BANK_NAME = window.BANK_NAME || 'Axis Bank';

    // Global state
    let allTransactions = [];
    let filteredTransactions = [];
    let selectedTransactionIndices = new Set();
    let modifiedTransactionIndices = new Set();  // Track unsaved changes
    let categories = [];

    // Pagination state
    let currentPage = 1;
    const ITEMS_PER_PAGE = 10;

    // Filter state
    let currentFilters = {
        category: [], // Empty means All
        project: [],
        vendor: [],
        search: ''
    };

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

        // Load categories
        await loadCategories();

        // Load transactions
        await loadTransactions();

        // Setup event listeners
        setupEventListeners();

        hideLoading();
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

            // Populate bulk category select (keep as select for now)
            const bulkCategory = document.getElementById('bulk-category');
            bulkCategory.innerHTML = '<option value="">Change Category...</option>';
            categories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat;
                option.textContent = cat;
                bulkCategory.appendChild(option);
            });

        } catch (error) {
            console.error('Error loading categories:', error);
        }
    }

    /**
     * Load all transactions from API
     */
    async function loadTransactions() {
        try {
            const response = await fetch(`/api/${BANK_CODE}/transactions?limit=10000`);
            const data = await response.json();
            allTransactions = data.transactions;

            // Populate project and vendor filters
            populateProjectFilter();
            populateVendorFilter();

            applyFilters();
            renderTable();
            updateCounts();
        } catch (error) {
            console.error('Error loading transactions:', error);
        }
    }

    /**
     * Populate project filter with unique projects from transactions
     */
    function populateProjectFilter() {
        const uniqueProjects = new Set();
        allTransactions.forEach(txn => {
            const project = txn.project || txn.Project;
            if (project && project.trim()) uniqueProjects.add(project.trim());
        });

        const sortedProjects = Array.from(uniqueProjects).sort();

        // Init Project Dropdown
        const dd = new CustomDropdown('edit-project-filter', 'All Projects', 'project');
        dd.setOptions(sortedProjects);
    }

    /**
     * Populate vendor filter with unique vendors from transactions
     */
    function populateVendorFilter() {
        const uniqueVendors = new Set();
        allTransactions.forEach(txn => {
            const vendor = txn.vendor || txn['Client/Vendor'];
            if (vendor && vendor.trim() && vendor.trim() !== 'Unknown') {
                uniqueVendors.add(vendor.trim());
            }
        });

        const sortedVendors = Array.from(uniqueVendors).sort();

        // Init Vendor Dropdown
        const dd = new CustomDropdown('edit-vendor-filter', 'All Vendors', 'vendor');
        dd.setOptions(sortedVendors);
    }

    /**
     * Apply current filters to transactions
     */
    function applyFilters() {
        filteredTransactions = allTransactions.filter(txn => {
            // Category filter
            if (currentFilters.category.length > 0 && !currentFilters.category.includes(txn.category)) {
                return false;
            }

            // Project filter
            if (currentFilters.project.length > 0) {
                const txnProject = (txn.project || txn.Project || '').trim();
                // Handle special "No Project" if needed, but for now exact match
                if (!currentFilters.project.includes(txnProject)) return false;
            }

            // Vendor filter
            if (currentFilters.vendor.length > 0) {
                const txnVendor = (txn.vendor || txn['Client/Vendor'] || '').trim();
                if (!currentFilters.vendor.includes(txnVendor)) return false;
            }

            // Search filter (description)
            if (currentFilters.search && !txn.description.toLowerCase().includes(currentFilters.search.toLowerCase())) {
                return false;
            }

            return true;
        });

        // Reset to page 1 when filters change
        currentPage = 1;
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

        // Render all transactions as a scrollable list (both desktop and mobile)
        let pageTransactions = filteredTransactions;

        pageTransactions.forEach((txn, index) => {
            const row = document.createElement('tr');
            const globalIndex = allTransactions.indexOf(txn);
            const isSelected = selectedTransactionIndices.has(globalIndex);
            const isModified = modifiedTransactionIndices.has(globalIndex);

            if (isSelected) {
                row.classList.add('selected');
            }
            if (isModified) {
                row.classList.add('modified');
            }

            const isCategoryUncategorized = txn.category === 'Uncategorized';

            row.innerHTML = `
                <td data-label="">
                    <input type="checkbox" class="row-checkbox" data-index="${globalIndex}" ${isSelected ? 'checked' : ''}>
                </td>
                <td data-label="Date">${txn.date}</td>
                <td class="editable-cell" data-field="vendor" data-index="${globalIndex}" data-label="Vendor">${txn.vendor || ''}</td>
                <td class="editable-cell" data-field="category" data-index="${globalIndex}" data-label="Category">
                    <span class="category-badge ${isCategoryUncategorized ? 'uncategorized' : ''}">${txn.category || ''}</span>
                </td>
                <td class="description-full" data-label="Description">${escapeHtml(txn.description || txn['Transaction Description'] || '')}</td>
                <td class="text-right" data-label="Debit">${txn.dr_amount > 0 ? `<span class="monetary-pill debit">${txn.dr_amount_formatted}</span>` : ''}</td>
                <td class="text-right" data-label="Credit">${txn.cr_amount > 0 ? `<span class="monetary-pill credit">${txn.cr_amount_formatted}</span>` : ''}</td>
                <td class="editable-cell" data-field="project" data-index="${globalIndex}" data-label="Project">${txn.project || txn.Project || ''}</td>
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
        const totalPages = Math.ceil(filteredTransactions.length / ITEMS_PER_PAGE) || 1;

        document.getElementById('current-page').textContent = currentPage;
        document.getElementById('total-pages').textContent = totalPages;

        document.getElementById('prev-page').disabled = currentPage <= 1;
        document.getElementById('next-page').disabled = currentPage >= totalPages;
    }

    /**
     * Go to specific page
     */
    function goToPage(page) {
        const totalPages = Math.ceil(filteredTransactions.length / ITEMS_PER_PAGE) || 1;

        if (page < 1) page = 1;
        if (page > totalPages) page = totalPages;

        currentPage = page;
        renderTable();

        // Scroll to top of table on mobile
        document.querySelector('.edit-table-container')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Handle cell click for inline editing
     */
    function handleCellClick(e) {
        const cell = e.currentTarget;
        if (cell.classList.contains('editing')) return;

        const field = cell.dataset.field;
        const index = parseInt(cell.dataset.index);
        const txn = allTransactions[index];

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
        if (field === 'category') {
            // Use select for category
            input = document.createElement('select');
            categories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat;
                option.textContent = cat;
                if (cat === currentValue) {
                    option.selected = true;
                }
                input.appendChild(option);
            });
        } else {
            // Use input for other fields
            input = document.createElement('input');
            input.type = 'text';
            input.value = currentValue;
        }

        cell.innerHTML = '';
        cell.appendChild(input);
        input.focus();

        // Save on blur or Enter
        input.addEventListener('blur', () => finishCellEdit(cell, input, field, index));
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                finishCellEdit(cell, input, field, index);
            }
        });
    }

    /**
     * Finish editing a cell
     */
    function finishCellEdit(cell, input, field, index) {
        const newValue = input.value.trim();

        // Update local transaction data - support both field name formats
        if (field === 'vendor') {
            allTransactions[index]['Client/Vendor'] = newValue;
            allTransactions[index]['vendor'] = newValue;
        } else if (field === 'category') {
            allTransactions[index]['Category'] = newValue;
            allTransactions[index]['category'] = newValue;
        } else if (field === 'project') {
            allTransactions[index]['Project'] = newValue;
            allTransactions[index]['project'] = newValue;
        }

        // Mark as modified
        modifiedTransactionIndices.add(index);
        updateModifiedUI();

        // Re-render cell
        cell.classList.remove('editing');
        if (field === 'category') {
            const isUncategorized = newValue === 'Uncategorized';
            cell.innerHTML = `<span class="category-badge ${isUncategorized ? 'uncategorized' : ''}">${newValue}</span>`;
        } else {
            cell.textContent = newValue;
        }

        // Re-render table to show modified indicator
        renderTable();
    }

    /**
     * Update modified transactions UI
     */
    function updateModifiedUI() {
        const count = modifiedTransactionIndices.size;
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
        if (modifiedTransactionIndices.size === 0) {
            return;
        }

        const modifiedTransactions = Array.from(modifiedTransactionIndices).map(i => allTransactions[i]);
        const totalCount = modifiedTransactions.length;

        saveAllBtn.disabled = true;
        saveAllBtn.textContent = `Saving 0/${totalCount}...`;
        showLoading();

        let successCount = 0;
        let failedCount = 0;

        // Save in parallel batches of 5 for better performance
        const batchSize = 5;
        for (let i = 0; i < modifiedTransactions.length; i += batchSize) {
            const batch = modifiedTransactions.slice(i, i + batchSize);
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
        modifiedTransactionIndices.clear();
        updateModifiedUI();
        renderTable();

        saveAllBtn.disabled = false;
        saveAllBtn.textContent = 'Save All Changes';

        if (failedCount === 0) {
            showNotification(`✓ All ${successCount} changes saved successfully!`);
        } else {
            showNotification(`⚠ Saved ${successCount}, Failed ${failedCount}`, 'error');
        }

        // Reload data to ensure consistency
        await loadTransactions();
    }

    /**
     * Discard all unsaved changes
     */
    async function discardAllChanges() {
        if (!confirm(`Discard ${modifiedTransactionIndices.size} unsaved changes?`)) {
            return;
        }

        // Reload data from server
        showLoading();
        await loadTransactions();
        hideLoading();

        modifiedTransactionIndices.clear();
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

            console.log('[DEBUG] Saving transaction:', requestData);

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
        const index = parseInt(e.target.dataset.index);

        if (e.target.checked) {
            selectedTransactionIndices.add(index);
            e.target.closest('tr').classList.add('selected');
        } else {
            selectedTransactionIndices.delete(index);
            e.target.closest('tr').classList.remove('selected');
        }

        updateSelectionUI();
    }

    /**
     * Handle select all checkbox
     */
    function handleSelectAllChange(e) {
        const isChecked = e.target.checked;

        filteredTransactions.forEach(txn => {
            const globalIndex = allTransactions.indexOf(txn);
            if (isChecked) {
                selectedTransactionIndices.add(globalIndex);
            } else {
                selectedTransactionIndices.delete(globalIndex);
            }
        });

        renderTable();
        updateSelectionUI();
    }

    /**
     * Update selection UI
     */
    function updateSelectionUI() {
        selectedCountEl.textContent = selectedTransactionIndices.size;
        bulkCountEl.textContent = selectedTransactionIndices.size;

        if (selectedTransactionIndices.size > 0) {
            bulkEditBar.style.display = 'flex';
        } else {
            bulkEditBar.style.display = 'none';
        }

        // Update select all checkbox state
        const allFilteredSelected = filteredTransactions.every(txn =>
            selectedTransactionIndices.has(allTransactions.indexOf(txn))
        );
        selectAllCheckbox.checked = allFilteredSelected && filteredTransactions.length > 0;
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

        let successCount = 0;
        const selectedTransactions = Array.from(selectedTransactionIndices).map(i => allTransactions[i]);

        for (const txn of selectedTransactions) {
            const txnIndex = allTransactions.indexOf(txn);

            // Update local data - support both field name formats
            if (bulkCategory) {
                txn.Category = bulkCategory;
                txn.category = bulkCategory;
            }
            if (bulkProject) {
                txn.Project = bulkProject;
                txn.project = bulkProject;
            }

            // Mark as modified (don't save immediately)
            modifiedTransactionIndices.add(txnIndex);
        }

        hideLoading();

        // Clear selection
        selectedTransactionIndices.clear();
        updateSelectionUI();

        // Update modified UI
        updateModifiedUI();

        // Re-render table
        renderTable();

        // Clear bulk inputs
        document.getElementById('bulk-category').value = '';
        document.getElementById('bulk-project').value = '';

        showNotification(`Bulk update complete! ${selectedTransactions.length} transactions marked for saving.`);
    }

    /**
     * Cancel bulk edit
     */
    function cancelBulkEdit() {
        selectedTransactionIndices.clear();
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
            search: ''
        };

        // Clear dropdowns
        if (dropdowns['edit-category-filter']) dropdowns['edit-category-filter'].clear();
        if (dropdowns['edit-project-filter']) dropdowns['edit-project-filter'].clear();
        if (dropdowns['edit-vendor-filter']) dropdowns['edit-vendor-filter'].clear();

        document.getElementById('edit-search').value = '';

        applyFilters();
        renderTable();
        updateCounts();
    }

    /**
     * Update counts
     */
    function updateCounts() {
        totalCountEl.textContent = filteredTransactions.length;
    }

    /**
     * Setup event listeners
     */
    function setupEventListeners() {
        // Filters
        // Note: Category, Project, Vendor filters are now handled by CustomDropdown class events

        document.getElementById('edit-search').addEventListener('input', (e) => {
            currentFilters.search = e.target.value;
            applyFilters();
            renderTable();
            updateCounts();
        });

        document.getElementById('filter-uncategorized').addEventListener('click', showUncategorized);
        document.getElementById('clear-all-filters').addEventListener('click', clearAllFilters);

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
            if (selectedTransactionIndices.size === 1) {
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
        if (selectedTransactionIndices.size !== 1) {
            alert('Please select exactly one transaction to split.');
            return;
        }

        // Get the selected transaction
        const selectedIndex = Array.from(selectedTransactionIndices)[0];
        splitOriginalTransaction = allTransactions[selectedIndex];

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

            // Build category options
            let categoryOptions = categories.map(cat =>
                `<option value="${cat}" ${row.category === cat ? 'selected' : ''}>${cat}</option>`
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
                        <select class="split-category-select" data-index="${index}">
                            ${categoryOptions}
                        </select>
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

        document.querySelectorAll('.split-category-select').forEach(select => {
            select.addEventListener('change', handleSplitFieldChange);
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
                selectedTransactionIndices.clear();
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
