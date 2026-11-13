// Общая часть всех страниц: вход, запросы к API, шапка и меню, мелкие помощники.
// Пишем под Chrome 75: без ?. и ??, без replaceAll, без внешних библиотек и шрифтов
// (в ЦОУ нет интернета).

var Motiv = (function () {
    var KEY = 'motiv_session';

    function session() {
        try { return JSON.parse(localStorage.getItem(KEY)); } catch (e) { return null; }
    }
    function setSession(s) { localStorage.setItem(KEY, JSON.stringify(s)); }
    function logout() { localStorage.removeItem(KEY); location.href = 'login.html'; }

    function can(action) {
        var s = session();
        var role = s ? s.role : '';
        if (action === 'edit') return role === 'admin' || role === 'duty';
        if (action === 'admin') return role === 'admin';
        return true;
    }

    // Запрос к API с токеном. Ошибку сервера превращает в понятный текст.
    function api(method, path, body) {
        var s = session();
        var opts = { method: method, headers: {}, cache: 'no-store' };
        if (s) opts.headers.Authorization = 'Bearer ' + s.token;
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        return fetch('/api' + path, opts).then(function (r) {
            if (r.status === 401 && path !== '/login') { logout(); throw new Error('Сессия истекла'); }
            var isJson = (r.headers.get('Content-Type') || '').indexOf('json') >= 0;
            var data = isJson ? r.json() : r.blob();
            return data.then(function (d) {
                if (!r.ok) throw new Error(errorText(d, r.status));
                return d;
            });
        });
    }

    function errorText(d, status) {
        if (d && typeof d.detail === 'string') return d.detail;
        if (d && d.detail && d.detail.length) {
            return d.detail.map(function (e) { return (e.loc ? e.loc[e.loc.length - 1] + ': ' : '') + e.msg; }).join('; ');
        }
        if (status === 403) return 'Недостаточно прав';
        return 'Ошибка сервера (' + status + ')';
    }

    function esc(v) {
        return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function pad(n) { return (n < 10 ? '0' : '') + n; }

    // Секунды → «чч:мм:сс» (часы могут быть больше 24)
    function hms(sec) {
        sec = Math.max(0, Math.floor(sec));
        return pad(Math.floor(sec / 3600)) + ':' + pad(Math.floor(sec % 3600 / 60)) + ':' + pad(sec % 60);
    }
    // «чч:мм:сс» → секунды
    function toSec(text) {
        if (!text) return 0;
        var p = String(text).split(':');
        return (parseInt(p[0], 10) || 0) * 3600 + (parseInt(p[1], 10) || 0) * 60 + (parseInt(p[2], 10) || 0);
    }
    // Свободный ввод → «чч:мм:сс»: «1:30» → 01:30:00, «90» (минуты) → 01:30:00
    function normalizeHms(text) {
        text = String(text || '').trim().replace(/[.,\s]/g, ':');
        if (!text) return '';
        if (/^\d+$/.test(text)) return hms(parseInt(text, 10) * 60);
        var p = text.split(':');
        if (p.length > 3 || p.some(function (x) { return !/^\d+$/.test(x); })) return null;
        return hms(toSec(text));
    }

    // «2026-11-13T08:15:00» → «13.11.2026 08:15»
    function fmtDateTime(iso) {
        if (!iso) return '';
        var d = iso.split('T');
        var ymd = d[0].split('-');
        return ymd[2] + '.' + ymd[1] + '.' + ymd[0] + ' ' + (d[1] || '').slice(0, 5);
    }
    function parseLocal(iso) {           // время из БД — местное время ЦОУ
        var m = /^(\d+)-(\d+)-(\d+)T(\d+):(\d+)(?::(\d+))?/.exec(iso || '');
        return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) : null;
    }
    function toInputValue(date) {          // Date → значение для <input type="datetime-local">
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
            'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
    }
    function isoDate(date) {
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
    }

    function fmtDuration(sec) {             // для статистики: «3 ч 20 мин», «2 сут 4 ч»
        sec = Math.round(sec || 0);
        var d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
        if (d) return d + ' сут ' + h + ' ч';
        if (h) return h + ' ч ' + m + ' мин';
        return m + ' мин';
    }

    function toast(text, kind) {
        var box = document.getElementById('toasts');
        if (!box) {
            box = document.createElement('div');
            box.id = 'toasts';
            box.className = 'toasts';
            document.body.appendChild(box);
        }
        var el = document.createElement('div');
        el.className = 'toast toast-' + (kind || 'ok');
        el.textContent = text;
        box.appendChild(el);
        setTimeout(function () { el.className += ' is-leaving'; }, 3500);
        setTimeout(function () { box.removeChild(el); }, 3900);
    }

    var PAGES = [
        { href: 'index.html', title: 'Аварии' },
        { href: 'reports.html', title: 'Отчётность' },
        { href: 'stats.html', title: 'Статистика' },
        { href: 'dicts.html', title: 'Справочники', admin: true },
    ];

    // Проверяет вход и рисует шапку с меню. Возвращает сессию или null (тогда уже идёт переход на вход).
    function initPage(active) {
        var s = session();
        if (!s) { location.replace('login.html'); return null; }
        var nav = PAGES.filter(function (p) { return !p.admin || s.role === 'admin'; }).map(function (p) {
            return '<a href="' + p.href + '"' + (p.href === active ? ' class="active"' : '') + '>' + p.title + '</a>';
        }).join('');
        var header = document.createElement('header');
        header.className = 'topbar';
        header.innerHTML =
            '<a class="brand" href="index.html"><span class="brand-mark"></span>МОТИВ <small>Веб-отчётность</small></a>' +
            '<nav class="tabs">' + nav + '</nav>' +
            '<div class="topbar-right">' +
            '<span class="clock" id="clock"></span>' +
            '<span class="who"><b>' + esc(s.full_name || s.username) + '</b><span class="role role-' + esc(s.role) + '">' +
            esc(s.role_name) + '</span></span>' +
            '<button class="link-btn" id="logout">Выйти</button></div>';
        document.body.insertBefore(header, document.body.firstChild);
        document.getElementById('logout').onclick = logout;
        var tick = function () {
            var d = new Date();
            document.getElementById('clock').textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
        };
        tick();
        setInterval(tick, 1000);
        document.body.className += ' role-' + s.role;
        document.body.style.visibility = 'visible';
        return s;
    }

    // Загрузка CSV с токеном: обычной ссылкой нельзя — нужен заголовок авторизации
    function download(path, filename) {
        return api('GET', path).then(function (blob) {
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        });
    }

    return {
        session: session, setSession: setSession, logout: logout, can: can, api: api, esc: esc,
        pad: pad, hms: hms, toSec: toSec, normalizeHms: normalizeHms, fmtDateTime: fmtDateTime,
        parseLocal: parseLocal, toInputValue: toInputValue, isoDate: isoDate, fmtDuration: fmtDuration,
        toast: toast, initPage: initPage, download: download,
    };
})();
