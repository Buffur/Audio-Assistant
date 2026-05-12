# Файл: database/db.py

import logging
from typing import Any

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)

DB_TIMEOUT_SECONDS = 10
DB_BUSY_TIMEOUT_MS = DB_TIMEOUT_SECONDS * 1000

ALLOWED_USAGE_FIELDS = {
    "text_messages_processed",
    "files_processed",
    "ocr_processed",
    "links_processed",
    "summaries_generated",
}


def get_db_connection() -> aiosqlite.Connection:
    return aiosqlite.connect(DB_PATH, timeout=DB_TIMEOUT_SECONDS)


async def _configure_sqlite(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")


async def _column_exists(
    db: aiosqlite.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        columns = await cursor.fetchall()

    return any(column[1] == column_name for column in columns)


async def init_db() -> None:
    async with get_db_connection() as db:
        await _configure_sqlite(db)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                voice TEXT,
                rate TEXT,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_banned INTEGER DEFAULT 0,
                plan TEXT DEFAULT 'free',
                premium_until TEXT
            )
        """)

        if not await _column_exists(db, "users", "is_banned"):
            logger.info("DB migration: додаю колонку users.is_banned")
            await db.execute(
                "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0"
            )

        if not await _column_exists(db, "users", "plan"):
            logger.info("DB migration: додаю колонку users.plan")
            await db.execute(
                "ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'"
            )

        if not await _column_exists(db, "users", "premium_until"):
            logger.info("DB migration: додаю колонку users.premium_until")
            await db.execute(
                "ALTER TABLE users ADD COLUMN premium_until TEXT"
            )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS document_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_name TEXT,
                text_preview TEXT,
                text_length INTEGER NOT NULL DEFAULT 0,
                chunks_count INTEGER NOT NULL DEFAULT 0,
                chunks_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        if not await _column_exists(db, "document_history", "chunks_json"):
            logger.info("DB migration: додаю колонку document_history.chunks_json")
            await db.execute(
                "ALTER TABLE document_history ADD COLUMN chunks_json TEXT"
            )

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_history_user_created
            ON document_history (user_id, created_at DESC)
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_daily (
                user_id INTEGER NOT NULL,
                usage_date TEXT NOT NULL,
                text_messages_processed INTEGER NOT NULL DEFAULT 0,
                files_processed INTEGER NOT NULL DEFAULT 0,
                ocr_processed INTEGER NOT NULL DEFAULT 0,
                links_processed INTEGER NOT NULL DEFAULT 0,
                summaries_generated INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, usage_date)
            )
        """)

        usage_columns = {
            "text_messages_processed": "INTEGER NOT NULL DEFAULT 0",
            "files_processed": "INTEGER NOT NULL DEFAULT 0",
            "ocr_processed": "INTEGER NOT NULL DEFAULT 0",
            "links_processed": "INTEGER NOT NULL DEFAULT 0",
            "summaries_generated": "INTEGER NOT NULL DEFAULT 0",
        }

        for column_name, column_type in usage_columns.items():
            if not await _column_exists(db, "usage_daily", column_name):
                logger.info(
                    "DB migration: додаю колонку usage_daily.%s",
                    column_name,
                )
                await db.execute(
                    f"ALTER TABLE usage_daily ADD COLUMN {column_name} {column_type}"
                )

        await db.commit()

    logger.info("Базу даних ініціалізовано: %s", DB_PATH)


