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

ADMIN_ID = 8145260053
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
