#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import os
import sqlite3
import time
import threading
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан в переменных окружения")

ADMIN_ID = int(os.getenv("ADMIN_ID", "8145260053"))
PORT = int(os.getenv("PORT", "8080"))

PRICE = 35

CARD_DETAILS = """
💳 *Оплата банковской картой*

🏦 *Тинькофф Банк*
💳 Номер карты: `2200702150754195`
👤 Получатель: *Баймакулова А.*

💰 *Сумма:* 35 ₽

📌 *После перевода отправьте СКРИНШОТ чека сюда.*
"""

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== БАЗА ДАННЫХ ====================
DB_PATH = "orders.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            price INTEGER,
            status TEXT DEFAULT 'waiting',
            created_at INTEGER,
            nickname TEXT,
            server TEXT,
            password TEXT,
            screenshot_file_id TEXT,
            completed_at INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_order(user_id, username, nickname, server, password):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (user_id, username, price, created_at, status, nickname, server, password)
        VALUES (?, ?, ?, ?, 'waiting', ?, ?, ?)
    ''', (user_id, username, PRICE, int(time.time()), nickname, server, password))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def update_order_screenshot(order_id, file_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET screenshot_file_id = ? WHERE id = ?", (file_id, order_id))
    conn.commit()
    conn.close()

def update_order_status(order_id, status, completed_at=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if completed_at:
        cursor.execute("UPDATE orders SET status = ?, completed_at = ? WHERE id = ?", (status, completed_at, order_id))
    else:
        cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()

def get_order(order_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_all_orders_by_status(status=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if status:
        cursor.execute("SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC", (status,))
    else:
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_user_orders(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, price, status, created_at, nickname, server FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    orders = cursor.fetchall()
    conn.close()
    return orders

# ==================== FSM СОСТОЯНИЯ ====================
class OrderStates(StatesGroup):
    waiting_nickname = State()
    waiting_server = State()
    waiting_password = State()
    waiting_screenshot = State()

# ==================== КЛАВИАТУРЫ ====================
def main_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 ЗАКАЗАТЬ ПРОКАЧКУ (24ч)", callback_data="new_order")],
        [InlineKeyboardButton(text="📊 МОИ ЗАКАЗЫ", callback_data="my_orders")],
        [InlineKeyboardButton(text="ℹ️ О ПРОКАЧКЕ", callback_data="about")],
        [InlineKeyboardButton(text="🆘 ПОДДЕРЖКА", callback_data="support")]
    ])
    return kb

def admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 ВСЕ ЗАКАЗЫ", callback_data="admin_all")],
        [InlineKeyboardButton(text="⏳ НОВЫЕ (ожидают оплаты)", callback_data="admin_waiting")],
        [InlineKeyboardButton(text="🔄 В РАБОТЕ", callback_data="admin_processing")],
        [InlineKeyboardButton(text="✅ ВЫПОЛНЕННЫЕ", callback_data="admin_completed")],
        [InlineKeyboardButton(text="◀ НАЗАД", callback_data="back_main")]
    ])
    return kb

def servers_keyboard():
    servers = [
        "RED", "GREEN", "BLUE", "YELLOW", "ORANGE", "PURPLE", "LIME", "PINK", "CHERRY", "BLACK",
        "INDIGO", "WHITE", "MAGENTA", "CRIMSON", "GOLD", "AZURE", "PLATINUM", "AQUA", "GRAY", "ICE",
        "CHILLI", "CHOCO", "MOSCOW", "SPB", "UFA", "SOCHI", "KAZAN", "SAMARA", "ROSTOV", "ANAPA",
        "EKB", "KRASNODAR", "ARZAMAS", "NOVOSIB", "GROZNY", "SARATOV", "OMSK", "IRKUTSK", "VOLGOGRAD",
        "VORONEZH", "BELGOROD", "MAKHACHKALA", "VLADIKAVKAZ", "VLADIVOSTOK", "KALININGRAD", "CHELYABINSK",
        "KRASNOYARSK", "CHEBOKSARY", "KHABAROVSK", "PERM", "TULA", "RYAZAN", "MURMANSK", "PENZA",
        "KURSK", "ARKHANGELSK", "ORENBURG", "KIROV", "KEMEROVO", "TYUMEN", "TOLYATTI", "IVANOVO",
        "STAVROPOL", "SMOLENSK", "PSKOV", "BRYANSK", "OREL", "YAROSLAVL", "BARNAUL", "LIPETSK",
        "ULYANOVSK", "YAKUTSK", "TAMBOV", "BRATSK", "ASTRAKHAN", "CHITA", "KOSTROMA", "VLADIMIR",
        "KALUGA", "NOVGOROD", "TAGANROG", "VOLOGDA", "TVER", "TOMSK", "IZHEVSK", "SURGUT", "PODOLSK"
    ]
    servers.sort()
    keyboard = []
    row = []
    for server in servers:
        row.append(InlineKeyboardButton(text=server, callback_data=f"server_{server}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="◀ НАЗАД", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ==================== АДМИН-ПАНЕЛЬ ====================
async def is_admin(user_id):
    return user_id == ADMIN_ID

@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    await message.answer("🔧 *Админ-панель*\n\nВыберите раздел:", parse_mode="Markdown", reply_markup=admin_keyboard())

async def send_orders_list(chat_id, orders, title, edit_msg_id=None):
    if not orders:
        text = f"📭 *{title}*: нет заказов"
        if edit_msg_id:
            await bot.edit_message_text(text, chat_id, edit_msg_id, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin")]]))
        else:
            await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin")]]))
        return
    text = f"📋 *{title}* ({len(orders)})\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for order in orders:
        status_emoji = {"waiting": "⏳", "processing": "🔄", "completed": "✅"}
        emoji = status_emoji.get(order[3], "❓")
        btn_text = f"{emoji} #{order[0]} | {order[5]} | {order[6]} | {order[2]} ₽"
        kb.inline_keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_order_{order[0]}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="◀ Назад", callback_data="back_to_admin")])
    if edit_msg_id:
        await bot.edit_message_text(text, chat_id, edit_msg_id, parse_mode="Markdown", reply_markup=kb)
    else:
        await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data.startswith("admin_"))
async def admin_category(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    category = callback.data.split("_")[1]
    if category == "all":
        orders = get_all_orders_by_status()
        title = "ВСЕ ЗАКАЗЫ"
    elif category == "waiting":
        orders = get_all_orders_by_status("waiting")
        title = "НОВЫЕ (ожидают оплаты)"
    elif category == "processing":
        orders = get_all_orders_by_status("processing")
        title = "В РАБОТЕ"
    elif category == "completed":
        orders = get_all_orders_by_status("completed")
        title = "ВЫПОЛНЕННЫЕ"
    else:
        await callback.answer()
        return
    await send_orders_list(callback.message.chat.id, orders, title, callback.message.message_id)
    await callback.answer()

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    await admin_panel(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("view_order_"))
async def view_order(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    order_id = int(callback.data.split("_")[2])
    order = get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден")
        return
    status_emoji = {"waiting": "⏳", "processing": "🔄", "completed": "✅"}
    status_text = {
        "waiting": "Ожидает оплаты",
        "processing": "В работе",
        "completed": "Выполнен"
    }
    text = (
        f"📦 *Заказ #{order[0]}*\n"
        f"👤 Пользователь: {order[2]} (ID: {order[1]})\n"
        f"🎮 Никнейм: `{order[5]}`\n"
        f"🌍 Сервер: `{order[6]}`\n"
        f"🔑 Пароль: `{order[7]}`\n"
        f"💰 Сумма: {order[3]} ₽\n"
        f"📅 Создан: {datetime.fromtimestamp(order[4]).strftime('%d.%m.%Y %H:%M')}\n"
        f"📸 Скриншот: {'✅' if order[8] else '❌'}\n"
        f"📌 Статус: {status_emoji.get(order[9], '❓')} {status_text.get(order[9], 'Неизвестно')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if order[9] == "waiting" and order[8]:
        kb.add(InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"confirm_order_{order[0]}"))
    if order[9] == "processing":
        kb.add(InlineKeyboardButton(text="🎉 Завершить заказ", callback_data=f"complete_order_{order[0]}"))
    kb.add(InlineKeyboardButton(text="◀ Назад к списку", callback_data="back_to_admin"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_order_"))
async def confirm_payment(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    order_id = int(callback.data.split("_")[2])
    order = get_order(order_id)
    if not order or order[9] != "waiting":
        await callback.answer("Заказ не может быть подтверждён")
        return
    update_order_status(order_id, "processing")
    await callback.answer("✅ Оплата подтверждена, заказ переведён в статус «В работе»")
    await callback.message.edit_text(callback.message.text + "\n\n✅ Статус обновлён: В работе")
    try:
        await bot.send_message(order[1], f"✅ *Заказ #{order_id} оплачен и принят в работу!* Ожидайте выполнения.", parse_mode="Markdown")
    except:
        pass
    await back_to_admin(callback)

@dp.callback_query(F.data.startswith("complete_order_"))
async def complete_order_admin(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    order_id = int(callback.data.split("_")[2])
    order = get_order(order_id)
    if not order or order[9] != "processing":
        await callback.answer("Заказ не может быть завершён")
        return
    update_order_status(order_id, "completed", int(time.time()))
    await callback.answer("🎉 Заказ завершён")
    await callback.message.edit_text(callback.message.text + "\n\n🎉 Заказ выполнен")
    try:
        await bot.send_message(order[1], f"✅ *Заказ #{order_id} выполнен!* Ваш аккаунт прокачан до 4 уровня. Спасибо за заказ!", parse_mode="Markdown")
    except:
        pass
    await back_to_admin(callback)

# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ПОЛЬЗОВАТЕЛЯ ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🚀 *BLACK RUSSIA PRO BOOST* 🚀\n\n"
        "🏆 *Прокачка аккаунтов в Black Russia*\n"
        "✅ Быстро, безопасно, недорого\n\n"
        "🔥 *Услуга:*\n"
        "• Прокачка с 1 до 4 уровня — 35 ₽\n"
        "• Срок: от 1 до 24 часов\n\n"
        "👇 *Выберите действие:*",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🚀 *BLACK RUSSIA PRO BOOST*\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "about")
async def about(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ *О ПРОКАЧКЕ*\n\n"
        "🎯 *Что вы получаете:*\n"
        "• 4 уровень персонажа\n"
        "• Доступ к новым возможностям\n\n"
        "⏱️ *Срок выполнения:*\n"
        "• От 1 до 24 часов\n"
        "• Уведомление придёт в этот чат\n\n"
        f"📞 *Поддержка:* @Asticse",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀ НАЗАД", callback_data="back_main")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "my_orders")
async def my_orders(callback: types.CallbackQuery):
    orders = get_user_orders(callback.from_user.id)
    if not orders:
        await callback.message.edit_text(
            "📭 *У вас пока нет заказов*\n\nНажмите «ЗАКАЗАТЬ ПРОКАЧКУ», чтобы сделать первый заказ!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 ЗАКАЗАТЬ", callback_data="new_order")],
                [InlineKeyboardButton(text="◀ НАЗАД", callback_data="back_main")]
            ])
        )
    else:
        text = "📊 *МОИ ЗАКАЗЫ*\n\n"
        status_emoji = {"waiting": "⏳", "processing": "🔄", "completed": "✅"}
        for order in orders:
            emoji = status_emoji.get(order[2], "❓")
            date = datetime.fromtimestamp(order[3]).strftime("%d.%m %H:%M")
            text += f"{emoji} #{order[0]} | {order[4]} | {order[1]} ₽\n   📅 {date}\n\n"
        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.answer()

@dp.callback_query(F.data == "support")
async def support(callback: types.CallbackQuery):
    await callback.message.answer(
        "🆘 *ПОДДЕРЖКА*\n\n"
        "Если у вас возникли вопросы или проблемы с заказом, напишите:\n"
        "📞 @Asticse\n\n"
        "Мы ответим в ближайшее время.",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "new_order")
async def new_order(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(OrderStates.waiting_nickname)
    await callback.message.edit_text(
        "🎮 *Введите ваш никнейм в Black Russia:*",
        parse_mode="Markdown"
    )

@dp.message(OrderStates.waiting_nickname)
async def get_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    await state.update_data(nickname=nickname)
    await state.set_state(OrderStates.waiting_server)
    await message.answer(
        f"✅ *Никнейм:* {nickname}\n\n"
        f"🌍 *Выберите сервер:*",
        parse_mode="Markdown",
        reply_markup=servers_keyboard()
    )

@dp.callback_query(OrderStates.waiting_server, F.data.startswith("server_"))
async def get_server(callback: types.CallbackQuery, state: FSMContext):
    server = callback.data.replace("server_", "")
    await state.update_data(server=server)
    await state.set_state(OrderStates.waiting_password)
    await callback.message.edit_text(
        f"✅ *Сервер:* {server}\n\n"
        f"🔒 *Введите пароль от аккаунта:*\n\n"
        f"⚠️ Пароль нужен только для выполнения прокачки. Он не будет передан третьим лицам.",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(OrderStates.waiting_password)
async def get_password(message: types.Message, state: FSMContext):
    password = message.text.strip()
    await state.update_data(password=password)
    data = await state.get_data()

    order_id = save_order(
        message.from_user.id,
        message.from_user.username,
        data["nickname"],
        data["server"],
        password
    )
    await state.update_data(order_id=order_id)

    await state.set_state(OrderStates.waiting_screenshot)
    await message.answer(
        f"✅ *Заказ #{order_id} создан!*\n\n"
        f"{CARD_DETAILS}\n\n"
        f"👉 *После оплаты отправьте сюда СКРИНШОТ чека*",
        parse_mode="Markdown"
    )

@dp.message(OrderStates.waiting_screenshot, F.photo)
async def handle_screenshot(message: types.Message, state: FSMContext):
    photo = message.photo[-1]
    file_id = photo.file_id
    data = await state.get_data()
    order_id = data.get("order_id")

    if order_id:
        update_order_screenshot(order_id, file_id)
        order = get_order(order_id)
        await bot.send_message(
            ADMIN_ID,
            f"🆕 *НОВЫЙ ЗАКАЗ #{order_id}*\n"
            f"👤 Пользователь: {message.from_user.id} (@{message.from_user.username})\n"
            f"🎮 Никнейм: {order[5]}\n"
            f"🌍 Сервер: {order[6]}\n"
            f"🔑 Пароль: {order[7]}\n"
            f"💰 Сумма: {PRICE} ₽\n"
            f"📸 Скриншот получен.\n"
            f"Для подтверждения используйте /admin",
            parse_mode="Markdown"
        )
        await message.answer(
            f"✅ *Скриншот получен!*\n\n"
            f"Заказ #{order_id} ожидает подтверждения оплаты администратором.\n"
            f"После подтверждения вы получите уведомление.\n\n"
            f"📞 По вопросам: @Asticse",
            parse_mode="Markdown"
        )
        await state.clear()
    else:
        await message.answer("❌ Ошибка: заказ не найден. Начните заказ заново через /start")

@dp.message(OrderStates.waiting_screenshot)
async def invalid_screenshot(message: types.Message):
    await message.answer(
        "❌ *Пожалуйста, отправьте фото (скриншот чека)*\n\n"
        f"Если у вас проблемы, напишите в поддержку: @Asticse",
        parse_mode="Markdown"
    )

# ==================== FLASK + SELF-PING ====================
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is running", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

async def self_pinger():
    url = f"http://localhost:{PORT}/"
    while True:
        await asyncio.sleep(240)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        logger.info("🏓 Self-ping отправлен")
        except Exception as e:
            logger.error(f"Self-ping ошибка: {e}")

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.create_task(self_pinger())
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Black Russia Boost Bot запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
