# ERP Integration Guide: Labour Attendance & Salary Monthly Summary

Complete self-contained reference for replicating the monthly attendance summary
and Excel export in your ERP application. Uses the **same MySQL database**.

---

## 1. DATABASE CONNECTION

**Driver:** `mysql+pymysql` (Python) or any MySQL connector
**Database name:** `visma_attendance`

```
mysql+pymysql://<user>:<password>@<host>:<port>/visma_attendance
```

Environment variables (in priority order):
| Variable | Description |
|---|---|
| `DATABASE_URL` | Full connection string |
| `MYSQL_URL` | Full connection string (Railway format) |
| `MYSQLHOST`, `MYSQLUSER`, `MYSQLDATABASE`, `MYSQLPORT`, `MYSQLPASSWORD` | Individual vars |

> If the URL starts with `mysql://`, replace with `mysql+pymysql://` for SQLAlchemy.

---

## 2. DATABASE SCHEMA

Two tables. Your ERP connects to the **same database** — these tables already exist.

```sql
CREATE TABLE salary (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    worker_id       INT NOT NULL,
    name            VARCHAR(100) NOT NULL,
    designation     VARCHAR(50),
    team            VARCHAR(50),
    base_salary_per_day DECIMAL(10,2) DEFAULT 0,
    year            INT NOT NULL,
    month           INT NOT NULL,           -- 1 to 12
    total_working_days INT DEFAULT 0,
    ot_hours        DECIMAL(6,2) DEFAULT 0,
    total_salary    DECIMAL(12,2) DEFAULT 0,
    UNIQUE KEY unique_worker_month (worker_id, year, month)
);

CREATE TABLE attendance (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    worker_id       INT NOT NULL,
    date            DATE NOT NULL,
    status          ENUM('P','A','H') DEFAULT 'A',   -- Present / Absent / Holiday
    ot_hours        DECIMAL(4,2) DEFAULT 0,
    project         VARCHAR(100),
    UNIQUE KEY unique_daily_attendance (worker_id, date)
);
```

**Relationships:**
- `attendance.worker_id` references `salary.worker_id`
- `salary` has ONE row per worker per month
- `attendance` has ONE row per worker per day

---

## 3. SALARY CALCULATION FORMULA

This is the core formula used everywhere:

```
base_pay   = total_working_days * base_salary_per_day
ot_pay     = (base_salary_per_day / 8) * ot_hours
total_salary = base_pay + ot_pay
```

- `total_working_days` = count of attendance records with `status = 'P'` for that worker in that month
- `ot_hours` = sum of `attendance.ot_hours` for that worker in that month
- OT rate = `base_salary_per_day / 8` (i.e., hourly rate derived from 8-hour workday)

---

## 4. PYTHON CODE — DATA PREPARATION

### 4a. SQLAlchemy Models

```python
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Salary(db.Model):
    """One row per worker per month."""
    __tablename__ = 'salary'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    worker_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    designation = db.Column(db.String(50))
    team = db.Column(db.String(50))
    base_salary_per_day = db.Column(db.Numeric(10, 2), default=0)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    total_working_days = db.Column(db.Integer, default=0)
    ot_hours = db.Column(db.Numeric(6, 2), default=0)
    total_salary = db.Column(db.Numeric(12, 2), default=0)

    __table_args__ = (
        db.UniqueConstraint('worker_id', 'year', 'month', name='unique_worker_month'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'worker_id': self.worker_id,
            'name': self.name,
            'designation': self.designation,
            'team': self.team,
            'base_salary_per_day': float(self.base_salary_per_day) if self.base_salary_per_day else 0,
            'year': self.year,
            'month': self.month,
            'total_working_days': self.total_working_days,
            'ot_hours': float(self.ot_hours) if self.ot_hours else 0,
            'total_salary': float(self.total_salary) if self.total_salary else 0
        }


class Attendance(db.Model):
    """Daily attendance record per worker."""
    __tablename__ = 'attendance'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    worker_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.Enum('P', 'A', 'H', name='attendance_status'), default='A')
    ot_hours = db.Column(db.Numeric(4, 2), default=0)
    project = db.Column(db.String(100))

    __table_args__ = (
        db.UniqueConstraint('worker_id', 'date', name='unique_daily_attendance'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'worker_id': self.worker_id,
            'date': self.date.isoformat() if self.date else None,
            'status': self.status,
            'ot_hours': float(self.ot_hours) if self.ot_hours else 0,
            'project': self.project
        }
```

