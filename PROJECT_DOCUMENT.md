# Expense Tracker MCP Server — Project Documentation

## Overview

A **Model Context Protocol (MCP) server** for tracking personal expenses with AI. Exposes 21 tools and 1 resource that allow Claude to add, list, search, summarize, update, delete, restore, budget, automate recurring expenses, and generate analytics — all via natural language conversation.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| MCP Framework | FastMCP 3.2.x |
| Language | Python 3.13+ |
| Package Manager | uv |
| Local Database | SQLite |
| Cloud Database | PostgreSQL (Render) |
| Cloud Hosting | Render (free tier) |
| Tunnel | Cloudflare Tunnel (optional) |
| Transport (local) | stdio |
| Transport (remote) | streamable-http |

---

## Project Structure

```
expense-tracker/
├── main.py               # MCP server — all 21 tools and resources
├── categories.json       # 20 expense categories with subcategories
├── pyproject.toml        # Python dependencies
├── Procfile              # Render start command
├── README.md             # Setup and usage guide
├── PROJECT_DOCUMENT.md   # This file — full project documentation
├── expenses.db           # Local SQLite database (auto-created)
└── .venv/                # Virtual environment
```

---

## Step 1 — Project Setup

```bash
mkdir expense-tracker && cd expense-tracker
uv init
uv add fastmcp psycopg2-binary
```

### pyproject.toml
```toml
[project]
name = "expense-tracker"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastmcp>=3.2.3",
    "psycopg2-binary>=2.9.9",
]
```

---

## Step 2 — MCP Server Code (main.py)

