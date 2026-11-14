import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime

import pymysql
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import backend as db


@asynccontextmanager
async def lifespan(app):
    try:
        await db.init_pool()
    except Exception:
        pass
    yield
    await db.close_pool()


app = FastAPI(title="Веб-отчётность", version="1.0.0", lifespan=lifespan)


class DataUpload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_num: str | None = Field(None, alias="PW", max_length=450)
    direction: str | None = Field(None, alias="NAPR")
    tech_center: str | None = Field(None, alias="TEHC")
    category: int | None = Field(None, alias="KATEG", ge=1, le=9)
    network_type: str | None = Field(None, alias="NETW_TYPE")
    network_element: str | None = Field(None, alias="SERV_ELEM", max_length=450)
    total_base_station: int | None = Field(None, alias="NUMB_RBS", ge=0, le=10000)
    element_type: str | None = Field(None, alias="EQIP_TYPE", max_length=450)
    type: str | None = Field(None, alias="ALARM_TYPE")
    description: str | None = Field(None, alias="DESCR", max_length=450)
    start_time: datetime = Field(alias="BEGIN_TIME")
    end_time: datetime | None = Field(None, alias="END_TIME")
    lifetime_by_battery: str | None = Field(None, alias="AKB")
    lifetime_by_generator: str | None = Field(None, alias="DGU")
    time_accident: str | None = Field(None, alias="LENGHT")
    time_connection_interupt: str | None = Field(None, alias="PROSTOY")
    base_station_downtime: str | None = Field(None, alias="COMMON_PROSTOY")
    accident_comment: str | None = Field(None, alias="ALARM_WHO", max_length=450)
    accident_detailed_description: str | None = Field(None, alias="DESC_NOTICE", max_length=450)


class DictItem(BaseModel):
    kind: str
    value: str = Field(min_length=1, max_length=128)


DB_DOWN = ("Нет связи с базой данных. Запись не сохранена — повторите через минуту. "
           "Если ошибка не проходит, сообщите администратору.")


@app.exception_handler(pymysql.err.OperationalError)
@app.exception_handler(pymysql.err.InterfaceError)
@app.exception_handler(ConnectionError)
async def db_down(request: Request, exc: Exception):
    return JSONResponse(status_code=503, content={"detail": DB_DOWN})


@app.get("/api/health")
async def api_health():
    return {"api": "ok", **(await db.health())}


SECRET = os.getenv("AUTH_SECRET", "motiv-secret").encode()
ROLE_NAMES = {"admin": "Администратор", "duty": "Дежурный", "engineer": "Инженер"}


def sign(data):
    return hmac.new(SECRET, data, hashlib.sha256).hexdigest()


def make_token(user):
    data = json.dumps({"u": user["USERNAME"], "r": user["ROLE"], "n": user["FULL_NAME"],
                       "exp": int(time.time()) + 12 * 3600}).encode()
    return base64.urlsafe_b64encode(data).decode() + "." + sign(data)


def get_user(authorization: str = Header(default="")):
    try:
        body, signature = authorization.replace("Bearer ", "").split(".")
        data = base64.urlsafe_b64decode(body)
        if not hmac.compare_digest(signature, sign(data)):
            raise ValueError
        token = json.loads(data)
        if token["exp"] < time.time():
            raise ValueError
    except Exception:
        raise HTTPException(401, "Нужно войти заново")
    return {"username": token["u"], "role": token["r"], "full_name": token["n"]}


def can_edit(user=Depends(get_user)):
    if user["role"] not in ("admin", "duty"):
        raise HTTPException(403, "Недостаточно прав")
    return user


