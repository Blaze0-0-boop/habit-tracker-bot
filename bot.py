import json
import logging
import os
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Файл, где бот хранит данные всех пользователей
DATA_FILE = "data.json"
# Часовой пояс, по которому считается "сегодня" (поменяй на свой)
TIMEZONE = ZoneInfo("Asia/Almaty")

# Лимиты
MAX_HABITS = 10
MAX_NAME_LENGTH = 50

# ---------- Опыт и уровни питомца ----------

XP_PER_HABIT = 10   # опыт за одну выполненную привычку
XP_ALL_DONE = 20    # бонус за идеальный день (раз в сутки)
LEVEL_STEP = 50     # сколько опыта нужно для нового уровня

# Стадии питомца: (с какого уровня, эмодзи, название)
PET_STAGES = [
    (1, "🥚", "Яйцо"),
    (3, "🐣", "Птенец"),
    (5, "🐥", "Цыплёнок"),
    (8, "🦅", "Орёл"),
    (12, "🐉", "Дракон"),
]

# Награды за серии дней: серия -> (сообщение, бонусный опыт)
MILESTONES = {
    3: ("🔥 3 дня подряд! Хорошее начало!", 15),
    7: ("🏆 Целая неделя подряд! Привычка формируется!", 30),
    14: ("💪 Две недели без пропусков! Отличная дисциплина!", 60),
    30: ("👑 30 дней подряд! Это уже часть твоей жизни!", 150),
}

# Достижения
BADGES = {
    "first_step": "🌱 Первый шаг",
    "perfect_day": "🎯 Идеальный день",
    "streak_7": "🏆 Неделя подряд",
    "streak_30": "👑 Месяц подряд",
    "collector": "📚 Коллекционер (5 привычек)",
}

# ---------- Стили (характер) бота ----------

STYLES = {
    "friend": {
        "title": "🤗 Мягкий друг",
        "welcome": "Привет, {name}! 🤗 Рад тебя видеть. Будем вместе растить полезные привычки и твоего питомца.",
        "added": "Здорово! Привычка «{habit}» добавлена. У тебя всё получится 💛",
        "done": ["Молодец! Так держать 💛", "Отлично, я тобой горжусь!", "Ещё один шаг вперёд 🌱"],
        "all_done": "🎉 Все привычки на сегодня выполнены! Ты большой молодец, отдыхай со спокойной душой.",
    },
    "coach": {
        "title": "💪 Строгий тренер",
        "welcome": "Здравствуй, {name}. Здесь без поблажек: сделал дело, отметь. Начинаем тренировку характера 💪",
        "added": "Привычка «{habit}» принята. Теперь выполняй, а не откладывай.",
        "done": ["Принято. Следующая!", "Это минимум. Не расслабляйся 💪", "Дисциплина побеждает мотивацию."],
        "all_done": "🏁 План на сегодня выполнен. Завтра повторим, без пропусков.",
    },
    "joker": {
        "title": "😄 Шутник",
        "welcome": "Йо, {name}! 😎 Кормишь меня выполненными привычками, а я расту. Договорились?",
        "added": "«{habit}» в списке! Теперь у тебя нет отмазок 😏",
        "done": ["Ого, кто-то у нас продуктивный! 😎", "Плюс балл в карму 🌟", "Питомец в восторге 🕺"],
        "all_done": "🎉 Всё выполнено! Ты просто машина. Но не забудь поспать 😴",
    },
}
DEFAULT_STYLE = "friend"

# ---------- Кнопки главного меню ----------

BTN_ADD = "➕ Добавить привычку"
BTN_LIST = "📋 Мои привычки"
BTN_PET = "🐾 Питомец"
BTN_STATS = "📊 Статистика"
BTN_STYLE = "🎭 Стиль бота"
BTN_HELP = "❓ Помощь"
MENU_BUTTONS = {BTN_ADD, BTN_LIST, BTN_PET, BTN_STATS, BTN_STYLE, BTN_HELP}

