import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import time
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator, Field

import backend as db

app = FastAPI(title="Веб-отчётность", version="0.1.0")

direct = ['ХМЯН', 'СВН', 'ЮЗН', 'Вся сеть']

class DataLogin(BaseModel):
    username: str
    password: str


class DataUpload(BaseModel):
    device_num: str | None = Field(None, max_length=15) # №1
    direction: str | None = Field(None, max_length=8) # №2
    tech_center: str | None = Field(None, max_length=4) # №3
    category: str | None = Field(None, max_length=1) # №4
    network_type: str | None = Field(None, max_length=7)# №5
    network_element: str | None = Field(None, max_length=20) # №6
    total_base_station: str | None = Field(None, max_length=10000) # №7
    element_type: str | None = Field(None, max_length=255) # №8
    type: str | None = Field(None, max_length=5) # №9
    description: str | None = Field(None, max_length=255) # №10
    start_time: str | None = Field(None, max_length=50) # №11
    end_time: str | None = Field(None, max_length=50) # №12
    lifetime_by_battery: str | None = Field(None, max_length=8) # №13
    lifetime_by_generator: str | None = Field(None, max_length=8) # №14
    time_accident: str | None = Field(None, max_length=8) # №15 !!!ПОМЕНЯТЬ НА ФОРМУЛУ ПО ТЗ!!!
    time_connection_interupt: str | None = Field(None, max_length=8) # №16
    base_station_downtime: str | None = Field(None, max_length=8) # №17 !!!ПОМЕНЯТЬ НА ФОРМУЛУ ПО ТЗ!!!
    accident_comment: str | None = Field(None, max_length=20) # №18
    accident_detailed_description: str | None = Field(None, max_length=255) # №19

    @field_validator('category')
    def num_is_digit(cls, v: str) -> str | None:
        try:
            if 0 < int(v) < 4:
                return v
            raise ValueError('Категория должна быть числом от 1 до 3')
        except:
            raise ValueError('Ошибка. Введенное значение должно быть числом')

    @field_validator('device_num')
    def aaa(cls, v):
        # TODO проверка номера PW/NTT
        return v




@app.get("/check")
def health_check():
    raise HTTPException(status_code=200, detail=f'API работает!')

@app.get('/Accident')
def data_tranfer():
    pass


# ---------------- API для сайта (nginx пускает только /api) ----------------

@app.on_event("startup")
async def startup():
    await db.init_pool()


@app.get("/api/health")
async def api_health():
    return {"api": "ok", **(await db.health())}


# --- вход и роли ---
# токен = данные + подпись, на сервере ничего не храним (работает и при нескольких копиях бэкенда)

SECRET = os.getenv("AUTH_SECRET", "motiv-secret").encode()
ROLE_NAMES = {"admin": "Администратор", "duty": "Дежурный", "engineer": "Инженер"}


def sign(data: bytes) -> str:
    return hmac.new(SECRET, data, hashlib.sha256).hexdigest()


def make_token(user):
    data = json.dumps({"u": user["USERNAME"], "r": user["ROLE"], "n": user["FULL_NAME"],
                       "exp": int(time.time()) + 12 * 3600}).encode()
    return base64.urlsafe_b64encode(data).decode() + "." + sign(data)


def get_user(authorization: str = Header(default="")):
    try:
        body, s = authorization.replace("Bearer ", "").split(".")
        data = base64.urlsafe_b64decode(body)
        assert hmac.compare_digest(s, sign(data))
        t = json.loads(data)
        assert t["exp"] > time.time()
    except Exception:
        raise HTTPException(401, "Нужно войти заново")
    return {"username": t["u"], "role": t["r"], "full_name": t["n"]}


def can_edit(user=Depends(get_user)):  # админ и дежурный
    if user["role"] not in ("admin", "duty"):
        raise HTTPException(403, "Недостаточно прав")
    return user


