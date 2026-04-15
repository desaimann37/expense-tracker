# Expense Tracker MCP Server

A personal finance assistant powered by AI. Built with [FastMCP](https://gofastmcp.com) and deployed on Render with PostgreSQL. Connect it to Claude and track every dollar you spend — groceries, rent, subscriptions, dining out — all through natural conversation. No spreadsheets, no manual entry forms, just tell Claude what you spent.

---

## What It Can Do

Once connected, just talk to Claude like you normally would:

```
"I spent $85 on groceries at Whole Foods today"
"Log $1,200 rent for April 1st and set it as a recurring monthly expense"
"How much have I spent on food this month?"
"Am I over budget anywhere?"
"Give me a full breakdown of my April spending"
"What were my 5 biggest expenses last month?"
"Find all my Uber and rideshare charges"
"I got a refund — delete that $45 Amazon order from last week"
"Show me everything I deleted this month, then restore the grocery ones"
"How does my spending this month compare to the last 3 months?"
"Set a $600 monthly budget for groceries"
"Apply all my recurring bills for this month"
```

Claude reads your expense categories automatically and maps plain English to the right category — say "coffee run" and it logs under `food → coffee_tea`, say "Uber to airport" and it goes under `transport → cab_ride_hailing`.

---

## Features

### Track Any Expense
Add expenses with a date, amount, category, subcategory, and optional note. List and filter by date range, category, or keyword.

### Monthly Budgets
Set spending limits per category (food, transport, entertainment, etc.). Get real-time status showing how much you've spent, how much remains, and whether you're on track, near the limit, or over budget.

### Recurring Bills — Set Once, Forget Forever
Add templates for fixed monthly costs like rent, Netflix, gym membership, or phone bill. Call `apply_recurring` once and every bill gets logged automatically — no manual entry needed each month. Safe to call multiple times; never double-charges.

### Smart Search
Find expenses by keyword across notes, category, and subcategory. Filter by date range, amount range, or category. Useful for finding all rideshare charges, all dining-out entries, or anything above a certain amount.

### Safe Delete & Full Restore
Nothing is ever permanently deleted. Soft-delete a single transaction or an entire category at once. View deleted items with their deletion timestamp. Restore any of them individually or by category — all changes persist in the database.

### Analytics & Reports
- **Monthly report** — total spent, category breakdown with % of budget, top 5 transactions, budget alerts, daily spending totals
- **Spending trend** — month-over-month totals with % change for the last N months
- **Subcategory drill-down** — break food into groceries vs dining out vs delivery

---

## Tools (21 total)

### Core Expense Management
| Tool | What it does |
|------|-------------|
| `add_expense` | Log a new expense with date, amount, category, subcategory, and note |
| `list_expenses` | List all active expenses in a date range — filter by category or subcategory |
| `summarize` | Total spending grouped by category; set `group_by_subcategory=true` to drill deeper |
| `update_expense` | Correct an existing expense — change amount, date, category, or note |
| `search_expenses` | Search by keyword, date range, category, min/max amount |
| `top_expenses` | See your N largest individual transactions in any date range |

### Safe Delete & Restore
| Tool | What it does |
|------|-------------|
| `delete_expense` | Soft-delete one transaction by ID — fully restorable |
| `delete_category` | Soft-delete every transaction in a category at once |
| `list_deleted_expenses` | View deleted transactions with deletion timestamps |
| `restore_expense` | Bring back a single deleted transaction |
| `restore_category` | Bring back all deleted transactions in a category |

### Budget Management
| Tool | What it does |
|------|-------------|
| `set_budget` | Set a monthly, weekly, or yearly spending cap for any category |
| `get_budget_status` | See spent vs budget, amount remaining, and % used for each category |
| `list_budgets` | View all your configured spending limits |
| `delete_budget` | Remove a budget for a category |

### Recurring Bills
| Tool | What it does |
|------|-------------|
| `add_recurring` | Create a recurring template for rent, subscriptions, EMIs, utilities |
| `list_recurring` | View all active recurring templates and when they were last applied |
| `apply_recurring` | Auto-generate all missing bill entries up to today — idempotent, safe to run anytime |
| `delete_recurring` | Cancel a recurring template (stops future entries, keeps past ones) |

### Analytics
| Tool | What it does |
|------|-------------|
| `monthly_report` | Full month summary: total, by-category with %, top 5 transactions, budget alerts, daily totals |
| `spending_trend` | Month-over-month spending totals with % change for the last N months |

### Resource
| Resource | What it returns |
|----------|----------------|
| `expense://categories` | Full list of 20 categories and their subcategories — Claude uses this to map your natural language to the right category |

---

## Expense Categories

20 built-in top-level categories, each with subcategories:

| Category | Subcategories (examples) |
|----------|--------------------------|
| `food` | groceries, dining_out, delivery_fees, coffee_tea, snacks |
| `transport` | fuel, cab_ride_hailing, public_transport, parking, tolls |
| `housing` | rent, maintenance_hoa, repairs_service, furnishing |
| `utilities` | electricity, internet_broadband, mobile_phone, water, gas |
| `health` | medicines, doctor_consultation, fitness_gym, insurance_health |
| `education` | courses, books, online_subscriptions, workshops |
| `entertainment` | movies_events, streaming_subscriptions, games_apps, outing |
| `shopping` | clothing, footwear, electronics_gadgets, home_decor |
| `subscriptions` | saas_tools, cloud_ai, music_video, storage_backup |
| `travel` | flights, hotels, train_bus, local_transport, food_travel |
| `investments` | mutual_funds, stocks, fd_rd, crypto, gold |
| `misc` | uncategorized, other |
| *(+ 8 more)* | family_kids, personal_care, gifts_donations, finance_fees, business, home, pet, taxes |

---

## Example Conversation

Here's what a real session with Claude looks like after connecting:

> **You:** I paid $1,800 rent on April 1st — set it as a recurring monthly expense starting today. Also set a $500 budget for groceries this month.
>
> **Claude:** Done. I've set your rent as a recurring monthly expense of $1,800 starting April 1st and logged it for this month. Your grocery budget is set at $500 for April. You have the full $500 remaining.

> **You:** I spent $120 at Trader Joe's today and $45 at Starbucks this week.
>
> **Claude:** Logged both. Trader Joe's $120 goes under food → groceries (April 15), Starbucks $45 under food → coffee_tea (April 15). You've now used $165 of your $500 grocery budget — 33% used, $335 remaining. You're on track.

> **You:** How did I do in April overall?
>
> **Claude:** April total: $2,142. Housing (rent) is $1,800 — 84% of your spend, which is expected. Food is $341 across groceries, coffee, and one delivery order. You came in $159 under your grocery budget. No categories exceeded their limits this month.

---

## Setup

### Option 1 — Connect to claude.ai Web

1. Deploy your own instance (see below)
2. Go to [claude.ai](https://claude.ai) → Settings → Connectors → `+`
3. Paste your server URL: `https://<your-app>.onrender.com/mcp`
4. Save — all 21 tools load automatically

### Option 2 — Connect to Claude Desktop (Local)

**1. Clone and set up**
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

**3. Restart Claude Desktop** — all 21 tools appear automatically and Claude can start tracking your expenses.

### Option 3 — Test with MCP Inspector (No Claude Required)

Useful for verifying your deployment works before connecting to Claude.

**1. Start the inspector**
```bash
npx @modelcontextprotocol/inspector
```

If you see cache errors on Windows:
```bash
npx clear-npx-cache
npx @modelcontextprotocol/inspector
```

**2. Open the URL printed in terminal**
```
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=<your-token>
```

**3. Connect**
- Transport → `Streamable HTTP`
- URL → `https://<your-app>.onrender.com/mcp`
- Click **Connect**

**4. Try this test sequence**
```
1. set_budget          → category: food, amount: 500, period: monthly
2. add_recurring       → name: Rent, amount: 1800, category: housing,
                         frequency: monthly, start_date: 2026-04-01
3. apply_recurring     → (no params needed — runs for today)
4. add_expense         → date: 2026-04-10, amount: 120, category: food,
                         subcategory: groceries, note: Trader Joe's run
5. get_budget_status   → period_start: 2026-04-01, period_end: 2026-04-30
6. monthly_report      → year: 2026, month: 4
7. spending_trend      → months: 3
8. search_expenses     → keyword: groceries
```

---

## Deploy Your Own

### Local Development
```bash
git clone https://github.com/desaimann37/expense-tracker.git
cd expense-tracker
uv sync
uv run python main.py
# Runs at http://localhost:8000/mcp — uses SQLite automatically
```

### Deploy to Render (Free, Persistent)

1. Fork this repo to your GitHub account
2. Go to [render.com](https://render.com) → New Web Service → connect your fork
3. Set:
   - **Build command:** `pip install fastmcp psycopg2-binary`
   - **Start command:** `python main.py`
   - **Plan:** Free
4. Create a free PostgreSQL database: Render → New → PostgreSQL → Free tier
5. Copy the **Internal Database URL** → add as env var `DATABASE_URL` on your web service
6. Save and redeploy — all tables are created automatically on startup

> **Why PostgreSQL?** Render's free tier has an ephemeral filesystem — SQLite data would reset on every restart. PostgreSQL on Render persists forever.

---

## Database

Three tables, all auto-created on first run. No migrations to run manually.

```
expenses          → every transaction (active and soft-deleted)
budgets           → per-category spending limits
recurring_expenses → templates for bills that repeat automatically
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection URL — if not set, SQLite is used |
| `PORT` | Server port (default: 8000, auto-set by Render) |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| MCP Framework | FastMCP 3.2.x |
| Language | Python 3.13+ |
| Package Manager | uv |
| Local DB | SQLite |
| Cloud DB | PostgreSQL (Render) |
| Hosting | Render (free tier) |
| Transport (local) | stdio |
| Transport (remote) | streamable-http |

---

## Render Free Tier Notes

- Web service sleeps after 15 min of inactivity — first request after sleep takes ~30s
- PostgreSQL database persists forever and never resets
- 750 free hours/month (enough to run continuously)
