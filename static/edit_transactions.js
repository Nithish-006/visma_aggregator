/**
 * Edit Transactions Page - Comprehensive Edit & Bulk Operations
 */

(function() {
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

    // Filter state
    let currentFilters = {
        category: 'All',
        project: 'All',
        vendor: '',
        search: ''
    };

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

            // Populate category filter
            const categoryFilter = document.getElementById('edit-category-filter');
            categoryFilter.innerHTML = '<option value="All">All Categories</option>';
            categories.forEach(cat => {
                const option = document.createElement('option');
                option.value = cat;
                option.textContent = cat;
                categoryFilter.appendChild(option);
            });

            // Populate bulk category select
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

            // Populate project filter with unique projects
            populateProjectFilter();

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
        const projectFilter = document.getElementById('edit-project-filter');
        const uniqueProjects = new Set();

        allTransactions.forEach(txn => {
            const project = txn.project || txn.Project;
            if (project && project.trim()) {
                uniqueProjects.add(project.trim());
            }
        });

        // Sort projects alphabetically
        const sortedProjects = Array.from(uniqueProjects).sort();

        // Populate dropdown
        projectFilter.innerHTML = '<option value="All">All Projects</option>';
        sortedProjects.forEach(proj => {
            const option = document.createElement('option');
            option.value = proj;
            option.textContent = proj;
            projectFilter.appendChild(option);
        });

        // Add "No Project" option for filtering empty projects
        const noProjectOption = document.createElement('option');
        noProjectOption.value = '__EMPTY__';
        noProjectOption.textContent = '(No Project)';
        projectFilter.appendChild(noProjectOption);
    }

    /**
     * Apply current filters to transactions
     */
    function applyFilters() {
        filteredTransactions = allTransactions.filter(txn => {
            // Category filter
            if (currentFilters.category !== 'All' && txn.category !== currentFilters.category) {
                return false;
            }

            // Project filter
            if (currentFilters.project !== 'All') {
                const txnProject = (txn.project || txn.Project || '').trim();
                if (currentFilters.project === '__EMPTY__') {
                    // Filter for transactions without project
                    if (txnProject !== '') {
                        return false;
                    }
                } else if (txnProject !== currentFilters.project) {
                    return false;
                }
            }

            // Vendor filter
            if (currentFilters.vendor && !txn.vendor.toLowerCase().includes(currentFilters.vendor.toLowerCase())) {
                return false;
            }

            // Search filter (description)
            if (currentFilters.search && !txn.description.toLowerCase().includes(currentFilters.search.toLowerCase())) {
                return false;
            }

            return true;
        });
    }

    /**
     * Render the transactions table
     */
    function renderTable() {
        tableBody.innerHTML = '';

        filteredTransactions.forEach((txn, index) => {
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
        currentFilters.category = 'Uncategorized';
        document.getElementById('edit-category-filter').value = 'Uncategorized';
        applyFilters();
        renderTable();
        updateCounts();
    }

    /**
     * Clear all filters
     */
    function clearAllFilters() {
        currentFilters = {
            category: 'All',
            project: 'All',
            vendor: '',
            search: ''
        };

        document.getElementById('edit-category-filter').value = 'All';
        document.getElementById('edit-project-filter').value = 'All';
        document.getElementById('edit-vendor-filter').value = '';
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
        document.getElementById('edit-category-filter').addEventListener('change', (e) => {
            currentFilters.category = e.target.value;
            applyFilters();
            renderTable();
            updateCounts();
        });

        document.getElementById('edit-project-filter').addEventListener('change', (e) => {
            currentFilters.project = e.target.value;
            applyFilters();
            renderTable();
            updateCounts();
        });

        document.getElementById('edit-vendor-filter').addEventListener('input', (e) => {
            currentFilters.vendor = e.target.value;
            applyFilters();
            renderTable();
            updateCounts();
        });

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

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', init);

})();
