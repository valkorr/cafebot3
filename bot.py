import asyncio
import logging
import json
import os
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ===== НАСТРОЙКИ =====
logging.basicConfig(level=logging.INFO)

TOKEN = "8403503474:AAGiHEkKZUdeI5E1os00_aUjBrmnI-WoKIM"
# Главный администратор (основной владелец)
MAIN_ADMIN_ID = 525686534
# Файл для хранения списка администраторов
ADMINS_FILE = "admins.json"
BOOKINGS_FILE = "bookings.json"
BLOCKED_TABLES_FILE = "blocked_tables.json"

# Картинки
WELCOME_IMAGE = "https://aledo-pro.ru/images/projects/img_64155c9bdeebd1_76912318.webp"
MENU_IMAGE = "https://i.pinimg.com/originals/a4/a4/5d/a4a45df28e9ddd5baf31acf3c5fd42d4.jpg"
CONTACT_IMAGE = "https://avatars.mds.yandex.net/i?id=43f5893baac8158cc429f73a1af43254_l-5562949-images-thumbs&n=13"
CONFIRM_IMAGE = "https://avatars.mds.yandex.net/i?id=5ef80d69d1ef34d60830aaf8516d5887_l-16282654-images-thumbs&n=13"

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ===== ФУНКЦИИ ДЛЯ УПРАВЛЕНИЯ АДМИНАМИ =====
def get_admins():
    """Получить список администраторов"""
    if os.path.exists(ADMINS_FILE):
        with open(ADMINS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Добавляем главного администратора, если его нет в списке
            if MAIN_ADMIN_ID not in data:
                data.append(MAIN_ADMIN_ID)
                save_admins(data)
            return data
    else:
        # Создаем файл с главным администратором
        admins = [MAIN_ADMIN_ID]
        save_admins(admins)
        return admins


def save_admins(admins):
    """Сохранить список администраторов"""
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump(admins, f, ensure_ascii=False, indent=2)


def is_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    admins = get_admins()
    return user_id in admins


def is_main_admin(user_id):
    """Проверка, является ли пользователь главным администратором"""
    return user_id == MAIN_ADMIN_ID


def add_admin(user_id):
    """Добавить администратора"""
    admins = get_admins()
    if user_id not in admins:
        admins.append(user_id)
        save_admins(admins)

        # Отправляем уведомление новому администратору
        asyncio.create_task(notify_new_admin(user_id))

        # Отправляем уведомление главному администратору
        asyncio.create_task(notify_main_admin_about_new_admin(user_id))

        return True
    return False


def remove_admin(user_id):
    """Удалить администратора (только если не главный)"""
    if user_id == MAIN_ADMIN_ID:
        return False  # Нельзя удалить главного администратора

    admins = get_admins()
    if user_id in admins:
        admins.remove(user_id)
        save_admins(admins)

        # Отправляем уведомление удаленному администратору
        asyncio.create_task(notify_removed_admin(user_id))

        return True
    return False


async def notify_new_admin(user_id):
    """Уведомить нового администратора"""
    try:
        await bot.send_message(
            user_id,
            "🎉 *Вас добавили в администраторы ресторана!*\n\n"
            "Теперь вы можете:\n"
            "• Просматривать все брони\n"
            "• Добавлять прямые брони\n"
            "• Управлять блокировками столов\n"
            "• Смотреть статистику\n\n"
            "Используйте команду /admin для доступа к панели управления.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Не удалось отправить уведомление новому администратору {user_id}: {e}")


async def notify_main_admin_about_new_admin(new_admin_id):
    """Уведомить главного администратора о новом администраторе"""
    try:
        await bot.send_message(
            MAIN_ADMIN_ID,
            f"✅ *Добавлен новый администратор*\n\n"
            f"ID: `{new_admin_id}`\n"
            f"Пользователь получил уведомление о новых правах.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Не удалось отправить уведомление главному администратору: {e}")


async def notify_removed_admin(user_id):
    """Уведомить удаленного администратора"""
    try:
        await bot.send_message(
            user_id,
            "ℹ️ *Ваши права администратора в боте ресторана были отозваны.*\n\n"
            "Если это ошибка, свяжитесь с главным администратором.",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Не удалось отправить уведомление удаленному администратору {user_id}: {e}")


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
    start_time = State()
    end_time = State()
    name = State()
    phone = State()
    confirm_booking = State()
    cancel_select = State()


class BlockTableState(StatesGroup):
    waiting_for_table_number = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_duration = State()


class DirectBookingState(StatesGroup):
    waiting_for_date = State()
    waiting_for_start_time = State()
    waiting_for_end_time = State()
    waiting_for_guests = State()
    waiting_for_table = State()
    waiting_for_name = State()
    waiting_for_phone = State()


# ===== УТИЛИТЫ =====
def validate_booking_time(start_str, end_str, date):
    """Проверка корректности времени бронирования"""
    try:
        start = datetime.strptime(f"{date} {start_str}", "%d.%m.%Y %H:%M")
        end = datetime.strptime(f"{date} {end_str}", "%d.%m.%Y %H:%M")

        now = datetime.now()

        if start < now:
            return False, "❌ Время начала бронирования не может быть в прошлом"

        if end <= start:
            return False, "❌ Время окончания должно быть позже времени начала"

        duration_hours = (end - start).total_seconds() / 3600

        if duration_hours < 0.5:
            return False, "❌ Минимальное время бронирования - 30 минут"

        if duration_hours > 6:
            return False, "❌ Максимальное время бронирования - 6 часов"

        return True, f"⏰ Длительность брони: {duration_hours:.1f} часов"
    except Exception as e:
        return False, "❌ Неверный формат времени"


def calculate_duration(booking):
    """Расчет длительности брони с поддержкой старого и нового форматов"""
    try:
        if 'start_time' in booking and 'end_time' in booking:
            # Новый формат
            start = datetime.strptime(f"{booking['date']} {booking['start_time']}", "%d.%m.%Y %H:%M")
            end = datetime.strptime(f"{booking['date']} {booking['end_time']}", "%d.%m.%Y %H:%M")
        elif 'time' in booking and 'end_time' in booking:
            # Старый формат
            start = datetime.strptime(f"{booking['date']} {booking['time']}", "%d.%m.%Y %H:%M")
            end = datetime.strptime(booking['end_time'], "%d.%m.%Y %H:%M")
        else:
            return 3.0  # Значение по умолчанию

        return (end - start).total_seconds() / 3600
    except:
        return 3.0  # Значение по умолчанию


def get_booking_time_info(booking):
    """Получение информации о времени брони с поддержкой старого и нового форматов"""
    try:
        if 'start_time' in booking and 'end_time' in booking:
            # Новый формат
            start_time = booking['start_time']
            end_time = booking['end_time']
        elif 'time' in booking and 'end_time' in booking:
            # Старый формат
            start_time = booking['time']
            # Извлекаем только время из поля end_time
            end_dt = datetime.strptime(booking['end_time'], "%d.%m.%Y %H:%M")
            end_time = end_dt.strftime("%H:%M")
        else:
            # Если данных нет, используем значения по умолчанию
            start_time = "??:??"
            end_time = "??:??"

        return start_time, end_time
    except:
        return "??:??", "??:??"


def get_bookings():
    """Загрузка броней с миграцией старых форматов"""
    if os.path.exists(BOOKINGS_FILE):
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            bookings = json.load(f)

        # Миграция старых форматов
        updated = False
        for booking in bookings:
            if 'time' in booking and 'start_time' not in booking:
                # Мигрируем старый формат в новый
                booking['start_time'] = booking['time']
                updated = True

            if 'time' in booking and 'end_time' in booking and isinstance(booking['end_time'], str) and len(
                    booking['end_time'].split()) > 1:
                # Поле end_time уже в правильном формате
                pass
            elif 'time' in booking and 'end_time' not in booking:
                # Старый формат без end_time - создаем его
                try:
                    start_dt = datetime.strptime(f"{booking['date']} {booking['time']}", "%d.%m.%Y %H:%M")
                    end_dt = start_dt + timedelta(hours=3)
                    booking['end_time'] = end_dt.strftime("%d.%m.%Y %H:%M")
                    updated = True
                except:
                    booking['end_time'] = f"{booking['date']} 23:59"
                    updated = True

        if updated:
            with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(bookings, f, ensure_ascii=False, indent=2)

        return bookings
    return []


def get_active_bookings():
    """Получить активные брони (не отмененные и не истекшие)"""
    bookings = get_bookings()
    now = datetime.now()
    active = []

    for b in bookings:
        if b.get("active", True):
            try:
                end_time = datetime.strptime(b["end_time"], "%d.%m.%Y %H:%M")
                if end_time > now:
                    active.append(b)
            except:
                continue

    return active


def get_expired_bookings():
    """Получить истекшие брони (за последние 24 часа)"""
    bookings = get_bookings()
    now = datetime.now()
    expired = []

    for b in bookings:
        if b.get("active", True):
            try:
                end_time = datetime.strptime(b["end_time"], "%d.%m.%Y %H:%M")
                if end_time < now and (now - end_time) <= timedelta(hours=24):
                    expired.append(b)
            except:
                continue

    return expired


def auto_cleanup_bookings():
    """Автоматическая очистка отмененных и истекших броней (старше 24 часов)"""
    bookings = get_bookings()
    now = datetime.now()
    cleaned_bookings = []

    for b in bookings:
        keep = True

        if not b.get("active", True):
            keep = False
        elif b.get("active", True):
            try:
                end_time = datetime.strptime(b["end_time"], "%d.%m.%Y %H:%M")
                if (now - end_time) > timedelta(hours=24):
                    keep = False
            except:
                pass

        if keep:
            cleaned_bookings.append(b)

    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned_bookings, f, ensure_ascii=False, indent=2)

    return len(bookings) - len(cleaned_bookings)


# ===== ФУНКЦИИ ДЛЯ БЛОКИРОВКИ СТОЛИКОВ =====
def get_blocked_tables():
    if os.path.exists(BLOCKED_TABLES_FILE):
        with open(BLOCKED_TABLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_blocked_tables(blocked_tables):
    with open(BLOCKED_TABLES_FILE, "w", encoding="utf-8") as f:
        json.dump(blocked_tables, f, ensure_ascii=False, indent=2)


def is_table_blocked(table_number, date, start_time, end_time_str):
    """Проверка, заблокирован ли стол в указанный промежуток времени"""
    blocked_tables = get_blocked_tables()

    requested_start = datetime.strptime(f"{date} {start_time}", "%d.%m.%Y %H:%M")
    requested_end = datetime.strptime(f"{date} {end_time_str}", "%d.%m.%Y %H:%M")

    for blocked in blocked_tables:
        if blocked["table_number"] == table_number:
            if blocked.get("permanent", False) and blocked["date"] == date:
                return True

            if blocked["date"] == date:
                blocked_start = datetime.strptime(f"{blocked['date']} {blocked['time']}", "%d.%m.%Y %H:%M")
                blocked_end = blocked_start + timedelta(hours=blocked.get("duration", 3))

                # Проверка пересечения временных интервалов
                if not (requested_end <= blocked_start or requested_start >= blocked_end):
                    return True

    return False


def get_blocked_tables_info():
    blocked_tables = get_blocked_tables()
    if not blocked_tables:
        return "🚫 Нет заблокированных столов"

    info = "🚫 Заблокированные столы:\n\n"

    blocks_by_date = {}

    for block in blocked_tables:
        date = block['date']
        if date not in blocks_by_date:
            blocks_by_date[date] = []
        blocks_by_date[date].append(block)

    try:
        sorted_dates = sorted(blocks_by_date.keys(), key=lambda x: datetime.strptime(x, "%d.%m.%Y"))
    except:
        sorted_dates = list(blocks_by_date.keys())

    for date in sorted_dates:
        info += f"📅 {date}:\n"
        date_blocks = blocks_by_date[date]

        permanent_blocks = [b for b in date_blocks if b.get("permanent", False)]
        if permanent_blocks:
            table_numbers = sorted([b['table_number'] for b in permanent_blocks])
            info += f"  🔒 Постоянно заблокированы: {', '.join(f'№{num}' for num in table_numbers)}\n"

        temporary_blocks = [b for b in date_blocks if not b.get("permanent", False)]
        if temporary_blocks:
            for block in sorted(temporary_blocks, key=lambda x: x.get('time', '00:00')):
                duration = block.get('duration', 3)
                time_str = block.get('time', '')
                end_time = (datetime.strptime(f"{date} {time_str}", "%d.%m.%Y %H:%M") +
                            timedelta(hours=duration)).strftime("%H:%M")
                info += f"  ⏰ Стол №{block['table_number']} с {time_str} до {end_time}\n"

        info += "\n"

    return info


def find_available_table(date, start_time, end_time, guests, exclude_tables=None):
    """Найти свободный стол на указанный временной интервал"""
    start = datetime.strptime(f"{date} {start_time}", "%d.%m.%Y %H:%M")
    end = datetime.strptime(f"{date} {end_time}", "%d.%m.%Y %H:%M")
    active = get_active_bookings()

    if exclude_tables is None:
        exclude_tables = []

    for table_number, cfg in sorted(TABLES_CONFIG.items(), key=lambda x: x[1]['seats']):
        if cfg['seats'] < guests:
            continue

        if table_number in exclude_tables:
            continue

        if is_table_blocked(table_number, date, start_time, end_time):
            continue

        busy = False
        for b in active:
            if b['table_number'] == table_number and b['date'] == date:
                # Получаем время начала брони (поддержка старого и нового форматов)
                start_time_b = b.get('start_time') or b.get('time', '00:00')
                bs = datetime.strptime(f"{b['date']} {start_time_b}", "%d.%m.%Y %H:%M")
                be = datetime.strptime(b['end_time'], "%d.%m.%Y %H:%M")
                # Проверка пересечения временных интервалов
                if not (end <= bs or start >= be):
                    busy = True
                    break

        if not busy:
            return table_number

    return None


def get_available_tables(date, start_time, end_time, guests):
    """Получить список всех доступных столов на указанный временной интервал"""
    start = datetime.strptime(f"{date} {start_time}", "%d.%m.%Y %H:%M")
    end = datetime.strptime(f"{date} {end_time}", "%d.%m.%Y %H:%M")
    active = get_active_bookings()
    available_tables = []

    for table_number, cfg in sorted(TABLES_CONFIG.items(), key=lambda x: x[1]['seats']):
        if cfg['seats'] < guests:
            continue

        if is_table_blocked(table_number, date, start_time, end_time):
            continue

        busy = False
        for b in active:
            if b['table_number'] == table_number and b['date'] == date:
                # Получаем время начала брони (поддержка старого и нового форматов)
                start_time_b = b.get('start_time') or b.get('time', '00:00')
                bs = datetime.strptime(f"{b['date']} {start_time_b}", "%d.%m.%Y %H:%M")
                be = datetime.strptime(b['end_time'], "%d.%m.%Y %H:%M")
                if not (end <= bs or start >= be):
                    busy = True
                    break

        if not busy:
            available_tables.append(table_number)

    return available_tables


def save_booking(data):
    """Сохранение брони с указанием времени начала и окончания"""
    bookings = get_bookings()
    data["id"] = len(bookings) + 1
    data["created_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    data["active"] = True
    bookings.append(data)

    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)

    send_booking_reminders(data)

    return data["id"]


def add_direct_booking(date, start_time, end_time, table_number, guests, name, phone, admin_id):
    """Добавить прямую бронь от администратора"""
    booking_data = {
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "table_number": table_number,
        "guests": guests,
        "name": name,
        "phone": phone,
        "user_id": admin_id,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "active": True,
        "source": "direct_admin"
    }

    bookings = get_bookings()
    booking_data["id"] = len(bookings) + 1
    bookings.append(booking_data)

    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(bookings, f, ensure_ascii=False, indent=2)

    return booking_data["id"]


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
    duration = calculate_duration(booking_data)

    # Получаем информацию о времени
    start_time, end_time = get_booking_time_info(booking_data)

    await bot.send_message(
        chat_id,
        f"🔔 Напоминание: ваша бронь на {booking_data['date']}\n"
        f"🕐 Время: с {start_time} до {end_time}\n"
        f"⏳ Длительность: {duration:.1f} часов\n"
        f"⏰ Через {hours_before} час(а/ов)"
    )


def send_booking_reminders(booking_data):
    now = datetime.now()
    # Получаем время начала брони
    start_time_str = booking_data.get('start_time') or booking_data.get('time', '00:00')
    start_time = datetime.strptime(f"{booking_data['date']} {start_time_str}", "%d.%m.%Y %H:%M")
    delta = start_time - now

    if delta >= timedelta(hours=24):
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 24))
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 3))
    elif delta >= timedelta(hours=3):
        asyncio.create_task(schedule_reminder(booking_data["user_id"], booking_data, 3))