```python
from fastmcp import FastMCP
import os
import calendar
from datetime import datetime, timezone, date, timedelta

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = DATABASE_URL is not None
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
else:
    import sqlite3
    DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")

mcp = FastMCP("ExpenseTracker")


def get_conn():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(cur) -> list:
    if USE_POSTGRES:
        return [dict(row) for row in cur.fetchall()]
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _due_dates(start: date, as_of: date, frequency: str) -> list:
    dates = []
    d = start
    while d <= as_of:
        dates.append(d)
        if frequency == "daily":
            d += timedelta(days=1)
        elif frequency == "weekly":
            d += timedelta(weeks=1)
        elif frequency == "monthly":
            month = d.month + 1
            year = d.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            day = min(d.day, calendar.monthrange(year, month)[1])
            d = date(year, month, day)
        elif frequency == "yearly":
            try:
                d = date(d.year + 1, d.month, d.day)
            except ValueError:
                d = date(d.year + 1, d.month, 28)
        else:
            break
    return dates


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    serial = "SERIAL" if USE_POSTGRES else "INTEGER"
    ai = "" if USE_POSTGRES else "AUTOINCREMENT"

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS expenses(
            id {serial} PRIMARY KEY {ai},
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT DEFAULT '',
            note TEXT DEFAULT '',
            deleted_at TEXT DEFAULT NULL,
            recurring_id INTEGER DEFAULT NULL
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS budgets(
            id {serial} PRIMARY KEY {ai},
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            period TEXT NOT NULL DEFAULT 'monthly',
            created_at TEXT NOT NULL,
            UNIQUE(category, period)
        )
    """)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS recurring_expenses(
            id {serial} PRIMARY KEY {ai},
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT DEFAULT '',
            note TEXT DEFAULT '',
            frequency TEXT NOT NULL DEFAULT 'monthly',
            start_date TEXT NOT NULL,
            last_applied TEXT DEFAULT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    if USE_POSTGRES:
        cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT NULL")
        cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS recurring_id INTEGER DEFAULT NULL")
    else:
        for col, defn in [("deleted_at", "TEXT DEFAULT NULL"), ("recurring_id", "INTEGER DEFAULT NULL")]:
            try:
                cur.execute(f"ALTER TABLE expenses ADD COLUMN {col} {defn}")
            except Exception:
                pass
    conn.commit()
    cur.close()
    conn.close()


init_db()


@mcp.tool()
def add_expense(date: str, amount: float, category: str, subcategory: str = "", note: str = "") -> dict:
    """Add a new expense entry to the database."""
    conn = get_conn()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(
            "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (date, amount, category, subcategory, note)
        )
        expense_id = cur.fetchone()[0]
    else:
        cur.execute(
            "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?,?,?,?,?)",
            (date, amount, category, subcategory, note)
        )
        expense_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "id": expense_id}


@mcp.tool()
def list_expenses(start_date: str, end_date: str, category: str = None, subcategory: str = None) -> list:
    """List active (non-deleted) expenses in a date range. Optionally filter by category or subcategory."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    query = f"""
        SELECT id, date, amount, category, subcategory, note, recurring_id
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL
    """
    params = [start_date, end_date]
    if category:
        query += f" AND category = {ph}"; params.append(category)
    if subcategory:
        query += f" AND subcategory = {ph}"; params.append(subcategory)
    query += " ORDER BY date ASC, id ASC"
    cur.execute(query, params)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def summarize(start_date: str, end_date: str, category: str = None, group_by_subcategory: bool = False) -> list:
    """Summarize expenses by category or subcategory. Set group_by_subcategory=True with a
    category filter to drill into subcategories."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    if group_by_subcategory and category:
        select, group = "subcategory AS label, SUM(amount) AS total_amount", "subcategory"
    else:
        select, group = "category AS label, SUM(amount) AS total_amount", "category"
    query = f"SELECT {select} FROM expenses WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL"
    params = [start_date, end_date]
    if category:
        query += f" AND category = {ph}"; params.append(category)
    query += f" GROUP BY {group} ORDER BY total_amount DESC"
    cur.execute(query, params)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def update_expense(expense_id: int, amount: float = None, category: str = None,
                   date: str = None, note: str = None, subcategory: str = None) -> dict:
    """Update an existing active expense by its ID."""
    ph = "%s" if USE_POSTGRES else "?"
    fields, values = [], []
    if amount is not None:
        fields.append(f"amount = {ph}"); values.append(amount)
    if category is not None:
        fields.append(f"category = {ph}"); values.append(category)
    if date is not None:
        fields.append(f"date = {ph}"); values.append(date)
    if note is not None:
        fields.append(f"note = {ph}"); values.append(note)
    if subcategory is not None:
        fields.append(f"subcategory = {ph}"); values.append(subcategory)
    if not fields:
        return {"status": "error", "message": "No fields to update"}
    values.append(expense_id)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE expenses SET {', '.join(fields)} WHERE id = {ph} AND deleted_at IS NULL", values)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "updated_id": expense_id}


@mcp.tool()
def search_expenses(keyword: str, start_date: str = None, end_date: str = None,
                    category: str = None, min_amount: float = None, max_amount: float = None) -> list:
    """Search active expenses by keyword (matches note, category, subcategory).
    All params except keyword are optional."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    kw = f"%{keyword}%"
    query = f"""
        SELECT id, date, amount, category, subcategory, note FROM expenses
        WHERE deleted_at IS NULL
        AND (note LIKE {ph} OR category LIKE {ph} OR subcategory LIKE {ph})
    """
    params = [kw, kw, kw]
    if start_date:
        query += f" AND date >= {ph}"; params.append(start_date)
    if end_date:
        query += f" AND date <= {ph}"; params.append(end_date)
    if category:
        query += f" AND category = {ph}"; params.append(category)
    if min_amount is not None:
        query += f" AND amount >= {ph}"; params.append(min_amount)
    if max_amount is not None:
        query += f" AND amount <= {ph}"; params.append(max_amount)
    query += " ORDER BY date DESC, amount DESC"
    cur.execute(query, params)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def top_expenses(start_date: str, end_date: str, limit: int = 10, category: str = None) -> list:
    """Return the largest individual expenses in a date range, sorted by amount descending."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    query = f"""
        SELECT id, date, amount, category, subcategory, note FROM expenses
        WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL
    """
    params = [start_date, end_date]
    if category:
        query += f" AND category = {ph}"; params.append(category)
    query += f" ORDER BY amount DESC LIMIT {ph}"; params.append(limit)
    cur.execute(query, params)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def delete_expense(expense_id: int) -> dict:
    """Soft-delete a single expense by ID. Restorable with restore_expense."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE expenses SET deleted_at = {ph} WHERE id = {ph} AND deleted_at IS NULL", (_now(), expense_id))
    affected = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    if affected == 0:
        return {"status": "error", "message": f"Expense {expense_id} not found or already deleted"}
    return {"status": "ok", "deleted_id": expense_id}


@mcp.tool()
def delete_category(category: str) -> dict:
    """Soft-delete ALL active expenses in a category. Restorable with restore_category."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE expenses SET deleted_at = {ph} WHERE category = {ph} AND deleted_at IS NULL", (_now(), category))
    affected = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return {"status": "ok", "category": category, "deleted_count": affected}


@mcp.tool()
def list_deleted_expenses(category: str = None) -> list:
    """List all soft-deleted expenses with deletion timestamps."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    query = "SELECT id, date, amount, category, subcategory, note, deleted_at FROM expenses WHERE deleted_at IS NOT NULL"
    params = []
    if category:
        query += f" AND category = {ph}"; params.append(category)
    query += " ORDER BY deleted_at DESC"
    cur.execute(query, params)
    result = _rows(cur); cur.close(); conn.close()
    return result


@mcp.tool()
def restore_expense(expense_id: int) -> dict:
    """Restore a single soft-deleted expense by ID."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE expenses SET deleted_at = NULL WHERE id = {ph} AND deleted_at IS NOT NULL", (expense_id,))
    affected = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    if affected == 0:
        return {"status": "error", "message": f"Expense {expense_id} not found or not deleted"}
    return {"status": "ok", "restored_id": expense_id}


@mcp.tool()
def restore_category(category: str) -> dict:
    """Restore all soft-deleted expenses in a category."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE expenses SET deleted_at = NULL WHERE category = {ph} AND deleted_at IS NOT NULL", (category,))
    affected = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    return {"status": "ok", "category": category, "restored_count": affected}


@mcp.tool()
def set_budget(category: str, amount: float, period: str = "monthly") -> dict:
    """Set or update a spending budget for a category (upsert — safe to call again to update)."""
    conn = get_conn()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute("""
            INSERT INTO budgets(category, amount, period, created_at) VALUES (%s,%s,%s,%s)
            ON CONFLICT(category, period) DO UPDATE SET amount = EXCLUDED.amount
        """, (category, amount, period, _now()))
    else:
        cur.execute("""
            INSERT INTO budgets(category, amount, period, created_at) VALUES (?,?,?,?)
            ON CONFLICT(category, period) DO UPDATE SET amount = excluded.amount
        """, (category, amount, period, _now()))
    conn.commit(); cur.close(); conn.close()
    return {"status": "ok", "category": category, "amount": amount, "period": period}


@mcp.tool()
def get_budget_status(period_start: str, period_end: str, category: str = None) -> list:
    """Compare actual spending vs budgets. Returns spent, remaining, pct_used, and status
    (on_track / near_limit / over_budget) for each budgeted category."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    query = f"""
        SELECT b.category, b.amount AS budget, b.period, COALESCE(SUM(e.amount), 0) AS spent
        FROM budgets b
        LEFT JOIN expenses e ON e.category = b.category
            AND e.date BETWEEN {ph} AND {ph} AND e.deleted_at IS NULL
    """
    params = [period_start, period_end]
    if category:
        query += f" WHERE b.category = {ph}"; params.append(category)
    query += " GROUP BY b.category, b.amount, b.period ORDER BY b.category ASC"
    cur.execute(query, params)
    rows = _rows(cur); cur.close(); conn.close()
    result = []
    for row in rows:
        budget, spent = row["budget"], row["spent"]
        pct = round(spent / budget * 100, 1) if budget > 0 else 0
        result.append({
            "category": row["category"], "period": row["period"],
            "budget": budget, "spent": round(spent, 2),
            "remaining": round(budget - spent, 2), "pct_used": pct,
            "status": "over_budget" if spent > budget else ("near_limit" if pct >= 80 else "on_track")
        })
    return result


@mcp.tool()
def list_budgets() -> list:
    """List all configured budgets."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute("SELECT id, category, amount, period, created_at FROM budgets ORDER BY category ASC")
    result = _rows(cur); cur.close(); conn.close()
    return result


@mcp.tool()
def delete_budget(category: str, period: str = "monthly") -> dict:
    """Remove a budget for a category."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM budgets WHERE category = {ph} AND period = {ph}", (category, period))
    affected = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    if affected == 0:
        return {"status": "error", "message": f"No budget found for {category} ({period})"}
    return {"status": "ok", "deleted": category, "period": period}


@mcp.tool()
def add_recurring(name: str, amount: float, category: str, frequency: str,
                  start_date: str, subcategory: str = "", note: str = "") -> dict:
    """Create a recurring expense template (rent, Netflix, EMI, gym, etc.).
    frequency: daily | weekly | monthly | yearly. Call apply_recurring to generate entries."""
    conn = get_conn()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(
            "INSERT INTO recurring_expenses(name,amount,category,subcategory,note,frequency,start_date) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (name, amount, category, subcategory, note, frequency, start_date)
        )
        rec_id = cur.fetchone()[0]
    else:
        cur.execute(
            "INSERT INTO recurring_expenses(name,amount,category,subcategory,note,frequency,start_date) VALUES (?,?,?,?,?,?,?)",
            (name, amount, category, subcategory, note, frequency, start_date)
        )
        rec_id = cur.lastrowid
    conn.commit(); cur.close(); conn.close()
    return {"status": "ok", "id": rec_id, "name": name, "frequency": frequency}


@mcp.tool()
def list_recurring() -> list:
    """List all active recurring expense templates."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute("SELECT id,name,amount,category,subcategory,note,frequency,start_date,last_applied FROM recurring_expenses WHERE active=1 ORDER BY category,name")
    result = _rows(cur); cur.close(); conn.close()
    return result


@mcp.tool()
def apply_recurring(as_of_date: str = None) -> dict:
    """Generate expense entries for all active recurring templates up to as_of_date (default: today).
    Idempotent — safe to call multiple times, never double-inserts.
    Call this at session start or when asked 'am I up to date?'"""
    as_of = date.fromisoformat(as_of_date) if as_of_date else date.today()
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute("SELECT * FROM recurring_expenses WHERE active = 1")
    templates = _rows(cur)
    applied = []
    for t in templates:
        start = date.fromisoformat(t["start_date"])
        all_due = _due_dates(start, as_of, t["frequency"])
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur2.execute(f"SELECT date FROM expenses WHERE recurring_id = {ph} AND deleted_at IS NULL", (t["id"],))
        already = {r["date"] for r in _rows(cur2)}; cur2.close()
        missing = [d for d in all_due if d.isoformat() not in already]
        for d in missing:
            cur3 = conn.cursor()
            if USE_POSTGRES:
                cur3.execute("INSERT INTO expenses(date,amount,category,subcategory,note,recurring_id) VALUES (%s,%s,%s,%s,%s,%s)",
                             (d.isoformat(), t["amount"], t["category"], t["subcategory"], t["note"], t["id"]))
            else:
                cur3.execute("INSERT INTO expenses(date,amount,category,subcategory,note,recurring_id) VALUES (?,?,?,?,?,?)",
                             (d.isoformat(), t["amount"], t["category"], t["subcategory"], t["note"], t["id"]))
            cur3.close()
        if missing:
            cur4 = conn.cursor()
            cur4.execute(f"UPDATE recurring_expenses SET last_applied = {ph} WHERE id = {ph}",
                         (max(missing).isoformat(), t["id"])); cur4.close()
            applied.append({"name": t["name"], "dates_added": [d.isoformat() for d in missing]})
    conn.commit(); cur.close(); conn.close()
    return {"status": "ok", "total_entries_added": sum(len(a["dates_added"]) for a in applied), "applied": applied}


@mcp.tool()
def delete_recurring(recurring_id: int) -> dict:
    """Delete a recurring template (stops future entries). Does not affect already-generated expenses."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM recurring_expenses WHERE id = {ph}", (recurring_id,))
    affected = cur.rowcount
    conn.commit(); cur.close(); conn.close()
    if affected == 0:
        return {"status": "error", "message": f"Recurring template {recurring_id} not found"}
    return {"status": "ok", "deleted_recurring_id": recurring_id}


@mcp.tool()
def monthly_report(year: int, month: int) -> dict:
    """Full monthly spending report: total, by-category breakdown with % of total,
    top 5 expenses, budget alerts, and daily spending totals."""
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL", (start, end))
    total = cur.fetchone()[0] or 0; cur.close()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"SELECT category, SUM(amount) AS t FROM expenses WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL GROUP BY category ORDER BY t DESC", (start, end))
    by_category = [{"category": r["category"], "total": round(r["t"], 2), "pct": round(r["t"]/total*100, 1) if total else 0} for r in _rows(cur)]; cur.close()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"SELECT id,date,amount,category,subcategory,note FROM expenses WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL ORDER BY amount DESC LIMIT 5", (start, end))
    top5 = _rows(cur); cur.close()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"SELECT date, SUM(amount) AS dt FROM expenses WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL GROUP BY date ORDER BY date ASC", (start, end))
    daily = {r["date"]: round(r["dt"], 2) for r in _rows(cur)}; cur.close()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"SELECT b.category, b.amount AS budget, COALESCE(SUM(e.amount),0) AS spent FROM budgets b LEFT JOIN expenses e ON e.category=b.category AND e.date BETWEEN {ph} AND {ph} AND e.deleted_at IS NULL WHERE b.period='monthly' GROUP BY b.category,b.amount", (start, end))
    budget_alerts = []
    for row in _rows(cur):
        pct = round(row["spent"]/row["budget"]*100, 1) if row["budget"] else 0
        if pct >= 80:
            budget_alerts.append({"category": row["category"], "budget": row["budget"], "spent": round(row["spent"], 2), "over_by": round(row["spent"]-row["budget"], 2) if row["spent"] > row["budget"] else 0, "pct_used": pct, "status": "over_budget" if row["spent"] > row["budget"] else "near_limit"})
    cur.close(); conn.close()
    return {"month": f"{year:04d}-{month:02d}", "total_spent": round(total, 2), "by_category": by_category, "top_expenses": top5, "budget_alerts": budget_alerts, "daily_totals": daily}


@mcp.tool()
def spending_trend(months: int = 3, category: str = None) -> list:
    """Month-over-month spending totals for the last N months with % change.
    Filter by category to see a single category's trend."""
    today = date.today()
    results = []
    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12; y -= 1
        start = f"{y:04d}-{m:02d}-01"
        end = f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
        conn = get_conn()
        cur = conn.cursor()
        _ph = "%s" if USE_POSTGRES else "?"
        q = f"SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date BETWEEN {_ph} AND {_ph} AND deleted_at IS NULL"
        params = [start, end]
        if category:
            q += f" AND category = {_ph}"; params.append(category)
        cur.execute(q, params)
        total = cur.fetchone()[0] or 0; cur.close(); conn.close()
        results.append({"month": f"{y:04d}-{m:02d}", "total": round(total, 2)})
    for i in range(1, len(results)):
        prev = results[i-1]["total"]
        results[i]["change_pct"] = round((results[i]["total"]-prev)/prev*100, 1) if prev > 0 else None
    return results


@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    """Return the list of valid expense categories and subcategories."""
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
```

