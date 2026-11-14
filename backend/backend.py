import hashlib
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
    "cursorclass": aiomysql.DictCursor,
}

NV = "0000-00-00 00:00:00"
TIME_MAX = 3020399

COLS = ["PW", "NAPR", "TEHC", "KATEG", "NETW_TYPE", "SERV_ELEM", "NUMB_RBS", "EQIP_TYPE", "ALARM_TYPE",
        "DESCR", "BEGIN_TIME", "END_TIME", "AKB", "DGU", "LENGHT", "PROSTOY", "COMMON_PROSTOY",
        "ALARM_WHO", "DESC_NOTICE"]

LENGHT_NOW = f"TIME_FORMAT(SEC_TO_TIME(LEAST(TIMESTAMPDIFF(SECOND, BEGIN_TIME, NOW()), {TIME_MAX})), '%%H:%%i:%%s')"

SELECT = f"""SELECT ID, {', '.join(c for c in COLS if c != 'LENGHT')},
    IF(END_TIME = '{NV}', {LENGHT_NOW}, LENGHT) AS LENGHT,
    END_TIME = '{NV}' AS IS_OPEN, CREATED_BY, CREATED_AT, UPDATED_BY, UPDATED_AT
    FROM ALARMS"""

RECALC = f"""UPDATE ALARMS SET
    LENGHT = TIME_FORMAT(SEC_TO_TIME(LEAST(TIMESTAMPDIFF(SECOND, BEGIN_TIME,
             IF(END_TIME = '{NV}', NOW(), END_TIME)), {TIME_MAX})), '%%H:%%i:%%s'),
    COMMON_PROSTOY = SEC_TO_TIME(LEAST(TIME_TO_SEC(PROSTOY) * GREATEST(NUMB_RBS, 1), {TIME_MAX}))
    WHERE ID = %s"""

pool = None


async def init_pool():
    global pool
    if pool is None:
        pool = await aiomysql.create_pool(minsize=1, maxsize=5, **DB_CONFIG)


async def close_pool():
    if pool is not None:
        pool.close()
        await pool.wait_closed()


def to_json(value):
    if isinstance(value, timedelta):
        sec = int(value.total_seconds())
        return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str) and value.startswith("0000-00-00"):
        return None
    return value


async def query(sql, params=()):
    await init_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()
    return [{key: to_json(val) for key, val in row.items()} for row in rows]


async def query_one(sql, params=()):
    rows = await query(sql, params)
    return rows[0] if rows else None


async def is_future(value):
    row = await query_one("SELECT %s > NOW() + INTERVAL 10 MINUTE AS f", (value,))
    return bool(row and row["f"])


async def run(sql, params=()):
    await init_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return cur.lastrowid or cur.rowcount


async def health():
    try:
        await init_pool()
        row = await query_one("SELECT COUNT(*) AS alarms FROM ALARMS")
        return {"database": "ok", "alarms": row["alarms"]}
    except Exception as e:
        return {"database": f"error: {e}"}


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


async def check_user(username, password):
    return await query_one(
        "SELECT USERNAME, ROLE, FULL_NAME FROM USERS WHERE USERNAME = %s AND PASSWORD_HASH = %s",
        (username, hash_password(password)))


async def get_dicts():
    result = {"napr": [], "tehc": [], "kateg": [], "netw_type": [], "alarm_type": []}
    for row in await query("SELECT KIND, VALUE FROM DICTS ORDER BY KIND, SORT, VALUE"):
        result.setdefault(row["KIND"], []).append(row["VALUE"])
    return result


async def get_dict_rows():
    rows = await query("SELECT ID, KIND, VALUE, SORT FROM DICTS ORDER BY KIND, SORT, VALUE")
    used = {}
    for col, kind in [("NAPR", "napr"), ("TEHC", "tehc"), ("NETW_TYPE", "netw_type"),
                      ("ALARM_TYPE", "alarm_type"), ("KATEG", "kateg")]:
        for row in await query(f"SELECT {col} AS V, COUNT(*) AS C FROM ALARMS GROUP BY {col}"):
            used[(kind, str(row["V"]))] = row["C"]
    for row in rows:
        row["USED"] = used.get((row["KIND"], row["VALUE"]), 0)
    return rows


