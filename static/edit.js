/**
 * Edit Transaction Functionality
 * Handles inline editing of transactions with modal UI
 */

(function() {
    'use strict';

    // Get modal and form elements
    const editModal = document.getElementById('edit-modal');
    const editForm = document.getElementById('edit-form');
    const closeBtn = editModal.querySelector('.modal-close');
    const cancelBtn = document.getElementById('edit-cancel-btn');
    const saveBtn = document.getElementById('edit-save-btn');
    const alertBox = document.getElementById('edit-alert');

    // Form fields
    const fields = {
        category: document.getElementById('edit-category'),
        vendor: document.getElementById('edit-vendor'),
        project: document.getElementById('edit-project'),
        dd: document.getElementById('edit-dd'),
        notes: document.getElementById('edit-notes'),
        // Read-only fields for transaction identification
        date: document.getElementById('edit-date'),
        description: document.getElementById('edit-description'),
        debit: document.getElementById('edit-debit'),
        credit: document.getElementById('edit-credit')
    };

    // Store current transaction data for API call
    let currentTransaction = null;

    /**
     * Open edit modal with transaction data
     * @param {Object} transaction - Transaction object with all fields
     */
    window.openEditModal = function(transaction) {
        currentTransaction = transaction;

        // Populate read-only fields
        fields.date.value = transaction.date_display || transaction.Date || '';
        fields.description.value = transaction['Transaction Description'] || '';
        fields.debit.value = transaction['DR Amount'] || '0.00';
        fields.credit.value = transaction['CR Amount'] || '0.00';

        // Populate editable fields
        fields.category.value = transaction.Category || '';
        fields.vendor.value = transaction['Client/Vendor'] || '';
        fields.project.value = transaction.Project || '';
        fields.dd.value = transaction.DD || '';
        fields.notes.value = transaction.Notes || '';

        // Hide alert
        hideAlert();

        // Show modal
        editModal.classList.add('show');
    };

    /**
     * Close edit modal
     */
    function closeEditModal() {
        editModal.classList.remove('show');
        currentTransaction = null;
        editForm.reset();
        hideAlert();
    }

    /**
     * Show alert message
     * @param {string} message - Alert message
     * @param {string} type - 'success' or 'error'
     */
    function showAlert(message, type) {
        alertBox.textContent = message;
        alertBox.className = `alert alert-${type}`;
    }

    /**
     * Hide alert message
     */
    function hideAlert() {
        alertBox.className = 'alert alert-hidden';
    }

    /**
     * Save transaction changes
     */
    async function saveTransaction() {
        if (!currentTransaction) return;

        // Disable save button
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';

        // Prepare update data
        const updateData = {
            // Transaction identification (using original raw date)
            date: currentTransaction.date_raw || currentTransaction.Date,
            description: currentTransaction['Transaction Description'],
            debit: parseFloat(currentTransaction['DR Amount']),
            credit: parseFloat(currentTransaction['CR Amount']),

            // Updated fields
            category: fields.category.value.trim(),
            vendor: fields.vendor.value.trim(),
            project: fields.project.value.trim() || null,
            dd: fields.dd.value.trim() || null,
            notes: fields.notes.value.trim() || null
        };

        try {
            const response = await fetch('/api/transaction/update', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(updateData)
            });

            const result = await response.json();

            if (response.ok && result.success) {
                // Show success message
                showAlert('Transaction updated successfully!', 'success');

                // Wait a moment, then close and reload
                setTimeout(() => {
                    closeEditModal();
                    // Reload dashboard data
                    if (typeof loadDashboardData === 'function') {
                        loadDashboardData();
                    } else {
                        // Fallback: reload page
                        window.location.reload();
                    }
                }, 1000);
            } else {
                // Show error message
                showAlert(result.message || 'Failed to update transaction', 'error');
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save Changes';
            }
        } catch (error) {
            console.error('Error updating transaction:', error);
            showAlert('An error occurred while updating the transaction', 'error');
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save Changes';
        }
    }

    /**
     * Category change handler - update broader_category based on category
     */
    function handleCategoryChange() {
        const category = fields.category.value;
        // The broader_category is set to match category value
        // This will be sent to the backend
    }

    // Event Listeners
    closeBtn.addEventListener('click', closeEditModal);
    cancelBtn.addEventListener('click', closeEditModal);
    saveBtn.addEventListener('click', saveTransaction);
    fields.category.addEventListener('change', handleCategoryChange);

    // Close modal when clicking outside
    editModal.addEventListener('click', function(e) {
        if (e.target === editModal) {
            closeEditModal();
        }
    });

    // Prevent form submission on Enter key
    editForm.addEventListener('submit', function(e) {
        e.preventDefault();
    });

    // Close modal on Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && editModal.classList.contains('show')) {
            closeEditModal();
        }
    });

})();