MAIN_MENU = ReplyKeyboardMarkup(
    [[BTN_LIST, BTN_ADD], [BTN_PET, BTN_STATS], [BTN_STYLE, BTN_HELP]],
    resize_keyboard=True,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ---------- Работа с данными (JSON) ----------

def load_data() -> dict:
    """Читает данные из файла. Если файла нет или он повреждён, возвращает пустой словарь."""
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data() -> None:
    """Сохраняет все данные в файл."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


def get_user(user_id: int) -> dict:
    """Возвращает данные пользователя. Недостающие поля добавляет (в том числе для старых данных)."""
    uid = str(user_id)  # в JSON ключи всегда строки
    user = data.setdefault(uid, {})
    user.setdefault("habits", [])
    user.setdefault("next_id", 1)
    user.setdefault("xp", 0)
    user.setdefault("style", DEFAULT_STYLE)
    user.setdefault("awards", [])   # разовые награды, чтобы нельзя было получить их повторно
    user.setdefault("badges", [])   # полученные достижения
    return user


def find_habit(user: dict, habit_id: str) -> dict | None:
    """Ищет привычку по id. Если не нашли, возвращает None."""
    for habit in user["habits"]:
        if str(habit["id"]) == habit_id:
            return habit
    return None


def style_of(user: dict) -> dict:
    """Возвращает словарь фраз выбранного стиля."""
    return STYLES.get(user["style"], STYLES[DEFAULT_STYLE])


# ---------- Логика дат и серий ----------

def today() -> date:
    return datetime.now(TIMEZONE).date()


def calc_streak(done_dates: list[str]) -> int:
    """Считает, сколько дней подряд выполнена привычка."""
    days = set(done_dates)
    day = today()
    # Если сегодня ещё не отмечено, серия не прервана: считаем со вчера
    if day.isoformat() not in days:
        day -= timedelta(days=1)
    streak = 0
    while day.isoformat() in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def week_squares(done_dates: list[str]) -> str:
    """Рисует последние 7 дней: 🟩 выполнено, ⬜ нет."""
    days = set(done_dates)
    result = ""
    for i in range(6, -1, -1):
        d = today() - timedelta(days=i)
        result += "🟩" if d.isoformat() in days else "⬜"
    return result


# ---------- Питомец, опыт, достижения ----------

def get_level(xp: int) -> int:
    return xp // LEVEL_STEP + 1


def get_stage(level: int) -> tuple:
    """Возвращает стадию питомца (уровень, эмодзи, название) для данного уровня."""
    result = PET_STAGES[0]
    for stage in PET_STAGES:
        if level >= stage[0]:
            result = stage
    return result


def add_xp(user: dict, amount: int) -> None:
    user["xp"] = max(0, user["xp"] + amount)


def give_award_once(user: dict, key: str) -> bool:
    """Возвращает True, если награда с таким ключом выдаётся впервые."""
    if key in user["awards"]:
        return False
    user["awards"].append(key)
    return True


def give_badge(user: dict, key: str) -> str | None:
    """Выдаёт достижение. Возвращает его название, если оно новое."""
    if key in user["badges"]:
        return None
    user["badges"].append(key)
    return BADGES[key]


def pet_mood(user: dict) -> str:
    """Настроение питомца зависит от того, когда ты последний раз выполнял привычки."""
    all_dates = [d for h in user["habits"] for d in h["done_dates"]]
    if not all_dates:
        return "😴 Спит и ждёт твою первую привычку"
    gap = (today() - date.fromisoformat(max(all_dates))).days
    if gap <= 0:
        return "😄 Счастлив: сегодня ты уже молодец!"
    if gap == 1:
        return "🙂 Спокоен, но ждёт тебя сегодня"
    return f"😢 Скучает: тебя не было {gap} дн."


# ---------- Клавиатуры и тексты ----------

def build_habits_view(user: dict):
    """Собирает текст и Inline-кнопки для списка привычек."""
    if not user["habits"]:
        return "У тебя пока нет привычек. Нажми «➕ Добавить привычку»!", None

    today_str = today().isoformat()
    done_count = sum(1 for h in user["habits"] if today_str in h["done_dates"])
    text = f"📋 Твои привычки на сегодня: {done_count}/{len(user['habits'])}"

    keyboard = []
    for habit in user["habits"]:
        mark = "✅" if today_str in habit["done_dates"] else "⬜"
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{mark} {habit['name']}", callback_data=f"toggle:{habit['id']}"
                ),
                InlineKeyboardButton("🗑", callback_data=f"del:{habit['id']}"),
            ]
        )
    return text, InlineKeyboardMarkup(keyboard)


def build_style_view(user: dict):
    """Кнопки выбора стиля бота (текущий отмечен галочкой)."""
    keyboard = []
    for key, style in STYLES.items():
        mark = "✓ " if key == user["style"] else ""
        keyboard.append(
            [InlineKeyboardButton(f"{mark}{style['title']}", callback_data=f"style:{key}")]
        )
    return "Выбери характер бота:", InlineKeyboardMarkup(keyboard)


# ---------- Команды и меню ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    name = update.effective_user.first_name
    await update.message.reply_text(
        style_of(user)["welcome"].format(name=name), reply_markup=MAIN_MENU
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Как это работает:\n"
        "1. «➕ Добавить привычку» - напиши название, например «Пить воду».\n"
        "2. «📋 Мои привычки» - нажимай на привычку, чтобы отметить её. "
        "Нажми ещё раз, чтобы отменить. 🗑 удаляет привычку.\n"
        "3. Каждое выполнение даёт опыт, а опыт растит твоего питомца 🐾\n"
        "4. «📊 Статистика» - серии дней и последние 7 дней.\n"
        "5. «🎭 Стиль бота» - выбери, как со мной общаться.\n\n"
        "Серии дней и идеальные дни дают бонусный опыт и достижения 🏅",
        reply_markup=MAIN_MENU,
    )


async def show_habits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    text, markup = build_habits_view(user)
    await update.message.reply_text(text, reply_markup=markup)


async def show_pet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    level = get_level(user["xp"])
    _, emoji, stage_name = get_stage(level)

    # Полоска прогресса до следующего уровня
    in_level = user["xp"] % LEVEL_STEP
    filled = in_level * 10 // LEVEL_STEP
    bar = "▰" * filled + "▱" * (10 - filled)

    badges = "\n".join(BADGES[b] for b in user["badges"] if b in BADGES) or "пока нет"
    await update.message.reply_text(
        f"{emoji} Твой питомец: {stage_name}\n"
        f"Уровень {level}\n"
        f"{pet_mood(user)}\n\n"
        f"XP: {bar} {in_level}/{LEVEL_STEP}\n\n"
        f"🏅 Достижения:\n{badges}"
    )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    if not user["habits"]:
        await update.message.reply_text("Статистики пока нет: сначала добавь привычку.")
        return

    level = get_level(user["xp"])
    _, emoji, _ = get_stage(level)
    lines = [f"📊 Твоя статистика:\n{emoji} Уровень {level} | Всего XP: {user['xp']}\n"]
    for habit in user["habits"]:
        streak = calc_streak(habit["done_dates"])
        total = len(habit["done_dates"])
        lines.append(
            f"{habit['name']}\n"
            f"{week_squares(habit['done_dates'])}\n"
            f"🔥 Серия: {streak} дн. | Всего: {total}\n"
        )
    await update.message.reply_text("\n".join(lines))


async def show_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    text, markup = build_style_view(user)
    await update.message.reply_text(text, reply_markup=markup)


async def ask_habit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = get_user(update.effective_user.id)
    if len(user["habits"]) >= MAX_HABITS:
        await update.message.reply_text(
            f"Максимум {MAX_HABITS} привычек. Удали ненужную, чтобы добавить новую."
        )
        return
    # Запоминаем, что следующее сообщение пользователя это название привычки
    context.user_data["adding"] = True
    await update.message.reply_text("Напиши название привычки (например: «Читать 20 минут»):")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает все обычные текстовые сообщения."""
    text = update.message.text.strip()

    # Нажатие кнопок главного меню
    if text in MENU_BUTTONS:
        context.user_data["adding"] = False  # отменяем добавление, если оно было
        if text == BTN_ADD:
            await ask_habit_name(update, context)
        elif text == BTN_LIST:
            await show_habits(update, context)
        elif text == BTN_PET:
            await show_pet(update, context)
        elif text == BTN_STATS:
            await show_stats(update, context)
        elif text == BTN_STYLE:
            await show_style(update, context)
        else:
            await help_command(update, context)
        return

    # Пользователь вводит название новой привычки
    if context.user_data.get("adding"):
        if len(text) > MAX_NAME_LENGTH:
            await update.message.reply_text(
                f"Слишком длинно (максимум {MAX_NAME_LENGTH} символов). Попробуй короче:"
            )
            return
        user = get_user(update.effective_user.id)
        if len(user["habits"]) >= MAX_HABITS:  # повторная проверка лимита
            context.user_data["adding"] = False
            await update.message.reply_text(f"Максимум {MAX_HABITS} привычек.")
            return
        user["habits"].append(
            {"id": user["next_id"], "name": text, "done_dates": []}
        )
        user["next_id"] += 1
        context.user_data["adding"] = False

        reply = style_of(user)["added"].format(habit=text)
        if len(user["habits"]) >= 5:
            badge = give_badge(user, "collector")
            if badge:
                reply += f"\n\n🏅 Новое достижение: {badge}"
        save_data()
        await update.message.reply_text(reply, reply_markup=MAIN_MENU)
        return

    # Всё остальное
    await update.message.reply_text(
        "Не понял 🤔 Выбери действие в меню или нажми /help.", reply_markup=MAIN_MENU
    )


# ---------- Inline-кнопки ----------

async def safe_edit(query, text: str, markup) -> None:
    """Редактирует сообщение. Игнорирует ошибку, если текст не изменился."""
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise


def process_completion(user: dict, habit: dict, today_str: str) -> list[str]:
    """Начисляет опыт, награды и достижения за выполненную привычку.
    Возвращает список сообщений для пользователя."""
    style = style_of(user)
    old_level = get_level(user["xp"])
    old_stage = get_stage(old_level)

    add_xp(user, XP_PER_HABIT)
    messages = [f"{random.choice(style['done'])} (+{XP_PER_HABIT} XP)"]

    badge = give_badge(user, "first_step")
    if badge:
        messages.append(f"🏅 Новое достижение: {badge}")

    # Серия дней
    streak = calc_streak(habit["done_dates"])
    if streak in MILESTONES:
        text, bonus = MILESTONES[streak]
        if give_award_once(user, f"ms:{habit['id']}:{streak}"):
            add_xp(user, bonus)
            messages.append(f"{text} (+{bonus} XP)")
    for days, key in ((7, "streak_7"), (30, "streak_30")):
        if streak >= days:
            badge = give_badge(user, key)
            if badge:
                messages.append(f"🏅 Новое достижение: {badge}")

    # Идеальный день: все привычки выполнены
    if all(today_str in h["done_dates"] for h in user["habits"]):
        if give_award_once(user, f"all:{today_str}"):
            add_xp(user, XP_ALL_DONE)
            messages.append(f"{style['all_done']} (+{XP_ALL_DONE} XP)")
        badge = give_badge(user, "perfect_day")
        if badge:
            messages.append(f"🏅 Новое достижение: {badge}")

    # Новый уровень и эволюция питомца
    new_level = get_level(user["xp"])
    if new_level > old_level:
        messages.append(f"🎊 Новый уровень: {new_level}!")
        new_stage = get_stage(new_level)
        if new_stage != old_stage:
            messages.append(f"✨ Питомец эволюционировал: {new_stage[1]} {new_stage[2]}!")
    return messages


def calculate_base_xp(user: dict) -> int:
    """Пересчитывает базовый XP из текущих выполнений привычек."""
    total = sum(len(h["done_dates"]) for h in user["habits"])
    return total * XP_PER_HABIT


def recalculate_xp(user: dict) -> None:
    """Синхронизирует XP с текущим состоянием привычек.

    Учитываются:
    - XP за каждое выполнение;
    - бонус за идеальный день;
    - бонусы за достигнутые серии.
    """
    xp = calculate_base_xp(user)

    # Бонус за идеальный день: один раз за каждый день,
    # когда были выполнены все существующие привычки.
    if user["habits"]:
        all_days = set()
        for habit in user["habits"]:
            all_days.update(habit["done_dates"])

        for day_str in all_days:
            if all(day_str in h["done_dates"] for h in user["habits"]):
                xp += XP_ALL_DONE

    # Бонусы за серии. Считаем только фактически достигнутые milestone-дни.
    for habit in user["habits"]:
        dates = set(habit["done_dates"])
        if not dates:
            continue

        # Считаем каждую непрерывную серию.
        sorted_days = sorted(date.fromisoformat(d) for d in dates)
        run = 1
        for i in range(1, len(sorted_days)):
            if sorted_days[i] == sorted_days[i - 1] + timedelta(days=1):
                run += 1
            else:
                run = 1

            if run in MILESTONES:
                xp += MILESTONES[run][1]

    user["xp"] = max(0, xp)


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()  # убирает "часики" на кнопке

    user = get_user(query.from_user.id)
    action, _, value = query.data.partition(":")
    habit = find_habit(user, value)

    # Привычку могли удалить, пока кнопка висела в чате
    if action in ("toggle", "del", "delyes") and habit is None:
        text, markup = build_habits_view(user)
        await safe_edit(query, text, markup)
        return

    if action == "toggle":
        today_str = today().isoformat()
        messages = []
        if today_str in habit["done_dates"]:
            habit["done_dates"].remove(today_str)  # отмена отметки
            # Пересчитываем XP, чтобы отмена не оставляла бонусы за
            # идеальный день или серию, которых больше нет.
            recalculate_xp(user)
        else:
            habit["done_dates"].append(today_str)
            messages = process_completion(user, habit, today_str)
        save_data()

        text, markup = build_habits_view(user)
        await safe_edit(query, text, markup)
        if messages:
            await query.message.reply_text("\n\n".join(messages))

    elif action == "del":
        # Просим подтверждение, чтобы не удалить случайно
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Да, удалить", callback_data=f"delyes:{habit['id']}"),
                    InlineKeyboardButton("Отмена", callback_data="list:"),
                ]
            ]
        )
        await safe_edit(query, f"Удалить привычку «{habit['name']}»?", keyboard)

    elif action == "delyes":
        user["habits"].remove(habit)
        save_data()
        text, markup = build_habits_view(user)
        await safe_edit(query, text, markup)

    elif action == "list":
        text, markup = build_habits_view(user)
        await safe_edit(query, text, markup)

    elif action == "style":
        if value in STYLES:
            user["style"] = value
            save_data()
            text, markup = build_style_view(user)
            await safe_edit(query, f"Готово! Стиль: {STYLES[value]['title']} ✅", markup)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Записывает любые ошибки в лог, чтобы бот не падал молча."""
    logger.error("Ошибка: %s", context.error, exc_info=context.error)


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "Не найден BOT_TOKEN. Создай файл .env и добавь строку BOT_TOKEN=твой_токен"
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    print("Бот запущен ✅")
    app.run_polling()


if __name__ == "__main__":
    main()
