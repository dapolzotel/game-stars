import asyncio
import logging
import sqlite3
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties

# ============================================================
#  НАСТРОЙКИ — заполни перед запуском
# ============================================================
BOT_TOKEN    = "8049073072:AAHDFhP7z3DG3I_CALdtrcIx7JbohKBMV_c"   # токен от @BotFather
BOT_USERNAME = "gamestarsykbot"     # username бота БЕЗ @
ADMIN_ID     = 7681037970               # ← ТВОЙ Telegram ID (узнай у @userinfobot)

SPONSORS = [
    {"name": "doozmbot",    "channel_id": "@doozmbot"},
    {"name": "suetastarss", "channel_id": "@suetastarss"},
    {"name": "imasta4",     "channel_id": "@imasta4"},
    {"name": "mxdarka",     "channel_id": "@mxdarka"},
]

STARS_PER_REFERRAL = 8
DB_FILE = "database.db"
WITHDRAW_OPTIONS = [15, 25, 50, 100]

# ============================================================
#  FSM — состояния
# ============================================================
class AdminStates(StatesGroup):
    waiting_broadcast   = State()   # ждём текст рассылки
    waiting_promo_name  = State()   # ждём название промокода
    waiting_promo_stars = State()   # ждём кол-во звёзд
    waiting_promo_uses  = State()   # ждём кол-во использований

class UserStates(StatesGroup):
    waiting_promo = State()         # ждём ввод промокода от юзера

