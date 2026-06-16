"""Pure project-name matching / stem helpers (no app or DB state).

These power the fuzzy mapping between free-text project tags on bank
transactions, bills, and salary records, and the canonical project registry.
"""

import re

from extensions import db_manager


def get_project_stems(project_str):
    """Extract first token (stem) from each project name for fuzzy matching.
    'RCH CT,SHOBA' -> ['rch', 'shoba']"""
    if not project_str:
        return []
    projects = [p.strip() for p in project_str.split(',') if p.strip()]
    stems = []
    for p in projects:
        tokens = p.split()
        first_token = tokens[0].lower() if tokens else p.lower()
        stems.append(first_token)
    return stems


NON_PROJECT_STEMS = {
    'axis', 'axi', 'kvb', 'factory', 'labour', 'labor', 'office', 'bank', 'salary',
    'tax', 'gst', 'tds', 'neft', 'rtgs', 'imps', 'upi', 'interest', 'charges',
    'unknown', 'unassigned', 'general', 'misc', 'amount', 'transfer', 'return',
    'received', 'payment', 'deposit', 'withdrawal', 'credit', 'debit'
}

PROJECT_ALIASES = {
    'palson': 'polson',
    'polsons': 'polson',
}


def normalize_project_stem(name):
    """Lowercase, strip whitespace, normalize plurals via alias lookup only."""
    s = name.lower().strip()
    # Check exact alias first
    if s in PROJECT_ALIASES:
        return PROJECT_ALIASES[s]
    # Try stripping trailing 's'/'es' and check if the base form is a known alias
    if s.endswith('es') and len(s) > 3:
        candidate = s[:-2]
        if candidate in PROJECT_ALIASES:
            return PROJECT_ALIASES[candidate]
    elif s.endswith('s') and len(s) > 2:
        candidate = s[:-1]
        if candidate in PROJECT_ALIASES:
            return PROJECT_ALIASES[candidate]
    # Return as-is (no blind plural stripping)
    return s


def build_smart_project_groups(all_project_names, bill_projects):
    """Build smart stem-based project groups from bank txn projects and bill projects.

    Returns {canonical_stem: set(original_project_names)}
    """
    # Merge all project names
    all_names = set()
    for name in all_project_names:
        s = str(name).strip()
        if s and s.lower() != 'nan':
            all_names.add(s)
    for name in bill_projects:
        s = str(name).strip()
        if s and s.lower() != 'nan':
            all_names.add(s)

    # Build candidate stems from first words of all names
    candidate_stems = set()
    for name in all_names:
        tokens = name.split()
        if tokens:
            candidate_stems.add(normalize_project_stem(tokens[0]))

    stem_groups = {}  # canonical_stem -> set of original names

    for name in all_names:
        s = name.strip()
        if not s:
            continue

        stem = None

        # Rule 1: If name contains ' - ' (dash separator), extract part AFTER dash
        if ' - ' in s:
            after_dash = s.split(' - ', 1)[1].strip()
            if after_dash:
                first_token = after_dash.split()[0] if after_dash.split() else after_dash
                candidate = normalize_project_stem(first_token)
                if candidate not in NON_PROJECT_STEMS:
                    stem = candidate

        # Rule 2: Check all tokens against candidate stems
        if stem is None:
            tokens = s.split()
            for token in tokens:
                candidate = normalize_project_stem(token)
                if candidate not in NON_PROJECT_STEMS and candidate in candidate_stems:
                    stem = candidate
                    break

        # Rule 3: Fallback - use first word
        if stem is None:
            tokens = s.split()
            first = normalize_project_stem(tokens[0]) if tokens else normalize_project_stem(s)
            if first not in NON_PROJECT_STEMS:
                stem = first

        # Skip if all tokens are non-project stems
        if stem is None or stem in NON_PROJECT_STEMS:
            continue

        stem_groups.setdefault(stem, set()).add(name)

    return stem_groups