async def schedule_reminder(chat_id, booking_data, hours_before):
    now = datetime.now()
    # Получаем время начала брони
    start_time_str = booking_data.get('start_time') or booking_data.get('time', '00:00')
    start_time = datetime.strptime(f"{booking_data['date']} {start_time_str}", "%d.%m.%Y %H:%M")
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
        "Выберите действия ниже:"
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
    user_bookings = [b for b in bookings if b.get("user_id") == message.from_user.id]

    if not user_bookings:
        return await message.answer("ℹ️ У вас нет активных броней для отмены.")

    keyboard_buttons = []
    for b in user_bookings:
        start_time, end_time = get_booking_time_info(b)
        keyboard_buttons.append([types.InlineKeyboardButton(
            text=f"{b['date']} {start_time}-{end_time} | {b['guests']} гостей",
            callback_data=f"cancel_{b['id']}"
        )])

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer("Выберите бронь для отмены:", reply_markup=keyboard)
    await state.set_state(BookingState.cancel_select)


@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_booking_callback(callback: types.CallbackQuery):
    booking_id = int(callback.data.split("_")[1])

    if os.path.exists(BOOKINGS_FILE):
        with open(BOOKINGS_FILE, 'r', encoding='utf-8') as f:
            bookings = json.load(f)
    else:
        bookings = []

    booking_found = False
    for booking in bookings:
        if booking['id'] == booking_id and booking.get("active", True):
            booking['active'] = False
            booking_found = True
            with open(BOOKINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(bookings, f, ensure_ascii=False, indent=2)

            # Получаем информацию о времени
            start_time, end_time = get_booking_time_info(booking)

            await callback.message.edit_text(
                f"🗑 Бронь на {booking['date']} с {start_time} до {end_time} "
                f"для {booking['guests']} гостей успешно отменена ✅"
            )
            await callback.answer("Бронь отменена")
            break

    if not booking_found:
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
    await message.answer("📅 Дата (ДД.ММ.ГГГГ)")
    await state.set_state(BookingState.date)


@dp.message(BookingState.date)
async def date(message: types.Message, state: FSMContext):
    try:
        d = datetime.strptime(message.text, "%d.%m.%Y").date()
        if d < datetime.now().date():
            raise ValueError
        await state.update_data(date=message.text)
        await message.answer("🕐 Время начала бронирования (ЧЧ:ММ)")
        await state.set_state(BookingState.start_time)
    except:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ")


@dp.message(BookingState.start_time)
async def start_time(message: types.Message, state: FSMContext):
    try:
        t_obj = datetime.strptime(message.text, "%H:%M")
        await state.update_data(start_time=message.text)
        await message.answer("🕔 Время окончания бронирования (ЧЧ:ММ)\n\n"
                             "⚠️ *Внимание!* После указанного времени окончания:\n"
                             "• Стол будет автоматически освобожден\n"
                             "• Стол может быть забронирован другими гостями\n"
                             "• Для продления времени обратитесь к администратору",
                             parse_mode="Markdown")
        await state.set_state(BookingState.end_time)
    except:
        await message.answer("Неверный формат времени. Используйте ЧЧ:ММ")


@dp.message(BookingState.end_time)
async def end_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date = data["date"]
    start_time_str = data["start_time"]
    end_time_str = message.text

    # Проверка корректности времени
    is_valid, message_text = validate_booking_time(start_time_str, end_time_str, date)

    if not is_valid:
        await message.answer(f"{message_text}\n\nПожалуйста, введите время окончания снова (ЧЧ:ММ):")
        return

    await state.update_data(end_time=end_time_str)

    # Ищем доступный стол
    table = find_available_table(date, start_time_str, end_time_str, data["guests"])

    if not table:
        await message.answer(
            "😔 Нет свободных столиков на это время.\n"
            "Пожалуйста, выберите другое время или дату.\n\n"
            "Введите время окончания снова (ЧЧ:ММ):"
        )
        return

    duration = calculate_duration({
        "date": date,
        "start_time": start_time_str,
        "end_time": end_time_str
    })

    await state.update_data(table_number=table, duration=duration)

    # Показываем подтверждение брони
    booking_info = (
        f"📋 *Подтверждение бронирования*\n\n"
        f"📅 *Дата:* {date}\n"
        f"🕐 *Время:* с {start_time_str} до {end_time_str}\n"
        f"⏳ *Длительность:* {duration:.1f} часов\n"
        f"👥 *Гостей:* {data['guests']}\n"
        f"🍽 *Стол:* №{table}\n\n"
        f"⚠️ *Важно:*\n"
        f"• Стол будет автоматически освобожден в {end_time_str}\n"
        f"• После этого время стол может быть занят другими гостями\n"
        f"• Для продления времени обратитесь к администратору\n\n"
        f"Всё верно?"
    )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="✅ Да, продолжить", callback_data="booking_confirm"),
                types.InlineKeyboardButton(text="❌ Нет, изменить", callback_data="booking_cancel")
            ]
        ]
    )

    await message.answer(booking_info, parse_mode="Markdown", reply_markup=keyboard)
    await state.set_state(BookingState.confirm_booking)


