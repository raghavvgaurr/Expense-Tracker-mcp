
import asyncio
import json
import math
import os
import re

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import aiosqlite
from fastmcp import FastMCP


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "expenses.db"
CATEGORY_FILE = BASE_DIR / "categories.json"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

mcp = FastMCP("ExpenseTracker")


# =========================================================
# DATABASE CONNECTION
# =========================================================

@asynccontextmanager
async def get_db():
    """
    Open an asynchronous SQLite connection.

    Each request gets its own connection. WAL mode and
    busy_timeout are configured during database startup.
    """
    conn = await aiosqlite.connect(
        str(DB_PATH),
        timeout=10
    )

    conn.row_factory = aiosqlite.Row

    try:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("PRAGMA busy_timeout = 10000")

        yield conn

    finally:
        await conn.close()


async def init_db():
    """Initialize database tables without deleting existing data."""

    async with get_db() as conn:

        await conn.execute("PRAGMA journal_mode = WAL")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                month TEXT NOT NULL,
                amount REAL NOT NULL,
                UNIQUE(category, month)
            )
        """)

        await conn.commit()


# =========================================================
# CATEGORY RESOURCE
# =========================================================

def load_categories():
    """Load standardized categories from categories.json."""

    if not CATEGORY_FILE.exists():
        raise FileNotFoundError(
            f"Category file not found: {CATEGORY_FILE}"
        )

    with open(CATEGORY_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data.get("categories"), list):
        raise ValueError(
            "categories.json must contain a categories list."
        )

    return data


@mcp.resource("expense://categories")
def get_expense_categories():
    """
    Read-only resource containing expense categories
    and their supported subcategories.
    """
    return json.dumps(load_categories(), indent=2)


# =========================================================
# CATEGORY NORMALIZATION
# =========================================================

CATEGORY_ALIASES = {
    "food": "Food",
    "restaurant": "Food",
    "restaurants": "Food",
    "dining": "Food",
    "eating out": "Food",

    "grocery": "Groceries",
    "groceries": "Groceries",
    "supermarket": "Groceries",

    "transport": "Transport",
    "transportation": "Transport",
    "cab": "Transport",
    "taxi": "Transport",
    "uber": "Transport",
    "ola": "Transport",

    "shopping": "Shopping",
    "clothes": "Shopping",
    "clothing": "Shopping",

    "entertainment": "Entertainment",
    "movies": "Entertainment",
    "movie": "Entertainment",
    "subscription": "Entertainment",

    "health": "Health",
    "medical": "Health",
    "medicine": "Health",

    "education": "Education",
    "college": "Education",
    "courses": "Education",

    "bills": "Bills",
    "utilities": "Bills",
    "electricity": "Bills",
    "rent": "Bills",

    "personal care": "Personal Care",
    "grooming": "Personal Care",

    "travel": "Travel",
    "finance": "Finance",
    "other": "Other"
}


SUBCATEGORY_ALIASES = {
    "uber": ("Transport", "Cab"),
    "ola": ("Transport", "Cab"),
    "taxi": ("Transport", "Cab"),
    "cab": ("Transport", "Cab"),
    "metro": ("Transport", "Metro"),
    "bus": ("Transport", "Bus"),
    "train": ("Transport", "Train"),
    "petrol": ("Transport", "Fuel"),
    "diesel": ("Transport", "Fuel"),
    "fuel": ("Transport", "Fuel"),
    "parking": ("Transport", "Parking"),

    "milk": ("Groceries", "Dairy"),
    "vegetables": ("Groceries", "Vegetables"),
    "fruits": ("Groceries", "Fruits"),

    "pizza": ("Food", "Fast Food"),
    "burger": ("Food", "Fast Food"),
    "coffee": ("Food", "Beverages"),
    "tea": ("Food", "Beverages"),
    "swiggy": ("Food", "Food Delivery"),
    "zomato": ("Food", "Food Delivery"),

    "netflix": ("Entertainment", "Subscriptions"),
    "hotstar": ("Entertainment", "Subscriptions"),
    "prime video": ("Entertainment", "Subscriptions"),

    "electricity": ("Bills", "Electricity"),
    "water bill": ("Bills", "Water"),
    "internet": ("Bills", "Internet"),
    "mobile recharge": ("Bills", "Mobile Recharge"),

    "medicine": ("Health", "Medicines"),
    "pharmacy": ("Health", "Medicines"),
    "doctor": ("Health", "Doctor Consultation"),

    "books": ("Education", "Books"),
    "course": ("Education", "Courses"),

    "clothes": ("Shopping", "Clothing"),
    "shoes": ("Shopping", "Footwear")
}


def normalize_category(category, subcategory=""):
    """
    Map common category variations to canonical categories.

    Unknown categories become Other / Uncategorized.
    """

    taxonomy = load_categories()

    raw_category = str(category).strip().lower()
    raw_subcategory = str(subcategory).strip().lower()

    # Recognize a known merchant or expense keyword.
    if raw_category in SUBCATEGORY_ALIASES:
        return SUBCATEGORY_ALIASES[raw_category]

    # Match category aliases.
    canonical_category = CATEGORY_ALIASES.get(raw_category)

    # Match canonical category names from the JSON resource.
    if not canonical_category:
        for item in taxonomy["categories"]:
            if item["category"].lower() == raw_category:
                canonical_category = item["category"]
                break

    if not canonical_category:
        return "Other", "Uncategorized"

    # Find allowed subcategories.
    allowed = []

    for item in taxonomy["categories"]:
        if item["category"] == canonical_category:
            allowed = item["subcategories"]
            break

    canonical_subcategory = ""

    if raw_subcategory:
        # Check subcategory aliases.
        alias_result = SUBCATEGORY_ALIASES.get(raw_subcategory)

        if alias_result:
            alias_category, alias_subcategory = alias_result

            if alias_category == canonical_category:
                canonical_subcategory = alias_subcategory

        # Check exact subcategory names.
        if not canonical_subcategory:
            for item in allowed:
                if item.lower() == raw_subcategory:
                    canonical_subcategory = item
                    break

        if not canonical_subcategory:
            canonical_subcategory = "Uncategorized"

    return canonical_category, canonical_subcategory


# =========================================================
# VALIDATION HELPERS
# =========================================================

def validate_amount(amount):
    try:
        amount = float(amount)
    except (ValueError, TypeError):
        raise ValueError("Amount must be a valid number.")

    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("Amount must be a positive number.")

    return round(amount, 2)


def validate_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ValueError("Date must use YYYY-MM-DD format.")


def validate_month(value):
    try:
        return datetime.strptime(
            value, "%Y-%m"
        ).strftime("%Y-%m")
    except (ValueError, TypeError):
        raise ValueError("Month must use YYYY-MM format.")


def validate_category(category):
    if not isinstance(category, str) or not category.strip():
        raise ValueError("Category cannot be empty.")

    return category.strip()


def expense_rows(rows):
    return [dict(row) for row in rows]


def parse_natural_date(text):
    text = text.lower()

    if "day before yesterday" in text:
        return (
            date.today() - timedelta(days=2)
        ).isoformat()

    if "yesterday" in text:
        return (
            date.today() - timedelta(days=1)
        ).isoformat()

    if "today" in text:
        return date.today().isoformat()

    match = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)

    if match:
        return validate_date(match.group())

    return date.today().isoformat()


# =========================================================
# TOOL 1: ADD EXPENSE
# =========================================================

@mcp.tool
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = ""
):
    """
    Add an expense to the database.

    Use the expense://categories resource for the
    standardized category and subcategory taxonomy.
    """

    expense_date = validate_date(date)
    expense_amount = validate_amount(amount)

    category, subcategory = normalize_category(
        validate_category(category),
        subcategory
    )

    async with get_db() as conn:

        cursor = await conn.execute("""
            INSERT INTO expenses
            (date, amount, category, subcategory, note)
            VALUES (?, ?, ?, ?, ?)
        """, (
            expense_date,
            expense_amount,
            category,
            subcategory,
            note.strip()
        ))

        await conn.commit()

        return {
            "status": "success",
            "message": "Expense added successfully.",
            "expense_id": cursor.lastrowid,
            "date": expense_date,
            "amount": expense_amount,
            "category": category,
            "subcategory": subcategory
        }


# =========================================================
# TOOL 2: QUICK NATURAL LANGUAGE EXPENSE
# =========================================================

@mcp.tool
async def quick_add_expense(utterance: str):
    """
    Add an expense from natural-language text.

    Examples:
    - I spent 250 rupees on groceries today.
    - Paid 120 for coffee yesterday.
    - Spent ₹500 on Uber.
    - I bought milk for 60 rupees.

    Ask the user for clarification if the amount or
    category cannot be confidently identified.
    """

    text = utterance.strip()
    lower = text.lower()

    if not text:
        return {
            "status": "needs_clarification",
            "message": "Please describe your expense."
        }

    # Detect amount in common Indian currency formats.
    amount_match = re.search(
        r"(?:₹|rs\.?|rupees?)\s*([\d,]+(?:\.\d{1,2})?)"
        r"|([\d,]+(?:\.\d{1,2})?)\s*(?:rupees?|rs\.?)",
        lower
    )

    # Also support: "spent 250 on food".
    if not amount_match:
        amount_match = re.search(
            r"\b(?:spent|paid|bought|cost)\s+"
            r"(?:₹|rs\.?\s*)?([\d,]+(?:\.\d{1,2})?)\b",
            lower
        )

    if not amount_match:
        return {
            "status": "needs_clarification",
            "message": "What was the expense amount?"
        }

    amount_text = next(
        group for group in amount_match.groups()
        if group is not None
    )

    amount = validate_amount(
        amount_text.replace(",", "")
    )

    matched_category = None
    matched_subcategory = ""

    # Match specific aliases first.
    for keyword in sorted(
        SUBCATEGORY_ALIASES,
        key=len,
        reverse=True
    ):
        if re.search(
            r"\b" + re.escape(keyword) + r"\b",
            lower
        ):
            matched_category, matched_subcategory = (
                SUBCATEGORY_ALIASES[keyword]
            )
            break

    # Otherwise match a general category.
    if not matched_category:
        for alias in sorted(
            CATEGORY_ALIASES,
            key=len,
            reverse=True
        ):
            if re.search(
                r"\b" + re.escape(alias) + r"\b",
                lower
            ):
                matched_category = CATEGORY_ALIASES[alias]
                break

    if not matched_category:
        return {
            "status": "needs_clarification",
            "message": (
                "I found the amount but could not identify "
                "the category. Which category should I use?"
            ),
            "detected_amount": amount
        }

    expense_date = parse_natural_date(text)

    result = await add_expense(
        date=expense_date,
        amount=amount,
        category=matched_category,
        subcategory=matched_subcategory,
        note=text
    )

    return {
        **result,
        "original_input": text,
        "parsed_date": expense_date
    }


# =========================================================
# TOOL 3: LIST EXPENSES
# =========================================================

@mcp.tool
async def list_expenses(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100
):
    """List expenses with optional date and category filters."""

    if not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000.")

    conditions = []
    params = []

    if start_date:
        conditions.append("date >= ?")
        params.append(validate_date(start_date))

    if end_date:
        conditions.append("date <= ?")
        params.append(validate_date(end_date))

    if category:
        canonical, _ = normalize_category(category)

        conditions.append("LOWER(category) = LOWER(?)")
        params.append(canonical)

    where = (
        " WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    async with get_db() as conn:

        cursor = await conn.execute(f"""
            SELECT *
            FROM expenses
            {where}
            ORDER BY date DESC, id DESC
            LIMIT ?
        """, (*params, limit))

        rows = await cursor.fetchall()

        return expense_rows(rows)


# =========================================================
# TOOL 4: UPDATE EXPENSE
# =========================================================

@mcp.tool
async def update_expense(
    expense_id: int,
    date: Optional[str] = None,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    note: Optional[str] = None
):
    """Update selected fields of an existing expense."""

    if expense_id <= 0:
        raise ValueError("Expense ID must be positive.")

    updates = {}

    if date is not None:
        updates["date"] = validate_date(date)

    if amount is not None:
        updates["amount"] = validate_amount(amount)

    if category is not None:
        canonical, canonical_subcategory = normalize_category(
            validate_category(category),
            subcategory or ""
        )

        updates["category"] = canonical

        if subcategory is None:
            updates["subcategory"] = canonical_subcategory

    if subcategory is not None:
        updates["subcategory"] = subcategory.strip()

    if note is not None:
        updates["note"] = note.strip()

    if not updates:
        return {
            "status": "error",
            "message": "No fields supplied."
        }

    columns = ", ".join(
        f"{column} = ?" for column in updates
    )

    async with get_db() as conn:

        cursor = await conn.execute(
            f"UPDATE expenses SET {columns} WHERE id = ?",
            (*updates.values(), expense_id)
        )

        await conn.commit()

        if cursor.rowcount == 0:
            return {
                "status": "not_found",
                "expense_id": expense_id
            }

        return {
            "status": "success",
            "expense_id": expense_id,
            "updated_fields": list(updates)
        }


# =========================================================
# TOOL 5: DELETE EXPENSE
# =========================================================

@mcp.tool
async def delete_expense(expense_id: int):
    """
    Delete an expense by ID.

    The assistant should obtain user confirmation
    before calling this destructive tool.
    """

    if expense_id <= 0:
        raise ValueError("Expense ID must be positive.")

    async with get_db() as conn:

        cursor = await conn.execute(
            "DELETE FROM expenses WHERE id = ?",
            (expense_id,)
        )

        await conn.commit()

        if cursor.rowcount == 0:
            return {
                "status": "not_found",
                "expense_id": expense_id
            }

        return {
            "status": "success",
            "message": "Expense deleted.",
            "expense_id": expense_id
        }


# =========================================================
# TOOL 6: MONTHLY SUMMARY
# =========================================================

@mcp.tool
async def get_monthly_summary(
    month: Optional[str] = None
):
    """Get monthly spending, transaction count and average."""

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    async with get_db() as conn:

        cursor = await conn.execute("""
            SELECT
                COUNT(*) AS transactions,
                COALESCE(SUM(amount), 0) AS total,
                COALESCE(AVG(amount), 0) AS average
            FROM expenses
            WHERE substr(date, 1, 7) = ?
        """, (month,))

        result = await cursor.fetchone()

        cursor = await conn.execute("""
            SELECT
                category,
                SUM(amount) AS total
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (month,))

        categories = await cursor.fetchall()

        return {
            "month": month,
            "total_spending": round(result["total"], 2),
            "transactions": result["transactions"],
            "average_expense": round(result["average"], 2),
            "category_breakdown": expense_rows(categories)
        }


