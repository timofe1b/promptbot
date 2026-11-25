
import os
import uuid

import psycopg
from psycopg.types.json import Jsonb


def _connect():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("Переменная DATABASE_URL не задана")

    return psycopg.connect(database_url)


def _research_is_active(cursor):
    """Проверяет срок исследования и удаляет данные после его окончания."""

    cursor.execute("""
        SELECT NOW() < research_started_at + INTERVAL '12 months'
        FROM research_meta
        WHERE id = 1
    """)

    row = cursor.fetchone()
    active = bool(row and row[0])

    if not active:
        cursor.execute("DELETE FROM participants")

    return active


def init_db():
    """Создаёт таблицы и фиксирует дату начала исследования."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS research_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    research_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                INSERT INTO research_meta (id)
                VALUES (1)
                ON CONFLICT (id) DO NOTHING
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS participants (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    telegram_id BIGINT NOT NULL UNIQUE,
                    research_code UUID NOT NULL UNIQUE,
                    consent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    participant_id BIGINT NOT NULL
                        REFERENCES participants(id) ON DELETE CASCADE,
                    mode TEXT NOT NULL CHECK (mode IN ('analyze', 'edit')),
                    user_prompt TEXT NOT NULL,
                    bot_response TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS analysis_results (
                    interaction_id BIGINT PRIMARY KEY
                        REFERENCES interactions(id) ON DELETE CASCADE,
                    score NUMERIC(4, 1) NOT NULL,
                    criteria JSONB NOT NULL,
                    recommendations JSONB NOT NULL
                )
            """)

            _research_is_active(cur)


def get_research_status():
    """Возвращает дату начала, дату окончания и статус исследования."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    research_started_at,
                    research_started_at + INTERVAL '12 months',
                    NOW() < research_started_at + INTERVAL '12 months'
                FROM research_meta
                WHERE id = 1
            """)

            row = cur.fetchone()

            if row is None:
                raise RuntimeError("Не найдены настройки исследования")

            started_at, deadline, active = row

            if not active:
                cur.execute("DELETE FROM participants")

            return {
                "started_at": started_at,
                "deadline": deadline,
                "active": bool(active),
            }


def has_consent(telegram_id: int) -> bool:
    with _connect() as conn:
        with conn.cursor() as cur:
            if not _research_is_active(cur):
                return False

            cur.execute("""
                SELECT 1
                FROM participants
                WHERE telegram_id = %s
                  AND consent_given = TRUE
            """, (telegram_id,))

            return cur.fetchone() is not None


def give_consent(telegram_id: int):
    with _connect() as conn:
        with conn.cursor() as cur:
            if not _research_is_active(cur):
                return False

            cur.execute("""
                INSERT INTO participants (
                    telegram_id,
                    research_code,
                    consent_given,
                    consent_date
                )
                VALUES (%s, %s, TRUE, NOW())
                ON CONFLICT (telegram_id)
                DO UPDATE SET
                    consent_given = TRUE,
                    consent_date = NOW()
                RETURNING id
            """, (telegram_id, uuid.uuid4()))

            return cur.fetchone() is not None


def save_interaction(
    telegram_id: int,
    mode: str,
    user_prompt: str,
    bot_response: str,
    analysis_data: dict | None = None,
):
    """Сохраняет взаимодействие только при действующем согласии."""

    with _connect() as conn:
        with conn.cursor() as cur:
            if not _research_is_active(cur):
                return False

            cur.execute(
                "SELECT id FROM participants WHERE telegram_id = %s",
                (telegram_id,),
            )

            participant = cur.fetchone()

            if participant is None:
                return False

            participant_id = participant[0]

            cur.execute("""
                INSERT INTO interactions (
                    participant_id,
                    mode,
                    user_prompt,
                    bot_response
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (participant_id, mode, user_prompt, bot_response))

            interaction_id = cur.fetchone()[0]

            if mode == "analyze" and analysis_data is not None:
                cur.execute("""
                    INSERT INTO analysis_results (
                        interaction_id,
                        score,
                        criteria,
                        recommendations
                    )
                    VALUES (%s, %s, %s, %s)
                """, (
                    interaction_id,
                    analysis_data["score"],
                    Jsonb(analysis_data["criteria"]),
                    Jsonb(analysis_data["recommendations"]),
                ))

            return True


def delete_participant(telegram_id: int) -> bool:
    """Удаляет участника и все его данные через каскадное удаление."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM participants WHERE telegram_id = %s",
                (telegram_id,),
            )

            return cur.rowcount > 0
