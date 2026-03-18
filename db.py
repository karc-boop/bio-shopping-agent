"""SQLite storage for lab profile, order history, and draft orders."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "lab_data.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS lab_profile (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                supplier TEXT NOT NULL,
                catalog_number TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price_usd REAL NOT NULL,
                total_price_usd REAL NOT NULL,
                grant_code TEXT,
                ordered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS draft_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                supplier TEXT NOT NULL,
                catalog_number TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price_usd REAL NOT NULL,
                total_price_usd REAL NOT NULL,
                grant_code TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS grant_budgets (
                grant_code TEXT PRIMARY KEY,
                total_budget_usd REAL NOT NULL,
                spent_usd REAL NOT NULL DEFAULT 0.0
            );
        """)

        # Seed lab profile if empty
        row = conn.execute("SELECT COUNT(*) FROM lab_profile").fetchone()[0]
        if row == 0:
            seed = {
                "lab_name": "Chen Lab – Bioengineering Dept",
                "institution": "University of California",
                "pi_name": "Prof. Sarah Chen",
                "grant_codes": json.dumps(["NIH-R01-2023-BIO", "NSF-MCB-2024", "DOD-CDMRP-2024"]),
            }
            conn.executemany(
                "INSERT INTO lab_profile (key, value) VALUES (?, ?)",
                seed.items(),
            )

        # Seed grant budgets if empty
        row = conn.execute("SELECT COUNT(*) FROM grant_budgets").fetchone()[0]
        if row == 0:
            budgets = [
                ("NIH-R01-2023-BIO", 15000.00, 0.0),
                ("NSF-MCB-2024",     8000.00,  0.0),
                ("DOD-CDMRP-2024",   5000.00,  0.0),
            ]
            conn.executemany(
                "INSERT INTO grant_budgets (grant_code, total_budget_usd, spent_usd) VALUES (?, ?, ?)",
                budgets,
            )


def get_grant_budgets() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT grant_code, total_budget_usd, spent_usd FROM grant_budgets ORDER BY grant_code"
        ).fetchall()
    return [
        {
            "grant_code": r["grant_code"],
            "total_budget_usd": r["total_budget_usd"],
            "spent_usd": r["spent_usd"],
            "remaining_usd": round(r["total_budget_usd"] - r["spent_usd"], 2),
        }
        for r in rows
    ]


def deduct_grant_spend(grant_code: str, amount: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE grant_budgets SET spent_usd = spent_usd + ? WHERE grant_code = ?",
            (amount, grant_code),
        )


def get_lab_profile() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM lab_profile").fetchall()
    profile = {r["key"]: r["value"] for r in rows}
    if "grant_codes" in profile:
        profile["grant_codes"] = json.loads(profile["grant_codes"])
    return profile


def get_order_history() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM order_history ORDER BY ordered_at DESC LIMIT 20"
        ).fetchall()
    return [dict(r) for r in rows]


def create_draft_order(
    product_id: str,
    product_name: str,
    supplier: str,
    catalog_number: str,
    quantity: int,
    unit_price_usd: float,
    grant_code: Optional[str],
    notes: Optional[str],
) -> dict:
    total = unit_price_usd * quantity
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO draft_orders
               (product_id, product_name, supplier, catalog_number, quantity,
                unit_price_usd, total_price_usd, grant_code, notes, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (product_id, product_name, supplier, catalog_number, quantity,
             unit_price_usd, total, grant_code, notes, now),
        )
        draft_id = cursor.lastrowid
    return get_draft_order(draft_id)


def get_draft_order(draft_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM draft_orders WHERE id = ?", (draft_id,)
        ).fetchone()
    return dict(row) if row else None


def approve_draft_order(draft_id: int) -> Optional[dict]:
    """Approve a draft order, move it to order history, and deduct from grant budget."""
    draft = get_draft_order(draft_id)
    if not draft or draft["status"] != "pending":
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE draft_orders SET status = 'approved' WHERE id = ?", (draft_id,)
        )
        conn.execute(
            """INSERT INTO order_history
               (product_id, product_name, supplier, catalog_number, quantity,
                unit_price_usd, total_price_usd, grant_code, ordered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (draft["product_id"], draft["product_name"], draft["supplier"],
             draft["catalog_number"], draft["quantity"], draft["unit_price_usd"],
             draft["total_price_usd"], draft["grant_code"], datetime.utcnow().isoformat()),
        )
    if draft.get("grant_code"):
        deduct_grant_spend(draft["grant_code"], draft["total_price_usd"])
    return get_draft_order(draft_id)


def reject_draft_order(draft_id: int) -> Optional[dict]:
    """Mark a draft order as rejected."""
    draft = get_draft_order(draft_id)
    if not draft or draft["status"] != "pending":
        return None
    with get_conn() as conn:
        conn.execute(
            "UPDATE draft_orders SET status = 'rejected' WHERE id = ?", (draft_id,)
        )
    return get_draft_order(draft_id)


def get_pending_drafts() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM draft_orders WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]