# =========================================================
# TOOL 7: CATEGORY ANALYSIS
# =========================================================

@mcp.tool
async def category_analysis(
    month: Optional[str] = None
):
    """Analyze spending distribution by category."""

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    async with get_db() as conn:

        cursor = await conn.execute("""
            SELECT
                category,
                COUNT(*) AS transactions,
                SUM(amount) AS total,
                AVG(amount) AS average
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (month,))

        rows = await cursor.fetchall()

        total = sum(row["total"] for row in rows)

        result = []

        for row in rows:
            item = dict(row)

            item["total"] = round(item["total"], 2)
            item["average"] = round(item["average"], 2)

            item["percentage"] = (
                round(item["total"] / total * 100, 2)
                if total else 0
            )

            result.append(item)

        return {
            "month": month,
            "total_spending": round(total, 2),
            "categories": result
        }


# =========================================================
# TOOL 8: SET MONTHLY BUDGET
# =========================================================

@mcp.tool
async def set_budget(
    category: str,
    amount: float,
    month: Optional[str] = None
):
    """Create or update a monthly category budget."""

    category, _ = normalize_category(
        validate_category(category)
    )

    amount = validate_amount(amount)

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    async with get_db() as conn:

        await conn.execute("""
            INSERT INTO budgets (category, month, amount)
            VALUES (?, ?, ?)
            ON CONFLICT(category, month)
            DO UPDATE SET amount = excluded.amount
        """, (category, month, amount))

        await conn.commit()

        return {
            "status": "success",
            "category": category,
            "month": month,
            "budget": amount
        }


# =========================================================
# TOOL 9: BUDGET TRACKER
# =========================================================

@mcp.tool
async def budget_tracker(
    month: Optional[str] = None
):
    """Compare monthly category spending against budgets."""

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    async with get_db() as conn:

        cursor = await conn.execute("""
            SELECT category, amount
            FROM budgets
            WHERE month = ?
        """, (month,))

        budgets = await cursor.fetchall()

        results = []

        for budget in budgets:

            cursor = await conn.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM expenses
                WHERE substr(date, 1, 7) = ?
                AND LOWER(category) = LOWER(?)
            """, (month, budget["category"]))

            spent = (await cursor.fetchone())[0]

            budget_amount = budget["amount"]
            remaining = budget_amount - spent

            percentage_used = (
                spent / budget_amount * 100
                if budget_amount > 0 else 0
            )

            if remaining < 0:
                status = "Over budget"
            elif percentage_used >= 80:
                status = "Budget exceeded 80%"
            else:
                status = "Within budget"

            results.append({
                "category": budget["category"],
                "budget": round(budget_amount, 2),
                "spent": round(spent, 2),
                "remaining": round(remaining, 2),
                "percentage_used": round(percentage_used, 2),
                "status": status
            })

        return {
            "month": month,
            "budgets": results
        }


