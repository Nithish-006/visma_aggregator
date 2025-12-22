// Global state
let charts = {};
let currentCategory = 'All';
let currentMonths = ['All'];
let crossFilterActive = false;

/** Utilities **/

function formatIndianNumber(amount) {
    if (!amount || amount === 0) return '₹0';

    const absAmount = Math.abs(amount);
    const sign = amount < 0 ? '-' : '';

    if (absAmount >= 10000000) {
        return `${sign}₹${(absAmount / 10000000).toFixed(2)} Cr`;
    } else if (absAmount >= 100000) {
        return `${sign}₹${(absAmount / 100000).toFixed(2)} L`;
    } else if (absAmount >= 1000) {
        return `${sign}₹${(absAmount / 1000).toFixed(2)} K`;
    } else {
        return `${sign}₹${absAmount.toFixed(0)}`;
    }
}

function showLoading() {
    document.getElementById('loading-overlay')?.classList.remove('hidden');
}

function hideLoading() {
    document.getElementById('loading-overlay')?.classList.add('hidden');
}

function formatMonthsForAPI(months) {
    if (!months || months.length === 0 || (months.length === 1 && months[0] === 'All')) {
        return 'All';
    }
    return months.join(',');
}

/** Filters loading **/

async function loadMonths() {
    try {
        const res = await fetch('/api/months');
        const data = await res.json();

        const select = $('#month-filter');
        select.empty();

        // Use the synchronized data from backend
        if (data.months_data) {
            data.months_data.forEach((item) => {
                const opt = new Option(item.label, item.value, false, false);
                select.append(opt);
            });
        }

        // Use Select2
        select.select2({
            placeholder: 'All months',
            allowClear: true,
            width: 'resolve'
        });
    } catch (e) {
        console.error('Error loading months:', e);
    }
}

async function loadCategories() {
    try {
        const res = await fetch('/api/categories');
        const data = await res.json();
        const select = document.getElementById('category-filter');
        if (!select) return;

        select.innerHTML = '';
        data.categories.forEach((cat) => {
            const option = document.createElement('option');
            option.value = cat;
            option.textContent = cat;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('Error loading categories:', e);
    }
}

/** Hero summary **/

async function loadHeroSummary(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/summary?category=${encodeURIComponent(category)}&month=${encodeURIComponent(
                monthParam
            )}`
        );
        const data = await res.json();

        // Header count
        document.getElementById('total-transactions').textContent = `${data.total_transactions} Transactions`;

        // KPIs
        document.getElementById('hero-current-balance').textContent =
            data.current_balance_formatted;
        document.getElementById('kpi-total-income').textContent =
            data.total_income_formatted;
        document.getElementById('kpi-total-expense').textContent =
            data.total_expense_formatted;
        document.getElementById('kpi-net-cashflow').textContent =
            data.net_cashflow_formatted;
        document.getElementById('kpi-expense-ratio').textContent = `${data.expense_ratio}%`;

        // Month comparison
        document.getElementById('month-comparison-net').textContent =
            data.this_month_net_formatted;
        const deltaElement = document.getElementById('month-comparison-delta');
        const deltaValue = deltaElement.querySelector('.delta-value');
        const deltaArrow = deltaElement.querySelector('.delta-arrow');
        if (data.net_change_pct !== undefined) {
            const isPositive = data.net_change_pct >= 0;
            deltaValue.textContent = `${isPositive ? '+' : ''}${data.net_change_pct.toFixed(
                1
            )}%`;
            deltaValue.className = `delta-value ${isPositive ? '' : 'negative'}`;
            deltaArrow.textContent = isPositive ? '↑' : '↓';
        }

        // Biggest category card
        if (data.biggest_category) {
            document.getElementById('biggest-category-name').textContent =
                data.biggest_category;
            document.getElementById('biggest-category-amount').textContent =
                data.biggest_category_amount_formatted;
        } else {
            document.getElementById('biggest-category-name').textContent = '–';
            document.getElementById('biggest-category-amount').textContent = '₹0';
        }

        await loadSparkline(category, months);
    } catch (e) {
        console.error('Error loading hero summary:', e);
    }
}

/** Sparkline **/

async function loadSparkline(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/running_balance?category=${encodeURIComponent(category)}&month=${encodeURIComponent(
                monthParam
            )}`
        );
        const data = await res.json();
        if (!data.sparkline_dates || data.sparkline_dates.length === 0) return;

        const ctx = document.getElementById('heroSparkline').getContext('2d');
        if (charts.heroSparkline) charts.heroSparkline.destroy();

        charts.heroSparkline = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.sparkline_dates,
                datasets: [
                    {
                        label: 'Balance',
                        data: data.sparkline_balance,
                        borderColor: 'rgba(255,255,255,0.85)',
                        backgroundColor: 'rgba(255,255,255,0.12)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 0,
                        pointHoverRadius: 3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => 'Balance: ' + formatIndianNumber(ctx.parsed.y)
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)',
                        padding: 8,
                        displayColors: false
                    }
                },
                scales: {
                    x: { display: false },
                    y: { display: false }
                }
            }
        });
    } catch (e) {
        console.error('Error loading sparkline:', e);
    }
}

