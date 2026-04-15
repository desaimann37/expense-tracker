# Expense Tracker MCP Server

An AI-powered expense tracking server built with [FastMCP](https://gofastmcp.com), deployed on Render with PostgreSQL. Connect it to Claude and manage your finances using natural language — no forms, no dashboards, just conversation.

## Live Server

Deploy your own instance on Render (see [Run Your Own Deployment](#run-your-own-deployment)) and connect any MCP client to your server URL:

```
https://<your-app>.onrender.com/mcp
```

---

## What It Can Do

Ask Claude things like:

```
"Add $1500 for groceries today"
"I paid $15000 rent on April 1st, set it as recurring every month"
"Am I on track with my food budget this month?"
"How did I do in April? Give me a full report"
"Show my top 5 expenses this month"
"Search for all Swiggy expenses"
"Delete all my food expenses from last week"
"Show me what I deleted — restore the food ones"
"What's my spending trend over the last 3 months?"
"Set a $5000 monthly budget for food"
"Apply my recurring expenses for this month"
```

---

## Tools (21 total)

### Core
| Tool | Description |
|------|-------------|
| `add_expense` | Add a new expense |
| `list_expenses` | List active expenses in a date range (filter by category/subcategory) |
| `summarize` | Total spending by category or subcategory |
| `update_expense` | Edit an existing expense by ID |
| `search_expenses` | Keyword + amount + date + category search |
| `top_expenses` | Largest individual expenses in a range |

### Soft-Delete & Restore
| Tool | Description |
|------|-------------|
| `delete_expense` | Soft-delete a single expense (restorable) |
| `delete_category` | Soft-delete all expenses in a category at once |
| `list_deleted_expenses` | View deleted expenses with timestamps |
| `restore_expense` | Restore a single deleted expense |
| `restore_category` | Restore all deleted expenses in a category |

### Budgets
| Tool | Description |
|------|-------------|
| `set_budget` | Set a monthly/weekly/yearly spending limit for a category |
| `get_budget_status` | Compare actual spending vs budget with % used and status |
| `list_budgets` | View all configured budgets |
| `delete_budget` | Remove a budget |

### Recurring Expenses
| Tool | Description |
|------|-------------|
| `add_recurring` | Create a recurring expense template (rent, Netflix, EMI, etc.) |
| `list_recurring` | View all active recurring templates |
| `apply_recurring` | Auto-generate missing expense entries for all recurring templates (idempotent) |
| `delete_recurring` | Stop a recurring expense template |

### Analytics
| Tool | Description |
|------|-------------|
| `monthly_report` | Full monthly summary: total, by category, top 5, budget alerts, daily totals |
| `spending_trend` | Month-over-month spending with % change for last N months |

## Resources
| Resource | Description |
|----------|-------------|
| `expense://categories` | JSON list of 20 valid categories and subcategories |

---

## Test with MCP Inspector

Anyone can test the live server interactively — no Claude needed, just Node.js.

### Steps

**1. Start MCP Inspector**
```bash
npx @modelcontextprotocol/inspector
```

If you get cache errors on Windows:
```bash
npx clear-npx-cache
npx @modelcontextprotocol/inspector
```

**2. Open the URL printed in terminal**
```
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=<your-token>
```

**3. Connect to the live server**
- Transport → `Streamable HTTP`
- URL → `https://<your-app>.onrender.com/mcp`
- Click **Connect**

**4. Test any tool from the browser UI**

Example flow:
```
set_budget        → category=food, amount=5000, period=monthly
add_recurring     → name=Rent, amount=15000, category=housing, frequency=monthly, start_date=2026-04-01
apply_recurring   → (no params — auto-generates entries for today)
get_budget_status → period_start=2026-04-01, period_end=2026-04-30
monthly_report    → year=2026, month=4
spending_trend    → months=3
```

---

## Connect to Claude Desktop (Local)

**1. Clone the repo**
```bash
git clone https://github.com/desaimann37/expense-tracker.git
cd expense-tracker
```

**2. Add to Claude Desktop config**

File location:
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "uv",
      "args": [
        "run", "--with", "fastmcp", "fastmcp", "run",
        "C:\\path\\to\\expense-tracker\\main.py"
      ],
      "env": {}
    }
  }
}
```

**3. Restart Claude Desktop** — all 21 tools appear automatically.

---

## Connect to claude.ai Web (Remote)

1. Go to [claude.ai](https://claude.ai) → Settings → Connectors → `+`
2. Paste your deployed server URL: `https://<your-app>.onrender.com/mcp`
3. Save — all tools load automatically

---

## Run Your Own Deployment

### Local dev
```bash
git clone https://github.com/desaimann37/expense-tracker.git
cd expense-tracker
uv sync
uv run python main.py
# Server at http://localhost:8000/mcp using SQLite
```

### Deploy to Render
1. Fork this repo → go to [render.com](https://render.com) → New Web Service → connect fork
2. **Build command:** `pip install fastmcp psycopg2-binary`
3. **Start command:** `python main.py`
4. Create a free PostgreSQL database on Render
5. Add env var `DATABASE_URL` → your PostgreSQL internal URL
6. Deploy — database tables and columns are auto-created on startup

---

## Database Schema

```sql
CREATE TABLE expenses (
    id          SERIAL PRIMARY KEY,
    date        TEXT NOT NULL,            -- YYYY-MM-DD
    amount      REAL NOT NULL,
    category    TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    deleted_at  TEXT DEFAULT NULL,        -- NULL = active, ISO timestamp = soft-deleted
    recurring_id INTEGER DEFAULT NULL     -- links to recurring_expenses template
);

CREATE TABLE budgets (
    id         SERIAL PRIMARY KEY,
    category   TEXT NOT NULL,
    amount     REAL NOT NULL,
    period     TEXT NOT NULL DEFAULT 'monthly',
    created_at TEXT NOT NULL,
    UNIQUE(category, period)
);

CREATE TABLE recurring_expenses (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    amount       REAL NOT NULL,
    category     TEXT NOT NULL,
    subcategory  TEXT DEFAULT '',
    note         TEXT DEFAULT '',
    frequency    TEXT NOT NULL,           -- daily | weekly | monthly | yearly
    start_date   TEXT NOT NULL,           -- first occurrence date
    last_applied TEXT DEFAULT NULL,
    active       INTEGER NOT NULL DEFAULT 1
);
```

All tables and columns are **auto-created and migrated** on server startup — no manual SQL needed.

---

## Categories

The server exposes `expense://categories` with 20 top-level categories:

`food` · `transport` · `housing` · `utilities` · `health` · `education` · `family_kids` · `entertainment` · `shopping` · `subscriptions` · `personal_care` · `gifts_donations` · `finance_fees` · `business` · `travel` · `home` · `pet` · `taxes` · `investments` · `misc`

Claude reads this resource automatically to pick the right category from natural language descriptions.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL URL — if unset, SQLite is used locally |
| `PORT` | Server port (default 8000, auto-set by Render) |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| MCP Framework | FastMCP 3.2.x |
| Language | Python 3.13+ |
| Package Manager | uv |
| Local DB | SQLite (auto) |
| Cloud DB | PostgreSQL (Render free tier) |
| Hosting | Render |
| Transport (local) | stdio |
| Transport (remote) | streamable-http |

---

## Render Free Tier Notes

- Web service sleeps after 15 min of inactivity — first request takes ~30s (cold start)
- PostgreSQL persists forever
- 750 free hours/month