@dp.callback_query(F.data == "booking_confirm")
async def booking_confirm(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✅ Бронь подтверждена! Теперь введите ваше имя:")
    await state.set_state(BookingState.name)
    await callback.answer()


@dp.callback_query(F.data == "booking_cancel")
async def booking_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Бронирование отменено. Начните заново командой /start")
    await state.clear()
    await callback.answer()


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

    # Сохраняем бронь
    booking_id = save_booking({
        "date": data["date"],
        "start_time": data["start_time"],
        "end_time": data["end_time"],
        "guests": data["guests"],
        "table_number": data["table_number"],
        "name": data["name"],
        "phone": message.text,
        "user_id": message.from_user.id,
        "duration": data.get("duration", 0)
    })

    # Отправляем уведомление всем администраторам
    admins = get_admins()
    for admin_id in admins:
        try:
            await bot.send_message(
                admin_id,
                f"🔥 Новая бронь от клиента:\n"
                f"📅 {data['date']} 🕐 {data['start_time']}-{data['end_time']}\n"
                f"👥 {data['guests']} гостей\n"
                f"🍽 Стол №{data['table_number']}\n"
                f"👤 {data['name']} 📱 {message.text}\n"
                f"⏳ Длительность: {data.get('duration', 0):.1f} часов"
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление администратору {admin_id}: {e}")

    # Отправляем подтверждение клиенту
    warning_text = (
        f"⚠️ *Внимание!*\n"
        f"После {data['end_time']} стол будет автоматически освобожден.\n"
        f"Стол может быть забронирован другими гостей.\n"
        f"Для продления времени обратитесь к администратору."
    )

    await message.answer_photo(
        photo=CONFIRM_IMAGE,
        caption=(
            f"✅ *Ваша бронь подтверждена!*\n\n"
            f"📅 *Дата:* {data['date']}\n"
            f"🕐 *Время:* с {data['start_time']} до {data['end_time']}\n"
            f"⏳ *Длительность:* {data.get('duration', 0):.1f} часов\n"
            f"👥 *Гостей:* {data['guests']}\n"
            f"🍽 *Стол:* №{data['table_number']}\n\n"
            f"{warning_text}\n\n"
            f"🔔 Напоминания придут за 24 и 3 часа до начала\n"
            f"🏮 Ждем вас для незабываемого вечера!"
        ),
        parse_mode="Markdown"
    )

    await state.clear()


# ===== МОИ БРОНИ =====
@dp.message(F.text == "🎫 Мои брони")
async def my_bookings(message: types.Message):
    bookings = get_active_bookings()
    user_bookings = [b for b in bookings if b.get("user_id") == message.from_user.id]

    if not user_bookings:
        return await message.answer("У вас нет активных броней")

    text = "🎫 *Ваши активные брони:*\n\n"
    for b in user_bookings:
        duration = calculate_duration(b)
        start_time, end_time = get_booking_time_info(b)

        text += (
            f"📅 *Дата:* {b['date']}\n"
            f"🕐 *Время:* с {start_time} до {end_time}\n"
            f"⏳ *Длительность:* {duration:.1f} часов\n"
            f"👥 *Гостей:* {b['guests']}\n"
            f"🍽 *Стол:* №{b['table_number']}\n"
            f"📞 *Телефон:* {b['phone']}\n"
            f"⚠️ *Стол освободится в:* {end_time}\n\n"
        )

    text += "\n⚠️ *Напоминание:* После указанного времени стол будет автоматически освобожден и может быть занят другими гостями."

    await message.answer(text, parse_mode="Markdown")


# ===== АДМИН ПАНЕЛЬ =====
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа к админ панели")

    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📅 Сегодняшние брони"), types.KeyboardButton(text="🗓 Все брони")],
            [types.KeyboardButton(text="📞 Добавить прямую бронь"),
             types.KeyboardButton(text="🔐 Блокировка/разблокировка")],
            [types.KeyboardButton(text="📊 Статистика")],
            [types.KeyboardButton(text="🚪 Выйти из админки")]
        ],
        resize_keyboard=True
    )

    await message.answer("🛠 Добро пожаловать в админ панель!", reply_markup=keyboard)


