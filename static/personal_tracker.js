// ============================================================================
// PERSONAL TRACKER - SIMPLIFIED MOBILE-FIRST UI
// ============================================================================

(function() {
    'use strict';

    // State
    let transactions = [];
    let allTransactions = [];
    let projects = [];
    let vendors = [];
    let deleteTargetId = null;
    let currentMonth = new Date();
    let currentTab = 'daily';
    let searchQuery = '';

    // Filter state
    let bankFilter = 'all'; // 'all', 'axis', 'kvb'

    // Category icons mapping
    const categoryIcons = {
        'Salary': { icon: '💰', name: 'Salary' },
        'Food': { icon: '🍔', name: 'Food' },
        'Transport': { icon: '🚗', name: 'Transport' },
        'Shopping': { icon: '🛒', name: 'Shopping' },
        'Bills': { icon: '📄', name: 'Bills' },
        'Entertainment': { icon: '🎬', name: 'Entertainment' },
        'Health': { icon: '💊', name: 'Health' },
        'Social Life': { icon: '🎉', name: 'Social' },
        'Investment': { icon: '📈', name: 'Invest' },
        'default_income': { icon: '💵', name: 'Income' },
        'default_expense': { icon: '💸', name: 'Expense' }
    };

    // DOM Elements
    const elements = {
        // Header
        currentMonth: document.getElementById('current-month'),
        prevMonth: document.getElementById('prev-month'),
        nextMonth: document.getElementById('next-month'),

        // Search
        searchToggle: document.getElementById('search-toggle'),
        searchBar: document.getElementById('search-bar'),
        searchInput: document.getElementById('search-input'),
        searchClose: document.getElementById('search-close'),

        // Tabs
        tabs: document.querySelectorAll('.tab'),
        tabContents: document.querySelectorAll('.tab-content'),

        // Summary
        summaryIncome: document.getElementById('summary-income'),
        summaryExpense: document.getElementById('summary-expense'),

        // Content containers
        dailyTransactions: document.getElementById('daily-transactions'),
        monthlyBreakdown: document.getElementById('monthly-breakdown'),
        totalSummary: document.getElementById('total-summary'),
        projectsBreakdown: document.getElementById('projects-breakdown'),

        // FAB
        fabAdd: document.getElementById('fab-add'),

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
        typeExpenseBtn: document.getElementById('type-expense-btn'),
        typeIncomeBtn: document.getElementById('type-income-btn'),
        deleteBtn: document.getElementById('delete-btn'),
        bankAxisBtn: document.getElementById('bank-axis-btn'),
        bankKvbBtn: document.getElementById('bank-kvb-btn'),
        transactionBank: document.getElementById('transaction-bank'),

        // Custom Dropdowns
        vendorDropdown: document.getElementById('vendor-dropdown'),
        vendorMenu: document.getElementById('vendor-menu'),
        projectDropdown: document.getElementById('project-dropdown'),
        projectMenu: document.getElementById('project-menu'),

        // Delete Modal
        deleteModal: document.getElementById('delete-modal'),
        deleteModalClose: document.getElementById('delete-modal-close'),
        deleteInfo: document.getElementById('delete-info'),
        deleteCancelBtn: document.getElementById('delete-cancel-btn'),
        deleteConfirmBtn: document.getElementById('delete-confirm-btn'),

        // Toast
        toast: document.getElementById('toast'),
        toastMessage: document.getElementById('toast-message'),

        // Bank Filter
        bankBtns: document.querySelectorAll('.bank-btn')
    };

    // ============================================================================
    // INITIALIZATION
    // ============================================================================

    function init() {
        setupEventListeners();
        setDefaultDate();
        updateMonthLabel();
        loadData();
    }

    function setupEventListeners() {
        // Month navigation
        elements.prevMonth.addEventListener('click', () => navigateMonth(-1));
        elements.nextMonth.addEventListener('click', () => navigateMonth(1));

        // Search
        elements.searchToggle.addEventListener('click', toggleSearch);
        elements.searchClose.addEventListener('click', closeSearch);
        elements.searchInput.addEventListener('input', debounce(handleSearch, 300));

        // Tabs
        elements.tabs.forEach(tab => {
            tab.addEventListener('click', () => switchTab(tab.dataset.tab));
        });

        // FAB
        elements.fabAdd.addEventListener('click', openAddModal);

        // Modal
        elements.modalClose.addEventListener('click', closeModal);
        elements.cancelBtn.addEventListener('click', closeModal);
        elements.transactionModal.addEventListener('click', (e) => {
            if (e.target === elements.transactionModal) closeModal();
        });

        // Transaction type toggle
        elements.typeExpenseBtn.addEventListener('click', () => setTransactionType('expense'));
        elements.typeIncomeBtn.addEventListener('click', () => setTransactionType('income'));

        // Bank selection
        elements.bankAxisBtn.addEventListener('click', () => setBank('axis'));
        elements.bankKvbBtn.addEventListener('click', () => setBank('kvb'));

        // Delete button in edit modal
        elements.deleteBtn.addEventListener('click', handleDeleteFromEdit);

        // Form submit
        elements.transactionForm.addEventListener('submit', handleFormSubmit);

        // Delete modal
        elements.deleteModalClose.addEventListener('click', closeDeleteModal);
        elements.deleteCancelBtn.addEventListener('click', closeDeleteModal);
        elements.deleteConfirmBtn.addEventListener('click', confirmDelete);
        elements.deleteModal.addEventListener('click', (e) => {
            if (e.target === elements.deleteModal) closeDeleteModal();
        });

        // Custom dropdowns
        setupCustomDropdown('vendor', elements.transactionVendor, elements.vendorMenu, () => vendors);
        setupCustomDropdown('project', elements.transactionProject, elements.projectMenu, () => projects);

        // Close dropdowns when clicking outside
        document.addEventListener('click', (e) => {
            if (!elements.vendorDropdown.contains(e.target)) {
                elements.vendorMenu.classList.remove('show');
            }
            if (!elements.projectDropdown.contains(e.target)) {
                elements.projectMenu.classList.remove('show');
            }
        });

        // Bank filter buttons
        elements.bankBtns.forEach(btn => {
            btn.addEventListener('click', () => handleBankFilterClick(btn.dataset.bank));
        });
    }

    function setupCustomDropdown(type, input, menu, getItems) {
        // Flag to prevent menu from reopening after selection
        let justSelected = false;

        input.addEventListener('focus', () => {
            if (justSelected) {
                justSelected = false;
                return;
            }
            renderDropdownPills(menu, getItems(), input, () => { justSelected = true; });
            menu.classList.add('show');
        });

        input.addEventListener('input', () => {
            const filtered = filterItems(getItems(), input.value);
            renderDropdownPills(menu, filtered, input, () => { justSelected = true; });
            if (filtered.length > 0) {
                menu.classList.add('show');
            } else {
                menu.classList.remove('show');
            }
        });
    }

    function filterItems(items, query) {
        if (!query) return items;
        const q = query.toLowerCase();
        return items.filter(item => item.toLowerCase().includes(q));
    }

    function renderDropdownPills(menu, items, input, onSelect) {
        if (!items || items.length === 0) {
            menu.innerHTML = '';
            return;
        }

        const pillsHtml = items.map(item =>
            `<div class="dropdown-pill" data-value="${escapeHtml(item)}">${escapeHtml(item)}</div>`
        ).join('');

        menu.innerHTML = `<div class="dropdown-pills">${pillsHtml}</div>`;

        // Add click handlers to pills
        menu.querySelectorAll('.dropdown-pill').forEach(pill => {
            pill.addEventListener('click', (e) => {
                e.stopPropagation();
                input.value = pill.dataset.value;
                menu.classList.remove('show');
                // Call the onSelect callback before focusing to prevent menu from reopening
                if (onSelect) onSelect();
                input.focus();
            });
        });
    }

    // ============================================================================
    // MONTH NAVIGATION
    // ============================================================================

    function navigateMonth(delta) {
        currentMonth.setMonth(currentMonth.getMonth() + delta);
        updateMonthLabel();
        applyFilters();
    }

    function updateMonthLabel() {
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        elements.currentMonth.textContent = `${months[currentMonth.getMonth()]} ${currentMonth.getFullYear()}`;
    }

    // ============================================================================
    // SEARCH
    // ============================================================================

    function toggleSearch() {
        elements.searchBar.classList.toggle('show');
        if (elements.searchBar.classList.contains('show')) {
            elements.searchInput.focus();
        }
    }

    function closeSearch() {
        elements.searchBar.classList.remove('show');
        elements.searchInput.value = '';
        searchQuery = '';
        renderCurrentTab();
    }

    function handleSearch() {
        searchQuery = elements.searchInput.value.toLowerCase().trim();
        renderCurrentTab();
    }

    // ============================================================================
    // FILTERS
    // ============================================================================

    function handleBankFilterClick(bank) {
        bankFilter = bank;
        updateBankFilterUI();
        applyFilters();
    }

    function updateBankFilterUI() {
        elements.bankBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.bank === bankFilter);
        });
    }

    function applyFilters() {
        filterTransactionsByFilters();
        updateSummary();
        renderCurrentTab();
    }

    function filterTransactionsByFilters() {
        const year = currentMonth.getFullYear();
        const month = currentMonth.getMonth();

        transactions = allTransactions.filter(t => {
            const date = new Date(t.date);

            // Apply month filter
            if (date.getFullYear() !== year || date.getMonth() !== month) {
                return false;
            }

            // Apply bank filter
            if (bankFilter !== 'all') {
                if (t.bank !== bankFilter) return false;
            }

            // Apply search filter
            if (searchQuery) {
                const matchesSearch =
                    t.vendor.toLowerCase().includes(searchQuery) ||
                    (t.description && t.description.toLowerCase().includes(searchQuery)) ||
                    (t.project && t.project.toLowerCase().includes(searchQuery));
                if (!matchesSearch) return false;
            }

            return true;
        });
    }

    // ============================================================================
    // TABS
    // ============================================================================

    function switchTab(tabName) {
        currentTab = tabName;

        // Update tab styles
        elements.tabs.forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === tabName);
        });

        // Update content visibility
        elements.tabContents.forEach(content => {
            content.classList.toggle('active', content.id === `tab-${tabName}`);
        });

        renderCurrentTab();
    }

    function renderCurrentTab() {
        switch (currentTab) {
            case 'daily':
                renderDailyView();
                break;
            case 'monthly':
                renderMonthlyView();
                break;
            case 'total':
                renderTotalView();
                break;
            case 'projects':
                renderProjectsView();
                break;
        }
    }

    // ============================================================================
    // DATA LOADING
    // ============================================================================

    async function loadData() {
        await Promise.all([
            loadProjects(),
            loadVendors(),
            loadTransactions()
        ]);
    }

    async function loadProjects() {
        try {
            const response = await fetch('/api/personal/projects');
            const data = await response.json();
            projects = data.projects || ['General'];
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
        } catch (error) {
            console.error('Error loading vendors:', error);
            vendors = [];
        }
    }

    async function loadTransactions() {
        try {
            const response = await fetch('/api/personal/transactions');
            const data = await response.json();

            if (data.error) {
                console.error('Error loading transactions:', data.error);
                return;
            }

            allTransactions = data.transactions || [];
            filterTransactionsByFilters();
            updateSummary();
            renderCurrentTab();
        } catch (error) {
            console.error('Error loading transactions:', error);
        }
    }

    function updateSummary() {
        let income = 0;
        let expense = 0;

        transactions.forEach(t => {
            if (t.transaction_type === 'income') {
                income += parseFloat(t.amount);
            } else {
                expense += parseFloat(t.amount);
            }
        });

        elements.summaryIncome.textContent = formatAmount(income);
        elements.summaryExpense.textContent = formatAmount(expense);
    }

    // ============================================================================
    // RENDERING - DAILY VIEW
    // ============================================================================

    function renderDailyView() {
        filterTransactionsByFilters();
        updateSummary();

        if (transactions.length === 0) {
            elements.dailyTransactions.innerHTML = `
                <div class="empty-state">
                    <p>No transactions this month</p>
                    <p style="font-size: 0.8rem; margin-top: 8px;">Tap + to add your first entry</p>
                </div>
            `;
            return;
        }

        // Group transactions by date
        const grouped = groupByDate(transactions);
        let html = '';

        Object.keys(grouped).sort((a, b) => new Date(b) - new Date(a)).forEach(dateStr => {
            const dayTransactions = grouped[dateStr];
            const date = new Date(dateStr);
            const dayIncome = dayTransactions.filter(t => t.transaction_type === 'income').reduce((sum, t) => sum + parseFloat(t.amount), 0);
            const dayExpense = dayTransactions.filter(t => t.transaction_type === 'expense').reduce((sum, t) => sum + parseFloat(t.amount), 0);

            const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
            const months = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'];

            html += `
                <div class="date-group">
                    <div class="date-header">
                        <div class="date-info">
                            <span class="date-day">${String(date.getDate()).padStart(2, '0')}</span>
                            <span class="date-weekday">${days[date.getDay()]}</span>
                            <span class="date-month">${months[date.getMonth()]}.${date.getFullYear()}</span>
                        </div>
                        <div class="date-totals">
                            ${dayIncome > 0 ? `<span class="date-income">${formatCompact(dayIncome)}</span>` : ''}
                            ${dayExpense > 0 ? `<span class="date-expense">${formatCompact(dayExpense)}</span>` : ''}
                        </div>
                    </div>
                    <div class="date-transactions">
            `;

            dayTransactions.forEach(t => {
                const category = getCategoryInfo(t);
                const typeClass = t.transaction_type === 'income' ? 'income' : 'expense';

                const projectText = escapeHtml(t.project || 'General');
                const descText = t.description ? escapeHtml(t.description) : '';
                const metaText = descText ? `${projectText} • ${descText}` : projectText;

                // Bank badge
                let bankBadge = '';
                if (t.bank) {
                    const bankClass = t.bank === 'axis' ? 'bank-axis' : 'bank-kvb';
                    const bankName = t.bank.toUpperCase();
                    bankBadge = `<span class="bank-badge ${bankClass}">${bankName}</span>`;
                }

                html += `
                    <div class="transaction-row" data-id="${t.id}" onclick="handleTransactionClick(${t.id})">
                        <div class="transaction-category">
                            <span class="category-icon">${category.icon}</span>
                            <span class="category-name">${category.name}</span>
                        </div>
                        <div class="transaction-details">
                            <div class="transaction-vendor">${escapeHtml(t.vendor)}${bankBadge}</div>
                            <div class="transaction-project">${metaText}</div>
                        </div>
                        <div class="transaction-amount ${typeClass}">${formatCompact(t.amount)}</div>
                    </div>
                `;
            });

            html += `</div></div>`;
        });

        elements.dailyTransactions.innerHTML = html;
    }

    function getCategoryInfo(transaction) {
        // Try to match vendor to a category
        const vendor = transaction.vendor.toLowerCase();

        if (transaction.transaction_type === 'income') {
            if (vendor.includes('salary') || vendor.includes('wage')) return categoryIcons['Salary'];
            return categoryIcons['default_income'];
        }

        if (vendor.includes('food') || vendor.includes('restaurant') || vendor.includes('cafe') || vendor.includes('swiggy') || vendor.includes('zomato')) {
            return categoryIcons['Food'];
        }
        if (vendor.includes('uber') || vendor.includes('ola') || vendor.includes('petrol') || vendor.includes('fuel') || vendor.includes('transport')) {
            return categoryIcons['Transport'];
        }
        if (vendor.includes('amazon') || vendor.includes('flipkart') || vendor.includes('shop') || vendor.includes('mall')) {
            return categoryIcons['Shopping'];
        }
        if (vendor.includes('bill') || vendor.includes('electric') || vendor.includes('water') || vendor.includes('gas') || vendor.includes('rent')) {
            return categoryIcons['Bills'];
        }
        if (vendor.includes('movie') || vendor.includes('netflix') || vendor.includes('spotify') || vendor.includes('game')) {
            return categoryIcons['Entertainment'];
        }
        if (vendor.includes('hospital') || vendor.includes('doctor') || vendor.includes('pharmacy') || vendor.includes('medical')) {
            return categoryIcons['Health'];
        }
        if (vendor.includes('party') || vendor.includes('dinner') || vendor.includes('friend') || vendor.includes('split')) {
            return categoryIcons['Social Life'];
        }
        if (vendor.includes('invest') || vendor.includes('stock') || vendor.includes('mutual') || vendor.includes('sip')) {
            return categoryIcons['Investment'];
        }

        return categoryIcons['default_expense'];
    }

    // ============================================================================
    // RENDERING - MONTHLY VIEW
    // ============================================================================

    function renderMonthlyView() {
        // Group all transactions by month
        const monthlyData = {};

        allTransactions.forEach(t => {
            const date = new Date(t.date);
            const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;

            if (!monthlyData[key]) {
                monthlyData[key] = { income: 0, expense: 0, date: date };
            }

            if (t.transaction_type === 'income') {
                monthlyData[key].income += parseFloat(t.amount);
            } else {
                monthlyData[key].expense += parseFloat(t.amount);
            }
        });

        const sortedMonths = Object.keys(monthlyData).sort((a, b) => b.localeCompare(a));

        if (sortedMonths.length === 0) {
            elements.monthlyBreakdown.innerHTML = `
                <div class="empty-state">
                    <p>No transactions yet</p>
                </div>
            `;
            return;
        }

        const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

        let html = '';
        sortedMonths.forEach(key => {
            const data = monthlyData[key];
            const monthName = months[data.date.getMonth()];
            const year = data.date.getFullYear();

            html += `
                <div class="month-row" onclick="navigateToMonth(${data.date.getFullYear()}, ${data.date.getMonth()})">
                    <span class="month-name">${monthName} ${year}</span>
                    <div class="month-stats">
                        <span class="date-income">${formatCompact(data.income)}</span>
                        <span class="date-expense">${formatCompact(data.expense)}</span>
                    </div>
                </div>
            `;
        });

        elements.monthlyBreakdown.innerHTML = html;
    }

    // ============================================================================
    // RENDERING - TOTAL VIEW
    // ============================================================================

    function renderTotalView() {
        let totalIncome = 0;
        let totalExpense = 0;
        let incomeCount = 0;
        let expenseCount = 0;

        allTransactions.forEach(t => {
            if (t.transaction_type === 'income') {
                totalIncome += parseFloat(t.amount);
                incomeCount++;
            } else {
                totalExpense += parseFloat(t.amount);
                expenseCount++;
            }
        });

        elements.totalSummary.innerHTML = `
            <div class="total-card">
                <div class="total-card-header">Total Income</div>
                <div class="total-card-value income">${formatAmount(totalIncome)}</div>
                <div class="total-card-count">${incomeCount} transaction${incomeCount !== 1 ? 's' : ''}</div>
            </div>
            <div class="total-card">
                <div class="total-card-header">Total Expenses</div>
                <div class="total-card-value expense">${formatAmount(totalExpense)}</div>
                <div class="total-card-count">${expenseCount} transaction${expenseCount !== 1 ? 's' : ''}</div>
            </div>
        `;
    }

    // ============================================================================
    // RENDERING - PROJECTS VIEW
    // ============================================================================

    function renderProjectsView() {
        // Group expenses by project
        const projectData = {};
        let totalExpenses = 0;

        allTransactions.forEach(t => {
            if (t.transaction_type === 'expense') {
                const project = t.project || 'General';
                if (!projectData[project]) {
                    projectData[project] = { amount: 0, count: 0 };
                }
                projectData[project].amount += parseFloat(t.amount);
                projectData[project].count++;
                totalExpenses += parseFloat(t.amount);
            }
        });

        const sortedProjects = Object.keys(projectData).sort((a, b) =>
            projectData[b].amount - projectData[a].amount
        );

        if (sortedProjects.length === 0) {
            elements.projectsBreakdown.innerHTML = `
                <div class="empty-state">
                    <p>No expenses yet</p>
                </div>
            `;
            return;
        }

        let html = '';
        sortedProjects.forEach(project => {
            const data = projectData[project];
            const percentage = totalExpenses > 0 ? (data.amount / totalExpenses * 100).toFixed(0) : 0;

            html += `
                <div class="project-row">
                    <div class="project-info">
                        <div class="project-name">${escapeHtml(project)}</div>
                        <div class="project-bar">
                            <div class="project-bar-fill" style="width: ${percentage}%"></div>
                        </div>
                    </div>
                    <div class="project-stats">
                        <div class="project-amount">${formatCompact(data.amount)}</div>
                        <div class="project-meta">${data.count} txn | ${percentage}%</div>
                    </div>
                </div>
            `;
        });

        elements.projectsBreakdown.innerHTML = html;
    }

    // ============================================================================
    // MODAL HANDLING
    // ============================================================================

    function openAddModal() {
        elements.modalTitle.textContent = 'Add Transaction';
        elements.saveBtn.textContent = 'Save';
        elements.deleteBtn.style.display = 'none';
        elements.transactionId.value = '';
        elements.transactionForm.reset();
        setDefaultDate();
        setTransactionType('expense');
        setBank(''); // Clear bank selection
        elements.transactionModal.classList.add('show');
        setTimeout(() => elements.transactionAmount.focus(), 100);
    }

    function openEditModal(transaction) {
        elements.modalTitle.textContent = 'Edit Transaction';
        elements.saveBtn.textContent = 'Update';
        elements.deleteBtn.style.display = 'block';
        elements.transactionId.value = transaction.id;
        elements.transactionDate.value = transaction.date;
        elements.transactionAmount.value = transaction.amount;
        elements.transactionVendor.value = transaction.vendor;
        elements.transactionDescription.value = transaction.description || '';
        elements.transactionProject.value = transaction.project || 'General';
        setTransactionType(transaction.transaction_type || 'expense');
        setBank(transaction.bank || '');
        elements.transactionModal.classList.add('show');
    }

    function closeModal() {
        elements.transactionModal.classList.remove('show');
        elements.transactionForm.reset();
    }

    function openDeleteModal(transaction) {
        deleteTargetId = transaction.id;
        elements.deleteInfo.textContent = `${transaction.vendor} - ${formatAmount(transaction.amount)}`;
        elements.deleteModal.classList.add('show');
    }

    function closeDeleteModal() {
        elements.deleteModal.classList.remove('show');
        deleteTargetId = null;
    }

    function handleDeleteFromEdit() {
        const id = elements.transactionId.value;
        if (!id) return;

        const transaction = allTransactions.find(t => t.id == id);
        if (transaction) {
            closeModal();
            openDeleteModal(transaction);
        }
    }

    function setDefaultDate() {
        const today = new Date().toISOString().split('T')[0];
        elements.transactionDate.value = today;
    }

    function setTransactionType(type) {
        elements.transactionType.value = type;

        // Update bubble styles
        if (type === 'expense') {
            elements.typeExpenseBtn.classList.add('active');
            elements.typeIncomeBtn.classList.remove('active');
        } else {
            elements.typeIncomeBtn.classList.add('active');
            elements.typeExpenseBtn.classList.remove('active');
        }
    }

    function setBank(bank) {
        elements.transactionBank.value = bank;

        // Update bubble styles
        if (bank === 'axis') {
            elements.bankAxisBtn.classList.add('active');
            elements.bankKvbBtn.classList.remove('active');
        } else if (bank === 'kvb') {
            elements.bankKvbBtn.classList.add('active');
            elements.bankAxisBtn.classList.remove('active');
        } else {
            // Clear both if no bank selected
            elements.bankAxisBtn.classList.remove('active');
            elements.bankKvbBtn.classList.remove('active');
        }
    }

    // ============================================================================
    // FORM HANDLING
    // ============================================================================

    async function handleFormSubmit(e) {
        e.preventDefault();

        const id = elements.transactionId.value;
        const bankValue = elements.transactionBank.value;
        const data = {
            date: elements.transactionDate.value,
            amount: parseFloat(elements.transactionAmount.value),
            vendor: elements.transactionVendor.value.trim(),
            description: elements.transactionDescription.value.trim(),
            project: elements.transactionProject.value.trim() || 'General',
            transaction_type: elements.transactionType.value,
            bank: bankValue || null
        };

        if (!data.date || !data.vendor || !data.amount) {
            showToast('Please fill required fields', 'error');
            return;
        }

        try {
            elements.saveBtn.disabled = true;
            elements.saveBtn.textContent = 'Saving...';

            let response;
            if (id) {
                response = await fetch(`/api/personal/transactions/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
            } else {
                response = await fetch('/api/personal/transactions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
            }

            const result = await response.json();

            if (result.success) {
                showToast(id ? 'Updated!' : 'Added!', 'success');
                closeModal();
                loadData();
            } else {
                showToast(result.error || 'Failed to save', 'error');
            }
        } catch (error) {
            console.error('Error saving transaction:', error);
            showToast('Failed to save', 'error');
        } finally {
            elements.saveBtn.disabled = false;
            elements.saveBtn.textContent = id ? 'Update' : 'Save';
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
                showToast('Deleted!', 'success');
                closeDeleteModal();
                loadData();
            } else {
                showToast(result.error || 'Failed to delete', 'error');
            }
        } catch (error) {
            console.error('Error deleting transaction:', error);
            showToast('Failed to delete', 'error');
        } finally {
            elements.deleteConfirmBtn.disabled = false;
            elements.deleteConfirmBtn.textContent = 'Delete';
        }
    }

    // ============================================================================
    // UTILITIES
    // ============================================================================

    function groupByDate(transactions) {
        const grouped = {};
        transactions.forEach(t => {
            const date = t.date;
            if (!grouped[date]) {
                grouped[date] = [];
            }
            grouped[date].push(t);
        });
        return grouped;
    }

    function formatAmount(amount) {
        return new Intl.NumberFormat('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(amount);
    }

    function formatCompact(amount) {
        // Show full amount without compacting
        return formatAmount(amount);
    }

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
        }, 2000);
    }

    // ============================================================================
    // GLOBAL FUNCTIONS
    // ============================================================================

    window.handleTransactionClick = function(id) {
        const transaction = allTransactions.find(t => t.id === id);
        if (transaction) {
            openEditModal(transaction);
        }
    };

    window.navigateToMonth = function(year, month) {
        currentMonth = new Date(year, month, 1);
        updateMonthLabel();
        switchTab('daily');
        applyFilters();
    };

    // ============================================================================
    // START
    // ============================================================================

    document.addEventListener('DOMContentLoaded', init);
})();
