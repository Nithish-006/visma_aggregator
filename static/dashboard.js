// Bank code from page context (set in template)
const BANK_CODE = window.BANK_CODE || 'axis';
const BANK_NAME = window.BANK_NAME || 'Axis Bank';

// Global state
let charts = {};
let currentCategory = 'All';
let currentStartDate = null;
let currentEndDate = null;
let crossFilterActive = false;
let currentSortBy = 'date';
let currentSortOrder = 'desc';
let currentSearch = '';
let searchTimeout = null;
let dataMinDate = null;
let dataMaxDate = null;

// Mobile detection for chart optimizations
const isMobile = () => window.innerWidth <= 768;
const isSmallPhone = () => window.innerWidth <= 480;

// Mobile-optimized chart font settings
function getMobileChartDefaults() {
    if (isSmallPhone()) {
        return {
            titleFont: { size: 11 },
            bodyFont: { size: 10 },
            footerFont: { size: 9 },
            tickFont: { size: 9 },
            legendFont: { size: 9 },
            padding: 6
        };
    } else if (isMobile()) {
        return {
            titleFont: { size: 12 },
            bodyFont: { size: 11 },
            footerFont: { size: 10 },
            tickFont: { size: 10 },
            legendFont: { size: 10 },
            padding: 8
        };
    }
    return {
        titleFont: { size: 14 },
        bodyFont: { size: 13 },
        footerFont: { size: 12 },
        tickFont: { size: 12 },
        legendFont: { size: 12 },
        padding: 10
    };
}

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

function formatDateRangeForAPI(startDate, endDate) {
    // Returns object with start_date and end_date params
    const params = {};
    if (startDate) {
        params.start_date = startDate;
    }
    if (endDate) {
        params.end_date = endDate;
    }
    return params;
}

function buildApiUrl(endpoint, category, startDate, endDate, extraParams = {}) {
    // Build bank-specific API URL
    const baseUrl = `/api/${BANK_CODE}${endpoint}`;

    const params = new URLSearchParams();
    params.append('category', category || 'All');
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    // Add any extra params
    for (const [key, value] of Object.entries(extraParams)) {
        params.append(key, value);
    }

    return `${baseUrl}?${params.toString()}`;
}

/** Filters loading **/

async function loadDateRange() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/date_range`);
        const data = await res.json();

        if (data.min_date && data.max_date) {
            dataMinDate = data.min_date;
            dataMaxDate = data.max_date;

            const startInput = document.getElementById('start-date');
            const endInput = document.getElementById('end-date');

            if (startInput && endInput) {
                // Set the min/max constraints on the date inputs
                startInput.min = data.min_date;
                startInput.max = data.max_date;
                endInput.min = data.min_date;
                endInput.max = data.max_date;

                // Default: show all data (leave inputs empty)
                startInput.value = '';
                endInput.value = '';
            }
        }
    } catch (e) {
        console.error('Error loading date range:', e);
    }
}

async function loadCategories() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/categories`);
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

async function loadHeroSummary(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/summary', category, startDate, endDate);
        const res = await fetch(url);
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

        await loadSparkline(category, startDate, endDate);
    } catch (e) {
        console.error('Error loading hero summary:', e);
    }
}

/** Sparkline **/

