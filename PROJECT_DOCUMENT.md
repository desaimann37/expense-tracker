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

## Step 2 — Database Schema

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
2. URL: `https://<your-app>.onrender.com/mcp`
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
"Add ₹200 for coffee today"
"I spent ₹3500 on groceries — log it under food"
"What did I spend today?"

# Budgets
"Set a ₹8000 monthly budget for food"
"How am I doing on my budget this month?"
"Show all my budgets"

# Recurring
"Set rent as ₹15000 recurring on the 1st of every month"
"Apply my recurring expenses"
"Stop my Netflix recurring"

# Reports & analytics
"Give me a full report for April"
"Show my spending trend for the last 3 months"
"What are my top 5 expenses this month?"
"Break down my food spending into subcategories"

# Search
"Find all Zomato expenses"
"Show expenses over ₹5000 in April"
"Search for anything tagged 'business trip'"

# Delete & restore
"Delete expense #12"
"Delete all my entertainment expenses"
"Show me what I deleted"
"Restore my food expenses"
```

---

*Document prepared for Expense Tracker MCP Server v2 — 21 tools, budgets, recurring expenses, analytics.*
