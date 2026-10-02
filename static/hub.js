/**
 * Hub page JavaScript
 * Fills the date line and the module counts, and runs Refresh.
 */

const countFormat = new Intl.NumberFormat('en-IN');

/**
 * Where each module's count comes from. The bank counts are rendered by the
 * server, so they are only re-fetched on Refresh (see refreshBankStats).
 */
const COUNT_SOURCES = [
    { id: 'projects-count', url: '/api/projects', pick: activeProjectCount },
    { id: 'personal-count', url: '/api/personal/summary', pick: data => data.transaction_count },
    { id: 'bill-count', url: '/api/bills/stats', pick: data => data.invoice_count },
    { id: 'sales-count', url: '/api/sales/stats', pick: data => data.invoice_count },
];

document.addEventListener('DOMContentLoaded', function () {
    showToday();
    formatServerCounts();
    loadCounts();

    const refreshBtn = document.getElementById('refresh-cache-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', refreshCache);
});

/**
 * Today's date for the bar, in the Indian long form ("Friday, 2 October 2026").
 */
function showToday() {
    const el = document.getElementById('today');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toLocaleDateString('en-IN', {
        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
    });
    // Local date, not toISOString(): that is UTC, a day behind before 5:30 am IST.
    const pad = n => String(n).padStart(2, '0');
    el.dateTime = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * The server renders bank counts as bare integers; group them the same way
 * as the counts loaded below.
 */
function formatServerCounts() {
    document.querySelectorAll('.tile__count[data-count]').forEach(el => {
        setCount(el, Number(el.dataset.count));
    });
}

/**
 * Write a count into its cell. A count that cannot be loaded shows a dash
 * rather than 0 - "0 bills" would be a claim about the data, not an error.
 */
function setCount(el, value) {
    if (typeof el === 'string') el = document.getElementById(el);
    if (!el) return;

    if (typeof value === 'number' && Number.isFinite(value)) {
        el.textContent = countFormat.format(value);
        delete el.dataset.state;
        el.removeAttribute('title');
    } else if (!/\d/.test(el.textContent)) {
        // Keep a number that is already showing; only an empty cell gets the dash.
        el.textContent = '—';
        el.dataset.state = 'error';
        el.title = "Couldn't load this count. Use Refresh to try again.";
    }
}

async function fetchJSON(url) {
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    return response.json();
}

/**
 * Load one count. Resolves to true on success so Refresh can report failures.
 */
async function loadCount(source) {
    try {
        const data = await fetchJSON(source.url);
        setCount(source.id, Number(source.pick(data)));
        return true;
    } catch (error) {
        console.error(`Error loading ${source.id}:`, error);
        setCount(source.id, null);
        return false;
    }
}

function loadCounts() {
    return Promise.all(COUNT_SOURCES.map(loadCount));
}

/**
 * "Active" mirrors the registry: type === 'project' and not closed (is_inactive).
 */
function activeProjectCount(data) {
    const projects = data.projects || [];
    return projects.filter(p => {
        const isClosed = p.is_inactive === true || p.is_inactive === 1;
        const type = p.project_type || (p.is_project === false ? 'other' : 'project');
        return !isClosed && type === 'project';
    }).length;
}

/**
 * Re-fetch both banks' transaction counts.
 */
async function refreshBankStats() {
    try {
        const data = await fetchJSON('/api/hub/stats');
        if (data.axis) setCount('axis-count', Number(data.axis.transaction_count));
        if (data.kvb) setCount('kvb-count', Number(data.kvb.transaction_count));
        return true;
    } catch (error) {
        console.error('Error refreshing bank stats:', error);
        return false;
    }
}

/**
 * Refresh the hub's live stats. The server no longer keeps a dataframe cache
 * (reads load fresh from the DB), so this just re-pulls the counts and clears
 * the browser's Cache Storage.
 */
async function refreshCache() {
    const btn = document.getElementById('refresh-cache-btn');
    const label = btn.querySelector('.btn__label');
    btn.disabled = true;
    btn.classList.add('is-busy');

    let ok = true;
    try {
        if ('caches' in window) {
            const names = await caches.keys();
            await Promise.all(names.map(name => caches.delete(name)));
        }
        const results = await Promise.all([refreshBankStats(), loadCounts()]);
        ok = results[0] && results[1].every(Boolean);
    } catch (error) {
        console.error('Error clearing cache:', error);
        ok = false;
    } finally {
        btn.disabled = false;
        btn.classList.remove('is-busy');
    }

    label.textContent = ok ? 'Refreshed' : 'Refresh failed';
    btn.setAttribute('aria-label', label.textContent);
    setTimeout(() => {
        label.textContent = 'Refresh';
        btn.setAttribute('aria-label', 'Refresh counts');
    }, 1800);
}
