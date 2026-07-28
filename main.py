import os
from datetime import date, datetime
from typing import Optional

import aiosqlite
from fastmcp import FastMCP

DB_PATH = os.getenv("EXPENSE_DB_PATH", "/tmp/expenses.db")

mcp = FastMCP(name="Expense-Tracker-MCP-Server")


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


@mcp.tool
async def add_expenses(
    amount: float,
    category: str,
    note: str = "",
    expense_date: Optional[str] = None,
) -> dict:
    """Add a new expense. expense_date should be YYYY-MM-DD; defaults to today."""
    expense_date = expense_date or date.today().isoformat()
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO expenses (amount, category, note, expense_date, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (amount, category, note, expense_date, datetime.utcnow().isoformat()),
    )
    await db.commit()
    new_id = cursor.lastrowid
    await db.close()
    return {"id": new_id, "amount": amount, "category": category, "note": note, "date": expense_date}


@mcp.tool
async def get_expense(expense_id: int) -> dict:
    """Return a single expense by its ID."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
    row = await cursor.fetchone()
    await db.close()
    if row is None:
        raise ValueError(f"No expense found with id {expense_id}")
    return dict(row)


@mcp.tool
async def update_expense(
    expense_id: int,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    note: Optional[str] = None,
    expense_date: Optional[str] = None,
) -> dict:
    """Update any fields of an existing expense. Only provided fields are changed."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,))
    row = await cursor.fetchone()
    if row is None:
        await db.close()
        raise ValueError(f"No expense found with id {expense_id}")

    updated = dict(row)
    if amount is not None:
        updated["amount"] = amount
    if category is not None:
        updated["category"] = category
    if note is not None:
        updated["note"] = note
    if expense_date is not None:
        updated["expense_date"] = expense_date

    await db.execute(
        """UPDATE expenses SET amount = ?, category = ?, note = ?, expense_date = ?
           WHERE id = ?""",
        (updated["amount"], updated["category"], updated["note"], updated["expense_date"], expense_id),
    )
    await db.commit()
    await db.close()
    return updated


@mcp.tool
async def delete_expense(expense_id: int) -> dict:
    """Delete an expense by its ID."""
    db = await get_db()
    cursor = await db.execute("SELECT id FROM expenses WHERE id = ?", (expense_id,))
    row = await cursor.fetchone()
    if row is None:
        await db.close()
        raise ValueError(f"No expense found with id {expense_id}")
    await db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    await db.commit()
    await db.close()
    return {"deleted_id": expense_id}


@mcp.tool
async def list_expenses(expense_date: str) -> list:
    """Return all expenses recorded on a given date (YYYY-MM-DD)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM expenses WHERE expense_date = ? ORDER BY id", (expense_date,)
    )
    rows = await cursor.fetchall()
    await db.close()
    return [dict(r) for r in rows]


@mcp.tool
async def recent_expenses(limit: int = 5) -> list:
    """Return the most recently added expenses."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM expenses ORDER BY id DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    await db.close()
    return [dict(r) for r in rows]


@mcp.tool
async def search_by_category(category: str) -> list:
    """Return all expenses for a given category (case-insensitive)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM expenses WHERE LOWER(category) = LOWER(?) ORDER BY id", (category,)
    )
    rows = await cursor.fetchall()
    await db.close()
    return [dict(r) for r in rows]


@mcp.tool
async def search_note(keyword: str) -> list:
    """Search expenses whose notes contain a keyword."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM expenses WHERE note LIKE ? ORDER BY id", (f"%{keyword}%",)
    )
    rows = await cursor.fetchall()
    await db.close()
    return [dict(r) for r in rows]


@mcp.tool
async def total_spending(start_date: str, end_date: str) -> dict:
    """Return total spending within an inclusive date range (YYYY-MM-DD)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT SUM(amount) as total FROM expenses WHERE expense_date BETWEEN ? AND ?",
        (start_date, end_date),
    )
    row = await cursor.fetchone()
    await db.close()
    return {"start_date": start_date, "end_date": end_date, "total": row["total"] or 0.0}


@mcp.tool
async def average_expense() -> dict:
    """Return the average expense amount across all records."""
    db = await get_db()
    cursor = await db.execute("SELECT AVG(amount) as avg FROM expenses")
    row = await cursor.fetchone()
    await db.close()
    return {"average": row["avg"] or 0.0}


@mcp.tool
async def largest_expense() -> dict:
    """Return the single largest recorded expense."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM expenses ORDER BY amount DESC LIMIT 1")
    row = await cursor.fetchone()
    await db.close()
    if row is None:
        raise ValueError("No expenses recorded yet")
    return dict(row)


@mcp.tool
async def expense_count() -> dict:
    """Return the total number of recorded expenses."""
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) as count FROM expenses")
    row = await cursor.fetchone()
    await db.close()
    return {"count": row["count"]}


@mcp.tool
async def summarize(start_date: str, end_date: str) -> list:
    """Summarize expenses by category within an inclusive date range."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT category, SUM(amount) as total, COUNT(*) as count
           FROM expenses WHERE expense_date BETWEEN ? AND ?
           GROUP BY category ORDER BY total DESC""",
        (start_date, end_date),
    )
    rows = await cursor.fetchall()
    await db.close()
    return [dict(r) for r in rows]


def _init_db_sync():
    """Create the expenses table synchronously at import time.

    Horizon imports this module directly and never runs the __main__
    block below, so we can't rely on asyncio.run(init_db()) happening
    there. Plain sqlite3 avoids any event-loop timing issues since this
    runs once, immediately, when the module is first loaded.
    """
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            note TEXT,
            expense_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


_init_db_sync()


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000,
    )