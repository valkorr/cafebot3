import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ===== НАСТРОЙКИ =====
logging.basicConfig(level=logging.INFO)

TOKEN = "8403503474:AAGiHEkKZUdeI5E1os00_aUjBrmnI-WoKIM"
ADMIN_ID = 525686534
BOOKINGS_FILE = "bookings.json"
BOOKING_DURATION_HOURS = 3  # Длительность брони

# Картинки
WELCOME_IMAGE = "https://aledo-pro.ru/images/projects/img_64155c9bdeebd1_76912318.webp"
MENU_IMAGE = "https://i.pinimg.com/originals/a4/a4/5d/a4a45df28e9ddd5baf31acf3c5fd42d4.jpg"
CONTACT_IMAGE = "https://avatars.mds.yandex.net/i?id=43f5893baac8158cc429f73a1af43254_l-5562949-images-thumbs&n=13"
CONFIRM_IMAGE = "https://avatars.mds.yandex.net/i?id=5ef80d69d1ef34d60830aaf8516d5887_l-16282654-images-thumbs&n=13"

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===== СТОЛИКИ (БЕЗ ОКОН) =====
TABLES_CONFIG = {
    **{i: {'seats': 1} for i in range(1, 6)},
    **{i: {'seats': 2} for i in range(6, 21)},
    **{i: {'seats': 4} for i in range(21, 31)},
}

# ===== FSM =====
class BookingState(StatesGroup):
    guests = State()
    date = State()
    time = State()
    name = State()
    phone = State()
    cancel_select = State()  # Выбор брони для отмены

# ===== УТИЛИТЫ =====
def calculate_end_time(date, time):
    # Изменен формат с %d-%m-%Y на %d.%m.%Y
    start = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
    return (start + timedelta(hours=BOOKING_DURATION_HOURS)).strftime("%d.%m.%Y %H:%M")

def get_bookings():
    if os.path.exists(BOOKINGS_FILE):
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def get_active_bookings():
    bookings = get_bookings()
    now = datetime.now()
    active = []
    for b in bookings:
        if b.get("active", True):
            try:
                # Изменен формат с %d-%m-%Y на %d.%m.%Y
                if datetime.strptime(b["end_time"], "%d.%m.%Y %H:%M") > now:
                    active.append(b)
            except:
                continue
    return active

def find_available_table(date, time, guests):
    # Изменен формат с %d-%m-%Y на %d.%m.%Y
    start = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
    end = start + timedelta(hours=BOOKING_DURATION_HOURS)
    active = get_active_bookings()

    for table_number, cfg in sorted(TABLES_CONFIG.items(), key=lambda x: x[1]['seats']):
        if cfg['seats'] < guests:
            continue

        busy = False
        for b in active:
            if b['table_number'] == table_number and b['date'] == date:
                # Изменен формат с %d-%m-%Y на %d.%m.%Y
                bs = datetime.strptime(f"{b['date']} {b['time']}", "%d.%m.%Y %H:%M")
                be = datetime.strptime(b['end_time'], "%d.%m.%Y %H:%M")
                if not (end <= bs or start >= be):
                    busy = True
                    break

        if not busy:
            return table_number

    return None

def save_booking(data):
    bookings = get_bookings()
    data["id"] = len(bookings) + 1
    data["created_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    data["end_time"] = calculate_end_time(data["date"], data["time"])
    data["active"] = True
    bookings.append(data)

    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)

    # Настройка напоминаний
    send_booking_reminders(data)

    return data["id"]

def cancel_booking_by_id(user_id, booking_id):
    bookings = get_bookings()
    for b in bookings:
        if b["user_id"] == user_id and b["id"] == booking_id and b.get("active", True):
            b["active"] = False
            with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(bookings, f, ensure_ascii=False, indent=2)
            return True
    return False

# ===== НАПОМИНАНИЯ =====
async def send_reminder(chat_id, booking_data, hours_before):
    await bot.send_message(
        chat_id,
        f"🔔 Напоминание: ваша бронь на {booking_data['date']} в {booking_data['time']} через {hours_before} час(а/ов)."
    )

