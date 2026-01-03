// ============================================================================
// UPLOAD FUNCTIONALITY
// ============================================================================

(function() {
    // Bank code from page context
    const BANK_CODE = window.BANK_CODE || 'axis';
    const isKVB = BANK_CODE === 'kvb';

    // DOM Elements
    const uploadBtn = document.getElementById('upload-btn');
    const uploadModal = document.getElementById('upload-modal');
    const closeModal = document.getElementById('close-modal');
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    const uploadPreview = document.getElementById('upload-preview');
    const uploadProgress = document.getElementById('upload-progress');
    const uploadResult = document.getElementById('upload-result');
    const progressBarFill = document.getElementById('progress-bar-fill');
    const progressText = document.getElementById('progress-text');
    const modalDoneBtn = document.getElementById('modal-done-btn');
    const filePasswordInput = document.getElementById('file-password');
    const uploadSubmitBtn = document.getElementById('upload-submit-btn');
    const removeFileBtn = document.getElementById('remove-file');
    const previewFilename = document.getElementById('preview-filename');
    const previewFilesize = document.getElementById('preview-filesize');

    // Store selected file
    let selectedFile = null;

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
            handleFileSelection(files[0]);
        }
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelection(e.target.files[0]);
        }
    });

    // Remove file button
    if (removeFileBtn) {
        removeFileBtn.addEventListener('click', () => {
            selectedFile = null;
            resetUploadModal();
        });
    }

    // Upload submit button (for KVB two-step flow)
    if (uploadSubmitBtn) {
        uploadSubmitBtn.addEventListener('click', () => {
            if (selectedFile) {
                processUpload(selectedFile);
            }
        });
    }

    // Done button
    modalDoneBtn.addEventListener('click', () => {
        uploadModal.classList.remove('show');
        // Reload the page to show new data
        location.reload();
    });

    function resetUploadModal() {
        uploadArea.style.display = 'block';
        if (uploadPreview) uploadPreview.style.display = 'none';
        uploadProgress.style.display = 'none';
        uploadResult.style.display = 'none';
        modalDoneBtn.style.display = 'none';
        progressBarFill.style.width = '0%';
        fileInput.value = '';
        selectedFile = null;
        if (filePasswordInput) filePasswordInput.value = '';
    }

    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    function handleFileSelection(file) {
        // Validate file type
        const validTypes = ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel'];
        const validExtensions = ['.xlsx', '.xls'];
        const fileExtension = '.' + file.name.split('.').pop().toLowerCase();

        if (!validTypes.includes(file.type) && !validExtensions.includes(fileExtension)) {
            showError('Invalid file type', 'Please upload an Excel file (.xlsx or .xls)');
            return;
        }

        selectedFile = file;

        // For KVB: Show preview with password input and upload button
        if (isKVB) {
            uploadArea.style.display = 'none';
            if (uploadPreview) {
                uploadPreview.style.display = 'block';
                if (previewFilename) previewFilename.textContent = file.name;
                if (previewFilesize) previewFilesize.textContent = formatFileSize(file.size);
            }
        } else {
            // For Axis: Process immediately (existing behavior)
            processUpload(file);
        }
    }

    function updateProgress(percent, message) {
        progressBarFill.style.width = percent + '%';
        progressText.textContent = message;
    }

    function processUpload(file) {
        // Show progress
        uploadArea.style.display = 'none';
        if (uploadPreview) uploadPreview.style.display = 'none';
        uploadProgress.style.display = 'block';

        updateProgress(10, 'Uploading file...');

        // Build form data
        const formData = new FormData();
        formData.append('file', file);

        // Add password for KVB encrypted files
        if (filePasswordInput && filePasswordInput.value) {
            formData.append('password', filePasswordInput.value);
        }

        // Simulate progress updates
        let progressStage = 0;
        const progressMessages = [
            { percent: 20, message: 'Uploading file...' },
            { percent: 35, message: 'File uploaded successfully' },
            { percent: 50, message: 'Processing bank statement...' },
            { percent: 65, message: 'Extracting transactions...' },
            { percent: 80, message: 'Inserting to database...' },
            { percent: 95, message: 'Finalizing...' }
        ];

        const progressInterval = setInterval(() => {
            if (progressStage < progressMessages.length) {
                const stage = progressMessages[progressStage];
                updateProgress(stage.percent, stage.message);
                progressStage++;
            }
        }, 800);

        fetch(`/api/${BANK_CODE}/upload`, {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            clearInterval(progressInterval);
            updateProgress(100, 'Complete!');

            setTimeout(() => {
                if (data.success) {
                    showSuccess(data);
                } else {
                    showError('Upload failed', data.error || data.details || 'An error occurred while processing the file');
                }
            }, 500);
        })
        .catch(error => {
            clearInterval(progressInterval);
            console.error('Upload error:', error);
            showError('Upload failed', 'Network error. Please try again.');
        });
    }

    function showSuccess(data) {
        uploadProgress.style.display = 'none';
        uploadResult.style.display = 'block';
        modalDoneBtn.style.display = 'block';
        modalDoneBtn.textContent = 'Done';

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
        if (uploadPreview) uploadPreview.style.display = 'none';
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
