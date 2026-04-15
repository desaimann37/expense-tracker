from fastmcp import FastMCP
import os
from datetime import datetime, timezone

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


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id SERIAL PRIMARY KEY,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT '',
                deleted_at TEXT DEFAULT NULL
            )
        """)
        cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT NULL")
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT '',
                deleted_at TEXT DEFAULT NULL
            )
        """)
        try:
            cur.execute("ALTER TABLE expenses ADD COLUMN deleted_at TEXT DEFAULT NULL")
        except Exception:
            pass  # Column already exists
    conn.commit()
    cur.close()
    conn.close()


init_db()


@mcp.tool()
def add_expense(date, amount, category, subcategory="", note=""):
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
def summarize(start_date, end_date, category=None):
    """Summarize expenses by category within an inclusive date range. Excludes deleted expenses."""
    conn = get_conn()
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        ph = "%s"
    else:
        cur = conn.cursor()
        ph = "?"
    query = f"""
        SELECT category, SUM(amount) AS total_amount
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph}
        AND deleted_at IS NULL
    """
    params = [start_date, end_date]
    if category:
        query += f" AND category = {ph}"
        params.append(category)
    query += " GROUP BY category ORDER BY category ASC"
    cur.execute(query, params)
    if USE_POSTGRES:
        result = [dict(row) for row in cur.fetchall()]
    else:
        cols = [d[0] for d in cur.description]
        result = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return result


@mcp.tool()
def list_expenses(start_date, end_date):
    """List active (non-deleted) expense entries within an inclusive date range."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
    cur.execute(f"""
        SELECT id, date, amount, category, subcategory, note
        FROM expenses
        WHERE date BETWEEN {ph} AND {ph}
        AND deleted_at IS NULL
        ORDER BY id ASC
    """, (start_date, end_date))
    if USE_POSTGRES:
        result = [dict(row) for row in cur.fetchall()]
    else:
        cols = [d[0] for d in cur.description]
        result = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return result


@mcp.tool()
def update_expense(expense_id: int, amount: float = None, category: str = None,
                   date: str = None, note: str = None, subcategory: str = None) -> dict:
    """Update an existing expense by its ID."""
    ph = "%s" if USE_POSTGRES else "?"
    fields = []
    values = []
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
def delete_expense(expense_id: int) -> dict:
    """Soft-delete a single expense by its ID. It is not permanently removed and can be restored with restore_expense."""
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
    """Soft-delete ALL expenses in a given category in one go. Can be fully restored with restore_category."""
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
    """List all soft-deleted expenses. Optionally filter by category to see what was deleted."""
    conn = get_conn()
    ph = "%s" if USE_POSTGRES else "?"
    if USE_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()
    query = """
        SELECT id, date, amount, category, subcategory, note, deleted_at
        FROM expenses
        WHERE deleted_at IS NOT NULL
    """
    params = []
    if category:
        query += f" AND category = {ph}"
        params.append(category)
    query += " ORDER BY deleted_at DESC"
    cur.execute(query, params)
    if USE_POSTGRES:
        result = [dict(row) for row in cur.fetchall()]
    else:
        cols = [d[0] for d in cur.description]
        result = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return result


@mcp.tool()
def restore_expense(expense_id: int) -> dict:
    """Restore a previously soft-deleted expense by its ID. Changes are persisted in the database."""
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
    """Restore all soft-deleted expenses in a given category. Changes are persisted in the database."""
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


@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    """Return the list of valid expense categories and subcategories."""
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
