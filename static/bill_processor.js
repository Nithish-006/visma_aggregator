/* ============================================================================
   BILL PROCESSOR - FRONTEND JAVASCRIPT
   ============================================================================ */

// State
let storedBills = [];
let allLineItems = [];
let fileQueue = [];
let processedResults = [];
let rawResults = [];

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

function init() {
    // Load data on page load
    loadSummary();
    loadStoredBills();

    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Header buttons
    document.getElementById('newBillBtn').addEventListener('click', openUploadModal);
    document.getElementById('refreshBtn').addEventListener('click', refreshData);
    document.getElementById('exportAllBtn').addEventListener('click', exportAllBills);

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
        }
    });

    // Close upload modal when clicking outside
    uploadModal.addEventListener('click', (e) => {
        if (e.target === uploadModal) closeUploadModal();
    });
}

// ============================================================================
// DATA LOADING
// ============================================================================

async function loadSummary() {
    try {
        const response = await fetch('/api/bills/summary');
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
        const response = await fetch('/api/bills/stored?limit=500');
        const data = await response.json();

        if (data.success) {
            storedBills = data.bills;
            renderInvoicesTable();
            loadAllLineItems();
        } else {
            showEmptyState('invoices');
        }
    } catch (error) {
        console.error('Error loading bills:', error);
        showEmptyState('invoices');
    }
}

async function loadAllLineItems() {
    // Collect all line items from stored bills
    allLineItems = [];

    for (const bill of storedBills) {
        try {
            const response = await fetch(`/api/bills/stored/${bill.id}`);
            const data = await response.json();

            if (data.success && data.bill.line_items) {
                data.bill.line_items.forEach(item => {
                    allLineItems.push({
                        ...item,
                        invoice_number: bill.invoice_number,
                        invoice_date: bill.invoice_date,
                        vendor_name: bill.vendor_name
                    });
                });
            }
        } catch (error) {
            console.error(`Error loading line items for bill ${bill.id}:`, error);
        }
    }

    renderLineItemsTable();
}

function refreshData() {
    loadSummary();
    loadStoredBills();
    showToast('Data refreshed', 'success');
}

// ============================================================================
// TAB SWITCHING
// ============================================================================

function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === tabName + 'Tab');
    });
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
                <td>
                    <div class="action-buttons">
                        <button class="btn-icon" onclick="viewInvoiceDetail(${bill.id})" title="View Details">
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                                <circle cx="12" cy="12" r="3"></circle>
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

function renderLineItemsTable() {
    const tbody = document.getElementById('lineItemsBody');
    const emptyState = document.getElementById('lineItemsEmpty');
    const tableContainer = document.querySelector('#lineitemsTab .table-container');

    if (allLineItems.length === 0) {
        tableContainer.style.display = 'none';
        emptyState.style.display = 'flex';
        return;
    }

    tableContainer.style.display = 'block';
    emptyState.style.display = 'none';

    tbody.innerHTML = allLineItems.map(item => {
        const gst = (parseFloat(item.cgst_amount) || 0) + (parseFloat(item.sgst_amount) || 0) + (parseFloat(item.igst_amount) || 0);
        const gstRate = (parseFloat(item.cgst_rate) || 0) + (parseFloat(item.sgst_rate) || 0) + (parseFloat(item.igst_rate) || 0);

        return `
            <tr>
                <td>${item.invoice_number || '-'}</td>
                <td>${item.invoice_date || '-'}</td>
                <td class="cell-wrap">${item.vendor_name || '-'}</td>
                <td>${item.sl_no || '-'}</td>
                <td class="cell-wrap">${item.description || '-'}</td>
                <td>${item.hsn_sac_code || '-'}</td>
                <td class="text-right">${item.quantity || 0}</td>
                <td>${item.uom || '-'}</td>
                <td class="text-right">${formatNumber(item.rate_per_unit)}</td>
                <td class="text-right">${formatNumber(item.taxable_value)}</td>
                <td class="text-right">${formatNumber(gst)}${gstRate ? ' (' + gstRate + '%)' : ''}</td>
                <td class="text-right cell-amount">${formatNumber(item.amount)}</td>
            </tr>
        `;
    }).join('');
}

function showEmptyState(type) {
    if (type === 'invoices') {
        document.querySelector('#invoicesTab .table-container').style.display = 'none';
        document.getElementById('invoicesEmpty').style.display = 'flex';
    } else {
        document.querySelector('#lineitemsTab .table-container').style.display = 'none';
        document.getElementById('lineItemsEmpty').style.display = 'flex';
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
