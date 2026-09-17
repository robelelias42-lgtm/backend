"""
Marageli (ማራጌሊ) — API + Telegram webhook
=============================================
This single service does two jobs:
  1. Answers the frontend (Mini App) when it asks for categories/listings.
  2. Receives Telegram's webhook — every message a student sends arrives
     here as an HTTP request, which is what keeps this service "alive"
     on Render's free tier (no polling, no fake health-check needed).

Run it with:  uvicorn api:app --host 0.0.0.0 --port 8000
"""

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from aiogram.types import Update
from pydantic import BaseModel

import db
import bot as bot_module  # the bot, dispatcher, and all chat handlers live in bot.py
from config import BACKEND_URL, BOT_TOKEN, CURRENCY, SITE_NAME, SITE_NAME_AMHARIC, WEBHOOK_SECRET

app = FastAPI(title="Marageli API")

# Allow the frontend (a different domain, e.g. Cloudflare Pages) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your real frontend URL once deployed
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


# ---------- Telegram Mini App auth ----------
# The frontend sends Telegram's signed `initData` string with every request
# that needs to know "who is this user" (favorites, likes, My Listings).
# We verify it here so nobody can fake being a different student.

def _verify_init_data(init_data: str) -> dict:
    parsed = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Missing Telegram auth")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(401, "Invalid Telegram auth")

    user_json = parsed.get("user")
    if not user_json:
        raise HTTPException(401, "No user in Telegram auth")
    return json.loads(user_json)


async def get_current_user(x_telegram_init_data: str | None = Header(default=None)):
    """FastAPI dependency: validates initData and returns the user's row from our own DB.
    Raises 401 if missing/invalid — use for actions that require being logged in
    (favorites, reactions, My Listings)."""
    if not x_telegram_init_data:
        raise HTTPException(401, "Missing X-Telegram-Init-Data header")

    tg_user = _verify_init_data(x_telegram_init_data)
    user = await db.get_or_create_user(
        telegram_id=tg_user["id"],
        username=tg_user.get("username", ""),
        full_name=f"{tg_user.get('first_name', '')} {tg_user.get('last_name', '')}".strip(),
    )
    return user


async def get_current_user_optional(x_telegram_init_data: str | None = Header(default=None)):
    """Same as above, but returns None instead of raising — use for browsing endpoints
    that work for anyone, but show extra info (favorited? my reaction?) when logged in."""
    if not x_telegram_init_data:
        return None
    try:
        return await get_current_user(x_telegram_init_data)
    except HTTPException:
        return None

# Keep this path hard to guess — it includes your secret, so random visitors
# and bots scanning the internet can't send fake Telegram updates to you.
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"


