/* ============================================================================
   Material reconciliation — purchase bills vs bank material spend.

   The auditor's work queue for one project. Two independent records claim to
   describe the same money (the bills we hold, and what actually left the bank
   under MATERIAL PURCHASE); this panel lays out where they disagree, per
   supplier, worst first, with the underlying rows one click away and a link
   straight to the screen where the disagreement gets fixed.

   The server (helpers/material_recon.py) owns the matching, the classification
   and every rupee figure. This file owns presentation only — it must not
   re-derive a number, or the panel and the export could tell different stories.

   Usage:  MaterialRecon.mount(el, payload,
                              { onBillClick, onRulingSaved, project })
   Styling lives in material_recon.css.
   ============================================================================ */
window.MaterialRecon = (function () {
    'use strict';

    // Presentation for each status the server can return. `tone` drives colour.
    // The same label names the row's badge and its filter chip — one word for
    // one condition, so the chip and the rows it produces read as the same thing.
    const STATUS = {
        unbilled: { label: 'No bill', tone: 'bad' },
        unpaid: { label: 'No payment', tone: 'warn' },
        short: { label: 'Short paid', tone: 'warn' },
        over: { label: 'Over paid', tone: 'bad' },
        ok: { label: 'Agrees', tone: 'ok' },
    };

    // Chip order = severity order, which is also the order the server sorts in.
    const CONFLICT_STATUSES = ['unbilled', 'over', 'short', 'unpaid'];

    function escapeHtml(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function pluralise(n, word) {
        return `${n} ${word}${n === 1 ? '' : 's'}`;
    }

    // 2026-03-14 -> 14 Mar. The year is noise in a column where every row
    // belongs to the same project; the full date stays in the title.
    function shortDate(iso) {
        if (!iso) return '';
        const d = new Date(iso + 'T00:00:00');
        if (isNaN(d)) return escapeHtml(iso);
        return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
    }

    // ── Deep links ────────────────────────────────────────────────────
    // Resolving a conflict always means changing data on another screen, so
    // every row carries the shortest route to it, pre-filtered.

    function editGridUrl(bank, project, { vendors, category, search } = {}) {
        const p = new URLSearchParams();
        if (project) p.set('project', project);
        if (vendors && vendors.length) p.set('vendor', vendors.join(','));
        if (category) p.set('category', category);
        if (search) p.set('search', search);
        // The bank dashboard is the edit grid now — /edit-transactions redirects
        // here anyway, but link straight through so there's no extra hop.
        return `/dashboard/${bank || 'kvb'}?${p.toString()}`;
    }

    // The bank vendor strings exactly as the edit grid's own filter lists them —
    // the group's label may come from the invoice and match nothing there.
    // The grid takes a comma-separated list, so a name containing a comma can't
    // be expressed and is left out rather than silently splitting into two.
    // Keyed by bank, because the edit grid is one account at a time and a link
    // to the wrong account would land on an empty screen.
    function bankVendorNames(group) {
        const byBank = new Map();
        (group.txns || []).forEach(t => {
            const v = (t.vendor || '').trim();
            if (!v || v.includes(',')) return;
            const bank = t.bank || 'kvb';
            if (!byBank.has(bank)) byBank.set(bank, new Set());
            byBank.get(bank).add(v);
        });
        return Array.from(byBank, ([bank, names]) => ({ bank, vendors: Array.from(names) }));
    }

    // Words that name a trade rather than a supplier. Searching the grid for
    // "MATERIALS" returns half the statement; searching for "SARAVANA" returns
    // the payment we're looking for.
    const GENERIC_WORDS = new Set([
        'AND', 'THE', 'PVT', 'LTD', 'PRIVATE', 'LIMITED', 'COMPANY', 'CORPORATION',
        'MATERIAL', 'MATERIALS', 'TRADERS', 'TRADING', 'ENTERPRISES', 'ENTERPRISE',
        'HARDWARE', 'HARDWARES', 'STEEL', 'STEELS', 'IRON', 'CEMENT', 'CEMENTS',
        'PAINT', 'PAINTS', 'TIMBER', 'TIMBERS', 'SUPPLIERS', 'SUPPLIES', 'AGENCIES',
        'AGENCY', 'INDUSTRIES', 'BUILDING', 'BUILDERS', 'CONSTRUCTION', 'STORES',
        'ENGINEERING', 'ENGINEERS', 'SERVICES', 'SOLUTIONS', 'ASSOCIATES',
    ]);

    // The word most likely to be the supplier's actual name — the longest one
    // that isn't a trade word. Enough to find a payment by free-text search when
    // the typed vendor doesn't match the invoice's spelling.
    function searchTerm(group) {
        const words = String(group.vendor || '')
            .split(/[^A-Za-z0-9]+/).filter(w => w.length > 2);
        if (!words.length) return String(group.vendor || '').trim();
        const named = words.filter(w => !GENERIC_WORDS.has(w.toUpperCase()));
        return (named.length ? named : words)
            .reduce((a, b) => (b.length > a.length ? b : a));
    }

    // Which account to open the edit grid on. Follow the money where there is
    // any; KVB is where material is paid from otherwise.
    function bankFor(group) {
        const t = (group.txns || [])[0];
        return (t && t.bank) || 'kvb';
    }

    // Every link deliberately chooses its own scope. Where the question is
    // "is this on the right project?", pinning the link to this project would
    // hide the answer — so those links drop the project filter and show the
    // vendor's whole history instead.
    function actionsHtml(group, project) {
        const actions = [];
        const perBank = bankVendorNames(group);

        if (perBank.length) {
            const misTagSuspect = group.status === 'unbilled' || group.status === 'over';
            const multi = perBank.length > 1;
            perBank.forEach(({ bank, vendors }) => {
                const base = misTagSuspect ? 'Check these debits' : 'Open the debits';
                actions.push({
                    href: editGridUrl(bank, misTagSuspect ? '' : project, {
                        vendors, category: 'MATERIAL PURCHASE',
                    }),
                    // The grid shows one account at a time, so a group paid from
                    // both banks gets one link each rather than a link that
                    // quietly drops half the payments.
                    label: multi ? `${base} (${bank.toUpperCase()})` : base,
                    title: misTagSuspect
                        ? 'Opens the edit grid on every material payment to this vendor, across all projects — if one of these belongs elsewhere, retag it there.'
                        : 'Opens the edit grid filtered to this project’s payments to this vendor.',
                });
            });
        }
        if (group.status === 'unpaid' || group.status === 'short') {
            actions.push({
                href: editGridUrl(bankFor(group), '', { search: searchTerm(group) }),
                label: 'Find the payment',
                title: 'Searches every transaction for this vendor — across projects and categories — so a payment booked under the wrong head or project turns up.',
            });
        }
        if (group.status === 'unbilled' || group.status === 'short') {
            actions.push({
                href: '/bill-processor',
                label: 'Upload the bill',
                title: 'Opens the bill processor to add the missing purchase bill.',
            });
        }
        if (!actions.length) return '';
        return `<div class="mr-actions">${actions.map(a => `
            <a class="mr-action" href="${a.href}" title="${escapeHtml(a.title)}">${escapeHtml(a.label)}
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline>
                </svg>
            </a>`).join('')}</div>`;
    }

    // ── Row internals ─────────────────────────────────────────────────

    function txnListHtml(group) {
        const rows = group.txns || [];
        if (!rows.length) {
            return `<div class="mr-side mr-side--empty">
                <span class="mr-side-h">Bank debits</span>
                <p class="mr-none">No MATERIAL PURCHASE payment to this vendor is tagged to this project.</p>
            </div>`;
        }
        return `<div class="mr-side">
            <span class="mr-side-h">Bank debits <em>${pluralise(rows.length, 'row')}</em></span>
            <ul class="mr-lines">${rows.map(t => `
                <li class="mr-line" title="${escapeHtml(t.description || '')}">
                    <span class="mr-line-date">${shortDate(t.date)}</span>
                    <span class="mr-line-tag mr-line-tag--${escapeHtml(t.bank)}">${escapeHtml((t.bank || '').toUpperCase())}</span>
                    <span class="mr-line-name">${escapeHtml(t.vendor || 'Unknown')}</span>
                    <span class="mr-line-amt">${escapeHtml(t.amount_formatted)}</span>
                </li>`).join('')}</ul>
        </div>`;
    }

    function billListHtml(group) {
        const rows = group.bills || [];
        if (!rows.length) {
            return `<div class="mr-side mr-side--empty">
                <span class="mr-side-h">Purchase bills</span>
                <p class="mr-none">No purchase bill from this vendor is tagged to this project.</p>
            </div>`;
        }
        return `<div class="mr-side">
            <span class="mr-side-h">Purchase bills <em>${pluralise(rows.length, 'bill')}</em></span>
            <ul class="mr-lines">${rows.map(b => `
                <li class="mr-line mr-line--bill" data-bill-id="${b.id != null ? escapeHtml(b.id) : ''}"
                    title="Invoice ${escapeHtml(b.invoice_number)}${b.is_split ? ' — split across projects; only this project’s share is counted' : ''}">
                    <span class="mr-line-date">${escapeHtml(b.invoice_date || '')}</span>
                    <span class="mr-line-name">${escapeHtml(b.invoice_number)}${b.is_split ? ' <em class="mr-split">split</em>' : ''}</span>
                    <span class="mr-line-amt">${escapeHtml(b.amount_formatted)}</span>
                </li>`).join('')}</ul>
        </div>`;
    }

    // Every spelling this row covers, canonical name first.
    function namesOf(group) {
        return [group.vendor].concat(group.aliases || []);
    }

    /* Who this row thinks the supplier is — and the two ways to correct it.
       Suppliers are matched on their names, which is a guess, so the guess is
       always shown and always reversible: each folded-in spelling can be split
       back out, and any other row can be declared the same supplier. Both are
       saved and outlive the page, because being asked the same question on
       every visit is what makes people stop answering it. */
    function identityHtml(group, index, allGroups) {
        const canonical = escapeHtml(group.vendor);

        const chips = (group.aliases || []).map(a => `
            <span class="mr-alias">${escapeHtml(a)}<button type="button"
                    class="mr-alias-split" data-alias="${escapeHtml(a)}"
                    data-canonical="${canonical}"
                    aria-label="Separate ${escapeHtml(a)} from ${canonical}"
                    title="Not the same supplier — give ${escapeHtml(a)} its own row from now on">×</button></span>`).join(' ');

        const aliasLine = chips
            ? `<p class="mr-aliases">Also seen as ${chips}</p>`
            : '';

        const others = allGroups.filter(g => g.vendor !== group.vendor);
        if (!others.length) return aliasLine;

        const selectId = `mr-merge-${index}`;
        const mergeLine = `
            <div class="mr-merge">
                <label class="mr-merge-label" for="${selectId}">Same supplier as</label>
                <select class="mr-merge-pick" id="${selectId}">
                    <option value="">another row…</option>
                    ${others.map(o => `<option value="${escapeHtml(o.vendor)}">${escapeHtml(o.vendor)}</option>`).join('')}
                </select>
                <button type="button" class="mr-merge-go" data-canonical="${canonical}"
                        title="Combine the two rows into one supplier, now and in future">Merge</button>
            </div>`;

        return aliasLine + mergeLine;
    }

    function rowHtml(group, index, project, allGroups) {
        const meta = STATUS[group.status] || STATUS.ok;
        const diff = Number(group.difference) || 0;
        // The headline figure is the deviation, signed the way the auditor
        // reads it: + means more money left the bank than we hold bills for.
        const sign = diff > 0 ? '+' : (diff < 0 ? '−' : '');
        return `<li class="mr-row mr-row--${meta.tone}" data-status="${escapeHtml(group.status)}" data-index="${index}">
            <button type="button" class="mr-row-head" aria-expanded="false">
                <span class="mr-row-main">
                    <span class="mr-vendor">${escapeHtml(group.vendor)}</span>
                    <span class="mr-row-meta">Billed ${escapeHtml(group.billed_formatted)}
                        <i>·</i> Paid ${escapeHtml(group.paid_formatted)}</span>
                </span>
                <span class="mr-row-right">
                    <span class="mr-badge">${escapeHtml(meta.label)}</span>
                    <span class="mr-diff">${sign}${escapeHtml(group.difference_formatted)}</span>
                </span>
                <svg class="mr-chev" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
            </button>
            <div class="mr-row-body" hidden>
                <p class="mr-hint">${escapeHtml(group.hint || '')}</p>
                ${identityHtml(group, index, allGroups)}
                ${txnListHtml(group)}
                ${billListHtml(group)}
                ${actionsHtml(group, project)}
            </div>
        </li>`;
    }

    // ── Header block ──────────────────────────────────────────────────

    function balanceHtml(s) {
        const billed = Number(s.billed_total) || 0;
        const paid = Number(s.paid_total) || 0;
        const max = Math.max(billed, paid, 1);
        const diff = Number(s.difference) || 0;
        const tone = Math.abs(diff) < 1 ? 'ok' : (diff > 0 ? 'bad' : 'warn');
        const verdict = Math.abs(diff) < 1
            ? 'Bills and payments agree'
            : (diff > 0
                ? `${s.difference_formatted} paid beyond the bills we hold`
                : `${s.difference_formatted} billed beyond what was paid`);
        return `<div class="mr-balance">
            <div class="mr-scale">
                <div class="mr-scale-row">
                    <span class="mr-scale-k">Purchase bills</span>
                    <span class="mr-scale-v">${escapeHtml(s.billed_total_formatted)}</span>
                </div>
                <div class="mr-bar"><i style="width:${(billed / max * 100).toFixed(1)}%"></i></div>
                <div class="mr-scale-row">
                    <span class="mr-scale-k">Bank material spend</span>
                    <span class="mr-scale-v">${escapeHtml(s.paid_total_formatted)}</span>
                </div>
                <div class="mr-bar mr-bar--paid"><i style="width:${(paid / max * 100).toFixed(1)}%"></i></div>
            </div>
            <p class="mr-verdict mr-verdict--${tone}">${escapeHtml(verdict)}</p>
            ${exposureHtml(s)}
        </div>`;
    }

    // The net gap is the honest headline but a poor measure of the work: a ₹5L
    // payment with no bill and ₹5L of bills with no payment net to nothing while
    // being two serious findings. So each kind of conflict states its own money.
    function exposureHtml(s) {
        const lines = [
            { n: s.unbilled_total, text: s.unbilled_total_formatted, label: 'Paid with no bill', tone: 'bad' },
            { n: s.unpaid_total, text: s.unpaid_total_formatted, label: 'Billed with no payment', tone: 'warn' },
            { n: s.mismatch_total, text: s.mismatch_total_formatted, label: 'Amounts disagree', tone: 'warn' },
        ].filter(l => Number(l.n) > 0);
        if (!lines.length) return '';
        return `<dl class="mr-exposure">${lines.map(l => `
            <div class="mr-exposure-row mr-exposure-row--${l.tone}">
                <dt>${escapeHtml(l.label)}</dt><dd>${escapeHtml(l.text)}</dd>
            </div>`).join('')}</dl>`;
    }

    function chipsHtml(s, groups) {
        const counts = s.counts || {};
        const chips = [];
        if (s.conflict_count > 0) {
            chips.push({ key: 'conflicts', label: 'To resolve', n: s.conflict_count });
        }
        CONFLICT_STATUSES.forEach(k => {
            if (counts[k]) chips.push({ key: k, label: STATUS[k].label, n: counts[k] });
        });
        if (counts.ok) chips.push({ key: 'ok', label: STATUS.ok.label, n: counts.ok });
        if (groups.length) chips.push({ key: 'all', label: 'All', n: groups.length });
        if (chips.length < 2) return '';
        // Land on the work queue, not on everything.
        const active = s.conflict_count > 0 ? 'conflicts' : 'all';
        return `<div class="mr-chips" role="tablist" aria-label="Filter conflicts">${chips.map(c => `
            <button type="button" class="mr-chip${c.key === active ? ' active' : ''}"
                    data-filter="${c.key}" role="tab" aria-selected="${c.key === active}">
                ${escapeHtml(c.label)}<span>${c.n}</span>
            </button>`).join('')}</div>`;
    }

    // The panel's own header doubles as its collapse control, so the whole
    // component folds down to one line. `flag` is the only thing worth reading
    // while it is shut, so it stays in the bar.
    // `interactive` is false for the states with nothing to open.
    function headHtml({ flag = '', sub = '', interactive = true, expanded = true }) {
        const subLine = sub ? `<p class="mr-sub">${sub}</p>` : '';
        const inner = `<div class="mr-head-text">
                <h2 class="mr-title">Material Reconciliation</h2>
                ${subLine}
            </div>
            ${flag}`;
        if (!interactive) return `<header class="mr-head">${inner}</header>`;
        return `<header class="mr-head">
            <button type="button" class="mr-head-btn" aria-expanded="${expanded}"
                    aria-controls="mr-body" title="Show or hide the reconciliation">
                ${inner}
                <svg class="mr-head-chev" width="16" height="16" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
                     stroke-linejoin="round" aria-hidden="true">
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
            </button>
        </header>`;
    }

    const SCOPE_NOTE = `Purchase bills vs bank material spend
        <span title="Bills and payments are compared over the project's whole life. A month filter would pair one month of payments against every bill and read ordinary part-payment timing as a conflict.">· whole project</span>`;

    /**
     * Build the panel's HTML from the /api/project-summary/material-reconciliation
     * payload. Returns a string; the caller owns the element.
     *
     * opts.expanded — start open (default: open only when there is something to
     * resolve, so a clean project takes one line and the page stays quiet).
     */
    function render(data, opts) {
        const project = (opts && opts.project) || '';
        if (!data || !data.available) {
            return `<section class="mr-panel mr-panel--muted">
                ${headHtml({ interactive: false })}
                <p class="mr-empty">${escapeHtml((data && data.reason)
                    || 'Reconciliation is unavailable for this project.')}</p>
            </section>`;
        }

        const s = data.summary || {};
        const groups = data.groups || [];

        if (!groups.length) {
            return `<section class="mr-panel">
                ${headHtml({ sub: 'Purchase bills vs bank material spend', interactive: false })}
                <p class="mr-empty">This project has no purchase bills and no material-purchase
                    payments yet, so there is nothing to reconcile.</p>
            </section>`;
        }

        const clean = s.conflict_count === 0;
        const flag = clean
            ? `<span class="mr-flag mr-flag--ok">All clear</span>`
            : `<span class="mr-flag mr-flag--bad">${s.conflict_count} to resolve</span>`;
        const expanded = (opts && typeof opts.expanded === 'boolean')
            ? opts.expanded : !clean;

        const cleanNote = clean ? `<p class="mr-allclear">Every material payment on this
            project is backed by a purchase bill from the same supplier, and every bill has
            a payment behind it.</p>` : '';

        const truncated = data.truncated ? `<p class="mr-warnline">Only the first
            ${groups.length} bills were read — totals below are partial.</p>` : '';

        return `<section class="mr-panel${expanded ? '' : ' collapsed'}">
            ${headHtml({ flag, sub: SCOPE_NOTE, expanded })}
            <div class="mr-body" id="mr-body"${expanded ? '' : ' hidden'}>
                <div class="mr-body-fixed">
                    ${truncated}
                    ${balanceHtml(s)}
                    ${cleanNote}
                    ${chipsHtml(s, groups)}
                </div>
                <ul class="mr-list">${groups.map((g, i) => rowHtml(g, i, project, groups)).join('')}</ul>
                <p class="mr-foot">${pluralise(s.vendor_count || 0, 'supplier')} ·
                    ${pluralise(s.bill_count || 0, 'bill')} ·
                    ${pluralise(s.txn_count || 0, 'payment')}. Suppliers are matched on name —
                    open a row to see which spellings were folded together, and correct it
                    there if the match is wrong.</p>
            </div>
        </section>`;
    }

    // Open/closed preference, per tab. sessionStorage throws in some privacy
    // modes, so every access is guarded — the panel falls back to its default
    // rather than failing to render.
    const PREF_KEY = 'mr.expanded';

    function readPref() {
        try {
            const v = sessionStorage.getItem(PREF_KEY);
            return v === null ? null : v === '1';
        } catch (e) { return null; }
    }

    function writePref(expanded) {
        try { sessionStorage.setItem(PREF_KEY, expanded ? '1' : '0'); } catch (e) { /* ignore */ }
    }

    // Only the rows the active chip asks for. Doing it here rather than
    // re-rendering keeps any row the auditor has open, open.
    function applyFilter(root, key) {
        root.querySelectorAll('.mr-row').forEach(row => {
            const st = row.dataset.status;
            const show = key === 'all'
                || (key === 'conflicts' ? st !== 'ok' : st === key);
            row.hidden = !show;
        });
    }

    /**
     * Render into `el` and wire up the interactions.
     * opts: { project, onBillClick(billId), onRulingSaved() }
     *
     * onRulingSaved fires after the auditor corrects a supplier match; the
     * caller should re-fetch and re-mount, because regrouping moves every
     * total, status and row position on the panel.
     */
    function mount(el, data, opts) {
        if (!el) return;
        opts = opts || {};
        // An auditor working through a list of projects shouldn't have to
        // re-open (or re-close) the panel on every one, so their last choice
        // carries across — but only for this tab.
        const remembered = readPref();
        el.innerHTML = render(data, Object.assign(
            remembered === null ? {} : { expanded: remembered }, opts));

        const panel = el.querySelector('.mr-panel');
        if (!panel) return;

        const headBtn = panel.querySelector('.mr-head-btn');
        if (headBtn) {
            headBtn.addEventListener('click', () => {
                const open = headBtn.getAttribute('aria-expanded') === 'true';
                headBtn.setAttribute('aria-expanded', String(!open));
                panel.classList.toggle('collapsed', open);
                const body = panel.querySelector('.mr-body');
                if (body) body.hidden = open;
                writePref(!open);
            });
        }

        const activeChip = panel.querySelector('.mr-chip.active');
        applyFilter(panel, activeChip ? activeChip.dataset.filter : 'all');

        panel.querySelectorAll('.mr-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                panel.querySelectorAll('.mr-chip').forEach(c => {
                    c.classList.remove('active');
                    c.setAttribute('aria-selected', 'false');
                });
                chip.classList.add('active');
                chip.setAttribute('aria-selected', 'true');
                applyFilter(panel, chip.dataset.filter);
            });
        });

        panel.querySelectorAll('.mr-row-head').forEach(head => {
            head.addEventListener('click', () => {
                const open = head.getAttribute('aria-expanded') === 'true';
                head.setAttribute('aria-expanded', String(!open));
                const body = head.nextElementSibling;
                if (body) body.hidden = open;
                head.closest('.mr-row').classList.toggle('open', !open);
            });
        });

        if (typeof opts.onBillClick === 'function') {
            panel.querySelectorAll('.mr-line--bill').forEach(line => {
                const id = line.dataset.billId;
                if (!id) return;
                line.classList.add('mr-line--clickable');
                line.addEventListener('click', (e) => {
                    e.stopPropagation();
                    opts.onBillClick(id);
                });
            });
        }

        wireIdentityControls(panel, data, opts);
    }

    // ── Correcting who a supplier is ──────────────────────────────────

    async function postRuling(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.message || "Couldn't save that.");
        }
        return data;
    }

    function wireIdentityControls(panel, data, opts) {
        const groups = (data && data.groups) || [];
        const byVendor = new Map(groups.map(g => [g.vendor, g]));
        // A saved ruling changes the grouping, so the panel has to be rebuilt
        // from the server rather than patched here — the totals, statuses and
        // ordering all move with it.
        const reload = typeof opts.onRulingSaved === 'function'
            ? opts.onRulingSaved : null;

        function fail(btn, err) {
            btn.disabled = false;
            console.error('Vendor alias error:', err);
            window.alert(err.message || "Couldn't save that.");
        }

        panel.querySelectorAll('.mr-alias-split').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const alias = btn.dataset.alias;
                const canonical = btn.dataset.canonical;
                if (!window.confirm(
                    `Treat "${alias}" and "${canonical}" as different suppliers `
                    + `from now on?\n\nThey will be listed as separate rows, on `
                    + `this project and every other.`)) return;
                btn.disabled = true;
                try {
                    await postRuling('/api/vendor-aliases/split',
                        { left: alias, right: canonical });
                    if (reload) reload();
                } catch (err) { fail(btn, err); }
            });
        });

        panel.querySelectorAll('.mr-merge-go').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const row = btn.closest('.mr-merge');
                const pick = row && row.querySelector('.mr-merge-pick');
                const other = pick && pick.value;
                if (!other) return;

                const here = byVendor.get(btn.dataset.canonical);
                const there = byVendor.get(other);
                if (!here || !there) return;

                // Keep the fuller name as the supplier's — the same rule the
                // server uses to label a group, so merging by hand doesn't
                // rename a supplier the auditor already recognises.
                const names = namesOf(here).concat(namesOf(there));
                const canonical = names.reduce(
                    (a, b) => (b.length > a.length ? b : a));
                const aliases = names.filter(n => n !== canonical);

                if (!window.confirm(
                    `Treat these as one supplier, named "${canonical}"?\n\n`
                    + aliases.map(a => `  • ${a}`).join('\n')
                    + `\n\nTheir bills and payments will be reconciled together, `
                    + `on this project and every other.`)) return;
                btn.disabled = true;
                try {
                    await postRuling('/api/vendor-aliases/link',
                        { aliases, canonical });
                    if (reload) reload();
                } catch (err) { fail(btn, err); }
            });
        });
    }

    return { render, mount };
})();
