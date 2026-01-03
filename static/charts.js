// Bank code from page context (set in template)
const BANK_CODE = window.BANK_CODE || 'axis';
const BANK_NAME = window.BANK_NAME || 'Axis Bank';

// Check if Chart.js is loaded
if (typeof Chart === 'undefined') {
    console.error('Chart.js is not loaded! Charts will not render.');
    document.addEventListener('DOMContentLoaded', () => {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.innerHTML = `
                <div style="color: #ef4444; text-align: center; padding: 20px;">
                    <h2>Charts Failed to Load</h2>
                    <p>Chart.js library could not be loaded. Please check your internet connection and refresh the page.</p>
                    <button onclick="location.reload()" style="margin-top: 15px; padding: 10px 20px; background: #4a6cf7; color: white; border: none; border-radius: 8px; cursor: pointer;">
                        Refresh Page
                    </button>
                </div>
            `;
        }
    });
}

// Global state
let charts = {};
let currentCategory = 'All';
let currentProject = 'All';
let currentStartDate = null;
let currentEndDate = null;
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
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.classList.remove('hidden');
        overlay.style.display = 'flex';
    }
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
        // Fallback: also set display to none after transition
        setTimeout(() => {
            if (overlay.classList.contains('hidden')) {
                overlay.style.display = 'none';
            }
        }, 350);
    }
}

function buildApiUrl(endpoint, category, startDate, endDate, project = 'All', extraParams = {}) {
    const baseUrl = `/api/${BANK_CODE}${endpoint}`;

    const params = new URLSearchParams();
    params.append('category', category || 'All');
    if (project && project !== 'All') params.append('project', project);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    for (const [key, value] of Object.entries(extraParams)) {
        params.append(key, value);
    }

    return `${baseUrl}?${params.toString()}`;
}

/** Filters loading **/

async function loadDateRange() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/date_range`);

        if (!res.ok) {
            console.error('[Charts] Date range API error:', res.status);
            return;
        }

        const data = await res.json();
        console.log('[Charts] Date range loaded:', data);

        if (data.min_date && data.max_date) {
            dataMinDate = data.min_date;
            dataMaxDate = data.max_date;

            const startInput = document.getElementById('start-date');
            const endInput = document.getElementById('end-date');

            if (startInput && endInput) {
                startInput.min = data.min_date;
                startInput.max = data.max_date;
                endInput.min = data.min_date;
                endInput.max = data.max_date;
                startInput.value = '';
                endInput.value = '';
            }
        }
    } catch (e) {
        console.error('[Charts] Error loading date range:', e);
    }
}

async function loadCategories() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/categories`);

        // Handle authentication errors
        if (res.status === 401 || res.status === 403) {
            console.error('[Charts] Authentication error - redirecting to login');
            window.location.href = '/login';
            return;
        }

        if (!res.ok) {
            console.error('[Charts] Categories API error:', res.status);
            return;
        }

        const data = await res.json();
        console.log('[Charts] Categories loaded:', data.categories?.length || 0);

        const select = document.getElementById('category-filter');
        if (!select) return;

        select.innerHTML = '';
        (data.categories || ['All']).forEach((cat) => {
            const option = document.createElement('option');
            option.value = cat;
            option.textContent = cat;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('[Charts] Error loading categories:', e);
    }
}

async function loadProjects() {
    try {
        const res = await fetch(`/api/${BANK_CODE}/transactions?limit=10000`);

        // Handle authentication errors
        if (res.status === 401 || res.status === 403) {
            console.error('[Charts] Authentication error in loadProjects');
            return;
        }

        if (!res.ok) {
            console.error('[Charts] Transactions API error:', res.status);
            return;
        }

        const data = await res.json();
        console.log('[Charts] Transactions loaded for projects:', data.transactions?.length || 0);

        const select = document.getElementById('project-filter');
        if (!select) return;

        const uniqueProjects = new Set();
        (data.transactions || []).forEach((txn) => {
            const project = txn.project || txn.Project;
            if (project && project.trim()) {
                uniqueProjects.add(project.trim());
            }
        });

        const sortedProjects = Array.from(uniqueProjects).sort();

        select.innerHTML = '<option value="All">All Projects</option>';
        sortedProjects.forEach((proj) => {
            const option = document.createElement('option');
            option.value = proj;
            option.textContent = proj;
            select.appendChild(option);
        });
    } catch (e) {
        console.error('[Charts] Error loading projects:', e);
    }
}

