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

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from aiogram.types import Update

import db
import bot as bot_module  # the bot, dispatcher, and all chat handlers live in bot.py
from config import BACKEND_URL, BOT_TOKEN, CURRENCY, SITE_NAME, SITE_NAME_AMHARIC, WEBHOOK_SECRET

app = FastAPI(title="Marageli API")

# Allow the frontend (a different domain, e.g. Cloudflare Pages) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your real frontend URL once deployed
    allow_methods=["GET"],
    allow_headers=["*"],
)

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
async def get_store():
    """Your own Marageli Store items (the admin's cosmetics etc.)."""
    listings = await db.list_approved_listings(store_only=True)
    return _with_photo_urls(listings)


@app.get("/api/listings")
async def get_listings(category_id: int | None = None):
    """Approved student listings, optionally filtered by category."""
    listings = await db.list_approved_listings(category_id=category_id, store_only=False)
    return _with_photo_urls(listings)


def _with_photo_urls(listings):
    """
    Listings only store a Telegram file_id, not a real image URL.
    Attach a ready-to-use photo URL field the frontend can display directly.
    """
    for listing in listings:
        listing["currency"] = CURRENCY
        listing["photo_url"] = f"/api/photo/{listing['photo_file_id']}"
    return listings


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