# ===== СЕГОДНЯШНИЕ БРОНИ =====
@dp.message(F.text == "📅 Сегодняшние брони")
async def todays_bookings(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа")

    today = datetime.now().strftime("%d.%m.%Y")
    active = get_active_bookings()
    todays = [b for b in active if b["date"] == today]

    if not todays:
        return await message.answer("Сегодня броней нет")

    text = f"📅 *Брони на сегодня ({today}):*\n\n"
    for b in todays:
        source = "📞" if b.get("source") == "direct_admin" else "🤖"
        duration = calculate_duration(b)
        start_time, end_time = get_booking_time_info(b)

        text += (
            f"{source} *{start_time}-{end_time}* | Стол №{b['table_number']} | "
            f"{b['guests']} гостей | {b['name']} | {b['phone']}\n"
            f"   ⏳ Длительность: {duration:.1f} часов | 🔚 Освободится: {end_time}\n\n"
        )

    await message.answer(text, parse_mode="Markdown")


# ===== ВСЕ БРОНИ С ПРОСРОЧЕННЫМИ =====
@dp.message(F.text == "🗓 Все брони")
async def all_bookings(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа")

    cleaned_count = auto_cleanup_bookings()

    bookings = get_bookings()
    if not bookings:
        return await message.answer("Брони отсутствуют")

    active_bookings = [b for b in bookings if b.get("active", True)]
    cancelled_bookings = [b for b in bookings if not b.get("active", True)]
    expired_bookings = get_expired_bookings()

    active_bookings = [b for b in active_bookings if b not in expired_bookings]

    text = "📋 *Все брони:*\n"

    if cleaned_count > 0:
        text += f"🧹 Автоочистка: удалено {cleaned_count} старых броней\n\n"

    if active_bookings:
        text += f"🟢 *Активные ({len(active_bookings)}):*\n"
        for b in active_bookings:
            source = "📞" if b.get("source") == "direct_admin" else "🤖"
            duration = calculate_duration(b)
            start_time, end_time = get_booking_time_info(b)
            text += (
                f"{source} {b['date']} {start_time}-{end_time} | "
                f"Стол №{b['table_number']} | {b['guests']} гостей | "
                f"{b['name']} | {b['phone']}\n"
                f"   ⏳ {duration:.1f}ч | 🔚 {end_time}\n"
            )
        text += "\n"

    if expired_bookings:
        text += f"🟡 *Истёкшие (24ч) ({len(expired_bookings)}):*\n"
        for b in expired_bookings:
            end_time_dt = datetime.strptime(b["end_time"], "%d.%m.%Y %H:%M")
            hours_ago = (datetime.now() - end_time_dt).total_seconds() / 3600
            source = "📞" if b.get("source") == "direct_admin" else "🤖"
            duration = calculate_duration(b)
            start_time, end_time = get_booking_time_info(b)
            text += (
                f"{source} {b['date']} {start_time}-{end_time} | "
                f"Стол №{b['table_number']} | {b['guests']} гостей | "
                f"{b['name']} | завершена {hours_ago:.1f} ч. назад\n"
                f"   ⏳ {duration:.1f}ч\n"
            )
        text += "\n"

    if cancelled_bookings:
        text += f"🔴 *Отменённые ({len(cancelled_bookings)}):*\n"
        for b in cancelled_bookings:
            created = datetime.strptime(b.get("created_at", ""), "%d.%m.%Y %H:%M:%S")
            days_ago = (datetime.now() - created).days
            source = "📞" if b.get("source") == "direct_admin" else "🤖"
            duration = calculate_duration(b)
            start_time, end_time = get_booking_time_info(b)
            text += (
                f"{source} {b['date']} {start_time}-{end_time} | "
                f"Стол №{b['table_number']} | {b['guests']} гостей | "
                f"{b['name']} | отменена {days_ago} дн. назад\n"
                f"   ⏳ {duration:.1f}ч\n"
            )

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="🗑️ Очистить все", callback_data="cleanup_all")
            ],
            [
                types.InlineKeyboardButton(text="⏰ Очистить истёкшие", callback_data="cleanup_expired"),
                types.InlineKeyboardButton(text="❌ Очистить отмененные", callback_data="cleanup_cancelled")
            ]
        ]
    )

    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


