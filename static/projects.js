(() => {
    'use strict';

    // Soft heads-up for a MATERIAL PURCHASE debit with no matching purchase
    // bill (set server-side, helpers/bill_reconcile). Full reason in the title.
    const NO_BILL_BADGE = '<span class="no-bill-flag" title="NO CORRESPONDING PURCHASE BILL FOUND — no purchase bill from this vendor is tagged to this project. Worth verifying the project tag.">no bill</span>';

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
    const editLiBody = document.getElementById('detail-po-li-body');
    const editLiAdd = document.getElementById('detail-po-li-add');
    const editLiWarn = document.getElementById('detail-po-li-warn');

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
    // Third-party payments — the same ledger shape as cash, but money going the
    // other way: out of what the client paid us, straight on to someone else.
    const tpTotalEl = document.getElementById('detail-tp-total');
    const tpForm = document.getElementById('detail-tp-form');
    const tpToggleBtn = document.getElementById('detail-tp-toggle');
    const tpToggleLabel = document.getElementById('detail-tp-toggle-label');
    const tpPayee = document.getElementById('detail-tp-payee');
    const tpPurpose = document.getElementById('detail-tp-purpose');
    const tpAmount = document.getElementById('detail-tp-amount');
    const tpDate = document.getElementById('detail-tp-date');
    const tpAddBtn = document.getElementById('detail-tp-add');
    const tpError = document.getElementById('detail-tp-error');
    const tpListEl = document.getElementById('detail-tp-list');
    const tpReconEl = document.getElementById('detail-tp-recon');

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

    // Top-of-page filter. One bucket at a time, mapped onto the same sections
    // renderList already builds: "ongoing/designs/others" are the active
    // type buckets, "closed" is every inactive entry regardless of type, and
    // "all" restores the full grouped view. A closed design counts as closed,
    // not as a design — closed wins, matching where the row is shown.
    const FILTER_LABELS = { ongoing: 'ongoing', closed: 'closed', designs: 'design', others: 'other' };
    let activeFilter = 'all';
    // The subset a given filter shows. Kept beside renderList so the pill
    // counts and the rendered sections can't disagree about a bucket.
    function projectsForFilter(filter) {
        switch (filter) {
            case 'ongoing': return projects.filter(p => !isClosed(p) && projectTypeOf(p) === 'project');
            case 'designs': return projects.filter(p => !isClosed(p) && projectTypeOf(p) === 'design');
            case 'others':  return projects.filter(p => !isClosed(p) && projectTypeOf(p) === 'other');
            case 'closed':  return projects.filter(isClosed);
            default:        return projects.slice();
        }
    }

    let projects = [];
    let activeProjectId = null;
    let insights = null;        // /insights payload for the open project
    let cashPayments = [];      // live cash ledger for the open project
    let thirdPartyPayments = []; // live third-party ledger for the open project

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
        // Only on the projects where money was passed on. Everywhere else the
        // net equals the received figure beside it, and a cell restating its
        // neighbour is noise on a card this dense.
        const thirdParty = Number(p.third_party_total) || 0;
        if (thirdParty > 0.5) {
            const net = received - thirdParty;
            cells.push(financeCell('Net', formatINRCompact(net), 'received',
                `For VISMA, after ${formatINR(thirdParty)} paid to third parties`, net));
        }
        if (hasPoValue) {
            // Against the net, as everywhere else: money forwarded to a
            // contractor never paid down the PO (helpers/project_finance).
            const bal = poValue - (received - thirdParty);
            const settled = bal <= 0.5;
            cells.push(financeCell('Balance', settled ? 'Settled' : formatINRCompact(bal),
                settled ? 'settled' : 'due',
                settled ? 'Fully received'
                        : `Balance due (PO value − ${thirdParty > 0.5 ? 'net ' : ''}received)`,
                settled ? null : bal));
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

    // Keep the filter pills' counts in step with the loaded set. Called from
    // renderList so an add/close/type-change reflects in the pills too.
    function updateFilterCounts() {
        const counts = {
            all: projects.length,
            ongoing: projectsForFilter('ongoing').length,
            closed: projectsForFilter('closed').length,
            designs: projectsForFilter('designs').length,
            others: projectsForFilter('others').length,
        };
        Object.keys(counts).forEach(k => {
            const el = document.querySelector(`[data-filter-count="${k}"]`);
            if (el) el.textContent = counts[k];
        });
    }

    function renderList() {
        updateFilterCounts();
        if (!projects.length) {
            listEl.innerHTML = `<div class="proj-empty">No projects yet. Click <strong>+ New Project</strong> to create the first one.</div>`;
            return;
        }

        listEl.innerHTML = '';
        // Which sections a filter reveals: "all" shows the whole grouped view,
        // each other filter narrows to its one bucket.
        const showType = (key) =>
            activeFilter === 'all' ||
            (activeFilter === 'ongoing' && key === 'project') ||
            (activeFilter === 'designs' && key === 'design') ||
            (activeFilter === 'others' && key === 'other');
        const showClosed = activeFilter === 'all' || activeFilter === 'closed';

        // Active entries first, grouped by type bucket…
        TYPE_SECTIONS.forEach(sec => {
            if (!showType(sec.key)) return;
            const items = projects.filter(p => !isClosed(p) && projectTypeOf(p) === sec.key);
            if (items.length) {
                listEl.appendChild(renderSection(sec.title, sec.sub, items, sec.variant));
            }
        });
        // …then a single "Closed" section at the very bottom for every inactive
        // entry, regardless of its type bucket.
        if (showClosed) {
            const closed = projects.filter(isClosed);
            if (closed.length) {
                listEl.appendChild(renderSection(
                    'Closed', 'Inactive / completed — kept for reference', closed, 'closed'));
            }
        }
        // A filter can legitimately match nothing (e.g. no designs yet) — say so
        // rather than leaving a blank page that reads as a load failure.
        if (!listEl.children.length) {
            listEl.innerHTML = `<div class="proj-empty">No ${FILTER_LABELS[activeFilter] || ''} projects to show.</div>`;
        }
    }

    // Filter pills — single select, re-rendering the list in place.
    const filterBar = document.getElementById('proj-filter-bar');
    if (filterBar) {
        filterBar.addEventListener('click', (e) => {
            const pill = e.target.closest('.proj-filter-pill');
            if (!pill || pill.dataset.filter === activeFilter) return;
            activeFilter = pill.dataset.filter;
            filterBar.querySelectorAll('.proj-filter-pill').forEach(b => {
                const on = b === pill;
                b.classList.toggle('active', on);
                b.setAttribute('aria-selected', on ? 'true' : 'false');
            });
            renderList();
        });
    }

    // Defined once in project_glance.js — the glance and this page format the
    // same figures, so they share one set rather than two that can drift.
    const escapeHtml = ProjectGlance.escapeHtml;
    const formatINR = ProjectGlance.formatINR;
    const formatSignedINR = ProjectGlance.formatSignedINR;
    const formatINRCompact = ProjectGlance.formatINRCompact;
    const formatDeltaINR = ProjectGlance.formatDeltaINR;

    // Render a bank name as a colored badge: Axis in red, KVB in green.
    function bankBadge(bank) {
        const code = String(bank || '').trim().toLowerCase();
        const label = code ? escapeHtml(code.toUpperCase()) : '';
        if (!label) return '';
        const cls = code === 'axis' ? 'bank-axis' : code === 'kvb' ? 'bank-kvb' : '';
        return `<span class="proj-bank-badge ${cls}">${label}</span>`;
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
        thirdPartyPayments = [];
        switchTab('overview');
        switchSubTab('bills', 'purchase');
        switchSubTab('ledger', 'payments');
        ['bills', 'ledger'].forEach(k => setTabCount(k, null));
        ['purchase', 'sales', 'payments', 'expenses', 'labour', 'thirdparty']
            .forEach(k => setSubTabCount(k, null));
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
        // Third-party ledger, same collapsed-until-asked-for treatment.
        setTpFormOpen(false);
        tpForm.reset();
        tpError.classList.add('hidden');
        tpError.textContent = '';
        if (tpReconEl) tpReconEl.classList.add('hidden');
        // One fetch feeds both ledgers — the payments endpoint returns the pair
        // together, since either one moves totals the other displays.
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

    // The "Less: third-party payments" rung in the value ladder is a way in to
    // the list behind the figure — one click from the number to the payees that
    // make it up, instead of hunting for the tab that holds them.
    detailModal.addEventListener('click', (e) => {
        const link = e.target.closest('[data-glance-goto="third-party"]');
        if (!link) return;
        switchTab('ledger');
        switchSubTab('ledger', 'thirdparty');
        const panel = document.getElementById('detail-tp');
        if (panel) panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
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

    // ── Third-party form reveal (+ Add) ────────────────
    function setTpFormOpen(on) {
        tpForm.classList.toggle('hidden', !on);
        tpToggleBtn.classList.toggle('active', on);
        tpToggleLabel.textContent = on ? 'Close' : 'Add payment';
        if (on) setTimeout(() => {
            tpForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            tpPayee.focus({ preventScroll: true });
        }, 60);
    }
    tpToggleBtn.addEventListener('click', () => {
        setTpFormOpen(tpForm.classList.contains('hidden'));
    });

    // ── Project at a glance ────────────────────────────
    // Rendered by the shared module so this pop-up and the project summary page
    // can't drift apart (project_glance.js). Called twice per open — once from
    // the cached registry row for an instant paint, then again once /insights
    // lands with the full picture.
    function renderOverview(p) {
        const html = ProjectGlance.render({
            project: p,
            insights: insights,
            // The overhead field is only editable where its handlers are wired,
            // which is here — see saveOverhead below.
            editableOverhead: true,
            // Likewise the deep-link out of the third-party deduction: the
            // ledger tab it jumps to only exists in this modal.
            linkThirdParty: true,
        });
        if (html === null) {
            detailOverview.classList.add('hidden');
            detailOverview.innerHTML = '';
            return;
        }
        detailOverview.innerHTML = html;
        detailOverview.classList.remove('hidden');
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
            insights.summary.third_party_total = summary.third_party_total;
            insights.summary.net_received = summary.received_net;
            // Struck against the net receipt and the contract, exactly as the
            // server does it (helpers/project_finance) — money that arrived
            // earmarked for a contractor never paid down our own work. Optimistic
            // only; the next /insights settles it.
            const contractTotal = (insights.summary.contract && insights.summary.contract.total)
                || insights.summary.value.total || 0;
            insights.summary.receivable = contractTotal - summary.received_net;
            // The cash position moves with the receipt too (the drawer behind
            // the hero's profit figure reads it). Profit and billed profit
            // don't: neither is struck against what has been paid.
            insights.summary.cash_position =
                summary.received_net - (Number(insights.summary.spend_total) || 0);
            insights.payments.cash_total = summary.received_cash;
            insights.payments.third_party_total = summary.third_party_total;
            insights.payments.total = summary.received_total;
            insights.payments.net = summary.received_net;
        }
        const cached = projects.find(x => x.id === activeProjectId);
        if (cached) {
            cached.received_bank = summary.received_bank;
            cached.received_cash = summary.received_cash;
            cached.received_total = summary.received_total;
            cached.third_party_total = summary.third_party_total;
            cached.received_net = summary.received_net;
            renderOverview(cached);
            renderList(); // keep the registry card's "Received" in sync
        }
        renderCashList(summary.payments || []);
        renderThirdPartyList(summary.third_party_payments || []);
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
    //
    // When money has been passed on to a third party the strip carries the whole
    // subtraction — gross, less what went out, equals what is ours — because the
    // two totals are only meaningful next to each other. With nothing passed on
    // it stays the original three chips rather than showing a zero deduction.
    function renderPayModes() {
        if (!insights) { payModesEl.innerHTML = ''; return; }
        const bank = insights.payments.bank;
        const bankTotal = Number(insights.payments.bank_total) || 0;
        const cashTotal = cashPayments.reduce((s, c) => s + (Number(c.amount) || 0), 0);
        const tpTotal = thirdPartyPayments.reduce((s, t) => s + (Number(t.amount) || 0), 0);
        const gross = bankTotal + cashTotal;
        const passThrough = tpTotal > 0.5 ? `
            <div class="proj-chip deduct">
                <span class="proj-chip-k">Less: third-party</span>
                <span class="proj-chip-v">−${formatINR(tpTotal)}</span>
                <span class="proj-chip-sub">${thirdPartyPayments.length} payment${thirdPartyPayments.length === 1 ? '' : 's'}</span>
            </div>
            <div class="proj-chip accent">
                <span class="proj-chip-k">Net for VISMA</span>
                <span class="proj-chip-v">${formatINR(gross - tpTotal)}</span>
                <span class="proj-chip-sub">funds our expenses</span>
            </div>` : '';
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
            <div class="proj-chip${tpTotal > 0.5 ? '' : ' accent'}">
                <span class="proj-chip-k">Total received</span>
                <span class="proj-chip-v">${formatINR(gross)}</span>
                ${tpTotal > 0.5 ? '<span class="proj-chip-sub">from the client</span>' : ''}
            </div>
            ${passThrough}`;
    }

    // ── Third-party payments ───────────────────────────
    function renderThirdPartyList(payments) {
        thirdPartyPayments = payments || [];
        renderThirdPartyHistory();
        renderPayModes();
    }

    function renderThirdPartyHistory() {
        const total = thirdPartyPayments.reduce((s, t) => s + (Number(t.amount) || 0), 0);
        tpTotalEl.textContent = thirdPartyPayments.length
            ? `${formatINR(total)} passed on` : '';
        setSubTabCount('thirdparty', thirdPartyPayments.length);

        // The subtraction restated on the tab that drives it. The receipts it
        // comes out of live one tab over, so without this the reader has to hold
        // the gross figure in their head to make sense of the list.
        if (tpReconEl) {
            const gross = insights
                ? (Number(insights.payments.bank_total) || 0)
                  + cashPayments.reduce((s, c) => s + (Number(c.amount) || 0), 0)
                : null;
            if (total > 0.5 && gross !== null) {
                tpReconEl.innerHTML = `Client paid <b>${formatINR(gross)}</b>`
                    + ` &minus; <b>${formatINR(total)}</b> passed on`
                    + ` = <b class="net">${formatINR(gross - total)}</b> for VISMA's expenses.`;
                tpReconEl.classList.remove('hidden');
            } else {
                tpReconEl.classList.add('hidden');
            }
        }

        if (!thirdPartyPayments.length) {
            tpListEl.innerHTML = `<p class="proj-cash-empty">Nothing paid to a third party on this project. Add one when the client's money goes straight out to a contractor.</p>`;
            return;
        }
        tpListEl.innerHTML = thirdPartyPayments.map(t => {
            const when = t.payment_date ? fmtDate(t.payment_date)
                : (t.created_at ? fmtDate(String(t.created_at).slice(0, 10)) : '');
            const purpose = t.purpose || t.note || '';
            return `
                <div class="proj-cash-item">
                    <div class="proj-cash-item-main">
                        <span class="proj-cash-item-amt is-out">−${formatINR(Number(t.amount) || 0)}
                            <span class="proj-mode-badge tp" title="Paid to a third party out of the client's money">${escapeHtml(t.payee || 'Third party')}</span>
                        </span>
                        ${purpose ? `<span class="proj-cash-item-note" title="${escapeHtml(purpose)}">${escapeHtml(purpose)}</span>` : ''}
                    </div>
                    <div class="proj-cash-item-side">
                        ${when ? `<span class="proj-cash-item-date">${when}</span>` : ''}
                        <button type="button" class="proj-cash-del" data-tp-id="${t.id}" title="Remove this payment" aria-label="Remove this payment">×</button>
                    </div>
                </div>`;
        }).join('');
    }

    tpForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeProjectId) return;
        tpError.classList.add('hidden');
        tpError.textContent = '';

        const payee = tpPayee.value.trim();
        if (!payee) {
            tpError.textContent = 'Enter who the money was paid to.';
            tpError.classList.remove('hidden');
            return;
        }
        const amount = parseFloat(tpAmount.value);
        if (Number.isNaN(amount) || amount <= 0) {
            tpError.textContent = 'Enter an amount greater than zero.';
            tpError.classList.remove('hidden');
            return;
        }
        const payload = {
            payee,
            amount,
            purpose: tpPurpose.value.trim() || null,
            payment_date: tpDate.value || null,
        };
        tpAddBtn.disabled = true;
        tpAddBtn.textContent = 'Adding…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/third-party-payments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                tpError.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                tpError.classList.remove('hidden');
                return;
            }
            tpForm.reset();
            setTpFormOpen(false);
            applyPaymentSummary(data);
            showToast(`${formatINR(amount)} to ${payee} recorded as a third-party payment.`);
        } catch (err) {
            tpError.textContent = `Network error: ${err.message}`;
            tpError.classList.remove('hidden');
        } finally {
            tpAddBtn.disabled = false;
            tpAddBtn.textContent = 'Add';
        }
    });

    tpListEl.addEventListener('click', async (e) => {
        const btn = e.target.closest('.proj-cash-del');
        if (!btn || !activeProjectId) return;
        const id = btn.dataset.tpId;
        if (!id) return;
        if (!confirm('Remove this third-party payment? The full amount goes back into the received total.')) return;
        btn.disabled = true;
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/third-party-payments/${id}`, {
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
            showToast('Third-party payment removed.');
        } catch (err) {
            showToast(`Network error: ${err.message}`, 'error');
            btn.disabled = false;
        }
    });

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
        tpListEl.innerHTML = `<p class="proj-cash-empty">Loading…</p>`;
        tpTotalEl.textContent = '';
        tpError.classList.add('hidden');
        tpError.textContent = '';
        // One endpoint, both ledgers — see _payment_summary in blueprints/projects.
        fetch(`/api/projects/${projectId}/cash-payments`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                if (projectId !== activeProjectId) return; // modal changed
                renderCashList(data.payments || []);
                renderThirdPartyList(data.third_party_payments || []);
            })
            .catch(() => {
                if (projectId !== activeProjectId) return;
                cashListEl.innerHTML = `<p class="proj-cash-empty">Couldn't load cash payments.</p>`;
                tpListEl.innerHTML = `<p class="proj-cash-empty">Couldn't load third-party payments.</p>`;
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
            if (!thirdPartyPayments.length && (data.payments.third_party || []).length) {
                thirdPartyPayments = data.payments.third_party;
            }
            // Unconditionally: the reconciliation line inside the tab needs the
            // gross received, which only arrives with insights, so the list has
            // to repaint even when its own fetch already filled it.
            renderThirdPartyHistory();
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
                <td><span class="proj-cat-chip">${escapeHtml(t.category)}</span>${t.no_bill_warning ? NO_BILL_BADGE : ''}</td>
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
        const manualTag = po.extraction_status === 'manual'
            ? `<span class="proj-gist-tag">manually edited</span>` : '';

        gistEl.innerHTML = `
            <div class="proj-gist-header">
                <span class="proj-field-label">Extracted PO gist</span>${manualTag}
            </div>
            <div class="proj-gist-rows" data-gist-rows>${poGistRowsHtml(po)}</div>
            ${renderPoLineItems(po.line_items)}
            ${renderLedger(LEDGERS.variation, po)}
            ${renderLedger(LEDGERS.actual, po)}`;
    }

    // Split out from renderPoGist because a ledger edit has to refresh these
    // figures without re-rendering the grid underneath — that grid holds the
    // input the user is currently tabbing out of.
    function poGistRowsHtml(po) {
        const rev = po.revised || {
            taxable_value: po.taxable_value, total_tax: po.total_tax, total_value: po.total_value,
        };
        const fin = po.final || rev;
        const vt = po.variation_totals || { count: 0, total: 0 };
        const at = po.actual_totals || { count: 0, total: 0 };
        // Decompositions of one headline, each internally consistent:
        // contract = as-per-PO + variations (right under it), and
        // as-per-PO = taxable + tax (down with the document facts). Once the
        // work has been measured the actuals *replace* that whole sub-ladder
        // rather than extending it, so the rung it used to end on is struck
        // through and kept as history — see resolve_contract. Only worth the
        // extra rows once the contract has actually moved; an untouched PO
        // shouldn't pay for a feature it isn't using.
        const headline = at.count ? 'Final PO value'
                       : vt.count ? 'Contract value'
                       : 'Total project value';
        const rows = [[headline, formatINR(fin.total_value), 'headline']];
        if (vt.count || at.count) {
            // Once actuals exist they replace the PO and its variations
            // outright, so every rung above them is struck as one — matching the
            // glance ladder, which strikes the whole pre-actuals sub-ladder. A
            // struck "As per PO" over a live "Variations" over a struck subtotal
            // would state that the components govern but their own sum does not.
            const supAbove = at.count ? 'is-superseded' : '';
            rows.push(['As per PO', formatINR(po.total_value), supAbove]);
            if (vt.count) {
                rows.push(['Variations', `${formatDeltaINR(vt.total)} <span class="proj-gist-sub">${vt.count} change${vt.count > 1 ? 's' : ''}</span>`, supAbove]);
                if (at.count) rows.push(['Revised PO value', formatINR(rev.total_value), 'is-superseded']);
            }
            if (at.count) {
                rows.push(['Actuals', `${formatINR(at.total)} <span class="proj-gist-sub">${at.count} ${at.count > 1 ? 'entries' : 'entry'} measured</span>`]);
            }
        }
        rows.push(
            ['PO number', po.po_number ? escapeHtml(po.po_number) : '—'],
            ['PO date', po.po_date ? escapeHtml(po.po_date) : '—'],
            ['Client', po.client_name ? escapeHtml(po.client_name) : '—'],
            // Baseline, not revised: these sit above the scope line items, which
            // sum to the baseline taxable, and the whole panel is checked
            // against the PDF behind "View PO document". Showing the revised
            // split here made the gist state a taxable value that matched
            // neither the document nor the items directly beneath it.
            ['Taxable value', formatINR(po.taxable_value)],
            ['Total tax', formatINR(po.total_tax)],
            ['Scope items', po.line_item_count != null ? po.line_item_count : '—'],
        );
        if (po.payment_terms) rows.push(['Payment terms', escapeHtml(po.payment_terms)]);
        if (po.amount_in_words) rows.push(['In words', escapeHtml(po.amount_in_words)]);
        return rows.map(([k, v, cls]) => `
            <div class="proj-gist-row ${cls || ''}">
                <span class="proj-gist-k">${k}</span>
                <span class="proj-gist-v">${v}</span>
            </div>`).join('');
    }

    // ── Core line-item breakdown (description / qty / unit / rate / amount) ──
    // The GST pair is only priced per line when someone has actually entered it
    // in the editor — the extractor reads a document-level tax total — so those
    // two columns appear only when there's something to put in them, rather than
    // adding a permanent pair of dashes to every PO.
    function renderPoLineItems(items) {
        if (!Array.isArray(items) || items.length === 0) return '';
        const num = (v) => (v ? formatINR(v) : '—');
        const qty = (v) => {
            if (!v) return '—';
            // trim trailing zeros: 12.00 -> 12, 12.50 -> 12.5
            return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 });
        };
        const withGst = items.some(it => it.gst_rate || it.tax_amount);
        const body = items.map(it => `
            <tr>
                <td class="proj-li-desc">${it.description ? escapeHtml(it.description) : '—'}</td>
                <td class="proj-li-num">${qty(it.quantity)}</td>
                <td class="proj-li-unit">${it.unit ? escapeHtml(it.unit) : '—'}</td>
                <td class="proj-li-num">${num(it.rate)}</td>
                <td class="proj-li-num">${num(it.amount)}</td>
                ${withGst ? `<td class="proj-li-num">${it.gst_rate ? `${qty(it.gst_rate)}%` : '—'}</td>
                <td class="proj-li-num">${num(it.tax_amount)}</td>` : ''}
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
                                <th class="proj-li-num">${withGst ? 'Base value' : 'Amount'}</th>
                                ${withGst ? `<th class="proj-li-num">GST %</th>
                                <th class="proj-li-num">GST amount</th>` : ''}
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            </div>`;
    }

    // ── Editable line items (inside the PO values form) ─────────────────────
    // The read-only table above states what the document says; this is the same
    // rows as inputs, so a misread figure can be fixed where it was misread
    // instead of being absorbed into the header totals.
    //
    // Two derivations run as you type, each a convenience that never overrides
    // an explicit edit: Qty × Rate fills the base value, and base × GST% fills
    // the GST amount. Touch the derived field directly and your number stands
    // until you edit one of its inputs again — the last edit wins, which is the
    // same rule the header totals follow against this grid.
    const PO_LI_TEXT_FIELDS = ['description', 'unit'];
    const PO_LI_NUM_FIELDS = ['quantity', 'rate', 'amount', 'gst_rate', 'tax_amount'];
    const PO_LI_FIELDS = [...PO_LI_TEXT_FIELDS, ...PO_LI_NUM_FIELDS];

    function poLiRowHtml(it) {
        const item = it || {};
        const cell = (field, placeholder, extra = '') => `
            <input class="proj-led-input ${extra}" type="text" data-po-li-field="${field}"
                   value="${escapeHtml(item[field] == null ? '' : String(item[field]))}"
                   placeholder="${placeholder}" autocomplete="off">`;
        const numCell = (field, placeholder) => `
            <td class="proj-li-num">${cell(field, placeholder, 'proj-led-num')}</td>`;
        return `
            <tr>
                <td>${cell('description', 'e.g. MS structural fabrication')}</td>
                ${numCell('quantity', '0')}
                <td>${cell('unit', 'MT', 'proj-led-unit')}</td>
                ${numCell('rate', '0')}
                ${numCell('amount', '0')}
                ${numCell('gst_rate', '18')}
                ${numCell('tax_amount', '0')}
                <td class="proj-led-actions">
                    <button type="button" class="proj-led-btn" data-po-li-delete title="Remove this line">×</button>
                </td>
            </tr>`;
    }

    // Unlike the ledgers — whose whole block is replaced, table element and all —
    // this table outlives its rows, so decorateProjLiTables' one-shot data-mobi
    // flag would leave every row added after the first render unlabelled on a
    // phone. Clear it and walk the table again.
    function redecoratePoLiTable() {
        const table = editLiBody.closest('.proj-li-table');
        if (table) table.removeAttribute('data-mobi');
        decorateProjLiTables(editForm);
    }

    function renderPoEditLineItems(items) {
        const list = (Array.isArray(items) && items.length) ? items : [{}];
        editLiBody.innerHTML = list.map(poLiRowHtml).join('');
        redecoratePoLiTable();
        refreshPoLiTotals();
    }

    // Numbers as the user typed them, blank staying blank — an empty GST cell
    // has to reach the server as null rather than a confident zero.
    function poLiRowValues(tr) {
        const out = {};
        PO_LI_FIELDS.forEach(f => {
            const el = tr.querySelector(`[data-po-li-field="${f}"]`);
            out[f] = el ? el.value.trim() : '';
        });
        return out;
    }

    function poLiEditedItems() {
        return Array.from(editLiBody.querySelectorAll('tr'))
            .map(poLiRowValues)
            .filter(v => PO_LI_FIELDS.some(f => v[f] !== ''))
            .map(v => {
                const item = {};
                PO_LI_TEXT_FIELDS.forEach(f => { item[f] = v[f]; });
                PO_LI_NUM_FIELDS.forEach(f => {
                    const n = v[f] === '' ? null : parseMoney(v[f]);
                    item[f] = (n == null || !Number.isFinite(n)) ? null : n;
                });
                return item;
            });
    }

    function setPoLiField(tr, field, value) {
        const el = tr.querySelector(`[data-po-li-field="${field}"]`);
        if (el) el.value = value;
    }

    // Round to paise the same way the server does, so what the footer sums and
    // what lands in the column can't differ by a stray fraction.
    const round2 = (n) => Math.round(n * 100) / 100;

    function poLiDerive(tr, field) {
        const v = poLiRowValues(tr);
        if (field === 'quantity' || field === 'rate') {
            const qty = parseMoney(v.quantity);
            const rate = parseMoney(v.rate);
            if (v.quantity !== '' && v.rate !== '' && Number.isFinite(qty) && Number.isFinite(rate)) {
                v.amount = String(round2(qty * rate));
                setPoLiField(tr, 'amount', v.amount);
                field = 'amount'; // the new base flows on into GST below
            }
        }
        if (field === 'amount' || field === 'gst_rate') {
            const base = parseMoney(v.amount);
            const gstRate = parseMoney(v.gst_rate);
            if (v.gst_rate !== '' && Number.isFinite(base) && Number.isFinite(gstRate)) {
                setPoLiField(tr, 'tax_amount', String(round2(base * gstRate / 100)));
            }
        }
    }

    // The footer sums, plus the header totals they feed. A mismatch is surfaced
    // rather than silently corrected: the user may be mid-entry, and a PO whose
    // lines genuinely don't sum to its printed total is a fact about the
    // document, not something this form gets to overwrite.
    function refreshPoLiTotals(syncHeader) {
        const items = poLiEditedItems();
        const sum = (f) => items.reduce((t, it) => t + (it[f] || 0), 0);
        const base = round2(sum('amount'));
        const tax = round2(sum('tax_amount'));

        const foot = (key, val, show) => {
            const cell = editForm.querySelector(`[data-po-li-sum="${key}"]`);
            if (cell) cell.textContent = show ? formatINR(val) : '—';
        };
        foot('amount', base, items.length > 0);
        foot('tax_amount', tax, items.some(it => it.tax_amount != null));

        if (syncHeader && items.length) {
            editForm.taxable_value.value = base;
            if (items.some(it => it.tax_amount != null)) editForm.total_tax.value = tax;
            editForm.total_value.value = round2(base + parseMoney(editForm.total_tax.value));
        }

        const typedBase = parseMoney(editForm.taxable_value.value);
        const off = items.length && Number.isFinite(typedBase) && Math.abs(typedBase - base) >= 0.01;
        editLiWarn.classList.toggle('hidden', !off);
        if (off) {
            editLiWarn.textContent = `These lines add up to ${formatINR(base)}, but the taxable`
                + ` value above reads ${formatINR(typedBase)}. Both will be saved as they stand —`
                + ` fix whichever one is wrong.`;
        }
    }

    editLiBody.addEventListener('input', (e) => {
        const el = e.target.closest('[data-po-li-field]');
        if (!el) return;
        poLiDerive(el.closest('tr'), el.dataset.poLiField);
        refreshPoLiTotals(true);
    });

    editLiBody.addEventListener('click', (e) => {
        if (!e.target.closest('[data-po-li-delete]')) return;
        const tr = e.target.closest('tr');
        if (tr) tr.remove();
        if (!editLiBody.querySelector('tr')) editLiBody.innerHTML = poLiRowHtml({});
        redecoratePoLiTable();
        refreshPoLiTotals(true);
    });

    editLiAdd.addEventListener('click', () => {
        editLiBody.insertAdjacentHTML('beforeend', poLiRowHtml({}));
        redecoratePoLiTable();
        const rows = editLiBody.querySelectorAll('tr');
        const input = rows[rows.length - 1].querySelector('[data-po-li-field="description"]');
        if (input) input.focus();
    });

    // The header inputs stay authoritative when typed into — but the moment one
    // moves, the mismatch note under the grid has to agree with it.
    editForm.addEventListener('input', (e) => {
        if (['taxable_value', 'total_tax', 'total_value'].includes(e.target.name)) {
            refreshPoLiTotals(false);
        }
    });

    // ── PO ledgers: variations and actuals ─────────────────────────────────
    // A signed contract moves two ways, and each is an editable grid of priced
    // lines that share this one implementation (see blueprints PO_LEDGERS):
    //
    //   variation  a change agreed after signing — extra tonnage, or scope
    //              dropped. A delta added to the PO; a reduction is a negative
    //              weight, so the figures run signed (formatDeltaINR).
    //   actual     the work as finally measured. An absolute restatement that
    //              replaces the PO and its variations outright, because a
    //              project that came in under its PO can't honestly be written
    //              as one big negative variation. Plain figures — a measurement
    //              has no sign to show.
    //
    // Either way the extracted PO above is left exactly as the document reads,
    // which is what keeps "View PO document" honest. Amounts are computed
    // server-side (helpers/project_finance) and only previewed here, so the
    // figure that lands in the ladder is never a number this file invented.
    const LED_GST_RATE = 18; // last-resort default; the server sends po.gst_rate
    const ledFields = ['description', 'quantity', 'unit', 'rate'];
    let insightsRefreshTimer = null;

    // The two grids, differing only in wording, sign convention and endpoint.
    // `fmt` is how a total is shown; `signed` is whether a reduction is allowed
    // (matched by the server's allow_negative_qty).
    const LEDGERS = {
        variation: {
            kind: 'variation', slug: 'po-variations', signed: true,
            label: 'Variations', addLabel: '+ Add variation',
            listKey: 'variations', totalsKey: 'variation_totals',
            changeCol: 'Change', weightCol: 'Weight',
            descPlaceholder: 'e.g. Additional structural steel',
            footTitle: 'Net change',
            emptyText: 'No changes to the contract yet.',
            note: `Agreed changes to the contract. Enter a reduction as a negative weight —
                   <strong>-2</strong> subtracts exactly what <strong>2</strong> would add.`,
            addedMsg: 'Variation added.', updatedMsg: 'Variation updated.',
            removeConfirm: (l) => `Remove "${l}" from the contract?`,
            removedMsg: 'Variation removed.',
            fmt: (v) => formatDeltaINR(v),
        },
        actual: {
            kind: 'actual', slug: 'po-actuals', signed: false,
            label: 'Actuals', addLabel: '+ Add actuals',
            listKey: 'actuals', totalsKey: 'actual_totals',
            changeCol: 'Item', weightCol: 'Weight',
            descPlaceholder: 'e.g. MS angle fabrication',
            footTitle: 'Final PO value',
            emptyText: 'No actuals recorded — the contract stands at the PO plus variations.',
            note: `The work as finally measured. These <strong>replace</strong> the PO value
                   above — use this when the project finished under its PO, where a big negative
                   variation would read as a credit note rather than the real total.`,
            addedMsg: 'Actuals entry added.', updatedMsg: 'Actuals entry updated.',
            removeConfirm: (l) => `Remove "${l}" from the actuals?`,
            removedMsg: 'Actuals entry removed.',
            fmt: (v) => formatINR(v),
        },
    };

    function ledgerOf(tr) {
        const block = tr.closest('[data-led-block]');
        return LEDGERS[block ? block.dataset.ledKind : 'variation'] || LEDGERS.variation;
    }

    function trimQty(v) {
        if (v === '' || v == null) return '';
        return String(Number(v)); // 20.000 -> 20, -2.500 -> -2.5
    }

    // GST is per line, not per ledger: some items and services are outside it
    // and the auditor entering the line is the only one who knows. Stored as a
    // zero rate rather than a flag (see resolve_ledger_gst_rate server-side), so
    // a row is taxed unless it explicitly says 0 — which also means every row
    // written before this choice existed reads as "GST", exactly what it was.
    const ledIsTaxed = (v) => !(v && v.gst_rate != null && Number(v.gst_rate) === 0);
    const ledTaxed = (tr) => tr.dataset.ledGst !== 'off';

    // The rate a row prices at: the server's standard rate, or nothing at all.
    // Never a third value — this is a two-way choice, not a rate field.
    function ledGstRate(tr) {
        if (!ledTaxed(tr)) return 0;
        return (currentPo && currentPo.gst_rate != null) ? currentPo.gst_rate : LED_GST_RATE;
    }

    function setLedTaxed(tr, taxed) {
        tr.dataset.ledGst = taxed ? 'on' : 'off';
        tr.querySelectorAll('[data-led-gst-set]').forEach(btn => {
            const on = (btn.dataset.ledGstSet === 'on') === taxed;
            btn.classList.toggle('is-on', on);
            btn.setAttribute('aria-pressed', String(on));
        });
        tr.classList.toggle('is-gst-exempt', !taxed);
    }

    // Two boxes rather than a checkbox or a rate field: the auditor is choosing
    // between two named treatments, and both names stay on screen so a row's
    // answer is readable without clicking it.
    function ledGstToggleHtml(taxed) {
        const opt = (val, label, hint) => `
            <button type="button" class="proj-led-gst-opt${(val === 'on') === taxed ? ' is-on' : ''}"
                    data-led-gst-set="${val}" aria-pressed="${(val === 'on') === taxed}"
                    title="${hint}">${label}</button>`;
        return `<span class="proj-led-gst" role="group" aria-label="GST treatment">
            ${opt('on', 'GST', 'Charge GST on this line')}${opt('off', 'N/A', 'This line carries no GST')}
        </span>`;
    }

    function ledgerRowHtml(cfg, v, draft) {
        const taxed = draft ? true : ledIsTaxed(v);
        const snap = JSON.stringify({
            description: v.description || '', quantity: trimQty(v.quantity || 0),
            unit: v.unit || '', rate: trimQty(v.rate || 0),
            gst: taxed ? 'on' : 'off',
        });
        // Unlike the overhead field, qty/rate stay as raw numbers at rest rather
        // than swapping formatted<->raw on focus. Overhead is a lone input
        // inside a read-only tabulation, where a bare 250000 looked broken; this
        // is a grid of inputs, where a value that rewrites itself on every blur
        // is just noise mid-entry.
        const cell = (field, extra, placeholder) => `
            <input class="proj-led-input ${extra}" type="text" data-led-field="${field}"
                   value="${escapeHtml(String(v[field] == null ? '' : v[field]))}"
                   placeholder="${placeholder}" autocomplete="off">`;
        return `
            <tr data-led-id="${draft ? 'new' : v.id}" data-led-gst="${taxed ? 'on' : 'off'}"
                class="${draft ? 'is-draft' : ''}${taxed ? '' : ' is-gst-exempt'}"
                data-led-snapshot='${escapeHtml(snap)}'>
                <td>${cell('description', '', cfg.descPlaceholder)}</td>
                <td class="proj-li-num"><input class="proj-led-input proj-led-num" type="text"
                        inputmode="decimal" data-led-field="quantity"
                        value="${trimQty(v.quantity || '')}" placeholder="0" autocomplete="off"></td>
                <td>${cell('unit', 'proj-led-unit', 'MT')}</td>
                <td class="proj-li-num"><input class="proj-led-input proj-led-num" type="text"
                        inputmode="decimal" data-led-field="rate"
                        value="${trimQty(v.rate || '')}" placeholder="0" autocomplete="off"></td>
                <td class="proj-li-num" data-led-out="basic">${cfg.fmt(v.basic_amount || 0)}</td>
                <td class="proj-li-num proj-led-tax">${ledGstToggleHtml(taxed)}<span
                        data-led-out="tax">${cfg.fmt(v.tax_amount || 0)}</span></td>
                <td class="proj-li-num proj-led-total" data-led-out="total">${cfg.fmt(v.total_amount || 0)}</td>
                <td class="proj-led-actions">${draft
                    ? `<button type="button" class="proj-led-btn is-save" data-led-save title="Save this entry">✓</button>
                       <button type="button" class="proj-led-btn" data-led-discard title="Discard">×</button>`
                    : `<button type="button" class="proj-led-btn" data-led-delete title="Remove this entry">×</button>`}
                </td>
            </tr>`;
    }

    function ledgerEmptyRow(cfg) {
        return `<tr class="proj-led-empty-row" data-led-empty>
            <td colspan="8">${cfg.emptyText}</td></tr>`;
    }

    function ledgerFootHtml(cfg, vt) {
        if (!vt || !vt.count) return '';
        // data-label is stamped by hand here: decorateProjLiTables only walks
        // tbody, so on a phone — where this becomes a card like the rows above —
        // these cells would otherwise lose their headings along with the thead.
        return `<tfoot><tr>
                <td colspan="4" class="proj-led-foot-title">${cfg.footTitle}</td>
                <td class="proj-li-num" data-label="Basic">${cfg.fmt(vt.taxable)}</td>
                <td class="proj-li-num" data-label="GST">${cfg.fmt(vt.tax)}</td>
                <td class="proj-li-num proj-led-total" data-label="Total">${cfg.fmt(vt.total)}</td>
                <td class="proj-led-foot-pad"></td>
            </tr></tfoot>`;
    }

    function renderLedger(cfg, po) {
        const list = (po && po[cfg.listKey]) || [];
        const vt = (po && po[cfg.totalsKey]) || { count: 0, taxable: 0, tax: 0, total: 0 };
        const rate = (po && po.gst_rate != null) ? po.gst_rate : LED_GST_RATE;
        // The supersede badge earns its place only once actuals actually exist:
        // it's how the block says the ladder above no longer governs.
        const badge = (cfg.kind === 'actual' && vt.count)
            ? `<span class="proj-led-supersede">supersedes PO</span>` : '';
        const blockCls = cfg.kind === 'actual' && vt.count ? ' is-actuals' : '';
        return `
            <div class="proj-gist-items proj-led-block${blockCls}" data-led-block data-led-kind="${cfg.kind}">
                <div class="proj-led-head">
                    <span class="proj-field-label">${cfg.label}${vt.count ? ` (${vt.count})` : ''}${badge}</span>
                    <button type="button" class="proj-secondary-btn proj-led-add" data-led-add>${cfg.addLabel}</button>
                </div>
                <p class="proj-note proj-led-note">${cfg.note}
                   Each line is taxed at ${rate}% or not at all — pick
                   <strong>GST</strong> or <strong>N/A</strong> in the GST column.</p>
                <div class="proj-li-scroll">
                    <table class="proj-li-table proj-led-table">
                        <thead>
                            <tr>
                                <th>${cfg.changeCol}</th><th class="proj-li-num">${cfg.weightCol}</th><th>Unit</th>
                                <th class="proj-li-num">Rate</th><th class="proj-li-num">Basic</th>
                                <th class="proj-li-num">GST</th><th class="proj-li-num">Total</th><th></th>
                            </tr>
                        </thead>
                        <tbody data-led-body>${list.length ? list.map(v => ledgerRowHtml(cfg, v, false)).join('') : ledgerEmptyRow(cfg)}</tbody>
                        ${ledgerFootHtml(cfg, vt)}
                    </table>
                </div>
            </div>`;
    }

    // ── Ledger edit plumbing ────────────────────────
    function ledRowValues(tr) {
        const out = {};
        ledFields.forEach(f => {
            const el = tr.querySelector(`[data-led-field="${f}"]`);
            out[f] = el ? el.value.trim() : '';
        });
        return out;
    }

    // Mirrors compute_ledger_amounts server-side so the figures move as you
    // type. Purely a preview — the row repaints from the server's answer on save.
    function previewLedgerRow(tr) {
        const cfg = ledgerOf(tr);
        const v = ledRowValues(tr);
        const qty = parseMoney(v.quantity);
        const rate = parseMoney(v.rate);
        const ok = Number.isFinite(qty) && Number.isFinite(rate);
        const basic = ok ? Math.round(qty * rate * 100) / 100 : 0;
        // ledGstRate reads this row's GST / N/A choice, and takes the taxed rate
        // from the server rather than the local constant, so PO_LEDGER_GST_RATE
        // stays the single place it's set — otherwise changing it there would
        // leave the preview quoting the old rate right up until save.
        const tax = Math.round(basic * ledGstRate(tr)) / 100;
        const set = (key, val) => {
            const cell = tr.querySelector(`[data-led-out="${key}"]`);
            if (cell) cell.textContent = cfg.fmt(val);
        };
        set('basic', basic);
        set('tax', tax);
        set('total', Math.round((basic + tax) * 100) / 100);
    }

    // Repaint everything a variation change moves *except* the variations table
    // itself, whose inputs the user may still be inside.
    function applyPoChange(po) {
        currentPo = po || null;
        const rowsEl = gistEl.querySelector('[data-gist-rows]');
        if (rowsEl && po) rowsEl.innerHTML = poGistRowsHtml(po);
        // Refresh each ledger's foot + head in place, without touching its
        // tbody (which may hold the input the user just tabbed out of). Same
        // reasoning for both grids, so it runs once per ledger.
        Object.values(LEDGERS).forEach(cfg => {
            const block = gistEl.querySelector(`[data-led-block][data-led-kind="${cfg.kind}"]`);
            if (!block) return;
            const vt = (po && po[cfg.totalsKey]) || { count: 0 };
            const table = block.querySelector('.proj-led-table');
            const foot = table && table.querySelector('tfoot');
            const footHtml = ledgerFootHtml(cfg, vt);
            // Replacing with '' removes the node outright, so re-adding it later
            // needs the table, not the (now detached) tfoot, as the anchor.
            if (foot) foot.outerHTML = footHtml;
            else if (footHtml && table) table.insertAdjacentHTML('beforeend', footHtml);
            const head = block.querySelector('.proj-led-head .proj-field-label');
            if (head) {
                const badge = (cfg.kind === 'actual' && vt.count)
                    ? ' <span class="proj-led-supersede">supersedes PO</span>' : '';
                head.innerHTML = `${cfg.label}${vt.count ? ` (${vt.count})` : ''}${badge}`;
            }
            block.classList.toggle('is-actuals', cfg.kind === 'actual' && !!vt.count);
        });
        // The glance ladder reads the *cached* registry row, not insights, so
        // the cache has to move too or the panel repaints to a stale contract.
        const cached = projects.find(x => x.id === activeProjectId);
        if (cached) {
            const vt = (po && po.variation_totals) || { count: 0 };
            const at = (po && po.actual_totals) || { count: 0 };
            const fin = po && po.final;
            // po === null means nothing is left to show — no gist row and
            // neither ledger. Skipping the cache then left the card advertising
            // a contract that no longer exists, and renderList() below would
            // repaint it straight back.
            cached.po_total_value = fin ? fin.total_value : null;
            cached.po_taxable_value = fin ? fin.taxable_value : null;
            cached.po_total_tax = fin ? fin.total_tax : null;
            // Every field the ladder reads, not just the final totals: it
            // derives its Contract / Variations / Actuals blocks from the
            // baseline and both rollups, so refreshing only the totals left it
            // announcing "3 entries measured" above a value still showing the
            // pre-actuals figure.
            cached.po_base_taxable_value = po ? po.taxable_value : null;
            cached.po_base_total_tax = po ? po.total_tax : null;
            cached.po_base_total_value = po ? po.total_value : null;
            cached.po_var_taxable = vt.taxable || 0;
            cached.po_var_tax = vt.tax || 0;
            cached.po_var_total = vt.total || 0;
            cached.po_var_count = vt.count;
            cached.po_act_taxable = at.taxable || 0;
            cached.po_act_tax = at.tax || 0;
            cached.po_act_total = at.total || 0;
            cached.po_act_count = at.count;
        }
        // Contract value feeds the ladder and what the client still owes, so the
        // glance is now stale. Debounced because insights is the heaviest query
        // in the app — bills, bank rows and the external salary API — and
        // tabbing across a row would otherwise fire it once per field, flicker
        // the panel through stale numbers, and risk the API returning 0 labour.
        clearTimeout(insightsRefreshTimer);
        const pid = activeProjectId;
        insightsRefreshTimer = setTimeout(() => {
            if (pid === activeProjectId) loadInsights(pid);
        }, 400);
        renderList();
    }

    function ledRowError(tr, msg) {
        tr.classList.add('error');
        showToast(msg, 'error');
    }

    async function saveLedgerRow(tr) {
        const cfg = ledgerOf(tr);
        // A save already in flight for this row: remember that the row moved on
        // and re-run once it lands. Returning here without this dropped the
        // edit silently AND let the in-flight save stamp a snapshot taken
        // before it, so the row looked saved and wasn't.
        if (tr.classList.contains('is-saving')) {
            tr.dataset.ledPending = '1';
            return;
        }
        const v = ledRowValues(tr);
        const isDraft = tr.dataset.ledId === 'new';
        if (!v.description) {
            // Says so for saved rows too, not just drafts: blanking the
            // description while editing the weight used to bail out here with
            // no request and no message, silently discarding every later edit
            // to that row for as long as it stayed blank.
            ledRowError(tr, 'This entry needs a description.');
            return;
        }
        const qty = parseMoney(v.quantity);
        const rate = parseMoney(v.rate);
        if (!Number.isFinite(qty) || !Number.isFinite(rate)) {
            ledRowError(tr, 'Weight and rate must be numbers.');
            return;
        }
        if (rate < 0) {
            ledRowError(tr, 'Rate must be zero or more' +
                (cfg.signed ? ' — use a negative weight to reduce scope.' : '.'));
            return;
        }
        // Actuals are a measurement: a negative weight is how a variations habit
        // would (wrongly) reach for an under-run, which the smaller total
        // already expresses. Caught here so the message lands before the round
        // trip, though the server refuses it too.
        if (!cfg.signed && qty < 0) {
            ledRowError(tr, 'Weight must be zero or more — a project under its PO is just a smaller total.');
            return;
        }
        // Unchanged? Leave it be — no request, no repaint. Same guard as the
        // overhead field, since focusout fires on every field the user tabs out
        // of, changed or not.
        const snap = tr.dataset.ledSnapshot;
        const now = JSON.stringify({
            description: v.description, quantity: trimQty(qty), unit: v.unit, rate: trimQty(rate),
            gst: ledTaxed(tr) ? 'on' : 'off',
        });
        if (!isDraft && snap === now) return;

        tr.classList.remove('error');
        tr.classList.add('is-saving');
        delete tr.dataset.ledPending;
        // gst_rate is always sent, including the 0 that means N/A: leaving it out
        // would let the server fall back to the standard rate and quietly tax a
        // line the auditor marked exempt.
        const body = JSON.stringify({ ...v, quantity: qty, rate, gst_rate: ledGstRate(tr) });
        // Pinned for the round trip: blurring a cell can close the modal, and
        // the response must not be applied to whichever project is open by the
        // time it lands. Same reason loadPoGist guards its own response.
        const pid = activeProjectId;
        const base = `/api/projects/${pid}/${cfg.slug}`;
        try {
            const res = await fetch(isDraft ? base : `${base}/${tr.dataset.ledId}`, {
                method: isDraft ? 'POST' : 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body,
            });
            const data = await res.json().catch(() => ({}));
            tr.classList.remove('is-saving');
            if (pid !== activeProjectId) return; // modal changed under us
            if (!res.ok) {
                ledRowError(tr, data.message || data.error || `Failed (HTTP ${res.status})`);
                return;
            }
            if (isDraft) {
                // A new row shifts the table anyway, so a full repaint costs
                // nothing here and leaves the grid ready for the next entry.
                renderPoGist(data.po);
                showToast(cfg.addedMsg);
            } else {
                tr.dataset.ledSnapshot = now;
                const v2 = data.row || {};
                ['basic', 'tax', 'total'].forEach(k => {
                    const cell = tr.querySelector(`[data-led-out="${k}"]`);
                    if (cell) cell.textContent = cfg.fmt(v2[`${k}_amount`] || 0);
                });
                showToast(cfg.updatedMsg);
            }
            applyPoChange(data.po);
            // Edited again while that was in flight — the row on screen is
            // ahead of what the server just stored, so send the difference.
            if (tr.dataset.ledPending && tr.isConnected) {
                delete tr.dataset.ledPending;
                saveLedgerRow(tr);
            }
        } catch (err) {
            tr.classList.remove('is-saving');
            ledRowError(tr, `Network error: ${err.message}`);
        }
    }

    async function deleteLedgerRow(tr) {
        const cfg = ledgerOf(tr);
        const label = (tr.querySelector('[data-led-field="description"]') || {}).value || 'this entry';
        if (!confirm(cfg.removeConfirm(label))) return;
        tr.classList.add('is-saving');
        const pid = activeProjectId; // see saveLedgerRow
        try {
            const res = await fetch(
                `/api/projects/${pid}/${cfg.slug}/${tr.dataset.ledId}`,
                { method: 'DELETE', credentials: 'same-origin' });
            const data = await res.json().catch(() => ({}));
            if (pid !== activeProjectId) return; // modal changed under us
            if (!res.ok) {
                tr.classList.remove('is-saving');
                ledRowError(tr, data.message || data.error || `Failed (HTTP ${res.status})`);
                return;
            }
            renderPoGist(data.po);
            applyPoChange(data.po);
            showToast(cfg.removedMsg);
        } catch (err) {
            tr.classList.remove('is-saving');
            ledRowError(tr, `Network error: ${err.message}`);
        }
    }

    // Delegated: the gist is re-rendered wholesale whenever the contract moves.
    gistEl.addEventListener('click', (e) => {
        const addBtn = e.target.closest('[data-led-add]');
        if (addBtn) {
            const block = addBtn.closest('[data-led-block]');
            const cfg = LEDGERS[block ? block.dataset.ledKind : 'variation'];
            const body = block.querySelector('[data-led-body]');
            if (!body || body.querySelector('.is-draft')) return; // one draft at a time
            const empty = body.querySelector('[data-led-empty]');
            if (empty) empty.remove();
            body.insertAdjacentHTML('beforeend', ledgerRowHtml(cfg, {}, true));
            // decorateProjLiTables skips tables it has already stamped, so a row
            // added after that first pass would reach a phone with no
            // data-label on any cell — four unlabelled boxes you can't tell
            // apart. Clear the stamp so the new row gets decorated too.
            const table = body.closest('.proj-li-table');
            if (table) {
                table.removeAttribute('data-mobi');
                decorateProjLiTables(gistEl);
            }
            const first = body.querySelector('.is-draft [data-led-field="description"]');
            if (first) first.focus();
            return;
        }
        const gstBtn = e.target.closest('[data-led-gst-set]');
        if (gstBtn) {
            const tr = gstBtn.closest('tr');
            const want = gstBtn.dataset.ledGstSet === 'on';
            if (ledTaxed(tr) === want) return; // already this treatment
            setLedTaxed(tr, want);
            previewLedgerRow(tr);
            // Unlike the text cells, this choice has no blur of its own to
            // commit on — clicking it *is* the edit — so a saved row saves here.
            // A draft still waits for ✓ or Enter, like every other field in it.
            if (tr.dataset.ledId !== 'new') saveLedgerRow(tr);
            return;
        }
        const saveBtn = e.target.closest('[data-led-save]');
        if (saveBtn) { saveLedgerRow(saveBtn.closest('tr')); return; }
        const discardBtn = e.target.closest('[data-led-discard]');
        if (discardBtn) {
            const block = discardBtn.closest('[data-led-block]');
            const cfg = LEDGERS[block ? block.dataset.ledKind : 'variation'];
            const body = block.querySelector('[data-led-body]');
            discardBtn.closest('tr').remove();
            if (body && !body.children.length) body.innerHTML = ledgerEmptyRow(cfg);
            return;
        }
        const delBtn = e.target.closest('[data-led-delete]');
        if (delBtn) deleteLedgerRow(delBtn.closest('tr'));
    });

    gistEl.addEventListener('input', (e) => {
        const field = e.target.closest('[data-led-field]');
        if (field) previewLedgerRow(field.closest('tr'));
    });

    // focusout is the single commit path for saved rows, matching the overhead
    // field. A draft row is explicitly *not* committed on blur: clicking away
    // from a half-typed entry would post one the user never confirmed.
    gistEl.addEventListener('focusout', (e) => {
        const field = e.target.closest('[data-led-field]');
        if (!field) return;
        const tr = field.closest('tr');
        // saveLedgerRow owns the in-flight case now — it queues rather than
        // drops, so blurring mid-save no longer loses the edit.
        if (tr && tr.dataset.ledId !== 'new') saveLedgerRow(tr);
    });

    gistEl.addEventListener('keydown', (e) => {
        const field = e.target.closest('[data-led-field]');
        if (!field) return;
        const tr = field.closest('tr');
        if (e.key === 'Enter') {
            e.preventDefault();
            if (tr.dataset.ledId === 'new') saveLedgerRow(tr);
            else field.blur();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            // Escape on the document closes every open modal. Here it means
            // "undo this cell" — without stopping it, discarding a typo would
            // also shut the whole project pop-up and lose the user's place.
            e.stopPropagation();
            if (tr.dataset.ledId === 'new') {
                const block = tr.closest('[data-led-block]');
                const cfg = LEDGERS[block ? block.dataset.ledKind : 'variation'];
                const body = block.querySelector('[data-led-body]');
                tr.remove();
                if (body && !body.children.length) body.innerHTML = ledgerEmptyRow(cfg);
                return;
            }
            // Restore from the snapshot, then let focusout no-op.
            const snap = JSON.parse(tr.dataset.ledSnapshot || '{}');
            ledFields.forEach(f => {
                const el = tr.querySelector(`[data-led-field="${f}"]`);
                if (el) el.value = snap[f] == null ? '' : snap[f];
            });
            // The GST choice is part of the row, so "undo this row" undoes it too.
            if (snap.gst) setLedTaxed(tr, snap.gst !== 'off');
            previewLedgerRow(tr);
            field.blur();
        }
    });

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
            // Escape on the document closes every open modal. Inside a field it
            // means "undo this cell", so the event stops here — otherwise
            // discarding a typo also shut the whole project pop-up and threw the
            // user out of the panel they were working in. preventDefault alone
            // wouldn't do it: bubbling is what reaches the document listener.
            e.preventDefault();
            e.stopPropagation();
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
        editForm.currency.value = po.currency ?? '';
        editForm.payment_terms.value = po.payment_terms ?? '';
        editForm.amount_in_words.value = po.amount_in_words ?? '';
        renderPoEditLineItems(po.line_items);
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
            currency: editForm.currency.value,
            payment_terms: editForm.payment_terms.value,
            amount_in_words: editForm.amount_in_words.value,
            // Replaces the stored list outright — a line deleted here is gone,
            // and the server re-derives line_item_count from what arrives.
            line_items: poLiEditedItems(),
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
