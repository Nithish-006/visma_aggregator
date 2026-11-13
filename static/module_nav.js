/* module_nav.js - the module switcher (templates/_module_nav.html).
   Click the header button, or press Ctrl/Cmd+K, to open the list of modules.
   While open: 1-7 jumps straight to a module, arrows move, Esc closes. */
(function () {
    const trigger = document.getElementById('mnav-trigger');
    const panel = document.getElementById('mnav-panel');
    const scrim = document.getElementById('mnav-scrim');
    if (!trigger || !panel || !scrim) return;

    const links = () => Array.from(panel.querySelectorAll('a'));
    const modules = () => Array.from(panel.querySelectorAll('.mnav-item'));
    const isOpen = () => !panel.hidden;
    const isPhone = () => window.matchMedia('(max-width: 640px)').matches;

    function place() {
        if (isPhone()) { panel.style.top = ''; panel.style.left = ''; return; }
        const r = trigger.getBoundingClientRect();
        const w = panel.offsetWidth || 300;
        const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
        panel.style.top = Math.round(r.bottom + 8) + 'px';
        panel.style.left = Math.round(left) + 'px';
    }

    function open() {
        if (isOpen()) return;
        panel.hidden = false;
        scrim.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        place();
        const target = panel.querySelector('.mnav-item:not(.is-current)') || links()[0];
        if (target) target.focus({ preventScroll: true });
    }

    function close(returnFocus) {
        if (!isOpen()) return;
        panel.hidden = true;
        scrim.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        if (returnFocus) trigger.focus({ preventScroll: true });
    }

    // Pages with unsaved edits (the bank dashboard) expose a counter. Ask
    // before leaving instead of silently dropping the work.
    function okToLeave() {
        const n = typeof window.vismaUnsavedChanges === 'function' ? window.vismaUnsavedChanges() : 0;
        return !n || window.confirm(`You have ${n} unsaved change${n === 1 ? '' : 's'} on this page. Leave without saving?`);
    }

    function go(a) {
        if (!a || a.classList.contains('is-current')) { close(true); return; }
        if (!okToLeave()) return;
        window.location.href = a.href;
    }

    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        isOpen() ? close(true) : open();
    });
    scrim.addEventListener('click', () => close(false));

    panel.addEventListener('click', (e) => {
        const a = e.target.closest('a');
        if (!a) return;
        // Let ctrl/cmd/shift/middle-click open a new tab as usual.
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        go(a);
    });

    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            isOpen() ? close(true) : open();
            return;
        }
        if (!isOpen()) return;
        if (e.key === 'Escape') { e.preventDefault(); close(true); return; }
        if (/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const m = modules()[Number(e.key) - 1];
            if (m) { e.preventDefault(); go(m); }
            return;
        }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const all = links();
            const i = all.indexOf(document.activeElement);
            const next = e.key === 'ArrowDown' ? (i + 1) % all.length : (i - 1 + all.length) % all.length;
            all[next].focus();
        }
        if (e.key === 'Tab') {
            // Keep focus inside while open; leaving the list closes it.
            const all = links();
            const i = all.indexOf(document.activeElement);
            if ((e.shiftKey && i === 0) || (!e.shiftKey && i === all.length - 1)) close(false);
        }
    });

    window.addEventListener('resize', () => { if (isOpen()) place(); });
    // Coming back via the browser's back button can restore the page with the
    // panel still open (bfcache); start closed.
    window.addEventListener('pageshow', () => close(false));
})();
