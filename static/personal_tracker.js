// ============================================================================
// PERSONAL TRACKER FUNCTIONALITY
// ============================================================================

(function() {
    'use strict';

    // State
    let transactions = [];
    let projects = [];
    let vendors = [];
    let deleteTargetId = null;

    // DOM Elements
    const elements = {
        // Summary
        totalIncome: document.getElementById('total-income'),
        totalExpense: document.getElementById('total-expense'),
        transactionCount: document.getElementById('transaction-count'),
        thisMonthIncome: document.getElementById('this-month-income'),
        thisMonthExpense: document.getElementById('this-month-expense'),

        // Panels
        projectBreakdown: document.getElementById('project-breakdown'),
        recentTransactions: document.getElementById('recent-transactions'),
        transactionsTbody: document.getElementById('transactions-tbody'),
        transactionCards: document.getElementById('transaction-cards'),

        // FAB (Mobile)
        fabAdd: document.getElementById('fab-add'),

        // Filters
        typeFilter: document.getElementById('type-filter'),
        projectFilter: document.getElementById('project-filter'),
        searchFilter: document.getElementById('search-filter'),

        // Modal
        transactionModal: document.getElementById('transaction-modal'),
        modalTitle: document.getElementById('modal-title'),
        modalClose: document.getElementById('modal-close'),
        transactionForm: document.getElementById('transaction-form'),
        transactionId: document.getElementById('transaction-id'),
        transactionType: document.getElementById('transaction-type'),
        transactionDate: document.getElementById('transaction-date'),
        transactionAmount: document.getElementById('transaction-amount'),
        transactionVendor: document.getElementById('transaction-vendor'),
        transactionDescription: document.getElementById('transaction-description'),
        transactionProject: document.getElementById('transaction-project'),
        cancelBtn: document.getElementById('cancel-btn'),
        saveBtn: document.getElementById('save-btn'),
        addTransactionBtn: document.getElementById('add-transaction-btn'),
        typeExpenseBtn: document.getElementById('type-expense-btn'),
        typeIncomeBtn: document.getElementById('type-income-btn'),

        // Dropdowns
        vendorDropdown: document.getElementById('vendor-dropdown'),
        vendorMenu: document.getElementById('vendor-menu'),
        vendorItems: document.getElementById('vendor-items'),
        projectDropdown: document.getElementById('project-dropdown'),
        projectMenu: document.getElementById('project-menu'),
        projectItems: document.getElementById('project-items'),

        // Delete Modal
        deleteModal: document.getElementById('delete-modal'),
        deleteModalClose: document.getElementById('delete-modal-close'),
        deleteInfo: document.getElementById('delete-info'),
        deleteCancelBtn: document.getElementById('delete-cancel-btn'),
        deleteConfirmBtn: document.getElementById('delete-confirm-btn'),

        // Toast
        toast: document.getElementById('toast'),
        toastMessage: document.getElementById('toast-message')
    };

    // ============================================================================
    // INITIALIZATION
    // ============================================================================

    function init() {
        setupEventListeners();
        setDefaultDate();
        loadData();
    }

    function setupEventListeners() {
        // Add transaction button (header - desktop)
        elements.addTransactionBtn.addEventListener('click', openAddModal);

        // FAB button (mobile)
        if (elements.fabAdd) {
            elements.fabAdd.addEventListener('click', openAddModal);
        }

        // Modal close buttons
        elements.modalClose.addEventListener('click', closeModal);
        elements.cancelBtn.addEventListener('click', closeModal);
        elements.transactionModal.addEventListener('click', (e) => {
            if (e.target === elements.transactionModal) closeModal();
        });

        // Transaction type toggle
        elements.typeExpenseBtn.addEventListener('click', () => setTransactionType('expense'));
        elements.typeIncomeBtn.addEventListener('click', () => setTransactionType('income'));

        // Form submit
        elements.transactionForm.addEventListener('submit', handleFormSubmit);

        // Delete modal
        elements.deleteModalClose.addEventListener('click', closeDeleteModal);
        elements.deleteCancelBtn.addEventListener('click', closeDeleteModal);
        elements.deleteConfirmBtn.addEventListener('click', confirmDelete);
        elements.deleteModal.addEventListener('click', (e) => {
            if (e.target === elements.deleteModal) closeDeleteModal();
        });

        // Filters
        elements.typeFilter.addEventListener('change', applyFilters);
        elements.projectFilter.addEventListener('change', applyFilters);
        elements.searchFilter.addEventListener('input', debounce(applyFilters, 300));

        // Setup searchable dropdowns
        setupSearchableDropdown('vendor');
        setupSearchableDropdown('project');

        // Close dropdowns when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#vendor-dropdown')) {
                closeDropdown('vendor');
            }
            if (!e.target.closest('#project-dropdown')) {
                closeDropdown('project');
            }
        });
    }

    // ============================================================================
    // SEARCHABLE DROPDOWN
    // ============================================================================

    let highlightedIndex = { vendor: -1, project: -1 };

    function setupSearchableDropdown(type) {
        const input = type === 'vendor' ? elements.transactionVendor : elements.transactionProject;
        const dropdown = type === 'vendor' ? elements.vendorDropdown : elements.projectDropdown;

        // Click on input to open dropdown
        input.addEventListener('click', () => {
            openDropdown(type);
        });

        // Focus on input to open dropdown
        input.addEventListener('focus', () => {
            openDropdown(type);
        });

        // Filter as user types
        input.addEventListener('input', () => {
            filterDropdownItems(type, input.value);
            if (!dropdown.classList.contains('open')) {
                openDropdown(type);
            }
        });

        // Keyboard navigation
        input.addEventListener('keydown', (e) => {
            const items = getVisibleDropdownItems(type);

            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    if (!dropdown.classList.contains('open')) {
                        openDropdown(type);
                    } else {
                        highlightedIndex[type] = Math.min(highlightedIndex[type] + 1, items.length - 1);
                        updateHighlight(type);
                    }
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    highlightedIndex[type] = Math.max(highlightedIndex[type] - 1, 0);
                    updateHighlight(type);
                    break;
                case 'Enter':
                    e.preventDefault();
                    if (highlightedIndex[type] >= 0 && items[highlightedIndex[type]]) {
                        selectDropdownItem(type, items[highlightedIndex[type]].textContent);
                    }
                    closeDropdown(type);
                    break;
                case 'Escape':
                    closeDropdown(type);
                    break;
                case 'Tab':
                    closeDropdown(type);
                    break;
            }
        });
    }

    function openDropdown(type) {
        const dropdown = type === 'vendor' ? elements.vendorDropdown : elements.projectDropdown;
        const input = type === 'vendor' ? elements.transactionVendor : elements.transactionProject;

        dropdown.classList.add('open');
        filterDropdownItems(type, input.value);
        highlightedIndex[type] = -1;
    }

    function closeDropdown(type) {
        const dropdown = type === 'vendor' ? elements.vendorDropdown : elements.projectDropdown;
        dropdown.classList.remove('open');
        dropdown.classList.remove('no-results');
        highlightedIndex[type] = -1;
    }

    function filterDropdownItems(type, searchTerm) {
        const items = type === 'vendor' ? vendors : projects;
        const container = type === 'vendor' ? elements.vendorItems : elements.projectItems;
        const dropdown = type === 'vendor' ? elements.vendorDropdown : elements.projectDropdown;
        const search = searchTerm.toLowerCase().trim();

        const filtered = items.filter(item =>
            item.toLowerCase().includes(search)
        );

        if (filtered.length === 0 && search === '') {
            // Show all items when empty
            renderDropdownItems(type, items);
            dropdown.classList.remove('no-results');
        } else if (filtered.length === 0) {
            container.innerHTML = '';
            dropdown.classList.add('no-results');
        } else {
            renderDropdownItems(type, filtered);
            dropdown.classList.remove('no-results');
        }

        highlightedIndex[type] = -1;
    }

    function renderDropdownItems(type, items) {
        const container = type === 'vendor' ? elements.vendorItems : elements.projectItems;
        const input = type === 'vendor' ? elements.transactionVendor : elements.transactionProject;
        const currentValue = input.value.trim();

        let html = '';
        items.forEach((item, index) => {
            const isSelected = item.toLowerCase() === currentValue.toLowerCase();
            html += `<div class="dropdown-item${isSelected ? ' selected' : ''}" data-index="${index}" data-value="${escapeHtml(item)}">${escapeHtml(item)}</div>`;
        });

        container.innerHTML = html;

        // Add click handlers
        container.querySelectorAll('.dropdown-item').forEach(el => {
            el.addEventListener('click', () => {
                selectDropdownItem(type, el.dataset.value);
                closeDropdown(type);
            });
        });
    }

    function selectDropdownItem(type, value) {
        const input = type === 'vendor' ? elements.transactionVendor : elements.transactionProject;
        input.value = value;
    }

    function getVisibleDropdownItems(type) {
        const container = type === 'vendor' ? elements.vendorItems : elements.projectItems;
        return container.querySelectorAll('.dropdown-item');
    }

    function updateHighlight(type) {
        const items = getVisibleDropdownItems(type);
        items.forEach((item, index) => {
            item.classList.toggle('highlighted', index === highlightedIndex[type]);
        });

        // Scroll highlighted item into view
        if (highlightedIndex[type] >= 0 && items[highlightedIndex[type]]) {
            items[highlightedIndex[type]].scrollIntoView({ block: 'nearest' });
        }
    }

    function setDefaultDate() {
        const today = new Date().toISOString().split('T')[0];
        elements.transactionDate.value = today;
    }

    function setTransactionType(type) {
        elements.transactionType.value = type;

        if (type === 'expense') {
            elements.typeExpenseBtn.classList.add('active');
            elements.typeIncomeBtn.classList.remove('active');
        } else {
            elements.typeIncomeBtn.classList.add('active');
            elements.typeExpenseBtn.classList.remove('active');
        }
    }

    // ============================================================================
    // DATA LOADING
    // ============================================================================

    async function loadData() {
        await Promise.all([
            loadSummary(),
            loadProjects(),
            loadVendors(),
            loadTransactions()
        ]);
    }

    async function loadSummary() {
        try {
            const response = await fetch('/api/personal/summary');
            const data = await response.json();

            if (data.error) {
                console.error('Error loading summary:', data.error);
                return;
            }

            elements.totalIncome.textContent = data.total_income_formatted || '₹0';
            elements.totalExpense.textContent = data.total_expense_formatted || '₹0';
            elements.transactionCount.textContent = data.transaction_count || '0';
            elements.thisMonthIncome.textContent = data.this_month_income_formatted || '₹0';
            elements.thisMonthExpense.textContent = data.this_month_expense_formatted || '₹0';

            renderProjectBreakdown(data.project_breakdown || []);
        } catch (error) {
            console.error('Error loading summary:', error);
        }
    }

    async function loadProjects() {
        try {
            const response = await fetch('/api/personal/projects');
            const data = await response.json();

            projects = data.projects || ['General'];
            updateProjectFilter();
            updateDropdownItems('project');
        } catch (error) {
            console.error('Error loading projects:', error);
            projects = ['General'];
        }
    }

    async function loadVendors() {
        try {
            const response = await fetch('/api/personal/vendors');
            const data = await response.json();

            vendors = data.vendors || [];
            updateDropdownItems('vendor');
        } catch (error) {
            console.error('Error loading vendors:', error);
            vendors = [];
        }
    }

    async function loadTransactions() {
        try {
            const type = elements.typeFilter.value;
            const project = elements.projectFilter.value;
            const search = elements.searchFilter.value;

            let url = '/api/personal/transactions?';
            if (type && type !== 'All') url += `type=${encodeURIComponent(type)}&`;
            if (project && project !== 'All') url += `project=${encodeURIComponent(project)}&`;
            if (search) url += `search=${encodeURIComponent(search)}&`;

            const response = await fetch(url);
            const data = await response.json();

            if (data.error) {
                console.error('Error loading transactions:', data.error);
                return;
            }

            transactions = data.transactions || [];
            renderTransactions();
            renderRecentTransactions();
        } catch (error) {
            console.error('Error loading transactions:', error);
        }
    }

    // ============================================================================
    // RENDERING
    // ============================================================================

    function renderProjectBreakdown(breakdown) {
        if (!breakdown || breakdown.length === 0) {
            elements.projectBreakdown.innerHTML = `
                <div class="empty-state">
                    <p>No projects yet</p>
                    <p style="font-size: 0.8rem;">Add expenses to see breakdown</p>
                </div>
            `;
            return;
        }

        let html = '';
        breakdown.forEach(item => {
            html += `
                <div class="project-item">
                    <div class="project-info">
                        <span class="project-name">${escapeHtml(item.project)}</span>
                        <span class="project-count">${item.count} transaction${item.count !== 1 ? 's' : ''}</span>
                    </div>
                    <div class="project-stats">
                        <span class="project-amount">${item.amount_formatted}</span>
                        <span class="project-pct">${item.percentage}%</span>
                    </div>
                </div>
                <div class="project-bar">
                    <div class="project-bar-fill" style="width: ${item.percentage}%"></div>
                </div>
            `;
        });

        elements.projectBreakdown.innerHTML = html;
    }

    function renderRecentTransactions() {
        const recent = transactions.slice(0, 5);

        if (recent.length === 0) {
            elements.recentTransactions.innerHTML = `
                <div class="empty-state">
                    <p>No recent transactions</p>
                </div>
            `;
            return;
        }

        let html = '';
        recent.forEach(t => {
            const typeClass = t.transaction_type === 'income' ? 'income' : 'expense';
            // Show + for income, no prefix for expense (just red color indicates expense)
            const prefix = t.transaction_type === 'income' ? '+' : '';
            html += `
                <div class="recent-item">
                    <div class="recent-info">
                        <span class="recent-vendor">${escapeHtml(t.vendor)}</span>
                        <span class="recent-date">${t.date_formatted}</span>
                    </div>
                    <span class="recent-amount ${typeClass}">${prefix}${t.amount_formatted}</span>
                </div>
            `;
        });

        elements.recentTransactions.innerHTML = html;
    }

    function renderTransactions() {
        // Empty state for both views
        if (transactions.length === 0) {
            const emptyHtml = `
                <div class="empty-state">
                    <p>No transactions found</p>
                    <p style="font-size: 0.8rem;">Tap + to add your first entry</p>
                </div>
            `;
            elements.transactionsTbody.innerHTML = `
                <tr>
                    <td colspan="7" class="empty-state">
                        <p>No transactions found</p>
                        <p style="font-size: 0.8rem;">Click "Add Transaction" to add your first entry</p>
                    </td>
                </tr>
            `;
            if (elements.transactionCards) {
                elements.transactionCards.innerHTML = emptyHtml;
            }
            return;
        }

        // Desktop Table View
        let tableHtml = '';
        transactions.forEach(t => {
            const typeClass = t.transaction_type === 'income' ? 'income' : 'expense';
            const typeLabel = t.transaction_type === 'income' ? 'Income' : 'Expense';
            // Show + for income, no prefix for expense (just red color indicates expense)
            const prefix = t.transaction_type === 'income' ? '+' : '';
            tableHtml += `
                <tr data-id="${t.id}">
                    <td>${t.date_formatted}</td>
                    <td><span class="type-tag ${typeClass}">${typeLabel}</span></td>
                    <td>${escapeHtml(t.vendor)}</td>
                    <td>${escapeHtml(t.description) || '-'}</td>
                    <td><span class="project-tag">${escapeHtml(t.project)}</span></td>
                    <td class="text-right amount-cell ${typeClass}">${prefix}${t.amount_formatted}</td>
                    <td class="text-center">
                        <div class="action-btns">
                            <button class="action-btn edit" onclick="editTransaction(${t.id})" title="Edit">
                                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                                </svg>
                            </button>
                            <button class="action-btn delete" onclick="deleteTransaction(${t.id})" title="Delete">
                                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        });
        elements.transactionsTbody.innerHTML = tableHtml;

        // Mobile Card View
        if (elements.transactionCards) {
            let cardsHtml = '';
            transactions.forEach(t => {
                const typeClass = t.transaction_type === 'income' ? 'income' : 'expense';
                const typeLabel = t.transaction_type === 'income' ? 'Income' : 'Expense';
                // Show + for income, no prefix for expense
                const prefix = t.transaction_type === 'income' ? '+' : '';
                const description = t.description ? `<div class="transaction-card-desc">${escapeHtml(t.description)}</div>` : '';

                cardsHtml += `
                    <div class="transaction-card" data-id="${t.id}">
                        <div class="transaction-card-header">
                            <span class="transaction-card-vendor">${escapeHtml(t.vendor)}</span>
                            <span class="transaction-card-amount ${typeClass}">${prefix}${t.amount_formatted}</span>
                        </div>
                        <div class="transaction-card-details">
                            <span class="transaction-card-date">${t.date_formatted}</span>
                            <span class="type-tag ${typeClass}">${typeLabel}</span>
                            <span class="project-tag">${escapeHtml(t.project)}</span>
                        </div>
                        ${description}
                        <div class="transaction-card-actions">
                            <button class="action-btn edit" onclick="editTransaction(${t.id})">
                                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                                </svg>
                                <span>Edit</span>
                            </button>
                            <button class="action-btn delete" onclick="deleteTransaction(${t.id})">
                                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                                <span>Delete</span>
                            </button>
                        </div>
                    </div>
                `;
            });
            elements.transactionCards.innerHTML = cardsHtml;
        }
    }

    function updateProjectFilter() {
        const currentValue = elements.projectFilter.value;
        let html = '<option value="All">All Projects</option>';
        projects.forEach(p => {
            html += `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`;
        });
        elements.projectFilter.innerHTML = html;
        elements.projectFilter.value = currentValue || 'All';
    }

    function updateDropdownItems(type) {
        const items = type === 'vendor' ? vendors : projects;
        renderDropdownItems(type, items);
    }

    // ============================================================================
    // MODAL HANDLING
    // ============================================================================

    function openAddModal() {
        elements.modalTitle.textContent = 'Add Transaction';
        elements.saveBtn.textContent = 'Save Transaction';
        elements.transactionId.value = '';
        elements.transactionForm.reset();
        setDefaultDate();
        setTransactionType('expense');
        closeDropdown('vendor');
        closeDropdown('project');
        updateDropdownItems('vendor');
        updateDropdownItems('project');
        elements.transactionModal.classList.add('show');
        setTimeout(() => elements.transactionVendor.focus(), 100);
    }

    function openEditModal(transaction) {
        elements.modalTitle.textContent = 'Edit Transaction';
        elements.saveBtn.textContent = 'Update Transaction';
        elements.transactionId.value = transaction.id;
        elements.transactionDate.value = transaction.date;
        elements.transactionAmount.value = transaction.amount;
        elements.transactionVendor.value = transaction.vendor;
        elements.transactionDescription.value = transaction.description || '';
        elements.transactionProject.value = transaction.project || 'General';
        setTransactionType(transaction.transaction_type || 'expense');
        closeDropdown('vendor');
        closeDropdown('project');
        updateDropdownItems('vendor');
        updateDropdownItems('project');
        elements.transactionModal.classList.add('show');
        setTimeout(() => elements.transactionVendor.focus(), 100);
    }

    function closeModal() {
        elements.transactionModal.classList.remove('show');
        elements.transactionForm.reset();
        closeDropdown('vendor');
        closeDropdown('project');
    }

    function openDeleteModal(transaction) {
        deleteTargetId = transaction.id;
        const typeLabel = transaction.transaction_type === 'income' ? 'Income' : 'Expense';
        elements.deleteInfo.textContent = `${typeLabel}: ${transaction.vendor} - ${transaction.amount_formatted} on ${transaction.date_formatted}`;
        elements.deleteModal.classList.add('show');
    }

    function closeDeleteModal() {
        elements.deleteModal.classList.remove('show');
        deleteTargetId = null;
    }

    // ============================================================================
    // FORM HANDLING
    // ============================================================================

    async function handleFormSubmit(e) {
        e.preventDefault();

        const id = elements.transactionId.value;
        const data = {
            date: elements.transactionDate.value,
            amount: parseFloat(elements.transactionAmount.value),
            vendor: elements.transactionVendor.value.trim(),
            description: elements.transactionDescription.value.trim(),
            project: elements.transactionProject.value.trim() || 'General',
            transaction_type: elements.transactionType.value
        };

        if (!data.date || !data.vendor || !data.amount) {
            showToast('Please fill in all required fields', 'error');
            return;
        }

        try {
            elements.saveBtn.disabled = true;
            elements.saveBtn.textContent = 'Saving...';

            let response;
            if (id) {
                // Update
                response = await fetch(`/api/personal/transactions/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
            } else {
                // Create
                response = await fetch('/api/personal/transactions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
            }

            const result = await response.json();

            if (result.success) {
                showToast(id ? 'Transaction updated!' : 'Transaction added!', 'success');
                closeModal();
                loadData();
            } else {
                showToast(result.error || 'Failed to save transaction', 'error');
            }
        } catch (error) {
            console.error('Error saving transaction:', error);
            showToast('Failed to save transaction', 'error');
        } finally {
            elements.saveBtn.disabled = false;
            elements.saveBtn.textContent = id ? 'Update Transaction' : 'Save Transaction';
        }
    }

    async function confirmDelete() {
        if (!deleteTargetId) return;

        try {
            elements.deleteConfirmBtn.disabled = true;
            elements.deleteConfirmBtn.textContent = 'Deleting...';

            const response = await fetch(`/api/personal/transactions/${deleteTargetId}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.success) {
                showToast('Transaction deleted!', 'success');
                closeDeleteModal();
                loadData();
            } else {
                showToast(result.error || 'Failed to delete transaction', 'error');
            }
        } catch (error) {
            console.error('Error deleting transaction:', error);
            showToast('Failed to delete transaction', 'error');
        } finally {
            elements.deleteConfirmBtn.disabled = false;
            elements.deleteConfirmBtn.textContent = 'Delete';
        }
    }

    // ============================================================================
    // FILTERS
    // ============================================================================

    function applyFilters() {
        loadTransactions();
    }

    // ============================================================================
    // UTILITIES
    // ============================================================================

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    function showToast(message, type = 'success') {
        elements.toastMessage.textContent = message;
        elements.toast.className = 'toast show ' + type;

        setTimeout(() => {
            elements.toast.classList.remove('show');
        }, 3000);
    }

    // ============================================================================
    // GLOBAL FUNCTIONS (for onclick handlers)
    // ============================================================================

    window.editTransaction = function(id) {
        const transaction = transactions.find(t => t.id === id);
        if (transaction) {
            openEditModal(transaction);
        }
    };

    window.deleteTransaction = function(id) {
        const transaction = transactions.find(t => t.id === id);
        if (transaction) {
            openDeleteModal(transaction);
        }
    };

    // ============================================================================
    // START
    // ============================================================================

    document.addEventListener('DOMContentLoaded', init);
})();
