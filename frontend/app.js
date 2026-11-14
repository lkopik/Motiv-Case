
try {
    if (localStorage.getItem('motiv_theme') === 'dark') document.documentElement.className += ' dark';
    document.documentElement.style.setProperty('--zoom', (parseInt(localStorage.getItem('motiv_scale'), 10) || 100) / 100);
    if ((parseInt(localStorage.getItem('motiv_scale'), 10) || 100) >= 125) document.documentElement.className += ' zoom-big';
} catch (e) {}

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

    function api(method, path, body) {
        var s = session();
        var opts = { method: method, headers: {}, cache: 'no-store' };
        if (s) opts.headers.Authorization = 'Bearer ' + s.token;
        if (body !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        return fetch('/api' + path, opts).catch(function () {
            outage('server');
            throw new Error(OUTAGE.server.text);
        }).then(function (r) {
            if (r.status === 401 && path !== '/login') { logout(); throw new Error('Сессия истекла'); }
            if (r.status === 502 || r.status === 504) { outage('server'); throw new Error(OUTAGE.server.text); }
            var isJson = (r.headers.get('Content-Type') || '').indexOf('json') >= 0;
            var data = isJson ? r.json() : r.blob();
            return data.then(function (d) {
                if (r.status === 503) { outage('db'); throw new Error(OUTAGE.db.text); }
                if (!r.ok) throw new Error(errorText(d, r.status));
                outage(null);
                return d;
            });
        });
    }

    function errorText(d, status) {
        if (d && typeof d.detail === 'string') return d.detail;
        if (d && d.detail && d.detail.length) {
            return d.detail.map(function (e) { return (e.loc ? e.loc[e.loc.length - 1] + ': ' : '') + e.msg; }).join('; ');
        }
        if (status === 403) return 'Недостаточно прав для этого действия';
        return 'Ошибка на сервере (код ' + status + '). Повторите действие; если не помогло — сообщите администратору.';
    }

    var OUTAGE = {
        db: { title: 'Нет связи с базой данных',
              text: 'Данные сейчас не сохраняются и не загружаются. Ничего не потеряно — повторите действие через минуту. ' +
                    'Если плашка не исчезает больше 5 минут, сообщите администратору.' },
        server: { title: 'Сервер не отвечает',
                  text: 'Нет связи с сервером. Проверьте сеть; если с сетью всё в порядке — сообщите администратору.' }
    };

    function outage(kind) {
        var el = document.getElementById('outage');
        if (!kind) { if (el) el.hidden = true; return; }
        if (!el) {
            el = document.createElement('div');
            el.id = 'outage';
            el.className = 'outage';
            var top = document.querySelector('.topbar');
            document.body.insertBefore(el, top ? top.nextSibling : document.body.firstChild);
        }
        el.innerHTML = '<b>' + OUTAGE[kind].title + '</b><span>' + OUTAGE[kind].text + '</span>' +
            '<button type="button" class="btn btn-sm" onclick="location.reload()">Проверить снова</button>';
        el.hidden = false;
    }

    function esc(v) {
        return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function pad(n) { return (n < 10 ? '0' : '') + n; }

    function hms(sec) {
        sec = Math.max(0, Math.floor(sec));
        return pad(Math.floor(sec / 3600)) + ':' + pad(Math.floor(sec % 3600 / 60)) + ':' + pad(sec % 60);
    }
    function toSec(text) {
        if (!text) return 0;
        var p = String(text).split(':');
        return (parseInt(p[0], 10) || 0) * 3600 + (parseInt(p[1], 10) || 0) * 60 + (parseInt(p[2], 10) || 0);
    }
    function normalizeHms(text) {
        text = String(text || '').trim().replace(/[.,\s]/g, ':');
        if (!text) return '';
        if (/^\d+$/.test(text)) return hms(parseInt(text, 10) * 60);
        var p = text.split(':');
        if (p.length > 3 || p.some(function (x) { return !/^\d+$/.test(x); })) return null;
        return hms(toSec(text));
    }

    function fmtDateTime(iso) {
        if (!iso) return '';
        var d = iso.split('T');
        var ymd = d[0].split('-');
        return ymd[2] + '.' + ymd[1] + '.' + ymd[0] + ' ' + (d[1] || '').slice(0, 5);
    }
    function parseLocal(iso) {
        var m = /^(\d+)-(\d+)-(\d+)T(\d+):(\d+)(?::(\d+))?/.exec(iso || '');
        return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) : null;
    }
    function toInputValue(date) {
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
            'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
    }
    function isoDate(date) {
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate());
    }

    function fmtDuration(sec) {
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
        { href: 'reports.html', title: 'Архив' },
        { href: 'stats.html', title: 'Статистика' },
        { href: 'map.html', title: 'Карта' },
        { href: 'dicts.html', title: 'Списки', admin: true },
        { href: 'help.html', title: 'Справка' },
    ];

    function initPage(active) {
        var s = session();
        if (!s) { location.replace('login.html'); return null; }
        var nav = PAGES.filter(function (p) { return !p.admin || s.role === 'admin'; }).map(function (p) {
            return '<a href="' + p.href + '"' + (p.href === active ? ' class="active"' : '') + '>' + p.title + '</a>';
        }).join('');
        var name = s.full_name && s.full_name !== s.role_name ? s.full_name : s.username;
        var header = document.createElement('header');
        header.className = 'topbar';
        header.innerHTML =
            '<a class="brand" href="index.html"><img src="logo.png" alt=""><span>мотив</span><em>ЦОУ</em></a>' +
            '<nav class="tabs">' + nav + '</nav>' +
            '<div class="topbar-right">' +
            '<span class="who" title="' + esc(s.role_name) + '">' + esc(name) + ' <i class="role role-' + esc(s.role) + '">' +
            esc(s.role_name) + '</i></span>' +
            '<span class="scale"><button class="link-btn" id="scale-down" title="Мельче">A−</button>' +
            '<b id="scale-value"></b><button class="link-btn" id="scale-up" title="Крупнее">A+</button></span>' +
            '<button class="link-btn" id="theme"></button>' +
            '<button class="link-btn" id="logout" title="Выйти">Выход</button></div>';
        document.body.insertBefore(header, document.body.firstChild);
        document.getElementById('logout').onclick = logout;
        var SCALES = [90, 100, 110, 125, 140];
        var scale = parseInt(localStorage.getItem('motiv_scale'), 10) || 100;
        var setScale = function (value) {
            scale = value;
            document.documentElement.style.setProperty('--zoom', value / 100);
            document.documentElement.classList.toggle('zoom-big', value >= 125);
            document.getElementById('scale-value').textContent = value + '%';
            try { localStorage.setItem('motiv_scale', value); } catch (e) {}
            window.dispatchEvent(new Event('resize'));
        };
        setScale(scale);
        document.getElementById('scale-down').onclick = function () {
            var i = SCALES.indexOf(scale);
            if (i > 0) setScale(SCALES[i - 1]);
        };
        document.getElementById('scale-up').onclick = function () {
            var i = SCALES.indexOf(scale);
            if (i < SCALES.length - 1) setScale(SCALES[i + 1]);
        };
        var themeBtn = document.getElementById('theme');
        var setThemeText = function () {
            themeBtn.textContent = document.documentElement.classList.contains('dark') ? 'Светлая тема' : 'Тёмная тема';
        };
        setThemeText();
        themeBtn.onclick = function () {
            var dark = document.documentElement.classList.toggle('dark');
            try { localStorage.setItem('motiv_theme', dark ? 'dark' : 'light'); } catch (e) {}
            setThemeText();
        };

        var bar = document.createElement('footer');
        bar.className = 'statusbar';
        bar.innerHTML = '<span id="sb-db">БД: …</span><span id="sb-count"></span>' +
            '<span class="sb-keys">Ctrl+Enter — сохранить · Esc — закрыть окно</span><span id="clock"></span>';
        document.body.appendChild(bar);

        var tick = function () {
            var d = new Date();
            document.getElementById('clock').textContent = pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() +
                ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
        };
        tick();
        setInterval(tick, 1000);
        var ping = function () {
            fetch('/api/health', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (h) {
                var ok = h.database === 'ok';
                var el = document.getElementById('sb-db');
                el.textContent = ok ? 'БД: подключена' : 'БД: нет связи';
                el.className = ok ? 'ok' : 'bad';
                document.getElementById('sb-count').textContent = ok ? 'записей в журнале: ' + h.alarms : '';
                outage(ok ? null : 'db');
            }).catch(function () {
                document.getElementById('sb-db').textContent = 'сервер недоступен';
                document.getElementById('sb-db').className = 'bad';
                outage('server');
            });
        };
        ping();
        setInterval(ping, 30000);
        document.body.className += ' role-' + s.role;
        document.body.style.visibility = 'visible';
        return s;
    }

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
        toast: toast, initPage: initPage, download: download, outage: outage,
    };
})();
