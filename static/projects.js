(() => {
    'use strict';

    const listEl = document.getElementById('projects-list');
    const newBtn = document.getElementById('new-project-btn');
    const newModal = document.getElementById('new-project-modal');
    const newForm = document.getElementById('new-project-form');
    const idInput = document.getElementById('new-project-id');
    const stemInput = document.getElementById('new-project-stem');
    const poInput = document.getElementById('new-project-po');
    const submitBtn = document.getElementById('new-project-submit');
    const collisionEl = document.getElementById('new-project-collision');
    const errorEl = document.getElementById('new-project-error');

    const detailModal = document.getElementById('project-detail-modal');
    const detailTitle = document.getElementById('detail-title');
    const detailPoFilename = document.getElementById('detail-po-filename');
    const detailPoLink = document.getElementById('detail-po-link');
    const detailUploadBlock = document.getElementById('detail-po-upload');
    const detailUploadLabel = document.getElementById('detail-upload-label');
    const detailUploadForm = document.getElementById('detail-upload-form');
    const detailPoInput = document.getElementById('detail-po-input');
    const detailUploadError = document.getElementById('detail-upload-error');

    // PO gist / edit / reprocess
    const gistEl = document.getElementById('detail-po-gist');
    const poActions = document.getElementById('detail-po-actions');
    const reprocessBtn = document.getElementById('detail-po-reprocess');
    const editBtn = document.getElementById('detail-po-edit-btn');
    const editForm = document.getElementById('detail-po-edit-form');
    const editCancel = document.getElementById('detail-po-edit-cancel');
    const editError = document.getElementById('detail-po-edit-error');

    const toast = document.getElementById('proj-toast');

    const detailOverview = document.getElementById('detail-overview');
    const detailPoBlock = document.getElementById('detail-po-block');

    // Insight tabs (PO / payments / expenses / bills / labour)
    const tabsBar = document.getElementById('detail-tabs');
    const tabButtons = () => Array.from(tabsBar.querySelectorAll('.proj-tab'));
    const tabPanels = () => Array.from(detailModal.querySelectorAll('[data-tab-panel]'));
    const payModesEl = document.getElementById('detail-pay-modes');
    const expensesEl = document.getElementById('detail-expenses');
    const purchaseBillsEl = document.getElementById('detail-purchase-bills');
    const salesBillsEl = document.getElementById('detail-sales-bills');
    const labourEl = document.getElementById('detail-labour');

    // Edit panel (type / reprocess / PO values, behind the header Edit button)
    const editToggleBtn = document.getElementById('detail-edit-toggle');
    const editToggleLabel = document.getElementById('detail-edit-toggle-label');
    const editPanel = document.getElementById('detail-edit-panel');
    const poAdmin = document.getElementById('detail-po-admin');

    // Cash client payments
    const cashTotalEl = document.getElementById('detail-cash-total');
    const cashForm = document.getElementById('detail-cash-form');
    const cashToggleBtn = document.getElementById('detail-cash-toggle');
    const cashToggleLabel = document.getElementById('detail-cash-toggle-label');
    const cashAmount = document.getElementById('detail-cash-amount');
    const cashDate = document.getElementById('detail-cash-date');
    const cashNote = document.getElementById('detail-cash-note');
    const cashAddBtn = document.getElementById('detail-cash-add');
    const cashError = document.getElementById('detail-cash-error');
    const cashListEl = document.getElementById('detail-cash-list');

    const detailTypeStatus = document.getElementById('detail-type-status');
    const detailTypeRadios = () => Array.from(detailModal.querySelectorAll('input[name="detail_project_type"]'));

    const detailStatusStatus = document.getElementById('detail-status-status');
    const detailInactiveToggle = document.getElementById('detail-is-inactive');

    // The three registry buckets, in display order. A row's bucket comes from
    // project_type, falling back to the legacy is_project boolean.
    const TYPE_SECTIONS = [
        { key: 'project', title: 'Projects', sub: 'Valid client / site projects', variant: 'projects' },
        { key: 'design', title: 'Designs', sub: 'Design-only work', variant: 'designs' },
        { key: 'other', title: 'Others', sub: 'Internal heads (office, factory, KVB, sridhar…)', variant: 'others' },
    ];
    const projectTypeOf = (p) => p.project_type || (p.is_project === false ? 'other' : 'project');
    const isClosed = (p) => p.is_inactive === true || p.is_inactive === 1;

    let projects = [];
    let activeProjectId = null;
    let insights = null;        // /insights payload for the open project
    let cashPayments = [];      // live cash ledger for the open project

    // ── Toast ──────────────────────────────────────────
    let toastTimer = null;
    function showToast(msg, kind = 'success') {
        toast.textContent = msg;
        toast.classList.remove('hidden', 'error');
        if (kind === 'error') toast.classList.add('error');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.add('hidden'), 2800);
    }

    // ── Render ─────────────────────────────────────────
    // One labelled stat in a card's finance strip. When `fullValue` is given,
    // the tooltip is enriched with the full-precision amount (the cell itself
    // shows the compact form), so callers don't repeat `: ${formatINR(x)}`.
    function financeCell(label, value, cls, title, fullValue) {
        const tip = fullValue != null
            ? (title ? `${title}: ${formatINR(fullValue)}` : formatINR(fullValue))
            : title;
        return `<div class="proj-fin-cell"${tip ? ` title="${escapeHtml(tip)}"` : ''}>
            <span class="proj-fin-k">${label}</span>
            <span class="proj-fin-v ${cls}">${value}</span>
        </div>`;
    }

    function buildCard(p) {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'project-card' + (isClosed(p) ? ' is-closed' : '');
        card.dataset.id = p.id;
        const created = p.created_at ? new Date(p.created_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' }) : '';
        const closedBadge = isClosed(p) ? `<span class="project-po-badge closed">Closed</span>` : '';
        const badge = p.has_po
            ? `<span class="project-po-badge has-po">PO uploaded</span>`
            : `<span class="project-po-badge no-po">No PO yet</span>`;
        const poValue = Number(p.po_total_value) || 0;
        const received = Number(p.received_total) || 0;
        const hasPoValue = p.po_total_value != null && poValue > 0;

        // A clean, aligned finance strip — one labelled stat per column —
        // instead of cramped abbreviated pills that wrapped onto each other.
        const cells = [];
        if (hasPoValue) {
            cells.push(financeCell('PO Value', formatINRCompact(poValue), '',
                'Total purchase-order value', poValue));
        } else if (p.po_extraction_status === 'failed') {
            cells.push(financeCell('PO Value', 'Pending', 'pending', 'Auto-read failed — open to enter manually'));
        }
        const hasReceived = received > 0;
        if (hasReceived || hasPoValue) {
            cells.push(financeCell('Received', hasReceived ? formatINRCompact(received) : '—',
                hasReceived ? 'received' : 'muted',
                'Client payments received', hasReceived ? received : null));
        }
        if (hasPoValue) {
            const bal = poValue - received;
            const settled = bal <= 0.5;
            cells.push(financeCell('Balance', settled ? 'Settled' : formatINRCompact(bal),
                settled ? 'settled' : 'due',
                settled ? 'Fully received' : 'Balance due (PO value − received)', settled ? null : bal));
        }
        const financeBlock = cells.length ? `<div class="project-finance">${cells.join('')}</div>` : '';

        card.innerHTML = `
            <div class="project-card-main">
                <span class="project-card-id">${p.id}</span>
                <span class="project-card-stem">${escapeHtml(p.stem_name)}</span>
            </div>
            <div class="project-card-foot">
                <div class="project-card-meta">
                    ${closedBadge}
                    ${badge}
                    ${created ? `<span class="project-created">Added ${created}</span>` : ''}
                </div>
                ${financeBlock}
            </div>
        `;
        card.addEventListener('click', () => openDetail(p.id));
        return card;
    }

    function renderSection(title, subtitle, items, variant) {
        const section = document.createElement('section');
        section.className = 'proj-section' + (variant ? ` proj-section--${variant}` : '');
        const head = document.createElement('div');
        head.className = 'proj-section-head';
        head.innerHTML = `
            <h2 class="proj-section-title">${title} <span class="proj-section-count">${items.length}</span></h2>
            ${subtitle ? `<span class="proj-section-sub">${subtitle}</span>` : ''}
        `;
        section.appendChild(head);
        const grid = document.createElement('div');
        grid.className = 'proj-section-grid';
        items.forEach(p => grid.appendChild(buildCard(p)));
        section.appendChild(grid);
        return section;
    }

    function renderList() {
        if (!projects.length) {
            listEl.innerHTML = `<div class="proj-empty">No projects yet. Click <strong>+ New Project</strong> to create the first one.</div>`;
            return;
        }

        listEl.innerHTML = '';
        // Active entries first, grouped by type bucket…
        TYPE_SECTIONS.forEach(sec => {
            const items = projects.filter(p => !isClosed(p) && projectTypeOf(p) === sec.key);
            if (items.length) {
                listEl.appendChild(renderSection(sec.title, sec.sub, items, sec.variant));
            }
        });
        // …then a single "Closed" section at the very bottom for every inactive
        // entry, regardless of its type bucket.
        const closed = projects.filter(isClosed);
        if (closed.length) {
            listEl.appendChild(renderSection(
                'Closed', 'Inactive / completed — kept for reference', closed, 'closed'));
        }
    }

    function escapeHtml(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // Render a bank name as a colored badge: Axis in red, KVB in green.
    function bankBadge(bank) {
        const code = String(bank || '').trim().toLowerCase();
        const label = code ? escapeHtml(code.toUpperCase()) : '';
        if (!label) return '';
        const cls = code === 'axis' ? 'bank-axis' : code === 'kvb' ? 'bank-kvb' : '';
        return `<span class="proj-bank-badge ${cls}">${label}</span>`;
    }

    // Indian-format a number with a ₹ prefix (e.g. 2325190 -> ₹23,25,190.00).
    // Always two decimals: mixing ₹2,00,000 with ₹5,505.90 in one column makes
    // the figures hard to scan, and a lone ".5" reads as a rounding bug.
    function formatINR(value) {
        const n = Number(value) || 0;
        return '₹' + n.toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    // Compact Indian-format for the card finance strip so values stay on a
    // single line (e.g. 22165179 -> ₹2.22 Cr, 6640450 -> ₹66.40 L).
    function formatINRCompact(value) {
        const n = Number(value) || 0;
        const sign = n < 0 ? '-' : '';
        const abs = Math.abs(n);
        if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
        if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
        return sign + '₹' + abs.toLocaleString('en-IN', { maximumFractionDigits: 0 });
    }

    // ── Load ───────────────────────────────────────────
    async function loadProjects() {
        try {
            const res = await fetch('/api/projects', { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            projects = data.projects || [];
            renderList();
        } catch (e) {
            console.error('Failed to load projects', e);
            listEl.innerHTML = `<div class="proj-empty">Failed to load projects. Refresh to retry.</div>`;
        }
    }

    // ── Modals ─────────────────────────────────────────
    function openModal(modal) {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }
    function closeModal(modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }

    document.querySelectorAll('[data-close]').forEach(el => {
        el.addEventListener('click', () => {
            const id = el.getAttribute('data-close');
            const m = document.getElementById(id);
            if (m) closeModal(m);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.proj-modal:not(.hidden)').forEach(m => closeModal(m));
        }
    });

    // ── New project flow ───────────────────────────────
    newBtn.addEventListener('click', () => {
        newForm.reset();
        collisionEl.classList.add('hidden');
        collisionEl.textContent = '';
        errorEl.classList.add('hidden');
        errorEl.textContent = '';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save';
        openModal(newModal);
        setTimeout(() => idInput.focus(), 60);
    });

    // Live collision check against cached project list
    function checkCollision() {
        collisionEl.classList.add('hidden');
        collisionEl.textContent = '';
        const idVal = idInput.value.trim();
        const stemVal = stemInput.value.trim().toLowerCase();
        if (!idVal) return;
        const idNum = parseInt(idVal, 10);
        if (Number.isNaN(idNum)) return;

        const idClash = projects.find(p => p.id === idNum);
        if (idClash) {
            collisionEl.textContent = `ID ${idNum} is already used by "${idClash.display}". Pick a different id.`;
            collisionEl.classList.remove('hidden');
            return;
        }
        if (stemVal) {
            const stemClash = projects.find(p => p.stem_name.toLowerCase() === stemVal);
            if (stemClash) {
                collisionEl.textContent = `A project named "${stemClash.stem_name}" already exists with id ${stemClash.id}.`;
                collisionEl.classList.remove('hidden');
            }
        }
    }
    idInput.addEventListener('input', checkCollision);
    stemInput.addEventListener('input', checkCollision);

    newForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.classList.add('hidden');
        errorEl.textContent = '';

        const idVal = idInput.value.trim();
        const stemVal = stemInput.value.trim();
        if (!idVal || !stemVal) {
            errorEl.textContent = 'Both ID and project name are required.';
            errorEl.classList.remove('hidden');
            return;
        }
        const idNum = parseInt(idVal, 10);
        if (Number.isNaN(idNum) || idNum <= 0) {
            errorEl.textContent = 'ID must be a positive integer.';
            errorEl.classList.remove('hidden');
            return;
        }

        const typeEl = newForm.querySelector('input[name="project_type"]:checked');
        if (!typeEl) {
            errorEl.textContent = 'Please choose a type — Project, Design or Other.';
            errorEl.classList.remove('hidden');
            return;
        }

        const fd = new FormData();
        fd.append('id', String(idNum));
        fd.append('stem_name', stemVal);
        fd.append('project_type', typeEl.value);
        if (poInput.files && poInput.files[0]) fd.append('po_file', poInput.files[0]);

        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving…';
        try {
            const res = await fetch('/api/projects', {
                method: 'POST',
                body: fd,
                credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const msg = data.message || data.error || `Failed (HTTP ${res.status})`;
                errorEl.textContent = msg;
                errorEl.classList.remove('hidden');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Save';
                return;
            }
            closeModal(newModal);
            showToast(`Project ${idNum} - ${stemVal} created.`);
            await loadProjects();
        } catch (err) {
            errorEl.textContent = `Network error: ${err.message}`;
            errorEl.classList.remove('hidden');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save';
        }
    });

    // ── Project detail / PO upload flow ────────────────
    function openDetail(projectId) {
        const p = projects.find(x => x.id === projectId);
        if (!p) return;
        activeProjectId = projectId;
        detailTitle.textContent = `${p.id} − ${p.stem_name}`;
        // Forward link to the full breakdown on the Project Summary page. The
        // canonical "<id> - NAME" tag is what that page matches on (by id).
        const breakdownLink = document.getElementById('detail-breakdown-link');
        if (breakdownLink) {
            breakdownLink.href = '/project-summary?project=' +
                encodeURIComponent(`${p.id} - ${p.stem_name}`);
        }
        // Fresh insight state: PO tab first, counts cleared, panels in loading state.
        insights = null;
        cashPayments = [];
        switchTab('overview');
        switchSubTab('bills', 'purchase');
        switchSubTab('ledger', 'payments');
        ['bills', 'ledger'].forEach(k => setTabCount(k, null));
        ['purchase', 'sales', 'payments', 'expenses', 'labour'].forEach(k => setSubTabCount(k, null));
        payModesEl.innerHTML = '';
        const loading = `<p class="proj-tab-loading">Loading…</p>`;
        expensesEl.innerHTML = loading;
        purchaseBillsEl.innerHTML = loading;
        salesBillsEl.innerHTML = loading;
        labourEl.innerHTML = loading;
        renderOverview(p);
        // Start in read-only view; editing is opt-in via the header Edit button.
        // (Overhead is the exception — it's edited in place in the Expenses
        // list, so it isn't gated behind Edit mode.)
        setEditMode(false);
        // Cash client payments ledger — form is collapsed until "+ Add".
        setCashFormOpen(false);
        cashForm.reset();
        cashError.classList.add('hidden');
        cashError.textContent = '';
        loadCashPayments(p.id);
        loadInsights(p.id);
        // Reflect current type in the toggle
        const wantVal = projectTypeOf(p);
        detailTypeRadios().forEach(r => { r.checked = (r.value === wantVal); });
        detailTypeStatus.textContent = '';
        detailTypeStatus.classList.remove('error');
        // Reflect closed/active status
        detailInactiveToggle.checked = isClosed(p);
        detailStatusStatus.textContent = '';
        detailStatusStatus.classList.remove('error');
        detailUploadError.classList.add('hidden');
        detailUploadError.textContent = '';
        detailUploadForm.reset();

        if (p.has_po) {
            detailPoBlock.classList.remove('hidden');
            detailPoBlock.open = false; // reference detail — folded until asked for
            detailUploadBlock.classList.add('hidden');
            detailPoFilename.textContent = p.po_filename;
            detailPoLink.href = `/api/projects/${p.id}/po`;
            poAdmin.classList.remove('hidden');
            exitPoEditForm();
            loadPoGist(p.id);
        } else {
            detailPoBlock.classList.add('hidden');
            detailUploadBlock.classList.remove('hidden');
            poAdmin.classList.add('hidden');
            detailUploadLabel.textContent = `Upload PO document for "${p.stem_name}"`;
        }
        openModal(detailModal);
    }

    // ── Edit mode (header Edit button reveals the edit panel) ──
    function setEditMode(on) {
        editPanel.classList.toggle('hidden', !on);
        editToggleBtn.classList.toggle('active', on);
        editToggleLabel.textContent = on ? 'Done' : 'Edit';
        if (!on) exitPoEditForm(); // collapse any open PO-values form on exit
    }
    editToggleBtn.addEventListener('click', () => {
        const turningOn = editPanel.classList.contains('hidden');
        if (turningOn) switchTab('overview'); // the edit panel lives on the Overview tab
        setEditMode(turningOn);
    });


    // ── Insight tabs ───────────────────────────────────
    function switchTab(key) {
        tabButtons().forEach(b => b.classList.toggle('active', b.dataset.tab === key));
        tabPanels().forEach(pn => pn.classList.toggle('hidden', pn.dataset.tabPanel !== key));
    }
    // Nothing recorded yet? Surface the cash entry form so the input is visible
    // without hunting for the "+ Add cash" button. Driven from the click
    // handlers rather than switchSubTab: openDetail calls switchSubTab to reset
    // the panels and then resets the form itself, so an auto-open in there
    // would be immediately undone.
    function maybeOpenCashForm() {
        if (cashForm.classList.contains('hidden')
            && !cashPayments.length
            && (!insights || !insights.payments.bank.length)) {
            setCashFormOpen(true);
        }
    }

    tabsBar.addEventListener('click', (e) => {
        const btn = e.target.closest('.proj-tab');
        if (!btn) return;
        switchTab(btn.dataset.tab);
        // The Ledger tab opens on its payments sub-panel, so it needs the same
        // nudge the payments sub-tab gets.
        if (btn.dataset.tab === 'ledger'
            && !subTabScope('ledger').querySelector('[data-subtab-panel="payments"]').classList.contains('hidden')) {
            maybeOpenCashForm();
        }
    });

    // Sub-tabs within Bills and Ledger. Scoped to their own panel so the two
    // groups can both have a "payments"/"purchase" key without colliding.
    function subTabScope(tabKey) {
        return detailModal.querySelector(`[data-tab-panel="${tabKey}"]`);
    }
    function switchSubTab(tabKey, subKey) {
        const scope = subTabScope(tabKey);
        if (!scope) return;
        scope.querySelectorAll('.proj-subtab').forEach(b =>
            b.classList.toggle('active', b.dataset.subtab === subKey));
        scope.querySelectorAll('[data-subtab-panel]').forEach(pn =>
            pn.classList.toggle('hidden', pn.dataset.subtabPanel !== subKey));
    }
    detailModal.addEventListener('click', (e) => {
        const btn = e.target.closest('.proj-subtab');
        if (!btn) return;
        const panel = btn.closest('[data-tab-panel]');
        if (!panel) return;
        switchSubTab(panel.dataset.tabPanel, btn.dataset.subtab);
        if (panel.dataset.tabPanel === 'ledger' && btn.dataset.subtab === 'payments') {
            maybeOpenCashForm();
        }
    });

    function setTabCount(key, value) {
        const el = tabsBar.querySelector(`[data-tab-count="${key}"]`);
        if (!el) return;
        if (!value) {
            el.classList.add('hidden');
            el.textContent = '';
        } else {
            el.textContent = value;
            el.classList.remove('hidden');
        }
    }

    function setSubTabCount(key, value) {
        detailModal.querySelectorAll(`[data-subtab-count="${key}"]`).forEach(el => {
            el.textContent = value ? ` ${value}` : '';
        });
    }

    function fmtDate(s) {
        if (!s) return '—';
        const d = new Date(s);
        return Number.isNaN(d.getTime())
            ? String(s)
            : d.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
    }

    // Revert the inline PO-values form back to the read-only gist.
    function exitPoEditForm() {
        editForm.classList.add('hidden');
        editError.classList.add('hidden');
        poActions.classList.remove('hidden');
        gistEl.classList.remove('hidden');
    }

    // ── Cash form reveal (+ Add) ───────────────────────
    function setCashFormOpen(on) {
        cashForm.classList.toggle('hidden', !on);
        cashToggleBtn.classList.toggle('active', on);
        cashToggleLabel.textContent = on ? 'Close' : 'Add cash';
        if (on) setTimeout(() => {
            // The modal body scrolls — on short screens the freshly revealed
            // form can sit below the fold, so bring it into view first.
            cashForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            cashAmount.focus({ preventScroll: true });
        }, 60);
    }
    cashToggleBtn.addEventListener('click', () => {
        setCashFormOpen(cashForm.classList.contains('hidden'));
    });

    // ── Project at a glance ────────────────────────────
    // Mirrors the summary sheet the client actually works from: a value ladder
    // (basic -> GST -> total -> received -> balance), the GST position of
    // purchases against sales, and the cost breakdown. Called twice per open —
    // once from the cached registry row for an instant paint, then again once
    // /insights lands with the full picture.
    function renderOverview(p) {
        const s = insights && insights.summary;
        const rec = Number((s ? s.received_total : p.received_total)) || 0;
        const bank = Number((s ? s.received_bank : p.received_bank)) || 0;
        const cash = Number((s ? s.received_cash : p.received_cash)) || 0;
        const po = Number(p.po_total_value) || 0;

        // Before insights arrive, the PO is all we have to show a ladder from.
        const val = s ? s.value : { basic: 0, gst: 0, total: po, source: po > 0 ? 'po' : 'none' };
        const total = Number(val.total) || 0;

        // Only bail when there is genuinely nothing to say. This guard predates
        // the cost breakdown, and a project can have real costs (bills, labour,
        // overhead) with no PO, no sales bills and nothing received yet —
        // hiding on value alone would blank out its spend and loss entirely.
        const hasCosts = !!(s && Number(s.spend_total) > 0);
        if (total <= 0 && rec <= 0 && !hasCosts) {
            detailOverview.classList.add('hidden');
            detailOverview.innerHTML = '';
            return;
        }

        const receivable = total - rec;
        const pct = total > 0 ? Math.min(100, Math.round((rec / total) * 100)) : null;
        const dueLabel = receivable < -0.5 ? 'Overpaid by' : 'To collect';
        const dueCls = receivable > 0.5 ? 'due' : 'settled';

        // ── Hero: the two questions people open this for ──
        const profitCell = s ? `
            <div class="proj-hero-cell">
                <span class="proj-hero-k">Profit</span>
                <span class="proj-hero-v ${s.profit >= 0 ? 'profit' : 'loss'}">${formatINR(Math.abs(s.profit))}${s.profit < 0 ? ' loss' : ''}</span>
                <span class="proj-hero-sub">${s.margin_pct != null ? `${s.margin_pct.toFixed(1)}% margin` : '&nbsp;'}</span>
            </div>` : `
            <div class="proj-hero-cell">
                <span class="proj-hero-k">Profit</span>
                <span class="proj-hero-v is-loading">…</span>
                <span class="proj-hero-sub">&nbsp;</span>
            </div>`;
        const hero = `
            <div class="proj-hero">
                <div class="proj-hero-cell">
                    <span class="proj-hero-k">${dueLabel}</span>
                    <span class="proj-hero-v ${dueCls}">${formatINR(Math.abs(receivable))}</span>
                    <span class="proj-hero-sub">${pct != null ? `${pct}% of ${formatINRCompact(total)} received` : '&nbsp;'}</span>
                </div>
                ${profitCell}
            </div>
            ${pct != null ? `<div class="proj-pay-bar"><div class="proj-pay-bar-fill" style="width:${pct}%"></div></div>` : ''}`;

        // ── Value ladder ──
        const splitNote = cash > 0
            ? `<span class="proj-ladder-split">${formatINRCompact(bank)} bank + ${formatINRCompact(cash)} cash</span>`
            : '';
        const SOURCE_NOTE = {
            sales_bills: 'From sales bills',
            po: 'From the purchase order — no sales bills tagged yet',
            none: 'No sales bills or PO value yet',
        };
        // The PO is the contract, the sales bills are what we billed. Showing
        // the gap matters: it's either work not yet invoiced or billing over PO.
        let poNote = '';
        if (val.source === 'sales_bills' && po > 0) {
            const diff = total - po;
            const billedPct = Math.round((total / po) * 100);
            poNote = Math.abs(diff) < 1
                ? ` · matches the PO exactly`
                : ` · PO ${formatINRCompact(po)}, billed ${billedPct}%`;
        }
        const ladder = `
            <div class="proj-ov-panel">
                <div class="proj-ov-head"><h4 class="proj-ov-title">Project value</h4></div>
                <div class="proj-ov-body">
                <dl class="proj-ladder">
                    <div class="proj-ladder-row"><dt>Basic value</dt><dd>${formatINR(val.basic)}</dd></div>
                    <div class="proj-ladder-row"><dt>GST</dt><dd>${formatINR(val.gst)}</dd></div>
                    <div class="proj-ladder-row is-total"><dt>Total value</dt><dd>${formatINR(total)}</dd></div>
                    <div class="proj-ladder-row"><dt>Received</dt><dd>${formatINR(rec)}${splitNote}</dd></div>
                    <div class="proj-ladder-row is-balance"><dt>${dueLabel === 'To collect' ? 'Current balance' : 'Overpaid by'}</dt><dd class="${dueCls}">${formatINR(Math.abs(receivable))}</dd></div>
                </dl>
                <p class="proj-ov-note">${SOURCE_NOTE[val.source] || ''}${poNote}</p>
                </div>
            </div>`;

        // ── GST position ──
        let gstPanel = '';
        if (s) {
            const g = s.gst;
            const hasBills = g.purchase_total > 0 || g.sales_total > 0;
            // Negative = input GST exceeds output: a credit, not something owed.
            const isCredit = g.extra < -0.5;
            gstPanel = `
            <div class="proj-ov-panel">
                <div class="proj-ov-head"><h4 class="proj-ov-title">GST position</h4></div>
                <div class="proj-ov-body">
                ${hasBills ? `
                <table class="proj-gst-table">
                    <thead><tr><th></th><th>Basic</th><th>GST</th><th>Total</th></tr></thead>
                    <tbody>
                        <tr>
                            <th scope="row">Purchase</th>
                            <td data-label="Basic">${formatINR(g.purchase_basic)}</td>
                            <td data-label="GST">${formatINR(g.purchase_gst)}</td>
                            <td data-label="Total">${formatINR(g.purchase_total)}</td>
                        </tr>
                        <tr>
                            <th scope="row">Sales</th>
                            <td data-label="Basic">${formatINR(g.sales_basic)}</td>
                            <td data-label="GST">${formatINR(g.sales_gst)}</td>
                            <td data-label="Total">${formatINR(g.sales_total)}</td>
                        </tr>
                    </tbody>
                </table>
                <div class="proj-gst-extra ${isCredit ? 'is-credit' : ''}">
                    <span class="proj-gst-extra-k">${isCredit ? 'GST credit' : 'GST extra'}</span>
                    <span class="proj-gst-extra-v">${formatINR(Math.abs(g.extra))}</span>
                </div>
                ${isCredit ? `<p class="proj-ov-note">Input GST exceeds output GST — carried forward as credit, not counted as a cost.</p>` : ''}
                ` : `<p class="proj-tab-empty">No bills tagged to this project yet.</p>`}
                </div>
            </div>`;
        }

        detailOverview.innerHTML = hero + `<div class="proj-ov-grid">${ladder}${gstPanel}</div>` + renderCostPanel();
        detailOverview.classList.remove('hidden');
    }

    // ── Expenses, highest first ───────────────────────
    // Lines and totals come from the server so they always sum to spend_total.
    // Overhead is the one hand-entered line and is edited in place here.
    function renderCostPanel() {
        const s = insights && insights.summary;
        if (!s) return '';
        const lines = s.cost_lines || [];
        // "Expenses" doubles as the head of the left column, so the band reads
        // as a table header rather than a title stacked on one.
        const head = `
            <div class="proj-ov-head">
                <h4 class="proj-ov-title">Expenses</h4>
                <span class="proj-cost-head-amt">Amount</span>
            </div>`;
        if (!lines.length) {
            return `<div class="proj-ov-panel proj-ov-costs">${head}
                <p class="proj-tab-empty proj-cost-empty">No costs recorded for this project yet.</p>
            </div>`;
        }
        const total = Number(s.spend_total) || 0;
        const rows = lines.map(l => {
            // A number input can't render "₹2,00,000.00", and a bare 200000 in a
            // column of formatted figures looks broken. So it's a text field
            // showing the formatted value at rest, swapped to the raw number on
            // focus (see the focusin/focusout handlers).
            const cell = l.editable
                ? `<input class="proj-cost-input" type="text" inputmode="decimal"
                          value="${l.amount ? formatINR(l.amount) : ''}" placeholder="${formatINR(0)}"
                          data-overhead-input data-raw="${l.amount || 0}"
                          aria-label="Overhead amount in rupees"
                          title="Costs no bill or bank row covers. Counts toward the total and profit.">`
                : formatINR(l.amount);
            return `
            <li class="proj-cost-row${l.editable ? ' is-editable' : ''}" data-source="${escapeHtml(l.source)}">
                <span class="proj-cost-k">${escapeHtml(l.label)}</span>
                <span class="proj-cost-v">${cell}</span>
            </li>`;
        }).join('');
        const profitCls = s.profit >= 0 ? 'profit' : 'loss';
        // Labour comes from the attendance app. If that's unreachable it counts
        // as 0, so the total is short and the profit correspondingly flattering
        // — say so rather than presenting an incomplete figure as final.
        const labourWarning = s.labour_available === false
            ? `<p class="proj-cost-warn">Labour is missing — the attendance app
               couldn't be reached, so the total and profit below exclude it.</p>`
            : '';
        return `
            <div class="proj-ov-panel proj-ov-costs">${head}
                ${labourWarning}
                <ul class="proj-cost-list">${rows}</ul>
                <div class="proj-cost-foot">
                    <div class="proj-cost-foot-row is-total">
                        <span>Total cost</span><span>${formatINR(total)}</span>
                    </div>
                    <div class="proj-cost-foot-row is-profit">
                        <span>Balance (${s.profit >= 0 ? 'profit' : 'loss'})</span>
                        <span class="${profitCls}">${formatINR(Math.abs(s.profit))}</span>
                    </div>
                </div>
            </div>`;
    }

    // ── Cash client payments ───────────────────────────
    function applyPaymentSummary(summary) {
        // Push fresh totals into the cached project so the card + payments view
        // reflect the change without a full reload.
        // Insights first: renderOverview reads its received/receivable figures
        // from insights.summary when it's loaded, so it has to see the new
        // totals before the repaint below.
        if (insights && insights.summary) {
            insights.summary.received_cash = summary.received_cash;
            insights.summary.received_total = summary.received_total;
            insights.summary.receivable = insights.summary.value.total - summary.received_total;
            insights.payments.cash_total = summary.received_cash;
            insights.payments.total = summary.received_total;
        }
        const cached = projects.find(x => x.id === activeProjectId);
        if (cached) {
            cached.received_bank = summary.received_bank;
            cached.received_cash = summary.received_cash;
            cached.received_total = summary.received_total;
            renderOverview(cached);
            renderList(); // keep the registry card's "Received" in sync
        }
        renderCashList(summary.payments || []);
    }

    function renderCashList(payments) {
        cashPayments = payments || [];
        renderPaymentHistory();
        renderPayModes();
        if (insights) {
            const payCount = insights.payments.bank.length + cashPayments.length;
            setSubTabCount('payments', payCount);
            setTabCount('ledger', payCount + insights.expenses.count);
        }
    }

    // Bank (KVB) total / cash total / total received chips at the top of the
    // Client Payments tab. Cash figures come from the live ledger so an
    // add/delete updates them instantly.
    function renderPayModes() {
        if (!insights) { payModesEl.innerHTML = ''; return; }
        const bank = insights.payments.bank;
        const bankTotal = Number(insights.payments.bank_total) || 0;
        const cashTotal = cashPayments.reduce((s, c) => s + (Number(c.amount) || 0), 0);
        payModesEl.innerHTML = `
            <div class="proj-chip">
                <span class="proj-chip-k">Bank (KVB)</span>
                <span class="proj-chip-v">${formatINR(bankTotal)}</span>
                <span class="proj-chip-sub">${bank.length} credit${bank.length === 1 ? '' : 's'}</span>
            </div>
            <div class="proj-chip">
                <span class="proj-chip-k">Cash</span>
                <span class="proj-chip-v">${formatINR(cashTotal)}</span>
                <span class="proj-chip-sub">${cashPayments.length} entr${cashPayments.length === 1 ? 'y' : 'ies'}</span>
            </div>
            <div class="proj-chip accent">
                <span class="proj-chip-k">Total received</span>
                <span class="proj-chip-v">${formatINR(bankTotal + cashTotal)}</span>
            </div>`;
    }

    // One chronological history mixing KVB statement credits (read-only, with
    // their statement context) and manual cash entries (deletable).
    function renderPaymentHistory() {
        const bank = (insights && insights.payments && insights.payments.bank) || [];
        const cashTotal = cashPayments.reduce((s, c) => s + (Number(c.amount) || 0), 0);
        cashTotalEl.textContent = cashPayments.length ? `${formatINR(cashTotal)} in cash` : '';

        const entries = [];
        bank.forEach(b => entries.push({
            mode: 'bank',
            date: b.date || '',
            amount: Number(b.amount) || 0,
            context: (b.vendor && b.vendor !== 'Unknown') ? b.vendor : (b.description || ''),
            title: b.description || '',
        }));
        cashPayments.forEach(c => entries.push({
            mode: 'cash',
            id: c.id,
            date: c.payment_date || (c.created_at ? String(c.created_at).slice(0, 10) : ''),
            amount: Number(c.amount) || 0,
            context: c.note || '',
            title: c.note || '',
        }));

        if (!entries.length) {
            cashListEl.innerHTML = insights
                ? `<p class="proj-cash-empty">No client payments recorded for this project yet.</p>`
                : `<p class="proj-cash-empty">Loading payments…</p>`;
            return;
        }

        entries.sort((a, b) => String(b.date).localeCompare(String(a.date)));
        cashListEl.innerHTML = entries.map(en => {
            const when = en.date ? fmtDate(en.date) : '';
            const badge = en.mode === 'bank'
                ? `<span class="proj-mode-badge bank" title="From the KVB bank statement">Bank</span>`
                : `<span class="proj-mode-badge cash" title="Cash handed over — recorded manually">Cash</span>`;
            const del = en.mode === 'cash'
                ? `<button type="button" class="proj-cash-del" data-id="${en.id}" title="Remove this payment" aria-label="Remove this payment">×</button>`
                : '';
            return `
                <div class="proj-cash-item">
                    <div class="proj-cash-item-main">
                        <span class="proj-cash-item-amt">${formatINR(en.amount)} ${badge}</span>
                        ${en.context ? `<span class="proj-cash-item-note" title="${escapeHtml(en.title)}">${escapeHtml(en.context)}</span>` : ''}
                    </div>
                    <div class="proj-cash-item-side">
                        ${when ? `<span class="proj-cash-item-date">${when}</span>` : ''}
                        ${del}
                    </div>
                </div>`;
        }).join('');
    }

    function loadCashPayments(projectId) {
        cashError.classList.add('hidden');
        cashError.textContent = '';
        cashListEl.innerHTML = `<p class="proj-cash-empty">Loading…</p>`;
        cashTotalEl.textContent = '';
        fetch(`/api/projects/${projectId}/cash-payments`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                if (projectId !== activeProjectId) return; // modal changed
                renderCashList(data.payments || []);
            })
            .catch(() => {
                if (projectId !== activeProjectId) return;
                cashListEl.innerHTML = `<p class="proj-cash-empty">Couldn't load cash payments.</p>`;
            });
    }

    cashForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeProjectId) return;
        cashError.classList.add('hidden');
        cashError.textContent = '';

        const amount = parseFloat(cashAmount.value);
        if (Number.isNaN(amount) || amount <= 0) {
            cashError.textContent = 'Enter an amount greater than zero.';
            cashError.classList.remove('hidden');
            return;
        }
        const payload = {
            amount,
            payment_date: cashDate.value || null,
            note: cashNote.value.trim() || null,
        };
        cashAddBtn.disabled = true;
        cashAddBtn.textContent = 'Adding…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/cash-payments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                cashError.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                cashError.classList.remove('hidden');
                return;
            }
            cashForm.reset();
            setCashFormOpen(false);
            applyPaymentSummary(data);
            showToast(`Cash payment of ${formatINR(amount)} added.`);
        } catch (err) {
            cashError.textContent = `Network error: ${err.message}`;
            cashError.classList.remove('hidden');
        } finally {
            cashAddBtn.disabled = false;
            cashAddBtn.textContent = 'Add';
        }
    });

    cashListEl.addEventListener('click', async (e) => {
        const btn = e.target.closest('.proj-cash-del');
        if (!btn || !activeProjectId) return;
        const id = btn.dataset.id;
        if (!id) return;
        if (!confirm('Remove this cash payment?')) return;
        btn.disabled = true;
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/cash-payments/${id}`, {
                method: 'DELETE',
                credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                showToast(data.message || data.error || 'Could not remove payment.', 'error');
                btn.disabled = false;
                return;
            }
            applyPaymentSummary(data);
            showToast('Cash payment removed.');
        } catch (err) {
            showToast(`Network error: ${err.message}`, 'error');
            btn.disabled = false;
        }
    });

    // ── Project insights (overview / bills / ledger tabs) ──
    async function loadInsights(projectId) {
        try {
            const res = await fetch(`/api/projects/${projectId}/insights`, { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (projectId !== activeProjectId) return; // modal changed
            insights = data;
            // If the cash ledger fetch hasn't landed yet, seed it from insights
            // so the merged history doesn't briefly miss the cash rows.
            if (!cashPayments.length && data.payments.cash.length) {
                cashPayments = data.payments.cash;
            }
            // Repaint the glance now that the real numbers (profit, GST, costs)
            // are in — the first paint only had the cached PO/received figures.
            const p = projects.find(x => x.id === projectId);
            if (p) renderOverview(p);
            renderPayModes();
            renderPaymentHistory();
            renderExpensesTab();
            renderBillsTab('purchase');
            renderBillsTab('sales');
            renderLabourTab();
            const payCount = data.payments.bank.length + cashPayments.length;
            const labourCount = data.labour && data.labour.monthly ? data.labour.monthly.length : 0;
            setTabCount('bills', data.purchase_bills.count + data.sales_bills.count);
            setTabCount('ledger', payCount + data.expenses.count);
            setSubTabCount('purchase', data.purchase_bills.count);
            setSubTabCount('sales', data.sales_bills.count);
            setSubTabCount('payments', payCount);
            setSubTabCount('expenses', data.expenses.count);
            setSubTabCount('labour', labourCount);
        } catch (e) {
            console.error('Failed to load project insights', e);
            if (projectId !== activeProjectId) return;
            const fail = `<p class="proj-tab-empty">Couldn't load this section. Close and reopen the project to retry.</p>`;
            expensesEl.innerHTML = fail;
            purchaseBillsEl.innerHTML = fail;
            salesBillsEl.innerHTML = fail;
            labourEl.innerHTML = fail;
            payModesEl.innerHTML = '';
            renderPaymentHistory();
            // The glance can't be trusted without insights — say so rather than
            // leaving the half-painted PO-only numbers looking authoritative.
            const costsFail = detailOverview.querySelector('.proj-ov-costs');
            if (costsFail) {
                costsFail.innerHTML = fail;
            }
        }
    }

    function renderExpensesTab() {
        const ex = insights.expenses;
        if (!ex || !ex.count) {
            expensesEl.innerHTML = `<p class="proj-tab-empty">No expenses tagged to this project in the bank statements yet.</p>`;
            return;
        }
        const chips = `
            <div class="proj-pay-modes">
                <div class="proj-chip accent">
                    <span class="proj-chip-k">Total spent</span>
                    <span class="proj-chip-v">${formatINR(ex.total)}</span>
                    <span class="proj-chip-sub">${ex.count} transaction${ex.count === 1 ? '' : 's'}</span>
                </div>
                ${ex.by_category.slice(0, 3).map(c => `
                <div class="proj-chip">
                    <span class="proj-chip-k">${escapeHtml(c.category)}</span>
                    <span class="proj-chip-v">${formatINRCompact(c.amount)}</span>
                    <span class="proj-chip-sub">${c.count}×</span>
                </div>`).join('')}
            </div>`;
        const rows = ex.transactions.map(t => `
            <tr>
                <td class="proj-li-unit">${fmtDate(t.date)}</td>
                <td class="proj-li-desc" title="${escapeHtml(t.description)}">${escapeHtml((t.vendor && t.vendor !== 'Unknown') ? t.vendor : t.description)}</td>
                <td><span class="proj-cat-chip">${escapeHtml(t.category)}</span></td>
                <td class="proj-li-unit">${bankBadge(t.bank)}</td>
                <td class="proj-li-num">${formatINR(t.amount)}</td>
            </tr>`).join('');
        const truncNote = ex.count > ex.transactions.length
            ? `<p class="proj-tab-note">Showing the latest ${ex.transactions.length} of ${ex.count} transactions.</p>` : '';
        expensesEl.innerHTML = `${chips}
            <div class="proj-li-scroll proj-li-scroll--tall">
                <table class="proj-li-table">
                    <thead><tr><th>Date</th><th>Paid to</th><th>Category</th><th>Bank</th><th class="proj-li-num">Amount</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>${truncNote}`;
    }

    function renderBillsTab(kind) {
        const isPurchase = kind === 'purchase';
        const el = isPurchase ? purchaseBillsEl : salesBillsEl;
        const data = isPurchase ? insights.purchase_bills : insights.sales_bills;
        if (!data || !data.count) {
            el.innerHTML = `<p class="proj-tab-empty">No ${isPurchase ? 'purchase' : 'sales'} bills found for this project.</p>`;
            return;
        }
        const chips = `
            <div class="proj-pay-modes">
                <div class="proj-chip accent">
                    <span class="proj-chip-k">Total billed</span>
                    <span class="proj-chip-v">${formatINR(data.total_amount)}</span>
                    <span class="proj-chip-sub">${data.count} bill${data.count === 1 ? '' : 's'}</span>
                </div>
                <div class="proj-chip">
                    <span class="proj-chip-k">GST included</span>
                    <span class="proj-chip-v">${formatINR(data.total_gst)}</span>
                </div>
            </div>`;
        const rows = data.bills.map(b => `
            <tr>
                <td class="proj-li-unit">${b.invoice_date ? escapeHtml(b.invoice_date) : '—'}</td>
                <td class="proj-li-unit">${b.invoice_number ? escapeHtml(b.invoice_number) : '—'}</td>
                <td class="proj-li-desc">${escapeHtml((isPurchase ? b.vendor_name : b.buyer_name) || '—')}</td>
                <td class="proj-li-num">${b.line_item_count != null ? b.line_item_count : '—'}</td>
                <td class="proj-li-num">${formatINR(b.total_amount)}</td>
            </tr>`).join('');
        el.innerHTML = `${chips}
            <div class="proj-li-scroll proj-li-scroll--tall">
                <table class="proj-li-table">
                    <thead><tr><th>Date</th><th>Invoice #</th><th>${isPurchase ? 'Vendor' : 'Buyer'}</th><th class="proj-li-num">Items</th><th class="proj-li-num">Amount</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    function renderLabourTab() {
        const lab = insights.labour;
        if (!lab || lab.available === false) {
            labourEl.innerHTML = `<p class="proj-tab-empty">Couldn't reach the attendance app database right now — labour charges are unavailable. Try again later.</p>`;
            return;
        }
        if (!lab.monthly || !lab.monthly.length) {
            labourEl.innerHTML = `<p class="proj-tab-empty">No attendance recorded against this project yet.</p>`;
            return;
        }
        const chips = `
            <div class="proj-pay-modes">
                <div class="proj-chip accent">
                    <span class="proj-chip-k">Labour charges</span>
                    <span class="proj-chip-v">${formatINR(lab.total_cost)}</span>
                    <span class="proj-chip-sub">from the attendance app</span>
                </div>
                <div class="proj-chip">
                    <span class="proj-chip-k">Man-days</span>
                    <span class="proj-chip-v">${Number(lab.total_days).toLocaleString('en-IN')}</span>
                </div>
                <div class="proj-chip">
                    <span class="proj-chip-k">OT hours</span>
                    <span class="proj-chip-v">${Number(lab.total_ot_hours).toLocaleString('en-IN')}</span>
                </div>
            </div>`;
        const rows = lab.monthly.map(m => `
            <tr>
                <td>${escapeHtml(m.label)}</td>
                <td class="proj-li-num">${Number(m.days).toLocaleString('en-IN')}</td>
                <td class="proj-li-num">${Number(m.ot_hours).toLocaleString('en-IN', { maximumFractionDigits: 1 })}</td>
                <td class="proj-li-num">${formatINR(m.cost)}</td>
            </tr>`).join('');
        const namesNote = lab.project_names && lab.project_names.length
            ? `<p class="proj-tab-note">Matched attendance project${lab.project_names.length === 1 ? '' : 's'}: ${lab.project_names.map(escapeHtml).join(', ')}</p>`
            : '';
        labourEl.innerHTML = `${chips}
            <div class="proj-li-scroll proj-li-scroll--tall">
                <table class="proj-li-table">
                    <thead><tr><th>Month</th><th class="proj-li-num">Man-days</th><th class="proj-li-num">OT hours</th><th class="proj-li-num">Cost</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>${namesNote}`;
    }

    // ── Mobile: collapse the modal's line-item tables into stacked cards ──
    // Reads each table's own <thead> and stamps every <td> with data-label so
    // the CSS (max-width:640px) can render LABEL : value rows. A MutationObserver
    // catches tables injected by any tab (expenses / bills / labour / PO items).
    function decorateProjLiTables(root) {
        (root || document).querySelectorAll('.proj-li-table:not([data-mobi])').forEach(table => {
            const heads = Array.from(table.querySelectorAll('thead th'))
                .map(th => th.textContent.trim());
            table.querySelectorAll('tbody tr').forEach(tr => {
                const tds = tr.querySelectorAll('td');
                if (tds.length <= 1) return;
                tds.forEach((td, i) => {
                    if (heads[i]) td.setAttribute('data-label', heads[i]);
                    td.classList.toggle('proj-li-title', i === 0);
                });
            });
            table.setAttribute('data-mobi', '1');
        });
    }
    (function watchProjTables() {
        const modal = document.getElementById('project-detail-modal');
        if (modal && 'MutationObserver' in window) {
            new MutationObserver(() => decorateProjLiTables(modal))
                .observe(modal, { childList: true, subtree: true });
        }
    })();

    let currentPo = null;

    // ── Render the extracted PO gist ───────────────────
    function loadPoGist(projectId) {
        currentPo = null;
        gistEl.innerHTML = `<div class="proj-gist-loading">Loading PO details…</div>`;
        fetch(`/api/projects/${projectId}/po-data`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                if (projectId !== activeProjectId) return; // modal changed
                currentPo = data.po || null;
                renderPoGist(currentPo);
            })
            .catch(() => {
                gistEl.innerHTML = `<div class="proj-gist-empty">Couldn't load PO details.</div>`;
            });
    }

    function renderPoGist(po) {
        if (!po) {
            gistEl.innerHTML = `<div class="proj-gist-empty">Not processed yet. Click <strong>Reprocess</strong> to extract the PO values.</div>`;
            return;
        }
        if (po.extraction_status === 'failed') {
            gistEl.innerHTML = `<div class="proj-gist-failed">
                Couldn't auto-read this PO${po.extraction_error ? ` (${escapeHtml(po.extraction_error)})` : ''}.
                Click <strong>Edit</strong> (top right) to enter the total manually or reprocess the file.
            </div>`;
            return;
        }
        const rows = [
            ['Total project value', formatINR(po.total_value), 'headline'],
            ['PO number', po.po_number ? escapeHtml(po.po_number) : '—'],
            ['PO date', po.po_date ? escapeHtml(po.po_date) : '—'],
            ['Client', po.client_name ? escapeHtml(po.client_name) : '—'],
            ['Taxable value', formatINR(po.taxable_value)],
            ['Total tax', formatINR(po.total_tax)],
            ['Scope items', po.line_item_count != null ? po.line_item_count : '—'],
        ];
        if (po.payment_terms) rows.push(['Payment terms', escapeHtml(po.payment_terms)]);
        if (po.amount_in_words) rows.push(['In words', escapeHtml(po.amount_in_words)]);

        const manualTag = po.extraction_status === 'manual'
            ? `<span class="proj-gist-tag">manually edited</span>` : '';

        gistEl.innerHTML = `
            <div class="proj-gist-header">
                <span class="proj-field-label">Extracted PO gist</span>${manualTag}
            </div>
            <div class="proj-gist-rows">
                ${rows.map(([k, v, cls]) => `
                    <div class="proj-gist-row ${cls === 'headline' ? 'headline' : ''}">
                        <span class="proj-gist-k">${k}</span>
                        <span class="proj-gist-v">${v}</span>
                    </div>`).join('')}
            </div>
            ${renderPoLineItems(po.line_items)}`;
    }

    // ── Core line-item breakdown (description / qty / unit / rate / amount) ──
    function renderPoLineItems(items) {
        if (!Array.isArray(items) || items.length === 0) return '';
        const num = (v) => (v ? formatINR(v) : '—');
        const qty = (v) => {
            if (!v) return '—';
            // trim trailing zeros: 12.00 -> 12, 12.50 -> 12.5
            return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 });
        };
        const body = items.map(it => `
            <tr>
                <td class="proj-li-desc">${it.description ? escapeHtml(it.description) : '—'}</td>
                <td class="proj-li-num">${qty(it.quantity)}</td>
                <td class="proj-li-unit">${it.unit ? escapeHtml(it.unit) : '—'}</td>
                <td class="proj-li-num">${num(it.rate)}</td>
                <td class="proj-li-num">${num(it.amount)}</td>
            </tr>`).join('');
        return `
            <div class="proj-gist-items">
                <div class="proj-field-label">Line items (${items.length})</div>
                <div class="proj-li-scroll">
                    <table class="proj-li-table">
                        <thead>
                            <tr>
                                <th>Description</th><th class="proj-li-num">Qty</th>
                                <th>Unit</th><th class="proj-li-num">Rate</th>
                                <th class="proj-li-num">Amount</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            </div>`;
    }

    // ── Type toggle (project / design / other) ─────────
    const TYPE_LABELS = { project: 'a project', design: 'a design', other: 'an internal “other”' };
    detailTypeRadios().forEach(radio => {
        radio.addEventListener('change', async () => {
            if (!activeProjectId || !radio.checked) return;
            const projectType = radio.value;
            detailTypeStatus.classList.remove('error');
            detailTypeStatus.textContent = 'Saving…';
            try {
                const res = await fetch(`/api/projects/${activeProjectId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ project_type: projectType }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    detailTypeStatus.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                    detailTypeStatus.classList.add('error');
                    return;
                }
                // Sync cached list so the sections regroup on close/reopen
                const cached = projects.find(x => x.id === activeProjectId);
                if (cached) {
                    cached.project_type = projectType;
                    cached.is_project = (projectType === 'project');
                }
                detailTypeStatus.textContent = 'Saved';
                showToast(`Marked as ${TYPE_LABELS[projectType] || 'updated'}.`);
                loadProjects();
            } catch (err) {
                detailTypeStatus.textContent = `Network error: ${err.message}`;
                detailTypeStatus.classList.add('error');
            }
        });
    });

    // ── Closed / active toggle ─────────────────────────
    detailInactiveToggle.addEventListener('change', async () => {
        if (!activeProjectId) return;
        const makeInactive = detailInactiveToggle.checked;
        detailStatusStatus.classList.remove('error');
        detailStatusStatus.textContent = 'Saving…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ is_inactive: makeInactive }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                detailStatusStatus.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                detailStatusStatus.classList.add('error');
                detailInactiveToggle.checked = !makeInactive; // revert
                return;
            }
            const cached = projects.find(x => x.id === activeProjectId);
            if (cached) cached.is_inactive = makeInactive;
            detailStatusStatus.textContent = 'Saved';
            showToast(makeInactive ? 'Project marked closed.' : 'Project reopened.');
            loadProjects();
        } catch (err) {
            detailStatusStatus.textContent = `Network error: ${err.message}`;
            detailStatusStatus.classList.add('error');
            detailInactiveToggle.checked = !makeInactive; // revert
        }
    });

    // ── Overhead (edited in place in the Expenses list) ─
    // A cost bills and bank statements can't see, so it's typed in by hand and
    // feeds the project's cost total and profit. Delegated, because the panel
    // is re-rendered wholesale whenever the numbers change.
    // "₹2,50,000.00" / "250000" / "2,50,000" -> 250000.
    // Cleared field -> 0 (a deliberate "no overhead"); anything with content but
    // no number in it -> NaN, so junk is rejected rather than silently zeroing.
    function parseMoney(text) {
        const s = String(text ?? '').trim();
        if (!s) return 0;
        const cleaned = s.replace(/[^0-9.-]/g, '');
        if (!cleaned) return NaN;
        return Number(cleaned);
    }

    async function saveOverhead(input) {
        if (!activeProjectId) return;
        const value = parseMoney(input.value);
        const original = Number(input.dataset.raw) || 0;
        if (!Number.isFinite(value) || value < 0) {
            input.classList.add('error');
            showToast('Overhead must be a number, zero or more.', 'error');
            input.value = original ? formatINR(original) : '';
            return;
        }
        input.classList.remove('error');
        // Unchanged? Reformat and leave it alone — no request, and no repaint
        // churning the panel for nothing.
        if (Math.abs(original - value) < 0.005) {
            input.value = value ? formatINR(value) : '';
            return;
        }
        input.value = formatINR(value); // show the committed value while saving
        input.disabled = true;
        const cached = projects.find(x => x.id === activeProjectId);
        try {
            const res = await fetch(`/api/projects/${activeProjectId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ overhead: value }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                input.classList.add('error');
                input.disabled = false;
                showToast(data.message || data.error || `Failed (HTTP ${res.status})`, 'error');
                return;
            }
            if (cached) cached.overhead = value;
            // Overhead is a cost input, so the glance is now stale: refetch so
            // the list, total cost and profit all move together. This re-renders
            // the panel, replacing the (disabled) input with a fresh one.
            loadInsights(activeProjectId);
            showToast('Overhead updated.');
        } catch (err) {
            input.disabled = false;
            input.classList.add('error');
            showToast(`Network error: ${err.message}`, 'error');
        }
    }

    // Editing shows the plain number; at rest it shows the formatted figure so
    // the column stays symmetrical.
    detailOverview.addEventListener('focusin', (e) => {
        const input = e.target.closest('[data-overhead-input]');
        if (!input) return;
        const raw = Number(input.dataset.raw) || 0;
        input.value = raw ? String(raw) : '';
        input.select();
    });
    // focusout is the single commit path — it covers blur, Tab and Enter (which
    // blurs below). Wiring 'change' as well would PATCH twice.
    detailOverview.addEventListener('focusout', (e) => {
        const input = e.target.closest('[data-overhead-input]');
        if (input && !input.disabled) saveOverhead(input);
    });
    detailOverview.addEventListener('keydown', (e) => {
        const input = e.target.closest('[data-overhead-input]');
        if (!input) return;
        if (e.key === 'Enter') {
            e.preventDefault();
            input.blur();
        } else if (e.key === 'Escape') {
            const raw = Number(input.dataset.raw) || 0;
            input.value = raw ? String(raw) : ''; // discard, then let focusout no-op
            input.blur();
        }
    });

    // ── Reprocess ──────────────────────────────────────
    reprocessBtn.addEventListener('click', async () => {
        if (!activeProjectId) return;
        reprocessBtn.disabled = true;
        const orig = reprocessBtn.textContent;
        reprocessBtn.textContent = 'Reprocessing…';
        gistEl.innerHTML = `<div class="proj-gist-loading">Re-reading the PO with AI…</div>`;
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/process-po`, {
                method: 'POST', credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            currentPo = data.po || null;
            renderPoGist(currentPo);
            showToast(data.success ? 'PO reprocessed.' : (data.message || 'Extraction failed — enter the value manually.'),
                data.success ? 'success' : 'error');
            loadProjects(); // refresh card chips
        } catch (err) {
            showToast(`Network error: ${err.message}`, 'error');
            renderPoGist(currentPo);
        } finally {
            reprocessBtn.disabled = false;
            reprocessBtn.textContent = orig;
        }
    });

    // ── Edit values ────────────────────────────────────
    editBtn.addEventListener('click', () => {
        const po = currentPo || {};
        editForm.total_value.value = po.total_value ?? '';
        editForm.po_number.value = po.po_number ?? '';
        editForm.po_date.value = po.po_date ?? '';
        editForm.client_name.value = po.client_name ?? '';
        editForm.taxable_value.value = po.taxable_value ?? '';
        editForm.total_tax.value = po.total_tax ?? '';
        editError.classList.add('hidden');
        editForm.classList.remove('hidden');
        poActions.classList.add('hidden');
        gistEl.classList.add('hidden');
    });

    editCancel.addEventListener('click', exitPoEditForm);

    editForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeProjectId) return;
        editError.classList.add('hidden');
        const payload = {
            total_value: editForm.total_value.value,
            po_number: editForm.po_number.value,
            po_date: editForm.po_date.value,
            client_name: editForm.client_name.value,
            taxable_value: editForm.taxable_value.value,
            total_tax: editForm.total_tax.value,
        };
        const btn = editForm.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.textContent = 'Saving…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/po-data`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                editError.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                editError.classList.remove('hidden');
                return;
            }
            currentPo = data.po || null;
            renderPoGist(currentPo);
            exitPoEditForm();
            showToast('PO values updated.');
            loadProjects();
        } catch (err) {
            editError.textContent = `Network error: ${err.message}`;
            editError.classList.remove('hidden');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Save changes';
        }
    });

    detailUploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeProjectId) return;
        detailUploadError.classList.add('hidden');
        detailUploadError.textContent = '';

        if (!detailPoInput.files || !detailPoInput.files[0]) {
            detailUploadError.textContent = 'Please choose a file.';
            detailUploadError.classList.remove('hidden');
            return;
        }
        const fd = new FormData();
        fd.append('po_file', detailPoInput.files[0]);

        const btn = detailUploadForm.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.textContent = 'Uploading…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/upload-po`, {
                method: 'POST',
                body: fd,
                credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                detailUploadError.textContent = data.message || data.error || `Upload failed (HTTP ${res.status})`;
                detailUploadError.classList.remove('hidden');
                btn.disabled = false;
                btn.textContent = 'Upload PO';
                return;
            }
            closeModal(detailModal);
            showToast('PO uploaded successfully.');
            await loadProjects();
        } catch (err) {
            detailUploadError.textContent = `Network error: ${err.message}`;
            detailUploadError.classList.remove('hidden');
            btn.disabled = false;
            btn.textContent = 'Upload PO';
        }
    });

    // ── Boot ───────────────────────────────────────────
    loadProjects();
})();