# ===== ДОБАВЛЕНИЕ ПРЯМОЙ БРОНИ =====
@dp.message(F.text == "📞 Добавить прямую бронь")
async def direct_booking_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа")

    await state.clear()
    await message.answer("📅 Введите дату для брони (ДД.ММ.ГГГГ):")
    await state.set_state(DirectBookingState.waiting_for_date)


@dp.message(DirectBookingState.waiting_for_date)
async def direct_booking_date(message: types.Message, state: FSMContext):
    try:
        d = datetime.strptime(message.text, "%d.%m.%Y").date()
        if d < datetime.now().date():
            raise ValueError
        await state.update_data(date=message.text)
        await message.answer("🕐 Введите время начала брони (ЧЧ:ММ):")
        await state.set_state(DirectBookingState.waiting_for_start_time)
    except:
        await message.answer("Неверный формат даты. Используйте ДД.ММ.ГГГГ")


@dp.message(DirectBookingState.waiting_for_start_time)
async def direct_booking_start_time(message: types.Message, state: FSMContext):
    try:
        t_obj = datetime.strptime(message.text, "%H:%M")
        await state.update_data(start_time=message.text)
        await message.answer("🕔 Введите время окончания брони (ЧЧ:ММ):")
        await state.set_state(DirectBookingState.waiting_for_end_time)
    except:
        await message.answer("Неверный формат времени. Используйте ЧЧ:ММ")