def only_admin(user=Depends(get_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Только для администратора")
    return user


@app.post("/api/login")
async def login(body: DataLogin):
    user = await db.check_user(body.username.strip(), body.password)
    if not user:
        raise HTTPException(401, "Неверный логин или пароль")
    return {"token": make_token(user), "username": user["USERNAME"], "role": user["ROLE"],
            "role_name": ROLE_NAMES[user["ROLE"]], "full_name": user["FULL_NAME"]}


# --- справочники ---

class DictItem(BaseModel):
    kind: str
    value: str = Field(min_length=1, max_length=128)


@app.get("/api/dicts")
async def dicts(user=Depends(get_user)):
    return await db.get_dicts()


@app.get("/api/dicts/rows")
async def dict_rows(user=Depends(only_admin)):
    kinds = {"napr": "Направление", "tehc": "ТЦ", "kateg": "Категория", "netw_type": "Тип сети", "alarm_type": "Тип аварии"}
    return {"kinds": kinds, "rows": await db.get_dict_rows()}


@app.post("/api/dicts", status_code=201)
async def add_dict(item: DictItem, user=Depends(only_admin)):
    if item.kind not in ("napr", "tehc", "kateg", "netw_type", "alarm_type"):
        raise HTTPException(422, "Нет такого справочника")
    if item.kind == "kateg" and not item.value.strip().isdigit():
        raise HTTPException(422, "Категория - число")
    new_id = await db.add_dict(item.kind, item.value.strip())
    if not new_id:
        raise HTTPException(409, "Такое значение уже есть")
    return {"id": new_id}


@app.delete("/api/dicts/{dict_id}")
async def delete_dict(dict_id: int, user=Depends(only_admin)):
    # старые аварии значение не теряют
    if not await db.delete_dict(dict_id):
        raise HTTPException(404, "Не найдено")
    return {"ok": True}


# --- аварии ---

class Alarm(BaseModel):
    # обязательно только начало, остальное может быть пустым (не у всех аварий есть номер PW и т.д.)
    PW: str | None = Field(None, max_length=450)
    NAPR: str | None = None
    TEHC: str | None = None
    KATEG: int | None = Field(None, ge=1, le=9)
    NETW_TYPE: str | None = None
    SERV_ELEM: str | None = Field(None, max_length=450)
    NUMB_RBS: int | None = Field(None, ge=0, le=10000)  # 0 = С (сектор)
    EQIP_TYPE: str | None = Field(None, max_length=450)
    ALARM_TYPE: str | None = None
    DESCR: str | None = Field(None, max_length=450)
    BEGIN_TIME: datetime
    END_TIME: datetime | None = None  # None = НВ
    AKB: str | None = None
    DGU: str | None = None
    PROSTOY: str | None = None
    ALARM_WHO: str | None = Field(None, max_length=450)
    DESC_NOTICE: str | None = Field(None, max_length=450)


async def check_alarm(a: Alarm):
    data = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in a.model_dump().items()}
    d = await db.get_dicts()
    for col, kind, name in [("NAPR", "napr", "Направление"), ("TEHC", "tehc", "ТЦ"),
                            ("NETW_TYPE", "netw_type", "Тип сети"), ("ALARM_TYPE", "alarm_type", "Тип")]:
        if data[col] and data[col] not in d[kind]:
            raise HTTPException(422, f"«{data[col]}» нет в справочнике «{name}»")
    if data["KATEG"] and str(data["KATEG"]) not in d["kateg"]:
        raise HTTPException(422, "Нет такой категории")
    for col in ("AKB", "DGU", "PROSTOY"):
        if data[col] and not re.match(r"^\d{1,3}:[0-5]\d(:[0-5]\d)?$", data[col]):
            raise HTTPException(422, f"{col}: формат чч:мм:сс")
    if data["END_TIME"] and data["END_TIME"] < data["BEGIN_TIME"]:
        raise HTTPException(422, "Окончание раньше начала")
    data["END_TIME"] = data["END_TIME"] or db.NV
    return data


async def alarm_or_404(alarm_id):
    a = await db.get_alarm(alarm_id)
    if not a:
        raise HTTPException(404, "Авария не найдена")
    return a


@app.get("/api/alarms")
async def alarms(date_from: date | None = None, date_to: date | None = None, only_open: bool = False,
                 napr: str | None = None, tehc: str | None = None, alarm_type: str | None = None,
                 q: str | None = None, limit: int = 1000, user=Depends(get_user)):
    f = dict(date_from=date_from, date_to=date_to, only_open=only_open, napr=napr, tehc=tehc, alarm_type=alarm_type, q=q)
    return await db.list_alarms(f, min(limit, 5000))


@app.get("/api/alarms/{alarm_id}")
async def alarm(alarm_id: int, user=Depends(get_user)):
    return await alarm_or_404(alarm_id)


@app.post("/api/alarms", status_code=201)
async def new_alarm(a: Alarm, user=Depends(can_edit)):
    new_id = await db.add_alarm(await check_alarm(a), user["username"])
    return await db.get_alarm(new_id)


@app.put("/api/alarms/{alarm_id}")
async def change_alarm(alarm_id: int, a: Alarm, user=Depends(can_edit)):
    await alarm_or_404(alarm_id)
    await db.edit_alarm(alarm_id, await check_alarm(a), user["username"])
    return await db.get_alarm(alarm_id)


@app.post("/api/alarms/{alarm_id}/close")
async def close_alarm(alarm_id: int, user=Depends(can_edit)):
    a = await alarm_or_404(alarm_id)
    if not a["IS_OPEN"]:
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


# --- отчёт CSV и статистика ---

CSV_HEAD = ["№", "Номер PW/NTT", "Направление", "ТЦ", "Категория", "Тип сети", "Сетевой элемент, услуга",
            "Количество БС", "Тип оборудования", "Тип", "Описание", "Начало", "Окончание", "АКБ", "ГУ",
            "Длительность аварии", "Время перерыва связи", "Общее время простоя БС", "Уведомление (кому)",
            "Подробное описание"]


@app.get("/api/alarms-export.csv")
async def export_csv(date_from: date | None = None, date_to: date | None = None, only_open: bool = False,
                     napr: str | None = None, tehc: str | None = None, alarm_type: str | None = None,
                     q: str | None = None, user=Depends(get_user)):
    f = dict(date_from=date_from, date_to=date_to, only_open=only_open, napr=napr, tehc=tehc, alarm_type=alarm_type, q=q)
    rows = await db.list_alarms(f, 100000, order="BEGIN_TIME")

    out = io.StringIO()
    out.write("﻿")  # BOM, чтобы Excel понял кириллицу
    w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow(CSV_HEAD)
    for r in rows:
        line = [r["ID"]]
        for c in db.COLS:
            v = r[c]
            if c == "END_TIME" and v is None:
                v = "НВ"
            elif c == "NUMB_RBS" and v == 0:
                v = "С"
            elif c in ("BEGIN_TIME", "END_TIME") and v:
                v = v.replace("T", " ")
            line.append("" if v is None else v)
        w.writerow(line)

    name = f"alarms_{date_from or 'all'}_{date_to or date.today()}.csv"
    return StreamingResponse(iter([out.getvalue().encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/stats")
async def stats(date_from: date | None = None, date_to: date | None = None, user=Depends(get_user)):
    return await db.get_stats(dict(date_from=date_from, date_to=date_to))
