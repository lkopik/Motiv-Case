import os
import aiomysql
import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal

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

# пул создаётся при старте (main.py)
pool = None


async def init_pool():
    global pool
    if pool is None:
        pool = await aiomysql.create_pool(minsize=1, maxsize=5, **DB_CONFIG)


async def db_health():
    """Проверка, что бэкенд жив и видит базу."""
    return await health()


async def health():
    if not pool: return {"database": "error: pool not initialized"}
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) AS alarms FROM ALARMS")
                alarms = (await cur.fetchone())["alarms"]
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


# ---------------- запросы для сайта ----------------

NV = "0000-00-00 00:00:00"  # НВ = авария не закрыта
TIME_MAX = 3020399  # 838:59:59, больше в TIME не влезет

COLS = ["PW", "NAPR", "TEHC", "KATEG", "NETW_TYPE", "SERV_ELEM", "NUMB_RBS", "EQIP_TYPE", "ALARM_TYPE",
        "DESCR", "BEGIN_TIME", "END_TIME", "AKB", "DGU", "LENGHT", "PROSTOY", "COMMON_PROSTOY",
        "ALARM_WHO", "DESC_NOTICE"]

# у открытой аварии длительность считаем на лету
SELECT = f"""SELECT ID, {', '.join(c for c in COLS if c != 'LENGHT')},
    IF(END_TIME = '{NV}', TIME_FORMAT(SEC_TO_TIME(LEAST(TIMESTAMPDIFF(SECOND, BEGIN_TIME, NOW()), {TIME_MAX})), '%%H:%%i:%%s'), LENGHT) AS LENGHT,
    END_TIME = '{NV}' AS IS_OPEN, CREATED_BY, CREATED_AT, UPDATED_BY, UPDATED_AT
    FROM ALARMS"""

# поля 15 и 17 считаем сами
RECALC = f"""UPDATE ALARMS SET
    LENGHT = TIME_FORMAT(SEC_TO_TIME(LEAST(TIMESTAMPDIFF(SECOND, BEGIN_TIME, IF(END_TIME = '{NV}', NOW(), END_TIME)), {TIME_MAX})), '%%H:%%i:%%s'),
    COMMON_PROSTOY = SEC_TO_TIME(LEAST(TIME_TO_SEC(PROSTOY) * GREATEST(NUMB_RBS, 1), {TIME_MAX}))
    WHERE ID = %s"""


def to_json(v):
    if isinstance(v, timedelta):  # TIME -> чч:мм:сс
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str) and v.startswith("0000-00-00"):
        return None
    return v


async def query(sql, params=()):
    await init_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
    return [{k: to_json(v) for k, v in r.items()} for r in rows]


async def query_one(sql, params=()):
    rows = await query(sql, params)
    return rows[0] if rows else None


async def run(sql, params=()):
    await init_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return cur.lastrowid or cur.rowcount


async def check_user(username, password):
    return await query_one("SELECT USERNAME, ROLE, FULL_NAME FROM USERS WHERE USERNAME = %s AND PASSWORD_HASH = %s",
                           (username, hash_password(password)))


# справочники
async def get_dicts():
    res = {"napr": [], "tehc": [], "kateg": [], "netw_type": [], "alarm_type": []}
    for r in await query("SELECT KIND, VALUE FROM DICTS ORDER BY KIND, SORT, VALUE"):
        res.setdefault(r["KIND"], []).append(r["VALUE"])
    return res


async def get_dict_rows():
    rows = await query("SELECT ID, KIND, VALUE, SORT FROM DICTS ORDER BY KIND, SORT, VALUE")
    used = {}
    for col, kind in [("NAPR", "napr"), ("TEHC", "tehc"), ("NETW_TYPE", "netw_type"),
                      ("ALARM_TYPE", "alarm_type"), ("KATEG", "kateg")]:
        for u in await query(f"SELECT {col} AS V, COUNT(*) AS C FROM ALARMS GROUP BY {col}"):
            used[(kind, str(u["V"]))] = u["C"]
    for r in rows:
        r["USED"] = used.get((r["KIND"], r["VALUE"]), 0)
    return rows


async def add_dict(kind, value):
    if await query_one("SELECT ID FROM DICTS WHERE KIND = %s AND VALUE = %s", (kind, value)):
        return None
    s = await query_one("SELECT COALESCE(MAX(SORT), 0) + 1 AS S FROM DICTS WHERE KIND = %s", (kind,))
    return await run("INSERT INTO DICTS (KIND, VALUE, SORT) VALUES (%s, %s, %s)", (kind, value, s["S"]))


async def delete_dict(dict_id):
    return await run("DELETE FROM DICTS WHERE ID = %s", (dict_id,))


