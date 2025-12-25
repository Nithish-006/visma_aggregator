// ============================================================================
// UPLOAD FUNCTIONALITY
// ============================================================================

(function() {
    // Bank code from page context
    const BANK_CODE = window.BANK_CODE || 'axis';

    const uploadBtn = document.getElementById('upload-btn');
    const uploadModal = document.getElementById('upload-modal');
    const closeModal = document.getElementById('close-modal');
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    const uploadProgress = document.getElementById('upload-progress');
    const uploadResult = document.getElementById('upload-result');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressText = document.getElementById('progress-text');
    const modalDoneBtn = document.getElementById('modal-done-btn');

    // Open modal
    uploadBtn.addEventListener('click', () => {
        uploadModal.classList.add('show');
        resetUploadModal();
    });

    // Close modal
    closeModal.addEventListener('click', () => {
        uploadModal.classList.remove('show');
    });

    // Close modal on outside click
    uploadModal.addEventListener('click', (e) => {
        if (e.target === uploadModal) {
            uploadModal.classList.remove('show');
        }
    });

    // Click to browse
    uploadArea.addEventListener('click', () => {
        fileInput.click();
    });

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
    });

    // Done button
    modalDoneBtn.addEventListener('click', () => {
        uploadModal.classList.remove('show');
        // Reload the page to show new data
        location.reload();
    });

    function resetUploadModal() {
        uploadArea.style.display = 'block';
        uploadProgress.style.display = 'none';
        uploadResult.style.display = 'none';
        modalDoneBtn.style.display = 'none';
        progressBarFill.style.width = '0%';
        fileInput.value = '';
    }

    function handleFile(file) {
        // Validate file type
        const validTypes = ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel'];
        const validExtensions = ['.xlsx', '.xls'];

        const fileExtension = '.' + file.name.split('.').pop().toLowerCase();

        if (!validTypes.includes(file.type) && !validExtensions.includes(fileExtension)) {
            showError('Invalid file type', 'Please upload an Excel file (.xlsx or .xls)');
            return;
        }

        // Show progress
        uploadArea.style.display = 'none';
        uploadProgress.style.display = 'block';
        progressBarFill.style.width = '30%';
        progressText.textContent = 'Uploading file...';

        // Upload file
        const formData = new FormData();
        formData.append('file', file);

        fetch(`/api/${BANK_CODE}/upload`, {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            progressBarFill.style.width = '100%';
            progressText.textContent = 'Processing complete!';

            setTimeout(() => {
                if (data.success) {
                    showSuccess(data);
                } else {
                    showError('Upload failed', data.error || 'An error occurred while processing the file');
                }
            }, 500);
        })
        .catch(error => {
            console.error('Upload error:', error);
            showError('Upload failed', 'Network error. Please try again.');
        });
    }

    function showSuccess(data) {
        uploadProgress.style.display = 'none';
        uploadResult.style.display = 'block';
        modalDoneBtn.style.display = 'block';

        const resultIcon = document.getElementById('result-icon');
        const resultTitle = document.getElementById('result-title');
        const resultMessage = document.getElementById('result-message');
        const resultStats = document.getElementById('result-stats');

        resultIcon.className = 'result-icon success';
        resultTitle.textContent = 'Upload Successful!';
        resultMessage.textContent = data.message || 'Your bank statement has been processed successfully.';

        if (data.stats) {
            let statsHTML = '<div class="stat-item"><span class="stat-label">Total Transactions:</span><span class="stat-value">' + data.stats.total + '</span></div>';
            statsHTML += '<div class="stat-item"><span class="stat-label">New Transactions:</span><span class="stat-value" style="color: #059669;">' + data.stats.inserted + '</span></div>';

            if (data.stats.duplicates > 0) {
                statsHTML += '<div class="stat-item"><span class="stat-label">Duplicates Skipped:</span><span class="stat-value" style="color: #f59e0b;">' + data.stats.duplicates + '</span></div>';
            }

            if (data.stats.errors > 0) {
                statsHTML += '<div class="stat-item"><span class="stat-label">Errors:</span><span class="stat-value" style="color: #dc2626;">' + data.stats.errors + '</span></div>';
            }

            resultStats.innerHTML = statsHTML;
        }
    }

    function showError(title, message) {
        uploadArea.style.display = 'none';
        uploadProgress.style.display = 'none';
        uploadResult.style.display = 'block';
        modalDoneBtn.style.display = 'block';
        modalDoneBtn.textContent = 'Close';

        const resultIcon = document.getElementById('result-icon');
        const resultTitle = document.getElementById('result-title');
        const resultMessage = document.getElementById('result-message');
        const resultStats = document.getElementById('result-stats');

        resultIcon.className = 'result-icon error';
        resultTitle.textContent = title;
        resultMessage.textContent = message;
        resultStats.innerHTML = '';
    }
})();
