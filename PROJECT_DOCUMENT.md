# Expense Tracker MCP Server — Project Documentation

## Overview

This project is a **Model Context Protocol (MCP) server** for tracking personal expenses. It exposes nine AI-callable tools and one resource that allow Claude (Desktop or Web) to add, list, summarize, update, delete, and restore expenses stored in a database.

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
├── main.py           # MCP server with all tools and resources
├── categories.json   # Valid expense categories and subcategories
├── pyproject.toml    # Project dependencies
├── Procfile          # Render start command
├── expenses.db       # Local SQLite database (auto-created)
└── .venv/            # Virtual environment
```

---

## Step 1 — Project Setup

### Initialize with uv

```bash
mkdir expense-tracker
cd expense-tracker
uv init
uv add fastmcp psycopg2-binary
```

### pyproject.toml

```toml
[project]
name = "expense-tracker"
version = "0.1.0"
description = "Expense Tracker MCP Server"
requires-python = ">=3.13"
dependencies = [
    "fastmcp>=3.2.3",
    "psycopg2-binary>=2.9.9",
]
```

---

## Step 2 — MCP Server Code

### main.py (Final Version)

```python
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
    """Soft-delete a single expense by its ID. Can be restored with restore_expense."""
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
    """Soft-delete ALL expenses in a given category. Can be restored with restore_category."""
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
    """List all soft-deleted expenses. Optionally filter by category."""
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
    """Restore a previously soft-deleted expense by its ID."""
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
    """Restore all soft-deleted expenses in a given category."""
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
```

---

## Step 3 — Categories Resource

`categories.json` defines 20 top-level categories, each with subcategories. The MCP server exposes this as a resource at `expense://categories`.

Claude reads this resource automatically when you describe an expense in natural language — it picks the matching category and subcategory before calling `add_expense`.

Example categories: `food`, `transport`, `housing`, `utilities`, `health`, `education`, `shopping`, `travel`, `investments`, `misc` (20 total).

---

## Step 4 — Tools and Resources Exposed

### Tools

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `add_expense` | Add a new expense | date, amount, category |
| `list_expenses` | List active expenses in a date range | start_date, end_date |
| `summarize` | Total by category in a date range | start_date, end_date |
| `update_expense` | Update an existing expense by ID | expense_id |
| `delete_expense` | Soft-delete a single expense | expense_id |
| `delete_category` | Soft-delete all expenses in a category | category |
| `list_deleted_expenses` | View deleted expenses | — (optional: category) |
| `restore_expense` | Restore a single deleted expense | expense_id |
| `restore_category` | Restore all deleted expenses in a category | category |

### Resources

| Resource URI | MIME Type | Description |
|--------------|-----------|-------------|
| `expense://categories` | application/json | Valid categories and subcategories |

---

## Step 5 — Local Setup (Claude Desktop)

Claude Desktop spawns the server automatically via stdio — no manual server start needed.

### Claude Desktop Config

File location:
```
Windows: %APPDATA%\Claude\claude_desktop_config.json
macOS:   ~/Library/Application Support/Claude/claude_desktop_config.json
```

```json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "C:\\path\\to\\uv.exe",
      "args": [
        "run",
        "--with",
        "fastmcp",
        "fastmcp",
        "run",
        "C:\\path\\to\\expense-tracker\\main.py"
      ],
      "env": {}
    }
  }
}
```

### How it works locally
```
Claude Desktop
     ↓ stdio (spawns process)
fastmcp run main.py
     ↓
expenses.db (SQLite on local machine)
```

---

## Step 6 — Remote Deployment (Render)

### Why deploy remotely?
- Local setup requires your laptop to be ON
- Remote deployment makes the server accessible 24/7 from any device

### Procfile
```
web: python main.py
```

### Deployment Steps

1. Push code to GitHub:
```bash
git init
git add main.py categories.json pyproject.toml Procfile README.md
git commit -m "Initial expense tracker MCP server"
git remote add origin https://github.com/<username>/expense-tracker.git
git branch -M main
git push -u origin main
```

2. Go to render.com → New Web Service → Connect GitHub repo
3. Set:
   - **Build Command:** `pip install fastmcp psycopg2-binary`
   - **Start Command:** `python main.py`
   - **Plan:** Free
4. Click Deploy

### Add PostgreSQL (Persistent Database)

1. Render dashboard → New → PostgreSQL → Free tier → Create
2. Copy the **Internal Database URL**
3. Go to your web service → Environment tab
4. Add environment variable:
   - Key: `DATABASE_URL`
   - Value: (paste Internal Database URL)
5. Save → auto redeploys

### How it works on Render
```
claude.ai web / any device
     ↓ HTTPS
https://<your-app>.onrender.com/mcp
     ↓
FastMCP (streamable-http transport)
     ↓
PostgreSQL (persistent, free tier)
```

---

## Step 7 — Cloudflare Tunnel (Optional)

Used to expose the local server to the internet without deploying to cloud.

### Install cloudflared (no admin required)
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -o "$HOME/.local/bin/cloudflared.exe"
```

### Create named tunnel
1. Go to Cloudflare Dashboard → Zero Trust → Networks → Tunnels
2. Create tunnel → Name it → Copy the token
3. Add public hostname:
   - Subdomain: `mcp`
   - Domain: your domain
   - Service: `http://localhost:8000`

