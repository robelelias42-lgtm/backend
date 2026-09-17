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


class AddStoreItem(StatesGroup):
    choosing_category = State()
    entering_title = State()
    entering_description = State()
    entering_price = State()
    uploading_photo = State()
    entering_pickup = State()


class PlayGame(StatesGroup):
    uploading_receipt = State()


# ---------- Helpers ----------

def main_menu_keyboard(is_admin: bool = False):
    buttons = [[KeyboardButton(text="🛍 Sell an item")], [KeyboardButton(text="🎲 Games")]]
    if is_admin:
        buttons.append([KeyboardButton(text="➕ Add Store Item")])
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


STATUS_LABELS = {"open": "🟢 Open — pick your lucky number!", "closed": "⏳ Waiting for winners"}


def games_menu_keyboard(boards):
    buttons = [
        [InlineKeyboardButton(text=f"{b['name']} — {STATUS_LABELS[b['status']]}", callback_data=f"game:board:{b['id']}")]
        for b in boards
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def game_number_grid_keyboard(board_id: int, numbers, is_admin: bool):
    rows = []
    for row_start in range(0, 100, 10):
        row = []
        for n in numbers[row_start:row_start + 10]:
            if n["status"] == "available":
                row.append(InlineKeyboardButton(text=str(n["number"]), callback_data=f"game:pick:{board_id}:{n['number']}"))
            else:
                row.append(InlineKeyboardButton(text=f"🔒{n['number']}", callback_data="game:taken"))
        rows.append(row)
    if is_admin:
        rows.append([InlineKeyboardButton(text="🔒 Close this round early", callback_data=f"game:close:{board_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def game_closed_keyboard(board_id: int, is_admin: bool):
    if not is_admin:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔓 Open a new round", callback_data=f"game:open:{board_id}")]]
    )


def game_admin_review_keyboard(number_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"game:appr:{number_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"game:rej:{number_id}"),
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
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id == ADMIN_TELEGRAM_ID
    await message.answer("Cancelled. You're back at the main menu.", reply_markup=main_menu_keyboard(is_admin=is_admin))


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


# ---------- Admin: post a Marageli Store item directly (no payment/review) ----------

@router.message(F.text == "➕ Add Store Item")
async def store_item_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return  # silently ignore — regular students never see this button anyway

    categories = await db.list_categories()
    await state.set_state(AddStoreItem.choosing_category)
    await message.answer("Store item — what category?", reply_markup=category_keyboard(categories))


@router.callback_query(AddStoreItem.choosing_category, F.data.startswith("cat:"))
async def store_item_category_chosen(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    await state.update_data(category_id=category_id)
    await state.set_state(AddStoreItem.entering_title)
    await callback.message.answer("Item name?")
    await callback.answer()


@router.message(AddStoreItem.entering_title)
async def store_item_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddStoreItem.entering_description)
    await message.answer("Description:")


@router.message(AddStoreItem.entering_description)
async def store_item_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddStoreItem.entering_price)
    await message.answer(f"Price, in {CURRENCY}? (numbers only, e.g. 250)")


@router.message(AddStoreItem.entering_price)
async def store_item_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("Please send a number, e.g. 250")
        return
    await state.update_data(price=price)
    await state.set_state(AddStoreItem.uploading_photo)
    await message.answer("Send ONE photo of the item:")


@router.message(AddStoreItem.uploading_photo, F.photo)
async def store_item_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(AddStoreItem.entering_pickup)
    await message.answer("Pickup location?")


@router.message(AddStoreItem.uploading_photo)
async def store_item_photo_invalid(message: Message):
    await message.answer("Please send a photo (not text).")


@router.message(AddStoreItem.entering_pickup)
async def store_item_pickup(message: Message, state: FSMContext):
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
        is_store_item=True,  # goes straight to status='approved', no payment step
    )
    await state.clear()

    await message.answer(
        f"✅ '{listing['title']}' was published to the Marageli Store — it's live in the Mini App now.",
        reply_markup=main_menu_keyboard(is_admin=True),
    )


# ---------- Games: Tepi, Aman, Mizan ----------

@router.message(F.text == "🎲 Games")
async def games_start(message: Message):
    boards = await db.list_game_boards()
    await message.answer(
        "🎲 Marageli Games\n\nPick a board to see it, or to pick a lucky number:",
        reply_markup=games_menu_keyboard(boards),
    )


@router.callback_query(F.data.startswith("game:board:"))
async def game_board_opened(callback: CallbackQuery):
    board_id = int(callback.data.split(":")[2])
    board = await db.get_game_board(board_id)
    is_admin = callback.from_user.id == ADMIN_TELEGRAM_ID

    if board["status"] == "closed":
        await callback.message.answer(
            f"{board['name']} — ⏳ Waiting for winners.\n\n"
            "This round is full and closed. A new round will open soon!",
            reply_markup=game_closed_keyboard(board_id, is_admin),
        )
    else:
        numbers = await db.list_game_numbers(board_id)
        await callback.message.answer(
            f"{board['name']} — 🟢 Game is opened, pick your lucky number!\n"
            f"Price per number: {board['price_etb']} {CURRENCY}\n"
            f"🔒 = already taken",
            reply_markup=game_number_grid_keyboard(board_id, numbers, is_admin),
        )
    await callback.answer()


@router.callback_query(F.data == "game:taken")
async def game_number_taken(callback: CallbackQuery):
    await callback.answer("Already taken — pick another number.", show_alert=False)


@router.callback_query(F.data.startswith("game:pick:"))
async def game_number_picked(callback: CallbackQuery, state: FSMContext):
    _, _, board_id_str, number_str = callback.data.split(":")
    board_id, number = int(board_id_str), int(number_str)

    user = await db.get_user_by_telegram_id(callback.from_user.id)
    claimed = await db.claim_game_number(board_id, number, user["id"])
    if not claimed:
        await callback.answer("Sorry, someone just took that number — pick another.", show_alert=True)
        return

    board = await db.get_game_board(board_id)
    await state.set_state(PlayGame.uploading_receipt)
    await state.update_data(board_id=board_id, number=number)
    await callback.answer()
    await callback.message.answer(
        f"You picked number {number} on {board['name']} 🎉\n"
        f"Price: {board['price_etb']} {CURRENCY}\n\n"
        "Send a photo/screenshot of your payment receipt to confirm this number.\n"
        "(If you don't pay, an admin may release this number back to others.)"
    )


@router.message(PlayGame.uploading_receipt, F.photo)
async def game_receipt_uploaded(message: Message, state: FSMContext):
    data = await state.get_data()
    board = await db.get_game_board(data["board_id"])
    number_row = await db.get_game_number(data["board_id"], data["number"])
    receipt_file_id = message.photo[-1].file_id

    await db.attach_game_receipt(number_row["id"], receipt_file_id)
    await state.clear()

    await message.answer(
        "Thanks! Sent for admin approval. You'll be notified once it's confirmed.",
        reply_markup=main_menu_keyboard(is_admin=message.from_user.id == ADMIN_TELEGRAM_ID),
    )

    await bot.send_photo(
        chat_id=ADMIN_TELEGRAM_ID,
        photo=receipt_file_id,
        caption=(
            f"🎲 Game payment pending review\n\n"
            f"Board: {board['name']}\nNumber: {data['number']}\n"
            f"From: @{message.from_user.username or message.from_user.full_name}"
        ),
        reply_markup=game_admin_review_keyboard(number_row["id"]),
    )


@router.message(PlayGame.uploading_receipt)
async def game_receipt_invalid(message: Message):
    await message.answer("Please send a photo of your payment receipt.")


# ---------- Admin: approve / reject a game number ----------

@router.callback_query(F.data.startswith("game:appr:"))
async def game_approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("Admins only.", show_alert=True)
        return

    number_id = int(callback.data.split(":")[2])
    number_row = await db.get_game_number_by_id(number_id)
    board = await db.get_game_board(number_row["board_id"])
    became_full = await db.approve_game_number(number_id)

    await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n✅ APPROVED")
    await callback.answer("Approved")

    if number_row["user_id"]:
        buyer = await db.query("SELECT telegram_id FROM users WHERE id = ?", [number_row["user_id"]])
        if buyer:
            await bot.send_message(
                buyer[0]["telegram_id"],
                f"🎉 Confirmed! Number {number_row['number']} on {board['name']} is yours.",
            )

    if became_full:
        await bot.send_message(
            ADMIN_TELEGRAM_ID,
            f"🎯 {board['name']} is now FULL — all 100 numbers taken!\n"
            "Pick a winner, then open a new round with /games when you're ready.",
        )


@router.callback_query(F.data.startswith("game:rej:"))
async def game_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("Admins only.", show_alert=True)
        return

    number_id = int(callback.data.split(":")[2])
    number_row = await db.get_game_number_by_id(number_id)
    board = await db.get_game_board(number_row["board_id"])
    await db.reject_game_number(number_id)

    await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n❌ REJECTED")
    await callback.answer("Rejected")

    if number_row["user_id"]:
        buyer = await db.query("SELECT telegram_id FROM users WHERE id = ?", [number_row["user_id"]])
        if buyer:
            await bot.send_message(
                buyer[0]["telegram_id"],
                f"Your payment for number {number_row['number']} on {board['name']} wasn't approved. "
                "The number is open again — message the admin if you have questions.",
            )


# ---------- Admin: open / close a round ----------

@router.callback_query(F.data.startswith("game:open:"))
async def game_open_round(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("Admins only.", show_alert=True)
        return

    board_id = int(callback.data.split(":")[2])
    await db.open_game_board(board_id)
    board = await db.get_game_board(board_id)

    await callback.answer("Round opened!")
    await callback.message.answer(
        f"🟢 {board['name']} is now OPEN — Round {board['round']}. Pick your lucky numbers!"
    )


@router.callback_query(F.data.startswith("game:close:"))
async def game_close_round(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("Admins only.", show_alert=True)
        return

    board_id = int(callback.data.split(":")[2])
    await db.close_game_board(board_id)
    board = await db.get_game_board(board_id)

    await callback.answer("Round closed.")
    await callback.message.answer(f"⏳ {board['name']} is now closed — waiting for winners.")


@router.message(Command("games"))
async def games_command(message: Message):
    boards = await db.list_game_boards()
    await message.answer("🎲 Marageli Games", reply_markup=games_menu_keyboard(boards))


# ---------- Admin: approve / reject (listings) ----------

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
