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


async def list_approved_listings(category_id: int | None = None, store_only: bool = False,
                                  search: str | None = None, sort: str | None = None):
    sql = "SELECT * FROM listings WHERE status IN ('approved', 'sold')"
    args = []
    if store_only:
        sql += " AND is_store_item = 1"
    else:
        sql += " AND is_store_item = 0"
    if category_id:
        sql += " AND category_id = ?"
        args.append(category_id)
    if search:
        sql += " AND (title LIKE ? OR description LIKE ?)"
        like = f"%{search}%"
        args.extend([like, like])

    if sort == "price_asc":
        sql += " ORDER BY price_etb ASC"
    elif sort == "price_desc":
        sql += " ORDER BY price_etb DESC"
    else:
        sql += " ORDER BY created_at DESC"

    return await query(sql, args)


async def mark_listing_sold(listing_id: int):
    await run("UPDATE listings SET status = 'sold' WHERE id = ?", [listing_id])


async def mark_listing_on_market(listing_id: int):
    await run("UPDATE listings SET status = 'approved' WHERE id = ?", [listing_id])


async def list_listings_for_user(user_id: int):
    """A student's own listings (any status), newest first — for 'My Listings'."""
    return await query(
        "SELECT * FROM listings WHERE user_id = ? ORDER BY created_at DESC",
        [user_id],
    )


# ---------- Favorites ----------

async def add_favorite(user_id: int, listing_id: int):
    await run(
        "INSERT OR IGNORE INTO favorites (user_id, listing_id) VALUES (?, ?)",
        [user_id, listing_id],
    )


async def remove_favorite(user_id: int, listing_id: int):
    await run(
        "DELETE FROM favorites WHERE user_id = ? AND listing_id = ?",
        [user_id, listing_id],
    )


async def list_favorite_listings(user_id: int):
    return await query(
        """SELECT listings.* FROM listings
           JOIN favorites ON favorites.listing_id = listings.id
           WHERE favorites.user_id = ? AND listings.status = 'approved'
           ORDER BY favorites.created_at DESC""",
        [user_id],
    )


async def get_favorite_listing_ids(user_id: int):
    rows = await query("SELECT listing_id FROM favorites WHERE user_id = ?", [user_id])
    return {row["listing_id"] for row in rows}


# ---------- Reactions (like / dislike) ----------

async def set_reaction(user_id: int, listing_id: int, reaction: str):
    """reaction is 'like' or 'dislike'. Calling again with the same value removes it (toggle)."""
    existing = await query(
        "SELECT reaction FROM reactions WHERE user_id = ? AND listing_id = ?",
        [user_id, listing_id],
    )
    if existing and existing[0]["reaction"] == reaction:
        await run("DELETE FROM reactions WHERE user_id = ? AND listing_id = ?", [user_id, listing_id])
        return None
    await run(
        """INSERT INTO reactions (user_id, listing_id, reaction) VALUES (?, ?, ?)
           ON CONFLICT(user_id, listing_id) DO UPDATE SET reaction = excluded.reaction""",
        [user_id, listing_id, reaction],
    )
    return reaction


async def get_reaction_counts(listing_ids: list[int]):
    """Returns {listing_id: {"likes": n, "dislikes": n}} for a batch of listings."""
    if not listing_ids:
        return {}
    placeholders = ",".join("?" for _ in listing_ids)
    rows = await query(
        f"""SELECT listing_id, reaction, COUNT(*) as c FROM reactions
            WHERE listing_id IN ({placeholders}) GROUP BY listing_id, reaction""",
        listing_ids,
    )
    counts = {lid: {"likes": 0, "dislikes": 0} for lid in listing_ids}
    for row in rows:
        key = "likes" if row["reaction"] == "like" else "dislikes"
        counts[row["listing_id"]][key] = row["c"]
    return counts


async def get_user_reactions(user_id: int, listing_ids: list[int]):
    """Returns {listing_id: 'like'|'dislike'} for the given user's own reactions."""
    if not listing_ids:
        return {}
    placeholders = ",".join("?" for _ in listing_ids)
    rows = await query(
        f"SELECT listing_id, reaction FROM reactions WHERE user_id = ? AND listing_id IN ({placeholders})",
        [user_id, *listing_ids],
    )
    return {row["listing_id"]: row["reaction"] for row in rows}


async def list_pending_review_listings():
    return await query(
        "SELECT * FROM listings WHERE status = 'pending_review' ORDER BY created_at ASC"
    )


# ---------- Games (Tepi / Aman / Mizan) ----------

async def list_game_boards():
    return await query("SELECT * FROM game_boards ORDER BY id")


async def get_game_board(board_id: int):
    rows = await query("SELECT * FROM game_boards WHERE id = ?", [board_id])
    return rows[0] if rows else None


async def list_game_numbers(board_id: int):
    return await query("SELECT * FROM game_numbers WHERE board_id = ? ORDER BY number", [board_id])


async def get_game_number(board_id: int, number: int):
    rows = await query(
        "SELECT * FROM game_numbers WHERE board_id = ? AND number = ?", [board_id, number]
    )
    return rows[0] if rows else None


async def get_game_number_by_id(number_id: int):
    rows = await query("SELECT * FROM game_numbers WHERE id = ?", [number_id])
    return rows[0] if rows else None


async def claim_game_number(board_id: int, number: int, user_id: int) -> bool:
    """Move a number from available -> pending_payment for this user.
    Returns False if someone else grabbed it first (no crash, just a clean 'too late')."""
    result = await run(
        """UPDATE game_numbers SET status = 'pending_payment', user_id = ?
           WHERE board_id = ? AND number = ? AND status = 'available'""",
        [user_id, board_id, number],
    )
    return result.rows_affected > 0


async def attach_game_receipt(number_id: int, receipt_file_id: str):
    await run("UPDATE game_numbers SET receipt_file_id = ? WHERE id = ?", [receipt_file_id, number_id])


async def approve_game_number(number_id: int) -> bool:
    """Marks a number as taken. Returns True if this filled the board (all 100 taken)."""
    row = await get_game_number_by_id(number_id)
    await run(
        "UPDATE game_numbers SET status = 'taken', taken_at = datetime('now') WHERE id = ?",
        [number_id],
    )
    remaining = await query(
        "SELECT COUNT(*) as c FROM game_numbers WHERE board_id = ? AND status != 'taken'",
        [row["board_id"]],
    )
    if remaining[0]["c"] == 0:
        await run("UPDATE game_boards SET status = 'closed' WHERE id = ?", [row["board_id"]])
        return True
    return False


async def reject_game_number(number_id: int):
    await run(
        "UPDATE game_numbers SET status = 'available', user_id = NULL, receipt_file_id = NULL WHERE id = ?",
        [number_id],
    )


async def open_game_board(board_id: int):
    """Starts a fresh round: clears the board back to all-available and marks it open."""
    await run(
        """UPDATE game_numbers SET status = 'available', user_id = NULL,
           receipt_file_id = NULL, taken_at = NULL WHERE board_id = ?""",
        [board_id],
    )
    await run("UPDATE game_boards SET status = 'open', round = round + 1 WHERE id = ?", [board_id])


async def close_game_board(board_id: int):
    await run("UPDATE game_boards SET status = 'closed' WHERE id = ?", [board_id])


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