@dp.message(DirectBookingState.waiting_for_end_time)
async def direct_booking_end_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    date = data["date"]
    start_time_str = data["start_time"]
    end_time_str = message.text

    # Проверка корректности времени
    is_valid, message_text = validate_booking_time(start_time_str, end_time_str, date)

    if not is_valid:
        await message.answer(f"{message_text}\n\nПожалуйста, введите время окончания снова (ЧЧ:ММ):")
        return

    await state.update_data(end_time=message.text)
    await message.answer("👥 Введите количество гостей (1-4):")
    await state.set_state(DirectBookingState.waiting_for_guests)


@dp.message(DirectBookingState.waiting_for_guests)
async def direct_booking_guests(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Введите число от 1 до 4")
    guests = int(message.text)
    if guests < 1 or guests > 4:
        return await message.answer("Введите число от 1 до 4")

    await state.update_data(guests=guests)

    data = await state.get_data()
    available_tables = get_available_tables(data["date"], data["start_time"], data["end_time"], guests)

    if not available_tables:
        await message.answer("😔 Нет свободных столиков на это время. Попробуйте другую дату или время.")
        await state.clear()
        return

    # Создаем кнопки с доступными столами
    keyboard_buttons = []
    row = []
    for i, table in enumerate(available_tables, 1):
        row.append(types.InlineKeyboardButton(text=f"№{table}", callback_data=f"direct_table_{table}"))
        if i % 4 == 0:
            keyboard_buttons.append(row)
            row = []
    if row:
        keyboard_buttons.append(row)

    keyboard_buttons.append([types.InlineKeyboardButton(text="❌ Отмена", callback_data="direct_cancel")])

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer(
        f"Доступные столы на {data['date']} с {data['start_time']} до {data['end_time']} "
        f"для {guests} гостей:",
        reply_markup=keyboard
    )
    await state.set_state(DirectBookingState.waiting_for_table)


@dp.callback_query(F.data.startswith("direct_table_"))
async def direct_booking_table(callback: types.CallbackQuery, state: FSMContext):
    table_number = int(callback.data.split("_")[2])

    await state.update_data(table_number=table_number)
    await callback.message.edit_text(f"✅ Выбран стол №{table_number}")
    await callback.message.answer("👤 Введите имя клиента:")
    await state.set_state(DirectBookingState.waiting_for_name)
    await callback.answer()


@dp.callback_query(F.data == "direct_cancel")
async def direct_booking_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Добавление брони отменено")
    await state.clear()
    await callback.answer()


@dp.message(DirectBookingState.waiting_for_name)
async def direct_booking_name(message: types.Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        return await message.answer("Введите имя")
    await state.update_data(name=message.text.strip())
    await message.answer("📱 Введите телефон клиента:")
    await state.set_state(DirectBookingState.waiting_for_phone)


@dp.message(DirectBookingState.waiting_for_phone)
async def direct_booking_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    duration = calculate_duration({
        "date": data["date"],
        "start_time": data["start_time"],
        "end_time": data["end_time"]
    })

    # Сохраняем бронь
    booking_id = add_direct_booking(
        data["date"],
        data["start_time"],
        data["end_time"],
        data["table_number"],
        data["guests"],
        data["name"],
        message.text,
        message.from_user.id
    )

    warning_text = (
        f"⚠️ *Внимание администратора!*\n"
        f"После {data['end_time']} стол будет автоматически освобожден.\n"
        f"Стол может быть забронирован другими гостями."
    )

    await message.answer(
        f"✅ *Прямая бронь добавлена!*\n\n"
        f"📅 *Дата:* {data['date']}\n"
        f"🕐 *Время:* с {data['start_time']} до {data['end_time']}\n"
        f"⏳ *Длительность:* {duration:.1f} часов\n"
        f"👥 *Гостей:* {data['guests']}\n"
        f"🍽 *Стол:* №{data['table_number']}\n"
        f"👤 *Имя:* {data['name']}\n"
        f"📱 *Телефон:* {message.text}\n"
        f"📝 *ID брони:* {booking_id}\n\n"
        f"{warning_text}",
        parse_mode="Markdown"
    )

    await state.clear()


# ===== БЛОКИРОВКА/РАЗБЛОКИРОВКА СТОЛИКА =====
@dp.message(F.text == "🔐 Блокировка/разблокировка")
async def block_unblock_menu(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа")

    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🚫 Заблокировать стол", callback_data="block_table_menu")],
            [types.InlineKeyboardButton(text="✅ Разблокировать стол", callback_data="unblock_table_menu")],
            [types.InlineKeyboardButton(text="📋 Показать блокировки", callback_data="show_blocks")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]
        ]
    )

    await message.answer("🔐 *Меню управления блокировками столов:*", reply_markup=keyboard, parse_mode="Markdown")


@dp.callback_query(F.data == "block_table_menu")
async def block_table_menu(callback: types.CallbackQuery):
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="⏰ На конкретное время", callback_data="block_temporary")],
            [types.InlineKeyboardButton(text="🔒 Постоянно (весь день)", callback_data="block_permanent")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_block_menu")]
        ]
    )

    await callback.message.edit_text(
        "Выберите тип блокировки столика:\n"
        "⚠️ Можно вводить несколько столов через запятую (например: 1,2,5 или 10-15)"
        , reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "unblock_table_menu")
async def unblock_table_menu(callback: types.CallbackQuery):
    blocked_tables = get_blocked_tables()
    if not blocked_tables:
        await callback.message.edit_text("❌ Нет заблокированных столиков")
        return

    keyboard_buttons = []
    for blocked in blocked_tables:
        if blocked.get("permanent", False):
            text = f"Стол №{blocked['table_number']} - {blocked['date']} (постоянно)"
        else:
            end_time = (datetime.strptime(f"{blocked['date']} {blocked.get('time', '00:00')}", "%d.%m.%Y %H:%M") +
                        timedelta(hours=blocked.get('duration', 3))).strftime("%H:%M")
            text = f"Стол №{blocked['table_number']} - {blocked['date']} {blocked.get('time', '')}-{end_time}"
        keyboard_buttons.append([types.InlineKeyboardButton(
            text=text,
            callback_data=f"unblock_{blocked_tables.index(blocked)}"
        )])

    keyboard_buttons.append([types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_block_menu")])

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await callback.message.edit_text("Выберите столик для разблокировки:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "show_blocks")
async def show_blocks(callback: types.CallbackQuery):
    info = get_blocked_tables_info()
    await callback.message.edit_text(info)
    await callback.answer()


@dp.callback_query(F.data == "back_to_block_menu")
async def back_to_block_menu(callback: types.CallbackQuery):
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🚫 Заблокировать стол", callback_data="block_table_menu")],
            [types.InlineKeyboardButton(text="✅ Разблокировать стол", callback_data="unblock_table_menu")],
            [types.InlineKeyboardButton(text="📋 Показать блокировки", callback_data="show_blocks")],
            [types.InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]
        ]
    )

    await callback.message.edit_text("🔐 *Меню управления блокировками столов:*", reply_markup=keyboard,
                                     parse_mode="Markdown")
    await callback.answer()


@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin_menu(callback: types.CallbackQuery):
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📅 Сегодняшние брони"), types.KeyboardButton(text="🗓 Все брони")],
            [types.KeyboardButton(text="📞 Добавить прямую бронь"),
             types.KeyboardButton(text="🔐 Блокировка/разблокировка")],
            [types.KeyboardButton(text="📊 Статистика")],
            [types.KeyboardButton(text="🚪 Выйти из админки")]
        ],
        resize_keyboard=True
    )

    await callback.message.edit_text("🛠 Возврат в админ панель")
    await callback.message.answer("Выберите действие:", reply_markup=keyboard)
    await callback.answer()