### Run tunnel
```bash
~/.local/bin/cloudflared.exe tunnel run --token <YOUR_TOKEN>
```

### Run MCP server for tunnel
```bash
cd expense-tracker
uv run python main.py
```

> **Note:** Tunnel requires both the MCP server and cloudflared running simultaneously. Render deployment is preferred for always-on access.

---

## Step 8 — Connecting claude.ai Web

1. Go to claude.ai → Settings → Connectors → `+`
2. Paste your Render URL: `https://<your-app>.onrender.com/mcp`
3. Name it → Save
4. All 9 tools and the categories resource appear automatically

---

## Step 9 — Testing with MCP Inspector

MCP Inspector is a browser-based UI for testing MCP servers interactively without needing Claude.

### Prerequisites
- Node.js v18+

### Steps

**1. Start the inspector**
```bash
npx @modelcontextprotocol/inspector
```

If you get npm cache errors, clear the cache first:
```bash
npx clear-npx-cache
```

**2. Open the printed URL**
```
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=<token>
```

**3. Connect to your server**
- Transport → `Streamable HTTP`
- URL → `https://<your-app>.onrender.com/mcp`
- Click **Connect**

**4. Test tools interactively**
- **Tools tab** → click any tool → fill params → Run Tool
- **Resources tab** → click `expense://categories` → see all valid categories

### Example test flow
```
1. add_expense      → date=2026-04-15, amount=150, category=food, subcategory=groceries
2. list_expenses    → start_date=2026-04-15, end_date=2026-04-15
3. summarize        → start_date=2026-04-01, end_date=2026-04-30
4. delete_expense   → expense_id=<id from step 1>
5. list_deleted_expenses → (no params needed)
6. restore_expense  → expense_id=<same id>
```

---

## Step 10 — Architecture Summary

### Local (Claude Desktop)
```
Claude Desktop ──stdio──► fastmcp run main.py ──► SQLite (expenses.db)
```

### Remote (claude.ai Web / Any Device)
```
claude.ai web ──HTTPS──► Render (main.py) ──► PostgreSQL (persistent)
```

### Tunnel (Optional / Temporary)
```
claude.ai web ──HTTPS──► Cloudflare ──► cloudflared ──► main.py ──► SQLite
```

### MCP Inspector (Testing)
```
Browser ──► Inspector UI ──► Proxy (localhost:6277) ──► MCP Server (Render/local)
```

---

## Step 11 — Database Schema

```sql
CREATE TABLE expenses (
    id          SERIAL PRIMARY KEY,       -- INTEGER AUTOINCREMENT in SQLite
    date        TEXT NOT NULL,            -- Format: YYYY-MM-DD
    amount      REAL NOT NULL,
    category    TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    deleted_at  TEXT DEFAULT NULL         -- NULL = active, ISO timestamp = soft-deleted
);
```

### Soft-delete behaviour
- `delete_expense` / `delete_category` → sets `deleted_at` to current UTC timestamp
- `restore_expense` / `restore_category` → sets `deleted_at` back to NULL
- `list_expenses` and `summarize` always filter `WHERE deleted_at IS NULL`
- `list_deleted_expenses` shows only rows `WHERE deleted_at IS NOT NULL`
- Nothing is ever permanently deleted — full rollback is always possible

---

## Step 12 — Key Decisions & Lessons

| Decision | Reason |
|----------|--------|
| FastMCP over raw MCP SDK | Simpler decorator-based API, less boilerplate |
| stdio for Claude Desktop | Most reliable, no OAuth needed, no networking |
| streamable-http for remote | Required by claude.ai web (newer MCP protocol) |
| PostgreSQL on Render | SQLite resets on every Render restart (ephemeral filesystem) |
| Dual SQLite/PostgreSQL support | Local dev uses SQLite, production uses PostgreSQL — no config change needed |
| Placeholder abstraction (`ph`) | `%s` for PostgreSQL, `?` for SQLite — one codebase works for both |
| Soft-delete over hard-delete | Never lose data — full rollback available via restore tools |
| `deleted_at` timestamp | Records when deletion happened, useful for audit trail |
| categories.json as MCP resource | Claude reads it at runtime to pick correct category — editable without restart |
| Cloudflare Tunnel | Allows testing remote access without deploying to cloud |
| Environment variable for DB URL | Never hardcode credentials in source code |

---

## Render Free Tier Notes

- Web service **sleeps after 15 minutes** of inactivity
- First request after sleep takes ~30 seconds (cold start)
- PostgreSQL database **persists forever** (does not reset)
- 750 free hours/month for web service

---

## Usage Examples

Once connected, use natural language in Claude:

```
"Add an expense of $500 for groceries on 2026-04-15"
"List all my expenses from April 1 to April 30"
"Summarize my expenses for this month"
"Update expense #3, change the amount to $250"
"Delete expense #5"
"Delete all my food expenses"
"Show me what I deleted today"
"Restore all food expenses"
"What expense categories are available?"
```

---

*Document prepared for Expense Tracker MCP Server project.*