### 4b. Get Monthly Salary Data (grouped by month)

This is the primary data source. Returns all workers grouped by year-month.

```python
import calendar
from decimal import Decimal

def get_monthly_salaries():
    """
    Returns a list of months, each containing worker salary records.
    Sorted newest-first.

    Output structure:
    [
        {
            "month": "2026-01",
            "year": 2026,
            "month_num": 1,
            "month_name": "January 2026",
            "workers": [
                {
                    "id": 1,
                    "worker_id": 101,
                    "name": "John",
                    "designation": "FITTER",
                    "team": "Team A",
                    "base_salary_per_day": 500.0,
                    "working_days": 22,
                    "ot_hours": 12.5,
                    "base_pay": 11000.0,
                    "ot_pay": 781.25,
                    "total_salary": 11781.25
                },
                ...
            ],
            "total_salary": 350000.0
        },
        ...
    ]
    """
    records = Salary.query.order_by(
        Salary.year.desc(),
        Salary.month.desc(),
        Salary.team,
        Salary.name
    ).all()

    months_data = {}
    for record in records:
        month_key = f"{record.year}-{record.month:02d}"
        if month_key not in months_data:
            months_data[month_key] = {
                'workers': [],
                'total_salary': Decimal('0')
            }

        base_salary = float(record.base_salary_per_day) if record.base_salary_per_day else 0
        working_days = record.total_working_days or 0
        ot_hours = float(record.ot_hours) if record.ot_hours else 0
        base_pay = working_days * base_salary
        ot_pay = (base_salary / 8) * ot_hours if base_salary > 0 else 0

        months_data[month_key]['workers'].append({
            'id': record.id,
            'worker_id': record.worker_id,
            'name': record.name,
            'designation': record.designation,
            'team': record.team,
            'base_salary_per_day': base_salary,
            'working_days': working_days,
            'ot_hours': ot_hours,
            'base_pay': base_pay,
            'ot_pay': ot_pay,
            'total_salary': float(record.total_salary) if record.total_salary else 0
        })
        months_data[month_key]['total_salary'] += Decimal(str(record.total_salary or 0))

    result = []
    for month_key in sorted(months_data.keys(), reverse=True):
        year, month = month_key.split('-')
        result.append({
            'month': month_key,
            'year': int(year),
            'month_num': int(month),
            'month_name': f"{calendar.month_name[int(month)]} {year}",
            'workers': months_data[month_key]['workers'],
            'total_salary': float(months_data[month_key]['total_salary'])
        })

    return result
```

### 4c. Get All Attendance Records (flat list for export)

This returns every attendance record joined with worker metadata. Used to build
the day-by-day grid in Excel.

```python
def get_attendance_export():
    """
    Returns flat list of all attendance records with worker info.

    Output structure:
    [
        {
            "date": "2026-01-15",
            "worker_id": 101,
            "name": "John",
            "designation": "FITTER",
            "team": "Team A",
            "status": "P",
            "ot_hours": 2.5,
            "project": "Project Alpha"
        },
        ...
    ]
    """
    records = db.session.query(
        Attendance,
        Salary.name,
        Salary.designation,
        Salary.team
    ).join(
        Salary,
        (Attendance.worker_id == Salary.worker_id)
    ).distinct(
        Attendance.id
    ).order_by(
        Attendance.date.desc(),
        Salary.team,
        Salary.name
    ).all()

    # Deduplicate (a worker may have multiple salary rows across months)
    seen = set()
    result = []
    for att, name, designation, team in records:
        if att.id not in seen:
            seen.add(att.id)
            result.append({
                'date': att.date.isoformat(),
                'worker_id': att.worker_id,
                'name': name,
                'designation': designation,
                'team': team,
                'status': att.status,
                'ot_hours': float(att.ot_hours) if att.ot_hours else 0,
                'project': att.project or ''
            })

    return result
```

### 4d. Get Attendance Summary (aggregated KPIs, project breakdown, daily headcount, worker totals)

This powers the summary dashboard. Give it a date range and optional filters.

