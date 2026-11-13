"""Журнал аварий: справочники, ввод и правка аварий, отчёт за период, CSV, подсказки, статистика.

Права (п. 3.6 ТЗ): admin — всё, duty — вносит и правит аварии, engineer — только просмотр.
"""
import csv
import io
import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import db
from auth import current_user, require_role

router = APIRouter(prefix="/api", tags=["alarms"])

NV = "0000-00-00 00:00:00"        # «НВ» — авария ещё не закрыта (так требует ТЗ)
TIME_MAX_SEC = 838 * 3600 + 59 * 60 + 59   # предел типа TIME в MariaDB

DICT_KINDS = {"napr": "Направление", "tehc": "ТЦ", "kateg": "Категория",
              "netw_type": "Тип сети", "alarm_type": "Тип аварии"}
DICT_FIELDS = {"NAPR": "napr", "TEHC": "tehc", "NETW_TYPE": "netw_type", "ALARM_TYPE": "alarm_type"}

# Поля 1–19 из ТЗ — порядок колонок в CSV
FIELDS = [
    ("PW", "Номер PW/NTT"), ("NAPR", "Направление"), ("TEHC", "ТЦ"), ("KATEG", "Категория"),
    ("NETW_TYPE", "Тип сети"), ("SERV_ELEM", "Сетевой элемент, услуга"), ("NUMB_RBS", "Количество БС"),
    ("EQIP_TYPE", "Тип оборудования"), ("ALARM_TYPE", "Тип"), ("DESCR", "Описание"),
    ("BEGIN_TIME", "Начало"), ("END_TIME", "Окончание"), ("AKB", "АКБ"), ("DGU", "ГУ"),
    ("LENGHT", "Длительность аварии"), ("PROSTOY", "Время перерыва связи"),
    ("COMMON_PROSTOY", "Общее время простоя БС"), ("ALARM_WHO", "Уведомление (кому)"),
    ("DESC_NOTICE", "Подробное описание"),
]

# Длительность для незакрытой аварии считается на лету: текущее время − начало
LENGHT_SQL = (f"IF(END_TIME = '{NV}', TIME_FORMAT(SEC_TO_TIME(LEAST(TIMESTAMPDIFF(SECOND, BEGIN_TIME, NOW()), "
              f"{TIME_MAX_SEC})), '%%H:%%i:%%s'), LENGHT)")
SELECT_SQL = (f"SELECT ID, {', '.join(f for f, _ in FIELDS if f != 'LENGHT')}, {LENGHT_SQL} AS LENGHT, "
              f"END_TIME = '{NV}' AS IS_OPEN, CREATED_BY, CREATED_AT, UPDATED_BY, UPDATED_AT FROM ALARMS")

# Автоматические поля (15 и 17) — одна формула и для сайта, и для демо-данных
RECALC_SQL = (f"UPDATE ALARMS SET "
              f"LENGHT = TIME_FORMAT(SEC_TO_TIME(LEAST(TIMESTAMPDIFF(SECOND, BEGIN_TIME, "
              f"IF(END_TIME = '{NV}', NOW(), END_TIME)), {TIME_MAX_SEC})), '%%H:%%i:%%s'), "
              f"COMMON_PROSTOY = SEC_TO_TIME(LEAST(TIME_TO_SEC(PROSTOY) * GREATEST(NUMB_RBS, 1), {TIME_MAX_SEC})) "
              f"WHERE ID = %s")

HMS = re.compile(r"^\d{1,3}:[0-5]\d(:[0-5]\d)?$")


# ---------------------------------------------------------------------------
# Справочники
# ---------------------------------------------------------------------------

async def load_dicts() -> dict[str, list[str]]:
    rows = await db.fetch_all("SELECT KIND, VALUE FROM DICTS ORDER BY KIND, SORT, VALUE")
    result = {kind: [] for kind in DICT_KINDS}
    for r in rows:
        result.setdefault(r["KIND"], []).append(r["VALUE"])
    return result


@router.get("/dicts")
async def dicts(_: dict = Depends(current_user)):
    return await load_dicts()


