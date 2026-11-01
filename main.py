
import json
import math
import re
import sqlite3

from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional

from fastmcp import FastMCP


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "expenses.db"
CATEGORY_FILE = BASE_DIR / "categories.json"

mcp = FastMCP("ExpenseTracker")


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                month TEXT NOT NULL,
                amount REAL NOT NULL,
                UNIQUE(category, month)
            )
        """)


init_db()


# =========================================================
# CATEGORY RESOURCE
# =========================================================

def load_categories():
    if not CATEGORY_FILE.exists():
        raise FileNotFoundError(
            f"Category resource not found: {CATEGORY_FILE}"
        )

    with open(CATEGORY_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


@mcp.resource("expense://categories")
def get_expense_categories():
    """
    Provides the standardized expense categories
    and their available subcategories.
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
    "groceries": "Groceries",
    "grocery": "Groceries",
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
    "metro": ("Transport", "Metro"),
    "bus": ("Transport", "Bus"),
    "petrol": ("Transport", "Fuel"),
    "diesel": ("Transport", "Fuel"),
    "fuel": ("Transport", "Fuel"),
    "milk": ("Groceries", "Dairy"),
    "vegetables": ("Groceries", "Vegetables"),
    "fruits": ("Groceries", "Fruits"),
    "pizza": ("Food", "Fast Food"),
    "burger": ("Food", "Fast Food"),
    "coffee": ("Food", "Beverages"),
    "tea": ("Food", "Beverages"),
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
    Convert common category variations into standard categories.

    Unknown categories are stored as Other / Uncategorized.
    """

    taxonomy = load_categories()

    normalized_category = category.strip().lower()
    normalized_subcategory = subcategory.strip().lower()

    # Check category aliases.
    canonical_category = CATEGORY_ALIASES.get(
        normalized_category
    )

    # Check whether the supplied category is already canonical.
    if not canonical_category:
        for item in taxonomy["categories"]:
            if item["category"].lower() == normalized_category:
                canonical_category = item["category"]
                break

    # Check aliases that identify both category and subcategory.
    if normalized_category in SUBCATEGORY_ALIASES:
        canonical_category, canonical_subcategory = (
            SUBCATEGORY_ALIASES[normalized_category]
        )
        return canonical_category, canonical_subcategory

    if not canonical_category:
        return "Other", "Uncategorized"

    # Match subcategory against the taxonomy.
    available_subcategories = []

    for item in taxonomy["categories"]:
        if item["category"] == canonical_category:
            available_subcategories = item["subcategories"]
            break

    canonical_subcategory = ""

    if normalized_subcategory:
        for item in available_subcategories:
            if item.lower() == normalized_subcategory:
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
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m")
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
        return (date.today() - timedelta(days=2)).isoformat()

    if "yesterday" in text:
        return (date.today() - timedelta(days=1)).isoformat()

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
def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = ""
):
    """
    Add a structured expense.

    Use the expense://categories resource for the standard
    category taxonomy. Unknown categories become Other.
    """

    expense_date = validate_date(date)
    expense_amount = validate_amount(amount)

    category, subcategory = normalize_category(
        validate_category(category),
        subcategory
    )

    with get_db() as conn:
        cur = conn.execute("""
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

        return {
            "status": "success",
            "message": "Expense added successfully.",
            "expense_id": cur.lastrowid,
            "date": expense_date,
            "amount": expense_amount,
            "category": category,
            "subcategory": subcategory
        }


# =========================================================
# TOOL 2: QUICK NATURAL LANGUAGE EXPENSE
# =========================================================

