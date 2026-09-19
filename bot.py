"""
Marageli (ማራጌሊ) — Telegram bot
=================================
This is the "brain" of the project. It talks to people in chat,
saves listings/payments through db.py, and lets the admin approve,
reject, or manage products.

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


# ---------- Conversation states ----------

class SellListing(StatesGroup):
    choosing_category = State()
    entering_title = State()
    entering_description = State()
    entering_price = State()
    uploading_photo = State()
    entering_pickup = State()
    entering_min_qty = State()
    choosing_delivery = State()
    entering_phone = State()
    uploading_receipt = State()


class AddStoreItem(StatesGroup):
    choosing_category = State()
    entering_title = State()
    entering_description = State()
    entering_price = State()
    uploading_photo = State()
    entering_pickup = State()
    entering_min_qty = State()
    choosing_delivery = State()
    entering_phone = State()


class RemoveProduct(StatesGroup):
    entering_id = State()


# ---------- Helpers ----------

def main_menu_keyboard(is_admin: bool = False):
    buttons = [[KeyboardButton(text="🛍 እቃዎን ይሽጡ")]]
    if is_admin:
        buttons.append([KeyboardButton(text="➕ የሱቅ እቃ ያክሉ")])
        buttons.append([KeyboardButton(text="📦 ምርቶችን ያስተዳድሩ")])
        buttons.append([KeyboardButton(text="🗑 ምርት ያስወግዱ")])
    if MINI_APP_URL and MINI_APP_URL != "YOUR_MINI_APP_URL":
        buttons.append([KeyboardButton(text="🏪 ማራጌሊ ገበያን ይመልከቱ", web_app=WebAppInfo(url=MINI_APP_URL))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def category_keyboard(categories):
    buttons = [[InlineKeyboardButton(text=c["name"], callback_data=f"cat:{c['id']}")] for c in categories]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delivery_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚚 አዎ፣ የመላኪያ አገልግሎት አለ", callback_data="deliv:yes"),
            InlineKeyboardButton(text="🏬 አይ፣ በአካል ብቻ መውሰድ", callback_data="deliv:no"),
        ]]
    )


def admin_review_keyboard(listing_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ አጽድቅ", callback_data=f"approve:{listing_id}"),
                InlineKeyboardButton(text="❌ ውድቅ አድርግ", callback_data=f"reject:{listing_id}"),
            ]
        ]
    )


def sold_toggle_keyboard(listing_id: int, status: str, is_store_item: bool):
    if is_store_item:
        label, action = ("✅ እንደሚገኝ ምልክት አድርግ", "onmarket") if status == "sold" else ("🚫 እንደማይገኝ ምልክት አድርግ", "sold")
    else:
        label, action = ("🟢 በገበያ ላይ እንዳለ ምልክት አድርግ", "onmarket") if status == "sold" else ("🔴 እንደተሸጠ ምልክት አድርግ", "sold")
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, callback_data=f"stat:{action}:{listing_id}")]])


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
        f"ሰላም! 👋 እንኳን በሰላም ወደ {SITE_NAME} (ማራጌሊ) ገበያ መጡ!\n\n"
        "በመላው ቴፒ፣ሚዛን እና አማን ካሉ ሰዎች ጋር እዚህ ቴሌግራም ውስጥ ይግዙ እና ይሽጡ።\n\n"
        "ለመጀመር ከታች ያሉትን ቁልፎች(buttons) ተጠቀም",
        reply_markup=main_menu_keyboard(is_admin=is_admin),
    )


@router.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id == ADMIN_TELEGRAM_ID
    await message.answer("ተሰርዟል። ወደ ዋናው ሜኑ ተመልሰዋል።", reply_markup=main_menu_keyboard(is_admin=is_admin))


# ---------- Selling flow: anyone creates one listing (Community Market) ----------

@router.message(F.text == "🛍 እቃዎን ይሽጡ")
async def sell_start(message: Message, state: FSMContext):
    categories = await db.list_categories()
    await state.set_state(SellListing.choosing_category)
    await message.answer("የእርስዎ እቃ የትኛው ምድብ ውስጥ ነው።?", reply_markup=category_keyboard(categories))


@router.callback_query(SellListing.choosing_category, F.data.startswith("cat:"))
async def sell_category_chosen(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    await state.update_data(category_id=category_id)
    await state.set_state(SellListing.entering_title)
    await callback.message.answer("የእቃው ስም? (ለምሳሌ 'Casio calculator')")
    await callback.answer()


@router.message(SellListing.entering_title)
async def sell_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(SellListing.entering_description)
    await message.answer("አጭር መግለጫ ያክሉ (ሁኔታ፣ ዝርዝሮች፣ ወዘተ.):")


@router.message(SellListing.entering_description)
async def sell_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(SellListing.entering_price)
    await message.answer(f"ዋጋው ስንት ነው፣ በ{CURRENCY}? (ቁጥሮች ብቻ ለምሳሌ. 250)")


@router.message(SellListing.entering_price)
async def sell_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("እባክዎ ቁጥር ይላኩ፣ ለምሳሌ 250")
        return
    await state.update_data(price=price)
    await state.set_state(SellListing.uploading_photo)
    await message.answer("አንድ ፎቶ ብቻ ይላኩ፦")


@router.message(SellListing.uploading_photo, F.photo)
async def sell_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(SellListing.entering_pickup)
    await message.answer("እቃው የት ነው የሚገኘው? (ለምሳሌ 'ቴፒ፣ ሚዛን')")


@router.message(SellListing.uploading_photo)
async def sell_photo_invalid(message: Message):
    await message.answer("እባክህ ፎቶ ይላኩ (ጽሑፍ ሳይሆን).")


@router.message(SellListing.entering_pickup)
async def sell_pickup(message: Message, state: FSMContext):
    await state.update_data(pickup_location=message.text)
    await state.set_state(SellListing.entering_min_qty)
    await message.answer("አንድ ገዢ ማዘዝ የሚችለው አነስተኛው የንጥሎች ብዛት ስንት ነው? (ለምሳሌ 1)")


@router.message(SellListing.entering_min_qty)
async def sell_min_qty(message: Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        if qty < 1:
            raise ValueError
    except ValueError:
        await message.answer("እባክዎ ሙሉ ቁጥር ይላኩ፣ ለምሳሌ 1")
        return
    await state.update_data(min_order_qty=qty)
    await state.set_state(SellListing.choosing_delivery)
    await message.answer("ለዚህ ዕቃ የመላኪያ አገልግሎት አለ??", reply_markup=delivery_keyboard())


@router.callback_query(SellListing.choosing_delivery, F.data.startswith("deliv:"))
async def sell_delivery_chosen(callback: CallbackQuery, state: FSMContext):
    is_delivery = callback.data.split(":")[1] == "yes"
    await state.update_data(is_delivery=is_delivery)
    await state.set_state(SellListing.entering_phone)
    await callback.message.answer("በየትኛው ስልክ ቁጥር ገዢዎች እርስዎን ማግኘት አለባቸው?")
    await callback.answer()


@router.message(SellListing.entering_phone)
async def sell_phone(message: Message, state: FSMContext):
    data = await state.update_data(phone_number=message.text.strip())
    user = await db.get_user_by_telegram_id(message.from_user.id)

    listing = await db.create_listing(
        user_id=user["id"],
        category_id=data["category_id"],
        title=data["title"],
        description=data["description"],
        price_etb=data["price"],
        photo_file_id=data["photo_file_id"],
        pickup_location=data["pickup_location"],
        min_order_qty=data["min_order_qty"],
        is_delivery=data["is_delivery"],
        phone_number=data["phone_number"],
    )
    await state.update_data(listing_id=listing["id"])
    await state.set_state(SellListing.uploading_receipt)

    await message.answer(
        "ዝርዝርዎ እንደ ረቂቅ ተቀምጧል። እሱን ለማስለጠፍ እባክዎን ይክፈሉት"
        "ቀጥሎ ከሚዘረዘረው የክፍያ መንገድ አንዱን በመጠቀም 20 ብር ከፍለው የክፍያ ደረሰኝ ፎቶ/ስክሪንሾት ይላኩ"
        "ቴሌ ብር፦ 0992242197"
    )


@router.message(SellListing.uploading_receipt, F.photo)
async def sell_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    receipt_file_id = message.photo[-1].file_id

    await db.create_payment(listing_id=data["listing_id"], receipt_file_id=receipt_file_id)

    await message.answer(
        "እናመሰግናለን! የክፍያ ደረሰኝዎ ለግምገማ ተልኳል። አስተዳዳሪ ዝርዝርዎን "
        "ካጸደቀው ወይም ካልተቀበለው ማሳወቂያ ይደርስዎታል።",
        reply_markup=main_menu_keyboard(),
    )
    await state.clear()

    listing = await db.get_listing(data["listing_id"])
    await bot.send_photo(
        chat_id=ADMIN_TELEGRAM_ID,
        photo=receipt_file_id,
        caption=(
            f"📥 አዲስ ዝርዝር ለግምገማ ተጠባባቂ ነው\n\n"
            f"#{listing['id']} — {listing['title']}\n"
            f"ዋጋ፦ {listing['price_etb']} {CURRENCY}\n"
            f"ቦታ፦ {listing['pickup_location']}\n"
            f"ዝቅተኛ የትዕዛዝ ብዛት፦ {listing['min_order_qty']}\n"
            f"መላኪያ፦ {'አዎ' if listing['is_delivery'] else 'አይ'}\n"
            f"ስልክ፦ {listing['phone_number']}\n"
            f"መግለጫ፦ {listing['description']}"
        ),
        reply_markup=admin_review_keyboard(listing["id"]),
    )


@router.message(SellListing.uploading_receipt)
async def sell_receipt_invalid(message: Message):
    await message.answer("እባክዎ የክፍያ ደረሰኝዎን ፎቶ ይላኩ።")


# ---------- Admin: post a Marageli Store item directly (no payment/review) ----------

@router.message(F.text == "➕ የሱቅ እቃ ያክሉ")
async def store_item_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return  # silently ignore — regular users never see this button anyway

    categories = await db.list_categories()
    await state.set_state(AddStoreItem.choosing_category)
    await message.answer("የሱቅ እቃ — የትኛው ምድብ ነው?", reply_markup=category_keyboard(categories))


@router.callback_query(AddStoreItem.choosing_category, F.data.startswith("cat:"))
async def store_item_category_chosen(callback: CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split(":")[1])
    await state.update_data(category_id=category_id)
    await state.set_state(AddStoreItem.entering_title)
    await callback.message.answer("የእቃው ስም?")
    await callback.answer()


@router.message(AddStoreItem.entering_title)
async def store_item_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddStoreItem.entering_description)
    await message.answer("መግለጫ፦")


@router.message(AddStoreItem.entering_description)
async def store_item_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddStoreItem.entering_price)
    await message.answer(f"ዋጋው ስንት ነው፣ በ{CURRENCY}? (ቁጥሮች ብቻ፣ ለምሳሌ 250)")


@router.message(AddStoreItem.entering_price)
async def store_item_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
    except ValueError:
        await message.answer("እባክዎ ቁጥር ይላኩ፣ ለምሳሌ 250")
        return
    await state.update_data(price=price)
    await state.set_state(AddStoreItem.uploading_photo)
    await message.answer("አንድ ፎቶ ብቻ ይላኩ፦")


@router.message(AddStoreItem.uploading_photo, F.photo)
async def store_item_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(AddStoreItem.entering_pickup)
    await message.answer("ቦታ?")


@router.message(AddStoreItem.uploading_photo)
async def store_item_photo_invalid(message: Message):
    await message.answer("እባክዎ ፎቶ ይላኩ (ጽሑፍ ሳይሆን)።")


@router.message(AddStoreItem.entering_pickup)
async def store_item_pickup(message: Message, state: FSMContext):
    await state.update_data(pickup_location=message.text)
    await state.set_state(AddStoreItem.entering_min_qty)
    await message.answer("አንድ ገዢ ማዘዝ የሚችለው አነስተኛው የንጥሎች ብዛት ስንት ነው? (ለምሳሌ 1)")


@router.message(AddStoreItem.entering_min_qty)
async def store_item_min_qty(message: Message, state: FSMContext):
    try:
        qty = int(message.text.strip())
        if qty < 1:
            raise ValueError
    except ValueError:
        await message.answer("እባክዎ ሙሉ ቁጥር ይላኩ፣ ለምሳሌ 1")
        return
    await state.update_data(min_order_qty=qty)
    await state.set_state(AddStoreItem.choosing_delivery)
    await message.answer("የመላኪያ አገልግሎት አለ?", reply_markup=delivery_keyboard())


@router.callback_query(AddStoreItem.choosing_delivery, F.data.startswith("deliv:"))
async def store_item_delivery_chosen(callback: CallbackQuery, state: FSMContext):
    is_delivery = callback.data.split(":")[1] == "yes"
    await state.update_data(is_delivery=is_delivery)
    await state.set_state(AddStoreItem.entering_phone)
    await callback.message.answer("ለዚህ እቃ የሚገናኙበት ስልክ ቁጥር?")
    await callback.answer()


@router.message(AddStoreItem.entering_phone)
async def store_item_phone(message: Message, state: FSMContext):
    data = await state.update_data(phone_number=message.text.strip())
    user = await db.get_user_by_telegram_id(message.from_user.id)

    listing = await db.create_listing(
        user_id=user["id"],
        category_id=data["category_id"],
        title=data["title"],
        description=data["description"],
        price_etb=data["price"],
        photo_file_id=data["photo_file_id"],
        pickup_location=data["pickup_location"],
        min_order_qty=data["min_order_qty"],
        is_delivery=data["is_delivery"],
        phone_number=data["phone_number"],
        is_store_item=True,  # goes straight to status='approved', no payment step
    )
    await state.clear()

    await message.answer(
        f"✅ '{listing['title']}' ወደ ማራጌሊ ሱቅ ታትሟል — አሁን በሚኒ አፕ ላይ ይገኛል።",
        reply_markup=main_menu_keyboard(is_admin=True),
    )
    await message.answer(
        f"#{listing['id']} — {listing['title']}",
        reply_markup=sold_toggle_keyboard(listing["id"], "approved", is_store_item=True),
    )


# ---------- Admin: toggle Sold/On Market or Available/Not Available ----------

@router.callback_query(F.data.startswith("stat:"))
async def toggle_listing_status(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("ለአስተዳዳሪዎች ብቻ።", show_alert=True)
        return

    _, action, listing_id_str = callback.data.split(":")
    listing_id = int(listing_id_str)
    listing = await db.get_listing(listing_id)
    if not listing:
        await callback.answer("ያ ዝርዝር ከአሁን በኋላ የለም።", show_alert=True)
        return

    if action == "sold":
        await db.mark_listing_sold(listing_id)
        new_status = "sold"
    else:
        await db.mark_listing_on_market(listing_id)
        new_status = "approved"

    await callback.message.edit_reply_markup(
        reply_markup=sold_toggle_keyboard(listing_id, new_status, bool(listing["is_store_item"]))
    )
    await callback.answer("ተዘምኗል ✅ — ለውጡ አሁን በሚኒ አፕ ላይ ታይቷል።")


@router.message(F.text == "📦 ምርቶችን ያስተዳድሩ")
async def manage_products(message: Message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return
    listings = await db.list_manageable_listings()
    if not listings:
        await message.answer("እስካሁን ምንም በገበያ ላይ ያሉ ምርቶች የሉም።")
        return
    for listing in listings:
        is_store = bool(listing["is_store_item"])
        if is_store:
            label = "✅ ይገኛል" if listing["status"] == "approved" else "🚫 አይገኝም"
        else:
            label = "🟢 በገበያ ላይ" if listing["status"] == "approved" else "🔴 ተሽጧል"
        tab = "ማራጌሊ ሱቅ" if is_store else "የማህበረሰብ ገበያ"
        await message.answer(
            f"#{listing['id']} — {listing['title']} — {listing['price_etb']} {CURRENCY}\n"
            f"{tab} · {label}",
            reply_markup=sold_toggle_keyboard(listing["id"], listing["status"], is_store),
        )


@router.message(Command("products"))
async def products_command(message: Message):
    await manage_products(message)


# ---------- Admin: remove a product by ID ----------

@router.message(F.text == "🗑 ምርት ያስወግዱ")
async def remove_product_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return
    await state.set_state(RemoveProduct.entering_id)
    await message.answer(
        "ለማስወገድ የምርቱን ID (ከምርቱ ስር የሚታየውን ትንሽ 'ቁ. X' ቁጥር) ይላኩ።\n"
        "ይህ ሊመለስ አይችልም። ለመሰረዝ /cancel ይላኩ።"
    )


@router.message(RemoveProduct.entering_id)
async def remove_product_id_entered(message: Message, state: FSMContext):
    try:
        listing_id = int(message.text.strip().lstrip("#"))
    except ValueError:
        await message.answer("እባክዎ ቁጥሩን ብቻ ይላኩ፣ ለምሳሌ 12")
        return

    listing = await db.get_listing(listing_id)
    if not listing:
        await message.answer(f"በID {listing_id} የተገኘ ምርት የለም። እንደገና ይሞክሩ ወይም /cancel ይላኩ።")
        return

    await db.delete_listing(listing_id)
    await state.clear()
    await message.answer(
        f"🗑 #{listing_id} — '{listing['title']}' ተወግዷል። አሁን ከሚኒ አፕ ላይ ተወግዷል።",
        reply_markup=main_menu_keyboard(is_admin=True),
    )


@router.message(Command("remove"))
async def remove_command(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return
    parts = message.text.split()
    if len(parts) == 2 and parts[1].isdigit():
        listing_id = int(parts[1])
        listing = await db.get_listing(listing_id)
        if not listing:
            await message.answer(f"በID {listing_id} የተገኘ ምርት የለም።")
            return
        await db.delete_listing(listing_id)
        await message.answer(f"🗑 #{listing_id} — '{listing['title']}' ተወግዷል።")
    else:
        await remove_product_start(message, state)


# ---------- Admin: approve / reject (listings) ----------

@router.callback_query(F.data.startswith("approve:"))
async def approve_listing(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("ለአስተዳዳሪዎች ብቻ።", show_alert=True)
        return

    listing_id = int(callback.data.split(":")[1])
    listing = await db.get_listing(listing_id)
    await db.set_listing_status(listing_id, "approved")
    await db.set_payment_status(listing_id, "approved")

    await callback.message.edit_caption(
        caption=callback.message.caption + "\n\n✅ ጸድቋል",
        reply_markup=sold_toggle_keyboard(listing_id, "approved", bool(listing["is_store_item"])),
    )
    await callback.answer("ጸድቋል")

    seller = await db.query("SELECT telegram_id FROM users WHERE id = ?", [listing["user_id"]])
    if seller:
        await bot.send_message(seller[0]["telegram_id"], f"🎉 የእርስዎ ዝርዝር '{listing['title']}' ጸድቋል እና አሁን በገበያ ላይ ነው!")


@router.callback_query(F.data.startswith("reject:"))
async def reject_listing(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_TELEGRAM_ID:
        await callback.answer("ለአስተዳዳሪዎች ብቻ።", show_alert=True)
        return

    listing_id = int(callback.data.split(":")[1])
    listing = await db.get_listing(listing_id)
    await db.set_listing_status(listing_id, "rejected")
    await db.set_payment_status(listing_id, "rejected")

    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ ውድቅ ተደርጓል")
    await callback.answer("ውድቅ ተደርጓል")

    seller = await db.query("SELECT telegram_id FROM users WHERE id = ?", [listing["user_id"]])
    if seller:
        await bot.send_message(
            seller[0]["telegram_id"],
            f"የእርስዎ ዝርዝር '{listing['title']}' ውድቅ ተደርጓል። ጥያቄ ካለዎት አስተዳዳሪውን ያግኙ።",
        )


@router.message(Command("pending"))
async def pending_command(message: Message):
    if message.from_user.id != ADMIN_TELEGRAM_ID:
        return
    pending = await db.list_pending_review_listings()
    if not pending:
        await message.answer("ለግምገማ የሚጠባበቅ ምንም ዝርዝር የለም። 🎉")
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