---

## Step 3 — Database Schema

Three tables. All created and migrated automatically on server startup — no manual SQL needed.

### expenses
```sql
CREATE TABLE expenses (
    id           SERIAL PRIMARY KEY,
    date         TEXT NOT NULL,           -- YYYY-MM-DD
    amount       REAL NOT NULL,
    category     TEXT NOT NULL,
    subcategory  TEXT DEFAULT '',
    note         TEXT DEFAULT '',
    deleted_at   TEXT DEFAULT NULL,       -- NULL=active, ISO timestamp=soft-deleted
    recurring_id INTEGER DEFAULT NULL     -- FK to recurring_expenses.id
);
```

### budgets
```sql
CREATE TABLE budgets (
    id         SERIAL PRIMARY KEY,
    category   TEXT NOT NULL,
    amount     REAL NOT NULL,
    period     TEXT NOT NULL DEFAULT 'monthly',  -- monthly | weekly | yearly
    created_at TEXT NOT NULL,
    UNIQUE(category, period)
);
```

### recurring_expenses
```sql
CREATE TABLE recurring_expenses (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    amount       REAL NOT NULL,
    category     TEXT NOT NULL,
    subcategory  TEXT DEFAULT '',
    note         TEXT DEFAULT '',
    frequency    TEXT NOT NULL,     -- daily | weekly | monthly | yearly
    start_date   TEXT NOT NULL,     -- YYYY-MM-DD, first occurrence
    last_applied TEXT DEFAULT NULL, -- display hint for last generation
    active       INTEGER DEFAULT 1
);
```