def send_booking_reminders(booking_data):
    now = datetime.now()
    # Изменен формат с %d-%m-%Y на %d.%m.%Y
    start_time = datetime.strptime(f"{booking_data['date']} {booking_data['time']}", "%d.%m.%Y %H:%M")
    delta = start_time - now

    if delta >= timedelta(hours=24):
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 24))
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 3))
    elif delta >= timedelta(hours=3):
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 3))

async def schedule_reminder(chat_id, booking_data, hours_before):
    now = datetime.now()
    # Изменен формат с %d-%m-%Y на %d.%m.%Y
    start_time = datetime.strptime(f"{booking_data['date']} {booking_data['time']}", "%d.%m.%Y %H:%M")
    remind_time = start_time - timedelta(hours=hours_before)
    wait_seconds = (remind_time - now).total_seconds()
    if wait_seconds > 0:
        await asyncio.sleep(wait_seconds)
        await send_reminder(chat_id, booking_data, hours_before)

# ===== /start =====
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    greeting = (
        "🏮 Добро пожаловать в наш премиальный ресторан!\n"
        "Изысканная кухня, уютная атмосфера и внимание к каждой детали.\n"
        "Выберите действие ниже:"
    )
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📋 Меню"), types.KeyboardButton(text="📅 Забронировать стол")],
            [types.KeyboardButton(text="📞 Контакты"), types.KeyboardButton(text="🎫 Мои брони")],
            [types.KeyboardButton(text="❌ Отменить бронь")]
        ],
        resize_keyboard=True
    )
    await message.answer_photo(WELCOME_IMAGE, caption=greeting, parse_mode="Markdown", reply_markup=keyboard)

# ===== МЕНЮ =====
@dp.message(F.text == "📋 Меню")
async def menu(message: types.Message):
    await message.answer_photo(
        photo=MENU_IMAGE,
        caption=(
            "🍽 Наше меню — быстрые, красивые и изысканные блюда.\n"
            "Каждое блюдо готовится с любовью и вниманием.\n"
            "📞 Заказ: +7 900 123-45-67"
        )
    )

# ===== КОНТАКТЫ =====
@dp.message(F.text == "📞 Контакты")
async def contacts(message: types.Message):
    text = (
        "📍 Адрес: ул. Примерная, д.1\n"
        "🕒 Часы работы: Пн–Вс: 10:00–22:00\n"
        "☎ Телефон: +7 900 123-45-67\n"
        "📧 Email: info@restaurant.ru\n"
        "🌐 Wi-Fi: Restaurant-Free\n"
        "🅿 Парковка бесплатная\n"
        "🎉 Ждем вас для незабываемого вечера!"
    )
    await message.answer_photo(CONTACT_IMAGE, caption=text)