# аварии
def make_filter(f):
    where, params = [], []
    if f.get("date_from"):
        # открытые аварии из прошлого тоже попадают в период
        where.append(f"(BEGIN_TIME >= %s OR END_TIME = '{NV}' OR END_TIME >= %s)")
        params += [f"{f['date_from']} 00:00:00"] * 2
    if f.get("date_to"):
        where.append("BEGIN_TIME <= %s")
        params.append(f"{f['date_to']} 23:59:59")
    if f.get("only_open"):
        where.append(f"END_TIME = '{NV}'")
    for col, key in [("NAPR", "napr"), ("TEHC", "tehc"), ("ALARM_TYPE", "alarm_type")]:
        if f.get(key):
            where.append(f"{col} = %s")
            params.append(f[key])
    if f.get("q"):
        where.append("CONCAT_WS(' ', PW, SERV_ELEM, EQIP_TYPE, DESCR, DESC_NOTICE, ALARM_WHO) LIKE %s")
        params.append(f"%{f['q']}%")
    return (" WHERE " + " AND ".join(where) if where else ""), params


async def list_alarms(f, limit=1000, order="IS_OPEN DESC, BEGIN_TIME DESC"):
    w, p = make_filter(f)
    return await query(f"{SELECT}{w} ORDER BY {order} LIMIT %s", p + [limit])


async def get_alarm(alarm_id):
    return await query_one(SELECT + " WHERE ID = %s", (alarm_id,))


async def add_alarm(data, user):
    cols = list(data)
    new_id = await run(f"INSERT INTO ALARMS ({', '.join(cols)}, CREATED_BY) VALUES ({', '.join(['%s'] * len(cols))}, %s)",
                       [data[c] for c in cols] + [user])
    await run(RECALC, (new_id,))
    return new_id


async def edit_alarm(alarm_id, data, user):
    await run(f"UPDATE ALARMS SET {', '.join(c + ' = %s' for c in data)}, UPDATED_BY = %s, UPDATED_AT = NOW() WHERE ID = %s",
              [data[c] for c in data] + [user, alarm_id])
    await run(RECALC, (alarm_id,))


async def close_alarm(alarm_id, user):
    await run("UPDATE ALARMS SET END_TIME = NOW(), UPDATED_BY = %s, UPDATED_AT = NOW() WHERE ID = %s", (user, alarm_id))
    await run(RECALC, (alarm_id,))


async def delete_alarm(alarm_id):
    return await run("DELETE FROM ALARMS WHERE ID = %s", (alarm_id,))


# подсказки для дежурного
async def get_suggest():
    res = {}
    for col in ["SERV_ELEM", "EQIP_TYPE", "DESCR", "ALARM_WHO"]:
        rows = await query(f"SELECT {col} AS V FROM ALARMS WHERE {col} <> '' GROUP BY {col} "
                           f"ORDER BY COUNT(*) DESC, MAX(BEGIN_TIME) DESC LIMIT 60")
        res[col] = [r["V"] for r in rows]
    return res


async def get_autofill(serv_elem):
    return await query_one("SELECT NAPR, TEHC, NETW_TYPE, NUMB_RBS, EQIP_TYPE, ALARM_WHO FROM ALARMS "
                           "WHERE SERV_ELEM = %s ORDER BY BEGIN_TIME DESC LIMIT 1", (serv_elem,))


# статистика
async def get_stats(f):
    w, p = make_filter(f)
    summary = await query_one(f"""SELECT COUNT(*) AS total, SUM(END_TIME = '{NV}') AS open,
        COALESCE(SUM(TIME_TO_SEC(COMMON_PROSTOY)), 0) AS prostoy_sec, COALESCE(SUM(NUMB_RBS), 0) AS bs,
        COALESCE(AVG(IF(END_TIME = '{NV}', NULL, TIMESTAMPDIFF(SECOND, BEGIN_TIME, END_TIME))), 0) AS avg_sec
        FROM ALARMS{w}""", p)
    res = {"summary": summary}
    for key, col in [("by_tehc", "TEHC"), ("by_type", "ALARM_TYPE"), ("by_napr", "NAPR")]:
        res[key] = await query(f"SELECT {col} AS name, COUNT(*) AS cnt, COALESCE(SUM(TIME_TO_SEC(COMMON_PROSTOY)), 0) AS prostoy_sec "
                               f"FROM ALARMS{w} GROUP BY {col} ORDER BY cnt DESC", p)
    res["by_day"] = await query(f"SELECT DATE(BEGIN_TIME) AS day, COUNT(*) AS cnt FROM ALARMS{w} GROUP BY day ORDER BY day", p)
    return res
