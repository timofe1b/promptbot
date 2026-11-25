
import os

import telebot
from dotenv import load_dotenv
from telebot import types
from telebot.types import BotCommand

import database
print("Загружен database:", database.__file__)
print("Есть init_db:", hasattr(database, "init_db"))
from ai_helper import (
    CRITERIA,
    AIError,
    analyze_prompt_data,
    format_analysis,
    improve_prompt,
)

load_dotenv()

bot = telebot.TeleBot(os.environ["TELEGRAM_TOKEN"])

BTN_RULES = "📖 Правила промпта"
BTN_ANALYZE = "🔍 Анализ промпта"
BTN_EDIT = "✏️ Редактирование промпта"

MAX_LEN = 1500

WELCOME_TEXT = (
    "Я помогаю писать запросы к нейросетям.\n\n"
    f"{BTN_RULES} — памятка с правилами промпта.\n\n"
    f"{BTN_ANALYZE} — проанализирую и оценю твой запрос.\n\n"
    f"{BTN_EDIT} — пришли запрос, и я верну его улучшенную версию.\n\n"
    "Выбери кнопку в меню 👇"
)

HELP_TEXT = (
    "🤖 <b>Возможности бота</b>\n\n"
    "Бот помогает анализировать и улучшать запросы к нейросетям.\n\n"

    "<b>Доступные кнопки:</b>\n"
    f"{BTN_RULES} — памятка с правилами составления промптов.\n"
    f"{BTN_ANALYZE} — оценка запроса по шести критериям "
    "и рекомендации по его улучшению.\n"
    f"{BTN_EDIT} — создание улучшенной версии твоего запроса.\n\n"

    "<b>Команды:</b>\n"
    "/start — запуск бота и отображение главного меню.\n"
    "/help — показать эту справку.\n"
    "/consent — ознакомиться с условиями участия в исследовании.\n"
    "/withdraw — отозвать согласие и удалить исследовательские данные.\n\n"

    "<b>Как пользоваться ботом?</b>\n"
    "1. Выбери нужный режим с помощью кнопок.\n"
    "2. Отправь свой запрос обычным текстовым сообщением.\n"
    "3. Получи анализ или улучшенную версию промпта.\n\n"

    "Участие в исследовании добровольное. "
    "Бот продолжает работать и без согласия на сбор данных."
)

user_mode: dict[int, str] = {}

# Если БД недоступна, бот продолжает работать без сбора данных.
db_ready = False


def main_menu():
    keyboard = types.ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=1,
        input_field_placeholder="Выбери действие или пришли промпт",
    )
    keyboard.add(
        types.KeyboardButton(BTN_RULES),
        types.KeyboardButton(BTN_ANALYZE),
        types.KeyboardButton(BTN_EDIT),
    )
    return keyboard


def setup_bot_commands():
    commands = [
        types.BotCommand("start", "Запустить бота"),
        types.BotCommand("help", "Помощь и список возможностей"),
        types.BotCommand("consent", "Условия участия в исследовании"),
        types.BotCommand("withdraw", "Отозвать согласие и удалить данные"),
    ]

    try:
        bot.set_my_commands(commands)
        print("Меню команд Telegram настроено.", flush=True)
    except Exception as e:
        print(f"Не удалось настроить меню команд: {e}", flush=True)


def consent_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "✅ Согласен(на)",
            callback_data="consent_yes",
        ),
        types.InlineKeyboardButton(
            "❌ Не согласен(на)",
            callback_data="consent_no",
        ),
    )
    return keyboard