/** Summary (Total Income & Expense) **/

async function loadSummary(category = 'All', startDate = null, endDate = null, project = 'All') {
    try {
        const url = buildApiUrl('/summary', category, startDate, endDate, project);
        console.log('[Charts] Fetching summary from:', url);
        const res = await fetch(url);

        if (!res.ok) {
            console.error('[Charts] Summary API error:', res.status, res.statusText);
            return;
        }

        const data = await res.json();
        console.log('[Charts] Summary data received:', data);

        const incomeEl = document.getElementById('kpi-total-income');
        const expenseEl = document.getElementById('kpi-total-expense');

        if (incomeEl) incomeEl.textContent = data.total_income_formatted || '₹0';
        if (expenseEl) expenseEl.textContent = data.total_expense_formatted || '₹0';
    } catch (e) {
        console.error('[Charts] Error loading summary:', e);
    }
}

/** Category chart **/

async function loadCategoryChart(category = 'All', startDate = null, endDate = null, project = 'All') {
    try {
        const url = buildApiUrl('/category_breakdown', category, startDate, endDate, project);
        console.log('[Charts] Fetching category breakdown from:', url);
        const res = await fetch(url);

        if (!res.ok) {
            console.error('[Charts] Category chart API error:', res.status, res.statusText);
            return;
        }

        const data = await res.json();
        console.log('[Charts] Category data received:', data);

        if (!data.categories || data.categories.length === 0) {
            console.log('[Charts] No category data available');
            return;
        }

        const canvas = document.getElementById('categoryChart');
        if (!canvas) {
            console.error('categoryChart canvas not found');
            return;
        }

        const ctx = canvas.getContext('2d');
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
                            font: { size: getMobileChartDefaults().legendFont.size },
                            color: '#ffffff'
                        }
                    },
                    tooltip: {
                        padding: getMobileChartDefaults().padding,
                        titleFont: getMobileChartDefaults().titleFont,
                        bodyFont: getMobileChartDefaults().bodyFont,
                        titleColor: '#ffffff',
                        bodyColor: '#ffffff',
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
    } catch (e) {
        console.error('Error loading category chart:', e);
    }
}

/** Vendors chart **/

