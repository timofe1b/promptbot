import json
import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

# Критерии хорошего промпта. Это единственное место, где они описаны:
# по ним работают и кнопка «Правила», и анализ, и редактирование.
# После исследования их можно поправить здесь, и бот изменится целиком.
CRITERIA = [
    ("task", "Задача", "что именно нужно сделать"),
    ("context", "Контекст", "зачем это нужно и что уже известно"),
    ("role", "Роль", "кем должна быть нейросеть (учитель, редактор, аналитик)"),
    ("audience", "Аудитория и тон", "для кого текст и в каком стиле"),
    ("format", "Формат", "как оформить ответ: объём, структура, список или абзацы"),
    ("limits", "Ограничения", "чего избегать, что обязательно учесть"),
]


class AIError(Exception):
    """Нейросеть не ответила или ответила не так, как ожидалось."""


def _ask(system: str, user: str, json_mode: bool = False, max_tokens: int = 1000) -> str:
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        temperature=0.3,
        response_mime_type="application/json" if json_mode else None,
    )
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL, contents=user, config=config
            )
            if response.text:
                return response.text.strip()
            raise AIError("Пустой ответ от модели")
        except AIError:
            raise
        except Exception as e:
            temporary = "503" in str(e) or "429" in str(e)
            if temporary and attempt < 2:
                time.sleep((attempt + 1) * 2)
                continue
            raise AIError(str(e)) from e
    raise AIError("Не удалось получить ответ")


def analyze_prompt(user_prompt: str) -> str:
    """Короткий разбор по критериям и оценка. Промпт не переписывает."""
    keys = [k for k, _, _ in CRITERIA]
    criteria_text = "\n".join(f"- {k}: {name} ({hint})" for k, name, hint in CRITERIA)
    example = {k: {"ok": True, "note": "..."} for k in keys}

    system = (
        "Ты проверяешь промпты, которые люди пишут нейросетям. "
        "Для каждого критерия определи, есть ли он в промпте.\n\n"
        f"Критерии:\n{criteria_text}\n\n"
        "Верни ТОЛЬКО JSON такого вида:\n"
        + json.dumps({"criteria": example, "tip": "..."}, ensure_ascii=False)
        + "\n\n"
        "ok — true, если критерий явно есть в промпте, иначе false. "
        "note — до 8 слов: что именно стоит добавить (для ok=true оставь пустую строку). "
        "tip — один главный совет в одном-двух предложениях. "
        "Не переписывай промпт и не добавляй ничего, кроме JSON."
    )
    raw = _ask(system, f"Промпт пользователя:\n{user_prompt}", json_mode=True)

    try:
        data = json.loads(raw)
        results = data["criteria"]
        tip = data.get("tip", "").strip()
        present = [name for k, name, _ in CRITERIA if results[k]["ok"]]
        missing = [(name, results[k].get("note", "").strip())
                   for k, name, _ in CRITERIA if not results[k]["ok"]]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise AIError(f"Ответ модели не удалось разобрать: {e}") from e

    lines = [f"Оценка: {len(present)}/{len(CRITERIA)}", ""]
    if present:
        lines.append("✅ Есть: " + ", ".join(present))
    if missing:
        lines.append("❌ Не хватает:")
        for name, note in missing:
            lines.append(f"• {name}" + (f" — {note}" if note else ""))
    if tip:
        lines += ["", f"💡 Главное: {tip}"]
    return "\n".join(lines)


def improve_prompt(user_prompt: str) -> str:
    """Возвращает только улучшенный промпт, без пояснений."""
    criteria_text = "\n".join(f"- {name}: {hint}" for _, name, hint in CRITERIA)
    system = (
        "Ты переписываешь промпты для нейросетей так, чтобы они были точными и полными.\n\n"
        f"В хорошем промпте есть:\n{criteria_text}\n\n"
        "Правила:\n"
        "1. Верни ТОЛЬКО текст улучшенного промпта: без вступления, пояснений и markdown-разметки.\n"
        "2. Сохрани тему и язык исходного промпта.\n"
        "3. Не выдумывай факты о пользователе. Если нужных данных нет, "
        "оставь пометку в квадратных скобках, например [класс], [объём], [для кого].\n"
        "4. Без лишней воды: промпт должен быть таким длинным, каким нужно, и не длиннее."
    )
    return _ask(system, f"Исходный промпт:\n{user_prompt}", max_tokens=800)