# ============================================================
#  БАЗА ДАННЫХ — SQLite
# ============================================================
def get_conn():
    return sqlite3.connect(DB_FILE)

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                stars       INTEGER DEFAULT 0,
                referrals   INTEGER DEFAULT 0,
                invited_by  INTEGER DEFAULT NULL,
                joined_at   TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_list (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id     INTEGER,
                referral_id     INTEGER,
                referral_name   TEXT,
                earned_stars    INTEGER,
                joined_at       TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                amount      INTEGER,
                status      TEXT DEFAULT 'pending',
                created_at  TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT UNIQUE,
                stars       INTEGER,
                max_uses    INTEGER,
                used_count  INTEGER DEFAULT 0,
                is_active   INTEGER DEFAULT 1,
                created_at  TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_uses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id    INTEGER,
                user_id     INTEGER,
                used_at     TEXT,
                UNIQUE(promo_id, user_id)
            )
        """)
        conn.commit()

# ---- пользователи ----
def is_new_user(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return row is None

def create_user(user_id: int, username: str, first_name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at) VALUES (?, ?, ?, ?)",
            (user_id, username or "", first_name or "", datetime.now().isoformat())
        )
        conn.commit()

def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    cols = ["user_id", "username", "first_name", "stars", "referrals", "invited_by", "joined_at"]
    return dict(zip(cols, row))

def get_all_user_ids() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
    return [r[0] for r in rows]

def get_stats() -> dict:
    with get_conn() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        stars    = conn.execute("SELECT SUM(stars) FROM users").fetchone()[0] or 0
        withdraws = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
    return {"total": total, "stars": stars, "pending_withdraws": withdraws}

def add_stars(user_id: int, amount: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def deduct_stars(user_id: int, amount: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET stars = stars - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def set_invited_by(user_id: int, referrer_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (referrer_id, user_id))
        conn.commit()

def increment_referrals(referrer_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id = ?", (referrer_id,))
        conn.commit()

def add_referral_record(referrer_id: int, referral_id: int, referral_name: str, stars: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO referral_list (referrer_id, referral_id, referral_name, earned_stars, joined_at) VALUES (?, ?, ?, ?, ?)",
            (referrer_id, referral_id, referral_name, stars, datetime.now().isoformat())
        )
        conn.commit()

def get_referral_list(referrer_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT referral_name, earned_stars, joined_at FROM referral_list WHERE referrer_id = ? ORDER BY joined_at DESC LIMIT 10",
            (referrer_id,)
        ).fetchall()
    return rows

def add_withdrawal(user_id: int, amount: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO withdrawals (user_id, amount, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user_id, amount, datetime.now().isoformat())
        )
        conn.commit()

def get_withdrawal_history(user_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT amount, status, created_at FROM withdrawals WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        ).fetchall()
    return rows

# ---- промокоды ----
def create_promo(code: str, stars: int, max_uses: int) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO promo_codes (code, stars, max_uses, created_at) VALUES (?, ?, ?, ?)",
                (code.upper(), stars, max_uses, datetime.now().isoformat())
            )
            conn.commit()
        return True
    except Exception:
        return False

def get_all_promos() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, code, stars, max_uses, used_count, is_active FROM promo_codes ORDER BY id DESC"
        ).fetchall()
    return rows

def delete_promo(promo_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM promo_codes WHERE id = ?", (promo_id,))
        conn.execute("DELETE FROM promo_uses WHERE promo_id = ?", (promo_id,))
        conn.commit()

def toggle_promo(promo_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE promo_codes SET is_active = 1 - is_active WHERE id = ?", (promo_id,))
        conn.commit()

def use_promo(code: str, user_id: int) -> tuple:
    """Возвращает (успех: bool, сообщение: str, звёзды: int)"""
    with get_conn() as conn:
        promo = conn.execute(
            "SELECT id, stars, max_uses, used_count, is_active FROM promo_codes WHERE code = ?",
            (code.upper(),)
        ).fetchone()

        if not promo:
            return False, "❌ Промокод не найден.", 0

        promo_id, stars, max_uses, used_count, is_active = promo

        if not is_active:
            return False, "❌ Промокод неактивен.", 0

        if used_count >= max_uses:
            return False, "❌ Промокод уже исчерпан.", 0

        already = conn.execute(
            "SELECT id FROM promo_uses WHERE promo_id = ? AND user_id = ?",
            (promo_id, user_id)
        ).fetchone()
        if already:
            return False, "❌ Ты уже использовал этот промокод.", 0

        conn.execute(
            "INSERT INTO promo_uses (promo_id, user_id, used_at) VALUES (?, ?, ?)",
            (promo_id, user_id, datetime.now().isoformat())
        )
        conn.execute(
            "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?",
            (promo_id,)
        )
        conn.commit()

    add_stars(user_id, stars)
    return True, f"✅ Промокод активирован! Тебе начислено <b>+{stars} ⭐</b>", stars

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
        [InlineKeyboardButton(text="🎟 Ввести промокод",   callback_data="enter_promo")],
    ])

def back_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu")]])

def admin_back_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Админ-панель", callback_data="admin_panel")]])

def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мои рефералы",    callback_data="my_refs")],
        [InlineKeyboardButton(text="📜 История выводов", callback_data="withdraw_history")],
        [InlineKeyboardButton(text="🔙 Главное меню",    callback_data="menu")],
    ])

def withdraw_keyboard(stars: int) -> InlineKeyboardMarkup:
    buttons = []
    for amount in WITHDRAW_OPTIONS:
        if stars >= amount:
            buttons.append([InlineKeyboardButton(text=f"💸 Вывести {amount} ⭐", callback_data=f"do_withdraw_{amount}")])
        else:
            buttons.append([InlineKeyboardButton(text=f"🔒 {amount} ⭐  (не хватает)", callback_data="not_enough")])
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка",         callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🎟 Промокоды",        callback_data="admin_promos")],
        [InlineKeyboardButton(text="📊 Статистика",       callback_data="admin_stats")],
    ])

def promos_keyboard(promos: list) -> InlineKeyboardMarkup:
    buttons = []
    for pid, code, stars, max_uses, used, is_active in promos:
        status = "✅" if is_active else "🔴"
        buttons.append([
            InlineKeyboardButton(text=f"{status} {code} | {stars}⭐ | {used}/{max_uses}", callback_data=f"promo_info_{pid}"),
        ])
    buttons.append([InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_create_promo")])
    buttons.append([InlineKeyboardButton(text="🔙 Админ-панель",    callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def promo_manage_keyboard(promo_id: int, is_active: int) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Деактивировать" if is_active else "✅ Активировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text,          callback_data=f"promo_toggle_{promo_id}")],
        [InlineKeyboardButton(text="🗑 Удалить промокод", callback_data=f"promo_delete_{promo_id}")],
        [InlineKeyboardButton(text="🔙 К промокодам",    callback_data="admin_promos")],
    ])

# ============================================================
#  БОТ
# ============================================================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp  = Dispatcher(storage=MemoryStorage())

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ============================================================
#  ПОЛЬЗОВАТЕЛЬСКИЕ ХЭНДЛЕРЫ
# ============================================================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id    = message.from_user.id
    username   = message.from_user.username or ""
    first_name = message.from_user.first_name or "Пользователь"
    args       = message.text.split()
    new_user   = is_new_user(user_id)

    create_user(user_id, username, first_name)

    if new_user and len(args) > 1:
        try:
            referrer_id = int(args[1])
            if referrer_id != user_id and get_user(referrer_id):
                set_invited_by(user_id, referrer_id)
                add_stars(referrer_id, STARS_PER_REFERRAL)
                increment_referrals(referrer_id)
                add_referral_record(referrer_id, user_id, first_name, STARS_PER_REFERRAL)
                try:
                    await bot.send_message(
                        referrer_id,
                        f"🎉 По вашей ссылке зарегистрировался <b>{first_name}</b>!\n"
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
            f"👋 Привет, <b>{first_name}</b>!\n\n✅ Все подписки активны.\nВыбери раздел:",
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
async def go_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
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
    uname  = f"@{user['username']}" if user['username'] else "—"
    joined = user['joined_at'][:10] if user['joined_at'] else "—"
    await call.message.edit_text(
        "👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Username: {uname}\n"
        f"⭐ Звёзд: <b>{user['stars']}</b>\n"
        f"👥 Рефералов: <b>{user['referrals']}</b>\n"
        f"📅 Дата регистрации: {joined}",
        reply_markup=profile_keyboard()
    )

@dp.callback_query(F.data == "my_refs")
async def my_refs(call: types.CallbackQuery):
    refs = get_referral_list(call.from_user.id)
    if not refs:
        text = "👥 <b>Мои рефералы</b>\n\nУ тебя пока нет рефералов.\nПоделись ссылкой из раздела ⭐ Заработать звёзды!"
    else:
        lines = ["👥 <b>Мои рефералы (последние 10)</b>\n"]
        for i, (name, earned, joined) in enumerate(refs, 1):
            date = joined[:10] if joined else "—"
            lines.append(f"{i}. <b>{name}</b> — +{earned} ⭐ — {date}")
        text = "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_btn())

@dp.callback_query(F.data == "withdraw_history")
async def withdraw_history(call: types.CallbackQuery):
    history = get_withdrawal_history(call.from_user.id)
    if not history:
        text = "📜 <b>История выводов</b>\n\nВыводов пока не было."
    else:
        status_emoji = {"pending": "⏳", "paid": "✅", "rejected": "❌"}
        lines = ["📜 <b>История выводов (последние 5)</b>\n"]
        for amount, status, created_at in history:
            date  = created_at[:10] if created_at else "—"
            emoji = status_emoji.get(status, "⏳")
            lines.append(f"{emoji} {amount} ⭐ — {date}")
        text = "\n".join(lines)
    await call.message.edit_text(text, reply_markup=back_btn())

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
    deduct_stars(call.from_user.id, amount)
    add_withdrawal(call.from_user.id, amount)
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"✅ <b>Заявка на вывод {amount} ⭐ принята!</b>\n\n"
        "Выплата будет произведена в течение <b>24 часов</b>.\n\n"
        f"Остаток на балансе: <b>{user['stars']} ⭐</b>",
        reply_markup=back_btn()
    )

@dp.callback_query(F.data == "not_enough")
async def not_enough(call: types.CallbackQuery):
    await call.answer("❌ Недостаточно звёзд для вывода!", show_alert=True)

# ---- промокоды для юзеров ----
@dp.callback_query(F.data == "enter_promo")
async def enter_promo(call: types.CallbackQuery, state: FSMContext):
    unsubscribed = await get_unsubscribed(bot, call.from_user.id)
    if unsubscribed:
        await call.answer("Сначала подпишись на каналы!", show_alert=True)
        return
    await state.set_state(UserStates.waiting_promo)
    await call.message.edit_text(
        "🎟 <b>Ввести промокод</b>\n\nНапиши промокод:",
        reply_markup=back_btn()
    )

@dp.message(UserStates.waiting_promo)
async def process_promo(message: types.Message, state: FSMContext):
    await state.clear()
    code = message.text.strip()
    success, msg, _ = use_promo(code, message.from_user.id)
    await message.answer(msg, reply_markup=main_menu())

# ============================================================
#  АДМИН ХЭНДЛЕРЫ
# ============================================================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "🔐 <b>Админ-панель</b>\n\nДобро пожаловать, хозяин!",
        reply_markup=admin_menu_keyboard()
    )

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_cb(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    await call.message.edit_text(
        "🔐 <b>Админ-панель</b>",
        reply_markup=admin_menu_keyboard()
    )

# ---- статистика ----
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    s = get_stats()
    await call.message.edit_text(
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{s['total']}</b>\n"
        f"⭐ Всего звёзд на балансах: <b>{s['stars']}</b>\n"
        f"⏳ Заявок на вывод (ожидают): <b>{s['pending_withdraws']}</b>",
        reply_markup=admin_back_btn()
    )

# ---- рассылка ----
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await call.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Напиши сообщение которое хочешь разослать всем пользователям.\n"
        "Поддерживается HTML-форматирование: <b>жирный</b>, <i>курсив</i>, <code>код</code>\n\n"
        "Для отмены напиши /admin",
        reply_markup=None
    )

@dp.message(AdminStates.waiting_broadcast)
async def admin_broadcast_send(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()

    user_ids = get_all_user_ids()
    text     = message.text or message.caption or ""

    sent = 0
    failed = 0
    status_msg = await message.answer(f"⏳ Начинаю рассылку на {len(user_ids)} пользователей...")

    for uid in user_ids:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от администратора:</b>\n\n{text}")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # защита от флуда

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>",
        reply_markup=admin_back_btn()
    )

# ---- промокоды (управление) ----
@dp.callback_query(F.data == "admin_promos")
async def admin_promos(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    promos = get_all_promos()
    if not promos:
        text = "🎟 <b>Промокоды</b>\n\nПромокодов пока нет."
    else:
        text = "🎟 <b>Промокоды</b>\n\nНажми на промокод для управления:"
    await call.message.edit_text(text, reply_markup=promos_keyboard(promos))

@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminStates.waiting_promo_name)
    await call.message.edit_text(
        "➕ <b>Создание промокода</b>\n\nВведи название промокода (только латиница и цифры):\nПример: <code>SUMMER2024</code>",
        reply_markup=None
    )

@dp.message(AdminStates.waiting_promo_name)
async def admin_promo_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip().upper()
    if not code.replace("_", "").isalnum():
        await message.answer("❌ Название должно содержать только латинские буквы и цифры. Попробуй снова:")
        return
    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.waiting_promo_stars)
    await message.answer(f"✅ Код: <b>{code}</b>\n\nСколько ⭐ звёзд будет начисляться?")

@dp.message(AdminStates.waiting_promo_stars)
async def admin_promo_stars(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        stars = int(message.text.strip())
        if stars <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число звёзд:")
        return
    await state.update_data(promo_stars=stars)
    await state.set_state(AdminStates.waiting_promo_uses)
    await message.answer(f"✅ Звёзд: <b>{stars} ⭐</b>\n\nСколько раз можно использовать промокод?\n(Введи число, например <code>100</code> или <code>1</code> для одноразового)")

@dp.message(AdminStates.waiting_promo_uses)
async def admin_promo_uses(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        max_uses = int(message.text.strip())
        if max_uses <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число использований:")
        return

    data = await state.get_data()
    await state.clear()

    code     = data["promo_code"]
    stars    = data["promo_stars"]
    success  = create_promo(code, stars, max_uses)

    if success:
        await message.answer(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"🎟 Код: <code>{code}</code>\n"
            f"⭐ Звёзд: <b>{stars}</b>\n"
            f"🔢 Использований: <b>{max_uses}</b>",
            reply_markup=admin_back_btn()
        )
    else:
        await message.answer(
            "❌ Промокод с таким названием уже существует. Попробуй другое название.",
            reply_markup=admin_back_btn()
        )

@dp.callback_query(F.data.startswith("promo_info_"))
async def promo_info(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    promo_id = int(call.data.split("_")[-1])
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, code, stars, max_uses, used_count, is_active, created_at FROM promo_codes WHERE id = ?",
            (promo_id,)
        ).fetchone()
    if not row:
        await call.answer("Промокод не найден", show_alert=True)
        return
    pid, code, stars, max_uses, used, is_active, created = row
    status = "✅ Активен" if is_active else "🔴 Неактивен"
    date   = created[:10] if created else "—"
    await call.message.edit_text(
        f"🎟 <b>Промокод: {code}</b>\n\n"
        f"📌 Статус: {status}\n"
        f"⭐ Звёзд за активацию: <b>{stars}</b>\n"
        f"🔢 Использований: <b>{used}/{max_uses}</b>\n"
        f"📅 Создан: {date}",
        reply_markup=promo_manage_keyboard(pid, is_active)
    )

@dp.callback_query(F.data.startswith("promo_toggle_"))
async def promo_toggle(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    promo_id = int(call.data.split("_")[-1])
    toggle_promo(promo_id)
    await call.answer("✅ Статус промокода изменён!")
    # обновляем инфо
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, code, stars, max_uses, used_count, is_active, created_at FROM promo_codes WHERE id = ?",
            (promo_id,)
        ).fetchone()
    if row:
        pid, code, stars, max_uses, used, is_active, created = row
        status = "✅ Активен" if is_active else "🔴 Неактивен"
        date   = created[:10] if created else "—"
        await call.message.edit_text(
            f"🎟 <b>Промокод: {code}</b>\n\n"
            f"📌 Статус: {status}\n"
            f"⭐ Звёзд за активацию: <b>{stars}</b>\n"
            f"🔢 Использований: <b>{used}/{max_uses}</b>\n"
            f"📅 Создан: {date}",
            reply_markup=promo_manage_keyboard(pid, is_active)
        )

@dp.callback_query(F.data.startswith("promo_delete_"))
async def promo_delete(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    promo_id = int(call.data.split("_")[-1])
    delete_promo(promo_id)
    await call.answer("🗑 Промокод удалён!")
    promos = get_all_promos()
    text   = "🎟 <b>Промокоды</b>\n\nНажми на промокод для управления:" if promos else "🎟 <b>Промокоды</b>\n\nПромокодов пока нет."
    await call.message.edit_text(text, reply_markup=promos_keyboard(promos))

# ============================================================
#  ЗАПУСК
# ============================================================
async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
