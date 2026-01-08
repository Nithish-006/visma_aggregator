/* ============================================================================
   BILL PROCESSOR - FRONTEND JAVASCRIPT
   ============================================================================ */

// State
let storedBills = [];
let allProjects = [];
let currentProjectFilter = '';
let fileQueue = [];
let processedResults = [];
let rawResults = [];
let activeProjectEdit = null;

// Edit Modal State
let currentEditBill = null;
let editLineItems = [];
let pdfDoc = null;
let currentPdfPage = 1;
let totalPdfPages = 1;
let currentZoom = 1;

// DOM Elements
const uploadModal = document.getElementById('uploadModal');
const detailModal = document.getElementById('detailModal');
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const fileQueueEl = document.getElementById('fileQueue');
const queueList = document.getElementById('queueList');
const clearQueueBtn = document.getElementById('clearQueue');
const processBtn = document.getElementById('processBtn');
const toast = document.getElementById('toast');

// Initialize
document.addEventListener('DOMContentLoaded', init);
console.log('[Bill Processor] JavaScript loaded successfully');

function init() {
    // Load data on page load
    loadProjects();
    loadSummary();
    loadStoredBills();

    // Project filter
    document.getElementById('projectFilter').addEventListener('change', handleProjectFilterChange);

    // Header buttons
    document.getElementById('newBillBtn').addEventListener('click', openUploadModal);
    document.getElementById('refreshBtn').addEventListener('click', refreshData);
    document.getElementById('exportAllBtn').addEventListener('click', exportAllBills);

    // Event delegation for project cell clicks
    document.getElementById('invoicesBody').addEventListener('click', handleTableClick);

    // Close project edit on outside click
    document.addEventListener('click', handleOutsideClick);

    // Upload modal events
    document.getElementById('closeUploadModal').addEventListener('click', closeUploadModal);
    document.getElementById('cancelUpload').addEventListener('click', closeUploadModal);
    uploadArea.addEventListener('click', () => fileInput.click());
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleDrop);
    fileInput.addEventListener('change', handleFileSelect);
    clearQueueBtn.addEventListener('click', clearQueue);
    processBtn.addEventListener('click', processFiles);

    // Detail modal events
    document.getElementById('closeDetailModal').addEventListener('click', closeDetailModal);
    detailModal.addEventListener('click', (e) => {
        if (e.target === detailModal) closeDetailModal();
    });

    // Close modals on escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeUploadModal();
            closeDetailModal();
            closeEditModal();
        }
    });

    // Edit modal events
    const editModal = document.getElementById('editModal');
    document.getElementById('closeEditModal').addEventListener('click', closeEditModal);
    document.getElementById('cancelEditBtn').addEventListener('click', closeEditModal);
    document.getElementById('saveEditBtn').addEventListener('click', saveEditChanges);
    document.getElementById('addLineItemBtn').addEventListener('click', addLineItem);
    editModal.addEventListener('click', (e) => {
        if (e.target === editModal) closeEditModal();
    });

    // Document viewer controls
    document.getElementById('zoomInBtn').addEventListener('click', () => adjustZoom(0.25));
    document.getElementById('zoomOutBtn').addEventListener('click', () => adjustZoom(-0.25));
    document.getElementById('zoomResetBtn').addEventListener('click', resetZoom);
    document.getElementById('prevPageBtn').addEventListener('click', () => changePdfPage(-1));
    document.getElementById('nextPageBtn').addEventListener('click', () => changePdfPage(1));

    // Close upload modal when clicking outside
    uploadModal.addEventListener('click', (e) => {
        if (e.target === uploadModal) closeUploadModal();
    });
}

// ============================================================================
// DATA LOADING
// ============================================================================

async function loadProjects() {
    try {
        const response = await fetch('/api/bills/projects');
        const data = await response.json();

        if (data.success) {
            allProjects = data.projects;
            populateProjectFilter();
        }
    } catch (error) {
        console.error('Error loading projects:', error);
    }
}

function populateProjectFilter() {
    const select = document.getElementById('projectFilter');
    const currentValue = select.value;

    // Keep "All Projects" option and add projects
    select.innerHTML = '<option value="">All Projects</option>';
    allProjects.forEach(project => {
        const option = document.createElement('option');
        option.value = project;
        option.textContent = project;
        if (project === currentValue) option.selected = true;
        select.appendChild(option);
    });
}

function handleProjectFilterChange(e) {
    currentProjectFilter = e.target.value;
    loadSummary();
    loadStoredBills();
}

function handleOutsideClick(e) {
    if (activeProjectEdit && !e.target.closest('.project-cell')) {
        closeProjectEdit();
    }
}

function handleTableClick(e) {
    // Handle project cell clicks
    const projectDisplay = e.target.closest('.project-display');
    if (projectDisplay) {
        const cell = projectDisplay.closest('.project-cell');
        if (cell) {
            const billId = parseInt(cell.dataset.billId);
            const project = cell.dataset.project || '';
            console.log('[Bill Processor] Project cell clicked:', billId, project);
            openProjectEdit(billId, project);
            e.stopPropagation();
            return;
        }
    }

    // Handle suggestion clicks
    const suggestion = e.target.closest('.project-suggestion');
    if (suggestion) {
        e.stopPropagation();
        return;
    }
}

async function loadSummary() {
    try {
        let url = '/api/bills/summary';
        if (currentProjectFilter) {
            url += `?project=${encodeURIComponent(currentProjectFilter)}`;
        }

        const response = await fetch(url);
        const data = await response.json();

        if (data.success) {
            document.getElementById('statTotalInvoices').textContent = data.summary.total_invoices;
            document.getElementById('statTotalValue').textContent = formatIndianCurrency(data.summary.total_value);
            document.getElementById('statTotalGST').textContent = formatIndianCurrency(data.summary.total_gst);
            document.getElementById('statUniqueVendors').textContent = data.summary.unique_vendors;
        }
    } catch (error) {
        console.error('Error loading summary:', error);
    }
}

async function loadStoredBills() {
    try {
        let url = '/api/bills/stored?limit=500';
        if (currentProjectFilter) {
            url += `&project=${encodeURIComponent(currentProjectFilter)}`;
        }

        const response = await fetch(url);
        const data = await response.json();

        if (data.success) {
            storedBills = data.bills;
            renderInvoicesTable();
        } else {
            showEmptyState('invoices');
        }
    } catch (error) {
        console.error('Error loading bills:', error);
        showEmptyState('invoices');
    }
}