/** Balance chart **/

async function loadBalanceChart(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/running_balance?category=${encodeURIComponent(category)}&month=${encodeURIComponent(
                monthParam
            )}`
        );
        const data = await res.json();

        const ctx = document.getElementById('balanceChart').getContext('2d');
        if (charts.balanceChart) charts.balanceChart.destroy();

        const balances = data.balance || [];
        const minBalance = Math.min(...balances);
        const maxBalance = Math.max(...balances);
        const range = maxBalance - minBalance;
        const comfortMin = minBalance + range * 0.25;
        const comfortMax = maxBalance - range * 0.25;

        // Insight badge text
        if (data.lowest_balance !== undefined && data.peak_balance !== undefined) {
            const badge = document.getElementById('balance-insight');
            if (badge) {
                badge.textContent = `Lowest: ${formatIndianNumber(
                    data.lowest_balance
                )} • Peak: ${formatIndianNumber(data.peak_balance)}`;
            }
        }

        const ds = [
            {
                label: 'Balance',
                data: balances,
                borderColor: '#4a6cf7',
                backgroundColor: 'rgba(74,108,247,0.08)',
                borderWidth: 2.5,
                fill: true,
                tension: 0.35
            }
        ];

        if (comfortMin !== comfortMax && Number.isFinite(comfortMin) && Number.isFinite(comfortMax)) {
            ds.push({
                label: 'Comfort Zone',
                data: balances.map(() => comfortMin),
                borderColor: 'rgba(16,185,129,0.3)',
                borderDash: [5, 4],
                borderWidth: 1,
                fill: false,
                pointRadius: 0
            });
            ds.push({
                label: 'Comfort Zone Max',
                data: balances.map(() => comfortMax),
                borderColor: 'rgba(16,185,129,0.3)',
                borderDash: [5, 4],
                borderWidth: 1,
                fill: false,
                pointRadius: 0
            });
        }

        if (data.lowest_balance !== undefined && data.peak_balance !== undefined) {
            const lowIdx = balances.indexOf(data.lowest_balance);
            const peakIdx = balances.indexOf(data.peak_balance);

            if (lowIdx !== -1) {
                ds.push({
                    label: 'Lowest',
                    data: balances.map((v, i) => (i === lowIdx ? v : null)),
                    borderColor: '#ef4444',
                    backgroundColor: '#ef4444',
                    borderWidth: 0,
                    pointRadius: 5,
                    pointHoverRadius: 7
                });
            }
            if (peakIdx !== -1) {
                ds.push({
                    label: 'Peak',
                    data: balances.map((v, i) => (i === peakIdx ? v : null)),
                    borderColor: '#22c55e',
                    backgroundColor: '#22c55e',
                    borderWidth: 0,
                    pointRadius: 5,
                    pointHoverRadius: 7
                });
            }
        }

        charts.balanceChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.dates || [],
                datasets: ds
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                if (ctx.dataset.label === 'Lowest') {
                                    return `Lowest balance: ${formatIndianNumber(ctx.parsed.y)}`;
                                }
                                if (ctx.dataset.label === 'Peak') {
                                    return `Peak balance: ${formatIndianNumber(ctx.parsed.y)}`;
                                }
                                if (ctx.dataset.label === 'Comfort Zone') return null;
                                return 'Balance: ' + formatIndianNumber(ctx.parsed.y);
                            }
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)',
                        padding: 10,
                        displayColors: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        ticks: {
                            callback: (value) => formatIndianNumber(value)
                        },
                        grid: { color: 'rgba(148,163,184,0.2)' }
                    },
                    x: {
                        ticks: { maxTicksLimit: 10 },
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    }
                }
            }
        });
    } catch (e) {
        console.error('Error loading balance chart:', e);
    }
}

/** Monthly chart **/

async function loadMonthlyChart(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/monthly_trend?category=${encodeURIComponent(category)}&month=${encodeURIComponent(
                monthParam
            )}`
        );
        const data = await res.json();

        const ctx = document.getElementById('monthlyChart').getContext('2d');
        if (charts.monthlyChart) charts.monthlyChart.destroy();

        // Insight badge
        if (data.highest_expense_month) {
            const badge = document.getElementById('monthly-insight');
            if (badge) {
                badge.textContent = `Highest expense: ${data.highest_expense_month} (${data.highest_expense_amount_formatted}, ${data.highest_expense_pct > 0 ? '+' : ''
                    }${data.highest_expense_pct}% vs avg)`;
            }
        }

        const netColors = (data.net || []).map((v) => (v >= 0 ? '#22c55e' : '#ef4444'));

        charts.monthlyChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.months || [],
                datasets: [
                    {
                        label: 'Income',
                        data: data.income,
                        backgroundColor: '#22c55e',
                        borderRadius: 8,
                        order: 2
                    },
                    {
                        label: 'Expense',
                        data: data.expense,
                        backgroundColor: '#ef4444',
                        borderRadius: 8,
                        order: 2
                    },
                    {
                        label: 'Net',
                        data: data.net,
                        type: 'line',
                        borderColor: netColors,
                        backgroundColor: 'transparent',
                        borderWidth: 2.5,
                        tension: 0.35,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: netColors,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        order: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, position: 'top' },
                    tooltip: {
                        callbacks: {
                            label: (ctx) =>
                                `${ctx.dataset.label}: ${formatIndianNumber(ctx.parsed.y)}`
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)',
                        padding: 10
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { callback: (v) => formatIndianNumber(v) },
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    },
                    x: {
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    }
                }
            }
        });

        // Click to filter by month
        setTimeout(() => {
            if (charts.monthlyChart) {
                charts.monthlyChart.canvas.onclick = function (evt) {
                    const points = charts.monthlyChart.getElementsAtEventForMode(
                        evt,
                        'nearest',
                        { intersect: true },
                        true
                    );
                    if (points.length) {
                        const first = points[0];
                        const label = charts.monthlyChart.data.labels[first.index];
                        filterByMonthFromLabel(label);
                    }
                };
            }
        }, 100);
    } catch (e) {
        console.error('Error loading monthly chart:', e);
    }
}