# ===== БЛОКИРОВКА СТОЛИКА (ПРОЦЕСС) =====
@dp.callback_query(F.data == "block_temporary")
async def block_temporary(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите номера столиков для блокировки:\n"
        "• Можно через запятую: 1,2,5\n"
        "• Можно диапазоном: 10-15\n"
        "• Можно комбинировать: 1,3,5-8"
    )
    await state.set_state(BlockTableState.waiting_for_table_number)
    await state.update_data(block_type="temporary")
    await callback.answer()


@dp.callback_query(F.data == "block_permanent")
async def block_permanent(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите номера столиков для постоянной блокировки:\n"
        "• Можно через запятую: 1,2,5\n"
        "• Можно диапазоном: 10-15\n"
        "• Можно комбинировать: 1,3,5-8"
    )
    await state.set_state(BlockTableState.waiting_for_table_number)
    await state.update_data(block_type="permanent")
    await callback.answer()


def parse_table_numbers(input_text):
    """Парсинг номеров столов из строки (поддержка запятых и диапазонов)"""
    table_numbers = set()

    # Удаляем пробелы
    input_text = input_text.replace(" ", "")

    # Разделяем по запятым
    parts = input_text.split(",")

    for part in parts:
        if "-" in part:
            # Обрабатываем диапазон
            try:
                start, end = map(int, part.split("-"))
                if start <= end:
                    table_numbers.update(range(start, end + 1))
            except:
                continue
        else:
            # Одиночный номер
            try:
                table_numbers.add(int(part))
            except:
                continue

    # Фильтруем только существующие номера столов
    valid_tables = [num for num in table_numbers if num in TABLES_CONFIG]
    return sorted(valid_tables)


@dp.message(BlockTableState.waiting_for_table_number)
async def block_table_number(message: types.Message, state: FSMContext):
    table_numbers = parse_table_numbers(message.text)

    if not table_numbers:
        await message.answer(
            f"❌ Неверный формат или номера столов.\n"
            f"Примеры:\n"
            f"• 1,2,5\n"
            f"• 10-15\n"
            f"• 1,3,5-8\n"
            f"Доступные номера: 1-{len(TABLES_CONFIG)}"
        )
        return

    await state.update_data(table_numbers=table_numbers)

    data = await state.get_data()
    if data.get("block_type") == "permanent":
        await message.answer(
            f"✅ Выбраны столы: {', '.join(f'№{num}' for num in table_numbers)}\n📅 Введите дату для блокировки (ДД.ММ.ГГГГ):")
        await state.set_state(BlockTableState.waiting_for_date)
    else:
        await message.answer(
            f"✅ Выбраны столы: {', '.join(f'№{num}' for num in table_numbers)}\n📅 Введите дату для блокировки (ДД.ММ.ГГГГ):")
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
            table_numbers = data["table_numbers"]

            for table_number in table_numbers:
                blocked_tables.append({
                    "table_number": table_number,
                    "date": data["date"],
                    "permanent": True,
                    "blocked_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                    "blocked_by": "admin"
                })

            save_blocked_tables(blocked_tables)

            await message.answer(
                f"✅ Столы {', '.join(f'№{num}' for num in table_numbers)} заблокированы на {data['date']} на весь день"
            )

            # Возвращаемся в меню блокировок
            keyboard = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [types.InlineKeyboardButton(text="🔐 Вернуться в меню блокировок",
                                                callback_data="back_to_block_menu")]
                ]
            )
            await message.answer("Что дальше?", reply_markup=keyboard)
            await state.clear()
        else:
            await message.answer("⏰ Введите время начала блокировки (ЧЧ:ММ):")
            await state.set_state(BlockTableState.waiting_for_time)
    except:
        await message.answer("Неверный формат дата. Используйте ДД.ММ.ГГГГ")


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
    table_numbers = data["table_numbers"]

    for table_number in table_numbers:
        blocked_tables.append({
            "table_number": table_number,
            "date": data["date"],
            "time": data["time"],
            "duration": duration,
            "permanent": False,
            "blocked_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "blocked_by": "admin"
        })

    save_blocked_tables(blocked_tables)

    end_time = (datetime.strptime(f"{data['date']} {data['time']}", "%d.%m.%Y %H:%M") +
                timedelta(hours=duration)).strftime("%H:%M")

    await message.answer(
        f"✅ Столы {', '.join(f'№{num}' for num in table_numbers)} заблокированы:\n"
        f"📅 {data['date']}\n"
        f"🕐 Время: с {data['time']} до {end_time}\n"
        f"⏳ Продолжительность: {message.text}",
        reply_markup=types.ReplyKeyboardRemove()
    )

    # Возвращаемся в меню блокировок
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🔐 Вернуться в меню блокировок", callback_data="back_to_block_menu")]
        ]
    )
    await message.answer("Что дальше?", reply_markup=keyboard)
    await state.clear()


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

        # Возвращаемся в меню блокировок
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="🔐 Вернуться в меню блокировок", callback_data="back_to_block_menu")]
            ]
        )
        await callback.message.answer("Что дальше?", reply_markup=keyboard)
    else:
        await callback.message.edit_text("❌ Ошибка: столик не найден")

    await callback.answer()