### Migration strategy
`init_db()` runs on every server start. It uses:
- PostgreSQL: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- SQLite: `ALTER TABLE ... ADD COLUMN` wrapped in try/except

This means existing production databases are migrated automatically on redeploy — no manual `psql` commands.

---

## Step 3 — All Tools (21)

### Core expense tools

**`add_expense(date, amount, category, subcategory="", note="")`**
Add a new expense. Returns `{"status": "ok", "id": N}`.

**`list_expenses(start_date, end_date, category=None, subcategory=None)`**
List active (non-deleted) expenses in a date range. Optional category/subcategory filters added in v2.

**`summarize(start_date, end_date, category=None, group_by_subcategory=False)`**
Total spending by category. Set `group_by_subcategory=True` with a `category` filter to drill into subcategories (e.g. "break down my food spending").

**`update_expense(expense_id, amount, category, date, note, subcategory)`**
Update any field of an active expense. Only updates fields that are passed.

**`search_expenses(keyword, start_date, end_date, category, min_amount, max_amount)`**
Full-text keyword search across note, category, subcategory. All params except `keyword` are optional. Supports amount range filtering.

**`top_expenses(start_date, end_date, limit=10, category=None)`**
Returns the N largest individual expenses in a date range, sorted by amount descending.

### Soft-delete & restore tools

