// Форма аварии (19 полей ТЗ). Одна и та же форма — для новой аварии и для правки строки в отчётности.
//   AlarmForm.create(container, { alarm, readonly, onSaved, onCancel }) → объект с .fill(alarm), .reset()

var AlarmForm = (function () {
    var M = Motiv;
    var cache = {};   // справочники и подсказки грузим один раз на страницу

    function loadRefs() {
        if (!cache.refs) {
            cache.refs = Promise.all([M.api('GET', '/dicts'), M.api('GET', '/suggest')]).then(function (r) {
                return { dicts: r[0], suggest: r[1] };
            });
        }
        return cache.refs;
    }

    function options(values, withEmpty) {
        return (withEmpty ? '<option value="">—</option>' : '') + values.map(function (v) {
            return '<option value="' + M.esc(v) + '">' + M.esc(v) + '</option>';
        }).join('');
    }
    function chips(name, values) {      // выбор из 2–4 вариантов — кнопками, а не списком
        return '<div class="chips" data-name="' + name + '">' + values.map(function (v) {
            return '<label><input type="radio" name="' + name + '" value="' + M.esc(v) + '"><span>' + M.esc(v) + '</span></label>';
        }).join('') + '</div>';
    }
    function datalist(id, values) {
        return '<datalist id="' + id + '">' + values.map(function (v) {
            return '<option value="' + M.esc(v) + '">';
        }).join('') + '</datalist>';
    }

    function template(uid, refs) {
        var d = refs.dicts, s = refs.suggest;
        return '' +
        '<form class="alarm-form" novalidate autocomplete="off">' +
        '<div class="form-error" hidden></div>' +

        '<fieldset><legend>Что и где</legend><div class="grid g-6">' +
          '<label class="f c-2"><span>1. Номер PW / NTT</span><input name="PW" placeholder="NTT-123456 или ссылка — можно пусто"></label>' +
          '<label class="f"><span>2. Направление</span><select name="NAPR">' + options(d.napr, true) + '</select></label>' +
          '<label class="f"><span>3. ТЦ</span><select name="TEHC">' + options(d.tehc, true) + '</select></label>' +
          '<div class="f"><span>4. Категория</span>' + chips('KATEG', d.kateg) + '</div>' +
          '<div class="f"><span>5. Тип сети</span>' + chips('NETW_TYPE', d.netw_type) + '</div>' +

          '<label class="f c-2"><span>6. Сетевой элемент, услуга <em class="hint" data-hint="autofill"></em></span>' +
            '<input name="SERV_ELEM" list="serv-' + uid + '" placeholder="Адрес или адреса БС — начните вводить, будут подсказки"></label>' +
          '<div class="f c-2"><span>7. Количество БС</span><div class="bs-count">' +
            '<input name="NUMB_RBS" type="number" min="1" max="10000" placeholder="1">' +
            '<label class="check"><input type="checkbox" name="SECTOR"> С (сектор)</label></div></div>' +
          '<label class="f c-2"><span>8. Тип оборудования</span><input name="EQIP_TYPE" list="eqip-' + uid + '"></label>' +

          '<label class="f"><span>9. Тип аварии</span><select name="ALARM_TYPE">' + options(d.alarm_type, true) + '</select></label>' +
          '<label class="f c-5"><span>10. Описание</span><input name="DESCR" list="descr-' + uid + '" placeholder="Кратко: что случилось"></label>' +
        '</div></fieldset>' +

        '<fieldset><legend>Время</legend><div class="grid g-6">' +
          '<div class="f c-2"><span>11. Начало</span><div class="with-btn">' +
            '<input name="BEGIN_TIME" type="datetime-local" required><button type="button" class="btn-mini" data-now="BEGIN_TIME">Сейчас</button></div></div>' +
          '<div class="f c-2"><span>12. Окончание</span><div class="with-btn">' +
            '<input name="END_TIME" type="datetime-local"><button type="button" class="btn-mini" data-now="END_TIME">Сейчас</button></div>' +
            '<label class="check nv"><input type="checkbox" name="NV"> НВ — авария продолжается</label></div>' +
          '<label class="f"><span>13. АКБ</span><input name="AKB" class="hms" placeholder="чч:мм:сс"></label>' +
          '<label class="f"><span>14. ГУ</span><input name="DGU" class="hms" placeholder="чч:мм:сс"></label>' +

          '<label class="f c-2"><span>16. Время перерыва связи (1 БС)</span><input name="PROSTOY" class="hms" placeholder="чч:мм:сс или минуты"></label>' +
          '<div class="calc c-2"><span>15. Длительность аварии</span><b data-out="LENGHT">—</b><small data-out="LENGHT_NOTE">окончание − начало</small></div>' +
          '<div class="calc c-2"><span>17. Общее время простоя БС</span><b data-out="COMMON_PROSTOY">—</b><small data-out="COMMON_NOTE">перерыв × количество БС</small></div>' +
        '</div></fieldset>' +

        '<fieldset><legend>Уведомление</legend><div class="grid g-6">' +
          '<label class="f c-2"><span>18. Уведомление об аварии (кому)</span><input name="ALARM_WHO" list="who-' + uid + '"></label>' +
          '<label class="f c-4"><span>19. Подробное описание</span><textarea name="DESC_NOTICE" rows="2"></textarea></label>' +
        '</div></fieldset>' +

        '<div class="form-actions">' +
          '<button type="submit" class="btn btn-primary" data-role="save">Сохранить</button>' +
          '<button type="button" class="btn" data-role="cancel">Отмена</button>' +
          '<span class="kbd-hint">Ctrl + Enter — сохранить</span>' +
          '<span class="audit" data-out="AUDIT"></span>' +
        '</div>' +
        '</form>' +
        datalist('serv-' + uid, s.SERV_ELEM) + datalist('eqip-' + uid, s.EQIP_TYPE) +
        datalist('descr-' + uid, s.DESCR) + datalist('who-' + uid, s.ALARM_WHO);
    }

    var counter = 0;

    function create(container, opts) {
        opts = opts || {};
        var uid = ++counter;
        var api = { ready: null };

        api.ready = loadRefs().then(function (refs) {
            container.innerHTML = template(uid, refs);
            var form = container.querySelector('form');
            var el = function (name) { return form.elements[name]; };
            var out = function (name) { return form.querySelector('[data-out="' + name + '"]'); };
            var current = null;    // авария, которую правим (null — новая)

            function radio(name, value) {
                var inputs = form.querySelectorAll('input[name="' + name + '"]');
                for (var i = 0; i < inputs.length; i++) {
                    if (value === undefined) { if (inputs[i].checked) return inputs[i].value; }
                    else inputs[i].checked = String(inputs[i].value) === String(value);
                }
                return value === undefined ? '' : undefined;
            }

            function setNv(on) {
                el('NV').checked = on;
                el('END_TIME').disabled = on;
                if (on) el('END_TIME').value = '';
                recalc();
            }

            function setSector(on) {
                el('SECTOR').checked = on;
                el('NUMB_RBS').disabled = on;
                if (on) el('NUMB_RBS').value = '';
                recalc();
            }

            // Поля 15 и 17 считаются сразу при вводе — по тем же правилам, что и на сервере
            function recalc() {
                var begin = M.parseLocal(el('BEGIN_TIME').value);
                var end = el('NV').checked ? new Date() : M.parseLocal(el('END_TIME').value);
                var len = out('LENGHT');
                if (begin && end) {
                    var sec = (end - begin) / 1000;
                    len.textContent = sec < 0 ? 'окончание раньше начала' : M.hms(sec);
                    len.className = sec < 0 ? 'bad' : (el('NV').checked ? 'live' : '');
                } else {
                    len.textContent = '—';
                    len.className = '';
                }
                out('LENGHT_NOTE').textContent = el('NV').checked ? 'идёт сейчас: текущее время − начало' : 'окончание − начало';

                var p = M.normalizeHms(el('PROSTOY').value);
                var n = el('SECTOR').checked ? 1 : (parseInt(el('NUMB_RBS').value, 10) || 1);
                out('COMMON_PROSTOY').textContent = p ? M.hms(Math.min(M.toSec(p) * n, 3020399)) : '—';
                out('COMMON_NOTE').textContent = p
                    ? p + ' × ' + (el('SECTOR').checked ? '1 (сектор)' : n + ' БС')
                    : 'перерыв × количество БС';
            }

            function showError(text) {
                var box = form.querySelector('.form-error');
                box.textContent = text || '';
                box.hidden = !text;
                if (text) box.scrollIntoView({ block: 'nearest' });
            }

            function fill(a) {
                current = a && a.ID ? a : null;
                form.reset();
                showError('');
                a = a || {};
                ['PW', 'NAPR', 'TEHC', 'SERV_ELEM', 'EQIP_TYPE', 'ALARM_TYPE', 'DESCR', 'AKB', 'DGU',
                 'PROSTOY', 'ALARM_WHO', 'DESC_NOTICE'].forEach(function (f) { el(f).value = a[f] || ''; });
                radio('KATEG', a.KATEG === undefined || a.KATEG === null ? '' : a.KATEG);
                radio('NETW_TYPE', a.NETW_TYPE || '');
                el('BEGIN_TIME').value = a.BEGIN_TIME ? a.BEGIN_TIME.slice(0, 16) : M.toInputValue(new Date());
                el('END_TIME').value = a.END_TIME ? a.END_TIME.slice(0, 16) : '';
                setSector(a.NUMB_RBS === 0);
                if (a.NUMB_RBS) el('NUMB_RBS').value = a.NUMB_RBS;
                setNv(!a.ID || !a.END_TIME);
                out('AUDIT').textContent = current
                    ? 'Внёс: ' + (current.CREATED_BY || '—') + (current.UPDATED_BY ? ', изменил: ' + current.UPDATED_BY + ' ' + M.fmtDateTime(current.UPDATED_AT) : '')
                    : '';
                form.querySelector('[data-role="save"]').textContent = current ? 'Сохранить изменения' : 'Зарегистрировать аварию';
                form.querySelector('[data-hint="autofill"]').textContent = '';
                recalc();
            }

            function collect() {
                var data = {};
                ['PW', 'NAPR', 'TEHC', 'SERV_ELEM', 'EQIP_TYPE', 'ALARM_TYPE', 'DESCR', 'ALARM_WHO', 'DESC_NOTICE']
                    .forEach(function (f) { data[f] = el(f).value.trim() || null; });
                var k = radio('KATEG');
                data.KATEG = k ? parseInt(k, 10) : null;
                data.NETW_TYPE = radio('NETW_TYPE') || null;
                data.NUMB_RBS = el('SECTOR').checked ? 0 : (el('NUMB_RBS').value ? parseInt(el('NUMB_RBS').value, 10) : null);
                data.BEGIN_TIME = el('BEGIN_TIME').value || null;
                data.END_TIME = el('NV').checked ? null : (el('END_TIME').value || null);
                var bad = [];
                ['AKB', 'DGU', 'PROSTOY'].forEach(function (f) {
                    var v = M.normalizeHms(el(f).value);
                    if (v === null) bad.push(f);
                    data[f] = v || null;
                });
                if (!data.BEGIN_TIME) return 'Укажите начало аварии';
                if (bad.length) return 'Время работы и перерыва — в формате чч:мм:сс (или числом минут)';
                if (!el('NV').checked && !data.END_TIME) return 'Укажите окончание или отметьте «НВ»';
                if (data.END_TIME && data.END_TIME < data.BEGIN_TIME) return 'Окончание раньше начала';
                return data;
            }

            function save(e) {
                if (e) e.preventDefault();
                var data = collect();
                if (typeof data === 'string') { showError(data); return; }
                var btn = form.querySelector('[data-role="save"]');
                btn.disabled = true;
                var req = current ? M.api('PUT', '/alarms/' + current.ID, data) : M.api('POST', '/alarms', data);
                req.then(function (saved) {
                    cache.refs = null;   // новые значения попадут в подсказки
                    M.toast(current ? 'Изменения сохранены' : 'Авария № ' + saved.ID + ' зарегистрирована');
                    if (opts.onSaved) opts.onSaved(saved, !current);
                    if (!current) fill(null);
                }).catch(function (err) { showError(err.message); })
                  .then(function () { btn.disabled = false; });
            }

            // Подсказка дежурному: выбрали элемент из прошлых аварий — подставляем ТЦ, сеть, оборудование
            function autofill() {
                var v = el('SERV_ELEM').value.trim();
                if (!v || current) return;
                M.api('GET', '/autofill?serv_elem=' + encodeURIComponent(v)).then(function (a) {
                    if (!a || !a.TEHC) return;
                    var filled = [];
                    if (!el('NAPR').value && a.NAPR) { el('NAPR').value = a.NAPR; filled.push('направление'); }
                    if (!el('TEHC').value && a.TEHC) { el('TEHC').value = a.TEHC; filled.push('ТЦ'); }
                    if (!radio('NETW_TYPE') && a.NETW_TYPE) { radio('NETW_TYPE', a.NETW_TYPE); filled.push('сеть'); }
                    if (!el('EQIP_TYPE').value && a.EQIP_TYPE) { el('EQIP_TYPE').value = a.EQIP_TYPE; filled.push('оборудование'); }
                    if (!el('NUMB_RBS').value && !el('SECTOR').checked && a.NUMB_RBS !== null) {
                        if (a.NUMB_RBS === 0) setSector(true); else el('NUMB_RBS').value = a.NUMB_RBS;
                        filled.push('кол-во БС');
                    }
                    if (!el('ALARM_WHO').value && a.ALARM_WHO) { el('ALARM_WHO').value = a.ALARM_WHO; filled.push('кому'); }
                    if (filled.length) {
                        form.querySelector('[data-hint="autofill"]').textContent = '↳ по прошлой аварии: ' + filled.join(', ');
                        recalc();
                    }
                });
            }

            form.addEventListener('submit', save);
            form.addEventListener('input', recalc);
            form.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) save(e);
            });
            el('NV').onchange = function () { setNv(el('NV').checked); };
            el('SECTOR').onchange = function () { setSector(el('SECTOR').checked); };
            el('SERV_ELEM').onchange = autofill;
            Array.prototype.forEach.call(form.querySelectorAll('.hms'), function (input) {
                input.onblur = function () {
                    var v = M.normalizeHms(input.value);
                    if (v) input.value = v;
                    input.classList.toggle('invalid', v === null);
                    recalc();
                };
            });
            Array.prototype.forEach.call(form.querySelectorAll('[data-now]'), function (btn) {
                btn.onclick = function () {
                    var name = btn.getAttribute('data-now');
                    if (name === 'END_TIME') setNv(false);
                    el(name).value = M.toInputValue(new Date());
                    recalc();
                };
            });
            form.querySelector('[data-role="cancel"]').onclick = function () {
                if (opts.onCancel) opts.onCancel(); else fill(null);
            };

            if (opts.readonly) {
                Array.prototype.forEach.call(form.elements, function (x) { x.disabled = true; });
                form.querySelector('[data-role="cancel"]').disabled = false;
                form.querySelector('[data-role="cancel"]').textContent = 'Закрыть';
                form.querySelector('[data-role="save"]').style.display = 'none';
                form.querySelector('.kbd-hint').style.display = 'none';
                form.className += ' is-readonly';
            }
            setInterval(function () { if (el('NV').checked) recalc(); }, 1000);

            api.fill = function (a) {
                fill(a);
                if (opts.readonly) {
                    Array.prototype.forEach.call(form.elements, function (x) { x.disabled = x.getAttribute('data-role') !== 'cancel'; });
                }
            };
            api.reset = function () { fill(null); };
            api.fill(opts.alarm || null);
            return api;
        });
        return api;
    }

    return { create: create };
})();