```python
from sqlalchemy import func

def get_attendance_summary(start_date, end_date, project_filter=None, worker_id_filter=None):
    """
    Aggregated attendance summary for a date range.

    Parameters:
        start_date: date object (e.g., date(2026, 1, 1))
        end_date:   date object (e.g., date(2026, 1, 31))
        project_filter: optional string, filter by project name
        worker_id_filter: optional int, filter by single worker

    Output structure:
    {
        "total_workers": 45,        # distinct workers with at least one 'P' day
        "working_days": 22,         # distinct dates with at least one 'P'
        "total_present_days": 990,  # sum of all P records
        "total_ot_hours": 156.5,
        "total_salary": 450000.0,
        "projects": [
            {"name": "Project A", "worker_count": 15, "working_days": 20, "ot_hours": 45.5}
        ],
        "daily_breakdown": [
            {"date": "2026-01-01", "present": 40, "absent": 3, "holiday": 2, "ot_hours": 7.5}
        ],
        "workers": [
            {
                "worker_id": 101, "name": "John", "team": "Team A",
                "present_days": 22, "absent_days": 0, "ot_hours": 8.5,
                "salary": 11425.0, "projects": ["Project A", "Project B"]
            }
        ]
    }
    """
    # Base query
    base_query = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date
    )
    if project_filter:
        base_query = base_query.filter(Attendance.project == project_filter)
    if worker_id_filter:
        base_query = base_query.filter(Attendance.worker_id == int(worker_id_filter))

    records = base_query.all()

    # Get worker info (latest salary record per worker)
    worker_ids = list(set(r.worker_id for r in records))
    worker_info_map = {}
    if worker_ids:
        subquery = db.session.query(
            Salary.worker_id,
            func.max(Salary.year * 100 + Salary.month).label('max_period')
        ).filter(Salary.worker_id.in_(worker_ids)).group_by(Salary.worker_id).subquery()

        workers = db.session.query(Salary).join(
            subquery,
            (Salary.worker_id == subquery.c.worker_id) &
            (Salary.year * 100 + Salary.month == subquery.c.max_period)
        ).all()

        for w in workers:
            worker_info_map[w.worker_id] = {
                'name': w.name,
                'team': w.team,
                'designation': w.designation,
                'base_salary_per_day': float(w.base_salary_per_day) if w.base_salary_per_day else 0
            }

    # Aggregation buckets
    project_data = {}
    daily_data = {}
    worker_data = {}
    present_workers = set()
    total_present_days = 0
    total_ot_hours = 0.0

    for r in records:
        ot = float(r.ot_hours) if r.ot_hours else 0
        proj = r.project or 'Unassigned'
        date_str = r.date.isoformat()

        # --- Project aggregation (only Present workers) ---
        if r.status == 'P':
            if proj not in project_data:
                project_data[proj] = {'worker_ids': set(), 'present_dates': set(), 'ot_hours': 0}
            project_data[proj]['worker_ids'].add(r.worker_id)
            project_data[proj]['present_dates'].add(r.date)
            project_data[proj]['ot_hours'] += ot
            present_workers.add(r.worker_id)

        # --- Daily aggregation ---
        if date_str not in daily_data:
            daily_data[date_str] = {'present': 0, 'absent': 0, 'holiday': 0, 'ot_hours': 0}
        if r.status == 'P':
            daily_data[date_str]['present'] += 1
            total_present_days += 1
        elif r.status == 'A':
            daily_data[date_str]['absent'] += 1
        elif r.status == 'H':
            daily_data[date_str]['holiday'] += 1
        daily_data[date_str]['ot_hours'] += ot
        total_ot_hours += ot

        # --- Worker aggregation ---
        if r.worker_id not in worker_data:
            info = worker_info_map.get(r.worker_id, {})
            worker_data[r.worker_id] = {
                'worker_id': r.worker_id,
                'name': info.get('name', f'Worker {r.worker_id}'),
                'team': info.get('team', ''),
                'base_salary_per_day': info.get('base_salary_per_day', 0),
                'present_days': 0,
                'absent_days': 0,
                'ot_hours': 0,
                'projects': set()
            }
        if r.status == 'P':
            worker_data[r.worker_id]['present_days'] += 1
        elif r.status == 'A':
            worker_data[r.worker_id]['absent_days'] += 1
        worker_data[r.worker_id]['ot_hours'] += ot
        if r.project:
            worker_data[r.worker_id]['projects'].add(r.project)

    # --- Build response ---
    projects_list = []
    for name, data in sorted(project_data.items()):
        projects_list.append({
            'name': name,
            'worker_count': len(data['worker_ids']),
            'working_days': len(data['present_dates']),
            'ot_hours': round(data['ot_hours'], 2)
        })

    daily_list = []
    for date_str in sorted(daily_data.keys()):
        d = daily_data[date_str]
        daily_list.append({
            'date': date_str,
            'present': d['present'],
            'absent': d['absent'],
            'holiday': d['holiday'],
            'ot_hours': round(d['ot_hours'], 2)
        })

    workers_list = []
    total_salary = 0.0
    for wid, data in sorted(worker_data.items(), key=lambda x: x[1]['name']):
        base = data['base_salary_per_day']
        base_pay = data['present_days'] * base
        ot_pay = (base / 8) * data['ot_hours'] if base > 0 else 0
        salary = round(base_pay + ot_pay, 2)
        total_salary += salary
        workers_list.append({
            'worker_id': data['worker_id'],
            'name': data['name'],
            'team': data['team'],
            'present_days': data['present_days'],
            'absent_days': data['absent_days'],
            'ot_hours': round(data['ot_hours'], 2),
            'salary': salary,
            'projects': sorted(list(data['projects']))
        })

    working_days = sum(1 for d in daily_data.values() if d['present'] > 0)

    return {
        'total_workers': len(present_workers),
        'working_days': working_days,
        'total_present_days': total_present_days,
        'total_ot_hours': round(total_ot_hours, 2),
        'total_salary': round(total_salary, 2),
        'projects': projects_list,
        'daily_breakdown': daily_list,
        'workers': workers_list
    }
```