def match_bills_to_project_groups(bills_list, stem_groups):
    """Match bills to project stem groups.

    Returns {stem: [list of bill dicts]}
    """
    # Build reverse lookup: original_name -> stem
    name_to_stem = {}
    for stem, names in stem_groups.items():
        for name in names:
            name_to_stem[name] = stem

    result = {}
    for bill in bills_list:
        project = str(bill.get('project', '') or '').strip()
        if not project or project.lower() == 'nan':
            continue

        matched_stem = name_to_stem.get(project)

        # If not directly matched, try fuzzy matching with same logic
        if matched_stem is None:
            if ' - ' in project:
                after_dash = project.split(' - ', 1)[1].strip()
                if after_dash:
                    first_token = after_dash.split()[0] if after_dash.split() else after_dash
                    candidate = normalize_project_stem(first_token)
                    if candidate in stem_groups:
                        matched_stem = candidate
            if matched_stem is None:
                tokens = project.split()
                for token in tokens:
                    candidate = normalize_project_stem(token)
                    if candidate in stem_groups:
                        matched_stem = candidate
                        break
            if matched_stem is None:
                tokens = project.split()
                first = normalize_project_stem(tokens[0]) if tokens else normalize_project_stem(project)
                if first in stem_groups:
                    matched_stem = first

        if matched_stem:
            result.setdefault(matched_stem, []).append(bill)

    return result


def match_labour_to_project_groups(labour_costs, stem_groups):
    """Match salary/attendance project names to stem groups.

    labour_costs: {project_name: cost} from salary DB
    stem_groups: {stem: set(names)} from build_smart_project_groups

    Returns {stem: total_labour_cost}
    """
    # Build reverse lookup from existing stem groups
    name_to_stem = {}
    for stem, names in stem_groups.items():
        for name in names:
            name_to_stem[name.lower().strip()] = stem

    result = {}
    for project, cost in labour_costs.items():
        p = project.strip()
        p_lower = p.lower()

        # Direct match
        matched_stem = name_to_stem.get(p_lower)

        # Fuzzy match using same logic as other matchers
        if matched_stem is None:
            if ' - ' in p:
                after_dash = p.split(' - ', 1)[1].strip()
                if after_dash:
                    candidate = normalize_project_stem(after_dash.split()[0])
                    if candidate in stem_groups:
                        matched_stem = candidate
        if matched_stem is None:
            tokens = p.split()
            for token in tokens:
                candidate = normalize_project_stem(token)
                if candidate in stem_groups:
                    matched_stem = candidate
                    break
        if matched_stem is None:
            tokens = p.split()
            first = normalize_project_stem(tokens[0]) if tokens else normalize_project_stem(p)
            if first in stem_groups:
                matched_stem = first

        if matched_stem:
            result[matched_stem] = result.get(matched_stem, 0) + cost

    return result


_CANONICAL_PROJECT_RE = re.compile(r'^\s*(\d+)\s*-')


def parse_project_selection(project_str):
    """Parse a comma-separated project filter into strict and fuzzy terms.

    Canonical selections ("659 - JAMUNA") are matched STRICTLY by their id
    prefix — the registry-fed UI always sends this form. Free-text
    selections (legacy callers) keep stem-prefix matching.

    Returns (ids, stems).
    """
    ids, stems = [], []
    for p in (project_str or '').split(','):
        p = p.strip()
        if not p or p == 'All':
            continue
        m = _CANONICAL_PROJECT_RE.match(p)
        if m:
            ids.append(int(m.group(1)))
        else:
            tokens = p.split()
            stems.append(normalize_project_stem(tokens[0].lower()) if tokens else p.lower())
    return ids, stems


def project_value_matches_selection(value, selection):
    """True when a project tag matches the parsed selection (ids, stems).

    Canonical ids match strictly on the "<id> -" tag prefix. Stems do a
    prefix test on the raw value and on the segment after " - "."""
    ids, stems = selection
    v = str(value or '').strip()
    if not v:
        return False
    m = _CANONICAL_PROJECT_RE.match(v)
    if ids and m and int(m.group(1)) in ids:
        return True
    if stems:
        low = v.lower()
        after_dash = low.split(' - ', 1)[-1].strip()
        for s in stems:
            if low.startswith(s) or after_dash.startswith(s):
                return True
    return False


def _canonical_project_set():
    """Return a case-insensitive map of display_form_lower -> canonical_display."""
    try:
        projects = db_manager.list_projects()
    except Exception:
        projects = []
    return {p['display'].lower(): p['display'] for p in projects}


def validate_project_value(raw_value):
    """Normalize and validate a project value against the canonical registry.

    Returns (ok, normalized_value, error_message).
    - Empty / None  -> (True, '', None)
    - Canonical hit -> (True, canonical_display, None)
    - Anything else -> (False, raw_value, "<readable error>")
    """
    value = (raw_value or '').strip()
    if not value:
        return True, '', None
    canonical = _canonical_project_set()
    hit = canonical.get(value.lower())
    if hit:
        return True, hit, None
    return False, value, (
        f"Project '{value}' is not in the canonical registry. "
        "Pick one from the Projects page (or leave blank)."
    )