Deleted records are never permanently removed. `deleted_at` stores the UTC timestamp of deletion.

**`delete_expense(expense_id)`**
Soft-delete a single expense. Returns error if already deleted.

**`delete_category(category)`**
Soft-delete ALL active expenses in a category at once. Returns `deleted_count`.

**`list_deleted_expenses(category=None)`**
View all soft-deleted expenses with `deleted_at` timestamps. Optional category filter.

**`restore_expense(expense_id)`**
Restore a single deleted expense (sets `deleted_at = NULL`).

**`restore_category(category)`**
Restore all deleted expenses in a category. Returns `restored_count`.

### Budget tools

**`set_budget(category, amount, period="monthly")`**
Set or update a spending limit. Upsert — calling twice updates, never duplicates.
`period` accepts: `monthly`, `weekly`, `yearly`.

**`get_budget_status(period_start, period_end, category=None)`**
Compare actual spending against budgets. Returns per-category:
```json
{
  "category": "food",
  "budget": 5000.0,
  "spent": 3200.0,
  "remaining": 1800.0,
  "pct_used": 64.0,
  "status": "on_track"    // on_track | near_limit (≥80%) | over_budget
}
```

**`list_budgets()`**
View all configured budgets.

**`delete_budget(category, period="monthly")`**
Remove a budget.

