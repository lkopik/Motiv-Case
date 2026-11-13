import os
import aiomysql
import hashlib

# Единый конфиг для пула (берем из переменных окружения, если есть)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "db"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "motivchik_qwe"),
    "db": os.getenv("DB_NAME", "logs_of_db"),
    "charset": "utf8mb4",
    "autocommit": True,
    "cursorclass": aiomysql.DictCursor
}

pool = None


async def init_db_pool():
    global pool
    pool = await aiomysql.create_pool(**DB_CONFIG, minsize=1, maxsize=10)


async def close_db_pool():
    if pool:
        pool.close()
        await pool.wait_closed()


# Проверка статуса (для деплоя)
async def health():
    if not pool: return {"database": "error: pool not initialized"}
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM ALARMS")
                (alarms,) = await cur.fetchone()
        return {"database": "ok", "alarms": alarms}
    except Exception as e:
        return {"database": f"error: {e}"}


# Хэширование пароля для проверки
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def get_user_by_username(username: str):
    if not pool: raise RuntimeError("Пул соединений не инициализирован")
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT * FROM USERS WHERE USERNAME=%s", (username,))
            return await cursor.fetchone()


async def get_alarms(start_date: str = None, end_date: str = None):
    if not pool: raise RuntimeError("Пул соединений не инициализирован")
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            query = "SELECT * FROM ALARMS WHERE 1=1"
            params = []

            if start_date:
                query += " AND BEGIN_TIME >= %s"
                params.append(start_date)
            if end_date:
                query += " AND BEGIN_TIME <= %s"
                params.append(end_date)

            query += " ORDER BY BEGIN_TIME DESC LIMIT 1000;"
            await cursor.execute(query, tuple(params))
            alarms = await cursor.fetchall()

            # Преобразование дат и времени для JSON
            for alarm in alarms:
                if alarm.get("END_TIME") and alarm["END_TIME"].year == 1:
                    alarm["END_TIME"] = None
                elif alarm.get("END_TIME"):
                    alarm["END_TIME"] = alarm["END_TIME"].strftime("%Y-%m-%d %H:%M:%S")

                if alarm.get("BEGIN_TIME"):
                    alarm["BEGIN_TIME"] = alarm["BEGIN_TIME"].strftime("%Y-%m-%d %H:%M:%S")

                for time_field in ["AKB", "DGU", "PROSTOY", "COMMON_PROSTOY"]:
                    if alarm.get(time_field):
                        alarm[time_field] = str(alarm[time_field])
            return alarms


async def create_alarm(data: dict):
    if not pool: raise RuntimeError("Пул соединений не инициализирован")
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            fields = [k for k in data.keys() if k != 'ID']
            placeholders = ", ".join(["%s"] * len(fields))
            columns = ", ".join(fields)
            values = tuple(data[k] for k in fields)

            query = f"INSERT INTO ALARMS ({columns}) VALUES ({placeholders})"
            await cursor.execute(query, values)
            return {"status": "ok", "id": cursor.lastrowid}


async def update_alarm(alarm_id: int, data: dict):
    if not pool: raise RuntimeError("Пул соединений не инициализирован")
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            fields = [f"{k}=%s" for k in data.keys() if k != 'ID']
            values = [data[k] for k in data.keys() if k != 'ID']
            values.append(alarm_id)

            query = f"UPDATE ALARMS SET {', '.join(fields)} WHERE ID=%s"
            await cursor.execute(query, tuple(values))
            return {"status": "ok", "message": "Авария обновлена"}