@router.get("/dicts/rows")
async def dict_rows(_: dict = Depends(require_role("admin"))):
    rows = await db.fetch_all("SELECT ID, KIND, VALUE, SORT FROM DICTS ORDER BY KIND, SORT, VALUE")
    used = {}
    for field, kind in DICT_FIELDS.items():
        for u in await db.fetch_all(f"SELECT {field} AS V, COUNT(*) AS C FROM ALARMS GROUP BY {field}"):
            used[(kind, u["V"])] = u["C"]
    for u in await db.fetch_all("SELECT KATEG AS V, COUNT(*) AS C FROM ALARMS GROUP BY KATEG"):
        used[("kateg", str(u["V"]))] = u["C"]
    for r in rows:
        r["USED"] = used.get((r["KIND"], r["VALUE"]), 0)
    return {"kinds": DICT_KINDS, "rows": rows}


class DictItem(BaseModel):
    kind: str
    value: str = Field(min_length=1, max_length=128)


@router.post("/dicts", status_code=201)
async def add_dict(item: DictItem, _: dict = Depends(require_role("admin"))):
    if item.kind not in DICT_KINDS:
        raise HTTPException(422, "Неизвестный справочник")
    value = item.value.strip()
    if item.kind == "kateg" and not value.isdigit():
        raise HTTPException(422, "Категория — целое число")
    if await db.fetch_one("SELECT ID FROM DICTS WHERE KIND = %s AND VALUE = %s", (item.kind, value)):
        raise HTTPException(409, "Такое значение уже есть")
    sort = await db.fetch_one("SELECT COALESCE(MAX(SORT), 0) + 1 AS S FROM DICTS WHERE KIND = %s", (item.kind,))
    new_id = await db.execute("INSERT INTO DICTS (KIND, VALUE, SORT) VALUES (%s, %s, %s)", (item.kind, value, sort["S"]))
    return {"id": new_id}


@router.delete("/dicts/{dict_id}")
async def delete_dict(dict_id: int, _: dict = Depends(require_role("admin"))):
    # Старые аварии сохраняют своё значение — справочник влияет только на новые записи
    if not await db.execute("DELETE FROM DICTS WHERE ID = %s", (dict_id,)):
        raise HTTPException(404, "Значение не найдено")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Аварии
# ---------------------------------------------------------------------------

class Alarm(BaseModel):
    """Все поля, кроме начала, необязательны: не у каждой аварии есть номер PW/NTT и т. п."""
    PW: str | None = Field(None, max_length=450)
    NAPR: str | None = None
    TEHC: str | None = None
    KATEG: int | None = Field(None, ge=1, le=9)
    NETW_TYPE: str | None = None
    SERV_ELEM: str | None = Field(None, max_length=450)
    NUMB_RBS: int | None = Field(None, ge=0, le=10000)   # 0 = «С» (сектор)
    EQIP_TYPE: str | None = Field(None, max_length=450)
    ALARM_TYPE: str | None = None
    DESCR: str | None = Field(None, max_length=450)
    BEGIN_TIME: datetime
    END_TIME: datetime | None = None                     # None = «НВ»
    AKB: str | None = None
    DGU: str | None = None
    PROSTOY: str | None = None
    ALARM_WHO: str | None = Field(None, max_length=450)
    DESC_NOTICE: str | None = Field(None, max_length=450)


async def validate(a: Alarm) -> dict:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in a.model_dump().items()}
    data = {k: (None if v == "" else v) for k, v in data.items()}
    dicts = await load_dicts()
    for field, kind in DICT_FIELDS.items():
        if data[field] and data[field] not in dicts.get(kind, []):
            raise HTTPException(422, f"«{data[field]}» нет в справочнике «{DICT_KINDS[kind]}»")
    if data["KATEG"] and str(data["KATEG"]) not in dicts.get("kateg", []):
        raise HTTPException(422, f"Категории {data['KATEG']} нет в справочнике")
    for field, title in (("AKB", "АКБ"), ("DGU", "ГУ"), ("PROSTOY", "Время перерыва связи")):
        if data[field] and not HMS.match(data[field]):
            raise HTTPException(422, f"{title}: формат чч:мм:сс")
    if data["END_TIME"] and data["END_TIME"] < data["BEGIN_TIME"]:
        raise HTTPException(422, "Окончание раньше начала")
    data["END_TIME"] = data["END_TIME"] or NV
    return data