async def add_dict(kind, value):
    if await query_one("SELECT ID FROM DICTS WHERE KIND = %s AND VALUE = %s", (kind, value)):
        return None
    last = await query_one("SELECT COALESCE(MAX(SORT), 0) + 1 AS S FROM DICTS WHERE KIND = %s", (kind,))
    return await run("INSERT INTO DICTS (KIND, VALUE, SORT) VALUES (%s, %s, %s)", (kind, value, last["S"]))


async def delete_dict(dict_id):
    return await run("DELETE FROM DICTS WHERE ID = %s", (dict_id,))


def make_filter(f):
    where = []
    params = []
    if f.get("date_from"):
        where.append(f"(BEGIN_TIME >= %s OR END_TIME = '{NV}' OR END_TIME >= %s)")
        params += [f"{f['date_from']} 00:00:00", f"{f['date_from']} 00:00:00"]
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
    if not where:
        return "", params
    return " WHERE " + " AND ".join(where), params


async def list_alarms(f, limit=1000, order="IS_OPEN DESC, BEGIN_TIME DESC"):
    where, params = make_filter(f)
    return await query(f"{SELECT}{where} ORDER BY {order} LIMIT %s", params + [limit])


async def get_alarm(alarm_id):
    return await query_one(SELECT + " WHERE ID = %s", (alarm_id,))


async def add_alarm(data, user):
    cols = list(data)
    marks = ", ".join(["%s"] * len(cols))
    values = [data[c] for c in cols] + [user]
    new_id = await run(f"INSERT INTO ALARMS ({', '.join(cols)}, CREATED_BY) VALUES ({marks}, %s)", values)
    await run(RECALC, (new_id,))
    return new_id


async def edit_alarm(alarm_id, data, user):
    sets = ", ".join(c + " = %s" for c in data)
    values = [data[c] for c in data] + [user, alarm_id]
    await run(f"UPDATE ALARMS SET {sets}, UPDATED_BY = %s, UPDATED_AT = NOW() WHERE ID = %s", values)
    await run(RECALC, (alarm_id,))


async def close_alarm(alarm_id, user):
    await run("UPDATE ALARMS SET END_TIME = NOW(), UPDATED_BY = %s, UPDATED_AT = NOW() WHERE ID = %s",
              (user, alarm_id))
    await run(RECALC, (alarm_id,))


async def delete_alarm(alarm_id):
    return await run("DELETE FROM ALARMS WHERE ID = %s", (alarm_id,))


async def get_suggest():
    result = {}
    for col in ["SERV_ELEM", "EQIP_TYPE", "DESCR", "ALARM_WHO"]:
        rows = await query(f"SELECT {col} AS V FROM ALARMS WHERE {col} <> '' GROUP BY {col} "
                           f"ORDER BY COUNT(*) DESC, MAX(BEGIN_TIME) DESC LIMIT 60")
        result[col] = [row["V"] for row in rows]
    return result


async def get_autofill(serv_elem):
    return await query_one(
        "SELECT NAPR, TEHC, NETW_TYPE, NUMB_RBS, EQIP_TYPE, ALARM_WHO FROM ALARMS "
        "WHERE SERV_ELEM = %s ORDER BY BEGIN_TIME DESC LIMIT 1", (serv_elem,))


async def get_stats(f):
    where, params = make_filter(f)
    summary = await query_one(f"""SELECT COUNT(*) AS total, SUM(END_TIME = '{NV}') AS open,
        COALESCE(SUM(TIME_TO_SEC(COMMON_PROSTOY)), 0) AS prostoy_sec,
        COALESCE(SUM(NUMB_RBS), 0) AS bs,
        COALESCE(AVG(IF(END_TIME = '{NV}', NULL, TIMESTAMPDIFF(SECOND, BEGIN_TIME, END_TIME))), 0) AS avg_sec
        FROM ALARMS{where}""", params)
    result = {"summary": summary}
    for key, col in [("by_tehc", "TEHC"), ("by_type", "ALARM_TYPE"), ("by_napr", "NAPR")]:
        result[key] = await query(
            f"SELECT {col} AS name, COUNT(*) AS cnt, COALESCE(SUM(TIME_TO_SEC(COMMON_PROSTOY)), 0) AS prostoy_sec "
            f"FROM ALARMS{where} GROUP BY {col} ORDER BY cnt DESC", params)
    result["by_day"] = await query(
        f"SELECT DATE(BEGIN_TIME) AS day, COUNT(*) AS cnt FROM ALARMS{where} GROUP BY day ORDER BY day", params)
    return result
