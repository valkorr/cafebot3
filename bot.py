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
    start = datetime.strptime(f"{date} {time}", "%d-%m-%Y %H:%M")
    return (start + timedelta(hours=BOOKING_DURATION_HOURS)).strftime("%d-%m-%Y %H:%M")

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
                if datetime.strptime(b["end_time"], "%d-%m-%Y %H:%M") > now:
                    active.append(b)
            except:
                continue
    return active

def find_available_table(date, time, guests):
    start = datetime.strptime(f"{date} {time}", "%d-%m-%Y %H:%M")
    end = start + timedelta(hours=BOOKING_DURATION_HOURS)
    active = get_active_bookings()

    for table_number, cfg in sorted(TABLES_CONFIG.items(), key=lambda x: x[1]['seats']):
        if cfg['seats'] < guests:
            continue

        busy = False
        for b in active:
            if b['table_number'] == table_number and b['date'] == date:
                bs = datetime.strptime(f"{b['date']} {b['time']}", "%d-%m-%Y %H:%M")
                be = datetime.strptime(b['end_time'], "%d-%m-%Y %H:%M")
                if not (end <= bs or start >= be):
                    busy = True
                    break

        if not busy:
            return table_number

    return None

def save_booking(data):
    bookings = get_bookings()
    data["id"] = len(bookings) + 1
    data["created_at"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
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
    start_time = datetime.strptime(f"{booking_data['date']} {booking_data['time']}", "%d-%m-%Y %H:%M")
    delta = start_time - now

    if delta >= timedelta(hours=24):
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 24))
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 3))
    elif delta >= timedelta(hours=3):
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 3))

async def schedule_reminder(chat_id, booking_data, hours_before):
    now = datetime.now()
    start_time = datetime.strptime(f"{booking_data['date']} {booking_data['time']}", "%d-%m-%Y %H:%M")
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
    await message.answer("📅 Дата (ДД-ММ-ГГГГ)")
    await state.set_state(BookingState.date)

@dp.message(BookingState.date)
async def date(message: types.Message, state: FSMContext):
    try:
        d = datetime.strptime(message.text, "%d-%m-%Y").date()
        if d < datetime.now().date():
            raise ValueError
        await state.update_data(date=message.text)
        await message.answer("⏰ Время (ЧЧ:ММ)")
        await state.set_state(BookingState.time)
    except:
        await message.answer("Неверный формат даты. Используйте ДД-ММ-ГГГГ")

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

# ===== АДМИН ПАНЕЛЬ =====
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    # Проверяем доступ
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа к админ панели")

    # Создаем клавиатуру
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📅 Сегодняшние брони"), types.KeyboardButton(text="🗓 Все брони")],
            [types.KeyboardButton(text="❌ Отменить бронь"), types.KeyboardButton(text="📊 Статистика")],
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

    today = datetime.now().strftime("%d-%m-%Y")
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

# ===== ВСЕ БРОНИ =====
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
        text += "🟢 Активные:\n"
        for b in active_bookings:
            text += (
                f"{b['date']} {b['time']} | Стол №{b['table_number']} | "
                f"{b['guests']} гостей | {b['name']} | {b['phone']}\n"
            )
        text += "\n"

    if cancelled_bookings:
        text += "🔴 Отменённые:\n"
        for b in cancelled_bookings:
            text += (
                f"{b['date']} {b['time']} | Стол №{b['table_number']} | "
                f"{b['guests']} гостей | {b['name']} | {b['phone']}\n"
            )

    await message.answer(text)

# ===== СТАТИСТИКА =====
@dp.message(F.text == "📊 Статистика")
async def bookings_statistics(message: types.Message):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    bookings = get_active_bookings()
    total_active = len(bookings)
    total_guests = sum(b['guests'] for b in bookings)

    text = (
        f"📊 Статистика активных броней:\n"
        f"Всего активных броней: {total_active}\n"
        f"Общее количество гостей: {total_guests}"
    )
    await message.answer(text)

# ===== ВЫХОД ИЗ АДМИНКИ =====
@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message, state: FSMContext):
    if message.from_user.id != 525686534:
        return await message.answer("❌ У вас нет доступа")

    # Очищаем состояние и возвращаем пользователя в главное меню
    await state.clear()

    # Вызов главного меню /start
    await start(message, state)


# ===== ЗАПУСК =====
async def main():
    print("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())