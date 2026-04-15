# Expense Tracker MCP Server

An AI-powered expense tracking server built with [FastMCP](https://gofastmcp.com), deployable to the cloud and accessible from Claude Desktop and claude.ai web.

## Live Server

The server is deployed and running at:
```
https://expense-tracker-qaqi.onrender.com/mcp
```
No setup needed to test — just connect your MCP client to this URL.

---

## Features

- Add expenses with date, amount, category, subcategory, and notes
- List expenses within a date range
- Summarize expenses by category
- Update existing expenses by ID
- Soft-delete single transactions or entire categories
- Restore deleted transactions (full rollback)
- View deleted transaction history
- Category taxonomy via a JSON resource
- Works locally (SQLite) and in the cloud (PostgreSQL)
- Accessible from Claude Desktop and claude.ai web

---

## Tools

| Tool | Description |
|------|-------------|
| `add_expense` | Add a new expense |
| `list_expenses` | List active expenses in a date range |
| `summarize` | Summarize totals by category |
| `update_expense` | Update an existing expense by ID |
| `delete_expense` | Soft-delete a single expense by ID |
| `delete_category` | Soft-delete all expenses in a category |
| `list_deleted_expenses` | View deleted expenses (optionally filter by category) |
| `restore_expense` | Restore a single deleted expense by ID |
| `restore_category` | Restore all deleted expenses in a category |

## Resources

| Resource | Description |
|----------|-------------|
| `expense://categories` | JSON list of valid categories and subcategories |

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
| Transport (local) | stdio |
| Transport (remote) | streamable-http |

---

## Option 1 — Test the Live Server with MCP Inspector

Anyone can test the deployed server without any local setup beyond Node.js.

### Prerequisites
- [Node.js](https://nodejs.org) v18 or higher

### Steps

**1. Start MCP Inspector**
```bash
npx @modelcontextprotocol/inspector
```

**2. Open the URL it prints**

It will print something like:
```
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=<your-token>
```
Copy and open that full URL in your browser.

**3. Connect to the live server**

In the inspector UI:
- **Transport** → select `Streamable HTTP`
- **URL** → paste `https://expense-tracker-qaqi.onrender.com/mcp`
- Click **Connect**

**4. Explore tools and resources**

- Click the **Tools** tab → all 9 tools will be listed
- Click the **Resources** tab → click `expense://categories` to see all valid categories
- Click any tool → fill in the parameters → click **Run Tool**

### Example: Add an expense
```
Tool: add_expense
date: 2026-04-15
amount: 150
category: food
subcategory: groceries
note: weekly shopping
```

### Example: Summarize expenses
```
Tool: summarize
start_date: 2026-04-01
end_date: 2026-04-30
```

### Example: Delete and restore
```
# Delete a single expense
Tool: delete_expense
expense_id: 5

# See what was deleted
Tool: list_deleted_expenses

# Restore it
Tool: restore_expense
expense_id: 5

# Or delete and restore an entire category
Tool: delete_category    → category: food
Tool: restore_category   → category: food
```

> **Note:** The live server uses a shared PostgreSQL database on Render. Data you add is visible to anyone connecting to the same URL.

---

## Option 2 — Connect via Claude Desktop (Local)

Run the server locally using stdio transport so Claude Desktop can spawn it automatically.

### Prerequisites
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- Python 3.13+

### Steps

**1. Clone the repo**
```bash
git clone https://github.com/desaimann37/expense-tracker.git
cd expense-tracker
```

**2. Add to Claude Desktop config**

File location:
```
Windows: %APPDATA%\Claude\claude_desktop_config.json
macOS:   ~/Library/Application Support/Claude/claude_desktop_config.json
```

Add this entry:
```json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "uv",
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

Replace `C:\\path\\to\\expense-tracker\\main.py` with the actual path to `main.py` on your machine.

**3. Restart Claude Desktop**

The expense tracker tools will appear automatically. Use natural language:
```
"Add an expense of $200 for groceries on 2026-04-15"
"List all my expenses from April 1 to April 30"
"Summarize my expenses for this month"
"Delete all food expenses"
"Restore the food category"
```

---

## Option 3 — Connect via claude.ai Web (Remote)

**1.** Go to [claude.ai](https://claude.ai) → Settings → Connectors → click `+`

**2.** Paste the server URL:
```
https://expense-tracker-qaqi.onrender.com/mcp
```

**3.** Save — all 9 tools load automatically

Now use Claude on the web exactly like Claude Desktop.

---

## Option 4 — Run Your Own Deployment

### Local development

```bash
git clone https://github.com/desaimann37/expense-tracker.git
cd expense-tracker
uv sync
uv run python main.py
```

Server starts at `http://localhost:8000/mcp` using SQLite.

### Deploy to Render (cloud)

1. Fork this repo to your GitHub account
2. Go to [render.com](https://render.com) → New Web Service → connect your fork
3. Set:
   - **Build Command:** `pip install fastmcp psycopg2-binary`
   - **Start Command:** `python main.py`
   - **Plan:** Free
4. Click Deploy

**Add a persistent PostgreSQL database:**

1. Render dashboard → New → PostgreSQL → Free tier → Create
2. Copy the **Internal Database URL**
3. Go to your web service → Environment tab
4. Add environment variable:
   - Key: `DATABASE_URL`
   - Value: your Internal Database URL
5. Save → auto redeploys

---

## Database Schema

```sql
CREATE TABLE expenses (
    id          SERIAL PRIMARY KEY,       -- INTEGER AUTOINCREMENT in SQLite
    date        TEXT NOT NULL,            -- Format: YYYY-MM-DD
    amount      REAL NOT NULL,
    category    TEXT NOT NULL,
    subcategory TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    deleted_at  TEXT DEFAULT NULL         -- NULL = active, timestamp = soft-deleted
);
```

Soft-deleted records are never permanently removed. `list_expenses` and `summarize` automatically exclude them. Use `list_deleted_expenses` to see them and `restore_expense` / `restore_category` to bring them back.

---

## Categories

The server exposes a `expense://categories` resource with 20 top-level categories and subcategories:

`food`, `transport`, `housing`, `utilities`, `health`, `education`, `family_kids`, `entertainment`, `shopping`, `subscriptions`, `personal_care`, `gifts_donations`, `finance_fees`, `business`, `travel`, `home`, `pet`, `taxes`, `investments`, `misc`

When using Claude, it reads this resource automatically to pick the right category when you describe an expense in natural language.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection URL — if not set, SQLite is used |
| `PORT` | Server port (default: 8000, auto-set by Render) |

---

## Render Free Tier Notes

- Web service sleeps after 15 minutes of inactivity
- First request after sleep takes ~30 seconds (cold start)
- PostgreSQL database persists forever
- 750 free hours/month for the web service
