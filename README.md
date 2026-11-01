# Expense Tracker MCP Server 💰

An asynchronous Expense Tracker built using **Python, FastMCP, and SQLite**. It allows AI assistants to manage expenses, track budgets, and analyse spending through MCP tools.

## 🚀 Features

- Add, update, delete, and view expenses.
- Natural-language expense entry.
- Monthly expense summaries.
- Category-wise spending analysis.
- Budget creation and tracking.
- Automated expense insights.
- Asynchronous database operations using `aiosqlite`.
- HTTP-based remote MCP connectivity.

## 🛠️ Tech Stack

- Python
- FastMCP
- SQLite
- aiosqlite
- Uvicorn
- uv

## 🌐 Live MCP Endpoint

**Remote Server:**  
https://grumpy-maroon-chameleon.fastmcp.app/mcp

## ⚙️ Run Locally

Install dependencies:

```bash
uv add fastmcp aiosqlite
```

Start the server:

```bash
uv run python main.py
```

Local MCP endpoint:

```text
http://localhost:8000/mcp
```

## 📁 Project Structure

```text
expense-tracker-mcp/
├── main.py
├── expenses.db
├── categories.json
├── seed_data.py
├── pyproject.toml
└── README.md
```

## 🔮 Future Improvements

- Multi-user authentication and data isolation.
- PostgreSQL integration.
- Receipt scanning using OCR.
- Voice-based expense tracking.
- Advanced financial analytics.
- Secure production deployment.

**Built with Python, FastMCP, and SQLite.**