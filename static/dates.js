/**
 * Friendly dates for display, precise dates for filters and form fields.
 *
 * Two halves:
 *   VismaDate.format(x)     - current year -> "12 Oct"; other years -> "12 Oct 2025"
 *   date pickers            - filters show dd-mm-yyyy; other fields show
 *                             "12 Oct 2026". Their values stay ISO dates.
 *
 * The native date input can't do this: it renders in the browser's locale
 * (mm/dd/yyyy on a US-English Chrome), whatever the page asks for.
 */
(function () {
    'use strict';

    const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
                     jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
    const pad = n => String(n).padStart(2, '0');

    /**
     * Parse what the app actually sends -> local Date (midnight), or null.
     * Day-first throughout: "05-10-2026" is 5 October, never May 10.
     *   2026-10-12, 2026-10-12 14:03:00, 2026-10-12T14:03:00Z
     *   12-10-2026, 12/10/2026, 12-Oct-2026, 12 Oct 2026, 12-October-2026
     */
    function parse(value) {
        if (value == null || value === '') return null;
        if (value instanceof Date) return isNaN(value) ? null : value;
        const s = String(value).trim();
        let m;
        if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:$|[T ])/))) {
            // A full timestamp keeps its time (and its zone, if it has one);
            // a bare date is a calendar day, not UTC midnight.
            if (s.length > 10) {
                const d = new Date(s.replace(' ', 'T'));
                if (!isNaN(d)) return d;
            }
            return build(+m[1], +m[2], +m[3]);
        }
        if ((m = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/))) {
            return build(year(m[3]), +m[2], +m[1]);
        }
        if ((m = s.match(/^(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]+(\d{2,4})$/))) {
            const mon = MONTHS[m[2].slice(0, 3).toLowerCase()];
            return mon ? build(year(m[3]), mon, +m[1]) : null;
        }
        const d = new Date(s);
        return isNaN(d) ? null : d;
    }

    function year(y) { return y.length === 2 ? 2000 + +y : +y; }

    function build(y, mo, d) {
        const dt = new Date(y, mo - 1, d);
        // Reject 31-02-2026 rather than silently rolling it into March.
        return dt.getMonth() === mo - 1 && dt.getDate() === d ? dt : null;
    }

    /** Current year -> "12 Oct"; other years -> "12 Oct 2025". */
    function format(value, fallback) {
        if (value == null || value === '') return fallback !== undefined ? fallback : '';
        const d = parse(value);
        if (!d) return String(value);
        const short = `${d.getDate()} ${d.toLocaleDateString('en-IN', { month: 'short' })}`;
        return d.getFullYear() === new Date().getFullYear() ? short : `${short} ${d.getFullYear()}`;
    }

    /** -> "2026-10-12", the value a date input and the API want. Local, not UTC. */
    function iso(value) {
        const d = parse(value);
        return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : '';
    }

    window.VismaDate = { parse, format, iso };

    // ── Date pickers ─────────────────────────────────────────────────

    const valueProp = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');

    function upgrade(input) {
        if (input._vismaPicker || typeof window.flatpickr !== 'function') return;

        const isFilter = input.id.startsWith('filter') || input.classList.contains('filter-input');
        input._vismaIsFilter = isFilter;
        const fp = window.flatpickr(input, {
            dateFormat: 'Y-m-d',          // what .value holds
            altInput: true,
            altFormat: isFilter ? 'd-m-Y' : 'j M Y',
            altInputClass: input.className + ' visma-date',
            allowInput: true,             // typing 12-10-2026 works too
            disableMobile: true,          // the native mobile picker would show the locale format again
            minDate: input.min || null,
            maxDate: input.max || null,
            parseDate: (s, fmt) => parse(s) || window.flatpickr.parseDate(s, fmt),
            onReady: (_, __, inst) => syncAttrs(input, inst.altInput),
        });
        input._vismaPicker = fp;

        // Callers set .value = '2026-10-12' (or '') directly; keep the visible
        // field in step. flatpickr writes .value itself too, so guard the loop.
        let syncing = false;
        Object.defineProperty(input, 'value', {
            configurable: true,
            get() { return valueProp.get.call(this); },
            set(v) {
                valueProp.set.call(this, v);
                if (syncing) return;
                syncing = true;
                try {
                    if (v) fp.setDate(v, false, 'Y-m-d');
                    else fp.clear(false);
                } finally { syncing = false; }
            },
        });

        // .min/.max/.title/.disabled set later (e.g. once the data range loads).
        new MutationObserver(muts => {
            for (const m of muts) {
                if (m.attributeName === 'min') fp.set('minDate', input.min || null);
                else if (m.attributeName === 'max') fp.set('maxDate', input.max || null);
                else syncAttrs(input, fp.altInput);
            }
        }).observe(input, { attributes: true, attributeFilter: ['min', 'max', 'title', 'disabled', 'required'] });
    }

    function syncAttrs(input, alt) {
        if (!alt) return;
        alt.title = input.title || '';
        alt.disabled = input.disabled;
        alt.required = input.required;
        if (!alt.placeholder) alt.placeholder = input._vismaIsFilter ? 'dd-mm-yyyy' : '20 Aug 2026';
        // A <label for="..."> should still focus the field the user can see.
        if (input.id && !alt.getAttribute('aria-label')) {
            const label = document.querySelector(`label[for="${input.id}"]`);
            if (label) alt.setAttribute('aria-label', label.textContent.trim());
        }
    }

    function upgradeAll(root) {
        (root || document).querySelectorAll('input[type="date"]').forEach(upgrade);
    }

    function start() {
        upgradeAll();
        // Inputs rendered later (modals, templated rows) get the same treatment.
        new MutationObserver(muts => {
            for (const m of muts) {
                for (const n of m.addedNodes) {
                    if (n.nodeType !== 1) continue;
                    if (n.matches('input[type="date"]')) upgrade(n);
                    else upgradeAll(n);
                }
            }
        }).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