### 4e. Salary Recalculation (triggered when attendance changes)

When your ERP marks/updates attendance, call this to keep salary in sync.

```python
from sqlalchemy import func, case

def recalculate_monthly_salaries(affected_periods):
    """
    Recalculate salary for affected (worker_id, year, month) tuples.

    Call this after any attendance insert/update.

    Parameters:
        affected_periods: set of (worker_id, year, month) tuples
            e.g., {(101, 2026, 1), (102, 2026, 1)}
    """
    for worker_id, year, month in affected_periods:
        # Get worker's base info from most recent salary record
        worker_info = Salary.query.filter_by(worker_id=worker_id).order_by(
            Salary.year.desc(), Salary.month.desc()
        ).first()

        if not worker_info:
            continue

        # Aggregate attendance for this worker+month
        stats = db.session.query(
            func.sum(case((Attendance.status == 'P', 1), else_=0)).label('working_days'),
            func.coalesce(func.sum(Attendance.ot_hours), 0).label('total_ot')
        ).filter(
            Attendance.worker_id == worker_id,
            func.extract('year', Attendance.date) == year,
            func.extract('month', Attendance.date) == month
        ).first()

        working_days = int(stats.working_days or 0)
        ot_hours = float(stats.total_ot or 0)
        base_salary = float(worker_info.base_salary_per_day) if worker_info.base_salary_per_day else 0

        # Apply formula
        base_pay = working_days * base_salary
        ot_pay = (base_salary / 8) * ot_hours if base_salary > 0 else 0
        total = base_pay + ot_pay

        # Upsert salary record
        salary = Salary.query.filter_by(worker_id=worker_id, year=year, month=month).first()

        if salary:
            salary.total_working_days = working_days
            salary.ot_hours = ot_hours
            salary.total_salary = total
        else:
            salary = Salary(
                worker_id=worker_id,
                name=worker_info.name,
                designation=worker_info.designation,
                team=worker_info.team,
                base_salary_per_day=worker_info.base_salary_per_day,
                year=year,
                month=month,
                total_working_days=working_days,
                ot_hours=ot_hours,
                total_salary=total
            )
            db.session.add(salary)

    db.session.commit()
```

---

## 5. RAW SQL EQUIVALENTS

If your ERP doesn't use SQLAlchemy, here are the raw SQL queries.

### 5a. Monthly salary data (grouped by month)

```sql
SELECT
    id, worker_id, name, designation, team,
    base_salary_per_day, year, month,
    total_working_days, ot_hours, total_salary,
    -- computed columns:
    (total_working_days * base_salary_per_day)                    AS base_pay,
    ((base_salary_per_day / 8) * ot_hours)                       AS ot_pay
FROM salary
ORDER BY year DESC, month DESC, team, name;
```

Group results by `CONCAT(year, '-', LPAD(month, 2, '0'))` in your app code.

### 5b. All attendance records with worker info (for export)

