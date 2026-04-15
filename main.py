from fastmcp import FastMCP
import os
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
                note TEXT DEFAULT ''
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)
    conn.commit()
    cur.close()
    conn.close()


init_db()


@mcp.tool()
def add_expense(date, amount, category, subcategory="", note=""):
    """Add an expense to the database."""
    conn = get_conn()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(
            "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (date, amount, category, subcategory, note)
        )
        row = cur.fetchone()
        expense_id = row[0]
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
    """Summarize expenses by category within an inclusive date range."""
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
    """List expense entries within an inclusive date range."""
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
    cur.execute(f"UPDATE expenses SET {', '.join(fields)} WHERE id = {ph}", values)
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "updated_id": expense_id}


@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    """Return the list of valid expense categories and subcategories."""
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