async function loadSparkline(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/running_balance', category, startDate, endDate);
        const res = await fetch(url);
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

async function loadBalanceChart(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/running_balance', category, startDate, endDate);
        const res = await fetch(url);
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
                        padding: getMobileChartDefaults().padding,
                        titleFont: getMobileChartDefaults().titleFont,
                        bodyFont: getMobileChartDefaults().bodyFont,
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
                        displayColors: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        ticks: {
                            callback: (value) => formatIndianNumber(value),
                            font: { size: getMobileChartDefaults().tickFont.size },
                            maxTicksLimit: isMobile() ? 5 : 8
                        },
                        grid: { color: 'rgba(148,163,184,0.2)' }
                    },
                    x: {
                        ticks: {
                            maxTicksLimit: isMobile() ? 6 : 10,
                            font: { size: getMobileChartDefaults().tickFont.size }
                        },
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

async function loadMonthlyChart(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/monthly_trend', category, startDate, endDate);
        const res = await fetch(url);
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
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            boxWidth: isMobile() ? 10 : 14,
                            padding: isMobile() ? 8 : 12,
                            font: { size: getMobileChartDefaults().legendFont.size }
                        }
                    },
                    tooltip: {
                        padding: getMobileChartDefaults().padding,
                        titleFont: getMobileChartDefaults().titleFont,
                        bodyFont: getMobileChartDefaults().bodyFont,
                        callbacks: {
                            label: (ctx) =>
                                `${ctx.dataset.label}: ${formatIndianNumber(ctx.parsed.y)}`
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: (v) => formatIndianNumber(v),
                            font: { size: getMobileChartDefaults().tickFont.size },
                            maxTicksLimit: isMobile() ? 5 : 8
                        },
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    },
                    x: {
                        ticks: {
                            font: { size: getMobileChartDefaults().tickFont.size },
                            maxRotation: isMobile() ? 45 : 0,
                            minRotation: isMobile() ? 45 : 0
                        },
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

async function loadCategoryChart(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/category_breakdown', category, startDate, endDate);
        const res = await fetch(url);
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
                        position: isMobile() ? 'bottom' : 'right',
                        labels: {
                            boxWidth: isMobile() ? 10 : 12,
                            padding: isMobile() ? 6 : 8,
                            font: { size: getMobileChartDefaults().legendFont.size }
                        }
                    },
                    tooltip: {
                        padding: getMobileChartDefaults().padding,
                        titleFont: getMobileChartDefaults().titleFont,
                        bodyFont: getMobileChartDefaults().bodyFont,
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

async function loadVendorChart(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/top_vendors', category, startDate, endDate);
        const res = await fetch(url);
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
                        padding: getMobileChartDefaults().padding,
                        titleFont: getMobileChartDefaults().titleFont,
                        bodyFont: getMobileChartDefaults().bodyFont,
                        callbacks: {
                            label: (ctx) => 'Spent: ' + formatIndianNumber(ctx.parsed.x)
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)'
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: {
                            callback: (v) => formatIndianNumber(v),
                            font: { size: getMobileChartDefaults().tickFont.size },
                            maxTicksLimit: isMobile() ? 4 : 6
                        },
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    },
                    y: {
                        ticks: {
                            font: { size: getMobileChartDefaults().tickFont.size },
                            // Truncate long vendor names on mobile
                            callback: function(value, index) {
                                const label = this.getLabelForValue(value);
                                if (isMobile() && label.length > 15) {
                                    return label.substring(0, 15) + '...';
                                }
                                return label;
                            }
                        },
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    }
                }
            }
        });
    } catch (e) {
        console.error('Error loading vendor chart:', e);
    }
}



/** Insights **/