async def register_or_update_user(
    user_id: int,
    username: str,
    full_name: str,
) -> None:
    async with get_db_connection() as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name, last_activity)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                last_activity = CURRENT_TIMESTAMP
        """, (user_id, username, full_name))
        await db.commit()


async def get_user_settings(user_id: int) -> tuple[str | None, str | None]:
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT voice, rate FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if row:
        return row[0], row[1]

    return None, None


async def set_user_settings(
    user_id: int,
    voice: str | None = None,
    rate: str | None = None,
) -> None:
    if voice is None and rate is None:
        logger.warning(
            "set_user_settings викликано без voice/rate для user_id=%s",
            user_id,
        )
        return

    async with get_db_connection() as db:
        await db.execute(
            """
            INSERT INTO users (
                user_id,
                username,
                full_name,
                voice,
                rate,
                last_activity
            )
            VALUES (?, 'N/A', 'N/A', ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                voice = COALESCE(excluded.voice, users.voice),
                rate = COALESCE(excluded.rate, users.rate),
                last_activity = CURRENT_TIMESTAMP
            """,
            (user_id, voice, rate),
        )
        await db.commit()


async def get_all_users() -> list[int]:
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT user_id FROM users WHERE is_banned = 0"
        ) as cursor:
            rows = await cursor.fetchall()

    return [row[0] for row in rows]


async def get_all_users_detailed() -> list[dict[str, Any]]:
    async with get_db_connection() as db:
        async with db.execute("""
            SELECT user_id, username, full_name, last_activity, is_banned, plan, premium_until
            FROM users
            ORDER BY last_activity DESC
        """) as cursor:
            rows = await cursor.fetchall()

    return [
        {
            "user_id": row[0],
            "username": row[1],
            "full_name": row[2],
            "last_activity": row[3],
            "is_banned": bool(row[4]),
            "plan": row[5] or "free",
            "premium_until": row[6],
        }
        for row in rows
    ]


async def ban_user(user_id: int) -> None:
    async with get_db_connection() as db:
        await db.execute(
            """
            UPDATE users
            SET is_banned = 1, last_activity = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (user_id,),
        )
        await db.commit()

    logger.info("Користувача заблоковано: user_id=%s", user_id)


