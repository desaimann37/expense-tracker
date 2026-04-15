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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_conn():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(cur) -> list:
    """Convert cursor results to list of dicts for both DB backends."""
    if USE_POSTGRES:
        return [dict(row) for row in cur.fetchall()]
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _due_dates(start: date, as_of: date, frequency: str) -> list:
    """Generate all due dates from start up to as_of for a given frequency."""
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


# ---------------------------------------------------------------------------
# DB Init — creates tables and safely migrates existing schemas
# ---------------------------------------------------------------------------

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    serial = "SERIAL" if USE_POSTGRES else "INTEGER"
    ai = "" if USE_POSTGRES else "AUTOINCREMENT"

    # expenses table
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

    # budgets table
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

    # recurring_expenses table
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

    # Migrate existing expenses table — add new columns if missing
    if USE_POSTGRES:
        cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT NULL")
        cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS recurring_id INTEGER DEFAULT NULL")
    else:
        for col, definition in [("deleted_at", "TEXT DEFAULT NULL"), ("recurring_id", "INTEGER DEFAULT NULL")]:
            try:
                cur.execute(f"ALTER TABLE expenses ADD COLUMN {col} {definition}")
            except Exception:
                pass

    conn.commit()
    cur.close()
    conn.close()


init_db()


# ---------------------------------------------------------------------------
# Core expense tools
# ---------------------------------------------------------------------------

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
        WHERE date BETWEEN {ph} AND {ph}
        AND deleted_at IS NULL
    """
    params = [start_date, end_date]
    if category:
        query += f" AND category = {ph}"
        params.append(category)
    if subcategory:
        query += f" AND subcategory = {ph}"
        params.append(subcategory)
    query += " ORDER BY date ASC, id ASC"
    cur.execute(query, params)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def summarize(start_date: str, end_date: str, category: str = None, group_by_subcategory: bool = False) -> list:
    """Summarize expenses by category (or subcategory) in a date range. Excludes deleted expenses.
    Set group_by_subcategory=True with a category filter to drill down into subcategories."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()

    if group_by_subcategory and category:
        select = "subcategory AS label, SUM(amount) AS total_amount"
        group = "subcategory"
    else:
        select = "category AS label, SUM(amount) AS total_amount"
        group = "category"

    query = f"""
        SELECT {select}
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph}
        AND deleted_at IS NULL
    """
    params = [start_date, end_date]
    if category:
        query += f" AND category = {ph}"
        params.append(category)
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
    Optionally filter by date range, category, or amount range."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    like = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    kw = f"%{keyword}%"
    query = f"""
        SELECT id, date, amount, category, subcategory, note
        FROM expenses
        WHERE deleted_at IS NULL
        AND (note LIKE {like} OR category LIKE {like} OR subcategory LIKE {like})
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
        SELECT id, date, amount, category, subcategory, note
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph}
        AND deleted_at IS NULL
    """
    params = [start_date, end_date]
    if category:
        query += f" AND category = {ph}"; params.append(category)
    query += f" ORDER BY amount DESC LIMIT {ph}"
    params.append(limit)
    cur.execute(query, params)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


# ---------------------------------------------------------------------------
# Soft-delete and restore tools
# ---------------------------------------------------------------------------

@mcp.tool()
def delete_expense(expense_id: int) -> dict:
    """Soft-delete a single expense by ID. Restorable with restore_expense."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE expenses SET deleted_at = {ph} WHERE id = {ph} AND deleted_at IS NULL",
        (_now(), expense_id)
    )
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if affected == 0:
        return {"status": "error", "message": f"Expense {expense_id} not found or already deleted"}
    return {"status": "ok", "deleted_id": expense_id}


@mcp.tool()
def delete_category(category: str) -> dict:
    """Soft-delete ALL active expenses in a category at once. Restorable with restore_category."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE expenses SET deleted_at = {ph} WHERE category = {ph} AND deleted_at IS NULL",
        (_now(), category)
    )
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "category": category, "deleted_count": affected}


