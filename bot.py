"""
Marageli (ማራጌሊ) — Telegram bot
=================================
This is the "brain" of the project. It talks to students in chat,
saves listings/payments through db.py, and lets the admin approve
or reject things.

Run it with:  python bot.py
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

import db
from config import ADMIN_TELEGRAM_ID, BOT_TOKEN, CURRENCY, MINI_APP_URL, SITE_NAME

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ---------- Conversation states for "sell an item" ----------

class SellListing(StatesGroup):
    choosing_category = State()
    entering_title = State()
    entering_description = State()
    entering_price = State()
    uploading_photo = State()
    entering_pickup = State()
    uploading_receipt = State()


# ---------- Helpers ----------

def main_menu_keyboard():
    buttons = [[KeyboardButton(text="🛍 Sell an item")]]
    if MINI_APP_URL and MINI_APP_URL != "YOUR_MINI_APP_URL":
        buttons.append([KeyboardButton(text="🏪 Open Marageli", web_app=WebAppInfo(url=MINI_APP_URL))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def category_keyboard(categories):
    buttons = [[InlineKeyboardButton(text=c["name"], callback_data=f"cat:{c['id']}")] for c in categories]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_review_keyboard(listing_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{listing_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{listing_id}"),
            ]
        ]
    )


# ---------- Basic commands ----------

@router.message(CommandStart())
async def start_handler(message: Message):
    is_admin = message.from_user.id == ADMIN_TELEGRAM_ID
    await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        is_admin=is_admin,
    )
    await message.answer(
        f"Selam! 👋 Welcome to {SITE_NAME} (ማራጌሊ).\n\n"
        "Buy and sell with fellow students, right here in Telegram.\n\n"
        "Use the buttons below to get started.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled. You're back at the main menu.", reply_markup=main_menu_keyboard())


# ---------- Selling flow: student creates one listing ----------

@router.message(F.text == "🛍 Sell an item")
async def sell_start(message: Message, state: FSMContext):
    user = await db.get_user_by_telegram_id(message.from_user.id)
    active_count = await db.count_active_listings_for_user(user["id"])
    if active_count >= 1:
        await message.answer(
            "You already have an active listing. Each student can only have "
            "ONE active listing at a time. Wait until it's sold or removed "
            "before posting a new one."
        )
        return

    categories = await db.list_categories()
    await state.set_state(SellListing.choosing_category)
    await message.answer("What category is your item?", reply_markup=category_keyboard(categories))


@router.callback_query(SellListing.choosing_category, F.data.startswith("cat:"))
async def sell_category_chosen(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    await state.update_data(category_id=category_id)
    await state.set_state(SellListing.entering_title)
    await callback.message.answer("Great. What's the item's name? (e.g. 'Casio calculator')")
    await callback.answer()


@router.message(SellListing.entering_title)
async def sell_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(SellListing.entering_description)
    await message.answer("Add a short description (condition, details, etc.):")


@router.message(SellListing.entering_description)
async def sell_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(SellListing.entering_price)
    await message.answer(f"What's the price, in {CURRENCY}? (numbers only, e.g. 250)")


@router.message(SellListing.entering_price)
async def sell_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("Please send a number, e.g. 250")
        return
    await state.update_data(price=price)
    await state.set_state(SellListing.uploading_photo)
    await message.answer("Send ONE photo of the item:")


@router.message(SellListing.uploading_photo, F.photo)
async def sell_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(SellListing.entering_pickup)
    await message.answer("Where can buyers pick this up? (e.g. 'Main gate, Building 4')")


@router.message(SellListing.uploading_photo)
async def sell_photo_invalid(message: Message):
    await message.answer("Please send a photo (not text).")


@router.message(SellListing.entering_pickup)
async def sell_pickup(message: Message, state: FSMContext):
    data = await state.update_data(pickup_location=message.text)
    user = await db.get_user_by_telegram_id(message.from_user.id)

    listing = await db.create_listing(
        user_id=user["id"],
        category_id=data["category_id"],
        title=data["title"],
        description=data["description"],
        price_etb=data["price"],
        photo_file_id=data["photo_file_id"],
        pickup_location=data["pickup_location"],
    )
    await state.update_data(listing_id=listing["id"])
    await state.set_state(SellListing.uploading_receipt)

    await message.answer(
        "Your listing is saved as a draft. To publish it, please pay the "
        "small listing fee and send a photo/screenshot of your payment "
        "receipt here."
    )


@router.message(SellListing.uploading_receipt, F.photo)
async def sell_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    receipt_file_id = message.photo[-1].file_id

    await db.create_payment(listing_id=data["listing_id"], receipt_file_id=receipt_file_id)

    await message.answer(
        "Thanks! Your receipt was sent for review. You'll be notified once "
        "an admin approves or rejects your listing.",
        reply_markup=main_menu_keyboard(),
    )
    await state.clear()

    listing = await db.get_listing(data["listing_id"])
    await bot.send_photo(
        chat_id=ADMIN_TELEGRAM_ID,
        photo=receipt_file_id,
        caption=(
            f"📥 New listing pending review\n\n"
            f"#{listing['id']} — {listing['title']}\n"
            f"Price: {listing['price_etb']} {CURRENCY}\n"
            f"Pickup: {listing['pickup_location']}\n"
            f"Description: {listing['description']}"
        ),
        reply_markup=admin_review_keyboard(listing["id"]),
    )


@router.message(SellListing.uploading_receipt)
async def sell_receipt_invalid(message: Message):
    await message.answer("Please send a photo of your payment receipt.")


# ---------- Admin: approve / reject ----------

@router.callback_query(F.data.startswith("approve:"))
async def approve_listing(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("Admins only.", show_alert=True)
        return

    listing_id = int(callback.data.split(":")[1])
    listing = await db.get_listing(listing_id)
    await db.set_listing_status(listing_id, "approved")
    await db.set_payment_status(listing_id, "approved")

    await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ APPROVED")
    await callback.answer("Approved")

    seller = await db.query("SELECT telegram_id FROM users WHERE id = ?", [listing["user_id"]])
    if seller:
        await bot.send_message(seller[0]["telegram_id"], f"🎉 Your listing '{listing['title']}' was approved and is now live!")


@router.callback_query(F.data.startswith("reject:"))
async def reject_listing(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("Admins only.", show_alert=True)
        return

    listing_id = int(callback.data.split(":")[1])
    listing = await db.get_listing(listing_id)
    await db.set_listing_status(listing_id, "rejected")
    await db.set_payment_status(listing_id, "rejected")

    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ REJECTED")
    await callback.answer("Rejected")

    seller = await db.query("SELECT telegram_id FROM users WHERE id = ?", [listing["user_id"]])
    if seller:
        await bot.send_message(
            seller[0]["telegram_id"],
            f"Your listing '{listing['title']}' was rejected. Message the admin if you have questions.",
        )


@router.message(Command("pending"))
async def pending_command(message: Message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return
    pending = await db.list_pending_review_listings()
    if not pending:
        await message.answer("No listings waiting for review. 🎉")
        return
    for listing in pending:
        await bot.send_photo(
            chat_id=ADMIN_TELEGRAM_ID,
            photo=listing["photo_file_id"],
            caption=f"#{listing['id']} — {listing['title']} — {listing['price_etb']} {CURRENCY}",
            reply_markup=admin_review_keyboard(listing["id"]),
        )


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