# =========================================================
# TOOL 10: EXPENSE INSIGHTS
# =========================================================

@mcp.tool
async def expense_insights(
    month: Optional[str] = None
):
    """
    Generate rule-based insights from expense history.

    This calculates spending patterns. It does not use
    a separate machine-learning model.
    """

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    async with get_db() as conn:

        cursor = await conn.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE substr(date, 1, 7) = ?
        """, (month,))

        total = (await cursor.fetchone())[0]

        cursor = await conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (month,))

        categories = await cursor.fetchall()

        cursor = await conn.execute("""
            SELECT date, SUM(amount) AS total
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY date
            ORDER BY total DESC
            LIMIT 1
        """, (month,))

        daily = await cursor.fetchone()

        insights = []

        if total == 0:
            insights.append(
                "No expenses recorded for this month yet."
            )
        else:
            insights.append(
                f"Your total spending for {month} "
                f"is ₹{total:.2f}."
            )

        if categories and total > 0:
            top = categories[0]
            percentage = top["total"] / total * 100

            insights.append(
                f"Your highest spending category is "
                f"{top['category']} at ₹{top['total']:.2f}, "
                f"which is {percentage:.1f}% of your spending."
            )

        if daily:
            insights.append(
                f"Your highest spending day was "
                f"{daily['date']} with ₹{daily['total']:.2f} spent."
            )

        return {
            "month": month,
            "total_spending": round(total, 2),
            "insights": insights
        }


# =========================================================
# SERVER STARTUP
# =========================================================

async def main():
    await init_db()

    print("ExpenseTracker MCP server is starting...")
    print(f"Host: {HOST}")
    print(f"Port: {PORT}")
    print(f"MCP endpoint: http://localhost:{PORT}/mcp")

    await mcp.run_async(
        transport="http",
        host=HOST,
        port=PORT,
        path="/mcp"
    )


if __name__ == "__main__":
    asyncio.run(main())
