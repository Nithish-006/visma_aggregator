"""Client for the external Project Salary API.

This replaces the app's old direct-to-attendance-DB labour salary calculations.
Every labour/salary figure shown in the project canonical registry, the project
summary page, and the Excel export is now sourced from this API, which prices
attendance against the salary table server-side. See ``salary-project-api.md``
for the full contract.

Configuration (environment variables):
    SALARY_API_BASE_URL   e.g. https://salary-app.up.railway.app
    SALARY_API_KEY        the shared X-API-Key value

The public helpers below intentionally mirror the return shapes of the old
``DatabaseManager.get_labour_*`` methods so the consuming views/exports needed
only their data source swapped, not their rendering logic.
"""

import calendar
import os
import threading
import time

import requests

_TIMEOUT = 25  # seconds per request
_session = requests.Session()


class SalaryApiError(Exception):
    """Raised when the salary API is unreachable or returns a non-200."""


def _base_url():
    return (os.environ.get('SALARY_API_BASE_URL') or '').rstrip('/')


def _api_key():
    return os.environ.get('SALARY_API_KEY') or ''


def is_configured():
    """True only when both the base URL and the API key are present."""
    return bool(_base_url() and _api_key())


def _date_str(value):
    """Coerce a date filter (str or date) into 'YYYY-MM-DD', or None."""
    if not value:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()[:10]
    return str(value)[:10]