async def unban_user(user_id: int) -> None:
    async with get_db_connection() as db:
        await db.execute(
            """
            UPDATE users
            SET is_banned = 0, last_activity = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (user_id,),
        )
        await db.commit()

    logger.info("Користувача розблоковано: user_id=%s", user_id)


async def is_user_banned(user_id: int) -> bool:
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT is_banned FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    return bool(row[0]) if row else False


async def set_user_premium(
    user_id: int,
    premium_until: str | None,
) -> None:
    """
    Видає користувачу premium.

    premium_until:
    - ISO datetime string;
    - None означає premium безстроково.
    """
    async with get_db_connection() as db:
        await db.execute(
            """
            INSERT INTO users (user_id, username, full_name, plan, premium_until, last_activity)
            VALUES (?, 'N/A', 'N/A', 'premium', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                plan = 'premium',
                premium_until = excluded.premium_until,
                last_activity = CURRENT_TIMESTAMP
            """,
            (user_id, premium_until),
        )
        await db.commit()


async def revoke_user_premium(user_id: int) -> None:
    """
    Забирає premium у користувача.
    """
    async with get_db_connection() as db:
        await db.execute(
            """
            UPDATE users
            SET
                plan = 'free',
                premium_until = NULL,
                last_activity = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (user_id,),
        )
        await db.commit()


async def get_user_plan_info(user_id: int) -> dict[str, Any]:
    """
    Повертає інформацію про тариф користувача.
    """
    async with get_db_connection() as db:
        async with db.execute(
            """
            SELECT plan, premium_until
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return {
            "plan": "free",
            "premium_until": None,
        }

    return {
        "plan": row[0] or "free",
        "premium_until": row[1],
    }


async def _ensure_usage_row(
    db: aiosqlite.Connection,
    user_id: int,
    usage_date: str,
) -> None:
    await db.execute(
        """
        INSERT OR IGNORE INTO usage_daily (
            user_id,
            usage_date,
            text_messages_processed,
            files_processed,
            ocr_processed,
            links_processed,
            summaries_generated
        )
        VALUES (?, ?, 0, 0, 0, 0, 0)
        """,
        (user_id, usage_date),
    )


async def get_daily_usage(
    user_id: int,
    usage_date: str,
) -> dict[str, int]:
    async with get_db_connection() as db:
        await _ensure_usage_row(db, user_id, usage_date)
        await db.commit()

        async with db.execute(
            """
            SELECT
                text_messages_processed,
                files_processed,
                ocr_processed,
                links_processed,
                summaries_generated
            FROM usage_daily
            WHERE user_id = ? AND usage_date = ?
            """,
            (user_id, usage_date),
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return {
            "text_messages_processed": 0,
            "files_processed": 0,
            "ocr_processed": 0,
            "links_processed": 0,
            "summaries_generated": 0,
        }

    return {
        "text_messages_processed": int(row[0]),
        "files_processed": int(row[1]),
        "ocr_processed": int(row[2]),
        "links_processed": int(row[3]),
        "summaries_generated": int(row[4]),
    }


async def increment_daily_usage(
    user_id: int,
    usage_date: str,
    field_name: str,
    amount: int = 1,
) -> None:
    if field_name not in ALLOWED_USAGE_FIELDS:
        raise ValueError(f"Unsupported usage field: {field_name}")

    if amount <= 0:
        raise ValueError("Usage increment amount must be greater than 0")

    async with get_db_connection() as db:
        await _ensure_usage_row(db, user_id, usage_date)
        await db.execute(
            f"""
            UPDATE usage_daily
            SET {field_name} = {field_name} + ?
            WHERE user_id = ? AND usage_date = ?
            """,
            (amount, user_id, usage_date),
        )
        await db.commit()


async def try_increment_daily_usage_under_limit(
    user_id: int,
    usage_date: str,
    field_name: str,
    limit: int | None,
    amount: int = 1,
) -> bool:
    """
    Атомарно збільшує usage тільки якщо ліміт ще не вичерпано.

    Повертає:
    - True, якщо usage успішно збільшено;
    - False, якщо користувач уже досяг ліміту.
    """
    if field_name not in ALLOWED_USAGE_FIELDS:
        raise ValueError(f"Unsupported usage field: {field_name}")

    if amount <= 0:
        raise ValueError("Usage increment amount must be greater than 0")

    async with get_db_connection() as db:
        await db.execute("BEGIN IMMEDIATE")

        try:
            await _ensure_usage_row(db, user_id, usage_date)

            async with db.execute(
                f"""
                SELECT {field_name}
                FROM usage_daily
                WHERE user_id = ? AND usage_date = ?
                """,
                (user_id, usage_date),
            ) as cursor:
                row = await cursor.fetchone()

            current_value = int(row[0]) if row else 0

            if limit is not None and current_value + amount > limit:
                await db.rollback()
                return False

            await db.execute(
                f"""
                UPDATE usage_daily
                SET {field_name} = {field_name} + ?
                WHERE user_id = ? AND usage_date = ?
                """,
                (amount, user_id, usage_date),
            )

            await db.commit()
            return True

        except Exception:
            await db.rollback()
            raise


async def add_document_history(
    user_id: int,
    source_type: str,
    source_name: str,
    text_preview: str,
    text_length: int,
    chunks_count: int,
    chunks_json: str | None = None,
) -> int:
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            INSERT INTO document_history (
                user_id,
                source_type,
                source_name,
                text_preview,
                text_length,
                chunks_count,
                chunks_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                source_type,
                source_name,
                text_preview,
                text_length,
                chunks_count,
                chunks_json,
            ),
        )
        await db.commit()

    return int(cursor.lastrowid)


async def get_user_document_history(
    user_id: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    async with get_db_connection() as db:
        async with db.execute(
            """
            SELECT
                id,
                source_type,
                source_name,
                text_preview,
                text_length,
                chunks_count,
                created_at,
                chunks_json
            FROM document_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        {
            "id": row[0],
            "source_type": row[1],
            "source_name": row[2],
            "text_preview": row[3],
            "text_length": row[4],
            "chunks_count": row[5],
            "created_at": row[6],
            "has_chunks": bool(row[7]),
        }
        for row in rows
    ]


async def get_user_document_by_id(
    user_id: int,
    document_id: int,
) -> dict[str, Any] | None:
    async with get_db_connection() as db:
        async with db.execute(
            """
            SELECT
                id,
                source_type,
                source_name,
                text_preview,
                text_length,
                chunks_count,
                created_at,
                chunks_json
            FROM document_history
            WHERE user_id = ? AND id = ?
            """,
            (user_id, document_id),
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "source_type": row[1],
        "source_name": row[2],
        "text_preview": row[3],
        "text_length": row[4],
        "chunks_count": row[5],
        "created_at": row[6],
        "chunks_json": row[7],
    }


async def delete_user_document(
    user_id: int,
    document_id: int,
) -> None:
    async with get_db_connection() as db:
        await db.execute(
            """
            DELETE FROM document_history
            WHERE user_id = ? AND id = ?
            """,
            (user_id, document_id),
        )
        await db.commit()


async def clear_user_document_history(user_id: int) -> None:
    async with get_db_connection() as db:
        await db.execute(
            "DELETE FROM document_history WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()