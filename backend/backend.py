import os

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

async def db_health():
    """Проверка, что бэкенд жив и видит базу."""
async def health():
    try:
        conn = await aiomysql.connect(**DB_CONFIG)
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM ALARMS")
            (alarms,) = await cur.fetchone()
        conn.close()
        return {"database": "ok", "alarms": alarms}
    except Exception as e:
        return {"database": f"error: {e}"}