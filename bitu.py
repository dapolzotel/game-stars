import asyncio
import logging
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage

# ============================================================
#  НАСТРОЙКИ — заполни перед запуском
# ============================================================
BOT_TOKEN    = "8049073072:AAHDFhP7z3DG3I_CALdtrcIx7JbohKBMV_c"   # токен от @BotFather
BOT_USERNAME = "gamestarsykbot"     # username бота БЕЗ @

SPONSORS = [
    {"name": "doozmbot",    "channel_id": "@doozmbot"},
    {"name": "suetastarss", "channel_id": "@suetastarss"},
    {"name": "gamestarsyknews", "channel_id": "@gamestarsyknews"},
    {"name": "imasta4",     "channel_id": "@imasta4"},
    {"name": "mxdarka",     "channel_id": "@mxdarka"},
]

STARS_PER_REFERRAL = 8
DATA_FILE = "users.json"
WITHDRAW_OPTIONS = [15, 25, 50, 100]

# ============================================================
#  БАЗА ДАННЫХ (JSON-файл)
# ============================================================
def load_db() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_db(db: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def is_new_user(user_id: int) -> bool:
    return str(user_id) not in load_db()

def get_user(user_id: int) -> dict:
    db = load_db()
    uid = str(user_id)
    if uid not in db:
        db[uid] = {"stars": 0, "referrals": 0, "invited_by": None, "joined": datetime.now().isoformat()}
        save_db(db)
    return db[uid]

def update_user(user_id: int, data: dict):
    db = load_db()
    db[str(user_id)] = data
    save_db(db)

# ============================================================
#  ПРОВЕРКА ПОДПИСОК
# ============================================================
async def get_unsubscribed(bot: Bot, user_id: int) -> list:
    result = []
    for sponsor in SPONSORS:
        try:
            member = await bot.get_chat_member(sponsor["channel_id"], user_id)
            if member.status in ("left", "kicked"):
                result.append(sponsor)
        except Exception:
            result.append(sponsor)
    return result

# ============================================================
#  КЛАВИАТУРЫ
# ============================================================
def sub_keyboard(unsubscribed: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=f"📢 Подписаться на @{s['name']}", url=f"https://t.me/{s['name']}")] for s in unsubscribed]
    buttons.append([InlineKeyboardButton(text="✅ Я подписался — проверить", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Заработать звёзды", callback_data="earn")],
        [InlineKeyboardButton(text="👤 Профиль",           callback_data="profile")],
        [InlineKeyboardButton(text="💸 Вывод",             callback_data="withdraw")],
    ])

def back_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu")]])

def withdraw_keyboard(stars: int) -> InlineKeyboardMarkup:
    buttons = []
    for amount in WITHDRAW_OPTIONS:
        if stars >= amount:
            buttons.append([InlineKeyboardButton(text=f"💸 Вывести {amount} ⭐", callback_data=f"do_withdraw_{amount}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"🔒 {amount} ⭐  (не хватает звёзд)", callback_data="not_enough")])
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================================
#  БОТ
# ============================================================
logging.basicConfig(level=logging.INFO)
from aiogram.client.default import DefaultBotProperties
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id  = message.from_user.id
    args     = message.text.split()
    new_user = is_new_user(user_id)

    user = get_user(user_id)  # создаём запись если нет

    # Реферал засчитывается ТОЛЬКО новому пользователю
    if new_user and len(args) > 1:
        try:
            referrer_id = int(args[1])
            if referrer_id != user_id:
                user["invited_by"] = referrer_id
                update_user(user_id, user)

                referrer = get_user(referrer_id)
                referrer["stars"]     += STARS_PER_REFERRAL
                referrer["referrals"] += 1
                update_user(referrer_id, referrer)

                try:
                    await bot.send_message(
                        referrer_id,
                        f"🎉 По вашей ссылке зарегистрировался новый пользователь!\n"
                        f"Вам начислено <b>+{STARS_PER_REFERRAL} ⭐</b>"
                    )
                except Exception:
                    pass
        except (ValueError, IndexError):
            pass

    unsubscribed = await get_unsubscribed(bot, user_id)
    if unsubscribed:
        await message.answer(
            "👋 Привет!\n\n🔒 Для доступа к боту подпишись на наших партнёров:",
            reply_markup=sub_keyboard(unsubscribed)
        )
    else:
        await message.answer(
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n✅ Все подписки активны.\nВыбери раздел:",
            reply_markup=main_menu()
        )

@dp.callback_query(F.data == "check_sub")
async def check_sub(call: types.CallbackQuery):
    unsubscribed = await get_unsubscribed(bot, call.from_user.id)
    if unsubscribed:
        await call.answer("❌ Ты ещё не подписался на все каналы!", show_alert=True)
        await call.message.edit_text("🔒 Подпишись на все каналы и нажми кнопку снова:", reply_markup=sub_keyboard(unsubscribed))
    else:
        await call.message.edit_text(
            f"✅ Отлично, <b>{call.from_user.first_name}</b>! Подписки подтверждены.\n\nВыбери раздел:",
            reply_markup=main_menu()
        )

@dp.callback_query(F.data == "menu")
async def go_menu(call: types.CallbackQuery):
    unsubscribed = await get_unsubscribed(bot, call.from_user.id)
    if unsubscribed:
        await call.message.edit_text("🔒 Подпишись на все каналы:", reply_markup=sub_keyboard(unsubscribed))
        return
    await call.message.edit_text("Выбери раздел:", reply_markup=main_menu())

@dp.callback_query(F.data == "earn")
async def earn_stars(call: types.CallbackQuery):
    unsubscribed = await get_unsubscribed(bot, call.from_user.id)
    if unsubscribed:
        await call.answer("Сначала подпишись на каналы!", show_alert=True)
        return
    ref_link = f"https://t.me/{BOT_USERNAME}?start={call.from_user.id}"
    await call.message.edit_text(
        "⭐ <b>Заработать звёзды</b>\n\n"
        f"Твоя реферальная ссылка:\n<code>{ref_link}</code>\n\n"
        f"За каждого нового пользователя, который впервые запустит бота по твоей ссылке, "
        f"тебе начислится <b>{STARS_PER_REFERRAL} ⭐</b> и +1 реферал в профиль.\n\n"
        "📌 Реферал засчитывается только если человек <b>впервые</b> открывает бота.",
        reply_markup=back_btn()
    )

@dp.callback_query(F.data == "profile")
async def profile(call: types.CallbackQuery):
    unsubscribed = await get_unsubscribed(bot, call.from_user.id)
    if unsubscribed:
        await call.answer("Сначала подпишись на каналы!", show_alert=True)
        return
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        "👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{call.from_user.id}</code>\n"
        f"⭐ Звёзд: <b>{user['stars']}</b>\n"
        f"👥 Рефералов: <b>{user['referrals']}</b>",
        reply_markup=back_btn()
    )

@dp.callback_query(F.data == "withdraw")
async def withdraw(call: types.CallbackQuery):
    unsubscribed = await get_unsubscribed(bot, call.from_user.id)
    if unsubscribed:
        await call.answer("Сначала подпишись на каналы!", show_alert=True)
        return
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"💸 <b>Вывод звёзд</b>\n\nУ тебя сейчас: <b>{user['stars']} ⭐</b>\n\nВыбери сумму для вывода:",
        reply_markup=withdraw_keyboard(user["stars"])
    )

@dp.callback_query(F.data.startswith("do_withdraw_"))
async def do_withdraw(call: types.CallbackQuery):
    amount = int(call.data.split("_")[-1])
    user   = get_user(call.from_user.id)
    if user["stars"] < amount:
        await call.answer("❌ Недостаточно звёзд!", show_alert=True)
        return
    user["stars"] -= amount
    update_user(call.from_user.id, user)
    await call.message.edit_text(
        f"✅ <b>Заявка на вывод {amount} ⭐ принята!</b>\n\n"
        "Выплата будет произведена в течение <b>24 часов</b>.\n\n"
        f"Остаток на балансе: <b>{user['stars']} ⭐</b>",
        reply_markup=back_btn()
    )

@dp.callback_query(F.data == "not_enough")
async def not_enough(call: types.CallbackQuery):
    await call.answer("❌ Недостаточно звёзд для вывода!", show_alert=True)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