### Recurring expense tools

**`add_recurring(name, amount, category, frequency, start_date, subcategory="", note="")`**
Create a recurring template. `frequency`: `daily | weekly | monthly | yearly`.
`start_date`: first occurrence date (YYYY-MM-DD).

**`list_recurring()`**
View all active templates with `last_applied` date.

**`apply_recurring(as_of_date=None)`**
The core automation tool. Generates all missing expense entries for every active template from `start_date` up to `as_of_date` (defaults to today).

**Idempotent by design:** Checks existing `expenses` rows with matching `recurring_id + date` before inserting. Calling it 10 times produces the same result as calling it once — never double-inserts.

Call this at the start of each session or when the user asks "am I up to date?" Returns:
```json
{
  "status": "ok",
  "total_entries_added": 2,
  "applied": [
    {"name": "Rent", "dates_added": ["2026-04-01"]},
    {"name": "Netflix", "dates_added": ["2026-04-01"]}
  ]
}
```

**`delete_recurring(recurring_id)`**
Hard-delete a template (stops future generation). Does not affect already-generated expenses.

### Analytics tools

**`monthly_report(year, month)`**
Comprehensive monthly summary in one call:
```json
{
  "month": "2026-04",
  "total_spent": 32436.49,
  "by_category": [
    {"category": "housing", "total": 30000.0, "pct": 92.5},
    ...
  ],
  "top_expenses": [...],
  "budget_alerts": [
    {"category": "food", "budget": 5000, "spent": 6200, "over_by": 1200, "status": "over_budget"}
  ],
  "daily_totals": {"2026-04-01": 30998.0, "2026-04-15": 805.0, ...}
}
```