/** Category chart **/

async function loadCategoryChart(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/category_breakdown?category=${encodeURIComponent(category)}&month=${encodeURIComponent(
                monthParam
            )}`
        );
        const data = await res.json();

        const ctx = document.getElementById('categoryChart').getContext('2d');
        if (charts.categoryChart) charts.categoryChart.destroy();

        if (data.top_category) {
            const badge = document.getElementById('category-insight');
            if (badge) {
                badge.textContent = `Top category: ${data.top_category} (${data.top_category_pct}% of total)`;
            }
        }

        const total = data.amounts.reduce((a, b) => a + b, 0);
        const baseColors = [
            [74, 108, 247],
            [79, 70, 229],
            [34, 197, 94],
            [239, 68, 68],
            [245, 158, 11],
            [59, 130, 246],
            [139, 92, 246],
            [16, 185, 129],
            [249, 115, 22],
            [148, 163, 184]
        ];
        const colors = data.categories.map((_, idx) => {
            const pct = (data.amounts[idx] / total) * 100;
            const intensity = Math.min(0.35 + (pct / 100) * 0.65, 1);
            const base = baseColors[idx % baseColors.length];
            return `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${intensity})`;
        });

        charts.categoryChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.categories,
                datasets: [
                    {
                        data: data.amounts,
                        backgroundColor: colors,
                        borderWidth: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'right',
                        labels: { boxWidth: 12, padding: 8 }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const label = ctx.label || '';
                                const value = formatIndianNumber(ctx.parsed);
                                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                const pct = ((ctx.parsed / total) * 100).toFixed(1);
                                return `${label}: ${value} (${pct}%)`;
                            }
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)',
                        padding: 10
                    }
                }
            }
        });

        // Click to filter by category
        setTimeout(() => {
            if (charts.categoryChart) {
                charts.categoryChart.canvas.onclick = function (evt) {
                    const points = charts.categoryChart.getElementsAtEventForMode(
                        evt,
                        'nearest',
                        { intersect: true },
                        true
                    );
                    if (points.length) {
                        const label = charts.categoryChart.data.labels[points[0].index];
                        filterByCategory(label);
                    }
                };
            }
        }, 100);
    } catch (e) {
        console.error('Error loading category chart:', e);
    }
}

/** Vendors chart **/

async function loadVendorChart(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/top_vendors?category=${encodeURIComponent(category)}&month=${encodeURIComponent(
                monthParam
            )}`
        );
        const data = await res.json();

        const ctx = document.getElementById('vendorChart').getContext('2d');
        if (charts.vendorChart) charts.vendorChart.destroy();

        if (data.top_vendor) {
            const badge = document.getElementById('vendor-insight');
            if (badge) {
                badge.textContent = `Top vendor: ${data.top_vendor} (${data.top_vendor_amount_formatted})`;
            }
        }

        const colors = data.amounts.map((a) =>
            a >= data.threshold ? '#ef4444' : '#9ca3af'
        );

        charts.vendorChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.vendors,
                datasets: [
                    {
                        label: 'Total spent',
                        data: data.amounts,
                        backgroundColor: colors,
                        borderRadius: 8
                    }
                ]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => 'Spent: ' + formatIndianNumber(ctx.parsed.x)
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)',
                        padding: 10
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: { callback: (v) => formatIndianNumber(v) },
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    },
                    y: { grid: { color: 'rgba(148,163,184,0.18)' } }
                }
            }
        });
    } catch (e) {
        console.error('Error loading vendor chart:', e);
    }
}