# ===== ОТМЕНА БРОНИ =====
@dp.message(F.text == "❌ Отменить бронь")
async def cancel_start(message: types.Message, state: FSMContext):
    bookings = get_active_bookings()
    user_bookings = [b for b in bookings if b["user_id"] == message.from_user.id]
    if not user_bookings:
        return await message.answer("ℹ️ У вас нет активных броней для отмены.")

    # создаем кнопки корректно
    keyboard_buttons = [
        [types.InlineKeyboardButton(
            text=f"{b['date']} {b['time']} | {b['guests']} гостей",
            callback_data=f"cancel_{b['id']}"
        )] for b in user_bookings
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer("Выберите бронь для отмены:", reply_markup=keyboard)
    await state.set_state(BookingState.cancel_select)


# ===== ОБРАБОТКА НАЖАТИЯ НА БРОНЬ ДЛЯ ОТМЕНЫ =====
@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_booking_callback(callback: types.CallbackQuery):
    booking_id = int(callback.data.split("_")[1])

    # загружаем все брони
    if os.path.exists(BOOKINGS_FILE):
        with open(BOOKINGS_FILE, 'r', encoding='utf-8') as f:
            bookings = json.load(f)
    else:
        bookings = []

    # ищем бронь по id
    for booking in bookings:
        if booking['id'] == booking_id:
            # помечаем как неактивную
            booking['active'] = False
            with open(BOOKINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(bookings, f, ensure_ascii=False, indent=2)

            await callback.message.edit_text(
                f"🗑 Бронь на {booking['date']} {booking['time']} для {booking['guests']} гостей успешно отменена ✅"
            )
            await callback.answer("Бронь отменена")
            return

    # если не нашли
    await callback.answer("❌ Бронь не найдена или уже отменена", show_alert=True)


# ===== СТАРТ БРОНИ =====
@dp.message(F.text == "📅 Забронировать стол")
async def booking_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👥 На сколько человек? (1–4)\n"
        "ℹ Если вы желаете столик на большее количество людей, пожалуйста, свяжитесь с администратором напрямую по телефону: +7(800)555-35-35"
    )
    await state.set_state(BookingState.guests)

@dp.message(BookingState.guests)
async def guests(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Введите число от 1 до 4")
    g = int(message.text)
    if g < 1 or g > 4:
        return await message.answer("Введите число от 1 до 4")
    await state.update_data(guests=g)
    # Изменено с ДД-ММ-ГГГГ на ДД.ММ.ГГГГ
    await message.answer("📅 Дата (ДД.ММ.ГГГГ)")
    await state.set_state(BookingState.date)

@dp.message(BookingState.date)
async def date(message: types.Message, state: FSMContext):
    try:
        # Изменен формат с %d-%m-%Y на %d.%m.%Y
        d = datetime.strptime(message.text, "%d.%m.%Y").date()
        if d < datetime.now().date():
            raise ValueError
        await state.update_data(date=message.text)
        await message.answer("⏰ Время (ЧЧ:ММ)")
        await state.set_state(BookingState.time)
    except:
        # Изменено сообщение об ошибке
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ")

@dp.message(BookingState.time)
async def time(message: types.Message, state: FSMContext):
    try:
        t_obj = datetime.strptime(message.text, "%H:%M")
        data = await state.get_data()
        table = find_available_table(data["date"], message.text, data["guests"])
        if not table:
            return await message.answer("😔 Нет свободных столиков на это время. Введите другое время.")
        await state.update_data(time=message.text, table_number=table)
        await message.answer("👤 Введите имя")
        await state.set_state(BookingState.name)
    except:
        await message.answer("Неверный формат времени. Используйте ЧЧ:ММ")

@dp.message(BookingState.name)
async def name(message: types.Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        return await message.answer("Введите имя")
    await state.update_data(name=message.text.strip())
    await message.answer("📱 Введите телефон")
    await state.set_state(BookingState.phone)

@dp.message(BookingState.phone)
async def phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    save_booking({
        "date": data["date"],
        "time": data["time"],
        "guests": data["guests"],
        "table_number": data["table_number"],
        "name": data["name"],
        "phone": message.text,
        "user_id": message.from_user.id
    })

    await bot.send_message(
        ADMIN_ID,
        f"🔥 Новая бронь:\n{data['date']} {data['time']}\n"
        f"{data['guests']} гостей\nСтол №{data['table_number']}\n{data['name']} {message.text}"
    )

    await message.answer_photo(
        photo=CONFIRM_IMAGE,
        caption=(
            f"✅ Ваша бронь подтверждена!\n\n"
            f"📅 {data['date']} ⏰ {data['time']}\n"
            f"👥 На сколько человек: {data['guests']}\n\n"
            "🔔 Напоминания придут за 24 и 3 часа\n"
            "🏮 Ждем вас для незабываемого вечера!"
        )
    )

    await state.clear()

# ===== МОИ БРОНИ =====
@dp.message(F.text == "🎫 Мои брони")
async def my_bookings(message: types.Message):
    bookings = get_active_bookings()
    user = [b for b in bookings if b["user_id"] == message.from_user.id]

    if not user:
        return await message.answer("У вас нет активных броней")

    text = "🎫 Ваши брони:\n\n"
    for b in user:
        text += (
            f"Дата: {b['date']} ⏰ {b['time']}\n"
            f"Гостей: {b['guests']}\n"
            f"Стол: №{b['table_number']}\n\n"
        )

    await message.answer(text)


from aiogram.filters import Command

from aiogram.filters import Command

# ===== ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ (ДОБАВЬТЕ В НАЧАЛО ФАЙЛА, ПОСЛЕ ДРУГИХ НАСТРОЕК) =====
BLOCKED_TABLES_FILE = "blocked_tables.json"


# ===== ФУНКЦИИ ДЛЯ БЛОКИРОВКИ СТОЛИКОВ (ДОБАВЬТЕ ПОСЛЕ get_active_bookings()) =====
def get_blocked_tables():
    """Получить список заблокированных столиков"""
    if os.path.exists(BLOCKED_TABLES_FILE):
        with open(BLOCKED_TABLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_blocked_tables(blocked_tables):
    """Сохранить список заблокированных столиков"""
    with open(BLOCKED_TABLES_FILE, "w", encoding="utf-8") as f:
        json.dump(blocked_tables, f, ensure_ascii=False, indent=2)


def is_table_blocked(table_number, date, time):
    """Проверить, заблокирован ли столик на определенное время"""
    blocked_tables = get_blocked_tables()

    for blocked in blocked_tables:
        if blocked["table_number"] == table_number:
            # Проверяем дату и время
            if blocked.get("permanent", False):
                return True

            # Проверяем конкретную дату и время
            if blocked["date"] == date:
                blocked_start = datetime.strptime(f"{blocked['date']} {blocked['time']}", "%d.%m.%Y %H:%M")
                blocked_end = blocked_start + timedelta(hours=blocked.get("duration", BOOKING_DURATION_HOURS))
                requested_time = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")

                if blocked_start <= requested_time < blocked_end:
                    return True

    return False


# ===== ИЗМЕНИТЕ СУЩЕСТВУЮЩУЮ ФУНКЦИЮ find_available_table =====
# ЗАМЕНИТЕ ВАШУ СТАРУЮ ФУНКЦИЮ find_available_table на эту:
def find_available_table(date, time, guests):
    # Изменен формат с %d-%m-%Y на %d.%m.%Y
    start = datetime.strptime(f"{date} {time}", "%d.%m.%Y %H:%M")
    end = start + timedelta(hours=BOOKING_DURATION_HOURS)
    active = get_active_bookings()

    for table_number, cfg in sorted(TABLES_CONFIG.items(), key=lambda x: x[1]['seats']):
        if cfg['seats'] < guests:
            continue

        # Проверяем, не заблокирован ли столик (НОВАЯ ПРОВЕРКА)
        if is_table_blocked(table_number, date, time):
            continue

        busy = False
        for b in active:
            if b['table_number'] == table_number and b['date'] == date:
                # Изменен формат с %d-%m-%Y на %d.%m.%Y
                bs = datetime.strptime(f"{b['date']} {b['time']}", "%d.%m.%Y %H:%M")
                be = datetime.strptime(b['end_time'], "%d.%m.%Y %H:%M")
                if not (end <= bs or start >= be):
                    busy = True
                    break

        if not busy:
            return table_number

    return None


# ===== АДМИН ПАНЕЛЬ (ПОЛНОСТЬЮ ЗАМЕНИТЕ СТАРЫЙ КОД) =====
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    # Проверяем доступ
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа к админ панели")

    # Создаем клавиатуру С НОВЫМИ КНОПКАМИ
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📅 Сегодняшние брони"), types.KeyboardButton(text="🗓 Все брони")],
            [types.KeyboardButton(text="🚫 Заблокировать стол"), types.KeyboardButton(text="✅ Разблокировать стол")],
            [types.KeyboardButton(text="📊 Статистика"), types.KeyboardButton(text="🧹 Очистка броней")],
            [types.KeyboardButton(text="🚪 Выйти из админки")]
        ],
        resize_keyboard=True
    )

    await message.answer("🛠 Добро пожаловать в админ панель!", reply_markup=keyboard)


# ===== СЕГОДНЯШНИЕ БРОНИ =====
@dp.message(F.text == "📅 Сегодняшние брони")
async def todays_bookings(message: types.Message):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    today = datetime.now().strftime("%d.%m.%Y")
    active = get_active_bookings()
    todays = [b for b in active if b["date"] == today]

    if not todays:
        return await message.answer("Сегодня броней нет")

    text = f"📅 Брони на сегодня ({today}):\n\n"
    for b in todays:
        text += (
            f"{b['time']} ⏰ | Стол №{b['table_number']} | "
            f"{b['guests']} гостей | {b['name']} | {b['phone']}\n"
        )

    await message.answer(text)


# ===== ВСЕ БРОНИ С КНОПКАМИ ОЧИСТКИ =====
@dp.message(F.text == "🗓 Все брони")
async def all_bookings(message: types.Message):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    bookings = get_bookings()
    if not bookings:
        return await message.answer("Брони отсутствуют")

    active_bookings = [b for b in bookings if b.get("active", True)]
    cancelled_bookings = [b for b in bookings if not b.get("active", True)]

    text = "📋 Все брони:\n\n"
    if active_bookings:
        text += f"🟢 Активные ({len(active_bookings)}):\n"
        for b in active_bookings:
            text += (
                f"{b['date']} {b['time']} | Стол №{b['table_number']} | "
                f"{b['guests']} гостей | {b['name']} | {b['phone']}\n"
            )
        text += "\n"

    if cancelled_bookings:
        text += f"🔴 Отменённые ({len(cancelled_bookings)}):\n"
        for b in cancelled_bookings:
            text += (
                f"{b['date']} {b['time']} | Стол №{b['table_number']} | "
                f"{b['guests']} гостей | {b['name']} | {b['phone']}\n"
            )

    # Добавляем кнопки очистки (НОВОЕ)
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🧹 Очистить неактивные", callback_data="cleanup_inactive"),
             types.InlineKeyboardButton(text="🗑️ Очистить все", callback_data="cleanup_all")]
        ]
    )

    await message.answer(text, reply_markup=keyboard)