def only_admin(user=Depends(get_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Только для администратора")
    return user


@app.post("/api/login")
async def login(data: dict):
    user = await db.check_user(str(data.get("username", "")).strip(), str(data.get("password", "")))
    if not user:
        raise HTTPException(401, "Неверный логин или пароль")
    return {"token": make_token(user), "username": user["USERNAME"], "role": user["ROLE"],
            "role_name": ROLE_NAMES[user["ROLE"]], "full_name": user["FULL_NAME"]}


@app.get("/api/dicts")
async def dicts(user=Depends(get_user)):
    return await db.get_dicts()


@app.get("/api/dicts/rows")
async def dict_rows(user=Depends(only_admin)):
    kinds = {"napr": "Направление", "tehc": "ТЦ", "kateg": "Категория",
             "netw_type": "Тип сети", "alarm_type": "Тип аварии"}
    return {"kinds": kinds, "rows": await db.get_dict_rows()}


@app.post("/api/dicts", status_code=201)
async def add_dict(item: DictItem, user=Depends(only_admin)):
    value = item.value.strip()
    if item.kind not in ("napr", "tehc", "kateg", "netw_type", "alarm_type"):
        raise HTTPException(422, "Нет такого списка")
    if item.kind == "kateg" and not value.isdigit():
        raise HTTPException(422, "Категория — это число")
    new_id = await db.add_dict(item.kind, value)
    if not new_id:
        raise HTTPException(409, "Такое значение уже есть")
    return {"id": new_id}


@app.delete("/api/dicts/{dict_id}")
async def delete_dict(dict_id: int, user=Depends(only_admin)):
    if not await db.delete_dict(dict_id):
        raise HTTPException(404, "Не найдено")
    return {"ok": True}


async def check_alarm(alarm: DataUpload):
    data = alarm.model_dump(by_alias=True)
    data.pop("LENGHT")
    data.pop("COMMON_PROSTOY")
    for key, value in data.items():
        if isinstance(value, str):
            data[key] = value.strip() or None

    lists = await db.get_dicts()
    for col, kind, name in [("NAPR", "napr", "Направление"), ("TEHC", "tehc", "ТЦ"),
                            ("NETW_TYPE", "netw_type", "Тип сети"), ("ALARM_TYPE", "alarm_type", "Тип")]:
        if data[col] and data[col] not in lists[kind]:
            raise HTTPException(422, f"«{data[col]}» нет в списке «{name}»")
    if data["KATEG"] and str(data["KATEG"]) not in lists["kateg"]:
        raise HTTPException(422, "Нет такой категории")

    for col in ["AKB", "DGU", "PROSTOY"]:
        if data[col] and not re.match(r"^\d{1,3}:[0-5]\d(:[0-5]\d)?$", data[col]):
            raise HTTPException(422, f"{col}: формат чч:мм:сс")

    if data["END_TIME"] and data["END_TIME"] < data["BEGIN_TIME"]:
        raise HTTPException(422, "Окончание раньше начала")
    if not data["END_TIME"]:
        data["END_TIME"] = db.NV
    return data


async def alarm_or_404(alarm_id):
    alarm = await db.get_alarm(alarm_id)
    if not alarm:
        raise HTTPException(404, "Авария не найдена")
    return alarm


def make_filter(date_from, date_to, only_open, napr, tehc, alarm_type, q):
    return {"date_from": date_from, "date_to": date_to, "only_open": only_open,
            "napr": napr, "tehc": tehc, "alarm_type": alarm_type, "q": q}


@app.get("/api/alarms")
async def alarms(date_from: date | None = None, date_to: date | None = None, only_open: bool = False,
                 napr: str | None = None, tehc: str | None = None, alarm_type: str | None = None,
                 q: str | None = None, limit: int = 1000, user=Depends(get_user)):
    f = make_filter(date_from, date_to, only_open, napr, tehc, alarm_type, q)
    return await db.list_alarms(f, min(limit, 5000))


@app.get("/api/alarms/{alarm_id}")
async def alarm(alarm_id: int, user=Depends(get_user)):
    return await alarm_or_404(alarm_id)


@app.post("/api/alarms", status_code=201)
async def new_alarm(alarm: DataUpload, user=Depends(can_edit)):
    data = await check_alarm(alarm)
    new_id = await db.add_alarm(data, user["username"])
    return await db.get_alarm(new_id)


@app.put("/api/alarms/{alarm_id}")
async def change_alarm(alarm_id: int, alarm: DataUpload, user=Depends(can_edit)):
    await alarm_or_404(alarm_id)
    data = await check_alarm(alarm)
    await db.edit_alarm(alarm_id, data, user["username"])
    return await db.get_alarm(alarm_id)


@app.post("/api/alarms/{alarm_id}/close")
async def close_alarm(alarm_id: int, user=Depends(can_edit)):
    alarm = await alarm_or_404(alarm_id)
    if not alarm["IS_OPEN"]:
        raise HTTPException(409, "Авария уже закрыта")
    await db.close_alarm(alarm_id, user["username"])
    return await db.get_alarm(alarm_id)


@app.delete("/api/alarms/{alarm_id}")
async def remove_alarm(alarm_id: int, user=Depends(only_admin)):
    await alarm_or_404(alarm_id)
    await db.delete_alarm(alarm_id)
    return {"ok": True}


@app.get("/api/suggest")
async def suggest(user=Depends(get_user)):
    return await db.get_suggest()


@app.get("/api/autofill")
async def autofill(serv_elem: str, user=Depends(get_user)):
    return await db.get_autofill(serv_elem) or {}


CSV_HEAD = ["№", "Номер PW/NTT", "Направление", "ТЦ", "Категория", "Тип сети", "Сетевой элемент, услуга",
            "Количество БС", "Тип оборудования", "Тип", "Описание", "Начало", "Окончание", "АКБ", "ГУ",
            "Длительность аварии", "Время перерыва связи", "Общее время простоя БС", "Уведомление (кому)",
            "Подробное описание"]


def csv_value(col, value):
    if col == "END_TIME" and value is None:
        return "НВ"
    if col == "NUMB_RBS" and value == 0:
        return "С"
    if col in ("BEGIN_TIME", "END_TIME") and value:
        return value.replace("T", " ")
    if value is None:
        return ""
    return value


@app.get("/api/alarms-export.csv")
async def export_csv(date_from: date | None = None, date_to: date | None = None, only_open: bool = False,
                     napr: str | None = None, tehc: str | None = None, alarm_type: str | None = None,
                     q: str | None = None, user=Depends(get_user)):
    f = make_filter(date_from, date_to, only_open, napr, tehc, alarm_type, q)
    rows = await db.list_alarms(f, 100000, order="BEGIN_TIME")

    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEAD)
    for row in rows:
        writer.writerow([row["ID"]] + [csv_value(col, row[col]) for col in db.COLS])

    name = f"alarms_{date_from or 'all'}_{date_to or date.today()}.csv"
    return StreamingResponse(iter([out.getvalue().encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/stats")
async def stats(date_from: date | None = None, date_to: date | None = None, user=Depends(get_user)):
    return await db.get_stats({"date_from": date_from, "date_to": date_to})