async function loadVendorChart(category = 'All', startDate = null, endDate = null, project = 'All') {
    try {
        const url = buildApiUrl('/top_vendors', category, startDate, endDate, project);
        console.log('[Charts] Fetching top vendors from:', url);
        const res = await fetch(url);

        if (!res.ok) {
            console.error('[Charts] Vendor chart API error:', res.status, res.statusText);
            return;
        }

        const data = await res.json();
        console.log('[Charts] Vendor data received:', data);

        if (!data.vendors || data.vendors.length === 0) {
            console.log('[Charts] No vendor data available');
            return;
        }

        const canvas = document.getElementById('vendorChart');
        if (!canvas) {
            console.error('vendorChart canvas not found');
            return;
        }

        const ctx = canvas.getContext('2d');
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
                        titleColor: '#ffffff',
                        bodyColor: '#ffffff',
                        callbacks: {
                            label: (ctx) => 'Spent: ' + formatIndianNumber(ctx.parsed.x)
                        },
                        backgroundColor: 'rgba(15,23,42,0.95)'
                    },
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: {
                            callback: (v) => formatIndianNumber(v),
                            font: { size: getMobileChartDefaults().tickFont.size },
                            maxTicksLimit: isMobile() ? 4 : 6,
                            color: '#ffffff'
                        },
                        grid: { color: 'rgba(148,163,184,0.18)' }
                    },
                    y: {
                        ticks: {
                            font: { size: getMobileChartDefaults().tickFont.size },
                            color: '#ffffff',
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

async function loadInsights(category = 'All', startDate = null, endDate = null, project = 'All') {
    try {
        const url = buildApiUrl('/insights', category, startDate, endDate, project);
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

/** Refresh **/

async function runFullRefresh() {
    console.log('[Charts] runFullRefresh starting...');
    showLoading();
    try {
        const results = await Promise.allSettled([
            loadSummary(currentCategory, currentStartDate, currentEndDate, currentProject),
            loadCategoryChart(currentCategory, currentStartDate, currentEndDate, currentProject),
            loadVendorChart(currentCategory, currentStartDate, currentEndDate, currentProject),
            loadInsights(currentCategory, currentStartDate, currentEndDate, currentProject)
        ]);

        // Log results of each promise
        const names = ['Summary', 'CategoryChart', 'VendorChart', 'Insights'];
        results.forEach((result, index) => {
            if (result.status === 'rejected') {
                console.error(`[Charts] ${names[index]} failed:`, result.reason);
            } else {
                console.log(`[Charts] ${names[index]} loaded successfully`);
            }
        });
    } catch (error) {
        console.error('[Charts] Error refreshing charts:', error);
    } finally {
        hideLoading();
        console.log('[Charts] runFullRefresh complete');
    }
}

/** Init **/

document.addEventListener('DOMContentLoaded', async () => {
    console.log('[Charts] DOMContentLoaded - starting initialization');
    console.log('[Charts] BANK_CODE:', BANK_CODE);

    // Check if Chart.js is available
    if (typeof Chart === 'undefined') {
        console.error('[Charts] Chart.js not available - aborting initialization');
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.innerHTML = `
                <div style="color: #ef4444; text-align: center; padding: 20px;">
                    <h2>Charts Failed to Load</h2>
                    <p>Chart.js library could not be loaded. Please refresh the page.</p>
                    <button onclick="location.reload()" style="margin-top: 15px; padding: 10px 20px; background: #4a6cf7; color: white; border: none; border-radius: 8px; cursor: pointer;">
                        Refresh Page
                    </button>
                </div>
            `;
        }
        return;
    }

    console.log('[Charts] Chart.js version:', Chart.version);

    showLoading();

    // Safety timeout - hide loading overlay after 15 seconds no matter what
    const safetyTimeout = setTimeout(() => {
        console.warn('[Charts] Safety timeout triggered - forcing loading overlay to hide');
        hideLoading();
    }, 15000);

    try {
        console.log('[Charts] Loading filters...');
        await Promise.all([loadCategories(), loadDateRange(), loadProjects()]);
        console.log('[Charts] Filters loaded successfully');
    } catch (error) {
        console.error('[Charts] Error loading filters:', error);
    }

    currentCategory = 'All';
    currentProject = 'All';
    currentStartDate = null;
    currentEndDate = null;

    // Helper functions
    function getDateNDaysAgo(n) {
        const date = new Date();
        date.setDate(date.getDate() - n);
        return date.toISOString().split('T')[0];
    }

    function getFirstDayOfMonth() {
        const date = new Date();
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-01`;
    }

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
        const projSelect = document.getElementById('project-filter');
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');

        currentCategory = catSelect.value || 'All';
        currentProject = projSelect.value || 'All';
        currentStartDate = startInput.value || null;
        currentEndDate = endInput.value || null;

        document
            .querySelectorAll('.chip')
            .forEach((c) => c.classList.remove('chip-active'));

        runFullRefresh();
    });

    document.getElementById('clear-filters').addEventListener('click', () => {
        const catSelect = document.getElementById('category-filter');
        const projSelect = document.getElementById('project-filter');
        const startInput = document.getElementById('start-date');
        const endInput = document.getElementById('end-date');

        currentCategory = 'All';
        currentProject = 'All';
        currentStartDate = null;
        currentEndDate = null;

        catSelect.value = 'All';
        projSelect.value = 'All';
        startInput.value = '';
        endInput.value = '';

        document
            .querySelectorAll('.chip')
            .forEach((c) => c.classList.remove('chip-active'));
        document
            .querySelector('.chip[data-scenario="all"]')
            ?.classList.add('chip-active');

        runFullRefresh();
    });

    try {
        console.log('[Charts] Running initial data refresh...');
        await runFullRefresh();
        console.log('[Charts] Initial refresh complete');
    } catch (error) {
        console.error('[Charts] Error during initial refresh:', error);
    } finally {
        clearTimeout(safetyTimeout);
        hideLoading();
        console.log('[Charts] Initialization complete');
    }
});