# ===== ОЧИСТКА БРОНЕЙ (ТОЛЬКО В КНОПКЕ "ВСЕ БРОНИ") =====
@dp.callback_query(F.data == "cleanup_all")
async def cleanup_all(callback: types.CallbackQuery):
    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)

    await callback.message.edit_text("✅ Все брони успешно очищены!")
    await callback.answer()


@dp.callback_query(F.data == "cleanup_expired")
async def cleanup_expired(callback: types.CallbackQuery):
    bookings = get_bookings()
    now = datetime.now()

    cleaned_bookings = []
    expired_count = 0

    for b in bookings:
        if b.get("active", True):
            try:
                end_time = datetime.strptime(b["end_time"], "%d.%m.%Y %H:%M")
                if end_time < now:
                    expired_count += 1
                    continue
            except:
                pass

        cleaned_bookings.append(b)

    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned_bookings, f, ensure_ascii=False, indent=2)

    await callback.message.edit_text(f"✅ Удалено {expired_count} истёкших броней!")
    await callback.answer()


@dp.callback_query(F.data == "cleanup_cancelled")
async def cleanup_cancelled(callback: types.CallbackQuery):
    bookings = get_bookings()

    active_bookings = [b for b in bookings if b.get("active", True)]
    cancelled_count = len(bookings) - len(active_bookings)

    with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(active_bookings, f, ensure_ascii=False, indent=2)

    await callback.message.edit_text(f"✅ Удалено {cancelled_count} отмененных броней!")
    await callback.answer()


# ===== СТАТИСТИКА =====
@dp.message(F.text == "📊 Статистика")
async def bookings_statistics(message: types.Message):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа")

    cleaned_count = auto_cleanup_bookings()

    bookings = get_active_bookings()
    total_active = len(bookings)
    total_guests = sum(b['guests'] for b in bookings)

    expired_bookings = get_expired_bookings()
    total_expired = len(expired_bookings)

    blocked_tables = get_blocked_tables()
    total_blocked = len(blocked_tables)

    today = datetime.now().strftime("%d.%m.%Y")
    today_bookings = [b for b in bookings if b["date"] == today]
    today_guests = sum(b['guests'] for b in today_bookings)

    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    tomorrow_bookings = [b for b in bookings if b["date"] == tomorrow]
    tomorrow_guests = sum(b['guests'] for b in tomorrow_bookings)

    # Получаем информацию о блокировках
    blocked_info = get_blocked_tables_info()

    text = (
        f"📊 *Статистика:*\n\n"
        f"🔹 Активные брони: {total_active}\n"
        f"🔹 Истёкшие (24ч): {total_expired}\n"
        f"🔹 Всего гостей: {total_guests}\n\n"
        f"📅 *Сегодня ({today}):*\n"
        f"   • Броней: {len(today_bookings)}\n"
        f"   • Гостей: {today_guests}\n\n"
        f"📅 *Завтра ({tomorrow}):*\n"
        f"   • Броней: {len(tomorrow_bookings)}\n"
        f"   • Гостей: {tomorrow_guests}\n\n"
        f"🚫 Заблокированных столиков: {total_blocked}\n"
    )

    if cleaned_count > 0:
        text += f"\n🧹 Автоочистка: удалено {cleaned_count} старых броней"

    # Добавляем информацию о блокировках
    text += f"\n\n{blocked_info}"

    await message.answer(text, parse_mode="Markdown")


# ===== ВЫХОД ИЗ АДМИНКИ =====
@dp.message(F.text == "🚪 Выйти из админки")
async def exit_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа")

    await state.clear()
    await start(message, state)


# ===== КОМАНДА ДЛЯ ДОБАВЛЕНИЯ АДМИНИСТРАТОРОВ ЧЕРЕЗ КОНСОЛЬ =====
@dp.message(Command("addadmin"))
async def add_admin_command(message: types.Message):
    """Команда для добавления администратора (только для главного администратора)"""
    if message.from_user.id != MAIN_ADMIN_ID:
        return await message.answer("❌ Эта команда доступна только главному администратору")

    # Парсим команду: /addadmin 123456789
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: `/addadmin <ID_пользователя>`", parse_mode="Markdown")
        return

    try:
        new_admin_id = int(parts[1])
        if add_admin(new_admin_id):
            await message.answer(f"✅ Пользователь с ID `{new_admin_id}` успешно добавлен в администраторы!",
                                 parse_mode="Markdown")
        else:
            await message.answer(f"ℹ️ Пользователь с ID `{new_admin_id}` уже является администратором.",
                                 parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")


@dp.message(Command("removeadmin"))
async def remove_admin_command(message: types.Message):
    """Команда для удаления администратора (только для главного администратора)"""
    if message.from_user.id != MAIN_ADMIN_ID:
        return await message.answer("❌ Эта команда доступна только главному администратору")

    # Парсим команду: /removeadmin 123456789
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: `/removeadmin <ID_пользователя>`", parse_mode="Markdown")
        return

    try:
        admin_id_to_remove = int(parts[1])
        if remove_admin(admin_id_to_remove):
            await message.answer(f"✅ Администратор с ID `{admin_id_to_remove}` успешно удален!", parse_mode="Markdown")
        else:
            await message.answer(f"❌ Не удалось удалить администратора с ID `{admin_id_to_remove}`",
                                 parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный формат ID. ID должен быть числом.")


@dp.message(Command("listadmins"))
async def list_admins_command(message: types.Message):
    """Команда для просмотра списка администраторов"""
    if not is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет доступа к этой команде")

    admins = get_admins()

    text = f"👑 *Список администраторов ({len(admins)}):*\n\n"
    for i, admin_id in enumerate(admins, 1):
        is_main = " (👑 Главный)" if admin_id == MAIN_ADMIN_ID else ""
        text += f"{i}. ID: `{admin_id}`{is_main}\n"

    await message.answer(text, parse_mode="Markdown")


# ===== АВТОМАТИЧЕСКАЯ ОЧИСТКА ПРИ ЗАПУСКЕ =====
async def auto_cleanup_on_startup():
    cleaned_count = auto_cleanup_bookings()
    if cleaned_count > 0:
        print(f"🧹 Автоочистка при запуске: удалено {cleaned_count} старых броней")


# ===== ЗАПУСК =====
async def main():
    await auto_cleanup_on_startup()

    print("🚀 Бот запущен...")
    print(f"👑 Главный администратор: {MAIN_ADMIN_ID}")
    print(f"📋 Список администраторов: {get_admins()}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())