async function loadInsights(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/insights', category, startDate, endDate);
        const res = await fetch(url);
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

async function loadTransactions(category = 'All', startDate = null, endDate = null) {
    try {
        const url = buildApiUrl('/transactions', category, startDate, endDate, {
            limit: '10000',
            sort_by: currentSortBy,
            sort_order: currentSortOrder,
            search: currentSearch
        });
        const res = await fetch(url);
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
        <td>${txn.project || ''}</td>
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
    // When clicking on a month bar in the chart, filter to that month
    // Parse "April 2025" format and set date range for that month
    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
                        'July', 'August', 'September', 'October', 'November', 'December'];
    const parts = label.split(' ');
    if (parts.length !== 2) return;

    const monthName = parts[0];
    const year = parseInt(parts[1]);
    const monthIndex = monthNames.indexOf(monthName);
    if (monthIndex === -1 || isNaN(year)) return;

    // Set start date to first of the month
    const startDate = `${year}-${String(monthIndex + 1).padStart(2, '0')}-01`;

    // Set end date to last day of the month
    const lastDay = new Date(year, monthIndex + 1, 0).getDate();
    const endDate = `${year}-${String(monthIndex + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;

    currentStartDate = startDate;
    currentEndDate = endDate;

    // Update the UI
    document.getElementById('start-date').value = startDate;
    document.getElementById('end-date').value = endDate;

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
        loadHeroSummary(currentCategory, currentStartDate, currentEndDate),
        loadBalanceChart(currentCategory, currentStartDate, currentEndDate),
        loadMonthlyChart(currentCategory, currentStartDate, currentEndDate),
        loadCategoryChart(currentCategory, currentStartDate, currentEndDate),
        loadVendorChart(currentCategory, currentStartDate, currentEndDate),
        loadInsights(currentCategory, currentStartDate, currentEndDate),
        loadTransactions(currentCategory, currentStartDate, currentEndDate)
    ]);
    hideLoading();
}

// Alias for edit.js compatibility
window.loadDashboardData = runFullRefresh;

/** Init **/

document.addEventListener('DOMContentLoaded', async () => {
    showLoading();

    await Promise.all([loadCategories(), loadDateRange()]);

    // default filter state
    currentCategory = 'All';
    currentStartDate = null;
    currentEndDate = null;

    // Helper function to get date N days ago
    function getDateNDaysAgo(n) {
        const date = new Date();
        date.setDate(date.getDate() - n);
        return date.toISOString().split('T')[0];
    }

    // Helper function to get first day of current month
    function getFirstDayOfMonth() {
        const date = new Date();
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-01`;
    }

    // Helper function to get today's date
    function getToday() {
        return new Date().toISOString().split('T')[0];
    }

    // Scenario chips for date ranges
    document.querySelectorAll('.chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            document
                .querySelectorAll('.chip')
                .forEach((c) => c.classList.remove('chip-active'));
            chip.classList.add('chip-active');
            const scenario = chip.dataset.scenario;

            const startInput = document.getElementById('start-date');
            const endInput = document.getElementById('end-date');

            if (scenario === 'all') {
                currentStartDate = null;
                currentEndDate = null;
                startInput.value = '';
                endInput.value = '';
            } else if (scenario === 'last7') {
                currentStartDate = getDateNDaysAgo(7);
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            } else if (scenario === 'last14') {
                currentStartDate = getDateNDaysAgo(14);
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            } else if (scenario === 'last30') {
                currentStartDate = getDateNDaysAgo(30);
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            } else if (scenario === 'thisMonth') {
                currentStartDate = getFirstDayOfMonth();
                currentEndDate = getToday();
                startInput.value = currentStartDate;
                endInput.value = currentEndDate;
            }
            runFullRefresh();
        });
    });


    // Apply / Clear
    document.getElementById('apply-filters').addEventListener('click', () => {
        const catSelect = document.getElementById('category-filter');
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');

        currentCategory = catSelect.value || 'All';
        currentStartDate = startInput.value || null;
        currentEndDate = endInput.value || null;

        // Clear chip selection when manually applying filters
        document
            .querySelectorAll('.chip')
            .forEach((c) => c.classList.remove('chip-active'));

        crossFilterActive = false;
        runFullRefresh();
    });

    document.getElementById('clear-filters').addEventListener('click', () => {
        const catSelect = document.getElementById('category-filter');
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');

        currentCategory = 'All';
        currentStartDate = null;
        currentEndDate = null;

        catSelect.value = 'All';
        startInput.value = '';
        endInput.value = '';

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
        const params = new URLSearchParams();
        params.append('category', currentCategory || 'All');
        if (currentStartDate) params.append('start_date', currentStartDate);
        if (currentEndDate) params.append('end_date', currentEndDate);

        window.location.href = `/api/${BANK_CODE}/download_transactions?${params.toString()}`;
    });

    // Search listener
    const searchInput = document.getElementById('transaction-search');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            currentSearch = e.target.value;
            if (searchTimeout) clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                loadTransactions(currentCategory, currentStartDate, currentEndDate);
            }, 300);
        });
    }

    // Sort listeners
    document.querySelectorAll('.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const field = th.dataset.sort;
            if (currentSortBy === field) {
                // Toggle order
                currentSortOrder = currentSortOrder === 'desc' ? 'asc' : 'desc';
            } else {
                currentSortBy = field;
                currentSortOrder = 'desc'; // Default to desc for new field
            }

            // Update UI
            document.querySelectorAll('.sortable').forEach(h => {
                h.classList.remove('header-sort-active');
                h.querySelector('.sort-icon').textContent = '';
            });
            th.classList.add('header-sort-active');
            th.querySelector('.sort-icon').textContent = currentSortOrder === 'desc' ? '↓' : '↑';

            loadTransactions(currentCategory, currentStartDate, currentEndDate);
        });
    });

    await runFullRefresh();
});
