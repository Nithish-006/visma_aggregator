/**
 * Expense Form - Dedicated Page JavaScript
 * Handles add/edit transaction functionality
 */

// ============================================================================
// STATE
// ============================================================================

let vendors = [];
let descriptions = [];
let projects = [];

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    initializeForm();
    loadDropdownData();
    setupEventListeners();
});

function initializeForm() {
    // Set default date to today if not editing
    const dateInput = document.getElementById('transaction-date');
    const transactionId = document.getElementById('transaction-id').value;

    if (!transactionId && !dateInput.value) {
        dateInput.value = new Date().toISOString().split('T')[0];
    }

    // Focus on amount field for new transactions
    if (!transactionId) {
        setTimeout(() => {
            document.getElementById('transaction-amount').focus();
        }, 100);
    }
}

async function loadDropdownData() {
    try {
        const [vendorsRes, descriptionsRes, projectsRes] = await Promise.all([
            fetch('/api/personal/vendors'),
            fetch('/api/personal/descriptions'),
            fetch('/api/personal/projects')
        ]);

        const vendorsData = await vendorsRes.json();
        const descriptionsData = await descriptionsRes.json();
        const projectsData = await projectsRes.json();

        vendors = vendorsData.vendors || [];
        descriptions = descriptionsData.descriptions || [];
        projects = projectsData.projects || [];

        // Initial render of pills (hidden until input focus)
        renderPills('vendor', vendors);
        renderPills('description', descriptions);
        renderPills('project', projects);
    } catch (error) {
        console.error('Error loading dropdown data:', error);
    }
}

// ============================================================================
// EVENT LISTENERS
// ============================================================================

function setupEventListeners() {
    // Type toggle buttons
    document.querySelectorAll('.type-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('transaction-type').value = btn.dataset.type;
        });
    });

    // Bank toggle buttons
    document.querySelectorAll('.bank-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const wasActive = btn.classList.contains('active');
            document.querySelectorAll('.bank-btn').forEach(b => b.classList.remove('active'));

            if (!wasActive) {
                btn.classList.add('active');
                document.getElementById('transaction-bank').value = btn.dataset.bank;
            } else {
                // Clicking active bank deselects it
                document.getElementById('transaction-bank').value = '';
            }
        });
    });

    // Dropdown inputs - pass getter functions to get current data
    setupDropdownInput('vendor', () => vendors);
    setupDropdownInput('description', () => descriptions);
    setupDropdownInput('project', () => projects);

    // Form submission
    document.getElementById('expense-form').addEventListener('submit', handleFormSubmit);

    // Delete button (if exists)
    const deleteBtn = document.getElementById('delete-btn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', openDeleteModal);
    }

    // Delete modal buttons
    const deleteCancelBtn = document.getElementById('delete-cancel-btn');
    const deleteConfirmBtn = document.getElementById('delete-confirm-btn');

    if (deleteCancelBtn) {
        deleteCancelBtn.addEventListener('click', closeDeleteModal);
    }
    if (deleteConfirmBtn) {
        deleteConfirmBtn.addEventListener('click', confirmDelete);
    }

    // Close modal on backdrop click
    const modal = document.getElementById('delete-modal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeDeleteModal();
            }
        });
    }
}

function setupDropdownInput(name, getItems) {
    const input = document.getElementById(`transaction-${name}`);
    const pillsContainer = document.getElementById(`${name}-pills`);

    if (!input || !pillsContainer) return;

    let justSelected = false;

    input.addEventListener('focus', () => {
        if (!justSelected) {
            filterAndShowPills(name, getItems(), input.value);
        }
        justSelected = false;
    });

    input.addEventListener('input', () => {
        filterAndShowPills(name, getItems(), input.value);
    });

    input.addEventListener('blur', () => {
        // Delay hiding to allow pill click
        setTimeout(() => {
            pillsContainer.classList.remove('show');
        }, 200);
    });
}

// ============================================================================
// PILLS RENDERING
// ============================================================================

function renderPills(name, items) {
    const container = document.getElementById(`${name}-pills`);
    if (!container) return;

    container.innerHTML = items.slice(0, 10).map(item =>
        `<span class="dropdown-pill" data-value="${escapeHtml(item)}">${escapeHtml(item)}</span>`
    ).join('');

    // Add click handlers
    container.querySelectorAll('.dropdown-pill').forEach(pill => {
        pill.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const input = document.getElementById(`transaction-${name}`);
            input.value = pill.dataset.value;
            container.classList.remove('show');
        });
    });
}