# ===== БЛОКИРОВКА СТОЛИКА =====
from aiogram.fsm.state import State, StatesGroup


# Добавьте новый класс состояний для блокировки столиков
class BlockTableState(StatesGroup):
    waiting_for_table_number = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_duration = State()


# ===== БЛОКИРОВКА СТОЛИКА =====
@dp.message(F.text == "🚫 Заблокировать стол")
async def block_table_start(message: types.Message, state: FSMContext):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="⏰ На конкретное время", callback_data="block_temporary")],
            [types.InlineKeyboardButton(text="🔒 Постоянно (весь день)", callback_data="block_permanent")],
            [types.InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel_block")]
        ]
    )

    await message.answer("Выберите тип блокировки столика:", reply_markup=keyboard)


@dp.callback_query(F.data == "block_temporary")
async def block_temporary(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите номер столика для блокировки:")
    await state.set_state(BlockTableState.waiting_for_table_number)
    await state.update_data(block_type="temporary")
    await callback.answer()


@dp.callback_query(F.data == "block_permanent")
async def block_permanent(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите номер столика для постоянной блокировки:")
    await state.set_state(BlockTableState.waiting_for_table_number)
    await state.update_data(block_type="permanent")
    await callback.answer()


@dp.callback_query(F.data == "cancel_block")
async def cancel_block(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Блокировка отменена")
    await state.clear()
    await callback.answer()


@dp.message(BlockTableState.waiting_for_table_number)
async def block_table_number(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Пожалуйста, введите номер столика (число)")

    table_number = int(message.text)
    if table_number not in TABLES_CONFIG:
        return await message.answer(f"❌ Столик №{table_number} не существует. Доступные номера: 1-{len(TABLES_CONFIG)}")

    await state.update_data(table_number=table_number)

    data = await state.get_data()
    if data.get("block_type") == "permanent":
        await message.answer("📅 Введите дату для блокировки (ДД.ММ.ГГГГ):")
        await state.set_state(BlockTableState.waiting_for_date)
    else:
        await message.answer("📅 Введите дату для блокировки (ДД.ММ.ГГГГ):")
        await state.set_state(BlockTableState.waiting_for_date)


@dp.message(BlockTableState.waiting_for_date)
async def block_date(message: types.Message, state: FSMContext):
    try:
        d = datetime.strptime(message.text, "%d.%m.%Y").date()
        if d < datetime.now().date():
            raise ValueError
        await state.update_data(date=message.text)

        data = await state.get_data()
        if data.get("block_type") == "permanent":
            blocked_tables = get_blocked_tables()
            blocked_tables.append({
                "table_number": data["table_number"],
                "date": data["date"],
                "permanent": True,
                "blocked_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "blocked_by": "admin"
            })
            save_blocked_tables(blocked_tables)

            await message.answer(
                f"✅ Столик №{data['table_number']} заблокирован на {data['date']} на весь день"
            )
            await state.clear()
        else:
            await message.answer("⏰ Введите время начала блокировки (ЧЧ:ММ):")
            await state.set_state(BlockTableState.waiting_for_time)
    except:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ")


@dp.message(BlockTableState.waiting_for_time)
async def block_time(message: types.Message, state: FSMContext):
    try:
        t = datetime.strptime(message.text, "%H:%M")
        await state.update_data(time=message.text)

        data = await state.get_data()

        keyboard = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="1 час"), types.KeyboardButton(text="2 часа")],
                [types.KeyboardButton(text="3 часа"), types.KeyboardButton(text="4 часа")],
                [types.KeyboardButton(text="5 часов"), types.KeyboardButton(text="Весь день")]
            ],
            resize_keyboard=True
        )

        await message.answer("⏳ Выберите продолжительность блокировки:", reply_markup=keyboard)
        await state.set_state(BlockTableState.waiting_for_duration)
    except:
        await message.answer("Неверный формат времени. Используйте ЧЧ:ММ")


