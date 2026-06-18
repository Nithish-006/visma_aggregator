# Project Salary API — Integration Guide

Feed for an external finance app to build a per-project master report / dashboard.
Returns salary, headcount and OT for one project, broken down by month.

---

## Endpoint

```
GET /api/salary/project
```

- **Base URL (prod):** your deployed host, e.g. `https://<your-app>.up.railway.app`
- **Base URL (local):** `http://localhost:5000`
- **Auth:** required — a shared API key. See [Authentication](#authentication).
- **CORS:** enabled app-wide, so browser/cross-origin calls work as-is.
- **Content-Type of response:** `application/json`

---

## Authentication

Every request must carry the shared API key. Pass it in the **`X-API-Key`
header** (preferred):

```
X-API-Key: <your-key>
```

Or, as a fallback, an `api_key` query parameter (avoid this where possible — it
can end up in server/proxy logs):

```
GET /api/salary/project?project_id=123&api_key=<your-key>
```

The key is set server-side via the `FINANCE_API_KEY` environment variable. Ask
the maintainer for the value; it is the same secret for all callers. Comparison
is constant-time.

| HTTP | When |
|------|------|
| `401 {"error": "Invalid or missing API key"}` | Key missing or wrong. |
| `503 {"error": "API access is not configured on the server"}` | `FINANCE_API_KEY` not set on the server — auth can't be performed. |

---

## How the numbers are produced (read this once)

The `salary` table is **one row per worker per month and has no project column** —
each row covers everything that worker did that month, across all projects. The
project is only recorded on `attendance`. So salaries cannot be filtered by
project from the salary table alone.

This endpoint therefore:

1. Scopes **attendance** to the requested project (and optional time window).
2. Prices each *present* day using **that month's stored base pay/day** from the
   `salary` table (falling back to the worker-master rate when a month has none,
   `0` if the worker never had a rate set).
3. Adds **overtime** at the hourly rate (`day rate ÷ 8`) **only for daily-rate
   workers**. Monthly-salaried workers have OT recorded for tracking but it is
   **never** added to their pay.

This is the exact same pricing used by the salary dashboard and the Excel export,
so the figures returned here line up with both.

---

## Request parameters

All are query-string parameters.

| Param             | Required | Example            | Description |
|-------------------|----------|--------------------|-------------|
| `project`         | yes\*    | `123 - GANTRY CRANE` | Exact canonical project value as stored on attendance (`"{id} - {name}"`). |
| `project_id`      | yes\*    | `123`              | Alternative to `project`. Matches every project value starting with `"{id} - "`. |
| `year`            | no       | `2026`             | Restrict to one year. |
| `month`           | no       | `6`                | Restrict to one month (`1`–`12`). Only applied together with `year`. |
| `start_date`      | no       | `2026-01-01`       | Range start, `YYYY-MM-DD`. **Ignored if `year` is given.** |
| `end_date`        | no       | `2026-06-30`       | Range end, `YYYY-MM-DD`. **Ignored if `year` is given.** |
| `include_workers` | no       | `false`            | `false` drops the per-worker rows for a lighter summary. Defaults to `true`. |

\* Provide **one** of `project` or `project_id`.

**Time scoping precedence:** `year`(+`month`) wins → else `start_date`/`end_date`
→ else **all months** are returned (newest first).

> Tip: `project` values can contain spaces and must be URL-encoded
> (`123%20-%20GANTRY%20CRANE`). Using `project_id=123` avoids that entirely.

---

## Response

A single JSON object: project info, period-wide totals, and a `months` array
(newest month first). Each month repeats the same totals and, by default,
carries a `workers` array.

### Top level

| Field                 | Type    | Description |
|-----------------------|---------|-------------|
| `project`             | string  | The project label queried (or `"{id} - *"` when `project_id` was used). |
| `project_id`          | string\|null | The leading id segment. |
| `headcount`           | int     | Distinct workers with any attendance in the period. |
| `total_present_days`  | int     | Sum of present worker-days. |
| `total_ot_hours`      | number  | Total OT hours logged. |
| `total_base_pay`      | number  | Sum of base pay (present days × rate). |
| `total_ot_pay`        | number  | Sum of OT pay (daily-rate workers only). |
| `total_salary`        | number  | `total_base_pay + total_ot_pay`. |
| `month_count`         | int     | Number of months returned. |
| `months`              | array   | Per-month breakdown, newest first. |

### Each `months[]` entry

| Field                | Type   | Description |
|----------------------|--------|-------------|
| `year`               | int    | e.g. `2026`. |
| `month`              | int    | `1`–`12`. |
| `month_key`          | string | `"2026-06"`. |
| `month_name`         | string | `"June 2026"`. |
| `headcount`          | int    | Distinct workers active this month on this project. |
| `working_days`       | int    | Distinct calendar dates with ≥1 present worker. |
| `total_present_days` | int    | Present worker-days this month. |
| `total_ot_hours`     | number | OT hours this month. |
| `total_base_pay`     | number | Base pay this month. |
| `total_ot_pay`       | number | OT pay this month. |
| `total_salary`       | number | Month total. |
| `workers`            | array  | Per-worker rows (omitted when `include_workers=false`). |

### Each `workers[]` entry

| Field                 | Type    | Description |
|-----------------------|---------|-------------|
| `worker_id`           | int     | Worker id. |
| `name`                | string  | Upper-cased worker name. |
| `designation`         | string  | Role/designation (may be empty). |
| `monthly_salaried`    | bool    | `true` = monthly-salaried (no OT pay); `false` = daily-rate. |
| `base_salary_per_day` | number  | Rate applied for this month (`0` if never set). |
| `present_days`        | int     | Present days this month on this project. |
| `absent_days`         | int     | Absent days. |
| `holiday_days`        | int     | Legacy `H` status days. |
| `ot_hours`            | number  | OT hours. |
| `base_pay`            | number  | `present_days × base_salary_per_day`. |
| `ot_pay`              | number  | OT pay (daily-rate only, else `0`). |
| `total_salary`        | number  | `base_pay + ot_pay`. |

> A worker with `base_salary_per_day = 0` means their rate was never entered, so
> their pay shows as `0`. Treat that as "rate not set", not "earned nothing".

---

## Examples

### 1. All months for a project (full detail)
```bash
curl -H "X-API-Key: $FINANCE_API_KEY" \
  "http://localhost:5000/api/salary/project?project_id=123"
```

### 2. A single month, summary only (no worker rows)
```bash
curl -H "X-API-Key: $FINANCE_API_KEY" \
  "http://localhost:5000/api/salary/project?project_id=123&year=2026&month=6&include_workers=false"
```

### 3. A date range, using the exact project value
```bash
curl -H "X-API-Key: $FINANCE_API_KEY" \
  "http://localhost:5000/api/salary/project?project=123%20-%20GANTRY%20CRANE&start_date=2026-01-01&end_date=2026-06-30"
```

### 4. JavaScript (fetch)
```js
const res = await fetch(
  `${BASE_URL}/api/salary/project?project_id=123&year=2026&month=6`,
  { headers: { "X-API-Key": FINANCE_API_KEY } }
);
if (!res.ok) throw new Error(`API ${res.status}`);
const data = await res.json();
```

### Sample response (trimmed)
```json
{
  "project": "123 - GANTRY CRANE",
  "project_id": "123",
  "headcount": 14,
  "total_present_days": 280,
  "total_ot_hours": 96.0,
  "total_base_pay": 420000,
  "total_ot_pay": 18000,
  "total_salary": 438000,
  "month_count": 1,
  "months": [
    {
      "year": 2026,
      "month": 6,
      "month_key": "2026-06",
      "month_name": "June 2026",
      "headcount": 8,
      "working_days": 22,
      "total_present_days": 140,
      "total_ot_hours": 40.0,
      "total_base_pay": 210000,
      "total_ot_pay": 9000,
      "total_salary": 219000,
      "workers": [
        {
          "worker_id": 42,
          "name": "RAMESH KUMAR",
          "designation": "WELDER",
          "monthly_salaried": false,
          "base_salary_per_day": 750,
          "present_days": 22,
          "absent_days": 3,
          "holiday_days": 0,
          "ot_hours": 12.0,
          "base_pay": 16500,
          "ot_pay": 1125,
          "total_salary": 17625
        }
      ]
    }
  ]
}
```

---

## Errors

| HTTP | Body                                            | Cause |
|------|-------------------------------------------------|-------|
| 400  | `{"error": "project (or project_id) is required"}` | Neither `project` nor `project_id` supplied. |
| 400  | `{"error": "year must be a number"}`            | `year` not numeric. |
| 400  | `{"error": "month must be 1-12"}`               | `month` out of range / not numeric. |
| 400  | `{"error": "Invalid date format. Use YYYY-MM-DD"}` | Bad `start_date`/`end_date`. |

An **unknown project** is not an error — you get a normal `200` with
`headcount: 0`, `total_salary: 0`, and an empty `months` array.

---

## Verifying auth (smoke test)

After setting `FINANCE_API_KEY` on the server, confirm the key check works.
Replace `$KEY` with the configured value.

```bash
# 1. No key -> 401
curl -i "http://localhost:5000/api/salary/project?project_id=123"
# HTTP/1.1 401 Unauthorized
# {"error": "Invalid or missing API key"}

# 2. Wrong key -> 401
curl -i -H "X-API-Key: nope" "http://localhost:5000/api/salary/project?project_id=123"
# HTTP/1.1 401 Unauthorized
# {"error": "Invalid or missing API key"}

# 3. Correct key -> 200 + JSON payload
curl -i -H "X-API-Key: $KEY" "http://localhost:5000/api/salary/project?project_id=123"
# HTTP/1.1 200 OK
# { "project": "...", "months": [ ... ] }
```

If you instead get `503 {"error": "API access is not configured on the server"}`,
the server has no `FINANCE_API_KEY` set — set it and restart the app.

---

## Finding valid project values

To populate a dropdown of selectable projects in the finance app:

- `GET /api/projects` → array of distinct project values already in attendance
  (only projects that actually have data), e.g. `["123 - GANTRY CRANE", ...]`.
- `GET /api/projects/registry` → live list from the shared VISMA registry as
  `{"projects": [{"id", "value"}, ...], "stale": bool}`.

Pass either the full `value` as `project`, or just its `id` as `project_id`.

---

## Security

- The endpoint is protected by the `FINANCE_API_KEY` shared secret (see
  [Authentication](#authentication)). It refuses all calls (`503`) until the key
  is configured server-side, so it can never accidentally run open.
- Prefer the `X-API-Key` header over the `api_key` query param — query strings
  are often captured in access logs and browser history.
- Always call over **HTTPS** in production so the key isn't sent in clear text.
- Treat the key as a credential: store it in the finance app's own secret store
  / env, never commit it. Rotate it by updating `FINANCE_API_KEY` on the server
  and the caller together.