function refreshData() {
    loadProjects();
    loadSummary();
    loadStoredBills();
    showToast('Data refreshed', 'success');
}

// ============================================================================
// RENDER TABLES
// ============================================================================

function renderInvoicesTable() {
    const tbody = document.getElementById('invoicesBody');
    const emptyState = document.getElementById('invoicesEmpty');
    const tableContainer = document.querySelector('#invoicesTab .table-container');

    if (storedBills.length === 0) {
        tableContainer.style.display = 'none';
        emptyState.style.display = 'flex';
        return;
    }

    tableContainer.style.display = 'block';
    emptyState.style.display = 'none';

    tbody.innerHTML = storedBills.map(bill => {
        const gst = (parseFloat(bill.total_cgst) || 0) + (parseFloat(bill.total_sgst) || 0) + (parseFloat(bill.total_igst) || 0);
        const projectDisplay = bill.project || '';
        const projectClass = projectDisplay ? '' : 'empty';
        const projectText = projectDisplay || 'Click to add';

        return `
            <tr>
                <td class="cell-link" onclick="viewInvoiceDetail(${bill.id})">${bill.invoice_number || '-'}</td>
                <td>${bill.invoice_date || '-'}</td>
                <td class="cell-wrap">${bill.vendor_name || '-'}</td>
                <td>${bill.vendor_gstin || '-'}</td>
                <td class="cell-wrap">${bill.buyer_name || '-'}</td>
                <td>${bill.line_item_count || 0}</td>
                <td class="text-right">${formatIndianCurrency(bill.subtotal)}</td>
                <td class="text-right">${formatIndianCurrency(gst)}</td>
                <td class="text-right cell-amount">${formatIndianCurrency(bill.total_amount)}</td>
                <td class="project-cell" data-bill-id="${bill.id}" data-project="${escapeForAttr(projectDisplay)}">
                    <div class="project-display">
                        <span class="project-text ${projectClass}">${escapeHtml(projectText)}</span>
                        <svg class="edit-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                        </svg>
                    </div>
                </td>
                <td>
                    <div class="action-buttons">
                        <button class="btn-icon" onclick="viewInvoiceDetail(${bill.id})" title="View Details">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                                <circle cx="12" cy="12" r="3"></circle>
                            </svg>
                        </button>
                        <button class="btn-icon btn-edit" onclick="openEditModal(${bill.id})" title="Edit Invoice">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                            </svg>
                        </button>
                        <button class="btn-icon btn-danger" onclick="deleteInvoice(${bill.id})" title="Delete">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function showEmptyState() {
    document.querySelector('#invoicesTab .table-container').style.display = 'none';
    document.getElementById('invoicesEmpty').style.display = 'flex';
}

// ============================================================================
// PROJECT EDITING
// ============================================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeForAttr(text) {
    if (!text) return '';
    return text.replace(/\\/g, '\\\\')
               .replace(/'/g, "\\'")
               .replace(/"/g, '&quot;')
               .replace(/\n/g, '\\n')
               .replace(/\r/g, '\\r');
}

function openProjectEdit(billId, currentProject) {
    console.log('[Bill Processor] openProjectEdit called:', billId, currentProject);
    // Close any existing edit
    closeProjectEdit();

    const cell = document.querySelector(`.project-cell[data-bill-id="${billId}"]`);
    if (!cell) {
        console.log('[Bill Processor] Cell not found for billId:', billId);
        return;
    }

    activeProjectEdit = billId;

    // Create edit container
    const editHtml = `
        <div class="project-edit-container">
            <input type="text" class="project-input" id="projectInput-${billId}"
                   value="${escapeHtml(currentProject)}" placeholder="Enter project name">
            <div class="project-suggestions" id="projectSuggestions-${billId}"></div>
        </div>
    `;

    cell.innerHTML = editHtml;

    const input = document.getElementById(`projectInput-${billId}`);

    // Add event listeners
    input.addEventListener('keydown', (e) => handleProjectKeydown(e, billId));
    input.addEventListener('input', () => filterProjectSuggestions(billId));

    input.focus();
    input.select();

    // Show suggestions
    filterProjectSuggestions(billId);
}

function closeProjectEdit() {
    if (!activeProjectEdit) return;

    const cell = document.querySelector(`.project-cell[data-bill-id="${activeProjectEdit}"]`);
    if (cell) {
        const project = cell.dataset.project || '';
        const projectClass = project ? '' : 'empty';
        const projectText = project || 'Click to add';

        cell.innerHTML = `
            <div class="project-display">
                <span class="project-text ${projectClass}">${escapeHtml(projectText)}</span>
                <svg class="edit-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                </svg>
            </div>
        `;
    }

    activeProjectEdit = null;
}

function filterProjectSuggestions(billId) {
    const input = document.getElementById(`projectInput-${billId}`);
    const suggestionsEl = document.getElementById(`projectSuggestions-${billId}`);

    if (!input || !suggestionsEl) return;

    const value = input.value.toLowerCase().trim();

    // Filter projects that match
    let filtered = allProjects.filter(p => p.toLowerCase().includes(value));

    // If current value is not in suggestions and not empty, add it as "new" option
    if (value && !allProjects.some(p => p.toLowerCase() === value)) {
        filtered = [`${input.value} (new)`, ...filtered];
    }

    if (filtered.length === 0) {
        suggestionsEl.style.display = 'none';
        return;
    }

    suggestionsEl.innerHTML = filtered.map(project => {
        const isNew = project.endsWith(' (new)');
        const displayText = isNew ? project : project;
        const selectValue = isNew ? input.value : project;
        return `<div class="project-suggestion" data-value="${escapeForAttr(selectValue)}">${escapeHtml(displayText)}</div>`;
    }).join('');

    // Add click handlers to suggestions
    suggestionsEl.querySelectorAll('.project-suggestion').forEach(el => {
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            const value = el.dataset.value;
            selectProject(billId, value);
        });
    });

    suggestionsEl.style.display = 'block';
}

function handleProjectKeydown(event, billId) {
    if (event.key === 'Enter') {
        event.preventDefault();
        const input = document.getElementById(`projectInput-${billId}`);
        if (input) {
            saveProject(billId, input.value);
        }
    } else if (event.key === 'Escape') {
        closeProjectEdit();
    }
}

function selectProject(billId, project) {
    saveProject(billId, project);
}

async function saveProject(billId, project) {
    const trimmedProject = project.trim();

    try {
        const response = await fetch(`/api/bills/stored/${billId}/project`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project: trimmedProject })
        });

        const data = await response.json();

        if (data.success) {
            // Update local state
            const bill = storedBills.find(b => b.id === billId);
            if (bill) {
                bill.project = trimmedProject;
            }

            // Update cell data attribute
            const cell = document.querySelector(`.project-cell[data-bill-id="${billId}"]`);
            if (cell) {
                cell.dataset.project = trimmedProject;
            }

            // Close edit and refresh display
            closeProjectEdit();

            // Add to projects list if new
            if (trimmedProject && !allProjects.includes(trimmedProject)) {
                allProjects.push(trimmedProject);
                allProjects.sort();
                populateProjectFilter();
            }

            showToast('Project updated', 'success');
        } else {
            showToast(data.error || 'Failed to update project', 'error');
        }
    } catch (error) {
        console.error('Error saving project:', error);
        showToast('Failed to save project', 'error');
    }
}

// ============================================================================
// INVOICE DETAIL
// ============================================================================

async function viewInvoiceDetail(invoiceId) {
    try {
        const response = await fetch(`/api/bills/stored/${invoiceId}`);
        const data = await response.json();

        if (!data.success) {
            showToast('Failed to load invoice details', 'error');
            return;
        }

        const bill = data.bill;
        const items = bill.line_items || [];

        document.getElementById('modalTitle').textContent = `Invoice: ${bill.invoice_number || 'N/A'}`;
        document.getElementById('modalBody').innerHTML = `
            <div class="detail-section">
                <div class="detail-section-title">Invoice Header</div>
                <div class="detail-grid">
                    ${detailItem('Invoice Number', bill.invoice_number)}
                    ${detailItem('Invoice Date', bill.invoice_date)}
                    ${detailItem('E-Way Bill', bill.eway_bill_number)}
                    ${detailItem('IRN', bill.irn)}
                    ${detailItem('Ack Number', bill.ack_number)}
                    ${detailItem('Vehicle Number', bill.vehicle_number)}
                </div>
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Vendor Details</div>
                <div class="detail-grid">
                    ${detailItem('Name', bill.vendor_name)}
                    ${detailItem('GSTIN', bill.vendor_gstin)}
                    ${detailItem('Address', bill.vendor_address)}
                    ${detailItem('State', bill.vendor_state)}
                    ${detailItem('PAN', bill.vendor_pan)}
                    ${detailItem('Phone', bill.vendor_phone)}
                    ${detailItem('Bank', bill.vendor_bank_name)}
                    ${detailItem('Account', bill.vendor_bank_account)}
                    ${detailItem('IFSC', bill.vendor_bank_ifsc)}
                </div>
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Buyer Details</div>
                <div class="detail-grid">
                    ${detailItem('Name', bill.buyer_name)}
                    ${detailItem('GSTIN', bill.buyer_gstin)}
                    ${detailItem('Address', bill.buyer_address)}
                    ${detailItem('State', bill.buyer_state)}
                </div>
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Line Items (${items.length})</div>
                ${items.length > 0 ? `
                <div style="overflow-x: auto;">
                <table class="line-items-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Description</th>
                            <th>HSN</th>
                            <th class="text-right">Qty</th>
                            <th>UOM</th>
                            <th class="text-right">Rate</th>
                            <th class="text-right">Taxable</th>
                            <th class="text-right">GST</th>
                            <th class="text-right">Amount</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${items.map(item => `
                        <tr>
                            <td>${item.sl_no || '-'}</td>
                            <td style="max-width: 200px;">${item.description || '-'}</td>
                            <td>${item.hsn_sac_code || '-'}</td>
                            <td class="text-right">${item.quantity || 0}</td>
                            <td>${item.uom || '-'}</td>
                            <td class="text-right">${formatNumber(item.rate_per_unit)}</td>
                            <td class="text-right">${formatNumber(item.taxable_value)}</td>
                            <td class="text-right">${formatNumber((item.cgst_amount || 0) + (item.sgst_amount || 0) + (item.igst_amount || 0))}</td>
                            <td class="text-right">${formatNumber(item.amount)}</td>
                        </tr>
                        `).join('')}
                    </tbody>
                </table>
                </div>
                ` : '<p class="empty-text">No line items</p>'}
            </div>

            <div class="detail-section">
                <div class="detail-section-title">Tax Summary</div>
                <div class="detail-grid">
                    ${detailItem('Subtotal', formatIndianCurrency(bill.subtotal))}
                    ${detailItem('CGST', formatIndianCurrency(bill.total_cgst))}
                    ${detailItem('SGST', formatIndianCurrency(bill.total_sgst))}
                    ${detailItem('IGST', formatIndianCurrency(bill.total_igst))}
                    ${detailItem('Other Charges', formatIndianCurrency(bill.other_charges))}
                    ${detailItem('Round Off', formatNumber(bill.round_off))}
                    ${detailItem('Total Amount', formatIndianCurrency(bill.total_amount), true)}
                </div>
            </div>
        `;

        detailModal.classList.add('show');
    } catch (error) {
        console.error('Error loading invoice detail:', error);
        showToast('Failed to load invoice details', 'error');
    }
}

function detailItem(label, value, highlight = false) {
    const displayValue = value || '-';
    const emptyClass = !value ? 'empty' : '';
    const style = highlight ? 'font-size: 1.25rem; color: var(--success-color); font-weight: 600;' : '';

    return `
        <div class="detail-item">
            <span class="detail-label">${label}</span>
            <span class="detail-value ${emptyClass}" style="${style}">${displayValue}</span>
        </div>
    `;
}

async function deleteInvoice(invoiceId) {
    if (!confirm('Are you sure you want to delete this invoice?')) return;

    try {
        const response = await fetch(`/api/bills/stored/${invoiceId}`, { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            showToast('Invoice deleted', 'success');
            refreshData();
        } else {
            showToast(data.error || 'Failed to delete', 'error');
        }
    } catch (error) {
        console.error('Error deleting invoice:', error);
        showToast('Failed to delete invoice', 'error');
    }
}

// ============================================================================
// UPLOAD MODAL
// ============================================================================

function openUploadModal() {
    resetUploadModal();
    uploadModal.classList.add('show');
}

function closeUploadModal() {
    uploadModal.classList.remove('show');
    resetUploadModal();
}

function resetUploadModal() {
    fileQueue = [];
    processedResults = [];
    rawResults = [];
    renderQueue();
    document.getElementById('processingStatus').style.display = 'none';
    document.getElementById('resultsPreview').style.display = 'none';
    document.getElementById('uploadArea').style.display = 'block';
    processBtn.disabled = true;
    processBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <polygon points="10 8 16 12 10 16 10 8"></polygon>
        </svg>
        Process Bills
    `;
}

function closeDetailModal() {
    detailModal.classList.remove('show');
}

// ============================================================================
// FILE HANDLING
// ============================================================================

function handleDragOver(e) {
    e.preventDefault();
    uploadArea.classList.add('dragover');
}

function handleDragLeave(e) {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
}

function handleDrop(e) {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    addFilesToQueue(Array.from(e.dataTransfer.files));
}

function handleFileSelect(e) {
    addFilesToQueue(Array.from(e.target.files));
    fileInput.value = '';
}

function addFilesToQueue(files) {
    const validExtensions = ['.jpg', '.jpeg', '.png', '.pdf', '.webp'];

    files.forEach(file => {
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (validExtensions.includes(ext)) {
            if (!fileQueue.some(f => f.name === file.name && f.size === file.size)) {
                fileQueue.push(file);
            }
        } else {
            showToast(`Skipped ${file.name}: Unsupported format`, 'error');
        }
    });

    renderQueue();
}

function renderQueue() {
    document.getElementById('fileCount').textContent = fileQueue.length;

    if (fileQueue.length === 0) {
        fileQueueEl.classList.remove('show');
        processBtn.disabled = true;
        return;
    }

    fileQueueEl.classList.add('show');
    processBtn.disabled = false;

    queueList.innerHTML = fileQueue.map((file, idx) => `
        <div class="queue-item">
            <div class="queue-item-icon">${getFileIcon(file.name)}</div>
            <div class="queue-item-info">
                <div class="queue-item-name">${file.name}</div>
                <div class="queue-item-size">${formatFileSize(file.size)}</div>
            </div>
            <button class="queue-item-remove" onclick="removeFromQueue(${idx})">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
        </div>
    `).join('');
}

function removeFromQueue(index) {
    fileQueue.splice(index, 1);
    renderQueue();
}

function clearQueue() {
    fileQueue = [];
    renderQueue();
}

function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    if (ext === 'pdf') {
        return `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`;
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>`;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ============================================================================
// PROCESSING
// ============================================================================

async function processFiles() {
    if (fileQueue.length === 0) return;

    // Show processing status
    document.getElementById('uploadArea').style.display = 'none';
    fileQueueEl.classList.remove('show');
    document.getElementById('processingStatus').style.display = 'block';
    processBtn.disabled = true;

    const total = fileQueue.length;
    let processed = 0;
    processedResults = [];
    rawResults = [];

    updateProgress(0, total);

    for (const file of fileQueue) {
        document.getElementById('processingText').textContent = `Processing ${file.name}...`;

        try {
            const result = await uploadAndProcessFile(file);
            if (result.success) {
                rawResults.push(...result.results);
                processedResults.push(...result.display_data);
            } else {
                processedResults.push({
                    success: false,
                    error: result.error || 'Unknown error',
                    filename: file.name
                });
            }
        } catch (error) {
            processedResults.push({
                success: false,
                error: error.message || 'Processing failed',
                filename: file.name
            });
        }

        processed++;
        updateProgress(processed, total);
    }

    // Show results
    showProcessingResults();
}

async function uploadAndProcessFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('/api/bills/process', {
        method: 'POST',
        body: formData
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Upload failed');
    }

    return await response.json();
}

function updateProgress(current, total) {
    const percent = total > 0 ? (current / total) * 100 : 0;
    document.getElementById('progressFill').style.width = percent + '%';
    document.getElementById('progressText').textContent = `${current} / ${total}`;
}

function showProcessingResults() {
    document.getElementById('processingStatus').style.display = 'none';
    document.getElementById('resultsPreview').style.display = 'block';

    const successCount = processedResults.filter(r => r.success).length;
    const errorCount = processedResults.filter(r => !r.success).length;

    document.getElementById('successCount').textContent = successCount;
    document.getElementById('errorCount').textContent = errorCount;

    document.getElementById('resultsList').innerHTML = processedResults.map(result => `
        <div class="result-item ${result.success ? 'success' : 'error'}">
            <div class="result-icon">
                ${result.success ?
                    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>' :
                    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>'
                }
            </div>
            <div class="result-info">
                <div class="result-filename">${result.filename || 'Unknown'}</div>
                <div class="result-detail">
                    ${result.success ?
                        `Invoice: ${result.invoice_number || 'N/A'} | ${result.vendor_name || 'Unknown Vendor'} | ${formatIndianCurrency(result.total_amount)}` :
                        `Error: ${result.error}`
                    }
                </div>
            </div>
        </div>
    `).join('');

    // Update button to close
    processBtn.disabled = false;
    processBtn.innerHTML = 'Done';
    processBtn.onclick = () => {
        closeUploadModal();
        refreshData();
    };

    fileQueue = [];
}

// ============================================================================
// EXPORT
// ============================================================================

async function exportAllBills() {
    if (storedBills.length === 0) {
        showToast('No bills to export', 'error');
        return;
    }

    showToast('Preparing export...', 'info');

    // Fetch all bill details for export
    const allBillData = [];
    for (const bill of storedBills) {
        try {
            const response = await fetch(`/api/bills/stored/${bill.id}`);
            const data = await response.json();
            if (data.success) {
                allBillData.push({
                    success: true,
                    data: {
                        invoice_header: {
                            invoice_number: data.bill.invoice_number,
                            invoice_date: data.bill.invoice_date,
                            irn: data.bill.irn,
                            ack_number: data.bill.ack_number,
                            eway_bill_number: data.bill.eway_bill_number
                        },
                        vendor: {
                            name: data.bill.vendor_name,
                            gstin: data.bill.vendor_gstin,
                            address: data.bill.vendor_address
                        },
                        buyer: {
                            name: data.bill.buyer_name,
                            gstin: data.bill.buyer_gstin
                        },
                        taxes: {
                            subtotal: data.bill.subtotal,
                            total_cgst: data.bill.total_cgst,
                            total_sgst: data.bill.total_sgst,
                            total_igst: data.bill.total_igst,
                            total_amount: data.bill.total_amount,
                            round_off: data.bill.round_off
                        },
                        transport: {
                            vehicle_number: data.bill.vehicle_number
                        },
                        project: data.bill.project,
                        line_items: data.bill.line_items
                    },
                    filename: data.bill.filename
                });
            }
        } catch (error) {
            console.error('Error fetching bill for export:', error);
        }
    }

    // Download
    try {
        const response = await fetch('/api/bills/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ results: allBillData })
        });

        if (!response.ok) throw new Error('Download failed');

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `all_bills_export_${new Date().toISOString().slice(0, 10)}.xlsx`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showToast('Export downloaded!', 'success');
    } catch (error) {
        console.error('Export error:', error);
        showToast('Export failed', 'error');
    }
}

// ============================================================================
// UTILITIES
// ============================================================================

function formatIndianCurrency(amount) {
    if (!amount || isNaN(amount)) return '0';
    const num = parseFloat(amount);
    const isNegative = num < 0;
    const absNum = Math.abs(num);

    const parts = absNum.toFixed(2).split('.');
    let intPart = parts[0];
    const decPart = parts[1];

    if (intPart.length > 3) {
        let result = intPart.slice(-3);
        intPart = intPart.slice(0, -3);
        while (intPart.length > 0) {
            result = intPart.slice(-2) + ',' + result;
            intPart = intPart.slice(0, -2);
        }
        intPart = result;
    }

    const formatted = decPart === '00' ? intPart : intPart + '.' + decPart;
    return (isNegative ? '-' : '') + formatted;
}

function formatNumber(num) {
    if (!num || isNaN(num)) return '0';
    return parseFloat(num).toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

function truncate(str, maxLength) {
    if (!str) return '';
    if (str.length <= maxLength) return str;
    return str.substring(0, maxLength) + '...';
}

function showToast(message, type = 'info') {
    toast.textContent = message;
    toast.className = 'toast show ' + type;
    setTimeout(() => toast.classList.remove('show'), 3000);
}

// ============================================================================
// EDIT MODAL FUNCTIONS
// ============================================================================

async function openEditModal(invoiceId) {
    console.log('[Bill Processor] Opening edit modal for invoice:', invoiceId);

    try {
        // Fetch full bill details
        const response = await fetch(`/api/bills/stored/${invoiceId}`);
        const data = await response.json();

        if (!data.success) {
            showToast('Failed to load invoice details', 'error');
            return;
        }

        currentEditBill = data.bill;
        editLineItems = [...(currentEditBill.line_items || [])];

        // Populate form fields
        populateEditForm(currentEditBill);

        // Render line items
        renderEditLineItems();

        // Populate project suggestions
        populateProjectSuggestions();

        // Load document viewer
        loadDocumentViewer(currentEditBill.filename);

        // Show modal
        document.getElementById('editModal').classList.add('show');
        document.getElementById('editModalTitle').textContent = `Edit Invoice: ${currentEditBill.invoice_number || 'N/A'}`;

    } catch (error) {
        console.error('Error opening edit modal:', error);
        showToast('Failed to open edit modal', 'error');
    }
}

function closeEditModal() {
    document.getElementById('editModal').classList.remove('show');
    currentEditBill = null;
    editLineItems = [];
    pdfDoc = null;
    currentPdfPage = 1;
    currentZoom = 1;

    // Clear document container
    document.getElementById('documentContainer').innerHTML = `
        <div class="document-placeholder">
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            <p>Loading document...</p>
        </div>
    `;
}

function populateEditForm(bill) {
    // Invoice Header
    document.getElementById('edit_invoice_number').value = bill.invoice_number || '';
    document.getElementById('edit_invoice_date').value = formatDateForInput(bill.invoice_date);
    document.getElementById('edit_irn').value = bill.irn || '';
    document.getElementById('edit_ack_number').value = bill.ack_number || '';
    document.getElementById('edit_eway_bill_number').value = bill.eway_bill_number || '';
    document.getElementById('edit_project').value = bill.project || '';

    // Vendor Details
    document.getElementById('edit_vendor_name').value = bill.vendor_name || '';
    document.getElementById('edit_vendor_gstin').value = bill.vendor_gstin || '';
    document.getElementById('edit_vendor_pan').value = bill.vendor_pan || '';
    document.getElementById('edit_vendor_address').value = bill.vendor_address || '';
    document.getElementById('edit_vendor_state').value = bill.vendor_state || '';
    document.getElementById('edit_vendor_phone').value = bill.vendor_phone || '';
    document.getElementById('edit_vendor_bank_name').value = bill.vendor_bank_name || '';
    document.getElementById('edit_vendor_bank_account').value = bill.vendor_bank_account || '';
    document.getElementById('edit_vendor_bank_ifsc').value = bill.vendor_bank_ifsc || '';

    // Buyer Details
    document.getElementById('edit_buyer_name').value = bill.buyer_name || '';
    document.getElementById('edit_buyer_gstin').value = bill.buyer_gstin || '';
    document.getElementById('edit_buyer_state').value = bill.buyer_state || '';
    document.getElementById('edit_buyer_address').value = bill.buyer_address || '';

    // Ship-To Details
    document.getElementById('edit_ship_to_name').value = bill.ship_to_name || '';
    document.getElementById('edit_ship_to_address').value = bill.ship_to_address || '';

    // Totals
    document.getElementById('edit_subtotal').value = bill.subtotal || 0;
    document.getElementById('edit_total_cgst').value = bill.total_cgst || 0;
    document.getElementById('edit_total_sgst').value = bill.total_sgst || 0;
    document.getElementById('edit_total_igst').value = bill.total_igst || 0;
    document.getElementById('edit_other_charges').value = bill.other_charges || 0;
    document.getElementById('edit_round_off').value = bill.round_off || 0;
    document.getElementById('edit_total_amount').value = bill.total_amount || 0;
    document.getElementById('edit_amount_in_words').value = bill.amount_in_words || '';

    // Transport
    document.getElementById('edit_vehicle_number').value = bill.vehicle_number || '';
    document.getElementById('edit_transporter_name').value = bill.transporter_name || '';
}

function formatDateForInput(dateStr) {
    if (!dateStr) return '';
    // Handle various date formats
    try {
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return '';
        return date.toISOString().split('T')[0];
    } catch {
        return '';
    }
}

function populateProjectSuggestions() {
    const datalist = document.getElementById('projectSuggestions');
    datalist.innerHTML = allProjects.map(p => `<option value="${escapeHtml(p)}">`).join('');
}

function renderEditLineItems() {
    const tbody = document.getElementById('lineItemsBody');

    if (editLineItems.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-row">
                <td colspan="12" class="text-center text-muted">
                    No line items. Click "Add Item" to add one.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = editLineItems.map((item, index) => `
        <tr data-index="${index}">
            <td>
                <input type="number" class="line-input line-input-sm" value="${item.sl_no || index + 1}"
                       onchange="updateLineItem(${index}, 'sl_no', this.value)">
            </td>
            <td>
                <input type="text" class="line-input line-input-desc" value="${escapeHtml(item.description || '')}"
                       onchange="updateLineItem(${index}, 'description', this.value)">
            </td>
            <td>
                <input type="text" class="line-input line-input-sm" value="${escapeHtml(item.hsn_sac_code || '')}"
                       onchange="updateLineItem(${index}, 'hsn_sac_code', this.value)">
            </td>
            <td>
                <input type="number" step="0.001" class="line-input line-input-num" value="${item.quantity || 0}"
                       onchange="updateLineItem(${index}, 'quantity', this.value)">
            </td>
            <td>
                <input type="text" class="line-input line-input-sm" value="${escapeHtml(item.uom || '')}"
                       onchange="updateLineItem(${index}, 'uom', this.value)">
            </td>
            <td>
                <input type="number" step="0.01" class="line-input line-input-num" value="${item.rate_per_unit || 0}"
                       onchange="updateLineItem(${index}, 'rate_per_unit', this.value)">
            </td>
            <td>
                <input type="number" step="0.01" class="line-input line-input-num" value="${item.taxable_value || 0}"
                       onchange="updateLineItem(${index}, 'taxable_value', this.value)">
            </td>
            <td>
                <input type="number" step="0.01" class="line-input line-input-sm" value="${item.cgst_rate || 0}"
                       onchange="updateLineItem(${index}, 'cgst_rate', this.value)">
            </td>
            <td>
                <input type="number" step="0.01" class="line-input line-input-sm" value="${item.sgst_rate || 0}"
                       onchange="updateLineItem(${index}, 'sgst_rate', this.value)">
            </td>
            <td>
                <input type="number" step="0.01" class="line-input line-input-sm" value="${item.igst_rate || 0}"
                       onchange="updateLineItem(${index}, 'igst_rate', this.value)">
            </td>
            <td>
                <input type="number" step="0.01" class="line-input line-input-num" value="${item.amount || 0}"
                       onchange="updateLineItem(${index}, 'amount', this.value)">
            </td>
            <td>
                <button type="button" class="btn-icon btn-danger btn-sm" onclick="removeLineItem(${index})" title="Remove Item">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </td>
        </tr>
    `).join('');
}

function updateLineItem(index, field, value) {
    if (editLineItems[index]) {
        if (['sl_no', 'quantity', 'rate_per_unit', 'taxable_value', 'cgst_rate', 'cgst_amount',
             'sgst_rate', 'sgst_amount', 'igst_rate', 'igst_amount', 'amount',
             'discount_percent', 'discount_amount'].includes(field)) {
            editLineItems[index][field] = parseFloat(value) || 0;
        } else {
            editLineItems[index][field] = value;
        }
    }
}

function addLineItem() {
    const newItem = {
        sl_no: editLineItems.length + 1,
        description: '',
        hsn_sac_code: '',
        quantity: 0,
        uom: '',
        rate_per_unit: 0,
        discount_percent: 0,
        discount_amount: 0,
        taxable_value: 0,
        cgst_rate: 0,
        cgst_amount: 0,
        sgst_rate: 0,
        sgst_amount: 0,
        igst_rate: 0,
        igst_amount: 0,
        amount: 0
    };
    editLineItems.push(newItem);
    renderEditLineItems();

    // Scroll to the new item
    const tbody = document.getElementById('lineItemsBody');
    tbody.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function removeLineItem(index) {
    if (editLineItems.length === 1) {
        showToast('Cannot remove the last item', 'warning');
        return;
    }
    editLineItems.splice(index, 1);
    // Re-number items
    editLineItems.forEach((item, i) => item.sl_no = i + 1);
    renderEditLineItems();
}

// ============================================================================
// DOCUMENT VIEWER FUNCTIONS
// ============================================================================

async function loadDocumentViewer(filename) {
    const container = document.getElementById('documentContainer');
    const pdfControls = document.getElementById('pdfPageControls');

    if (!filename) {
        container.innerHTML = `
            <div class="document-placeholder">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
                <p>No document available</p>
            </div>
        `;
        pdfControls.style.display = 'none';
        return;
    }

    const fileUrl = `/api/bills/file/${encodeURIComponent(filename)}`;
    const ext = filename.toLowerCase().split('.').pop();

    if (ext === 'pdf') {
        // Load PDF
        pdfControls.style.display = 'flex';
        await loadPdfDocument(fileUrl);
    } else {
        // Load Image
        pdfControls.style.display = 'none';
        loadImageDocument(fileUrl);
    }
}

async function loadPdfDocument(url) {
    const container = document.getElementById('documentContainer');
    container.innerHTML = '<div class="document-loading"><div class="loading-spinner"></div><p>Loading PDF...</p></div>';

    try {
        // Set PDF.js worker
        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

        pdfDoc = await pdfjsLib.getDocument(url).promise;
        totalPdfPages = pdfDoc.numPages;
        currentPdfPage = 1;

        document.getElementById('totalPages').textContent = totalPdfPages;
        document.getElementById('currentPage').textContent = currentPdfPage;

        // Create canvas for PDF rendering
        container.innerHTML = '<canvas id="pdfCanvas"></canvas>';
        await renderPdfPage(currentPdfPage);

    } catch (error) {
        console.error('Error loading PDF:', error);
        container.innerHTML = `
            <div class="document-placeholder error">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="15" y1="9" x2="9" y2="15"></line>
                    <line x1="9" y1="9" x2="15" y2="15"></line>
                </svg>
                <p>Failed to load PDF</p>
            </div>
        `;
    }
}

async function renderPdfPage(pageNum) {
    if (!pdfDoc) return;

    try {
        const page = await pdfDoc.getPage(pageNum);
        const canvas = document.getElementById('pdfCanvas');
        const ctx = canvas.getContext('2d');

        // Calculate scale to fit container width
        const container = document.getElementById('documentContainer');
        const containerWidth = container.clientWidth - 20;
        const viewport = page.getViewport({ scale: 1 });
        const baseScale = containerWidth / viewport.width;
        const scaledViewport = page.getViewport({ scale: baseScale * currentZoom });

        canvas.width = scaledViewport.width;
        canvas.height = scaledViewport.height;

        await page.render({
            canvasContext: ctx,
            viewport: scaledViewport
        }).promise;

        document.getElementById('currentPage').textContent = pageNum;
        updateZoomDisplay();

    } catch (error) {
        console.error('Error rendering PDF page:', error);
    }
}

function changePdfPage(delta) {
    const newPage = currentPdfPage + delta;
    if (newPage >= 1 && newPage <= totalPdfPages) {
        currentPdfPage = newPage;
        renderPdfPage(currentPdfPage);
    }
}

function loadImageDocument(url) {
    const container = document.getElementById('documentContainer');
    container.innerHTML = `
        <div class="image-wrapper" id="imageWrapper">
            <img id="documentImage" src="${url}" alt="Invoice Document"
                 style="transform: scale(${currentZoom})"
                 onload="updateZoomDisplay()"
                 onerror="handleImageError()">
        </div>
    `;
}

function handleImageError() {
    const container = document.getElementById('documentContainer');
    container.innerHTML = `
        <div class="document-placeholder error">
            <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
            </svg>
            <p>Failed to load image</p>
        </div>
    `;
}

function adjustZoom(delta) {
    const newZoom = Math.max(0.25, Math.min(3, currentZoom + delta));
    if (newZoom !== currentZoom) {
        currentZoom = newZoom;
        applyZoom();
    }
}

function resetZoom() {
    currentZoom = 1;
    applyZoom();
}

function applyZoom() {
    const image = document.getElementById('documentImage');
    const canvas = document.getElementById('pdfCanvas');

    if (image) {
        image.style.transform = `scale(${currentZoom})`;
    } else if (canvas && pdfDoc) {
        renderPdfPage(currentPdfPage);
    }

    updateZoomDisplay();
}

function updateZoomDisplay() {
    document.getElementById('zoomLevel').textContent = Math.round(currentZoom * 100) + '%';
}

// ============================================================================
// SAVE EDIT CHANGES
// ============================================================================

async function saveEditChanges() {
    if (!currentEditBill) return;

    const saveBtn = document.getElementById('saveEditBtn');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<div class="btn-spinner"></div> Saving...';

    try {
        // Collect form data
        const formData = {
            invoice_number: document.getElementById('edit_invoice_number').value,
            invoice_date: document.getElementById('edit_invoice_date').value,
            irn: document.getElementById('edit_irn').value,
            ack_number: document.getElementById('edit_ack_number').value,
            eway_bill_number: document.getElementById('edit_eway_bill_number').value,
            project: document.getElementById('edit_project').value,

            vendor_name: document.getElementById('edit_vendor_name').value,
            vendor_gstin: document.getElementById('edit_vendor_gstin').value,
            vendor_pan: document.getElementById('edit_vendor_pan').value,
            vendor_address: document.getElementById('edit_vendor_address').value,
            vendor_state: document.getElementById('edit_vendor_state').value,
            vendor_phone: document.getElementById('edit_vendor_phone').value,
            vendor_bank_name: document.getElementById('edit_vendor_bank_name').value,
            vendor_bank_account: document.getElementById('edit_vendor_bank_account').value,
            vendor_bank_ifsc: document.getElementById('edit_vendor_bank_ifsc').value,

            buyer_name: document.getElementById('edit_buyer_name').value,
            buyer_gstin: document.getElementById('edit_buyer_gstin').value,
            buyer_state: document.getElementById('edit_buyer_state').value,
            buyer_address: document.getElementById('edit_buyer_address').value,

            ship_to_name: document.getElementById('edit_ship_to_name').value,
            ship_to_address: document.getElementById('edit_ship_to_address').value,

            subtotal: parseFloat(document.getElementById('edit_subtotal').value) || 0,
            total_cgst: parseFloat(document.getElementById('edit_total_cgst').value) || 0,
            total_sgst: parseFloat(document.getElementById('edit_total_sgst').value) || 0,
            total_igst: parseFloat(document.getElementById('edit_total_igst').value) || 0,
            other_charges: parseFloat(document.getElementById('edit_other_charges').value) || 0,
            round_off: parseFloat(document.getElementById('edit_round_off').value) || 0,
            total_amount: parseFloat(document.getElementById('edit_total_amount').value) || 0,
            amount_in_words: document.getElementById('edit_amount_in_words').value,

            vehicle_number: document.getElementById('edit_vehicle_number').value,
            transporter_name: document.getElementById('edit_transporter_name').value,

            line_items: editLineItems
        };

        const response = await fetch(`/api/bills/stored/${currentEditBill.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });

        const result = await response.json();

        if (result.success) {
            showToast('Invoice updated successfully', 'success');
            closeEditModal();
            refreshData();
        } else {
            showToast(result.error || 'Failed to update invoice', 'error');
        }

    } catch (error) {
        console.error('Error saving changes:', error);
        showToast('Failed to save changes', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                <polyline points="17 21 17 13 7 13 7 21"></polyline>
                <polyline points="7 3 7 8 15 8"></polyline>
            </svg>
            Save Changes
        `;
    }
}

// ============================================================================
// BULK UPLOAD FUNCTIONS
// ============================================================================

let bulkUploadFiles = [];

function initBulkUpload() {
    const bulkUploadModal = document.getElementById('bulkUploadModal');
    const bulkUploadArea = document.getElementById('bulkUploadArea');
    const bulkFileInput = document.getElementById('bulkFileInput');

    // Button to open modal
    document.getElementById('bulkUploadBtn').addEventListener('click', openBulkUploadModal);

    // Close modal events
    document.getElementById('closeBulkUploadModal').addEventListener('click', closeBulkUploadModal);
    document.getElementById('cancelBulkUpload').addEventListener('click', closeBulkUploadModal);
    bulkUploadModal.addEventListener('click', (e) => {
        if (e.target === bulkUploadModal) closeBulkUploadModal();
    });

    // Upload area events
    bulkUploadArea.addEventListener('click', () => bulkFileInput.click());
    bulkUploadArea.addEventListener('dragover', handleBulkDragOver);
    bulkUploadArea.addEventListener('dragleave', handleBulkDragLeave);
    bulkUploadArea.addEventListener('drop', handleBulkDrop);
    bulkFileInput.addEventListener('change', handleBulkFileSelect);

    // Start upload button
    document.getElementById('startBulkUpload').addEventListener('click', startBulkUpload);
}

function openBulkUploadModal() {
    bulkUploadFiles = [];
    document.getElementById('bulkUploadModal').classList.add('show');
    document.getElementById('bulkFileList').style.display = 'none';
    document.getElementById('bulkUploadProgress').style.display = 'none';
    document.getElementById('bulkUploadResults').style.display = 'none';
    document.getElementById('startBulkUpload').disabled = true;
    document.getElementById('bulkFileInput').value = '';
}

function closeBulkUploadModal() {
    document.getElementById('bulkUploadModal').classList.remove('show');
    bulkUploadFiles = [];
}

function handleBulkDragOver(e) {
    e.preventDefault();
    e.currentTarget.classList.add('drag-over');
}

function handleBulkDragLeave(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');
}

function handleBulkDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files);
    addBulkFiles(files);
}

function handleBulkFileSelect(e) {
    const files = Array.from(e.target.files);
    addBulkFiles(files);
}

function addBulkFiles(files) {
    const allowedExtensions = ['.pdf', '.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'];

    files.forEach(file => {
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (allowedExtensions.includes(ext)) {
            // Avoid duplicates
            if (!bulkUploadFiles.find(f => f.name === file.name)) {
                bulkUploadFiles.push(file);
            }
        }
    });

    renderBulkFileList();
}

function renderBulkFileList() {
    const container = document.getElementById('bulkFileListContainer');
    const fileList = document.getElementById('bulkFileList');
    const fileCount = document.getElementById('bulkFileCount');
    const uploadBtn = document.getElementById('startBulkUpload');

    if (bulkUploadFiles.length === 0) {
        fileList.style.display = 'none';
        uploadBtn.disabled = true;
        return;
    }

    fileList.style.display = 'block';
    fileCount.textContent = bulkUploadFiles.length;
    uploadBtn.disabled = false;

    container.innerHTML = bulkUploadFiles.map((file, index) => `
        <div class="bulk-file-item">
            <span class="file-name">${file.name}</span>
            <span class="file-size">${formatFileSize(file.size)}</span>
            <button type="button" class="btn-remove-file" onclick="removeBulkFile(${index})" title="Remove">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        </div>
    `).join('');
}

function removeBulkFile(index) {
    bulkUploadFiles.splice(index, 1);
    renderBulkFileList();
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function startBulkUpload() {
    if (bulkUploadFiles.length === 0) return;

    const uploadBtn = document.getElementById('startBulkUpload');
    const progressSection = document.getElementById('bulkUploadProgress');
    const progressFill = document.getElementById('bulkProgressFill');
    const progressText = document.getElementById('bulkProgressText');
    const resultsSection = document.getElementById('bulkUploadResults');
    const resultSummary = document.getElementById('bulkResultSummary');

    // Show progress
    uploadBtn.disabled = true;
    progressSection.style.display = 'block';
    resultsSection.style.display = 'none';
    progressFill.style.width = '0%';
    progressText.textContent = 'Preparing upload...';

    try {
        const formData = new FormData();
        bulkUploadFiles.forEach(file => {
            formData.append('files', file);
        });

        progressText.textContent = `Uploading ${bulkUploadFiles.length} files...`;
        progressFill.style.width = '50%';

        const response = await fetch('/api/bills/upload-files', {
            method: 'POST',
            body: formData
        });

        progressFill.style.width = '100%';
        const data = await response.json();

        // Show results
        progressSection.style.display = 'none';
        resultsSection.style.display = 'block';

        if (data.success) {
            resultSummary.innerHTML = `
                <div class="result-success">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                        <polyline points="22 4 12 14.01 9 11.01"></polyline>
                    </svg>
                    <div>
                        <strong>${data.uploaded} files uploaded successfully</strong>
                        ${data.skipped > 0 ? `<br><span class="text-muted">${data.skipped} files skipped</span>` : ''}
                    </div>
                </div>
                ${data.details && data.details.length > 0 ? `
                    <div class="result-details">
                        ${data.details.map(d => `
                            <div class="result-item ${d.status}">
                                <span class="filename">${d.filename}</span>
                                <span class="status-badge ${d.status}">${d.status}${d.reason ? ': ' + d.reason : ''}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            `;
            showToast(`${data.uploaded} files uploaded successfully`, 'success');
        } else {
            resultSummary.innerHTML = `
                <div class="result-error">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="15" y1="9" x2="9" y2="15"></line>
                        <line x1="9" y1="9" x2="15" y2="15"></line>
                    </svg>
                    <div>
                        <strong>Upload failed</strong>
                        <br><span class="text-muted">${data.error || 'Unknown error'}</span>
                    </div>
                </div>
            `;
            showToast('Upload failed: ' + (data.error || 'Unknown error'), 'error');
        }

        // Clear the file list
        bulkUploadFiles = [];
        document.getElementById('bulkFileList').style.display = 'none';

    } catch (error) {
        console.error('Bulk upload error:', error);
        progressSection.style.display = 'none';
        resultsSection.style.display = 'block';
        resultSummary.innerHTML = `
            <div class="result-error">
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="15" y1="9" x2="9" y2="15"></line>
                    <line x1="9" y1="9" x2="15" y2="15"></line>
                </svg>
                <div>
                    <strong>Upload failed</strong>
                    <br><span class="text-muted">${error.message}</span>
                </div>
            </div>
        `;
        showToast('Upload failed: ' + error.message, 'error');
    }

    uploadBtn.disabled = false;
}

// Initialize bulk upload on page load
document.addEventListener('DOMContentLoaded', initBulkUpload);

// ============================================================================
// EXPOSE FUNCTIONS TO GLOBAL SCOPE (for remaining inline onclick handlers)
// ============================================================================
window.viewInvoiceDetail = viewInvoiceDetail;
window.deleteInvoice = deleteInvoice;
window.openEditModal = openEditModal;
window.updateLineItem = updateLineItem;
window.removeLineItem = removeLineItem;
window.handleImageError = handleImageError;
window.updateZoomDisplay = updateZoomDisplay;
window.removeBulkFile = removeBulkFile;