**`spending_trend(months=3, category=None)`**
Month-over-month totals for last N months with % change:
```json
[
  {"month": "2026-02", "total": 28000.0},
  {"month": "2026-03", "total": 31000.0, "change_pct": 10.7},
  {"month": "2026-04", "total": 32436.0, "change_pct": 4.6}
]
```

### Resource

**`expense://categories`** (MIME: application/json)
Returns `categories.json` — 20 top-level categories each with subcategories. Claude reads this automatically to map natural language descriptions to the correct category/subcategory before calling `add_expense`.

---

## Step 4 — categories.json

20 categories with subcategories:

| Category | Example Subcategories |
|----------|-----------------------|
| food | groceries, dining_out, delivery_fees, coffee_tea |
| transport | fuel, cab_ride_hailing, public_transport, parking |
| housing | rent, maintenance_hoa, repairs_service |
| utilities | electricity, internet_broadband, mobile_phone |
| health | medicines, doctor_consultation, fitness_gym |
| education | courses, books, online_subscriptions |
| shopping | clothing, electronics_gadgets, home_decor |
| subscriptions | saas_tools, cloud_ai, music_video |
| travel | flights, hotels, local_transport |
| investments | mutual_funds, stocks, crypto |
| … | (20 total — see categories.json) |

---

## Step 5 — Local Setup (Claude Desktop)

Claude Desktop spawns the server via stdio — no manual server start needed.

### Config file location
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "C:\\path\\to\\uv.exe",
      "args": [
        "run", "--with", "fastmcp", "fastmcp", "run",
        "C:\\path\\to\\expense-tracker\\main.py"
      ],
      "env": {}
    }
  }
}
```

### Flow
```
Claude Desktop ──stdio──► fastmcp run main.py ──► SQLite (expenses.db)
```

---

## Step 6 — Remote Deployment (Render)

### Procfile
```
web: python main.py
```

### Deploy steps
1. Push to GitHub
2. Render → New Web Service → connect repo
3. **Build command:** `pip install fastmcp psycopg2-binary`
4. **Start command:** `python main.py`
5. Render → New PostgreSQL → free tier → copy Internal URL
6. Web service → Environment → add `DATABASE_URL` → save → auto-redeploys

### Flow
```
claude.ai / any device ──HTTPS──► Render ──► FastMCP ──► PostgreSQL
```

### Render free tier notes
- Web service sleeps after 15 min inactivity (30s cold start)
- PostgreSQL persists forever
- 750 free hours/month

---

## Step 7 — Cloudflare Tunnel (Optional)

Expose local server to the internet without Render.

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -o "$HOME/.local/bin/cloudflared.exe"

# Create named tunnel in Cloudflare dashboard → Zero Trust → Networks → Tunnels
# Add hostname: subdomain=mcp, service=http://localhost:8000

# Run server
uv run python main.py

# Run tunnel
~/.local/bin/cloudflared.exe tunnel run --token <YOUR_TOKEN>
```

### Flow
```
claude.ai ──HTTPS──► Cloudflare ──► cloudflared ──► main.py ──► SQLite
```

---