def show_consent_prompt(chat_id: int):
    if not db_ready:
        return

    status = database.get_research_status()

    if not status["active"]:
        bot.send_message(
            chat_id,
            "Срок сбора исследовательских данных завершён. "
            "Бот продолжает работать в обычном режиме.",
        )
        return

    deadline = status["deadline"].strftime("%d.%m.%Y")

    text = (
        "🔬 <b>Участие в исследовании</b>\n\n"
        "Я провожу исследование о том, как пользователи формулируют "
        "запросы к нейросетям и как меняется их качество после улучшения.\n\n"
        "Участие добровольное. Если ты согласишься, будут сохраняться:\n"
        "• отправленные тобой промпты;\n"
        "• ответы бота на эти промпты;\n"
        "• оценки по шести критериям при анализе;\n"
        "• дата и режим взаимодействия.\n\n"
        "Доступ к данным имеет автор исследования. "
        "Для обработки промптов используется Google Gemini: "
        "отправленные запросы передаются этому сервису. "
        "Данные хранятся до конца исследования, после чего удаляются.\n\n"
        "Не отправляй боту пароли, личные документы и другие "
        "конфиденциальные сведения.\n\n"
        "Ты можешь отозвать согласие в любой момент командой /withdraw. "
        "После отказа или отзыва согласия бот продолжит работать, "
        "но новые взаимодействия сохраняться не будут.\n\n"
        "Согласен(на) ли ты участвовать?"
    )

    bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=consent_keyboard(),
    )


def rules_text() -> str:
    lines = ["<b>Хороший промпт отвечает на шесть вопросов:</b>", ""]

    for i, (_, name, hint) in enumerate(CRITERIA, 1):
        lines.append(f"{i}. <b>{name}</b> — {hint}")

    lines += [
        "",
        "<b>Пример</b>",
        "❌ «Напиши сочинение про зиму»",
        "",
        "✅ «Ты — учитель литературы. Напиши сочинение-описание "
        "«Зима в городе» для 8 класса, 150–200 слов, живым языком, "
        "без штампов вроде «белое одеяло». Формат: три абзаца.»",
    ]

    return "\n".join(lines)


@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_mode.pop(message.chat.id, None)

    bot.send_message(
        message.chat.id,
        WELCOME_TEXT,
        reply_markup=main_menu(),
    )

    if db_ready:
        try:
            if not database.has_consent(message.from_user.id):
                show_consent_prompt(message.chat.id)
        except Exception as e:
            print(f"Ошибка проверки согласия: {e}", flush=True)


@bot.message_handler(commands=["help"])
def send_help(message):
    bot.send_message(
        message.chat.id,
        HELP_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@bot.message_handler(commands=["consent"])
def request_consent(message):
    if not db_ready:
        bot.send_message(
            message.chat.id,
            "Сейчас база данных недоступна. Попробуй позже.",
        )
        return

    try:
        if database.has_consent(message.from_user.id):
            bot.send_message(
                message.chat.id,
                "Твоё согласие уже действует. "
                "Для его отзыва используй /withdraw.",
            )
        else:
            show_consent_prompt(message.chat.id)
    except Exception as e:
        print(f"Ошибка получения согласия: {e}", flush=True)
        bot.send_message(
            message.chat.id,
            "Не удалось получить информацию. Попробуй позже.",
        )


@bot.callback_query_handler(
    func=lambda call: call.data in ("consent_yes", "consent_no")
)
def handle_consent(call):
    if call.data == "consent_no":
        bot.answer_callback_query(call.id, "Отказ принят.")

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
        )

        bot.send_message(
            call.message.chat.id,
            "Ты отказался(ась) от участия. Бот продолжает работать, "
            "но твои взаимодействия не сохраняются.",
        )
        return

    try:
        if not db_ready:
            raise RuntimeError("База данных недоступна")

        accepted = database.give_consent(call.from_user.id)

        bot.answer_callback_query(call.id)

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None,
        )

        if accepted:
            bot.send_message(
                call.message.chat.id,
                "✅ Спасибо! Согласие зарегистрировано. "
                "Теперь взаимодействия будут сохраняться для исследования.",
            )
        else:
            bot.send_message(
                call.message.chat.id,
                "Срок сбора исследовательских данных завершён. "
                "Бот продолжает работать без сохранения взаимодействий.",
            )

    except Exception as e:
        print(f"Ошибка регистрации согласия: {e}", flush=True)
        bot.answer_callback_query(
            call.id,
            "Не удалось сохранить согласие.",
            show_alert=True,
        )