/** Insights **/

async function loadInsights(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/insights?category=${encodeURIComponent(category)}&month=${encodeURIComponent(
                monthParam
            )}`
        );
        const data = await res.json();

        document.getElementById('avg-monthly-expense').textContent =
            data.avg_monthly_expense_formatted;
        document.getElementById(
            'avg-expense-desc'
        ).textContent = `Based on ${data.total_months} months`;

        const trendElement = document.getElementById('expense-trend');
        const trendDesc = document.getElementById('expense-trend-desc');

        if (data.expense_trend_direction === 'increasing') {
            trendElement.textContent = `+${data.expense_trend_pct}%`;
            trendElement.style.color = '#ef4444';
            trendDesc.textContent = 'Expenses are increasing';
        } else if (data.expense_trend_direction === 'decreasing') {
            trendElement.textContent = `${data.expense_trend_pct}%`;
            trendElement.style.color = '#22c55e';
            trendDesc.textContent = 'Expenses are decreasing';
        } else {
            trendElement.textContent = 'Stable';
            trendElement.style.color = '#6b7280';
            trendDesc.textContent = 'Insufficient data for trend';
        }

        document.getElementById('avg-transaction-size').textContent =
            data.avg_transaction_size_formatted;
        document.getElementById('avg-transaction-desc').textContent =
            'Mean transaction amount';

        if (data.peak_day) {
            document.getElementById('peak-day').textContent = data.peak_day;
            document.getElementById(
                'peak-day-desc'
            ).textContent = `${data.peak_day_amount_formatted} typically spent`;
        } else {
            document.getElementById('peak-day').textContent = 'N/A';
            document.getElementById('peak-day-desc').textContent = 'No data available';
        }

        document.getElementById(
            'cashflow-velocity'
        ).textContent = `${Math.round(data.cashflow_velocity)} transactions`;
        document.getElementById('velocity-desc').textContent = 'Average per month';
    } catch (e) {
        console.error('Error loading insights:', e);
    }
}

/** Transactions **/

async function loadTransactions(category = 'All', months = ['All']) {
    try {
        const monthParam = formatMonthsForAPI(months);
        const res = await fetch(
            `/api/transactions?category=${encodeURIComponent(
                category
            )}&month=${encodeURIComponent(monthParam)}&limit=10000`
        );
        const data = await res.json();

        const tbody = document.getElementById('transactions-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        data.transactions.forEach((txn) => {
            const row = document.createElement('tr');
            let netClass = 'amount-net';
            if (txn.net > 0) netClass += ' amount-credit';
            else if (txn.net < 0) netClass += ' amount-debit';

            row.innerHTML = `
        <td>${txn.date}</td>
        <td>${txn.vendor}</td>
        <td>${txn.category}</td>
        <td>${txn.description || ''}</td>
        <td class="text-right">${txn.dr_amount > 0 ? `<span class="monetary-pill debit">${txn.dr_amount_formatted}</span>` : ''}</td>
        <td class="text-right">${txn.cr_amount > 0 ? `<span class="monetary-pill credit">${txn.cr_amount_formatted}</span>` : ''}</td>
        <td class="text-right"><span class="monetary-pill ${txn.net > 0 ? 'credit' : (txn.net < 0 ? 'debit' : 'neutral')}">${txn.net_formatted}</span></td>
      `;
            tbody.appendChild(row);
        });
    } catch (e) {
        console.error('Error loading transactions:', e);
    }
}

/** Cross‑filter helpers **/

function filterByMonthFromLabel(label) {
    if (!label) return;
    // Expect something like "April 2025" in month_name
    const select = $('#month-filter');
    const matching = Array.from(select[0].options).find(
        (opt) => opt.textContent === label
    );
    if (!matching) return;
    currentMonths = [matching.value];
    select.val(currentMonths).trigger('change');
    crossFilterActive = true;
    runFullRefresh();
}

function filterByCategory(category) {
    const select = document.getElementById('category-filter');
    if (!select) return;
    currentCategory = category;
    select.value = category;
    crossFilterActive = true;
    runFullRefresh();
}

/** Refresh **/

async function runFullRefresh() {
    showLoading();
    await Promise.all([
        loadHeroSummary(currentCategory, currentMonths),
        loadBalanceChart(currentCategory, currentMonths),
        loadMonthlyChart(currentCategory, currentMonths),
        loadCategoryChart(currentCategory, currentMonths),
        loadVendorChart(currentCategory, currentMonths),
        loadVendorChart(currentCategory, currentMonths),
        loadInsights(currentCategory, currentMonths),
        loadTransactions(currentCategory, currentMonths)
    ]);
    hideLoading();
}

/** Init **/

document.addEventListener('DOMContentLoaded', async () => {
    showLoading();

    await Promise.all([loadCategories(), loadMonths()]);

    // default filter state
    currentCategory = 'All';
    currentMonths = ['All'];

    // Scenario chips
    document.querySelectorAll('.chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            document
                .querySelectorAll('.chip')
                .forEach((c) => c.classList.remove('chip-active'));
            chip.classList.add('chip-active');
            const scenario = chip.dataset.scenario;
            const monthSelect = $('#month-filter');

            if (scenario === 'all') {
                currentMonths = ['All'];
                monthSelect.val(null).trigger('change');
            } else if (scenario === 'current') {
                // Let backend pick latest; just set All but treat as scenario
                currentMonths = ['All'];
            } else if (scenario === 'last3') {
                // leave selection; business logic could be added here if needed
                currentMonths = ['All'];
            }
            runFullRefresh();
        });
    });


    // Apply / Clear
    document.getElementById('apply-filters').addEventListener('click', () => {
        const catSelect = document.getElementById('category-filter');
        const monthSelect = $('#month-filter');

        currentCategory = catSelect.value || 'All';
        const selectedMonths = monthSelect.val();
        currentMonths = selectedMonths && selectedMonths.length > 0 ? selectedMonths : ['All'];

        // Handle "All" logic - if specific months are selected, remove All
        if (currentMonths.length > 1 && currentMonths.includes('All')) {
            currentMonths = currentMonths.filter(m => m !== 'All');
            // update UI to reflect removal of All
            monthSelect.val(currentMonths).trigger('change.select2');
        }

        crossFilterActive = false;
        runFullRefresh();
    });

    document.getElementById('clear-filters').addEventListener('click', () => {
        const catSelect = document.getElementById('category-filter');
        const monthSelect = $('#month-filter');

        currentCategory = 'All';
        currentMonths = ['All'];

        catSelect.value = 'All';
        monthSelect.val(null).trigger('change');

        document
            .querySelectorAll('.chip')
            .forEach((c) => c.classList.remove('chip-active'));
        document
            .querySelector('.chip[data-scenario="all"]')
            ?.classList.add('chip-active');

        crossFilterActive = false;
        runFullRefresh();
    });

    // Download Transactions
    document.getElementById('download-transactions')?.addEventListener('click', () => {
        const monthParam = formatMonthsForAPI(currentMonths);
        const url = `/api/download_transactions?category=${encodeURIComponent(
            currentCategory
        )}&month=${encodeURIComponent(monthParam)}`;
        window.location.href = url;
    });

    await runFullRefresh();
});
