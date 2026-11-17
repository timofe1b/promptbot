import os

import psycopg
import telebot
from dotenv import load_dotenv
from telebot import types

from ai_helper import CRITERIA, AIError, analyze_prompt, improve_prompt

load_dotenv()

bot = telebot.TeleBot(os.environ["TELEGRAM_TOKEN"])

def check_database():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        print("ОШИБКА: переменная DATABASE_URL не найдена.")
        return

    try:
        with psycopg.connect(database_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user")
                db_name, db_user = cur.fetchone()

        print(f"БАЗА ДАННЫХ ПОДКЛЮЧЕНА: {db_name}, пользователь: {db_user}")

    except Exception as e:
        print(f"ОШИБКА ПОДКЛЮЧЕНИЯ К БД: {type(e).__name__}: {e}")
        
BTN_RULES = "📖 Правила промпта"
BTN_ANALYZE = "🔍 Анализ промпта"
BTN_EDIT = "✏️ Редактирование промпта"

MAX_LEN = 1500  # максимум символов в присланном промпте

# Одно и то же сообщение показывается и в /start, и в /help
WELCOME_TEXT = (
    "Я помогаю писать запросы к нейросетям.\n\n"
    f"{BTN_RULES} — из каких шести частей состоит хороший запрос, плюс пример.\n\n"
    f"{BTN_ANALYZE} — пришли свой запрос: я оценю его по шкале от 0 до 6 "
    "и подскажу, чего не хватает. Переписывать не буду.\n\n"
    f"{BTN_EDIT} — пришли запрос: я верну его улучшенную версию, "
    "которую можно сразу копировать.\n\n"
    "Выбери кнопку в меню 👇"
)

# В каком режиме сейчас каждый чат: "analyze" или "edit".
# Режим держится, пока пользователь не нажмёт другую кнопку,
# так что промпты можно присылать подряд.
user_mode: dict[int, str] = {}


def main_menu():
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=1,  # одна кнопка в строке
        input_field_placeholder="Выбери действие или пришли промпт",
    )
    keyboard.add(
        types.KeyboardButton(BTN_RULES),
        types.KeyboardButton(BTN_ANALYZE),
        types.KeyboardButton(BTN_EDIT),
    )
    return keyboard


def rules_text() -> str:
    lines = ["<b>Хороший промпт отвечает на шесть вопросов:</b>", ""]
    for i, (_, name, hint) in enumerate(CRITERIA, 1):
        lines.append(f"{i}. <b>{name}</b> — {hint}")
    lines += [
        "",
        "<b>Пример</b>",
        "❌ «Напиши сочинение про зиму»",
        "",
        "✅ «Ты — учитель литературы. Напиши сочинение-описание «Зима в городе» "
        "для 8 класса, 150–200 слов, живым языком, без штампов вроде «белое одеяло». "
        "Формат: три абзаца.»",
    ]
    return "\n".join(lines)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    user_mode.pop(message.chat.id, None)
    bot.send_message(message.chat.id, WELCOME_TEXT, reply_markup=main_menu())


@bot.message_handler(func=lambda m: m.text == BTN_RULES)
def show_rules(message):
    user_mode.pop(message.chat.id, None)
    bot.send_message(message.chat.id, rules_text(), parse_mode="HTML")


@bot.message_handler(func=lambda m: m.text == BTN_ANALYZE)
def start_analyze(message):
    user_mode[message.chat.id] = "analyze"
    bot.send_message(message.chat.id, "🔍 Пришли промпт, я оценю его по критериям.")


@bot.message_handler(func=lambda m: m.text == BTN_EDIT)
def start_edit(message):
    user_mode[message.chat.id] = "edit"
    bot.send_message(message.chat.id, "✏️ Пришли промпт, я перепишу его.")


@bot.message_handler(content_types=["text"])
def handle_prompt(message):
    mode = user_mode.get(message.chat.id)
    if mode is None:
        bot.send_message(message.chat.id, "Выбери действие в меню 👇", reply_markup=main_menu())
        return

    text = message.text.strip()
    if len(text) > MAX_LEN:
        bot.send_message(message.chat.id, f"Промпт длиннее {MAX_LEN} символов, попробуй сократить.")
        return

    wait = bot.send_message(message.chat.id, "⏳ Думаю...")
    try:
        if mode == "analyze":
            result = analyze_prompt(text)
        else:
            result = "✏️ Улучшенный промпт:\n\n" + improve_prompt(text)
    except AIError as e:
        print(f"Ошибка ИИ: {e}", flush=True)
        result = "Не получилось получить ответ от нейросети. Попробуй ещё раз через минуту."

    bot.edit_message_text(result, message.chat.id, wait.message_id)


@bot.message_handler(content_types=["photo", "sticker", "voice", "document", "video"])
def handle_other(message):
    bot.send_message(message.chat.id, "Я понимаю только текст. Пришли промпт сообщением.")


if __name__ == "__main__":
    check_database()
    bot.infinity_polling()