@app.on_event("startup")
async def register_webhook():
    if BACKEND_URL == "YOUR_BACKEND_URL":
        # Running locally without a real deployed URL yet — skip registration.
        return
    webhook_url = f"{BACKEND_URL}{WEBHOOK_PATH}"
    await bot_module.bot.set_webhook(url=webhook_url, drop_pending_updates=True)


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Telegram sends every message/click here as a POST request."""
    payload = await request.json()
    update = Update.model_validate(payload, context={"bot": bot_module.bot})
    await bot_module.dp.feed_update(bot=bot_module.bot, update=update)
    return {"ok": True}


@app.get("/")
async def root():
    return {"site": SITE_NAME, "site_amharic": SITE_NAME_AMHARIC, "status": "ok"}


@app.get("/api/categories")
async def get_categories():
    return await db.list_categories()


@app.get("/api/store")
async def get_store(search: str | None = None, sort: str | None = None,
                     current_user=Depends(get_current_user_optional)):
    """Your own Marageli Store items (the admin's cosmetics etc.)."""
    listings = await db.list_approved_listings(store_only=True, search=search, sort=sort)
    return await _enrich_listings(listings, current_user)


@app.get("/api/listings")
async def get_listings(category_id: int | None = None, search: str | None = None, sort: str | None = None,
                        current_user=Depends(get_current_user_optional)):
    """Approved (or sold) student listings, optionally filtered by category, searched, and sorted."""
    listings = await db.list_approved_listings(category_id=category_id, store_only=False, search=search, sort=sort)
    return await _enrich_listings(listings, current_user)


# ---------- Admin: mark a listing sold / back on market ----------

@app.post("/api/listings/{listing_id}/mark-sold")
async def mark_sold(listing_id: int, current_user=Depends(get_current_user)):
    if not current_user["is_admin"]:
        raise HTTPException(403, "Admins only")
    await db.mark_listing_sold(listing_id)
    return {"ok": True, "status": "sold"}


@app.post("/api/listings/{listing_id}/mark-on-market")
async def mark_on_market(listing_id: int, current_user=Depends(get_current_user)):
    if not current_user["is_admin"]:
        raise HTTPException(403, "Admins only")
    await db.mark_listing_on_market(listing_id)
    return {"ok": True, "status": "approved"}


# ---------- Reactions (like / dislike) ----------

class ReactionRequest(BaseModel):
    reaction: str  # "like" or "dislike"


@app.post("/api/listings/{listing_id}/react")
async def react_to_listing(listing_id: int, body: ReactionRequest, current_user=Depends(get_current_user)):
    if body.reaction not in ("like", "dislike"):
        raise HTTPException(400, "reaction must be 'like' or 'dislike'")
    result = await db.set_reaction(current_user["id"], listing_id, body.reaction)
    counts = await db.get_reaction_counts([listing_id])
    return {"ok": True, "my_reaction": result, **counts[listing_id]}


def _with_photo_urls(listings):
    """
    Listings only store a Telegram file_id, not a real image URL.
    Attach a ready-to-use photo URL field the frontend can display directly.
    """
    for listing in listings:
        listing["currency"] = CURRENCY
        listing["photo_url"] = f"/api/photo/{listing['photo_file_id']}"
    return listings


async def _enrich_listings(listings, current_user):
    """Attach photo URL, currency, reaction counts, and (if admin) a can_manage flag
    so the frontend knows whether to show the Mark as Sold / On Market controls."""
    listings = _with_photo_urls(listings)
    ids = [listing["id"] for listing in listings]
    counts = await db.get_reaction_counts(ids)

    my_reactions = {}
    if current_user:
        my_reactions = await db.get_user_reactions(current_user["id"], ids)

    is_admin = bool(current_user and current_user["is_admin"])

    for listing in listings:
        c = counts.get(listing["id"], {"likes": 0, "dislikes": 0})
        listing["likes"] = c["likes"]
        listing["dislikes"] = c["dislikes"]
        listing["my_reaction"] = my_reactions.get(listing["id"])
        listing["can_manage"] = is_admin

    return listings


@app.get("/api/games")
async def get_games():
    """Read-only board view for the Mini App's GAME tab.
    Picking/paying for numbers happens in the bot chat, not here — this just
    shows which numbers are taken so far. Pending (unapproved) payments are
    intentionally shown as still 'available' publicly, since only an admin
    approval should visibly lock in a number."""
    boards = await db.list_game_boards()
    result = []
    for board in boards:
        numbers = await db.list_game_numbers(board["id"])
        result.append({
            "id": board["id"],
            "name": board["name"],
            "status": board["status"],
            "round": board["round"],
            "price_etb": board["price_etb"],
            "currency": CURRENCY,
            "numbers": [
                {"number": n["number"], "status": "taken" if n["status"] == "taken" else "available"}
                for n in numbers
            ],
        })
    return result


@app.get("/api/photo/{file_id}")
async def get_photo(file_id: str):
    """
    Telegram doesn't give out a direct public URL for a file_id — you have to
    ask Telegram where the file lives first, then redirect the browser there.
    This does that lookup and sends the browser straight to the real image.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile", params={"file_id": file_id})
        data = resp.json()
        file_path = data["result"]["file_path"]
        real_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        return RedirectResponse(real_url)
