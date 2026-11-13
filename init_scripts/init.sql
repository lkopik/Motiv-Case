SET NAMES utf8mb4;

--
-- Журнал аварий. Одна строка = одна авария.
--

CREATE TABLE IF NOT EXISTS ALARMS (
    ID              INT AUTO_INCREMENT PRIMARY KEY,
    PW              VARCHAR(450),   -- 1  Номер PW/NTT (ссылка в CRM)
    NAPR            VARCHAR(450),   -- 2  Направление: ХМЯН, СВН, ЮЗН, Вся сеть
    TEHC            VARCHAR(450),   -- 3  ТЦ: НБР, АСБ, ИРБ, ...
    KATEG           TINYINT,        -- 4  Категория: 1, 2, 3
    NETW_TYPE       VARCHAR(450),   -- 5  Тип сети: GSM, LTE, LTE/GSM
    SERV_ELEM       VARCHAR(450),   -- 6  Сетевой элемент, услуга (адреса БС)
    NUMB_RBS        INT,            -- 7  Количество БС (0 = «С», сектор)
    EQIP_TYPE       VARCHAR(450),   -- 8  Тип оборудования
    ALARM_TYPE      VARCHAR(450),   -- 9  Тип: РРС, ССС, ЭЛ, RBS, МСПД, ТМ, ОПС, ПР, АВР, Аренда
    DESCR           VARCHAR(450),   -- 10 Описание
    BEGIN_TIME      DATETIME,       -- 11 Начало
    END_TIME        DATETIME,       -- 12 Окончание; '0000-00-00 00:00:00' = НВ (настоящее время)
    AKB             TIME,           -- 13 Работа от АКБ
    DGU             TIME,           -- 14 Работа от генератора (ГУ)
    LENGHT          VARCHAR(450),   -- 15 Длительность аварии — считается автоматически
    PROSTOY         TIME,           -- 16 Время перерыва связи (1 БС)
    COMMON_PROSTOY  TIME,           -- 17 Общий простой = PROSTOY * NUMB_RBS — автоматически
    ALARM_WHO       VARCHAR(450),   -- 18 Уведомление об аварии (кому)
    DESC_NOTICE     VARCHAR(450)    -- 19 Подробное описание
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

--
-- Пользователи и роли: admin — всё, duty (дежурный) — вносит
-- и правит аварии, engineer — только просмотр. Пароль хранится как SHA-256.
--

CREATE TABLE IF NOT EXISTS USERS (
    ID             INT AUTO_INCREMENT PRIMARY KEY,
    USERNAME       VARCHAR(64) NOT NULL UNIQUE,
    PASSWORD_HASH  CHAR(64) NOT NULL,
    ROLE           ENUM('admin', 'duty', 'engineer') NOT NULL,
    FULL_NAME      VARCHAR(128)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO USERS (USERNAME, PASSWORD_HASH, ROLE, FULL_NAME) VALUES
    ('admin',    SHA2('admin123', 256),    'admin',    'Администратор'),
    ('duty',     SHA2('duty123', 256),     'duty',     'Дежурный'),
    ('engineer', SHA2('engineer123', 256), 'engineer', 'Инженер');

-- Пара примеров, чтобы Некит мог показать первый запуск
INSERT INTO ALARMS (PW, NAPR, TEHC, KATEG, NETW_TYPE, SERV_ELEM, NUMB_RBS, EQIP_TYPE, ALARM_TYPE,
                    DESCR, BEGIN_TIME, END_TIME, AKB, DGU, LENGHT, PROSTOY, COMMON_PROSTOY,
                    ALARM_WHO, DESC_NOTICE) VALUES
    ('NTT-104512', 'СВН', 'ЕКБ', 2, 'LTE/GSM', 'г. Екатеринбург, ул. Малышева, 36', 3, 'Huawei BTS3900',
     'ЭЛ', 'Отключение промсети', '2026-11-12 08:15:00', '2026-11-12 11:40:00', '01:30:00', '01:55:00',
     '03:25:00', '00:40:00', '02:00:00', 'Начальник смены ЦОУ, ТЦ ЕКБ', 'Работа от АКБ, затем от ДГУ до восстановления питания.'),
    ('PW-88213', 'ХМЯН', 'СЛХ', 1, 'LTE', 'г. Салехард, ул. Республики, 72', 0, 'Ericsson RBS 6000',
     'РРС', 'Обрыв РРЛ', '2026-11-13 06:05:00', '0000-00-00 00:00:00', NULL, NULL,
     NULL, '00:30:00', '00:00:00', 'Дежурный инженер ТЦ СЛХ', 'Авария продолжается (НВ), сектор без связи.');
