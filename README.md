# Expense Tracker MCP Server

An AI-powered expense tracking server built with [FastMCP](https://gofastmcp.com), deployable to the cloud and accessible from Claude Desktop and claude.ai web.

## Features

- Add expenses with date, amount, category, subcategory, and notes
- List expenses within a date range
- Summarize expenses by category
- Update existing expenses by ID
- Works locally (SQLite) and in the cloud (PostgreSQL)
- Accessible from Claude Desktop and claude.ai web

## Tools

| Tool | Description |
|------|-------------|
| `add_expense` | Add a new expense |
| `list_expenses` | List expenses in a date range |
| `summarize` | Summarize totals by category |
| `update_expense` | Update an existing expense by ID |

## Usage

Once connected to Claude, use natural language:

```
"Add an expense of $200 for Food on 2026-04-14"
"List all my expenses from April 1 to April 30"
"Summarize my expenses for this month"
"Update expense #3, change the amount to $250"
```

## Setup

### Local (Claude Desktop)

Add to your `claude_desktop_config.json`:

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
        "path/to/main.py"
      ],
      "transport": "stdio"
    }
  }
}
```

### Remote (claude.ai web)

The server is deployed on Render. Add it to claude.ai:

1. Go to claude.ai → Settings → Connectors → `+`
2. Paste the server URL: `https://<your-app>.onrender.com/mcp`
3. Save — all 4 tools load automatically

## Tech Stack

- **Framework:** FastMCP 3.2.x
- **Language:** Python 3.13+
- **Local DB:** SQLite
- **Cloud DB:** PostgreSQL (Render free tier)
- **Hosting:** Render
- **Transport:** stdio (local) / streamable-http (remote)

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection URL (set on Render) |
| `PORT` | Server port (auto-set by Render) |

## Local Development

```bash
# Install dependencies
uv sync

# Run locally
uv run python main.py
```

## Deployment

Deployed on [Render](https://render.com) with a free PostgreSQL database for persistent storage.

- **Build command:** `pip install fastmcp psycopg2-binary`
- **Start command:** `python main.py`
- **Environment variable:** `DATABASE_URL` → set to your Render PostgreSQL internal URL
