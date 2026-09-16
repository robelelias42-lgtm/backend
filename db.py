"""
All database access goes through this file.
Neither bot.py nor api.py talk to Turso directly — they call these
functions instead, so the database rules live in exactly one place.
"""

import libsql_client
from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN


def get_client():
    """Open a fresh connection to the Turso database."""
    return libsql_client.create_client(
        url=TURSO_DATABASE_URL,
        auth_token=TURSO_AUTH_TOKEN,
    )


async def run(sql: str, args: list | None = None):
    """Run one write statement (INSERT/UPDATE/DELETE)."""
    client = get_client()
    try:
        result = await client.execute(sql, args or [])
        return result
    finally:
        await client.close()


async def query(sql: str, args: list | None = None):
    """Run one read statement (SELECT) and return rows as list of dicts."""
    client = get_client()
    try:
        result = await client.execute(sql, args or [])
        columns = result.columns
        return [dict(zip(columns, row)) for row in result.rows]
    finally:
        await client.close()


# ---------- Users ----------

async def get_or_create_user(telegram_id: int, username: str, full_name: str, is_admin: bool = False):
    rows = await query("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])
    if rows:
        return rows[0]
    await run(
        "INSERT INTO users (telegram_id, username, full_name, is_admin) VALUES (?, ?, ?, ?)",
        [telegram_id, username, full_name, 1 if is_admin else 0],
    )
    rows = await query("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])
    return rows[0]


async def get_user_by_telegram_id(telegram_id: int):
    rows = await query("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])
    return rows[0] if rows else None


# ---------- Categories ----------

async def list_categories():
    return await query("SELECT * FROM categories ORDER BY name")


async def get_category_by_name(name: str):
    rows = await query("SELECT * FROM categories WHERE name = ?", [name])
    return rows[0] if rows else None


# ---------- Listings ----------

async def count_active_listings_for_user(user_id: int):
    rows = await query(
        """SELECT COUNT(*) as c FROM listings
           WHERE user_id = ? AND is_store_item = 0
           AND status IN ('draft', 'pending_payment', 'pending_review', 'approved')""",
        [user_id],
    )
    return rows[0]["c"]


async def create_listing(user_id, category_id, title, description, price_etb,
                          photo_file_id, pickup_location, is_store_item=False):
    await run(
        """INSERT INTO listings
           (user_id, category_id, title, description, price_etb, photo_file_id,
            pickup_location, is_store_item, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [user_id, category_id, title, description, price_etb, photo_file_id,
         pickup_location, 1 if is_store_item else 0,
         "approved" if is_store_item else "pending_payment"],
    )
    rows = await query("SELECT * FROM listings ORDER BY id DESC LIMIT 1")
    return rows[0]


async def set_listing_status(listing_id: int, status: str):
    await run(
        "UPDATE listings SET status = ?, reviewed_at = datetime('now') WHERE id = ?",
        [status, listing_id],
    )


async def get_listing(listing_id: int):
    rows = await query("SELECT * FROM listings WHERE id = ?", [listing_id])
    return rows[0] if rows else None


async def list_approved_listings(category_id: int | None = None, store_only: bool = False):
    sql = "SELECT * FROM listings WHERE status = 'approved'"
    args = []
    if store_only:
        sql += " AND is_store_item = 1"
    else:
        sql += " AND is_store_item = 0"
    if category_id:
        sql += " AND category_id = ?"
        args.append(category_id)
    sql += " ORDER BY created_at DESC"
    return await query(sql, args)


async def list_pending_review_listings():
    return await query(
        "SELECT * FROM listings WHERE status = 'pending_review' ORDER BY created_at ASC"
    )


# ---------- Payments ----------

async def create_payment(listing_id: int, receipt_file_id: str):
    await run(
        "INSERT INTO payments (listing_id, receipt_file_id) VALUES (?, ?)",
        [listing_id, receipt_file_id],
    )
    await set_listing_status(listing_id, "pending_review")


async def set_payment_status(listing_id: int, status: str):
    await run(
        """UPDATE payments SET status = ?, reviewed_at = datetime('now')
           WHERE id = (
               SELECT id FROM payments WHERE listing_id = ? ORDER BY id DESC LIMIT 1
           )""",
        [status, listing_id],
    )