async def get_alarm(alarm_id: int) -> dict:
    row = await db.fetch_one(SELECT_SQL + " WHERE ID = %s", (alarm_id,))
    if not row:
        raise HTTPException(404, "Авария не найдена")
    return row


def period_filter(date_from, date_to, only_open, napr, tehc, alarm_type, q):
    where, params = [], []
    if date_from:
        # Незакрытые аварии, начавшиеся раньше периода, тоже относятся к нему
        where.append(f"(BEGIN_TIME >= %s OR END_TIME = '{NV}' OR END_TIME >= %s)")
        params += [f"{date_from} 00:00:00", f"{date_from} 00:00:00"]
    if date_to:
        where.append("BEGIN_TIME <= %s")
        params.append(f"{date_to} 23:59:59")
    if only_open:
        where.append(f"END_TIME = '{NV}'")
    for field, value in (("NAPR", napr), ("TEHC", tehc), ("ALARM_TYPE", alarm_type)):
        if value:
            where.append(f"{field} = %s")
            params.append(value)
    if q:
        where.append("CONCAT_WS(' ', PW, SERV_ELEM, EQIP_TYPE, DESCR, DESC_NOTICE, ALARM_WHO) LIKE %s")
        params.append(f"%{q}%")
    return (" WHERE " + " AND ".join(where)) if where else "", params


@router.get("/alarms")
async def list_alarms(
    date_from: date | None = None, date_to: date | None = None, only_open: bool = False,
    napr: str | None = None, tehc: str | None = None, alarm_type: str | None = None,
    q: str | None = Query(None, max_length=100), limit: int = Query(1000, ge=1, le=5000),
    _: dict = Depends(current_user),
):
    clause, params = period_filter(date_from, date_to, only_open, napr, tehc, alarm_type, q)
    return await db.fetch_all(f"{SELECT_SQL}{clause} ORDER BY IS_OPEN DESC, BEGIN_TIME DESC LIMIT %s",
                              params + [limit])


@router.get("/alarms/{alarm_id}")
async def alarm(alarm_id: int, _: dict = Depends(current_user)):
    return await get_alarm(alarm_id)


@router.post("/alarms", status_code=201)
async def create_alarm(a: Alarm, user: dict = Depends(require_role("admin", "duty"))):
    data = await validate(a)
    cols = list(data)
    new_id = await db.execute(
        f"INSERT INTO ALARMS ({', '.join(cols)}, CREATED_BY) VALUES ({', '.join(['%s'] * len(cols))}, %s)",
        [data[c] for c in cols] + [user["username"]],
    )
    await db.execute(RECALC_SQL, (new_id,))
    return await get_alarm(new_id)


@router.put("/alarms/{alarm_id}")
async def update_alarm(alarm_id: int, a: Alarm, user: dict = Depends(require_role("admin", "duty"))):
    await get_alarm(alarm_id)
    data = await validate(a)
    await db.execute(
        f"UPDATE ALARMS SET {', '.join(f'{c} = %s' for c in data)}, UPDATED_BY = %s, UPDATED_AT = NOW() WHERE ID = %s",
        [data[c] for c in data] + [user["username"], alarm_id],
    )
    await db.execute(RECALC_SQL, (alarm_id,))
    return await get_alarm(alarm_id)


@router.post("/alarms/{alarm_id}/close")
async def close_alarm(alarm_id: int, user: dict = Depends(require_role("admin", "duty"))):
    """Закрыть аварию одной кнопкой: окончание = текущее время."""
    row = await get_alarm(alarm_id)
    if not row["IS_OPEN"]:
        raise HTTPException(409, "Авария уже закрыта")
    await db.execute("UPDATE ALARMS SET END_TIME = NOW(), UPDATED_BY = %s, UPDATED_AT = NOW() WHERE ID = %s",
                     (user["username"], alarm_id))
    await db.execute(RECALC_SQL, (alarm_id,))
    return await get_alarm(alarm_id)