@mcp.tool
def quick_add_expense(utterance: str):
    """
    Record an expense from natural-language text.

    Examples:
    - I spent 250 rupees on groceries today.
    - Paid 120 for coffee yesterday.
    - Spent 500 on Uber.
    - I bought milk for 60 rupees.

    If the amount cannot be identified, ask the user.
    """

    text = utterance.strip()
    lower = text.lower()

    if not text:
        return {
            "status": "needs_clarification",
            "message": "Please describe your expense."
        }

    amount_match = re.search(
        r"(?:₹|rs\.?|rupees?)\s*([\d,]+(?:\.\d{1,2})?)"
        r"|([\d,]+(?:\.\d{1,2})?)\s*(?:rupees?|rs\.?)",
        lower
    )

    # Also support phrases such as "spent 250 on food".
    if not amount_match:
        amount_match = re.search(
            r"\b(?:spent|paid|bought|cost|for)\s+"
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

    amount = validate_amount(amount_text.replace(",", ""))

    # Find a recognizable subcategory or alias.
    matched_category = None
    matched_subcategory = ""

    for keyword, pair in SUBCATEGORY_ALIASES.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", lower):
            matched_category, matched_subcategory = pair
            break

    # If no subcategory alias matched, check category keywords.
    if not matched_category:
        for alias, canonical in CATEGORY_ALIASES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", lower):
                matched_category = canonical
                break

    if not matched_category:
        return {
            "status": "needs_clarification",
            "message": (
                "I found the amount, but could not identify "
                "the category. Which category should I use?"
            ),
            "detected_amount": amount
        }

    expense_date = parse_natural_date(text)

    result = add_expense(
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
def list_expenses(
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

    with get_db() as conn:
        rows = conn.execute(f"""
            SELECT * FROM expenses
            {where}
            ORDER BY date DESC, id DESC
            LIMIT ?
        """, (*params, limit)).fetchall()

        return expense_rows(rows)


# =========================================================
# TOOL 4: UPDATE EXPENSE
# =========================================================

@mcp.tool
def update_expense(
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
            category,
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

    with get_db() as conn:
        cur = conn.execute(
            f"UPDATE expenses SET {columns} WHERE id = ?",
            (*updates.values(), expense_id)
        )

        if cur.rowcount == 0:
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
def delete_expense(expense_id: int):
    """
    Permanently delete an expense by ID.

    The assistant should obtain user confirmation before
    calling this destructive tool.
    """

    if expense_id <= 0:
        raise ValueError("Expense ID must be positive.")

    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM expenses WHERE id = ?",
            (expense_id,)
        )

        if cur.rowcount == 0:
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
def get_monthly_summary(month: Optional[str] = None):
    """Get monthly spending, transaction count and average."""

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    with get_db() as conn:
        result = conn.execute("""
            SELECT
                COUNT(*) AS transactions,
                COALESCE(SUM(amount), 0) AS total,
                COALESCE(AVG(amount), 0) AS average
            FROM expenses
            WHERE substr(date, 1, 7) = ?
        """, (month,)).fetchone()

        categories = conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (month,)).fetchall()

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
def category_analysis(month: Optional[str] = None):
    """Analyze spending distribution by category."""

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                category,
                COUNT(*) AS transactions,
                SUM(amount) AS total,
                AVG(amount) AS average
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (month,)).fetchall()

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
def set_budget(
    category: str,
    amount: float,
    month: Optional[str] = None
):
    """Create or update a monthly budget for a category."""

    category, _ = normalize_category(
        validate_category(category)
    )

    amount = validate_amount(amount)

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    with get_db() as conn:
        conn.execute("""
            INSERT INTO budgets (category, month, amount)
            VALUES (?, ?, ?)
            ON CONFLICT(category, month)
            DO UPDATE SET amount = excluded.amount
        """, (category, month, amount))

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
def budget_tracker(month: Optional[str] = None):
    """Compare monthly category spending against budgets."""

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    with get_db() as conn:
        budgets = conn.execute("""
            SELECT category, amount
            FROM budgets
            WHERE month = ?
        """, (month,)).fetchall()

        results = []

        for budget in budgets:
            spent = conn.execute("""
                SELECT COALESCE(SUM(amount), 0)
                FROM expenses
                WHERE substr(date, 1, 7) = ?
                AND LOWER(category) = LOWER(?)
            """, (month, budget["category"])).fetchone()[0]

            remaining = budget["amount"] - spent

            results.append({
                "category": budget["category"],
                "budget": round(budget["amount"], 2),
                "spent": round(spent, 2),
                "remaining": round(remaining, 2),
                "percentage_used": round(
                    spent / budget["amount"] * 100, 2
                ),
                "status": (
                    "Over budget" if remaining < 0
                    else "Budget exceeded 80%"
                    if spent / budget["amount"] >= 0.8
                    else "Within budget"
                )
            })

        return {
            "month": month,
            "budgets": results
        }


# =========================================================
# TOOL 10: EXPENSE INSIGHTS
# =========================================================

@mcp.tool
def expense_insights(month: Optional[str] = None):
    """
    Generate rule-based insights from expense history.

    This tool calculates spending patterns. It does not
    use a separate machine-learning model.
    """

    month = validate_month(
        month or date.today().strftime("%Y-%m")
    )

    with get_db() as conn:
        total = conn.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE substr(date, 1, 7) = ?
        """, (month,)).fetchone()[0]

        categories = conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY category
            ORDER BY total DESC
        """, (month,)).fetchall()

        daily = conn.execute("""
            SELECT date, SUM(amount) AS total
            FROM expenses
            WHERE substr(date, 1, 7) = ?
            GROUP BY date
            ORDER BY total DESC
            LIMIT 1
        """, (month,)).fetchone()

        insights = []

        if total == 0:
            insights.append(
                "No expenses recorded for this month yet."
            )
        else:
            insights.append(
                f"Your total spending for {month} is ₹{total:.2f}."
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
                f"Your highest spending day was {daily['date']} "
                f"with ₹{daily['total']:.2f} spent."
            )

        return {
            "month": month,
            "total_spending": round(total, 2),
            "insights": insights
        }


# =========================================================
# SERVER ENTRY POINT
# =========================================================

if __name__ == "__main__":
    mcp.run()
