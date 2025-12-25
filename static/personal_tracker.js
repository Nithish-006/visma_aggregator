// ============================================================================
// PERSONAL TRACKER FUNCTIONALITY
// ============================================================================

(function() {
    'use strict';

    // State
    let transactions = [];
    let projects = [];
    let deleteTargetId = null;

    // DOM Elements
    const elements = {
        // Summary
        totalSpent: document.getElementById('total-spent'),
        thisMonth: document.getElementById('this-month'),
        transactionCount: document.getElementById('transaction-count'),

        // Panels
        projectBreakdown: document.getElementById('project-breakdown'),
        recentTransactions: document.getElementById('recent-transactions'),
        transactionsTbody: document.getElementById('transactions-tbody'),

        // Filters
        projectFilter: document.getElementById('project-filter'),
        searchFilter: document.getElementById('search-filter'),

        // Modal
        expenseModal: document.getElementById('expense-modal'),
        modalTitle: document.getElementById('modal-title'),
        modalClose: document.getElementById('modal-close'),
        expenseForm: document.getElementById('expense-form'),
        expenseId: document.getElementById('expense-id'),
        expenseDate: document.getElementById('expense-date'),
        expenseAmount: document.getElementById('expense-amount'),
        expenseVendor: document.getElementById('expense-vendor'),
        expenseDescription: document.getElementById('expense-description'),
        expenseProject: document.getElementById('expense-project'),
        projectList: document.getElementById('project-list'),
        cancelBtn: document.getElementById('cancel-btn'),
        saveBtn: document.getElementById('save-btn'),
        addExpenseBtn: document.getElementById('add-expense-btn'),

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
        // Add expense button
        elements.addExpenseBtn.addEventListener('click', openAddModal);

        // Modal close buttons
        elements.modalClose.addEventListener('click', closeModal);
        elements.cancelBtn.addEventListener('click', closeModal);
        elements.expenseModal.addEventListener('click', (e) => {
            if (e.target === elements.expenseModal) closeModal();
        });

        // Form submit
        elements.expenseForm.addEventListener('submit', handleFormSubmit);

        // Delete modal
        elements.deleteModalClose.addEventListener('click', closeDeleteModal);
        elements.deleteCancelBtn.addEventListener('click', closeDeleteModal);
        elements.deleteConfirmBtn.addEventListener('click', confirmDelete);
        elements.deleteModal.addEventListener('click', (e) => {
            if (e.target === elements.deleteModal) closeDeleteModal();
        });

        // Filters
        elements.projectFilter.addEventListener('change', applyFilters);
        elements.searchFilter.addEventListener('input', debounce(applyFilters, 300));
    }

    function setDefaultDate() {
        const today = new Date().toISOString().split('T')[0];
        elements.expenseDate.value = today;
    }

    // ============================================================================
    // DATA LOADING
    // ============================================================================

    async function loadData() {
        await Promise.all([
            loadSummary(),
            loadProjects(),
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

            elements.totalSpent.textContent = data.total_spent_formatted || '₹0';
            elements.thisMonth.textContent = data.this_month_formatted || '₹0';
            elements.transactionCount.textContent = data.transaction_count || '0';

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
            updateProjectDatalist();
        } catch (error) {
            console.error('Error loading projects:', error);
            projects = ['General'];
        }
    }

    async function loadTransactions() {
        try {
            const project = elements.projectFilter.value;
            const search = elements.searchFilter.value;

            let url = '/api/personal/transactions?';
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
            html += `
                <div class="recent-item">
                    <div class="recent-info">
                        <span class="recent-vendor">${escapeHtml(t.vendor)}</span>
                        <span class="recent-date">${t.date_formatted}</span>
                    </div>
                    <span class="recent-amount">${t.amount_formatted}</span>
                </div>
            `;
        });

        elements.recentTransactions.innerHTML = html;
    }

    function renderTransactions() {
        if (transactions.length === 0) {
            elements.transactionsTbody.innerHTML = `
                <tr>
                    <td colspan="6" class="empty-state">
                        <p>No transactions found</p>
                        <p style="font-size: 0.8rem;">Click "Add Expense" to add your first transaction</p>
                    </td>
                </tr>
            `;
            return;
        }

        let html = '';
        transactions.forEach(t => {
            html += `
                <tr data-id="${t.id}">
                    <td>${t.date_formatted}</td>
                    <td>${escapeHtml(t.vendor)}</td>
                    <td>${escapeHtml(t.description) || '-'}</td>
                    <td><span class="project-tag">${escapeHtml(t.project)}</span></td>
                    <td class="text-right amount-cell">${t.amount_formatted}</td>
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

        elements.transactionsTbody.innerHTML = html;
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

    function updateProjectDatalist() {
        let html = '';
        projects.forEach(p => {
            html += `<option value="${escapeHtml(p)}">`;
        });
        elements.projectList.innerHTML = html;
    }

    // ============================================================================
    // MODAL HANDLING
    // ============================================================================

    function openAddModal() {
        elements.modalTitle.textContent = 'Add Expense';
        elements.saveBtn.textContent = 'Save Expense';
        elements.expenseId.value = '';
        elements.expenseForm.reset();
        setDefaultDate();
        elements.expenseModal.classList.add('show');
        elements.expenseVendor.focus();
    }

    function openEditModal(transaction) {
        elements.modalTitle.textContent = 'Edit Expense';
        elements.saveBtn.textContent = 'Update Expense';
        elements.expenseId.value = transaction.id;
        elements.expenseDate.value = transaction.date;
        elements.expenseAmount.value = transaction.amount;
        elements.expenseVendor.value = transaction.vendor;
        elements.expenseDescription.value = transaction.description || '';
        elements.expenseProject.value = transaction.project || 'General';
        elements.expenseModal.classList.add('show');
        elements.expenseVendor.focus();
    }

    function closeModal() {
        elements.expenseModal.classList.remove('show');
        elements.expenseForm.reset();
    }

    function openDeleteModal(transaction) {
        deleteTargetId = transaction.id;
        elements.deleteInfo.textContent = `${transaction.vendor} - ${transaction.amount_formatted} on ${transaction.date_formatted}`;
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

        const id = elements.expenseId.value;
        const data = {
            date: elements.expenseDate.value,
            amount: parseFloat(elements.expenseAmount.value),
            vendor: elements.expenseVendor.value.trim(),
            description: elements.expenseDescription.value.trim(),
            project: elements.expenseProject.value.trim() || 'General'
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
            elements.saveBtn.textContent = id ? 'Update Expense' : 'Save Expense';
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