@dp.message(BlockTableState.waiting_for_duration)
async def block_duration(message: types.Message, state: FSMContext):
    data = await state.get_data()

    duration_map = {
        "1 час": 1,
        "2 часа": 2,
        "3 часа": 3,
        "4 часа": 4,
        "5 часов": 5,
        "Весь день": 12
    }

    duration = duration_map.get(message.text, 3)

    blocked_tables = get_blocked_tables()
    blocked_tables.append({
        "table_number": data["table_number"],
        "date": data["date"],
        "time": data["time"],
        "duration": duration,
        "permanent": False,
        "blocked_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "blocked_by": "admin"
    })
    save_blocked_tables(blocked_tables)

    await message.answer(
        f"✅ Столик №{data['table_number']} заблокирован:\n"
        f"📅 {data['date']} ⏰ {data['time']}\n"
        f"⏳ Продолжительность: {message.text}",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.clear()


# ===== РАЗБЛОКИРОВКА СТОЛИКА =====
@dp.message(F.text == "✅ Разблокировать стол")
async def unblock_table_start(message: types.Message, state: FSMContext):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    blocked_tables = get_blocked_tables()
    if not blocked_tables:
        return await message.answer("❌ Нет заблокированных столиков")

    keyboard_buttons = []
    for blocked in blocked_tables:
        if blocked.get("permanent", False):
            text = f"Стол №{blocked['table_number']} - {blocked['date']} (постоянно)"
        else:
            text = f"Стол №{blocked['table_number']} - {blocked['date']} {blocked.get('time', '')}"
        keyboard_buttons.append([types.InlineKeyboardButton(
            text=text,
            callback_data=f"unblock_{blocked_tables.index(blocked)}"
        )])

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer("Выберите столик для разблокировки:", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("unblock_"))
async def unblock_table(callback: types.CallbackQuery):
    index = int(callback.data.split("_")[1])

    blocked_tables = get_blocked_tables()
    if 0 <= index < len(blocked_tables):
        blocked = blocked_tables.pop(index)
        save_blocked_tables(blocked_tables)

        await callback.message.edit_text(
            f"✅ Столик №{blocked['table_number']} разблокирован\n"
            f"Дата: {blocked['date']}"
        )
    else:
        await callback.message.edit_text("❌ Ошибка: столик не найден")

    await callback.answer()


# ===== ОЧИСТКА БРОНЕЙ =====
@dp.message(F.text == "🧹 Очистка броней")
async def cleanup_bookings_start(message: types.Message):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🗑️ Очистить все брони", callback_data="cleanup_all")],
            [types.InlineKeyboardButton(text="🧽 Очистить неактивные брони", callback_data="cleanup_inactive")],
            [types.InlineKeyboardButton(text="📊 Статистика перед очисткой", callback_data="cleanup_stats")],
            [types.InlineKeyboardButton(text="❌ Отмена", callback_data="cleanup_cancel")]
        ]
    )

    await message.answer("🧹 Выберите тип очистки броней:", reply_markup=keyboard)