@mcp.tool()
def list_deleted_expenses(category: str = None) -> list:
    """List all soft-deleted expenses with deletion timestamps. Optionally filter by category."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    query = "SELECT id, date, amount, category, subcategory, note, deleted_at FROM expenses WHERE deleted_at IS NOT NULL"
    params = []
    if category:
        query += f" AND category = {ph}"; params.append(category)
    query += " ORDER BY deleted_at DESC"
    cur.execute(query, params)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def restore_expense(expense_id: int) -> dict:
    """Restore a single soft-deleted expense by ID."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE expenses SET deleted_at = NULL WHERE id = {ph} AND deleted_at IS NOT NULL",
        (expense_id,)
    )
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if affected == 0:
        return {"status": "error", "message": f"Expense {expense_id} not found or not deleted"}
    return {"status": "ok", "restored_id": expense_id}


@mcp.tool()
def restore_category(category: str) -> dict:
    """Restore all soft-deleted expenses in a category."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE expenses SET deleted_at = NULL WHERE category = {ph} AND deleted_at IS NOT NULL",
        (category,)
    )
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "category": category, "restored_count": affected}


# ---------------------------------------------------------------------------
# Budget tools
# ---------------------------------------------------------------------------

@mcp.tool()
def set_budget(category: str, amount: float, period: str = "monthly") -> dict:
    """Set or update a spending budget for a category. period can be: monthly, weekly, yearly.
    Calling this again for the same category+period updates the existing budget."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute("""
            INSERT INTO budgets(category, amount, period, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(category, period) DO UPDATE SET amount = EXCLUDED.amount
        """, (category, amount, period, _now()))
    else:
        cur.execute("""
            INSERT INTO budgets(category, amount, period, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(category, period) DO UPDATE SET amount = excluded.amount
        """, (category, amount, period, _now()))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "category": category, "amount": amount, "period": period}


@mcp.tool()
def get_budget_status(period_start: str, period_end: str, category: str = None) -> list:
    """Compare actual spending against budgets for a date range.
    Returns each budgeted category with spent, remaining, and percentage used.
    Use this to answer questions like 'how am I doing on my budget this month?'"""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    query = f"""
        SELECT
            b.category,
            b.amount AS budget,
            b.period,
            COALESCE(SUM(e.amount), 0) AS spent
        FROM budgets b
        LEFT JOIN expenses e
            ON e.category = b.category
            AND e.date BETWEEN {ph} AND {ph}
            AND e.deleted_at IS NULL
    """
    params = [period_start, period_end]
    if category:
        query += f" WHERE b.category = {ph}"
        params.append(category)
    query += " GROUP BY b.category, b.amount, b.period ORDER BY b.category ASC"
    cur.execute(query, params)
    rows = _rows(cur)
    cur.close()
    conn.close()

    result = []
    for row in rows:
        budget = row["budget"]
        spent = row["spent"]
        remaining = budget - spent
        pct_used = round((spent / budget * 100) if budget > 0 else 0, 1)
        status = "over_budget" if spent > budget else ("near_limit" if pct_used >= 80 else "on_track")
        result.append({
            "category": row["category"],
            "period": row["period"],
            "budget": budget,
            "spent": round(spent, 2),
            "remaining": round(remaining, 2),
            "pct_used": pct_used,
            "status": status
        })
    return result


@mcp.tool()
def list_budgets() -> list:
    """List all configured budgets."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute("SELECT id, category, amount, period, created_at FROM budgets ORDER BY category ASC")
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def delete_budget(category: str, period: str = "monthly") -> dict:
    """Remove a budget for a category."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM budgets WHERE category = {ph} AND period = {ph}", (category, period))
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if affected == 0:
        return {"status": "error", "message": f"No budget found for {category} ({period})"}
    return {"status": "ok", "deleted": category, "period": period}


# ---------------------------------------------------------------------------
# Recurring expense tools
# ---------------------------------------------------------------------------

@mcp.tool()
def add_recurring(name: str, amount: float, category: str, frequency: str,
                  start_date: str, subcategory: str = "", note: str = "") -> dict:
    """Add a recurring expense template (e.g. rent, Netflix, gym).
    frequency: daily | weekly | monthly | yearly
    start_date: YYYY-MM-DD — date of first occurrence.
    Call apply_recurring to generate the actual expense entries."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(
            "INSERT INTO recurring_expenses(name, amount, category, subcategory, note, frequency, start_date) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (name, amount, category, subcategory, note, frequency, start_date)
        )
        rec_id = cur.fetchone()[0]
    else:
        cur.execute(
            "INSERT INTO recurring_expenses(name, amount, category, subcategory, note, frequency, start_date) VALUES (?,?,?,?,?,?,?)",
            (name, amount, category, subcategory, note, frequency, start_date)
        )
        rec_id = cur.lastrowid
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "id": rec_id, "name": name, "frequency": frequency}