@bot.message_handler(commands=["withdraw"])
def withdraw_consent(message):
    user_mode.pop(message.chat.id, None)

    if not db_ready:
        bot.send_message(
            message.chat.id,
            "База данных сейчас недоступна. "
            "Не удалось подтвердить удаление данных. Попробуй позже.",
        )
        return

    try:
        deleted = database.delete_participant(message.from_user.id)

        if deleted:
            bot.send_message(
                message.chat.id,
                "✅ Согласие отозвано. Все сохранённые исследовательские "
                "данные, связанные с твоим участником, удалены. "
                "Бот продолжает работать без сбора данных.",
            )
        else:
            bot.send_message(
                message.chat.id,
                "В базе нет сохранённых исследовательских данных, "
                "связанных с твоим аккаунтом. Бот продолжает работать.",
            )

    except Exception as e:
        print(f"Ошибка удаления данных: {e}", flush=True)
        bot.send_message(
            message.chat.id,
            "Не удалось удалить данные из базы. "
            "Попробуй выполнить /withdraw позднее.",
        )


@bot.message_handler(func=lambda m: m.text == BTN_RULES)
def show_rules(message):
    user_mode.pop(message.chat.id, None)
    bot.send_message(
        message.chat.id,
        rules_text(),
        parse_mode="HTML",
    )


@bot.message_handler(func=lambda m: m.text == BTN_ANALYZE)
def start_analyze(message):
    user_mode[message.chat.id] = "analyze"
    bot.send_message(
        message.chat.id,
        "🔍 Пришли промпт, я оценю его по критериям.",
    )


@bot.message_handler(func=lambda m: m.text == BTN_EDIT)
def start_edit(message):
    user_mode[message.chat.id] = "edit"
    bot.send_message(
        message.chat.id,
        "✏️ Пришли промпт, я перепишу его.",
    )


@bot.message_handler(content_types=["text"])
def handle_prompt(message):
    mode = user_mode.get(message.chat.id)

    if mode is None:
        bot.send_message(
            message.chat.id,
            "Выбери действие в меню 👇",
            reply_markup=main_menu(),
        )
        return

    text = message.text.strip()

    if not any(char.isalnum() for char in text):
        bot.send_message(
            message.chat.id,
            "Похоже, в сообщении нет текста. Пришли полноценный промпт.",
        )
        return

    if len(text) > MAX_LEN:
        bot.send_message(
            message.chat.id,
            f"Промпт длиннее {MAX_LEN} символов, попробуй сократить.",
        )
        return

    wait = bot.send_message(message.chat.id, "⏳ Думаю...")

    analysis_data = None

    try:
        if mode == "analyze":
            analysis_data = analyze_prompt_data(text)
            result = format_analysis(analysis_data)
        else:
            result = "✏️ Улучшенный промпт:\n\n" + improve_prompt(text)

    except AIError as e:
        print(f"Ошибка ИИ: {e}", flush=True)
        result = (
            "Не получилось получить ответ от нейросети. "
            "Попробуй ещё раз через минуту."
        )

    else:
        # Сохраняем только успешные взаимодействия и только при согласии.
        if db_ready:
            try:
                database.save_interaction(
                    telegram_id=message.from_user.id,
                    mode=mode,
                    user_prompt=text,
                    bot_response=result,
                    analysis_data=analysis_data,
                )
            except Exception as e:
                # Ошибка БД не должна мешать работе бота.
                print(f"Ошибка сохранения взаимодействия: {e}", flush=True)

    bot.edit_message_text(
        result,
        message.chat.id,
        wait.message_id,
    )


@bot.message_handler(
    content_types=[
        "photo",
        "sticker",
        "animation",
        "voice",
        "document",
        "video",
    ]
)
def handle_other(message):
    bot.send_message(
        message.chat.id,
        "Я понимаю только текст. Пришли промпт сообщением.",
    )


if __name__ == "__main__":
    try:
        database.init_db()
        db_ready = True
        print("PostgreSQL: подключение успешно, таблицы проверены.", flush=True)
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}", flush=True)
        print("Бот запустится без сбора исследовательских данных.", flush=True)

    setup_bot_commands()

    bot.infinity_polling()