## Step 8 — Connecting claude.ai Web

1. claude.ai → Settings → Connectors → `+`
2. Paste your deployed server URL:
   ```
   https://<your-app>.onrender.com/mcp
   ```
3. Save — all 21 tools load automatically

---

## Step 9 — Testing with MCP Inspector

### Start inspector
```bash
npx @modelcontextprotocol/inspector
```

If npm cache is corrupted (Windows):
```bash
npx clear-npx-cache
# Kill existing node processes, then:
npx @modelcontextprotocol/inspector
```

### Connect
- Open printed URL: `http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=<token>`
- Transport → `Streamable HTTP`
- URL → `https://<your-app>.onrender.com/mcp`
- Click Connect

### Inspector proxy architecture
```
Browser ──► Inspector UI (6274) ──► Proxy server (6277) ──► MCP Server (Render)
```

### Example test sequence
```
1. set_budget          category=food, amount=5000
2. add_recurring       name=Rent, amount=15000, category=housing, frequency=monthly, start_date=2026-04-01
3. apply_recurring     (no params)
4. get_budget_status   period_start=2026-04-01, period_end=2026-04-30
5. monthly_report      year=2026, month=4
6. spending_trend      months=3
7. search_expenses     keyword=rent
8. top_expenses        start_date=2026-04-01, end_date=2026-04-30, limit=5
```

---

## Step 10 — Architecture Summary

### Local (Claude Desktop)
```
Claude Desktop ──stdio──► fastmcp run main.py ──► SQLite
```

### Remote (claude.ai / any MCP client)
```
Claude / MCP Client ──HTTPS──► Render ──► PostgreSQL
```

### Tunnel (optional, temporary)
```
Claude ──HTTPS──► Cloudflare ──► cloudflared ──► main.py ──► SQLite
```

### MCP Inspector (testing)
```
Browser ──► Inspector UI ──► Proxy ──► MCP Server
```

---

## Step 11 — Key Decisions & Lessons

| Decision | Reason |
|----------|--------|
| FastMCP over raw SDK | Decorator-based API, minimal boilerplate |
| stdio for Claude Desktop | No OAuth, no networking, most reliable |
| streamable-http for remote | Required by claude.ai web |
| PostgreSQL on Render | SQLite resets on every Render restart (ephemeral fs) |
| Dual SQLite/PostgreSQL | `ph = "%s" if USE_POSTGRES else "?"` — one codebase, both DBs |
| `init_db()` auto-migration | `ALTER TABLE ADD COLUMN IF NOT EXISTS` — zero manual DB ops on redeploy |
| Soft-delete over hard-delete | Never lose data — full rollback always available |
| `recurring_id` on expenses | Enables idempotent `apply_recurring` via set subtraction |
| `apply_recurring` idempotency | Checks `(recurring_id, date)` pairs before inserting — safe to call anytime |
| Upsert for budgets | `ON CONFLICT DO UPDATE` — set_budget is also update_budget |
| `group_by_subcategory` in summarize | Drill-down without a separate tool |
| categories.json as MCP resource | Claude reads it at runtime — editable without restart |
| Environment variable for DB URL | Credentials never in source code |

---

## Usage Examples

```
# Daily use
"Add $200 for coffee today"
"I spent $3500 on groceries — log it under food"
"What did I spend today?"

# Budgets
"Set a $8000 monthly budget for food"
"How am I doing on my budget this month?"
"Show all my budgets"

# Recurring
"Set rent as $15000 recurring on the 1st of every month"
"Apply my recurring expenses"
"Stop my Netflix recurring"

# Reports & analytics
"Give me a full report for April"
"Show my spending trend for the last 3 months"
"What are my top 5 expenses this month?"
"Break down my food spending into subcategories"

# Search
"Find all Zomato expenses"
"Show expenses over $5000 in April"
"Search for anything tagged 'business trip'"

# Delete & restore
"Delete expense #12"
"Delete all my entertainment expenses"
"Show me what I deleted"
"Restore my food expenses"
```

---

*Document prepared for Expense Tracker MCP Server v2 — 21 tools, budgets, recurring expenses, analytics.*