@mcp.tool()
def list_recurring() -> list:
    """List all active recurring expense templates."""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute("""
        SELECT id, name, amount, category, subcategory, note, frequency, start_date, last_applied
        FROM recurring_expenses
        WHERE active = 1
        ORDER BY category ASC, name ASC
    """)
    result = _rows(cur)
    cur.close()
    conn.close()
    return result


@mcp.tool()
def apply_recurring(as_of_date: str = None) -> dict:
    """Generate expense entries for all active recurring templates up to as_of_date (defaults to today).
    Safe to call multiple times — never double-inserts. Call this at the start of each session
    or when a user asks 'am I up to date?' to ensure recurring expenses like rent and subscriptions
    are logged automatically."""
    as_of = date.fromisoformat(as_of_date) if as_of_date else date.today()
    ph = "%s" if USE_POSTGRES else "?"

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute("SELECT * FROM recurring_expenses WHERE active = 1")
    templates = _rows(cur)

    applied = []
    for t in templates:
        start = date.fromisoformat(t["start_date"])
        all_due = _due_dates(start, as_of, t["frequency"])

        # Find dates already logged for this recurring template
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
        cur2.execute(
            f"SELECT date FROM expenses WHERE recurring_id = {ph} AND deleted_at IS NULL",
            (t["id"],)
        )
        already = {r["date"] for r in _rows(cur2)}
        cur2.close()

        missing = [d for d in all_due if d.isoformat() not in already]
        for d in missing:
            if USE_POSTGRES:
                cur3 = conn.cursor()
                cur3.execute(
                    "INSERT INTO expenses(date, amount, category, subcategory, note, recurring_id) VALUES (%s,%s,%s,%s,%s,%s)",
                    (d.isoformat(), t["amount"], t["category"], t["subcategory"], t["note"], t["id"])
                )
                cur3.close()
            else:
                cur3 = conn.cursor()
                cur3.execute(
                    "INSERT INTO expenses(date, amount, category, subcategory, note, recurring_id) VALUES (?,?,?,?,?,?)",
                    (d.isoformat(), t["amount"], t["category"], t["subcategory"], t["note"], t["id"])
                )
                cur3.close()

        if missing:
            cur4 = conn.cursor()
            cur4.execute(
                f"UPDATE recurring_expenses SET last_applied = {ph} WHERE id = {ph}",
                (max(missing).isoformat(), t["id"])
            )
            cur4.close()
            applied.append({"name": t["name"], "dates_added": [d.isoformat() for d in missing]})

    conn.commit()
    cur.close()
    conn.close()
    total = sum(len(a["dates_added"]) for a in applied)
    return {"status": "ok", "total_entries_added": total, "applied": applied}


@mcp.tool()
def delete_recurring(recurring_id: int) -> dict:
    """Delete a recurring expense template (stops future entries). Does not affect already-generated expenses."""
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM recurring_expenses WHERE id = {ph}", (recurring_id,))
    affected = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if affected == 0:
        return {"status": "error", "message": f"Recurring template {recurring_id} not found"}
    return {"status": "ok", "deleted_recurring_id": recurring_id}


# ---------------------------------------------------------------------------
# Analytics tools
# ---------------------------------------------------------------------------