function filterAndShowPills(name, items, filter) {
    const container = document.getElementById(`${name}-pills`);
    if (!container) return;

    const filtered = filter
        ? items.filter(item => item.toLowerCase().includes(filter.toLowerCase()))
        : items;

    if (filtered.length > 0) {
        renderPills(name, filtered);
        container.classList.add('show');
    } else {
        container.classList.remove('show');
    }
}

// ============================================================================
// FORM SUBMISSION
// ============================================================================

async function handleFormSubmit(e) {
    e.preventDefault();

    const transactionId = document.getElementById('transaction-id').value;
    const date = document.getElementById('transaction-date').value;
    const amount = document.getElementById('transaction-amount').value;
    const vendor = document.getElementById('transaction-vendor').value.trim();
    const description = document.getElementById('transaction-description').value.trim();
    const project = document.getElementById('transaction-project').value.trim() || 'General';
    const transactionType = document.getElementById('transaction-type').value;
    const bank = document.getElementById('transaction-bank').value || null;

    // Validation
    if (!date || !amount || !vendor) {
        showToast('Please fill in all required fields', 'error');
        return;
    }

    const saveBtn = document.getElementById('save-btn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="spin">
            <line x1="12" y1="2" x2="12" y2="6"></line>
            <line x1="12" y1="18" x2="12" y2="22"></line>
            <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
            <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
            <line x1="2" y1="12" x2="6" y2="12"></line>
            <line x1="18" y1="12" x2="22" y2="12"></line>
            <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
            <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
        </svg>
        Saving...
    `;

    const data = {
        date,
        amount: parseFloat(amount),
        vendor,
        description,
        project,
        transaction_type: transactionType,
        bank
    };

    const url = transactionId
        ? `/api/personal/transactions/${transactionId}`
        : '/api/personal/transactions';
    const method = transactionId ? 'PUT' : 'POST';

    try {
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showToast('Transaction saved successfully', 'success');
            setTimeout(() => {
                window.location.href = '/personal-tracker';
            }, 500);
        } else {
            showToast(result.error || 'Failed to save transaction', 'error');
            resetSaveButton();
        }
    } catch (error) {
        console.error('Error saving transaction:', error);
        showToast('Failed to save transaction', 'error');
        resetSaveButton();
    }
}

function resetSaveButton() {
    const saveBtn = document.getElementById('save-btn');
    saveBtn.disabled = false;
    saveBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        Save Transaction
    `;
}

// ============================================================================
// DELETE FUNCTIONALITY
// ============================================================================

function openDeleteModal() {
    const vendor = document.getElementById('transaction-vendor').value;
    const amount = document.getElementById('transaction-amount').value;

    document.getElementById('delete-details').textContent =
        `${vendor} - ₹${parseFloat(amount).toLocaleString('en-IN')}`;

    document.getElementById('delete-modal').classList.add('show');
}

function closeDeleteModal() {
    document.getElementById('delete-modal').classList.remove('show');
}

async function confirmDelete() {
    const transactionId = document.getElementById('transaction-id').value;
    if (!transactionId) return;

    const confirmBtn = document.getElementById('delete-confirm-btn');
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Deleting...';

    try {
        const response = await fetch(`/api/personal/transactions/${transactionId}`, {
            method: 'DELETE'
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showToast('Transaction deleted', 'success');
            setTimeout(() => {
                window.location.href = '/personal-tracker';
            }, 500);
        } else {
            showToast(result.error || 'Failed to delete transaction', 'error');
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Delete';
        }
    } catch (error) {
        console.error('Error deleting transaction:', error);
        showToast('Failed to delete transaction', 'error');
        confirmBtn.disabled = false;
        confirmBtn.textContent = 'Delete';
    }
}

// ============================================================================
// TOAST NOTIFICATION
// ============================================================================

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toast-message');

    toast.className = 'toast';
    toastMessage.textContent = message;
    toast.classList.add(type, 'show');

    setTimeout(() => {
        toast.classList.remove('show');
    }, 2500);
}

// ============================================================================
// UTILITIES
// ============================================================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