@dp.callback_query(F.data == "cleanup_all")
async def cleanup_all(callback: types.CallbackQuery):
    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

    await callback.message.edit_text("✅ Все брони успешно очищены!")
    await callback.answer()


@dp.callback_query(F.data == "cleanup_inactive")
async def cleanup_inactive(callback: types.CallbackQuery):
    bookings = get_bookings()
    active_bookings = [b for b in bookings if b.get("active", True)]

    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(active_bookings, f, ensure_ascii=False, indent=2)

    removed_count = len(bookings) - len(active_bookings)
    await callback.message.edit_text(f"✅ Удалено {removed_count} неактивных броней!")
    await callback.answer()


@dp.callback_query(F.data == "cleanup_stats")
async def cleanup_stats(callback: types.CallbackQuery):
    bookings = get_bookings()
    active_bookings = [b for b in bookings if b.get("active", True)]
    inactive_bookings = [b for b in bookings if not b.get("active", True)]

    text = (
        f"📊 Статистика броней перед очисткой:\n\n"
        f"Всего броней: {len(bookings)}\n"
        f"Активных: {len(active_bookings)}\n"
        f"Неактивных: {len(inactive_bookings)}\n\n"
        f"Выберите действие очистки:"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🗑️ Очистить все брони", callback_data="cleanup_all")],
            [types.InlineKeyboardButton(text="🧽 Очистить неактивные брони", callback_data="cleanup_inactive")],
            [types.InlineKeyboardButton(text="❌ Отмена", callback_data="cleanup_cancel")]
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "cleanup_cancel")
async def cleanup_cancel(callback: types.CallbackQuery):
    await callback.message.edit_text("❌ Очистка отменена")
    await callback.answer()


# ===== СТАТИСТИКА С БЛОКИРОВАННЫМИ СТОЛИКАМИ =====
@dp.message(F.text == "📊 Статистика")
async def bookings_statistics(message: types.Message):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    bookings = get_active_bookings()
    total_active = len(bookings)
    total_guests = sum(b['guests'] for b in bookings)

    blocked_tables = get_blocked_tables()
    total_blocked = len(blocked_tables)

    today = datetime.now().strftime("%d.%m.%Y")
    today_bookings = [b for b in bookings if b["date"] == today]
    today_guests = sum(b['guests'] for b in today_bookings)

    text = (
        f"📊 Статистика:\n\n"
        f"🔹 Активные брони: {total_active}\n"
        f"🔹 Всего гостей: {total_guests}\n\n"
        f"📅 Сегодня ({today}):\n"
        f"   • Броней: {len(today_bookings)}\n"
        f"   • Гостей: {today_guests}\n\n"
        f"🚫 Заблокированных столиков: {total_blocked}"
    )
    await message.answer(text)


# ===== ВЫХОД ИЗ АДМИНКИ =====
@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    await state.clear()
    await start(message, state)

# ===== ЗАПУСК =====
async def main():
    print("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())