@router.delete("/alarms/{alarm_id}")
async def delete_alarm(alarm_id: int, _: dict = Depends(require_role("admin"))):
    await get_alarm(alarm_id)
    await db.execute("DELETE FROM ALARMS WHERE ID = %s", (alarm_id,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Подсказки для дежурного
# ---------------------------------------------------------------------------

SUGGEST_FIELDS = ("SERV_ELEM", "EQIP_TYPE", "DESCR", "ALARM_WHO")


@router.get("/suggest")
async def suggest(_: dict = Depends(current_user)):
    """Частые значения из прошлых аварий — для выпадающих подсказок в форме."""
    result = {}
    for field in SUGGEST_FIELDS:
        rows = await db.fetch_all(
            f"SELECT {field} AS V FROM ALARMS WHERE {field} IS NOT NULL AND {field} <> '' "
            f"GROUP BY {field} ORDER BY COUNT(*) DESC, MAX(BEGIN_TIME) DESC LIMIT 60")
        result[field] = [r["V"] for r in rows]
    return result


@router.get("/autofill")
async def autofill(serv_elem: str, _: dict = Depends(current_user)):
    """Последняя авария на этом же элементе: подставляем ТЦ, направление, сеть, оборудование."""
    row = await db.fetch_one(
        "SELECT NAPR, TEHC, NETW_TYPE, NUMB_RBS, EQIP_TYPE, ALARM_WHO FROM ALARMS "
        "WHERE SERV_ELEM = %s ORDER BY BEGIN_TIME DESC LIMIT 1", (serv_elem,))
    return row or {}


# ---------------------------------------------------------------------------
# Выгрузка CSV и статистика
# ---------------------------------------------------------------------------

@router.get("/alarms-export.csv")
async def export_csv(
    date_from: date | None = None, date_to: date | None = None, only_open: bool = False,
    napr: str | None = None, tehc: str | None = None, alarm_type: str | None = None, q: str | None = None,
    _: dict = Depends(current_user),
):
    clause, params = period_filter(date_from, date_to, only_open, napr, tehc, alarm_type, q)
    rows = await db.fetch_all(f"{SELECT_SQL}{clause} ORDER BY BEGIN_TIME", params)

    buf = io.StringIO()
    buf.write("﻿")   # BOM — Excel откроет кириллицу без «кракозябр»
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(["№"] + [title for _, title in FIELDS])
    for r in rows:
        line = [r["ID"]]
        for field, _ in FIELDS:
            v = r[field]
            if field == "END_TIME" and v is None:
                v = "НВ"
            elif field == "NUMB_RBS" and v == 0:
                v = "С"
            elif field in ("BEGIN_TIME", "END_TIME") and v:
                v = v.replace("T", " ")
            line.append("" if v is None else v)
        writer.writerow(line)

    name = f"alarms_{date_from or 'all'}_{date_to or datetime.now().date()}.csv"
    return StreamingResponse(iter([buf.getvalue().encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/stats")
async def stats(date_from: date | None = None, date_to: date | None = None, _: dict = Depends(current_user)):
    clause, params = period_filter(date_from, date_to, False, None, None, None, None)
    base = f"FROM ALARMS{clause}"
    total = await db.fetch_one(
        f"SELECT COUNT(*) AS total, SUM(END_TIME = '{NV}') AS open, "
        f"COALESCE(SUM(TIME_TO_SEC(COMMON_PROSTOY)), 0) AS prostoy_sec, "
        f"COALESCE(SUM(NUMB_RBS), 0) AS bs, "
        f"COALESCE(AVG(IF(END_TIME = '{NV}', NULL, TIMESTAMPDIFF(SECOND, BEGIN_TIME, END_TIME))), 0) AS avg_sec "
        f"{base}", params)

    async def group(field):
        return await db.fetch_all(
            f"SELECT {field} AS name, COUNT(*) AS cnt, COALESCE(SUM(TIME_TO_SEC(COMMON_PROSTOY)), 0) AS prostoy_sec "
            f"{base} GROUP BY {field} ORDER BY cnt DESC, prostoy_sec DESC", params)

    by_day = await db.fetch_all(f"SELECT DATE(BEGIN_TIME) AS day, COUNT(*) AS cnt {base} GROUP BY DATE(BEGIN_TIME) "
                                f"ORDER BY day", params)
    return {"summary": total, "by_tehc": await group("TEHC"), "by_type": await group("ALARM_TYPE"),
            "by_napr": await group("NAPR"), "by_day": by_day}