```sql
SELECT DISTINCT
    a.id, a.date, a.worker_id, a.status, a.ot_hours, a.project,
    s.name, s.designation, s.team
FROM attendance a
JOIN salary s ON a.worker_id = s.worker_id
ORDER BY a.date DESC, s.team, s.name;
```

> Deduplicate by `a.id` in your app (the JOIN may produce multiple rows
> per attendance record since a worker has one salary row per month).

### 5c. Attendance summary for a date range

```sql
-- Per-worker summary
SELECT
    a.worker_id,
    s.name,
    s.team,
    s.base_salary_per_day,
    SUM(CASE WHEN a.status = 'P' THEN 1 ELSE 0 END) AS present_days,
    SUM(CASE WHEN a.status = 'A' THEN 1 ELSE 0 END) AS absent_days,
    SUM(a.ot_hours) AS total_ot_hours,
    (SUM(CASE WHEN a.status = 'P' THEN 1 ELSE 0 END) * s.base_salary_per_day)
        + ((s.base_salary_per_day / 8) * SUM(a.ot_hours)) AS salary
FROM attendance a
JOIN (
    -- Latest salary record per worker
    SELECT s1.* FROM salary s1
    INNER JOIN (
        SELECT worker_id, MAX(year * 100 + month) AS max_period
        FROM salary GROUP BY worker_id
    ) s2 ON s1.worker_id = s2.worker_id
        AND (s1.year * 100 + s1.month) = s2.max_period
) s ON a.worker_id = s.worker_id
WHERE a.date BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY a.worker_id, s.name, s.team, s.base_salary_per_day;

-- Daily headcount
SELECT
    a.date,
    SUM(CASE WHEN a.status = 'P' THEN 1 ELSE 0 END) AS present,
    SUM(CASE WHEN a.status = 'A' THEN 1 ELSE 0 END) AS absent,
    SUM(CASE WHEN a.status = 'H' THEN 1 ELSE 0 END) AS holiday,
    SUM(a.ot_hours) AS ot_hours
FROM attendance a
WHERE a.date BETWEEN '2026-01-01' AND '2026-01-31'
GROUP BY a.date
ORDER BY a.date;

-- Project breakdown
SELECT
    COALESCE(a.project, 'Unassigned') AS project,
    COUNT(DISTINCT a.worker_id) AS worker_count,
    COUNT(DISTINCT CASE WHEN a.status = 'P' THEN a.date END) AS working_days,
    SUM(a.ot_hours) AS ot_hours
FROM attendance a
WHERE a.date BETWEEN '2026-01-01' AND '2026-01-31'
  AND a.status = 'P'
GROUP BY COALESCE(a.project, 'Unassigned');
```

### 5d. Recalculate salary for a worker+month

```sql
-- Step 1: Get stats from attendance
SELECT
    SUM(CASE WHEN status = 'P' THEN 1 ELSE 0 END) AS working_days,
    COALESCE(SUM(ot_hours), 0) AS total_ot
FROM attendance
WHERE worker_id = 101
  AND YEAR(date) = 2026
  AND MONTH(date) = 1;

-- Step 2: Update salary (assuming base_salary_per_day = 500)
-- base_pay = working_days * 500
-- ot_pay   = (500 / 8) * total_ot
-- total    = base_pay + ot_pay

UPDATE salary
SET total_working_days = <working_days>,
    ot_hours = <total_ot>,
    total_salary = (<working_days> * base_salary_per_day)
                 + ((base_salary_per_day / 8) * <total_ot>)
WHERE worker_id = 101 AND year = 2026 AND month = 1;
```

---

## 6. EXCEL EXPORT LOGIC (JavaScript — SheetJS)