def _get(path, params=None):
    base = _base_url()
    if not base:
        raise SalaryApiError('SALARY_API_BASE_URL is not set')
    if not _api_key():
        raise SalaryApiError('SALARY_API_KEY is not set')
    resp = _session.get(
        f"{base}{path}",
        params=params,
        headers={'X-API-Key': _api_key()},
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        try:
            msg = resp.json().get('error')
        except Exception:
            msg = (resp.text or '')[:200]
        raise SalaryApiError(f"HTTP {resp.status_code}: {msg}")
    return resp.json()


# ── Raw endpoint wrappers ───────────────────────────────────────────────

def list_project_values():
    """Distinct attendance project values that actually have data.

    GET /api/projects -> ["123 - GANTRY CRANE", ...]
    """
    data = _get('/api/projects')
    if isinstance(data, list):
        return [str(p) for p in data if str(p).strip()]
    if isinstance(data, dict):  # tolerate {"projects": [...]} shape
        return [str(p) for p in data.get('projects', []) if str(p).strip()]
    return []


def get_project_salary(project=None, project_id=None, start_date=None,
                       end_date=None, year=None, month=None, include_workers=True):
    """GET /api/salary/project for one project. Returns the raw JSON object.

    Provide exactly one of ``project`` (exact value) or ``project_id``.
    Time scoping precedence (server-side): year(+month) > start/end > all months.
    """
    params = {}
    if project_id is not None:
        params['project_id'] = project_id
    elif project is not None:
        params['project'] = project
    else:
        raise SalaryApiError('project or project_id is required')

    if year is not None:
        params['year'] = year
        if month is not None:
            params['month'] = month
    else:
        sd, ed = _date_str(start_date), _date_str(end_date)
        if sd:
            params['start_date'] = sd
        if ed:
            params['end_date'] = ed

    params['include_workers'] = 'true' if include_workers else 'false'
    return _get('/api/salary/project', params)


# ── Drop-in replacements for the old DatabaseManager.get_labour_* methods ──

def get_labour_summary_for_project(project_id, project_display=None,
                                   start_date=None, end_date=None):
    """Monthly labour for ONE canonical project, shaped for the registry modal.

    Mirrors the old DatabaseManager.get_labour_summary_for_project contract:
        {available, monthly:[{year, month, label, days, workers, ot_hours, cost}],
         total_cost, total_days, total_ot_hours, project_names}
    ``available`` is False (with an ``error``) when the API can't be reached so
    the UI can show its "couldn't reach the attendance app" message. When
    ``start_date``/``end_date`` are given, only months in that window are returned.
    """
    empty = {'available': False, 'monthly': [], 'total_cost': 0.0,
             'total_days': 0, 'total_ot_hours': 0.0, 'project_names': []}
    if not is_configured():
        return {**empty, 'error': 'Salary API not configured'}

    try:
        data = get_project_salary(project_id=project_id, include_workers=False,
                                  start_date=start_date, end_date=end_date)
    except Exception as e:
        print(f"[!] Salary API error (project {project_id}): {e}")
        return {**empty, 'error': str(e)}

    monthly = []
    for m in data.get('months', []):
        yr = int(m.get('year') or 0)
        mn = int(m.get('month') or 0)
        label = m.get('month_name') or (f"{calendar.month_abbr[mn]} {yr}" if mn else '')
        monthly.append({
            'year': yr,
            'month': mn,
            'label': label,
            'days': int(m.get('total_present_days') or 0),
            'workers': int(m.get('headcount') or 0),
            'ot_hours': round(float(m.get('total_ot_hours') or 0), 1),
            'cost': round(float(m.get('total_salary') or 0), 2),
        })

    if project_display:
        names = [project_display]
    elif data.get('project'):
        names = [str(data['project'])]
    else:
        names = []

    return {
        'available': True,
        'monthly': monthly,
        'total_cost': round(float(data.get('total_salary') or 0), 2),
        'total_days': int(data.get('total_present_days') or 0),
        'total_ot_hours': round(float(data.get('total_ot_hours') or 0), 1),
        'project_names': names,
    }


# Short-lived cache for the all-projects sweep: a single project-summary page
# render (page API + export) hits this repeatedly with the same date window.
_costs_cache = {}                 # (start, end) -> (timestamp, {value: cost})
_costs_lock = threading.Lock()
_COSTS_TTL = 120                  # seconds


def get_labour_costs_by_project(start_date=None, end_date=None):
    """Labour cost per project across ALL projects: {project_value: total_salary}.

    Drop-in for the old DatabaseManager.get_labour_costs_by_project. Enumerates
    projects via /api/projects then sums each project's API total_salary for the
    window. Returns {} when the API is not configured/unreachable.
    """
    if not is_configured():
        return {}

    key = (_date_str(start_date) or '', _date_str(end_date) or '')
    now = time.time()
    with _costs_lock:
        hit = _costs_cache.get(key)
        if hit and now - hit[0] < _COSTS_TTL:
            return dict(hit[1])

    try:
        values = list_project_values()
    except Exception as e:
        print(f"[!] Salary API error listing projects: {e}")
        return {}

    result = {}
    for value in values:
        try:
            data = get_project_salary(project=value, start_date=start_date,
                                      end_date=end_date, include_workers=False)
        except Exception as e:
            print(f"[!] Salary API error for project '{value}': {e}")
            continue
        cost = round(float(data.get('total_salary') or 0), 2)
        if cost > 0:
            result[value] = cost

    with _costs_lock:
        _costs_cache[key] = (now, dict(result))
    return result


def get_monthly_labour_summary(start_date=None, end_date=None, project=None):
    """Per-worker MONTHLY labour summary for the Excel export's Labour tab.

    The salary API exposes per-worker monthly totals (present days, OT, base/OT
    pay) but not day-by-day attendance, so the export's old day-grid calendar is
    replaced by this monthly summary. Workers are aggregated across projects by
    (year, month, worker_id) so a worker who split a month across projects shows
    one combined row.

    When ``project`` is given, only the matching project value(s) are queried.

    Returns a list of month dicts, newest first:
        {year, month_num, month_name, sheet_name, days_in_month,
         workers:[{worker_id, name, designation, monthly_salaried,
                   base_salary_per_day, present_days, ot_hours,
                   base_pay, ot_pay, total_salary}],
         headcount, total_present_days, total_ot_hours,
         total_base_pay, total_ot_pay, total_salary}
    """
    if not is_configured():
        return []

    try:
        values = list_project_values()
    except Exception as e:
        print(f"[!] Salary API error listing projects: {e}")
        return []

    # Narrow to the selected project(s) when a filter is active.
    if project and project != 'All':
        from helpers.projects import (
            parse_project_selection, project_value_matches_selection,
        )
        sel = parse_project_selection(project)
        if sel[0] or sel[1]:
            values = [v for v in values if project_value_matches_selection(v, sel)]

    # months[(year, month)] -> {meta, workers:{worker_id: agg}}
    months = {}
    for value in values:
        try:
            data = get_project_salary(project=value, start_date=start_date,
                                      end_date=end_date, include_workers=True)
        except Exception as e:
            print(f"[!] Salary API error for project '{value}': {e}")
            continue

        for m in data.get('months', []):
            yr = int(m.get('year') or 0)
            mn = int(m.get('month') or 0)
            if not yr or not mn:
                continue
            bucket = months.setdefault((yr, mn), {'workers': {}})
            for w in m.get('workers', []):
                wid = w.get('worker_id')
                agg = bucket['workers'].get(wid)
                if agg is None:
                    agg = bucket['workers'][wid] = {
                        'worker_id': wid,
                        'name': w.get('name') or '',
                        'designation': w.get('designation') or '',
                        'monthly_salaried': bool(w.get('monthly_salaried')),
                        'base_salary_per_day': float(w.get('base_salary_per_day') or 0),
                        'present_days': 0,
                        'ot_hours': 0.0,
                        'base_pay': 0.0,
                        'ot_pay': 0.0,
                        'total_salary': 0.0,
                    }
                agg['present_days'] += int(w.get('present_days') or 0)
                agg['ot_hours'] += float(w.get('ot_hours') or 0)
                agg['base_pay'] += float(w.get('base_pay') or 0)
                agg['ot_pay'] += float(w.get('ot_pay') or 0)
                agg['total_salary'] += float(w.get('total_salary') or 0)

    result = []
    for (yr, mn) in sorted(months.keys(), reverse=True):
        workers = sorted(
            months[(yr, mn)]['workers'].values(),
            key=lambda x: (x['name'] or '').upper(),
        )
        for w in workers:
            w['ot_hours'] = round(w['ot_hours'], 2)
            w['base_pay'] = round(w['base_pay'], 2)
            w['ot_pay'] = round(w['ot_pay'], 2)
            w['total_salary'] = round(w['total_salary'], 2)
        if not workers:
            continue
        result.append({
            'year': yr,
            'month_num': mn,
            'month_name': f"{calendar.month_name[mn]} {yr}",
            'sheet_name': f"{calendar.month_abbr[mn].upper()}-{str(yr)[-2:]}",
            'days_in_month': calendar.monthrange(yr, mn)[1],
            'workers': workers,
            'headcount': len(workers),
            'total_present_days': sum(w['present_days'] for w in workers),
            'total_ot_hours': round(sum(w['ot_hours'] for w in workers), 2),
            'total_base_pay': round(sum(w['base_pay'] for w in workers), 2),
            'total_ot_pay': round(sum(w['ot_pay'] for w in workers), 2),
            'total_salary': round(sum(w['total_salary'] for w in workers), 2),
        })
    return result
