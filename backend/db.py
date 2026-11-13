"""Подключение к MariaDB: общий пул соединений и короткие помощники для запросов."""
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import aiomysql

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "db"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "motivchik_qwe"),
    "db": os.getenv("DB_NAME", "logs_of_db"),
    "charset": "utf8mb4",
    "autocommit": True,
}

_pool: aiomysql.Pool | None = None


async def pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(minsize=1, maxsize=10, **DB_CONFIG)
    return _pool


async def close() -> None:
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()


def fmt_time(td: timedelta | None) -> str | None:
    """TIME из MariaDB приходит как timedelta → «чч:мм:сс» (часы могут быть больше 24)."""
    if td is None:
        return None
    total = int(td.total_seconds())
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _clean(value):
    if isinstance(value, timedelta):
        return fmt_time(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str) and value.startswith("0000-00-00"):
        return None   # нулевая дата — «НВ»
    return value


async def fetch_all(sql: str, params=()) -> list[dict]:
    async with (await pool()).acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
    return [{k: _clean(v) for k, v in row.items()} for row in rows]


async def fetch_one(sql: str, params=()) -> dict | None:
    rows = await fetch_all(sql, params)
    return rows[0] if rows else None


async def execute(sql: str, params=()) -> int:
    """Выполняет INSERT/UPDATE/DELETE. Возвращает id новой строки или число затронутых."""
    async with (await pool()).acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return cur.lastrowid or cur.rowcount