The Excel export runs **client-side** using [SheetJS (xlsx)](https://cdn.sheetjs.com/xlsx-0.20.1/package/dist/xlsx.full.min.js).

It needs two data sources:
1. **salaryData** — from `get_monthly_salaries()` (Section 4b)
2. **attendanceData** — from `get_attendance_export()` (Section 4c)

### Complete Export Function

```javascript
/**
 * CDN: https://cdn.sheetjs.com/xlsx-0.20.1/package/dist/xlsx.full.min.js
 *
 * salaryData:     array from get_monthly_salaries()   — one entry per month
 * attendanceData: array from get_attendance_export()   — flat list of all records
 */
function exportExcel(salaryData, attendanceData) {
    const wb = XLSX.utils.book_new();

    for (const month of salaryData) {
        const monthAbbr = month.month_name.split(' ')[0].toUpperCase().substring(0, 3);
        const year = month.year;
        const yearShort = String(year).slice(-2);
        const monthNum = month.month_num;
        const sheetName = `${monthAbbr}-${yearShort}`;   // e.g. "JAN-26"

        const daysInMonth = new Date(year, monthNum, 0).getDate();

        // ----- Filter attendance for this month -----
        const monthAttendance = attendanceData.filter(a => {
            const d = new Date(a.date);
            return d.getFullYear() === year && (d.getMonth() + 1) === monthNum;
        });

        // ----- Build attendance lookup: worker_id -> day -> {status, ot, project} -----
        const attendanceMap = {};
        monthAttendance.forEach(a => {
            const day = new Date(a.date).getDate();
            if (!attendanceMap[a.worker_id]) attendanceMap[a.worker_id] = {};
            attendanceMap[a.worker_id][day] = {
                status: a.status,
                ot: a.ot_hours || '',
                project: a.project || ''
            };
        });

        // ===== ROW 0: Title =====
        const titleRow = [`LABOUR ATTENDANCE FOR ${sheetName}`];

        // ===== ROW 1: Header row 1 (day numbers) =====
        const headerRow1 = ['S. No', 'Name', 'DESIGNATION', 'TEAM'];
        const headerRow2 = ['', '', '', ''];
        for (let day = 1; day <= daysInMonth; day++) {
            const date = new Date(year, monthNum - 1, day);
            const isSunday = date.getDay() === 0;
            headerRow1.push(isSunday ? `${day} SUNDAY` : day, '', '');
            headerRow2.push('', 'OT', 'Pr');   // sub-headers per day
        }
        // Summary column headers
        headerRow1.push(`${sheetName} MONTH LABOUR ATTENDANCE & PAYMENT`, '', '', '', '', '');
        headerRow2.push('TOTAL PRESENT', 'TOTAL OT', 'BASE SALARY', 'BASE PAY', 'OT PAY', 'TOTAL SALARY');

        // ===== DATA ROWS (one per worker, grouped by team) =====
        const dataRows = [];
        let sNo = 1;
        const teams = {};
        month.workers.forEach(w => {
            const team = w.team || 'Unassigned';
            if (!teams[team]) teams[team] = [];
            teams[team].push(w);
        });

        for (const [team, workers] of Object.entries(teams)) {
            workers.forEach(w => {
                const row = [sNo++, w.name, w.designation || '', w.team || ''];
                // Day-by-day: 3 columns per day (status, OT hours, project)
                for (let day = 1; day <= daysInMonth; day++) {
                    const att = attendanceMap[w.worker_id]?.[day];
                    if (att) {
                        row.push(att.status, att.ot || '', att.project || '');
                    } else {
                        row.push('', '', '');
                    }
                }
                // Summary columns
                row.push(
                    w.working_days,
                    w.ot_hours,
                    w.base_salary_per_day || 0,
                    w.base_pay || 0,
                    w.ot_pay || 0,
                    w.total_salary
                );
                dataRows.push(row);
            });
        }

        // ===== SUMMARY SECTIONS (below worker rows) =====
        const summaryRows = [];

        // KPI totals
        const totalWorkers = month.workers.length;
        const totalPresent = month.workers.reduce((s, w) => s + (w.working_days || 0), 0);
        const totalOT = month.workers.reduce((s, w) => s + (w.ot_hours || 0), 0);
        const totalSalaryAmt = month.workers.reduce((s, w) => s + (w.total_salary || 0), 0);

        summaryRows.push([]);
        summaryRows.push(['MONTHLY SUMMARY']);
        summaryRows.push([
            'Total Workers', totalWorkers, '',
            'Total Present Days', totalPresent, '',
            'Total OT Hours', totalOT, '',
            'Total Salary', totalSalaryAmt
        ]);

        // Project breakdown
        const projectStats = {};
        monthAttendance.forEach(a => {
            const proj = a.project || 'Unassigned';
            if (!projectStats[proj]) {
                projectStats[proj] = { workerIds: new Set(), presentDates: new Set(), otHours: 0 };
            }
            projectStats[proj].workerIds.add(a.worker_id);
            if (a.status === 'P') projectStats[proj].presentDates.add(a.date);
            projectStats[proj].otHours += (a.ot_hours || 0);
        });

        summaryRows.push([]);
        summaryRows.push(['PROJECT BREAKDOWN']);
        summaryRows.push(['Project', 'Workers', 'Working Days', 'OT Hours']);
        for (const [proj, stats] of Object.entries(projectStats).sort()) {
            summaryRows.push([
                proj, stats.workerIds.size, stats.presentDates.size,
                Math.round(stats.otHours * 100) / 100
            ]);
        }

        // Daily headcount
        const dailyStats = {};
        monthAttendance.forEach(a => {
            const day = new Date(a.date).getDate();
            if (!dailyStats[day]) dailyStats[day] = { present: 0, absent: 0, holiday: 0, otHours: 0 };
            if (a.status === 'P') dailyStats[day].present++;
            else if (a.status === 'A') dailyStats[day].absent++;
            else if (a.status === 'H') dailyStats[day].holiday++;
            dailyStats[day].otHours += (a.ot_hours || 0);
        });

        summaryRows.push([]);
        summaryRows.push(['DAILY HEADCOUNT']);
        summaryRows.push(['Day', 'Date', 'Present', 'Absent', 'Holiday', 'OT Hours']);
        const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        for (let day = 1; day <= daysInMonth; day++) {
            const ds = dailyStats[day];
            if (!ds) continue;
            const date = new Date(year, monthNum - 1, day);
            summaryRows.push([
                dayNames[date.getDay()],
                `${day}/${monthNum}/${year}`,
                ds.present, ds.absent, ds.holiday,
                Math.round(ds.otHours * 100) / 100
            ]);
        }

        // ===== Assemble sheet =====
        const sheetData = [titleRow, headerRow1, headerRow2, ...dataRows, ...summaryRows];
        const sheet = XLSX.utils.aoa_to_sheet(sheetData);

        // Column widths
        const cols = [
            { wch: 5 },    // S.No
            { wch: 20 },   // Name
            { wch: 12 },   // Designation
            { wch: 10 }    // Team
        ];
        for (let day = 1; day <= daysInMonth; day++) {
            cols.push({ wch: 3 }, { wch: 3 }, { wch: 8 });  // status, OT, project
        }
        cols.push(
            { wch: 13 },   // Total Present
            { wch: 10 },   // Total OT
            { wch: 12 },   // Base Salary
            { wch: 10 },   // Base Pay
            { wch: 10 },   // OT Pay
            { wch: 12 }    // Total Salary
        );
        sheet['!cols'] = cols;

        // Merge title row
        sheet['!merges'] = [
            { s: { r: 0, c: 0 }, e: { r: 0, c: 3 } }
        ];

        XLSX.utils.book_append_sheet(wb, sheet, sheetName);
    }

    const fileName = `salary_report_${new Date().toISOString().split('T')[0]}.xlsx`;
    XLSX.writeFile(wb, fileName);
}
```

---

## 7. EXCEL SHEET LAYOUT REFERENCE

Each month gets its own sheet tab (e.g., `JAN-26`, `FEB-26`).

```
SHEET: JAN-26
==============================================================================

ROW 0  | LABOUR ATTENDANCE FOR JAN-26  (merged across first 4 cols)
-------+----------------------------------------------------------------------
ROW 1  | S.No | Name | DESIGNATION | TEAM | 1 |   |    | 2 |   |    | ... | JAN-26 MONTH LABOUR ATTENDANCE & PAYMENT |   |   |   |   |
ROW 2  |      |      |             |      |   | OT | Pr |   | OT | Pr | ... | TOTAL PRESENT | TOTAL OT | BASE SALARY | BASE PAY | OT PAY | TOTAL SALARY
-------+----------------------------------------------------------------------
ROW 3  |  1   | John | FITTER      | TM-A | P | 2  | ProjA | A |   |    | ... | 22 | 16 | 500 | 11000 | 1000 | 12000
ROW 4  |  2   | Ali  | HELPER      | TM-A | P |    | ProjB | P | 1 | ProjB | ... | 20 | 8  | 400 | 8000  | 400  | 8400
...
-------+----------------------------------------------------------------------
       | (blank row)
       | MONTHLY SUMMARY
       | Total Workers | 45 | | Total Present Days | 990 | | Total OT Hours | 156 | | Total Salary | 450000
       |
       | PROJECT BREAKDOWN
       | Project        | Workers | Working Days | OT Hours
       | Project Alpha  | 15      | 20           | 45.5
       | Project Beta   | 30      | 22           | 111
       |
       | DAILY HEADCOUNT
       | Day | Date       | Present | Absent | Holiday | OT Hours
       | Mon | 1/1/2026   | 40      | 3      | 2       | 7.5
       | Tue | 2/1/2026   | 42      | 1      | 2       | 8.0
       ...
```

**Per-day columns (3 columns per day):**
| Col 1 | Col 2 | Col 3 |
|-------|-------|-------|
| Status (P/A/H) | OT hours | Project name |

Sundays are labeled as `"1 SUNDAY"` in header row 1.

---

## 8. QUICK-START: MINIMAL ERP INTEGRATION

If you just need to read monthly summaries from the shared DB:

```python
import pymysql
import calendar

# Connect to the same database
conn = pymysql.connect(
    host='your-host',
    user='your-user',
    password='your-password',
    database='visma_attendance',
    port=3306
)

def get_month_report(year, month):
    """Get complete monthly report for ERP."""
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # 1. Worker salary summary
    cursor.execute("""
        SELECT worker_id, name, designation, team,
               base_salary_per_day, total_working_days, ot_hours, total_salary,
               (total_working_days * base_salary_per_day) AS base_pay,
               ((base_salary_per_day / 8) * ot_hours) AS ot_pay
        FROM salary
        WHERE year = %s AND month = %s
        ORDER BY team, name
    """, (year, month))
    workers = cursor.fetchall()

    # 2. Daily attendance detail
    cursor.execute("""
        SELECT a.worker_id, a.date, a.status, a.ot_hours, a.project
        FROM attendance a
        WHERE YEAR(a.date) = %s AND MONTH(a.date) = %s
        ORDER BY a.date, a.worker_id
    """, (year, month))
    attendance = cursor.fetchall()

    # 3. Daily headcount
    cursor.execute("""
        SELECT date,
               SUM(status = 'P') AS present,
               SUM(status = 'A') AS absent,
               SUM(status = 'H') AS holiday,
               SUM(ot_hours) AS ot_hours
        FROM attendance
        WHERE YEAR(date) = %s AND MONTH(date) = %s
        GROUP BY date ORDER BY date
    """, (year, month))
    daily = cursor.fetchall()

    # 4. Project breakdown
    cursor.execute("""
        SELECT COALESCE(project, 'Unassigned') AS project,
               COUNT(DISTINCT worker_id) AS workers,
               COUNT(DISTINCT CASE WHEN status='P' THEN date END) AS working_days,
               SUM(ot_hours) AS ot_hours
        FROM attendance
        WHERE YEAR(date) = %s AND MONTH(date) = %s AND status = 'P'
        GROUP BY COALESCE(project, 'Unassigned')
    """, (year, month))
    projects = cursor.fetchall()

    # 5. KPIs
    total_salary = sum(float(w['total_salary'] or 0) for w in workers)
    total_workers = len([w for w in workers if (w['total_working_days'] or 0) > 0])

    cursor.close()

    return {
        'month_name': f"{calendar.month_name[month]} {year}",
        'total_workers': total_workers,
        'total_salary': total_salary,
        'workers': workers,
        'attendance': attendance,
        'daily_headcount': daily,
        'project_breakdown': projects
    }


# Usage:
report = get_month_report(2026, 1)
print(f"{report['month_name']}: {report['total_workers']} workers, Total: {report['total_salary']}")
```

---

## 9. IMPORTANT NOTES

1. **Read-only from ERP**: If your ERP only reads data, you don't need the recalculation logic. The attendance app keeps `salary.total_salary` up to date automatically.

2. **If your ERP also writes attendance**: You MUST call the recalculation logic (Section 4e or 5d) after every attendance insert/update to keep salary totals in sync.

3. **Worker identity**: Workers are identified by `worker_id` (integer). There's no separate workers table — the `salary` table acts as the worker master (one row per worker per month, with the latest row having current metadata).

4. **Latest worker info**: To get a worker's current name/team/designation, query the salary record with the highest `year*100 + month` for that `worker_id`.

5. **Currency**: All amounts are in INR (Indian Rupees). The frontend formats using `en-IN` locale.

6. **OT rate**: Always `base_salary_per_day / 8`. There is no separate OT rate field.

7. **Status values**: `P` = Present, `A` = Absent, `H` = Holiday. Only `P` counts toward working days and salary.
