"""Веб-отчётность по авариям сети. Точка входа FastAPI — сюда добавляются эндпоинты /api/..."""
import os

import aiomysql
from fastapi import FastAPI

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "db"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "motivchik_qwe"),
    "db": os.getenv("DB_NAME", "logs_of_db"),
    "charset": "utf8mb4",
    "autocommit": True,
}

app = FastAPI(title="Веб-отчётность", version="0.1.0")


@app.get("/api/health")
async def health():
    """Проверка, что бэкенд жив и видит базу."""
    try:
        conn = await aiomysql.connect(**DB_CONFIG)
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM ALARMS")
            (alarms,) = await cur.fetchone()
        conn.close()
        return {"api": "ok", "database": "ok", "alarms": alarms}
    except Exception as e:
        return {"api": "ok", "database": f"error: {e}"}