@mcp.tool()
def monthly_report(year: int, month: int) -> dict:
    """Generate a comprehensive monthly spending report.
    Includes: total spent, category breakdown with % of total, top 5 expenses,
    budget alerts (if budgets are set), and daily spending totals.
    Use this when asked 'how did I do in April?' or 'give me a summary for March'."""
    start = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    ph = "%s" if USE_POSTGRES else "?"

    conn = get_conn()

    # Total spent
    cur = conn.cursor()
    cur.execute(
        f"SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL",
        (start, end)
    )
    total = cur.fetchone()[0] or 0
    cur.close()

    # By category
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"""
        SELECT category, SUM(amount) AS total_amount
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL
        GROUP BY category ORDER BY total_amount DESC
    """, (start, end))
    by_cat_rows = _rows(cur)
    cur.close()
    by_category = [
        {"category": r["category"], "total": round(r["total_amount"], 2),
         "pct": round(r["total_amount"] / total * 100, 1) if total > 0 else 0}
        for r in by_cat_rows
    ]

    # Top 5 expenses
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"""
        SELECT id, date, amount, category, subcategory, note
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL
        ORDER BY amount DESC LIMIT 5
    """, (start, end))
    top5 = _rows(cur)
    cur.close()

    # Daily totals
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"""
        SELECT date, SUM(amount) AS daily_total
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph} AND deleted_at IS NULL
        GROUP BY date ORDER BY date ASC
    """, (start, end))
    daily = {r["date"]: round(r["daily_total"], 2) for r in _rows(cur)}
    cur.close()

    # Budget alerts
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if USE_POSTGRES else conn.cursor()
    cur.execute(f"""
        SELECT b.category, b.amount AS budget,
               COALESCE(SUM(e.amount), 0) AS spent
        FROM budgets b
        LEFT JOIN expenses e
            ON e.category = b.category
            AND e.date BETWEEN {ph} AND {ph}
            AND e.deleted_at IS NULL
        WHERE b.period = 'monthly'
        GROUP BY b.category, b.amount
    """, (start, end))
    budget_rows = _rows(cur)
    cur.close()
    conn.close()

    budget_alerts = []
    for row in budget_rows:
        spent = row["spent"]
        budget = row["budget"]
        pct = round(spent / budget * 100, 1) if budget > 0 else 0
        if pct >= 80:
            budget_alerts.append({
                "category": row["category"],
                "budget": budget,
                "spent": round(spent, 2),
                "over_by": round(spent - budget, 2) if spent > budget else 0,
                "pct_used": pct,
                "status": "over_budget" if spent > budget else "near_limit"
            })

    return {
        "month": f"{year:04d}-{month:02d}",
        "total_spent": round(total, 2),
        "by_category": by_category,
        "top_expenses": top5,
        "budget_alerts": budget_alerts,
        "daily_totals": daily
    }


@mcp.tool()
def spending_trend(months: int = 3, category: str = None) -> list:
    """Show month-over-month spending totals for the last N months (default 3).
    Optionally filter to one category to see its trend.
    Use this to answer 'am I spending more than before?' or 'show my food spending trend'."""
    today = date.today()
    results = []

    for i in range(months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        start = f"{y:04d}-{m:02d}-01"
        last_day = calendar.monthrange(y, m)[1]
        end = f"{y:04d}-{m:02d}-{last_day:02d}"

        conn = get_conn()
        cur = conn.cursor()
        _ph = "%s" if USE_POSTGRES else "?"
        query = f"""
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE date BETWEEN {_ph} AND {_ph}
            AND deleted_at IS NULL
        """
        params = [start, end]
        if category:
            query += f" AND category = {_ph}"
            params.append(category)
        cur.execute(query, params)
        total = cur.fetchone()[0] or 0
        cur.close()
        conn.close()
        results.append({"month": f"{y:04d}-{m:02d}", "total": round(total, 2)})

    # Add month-over-month change
    for i in range(1, len(results)):
        prev = results[i - 1]["total"]
        curr = results[i]["total"]
        if prev > 0:
            change_pct = round((curr - prev) / prev * 100, 1)
        else:
            change_pct = None
        results[i]["change_pct"] = change_pct

    return results


# ---------------------------------------------------------------------------
# Categories resource
# ---------------------------------------------------------------------------

@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    """Return the list of valid expense categories and subcategories."""
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
