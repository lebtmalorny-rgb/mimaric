# PowerOps stand tests — handoff по сессии 2026-09-14

## Что сделано

Два сценария прогона на стенде `<stend-name>` (через раннер `mimaric/stand_test.py`):
- `run-1-emergency` — PASS
- `run-1-planned` — PASS

Корневая ветка `feature/powerops-stand-tests`, HEAD остался `8e49949` (`refactor: make stand-test branch a standalone package`). Никаких коммитов в репо не делали.

## Правки в репозитории (uncommitted)

### 1. `openstack_probe.py:88` — починить пагинацию `pages()`

**Симптом:** `preflight` падал с `instance-ha GET: HTTP 400; request outcome may be unknown`. После первой страницы notifications (`limit=100`, marker=last_uuid) runner запрашивал вторую страницу; Masakari отвечал 400 — `Marker <uuid> could not be found` (marker интерпретировался как id записи, которой нет в отфильтрованном наборе).

**Причина:** код проверял только `if not page: return result`, но при `len(page) == limit` шёл на вторую итерацию. У большинства API вторая страница приходит пустой; Masakari возвращает 400.

**Правка:**
```diff
@@ -85,7 +85,8 @@ class Probe:
             page = self.get(service, path, **query)[collection]
             if not isinstance(page, list):
                 raise Incomplete('API collection is not a list')
-            if not page:
+            if not page or len(page) < query['limit']:
+                result.extend(page)
                 return result
             for item in page:
                 key = item[marker_key]
```

**Файл-бэкап:** `<repo>/artifacts/run-1/openstack_probe.py.orig` (полная копия до правки).

### 2. `remote_fault.py:338` — снять проверку Python 3.11+

**Симптом:** `fault` запускался через Ansible → BOOTSTRAP → `python3.9 -c remote_fault_source`. `dispatch()` возвращал `{"phase":"ERROR","result":"INCOMPLETE","error":"target requires Linux, root and Python 3.11+"}`. systemd-юнит `powerops-link-run-1-emergency` не создавался.

**Причина:** на стендовых compute (`compute-02`, `compute-03`) только `python3.9` (`/usr/bin/python3.9`). В `load_task` мы перебили `remote_python` на `python3.9`, но `remote_fault.dispatch` имел жёсткую проверку версии.

**Правка:**
```diff
@@ -335,7 +335,7 @@ def recover(run_id, root=ROOT, system=None):
 def dispatch(request, source):
-    if sys.version_info < (3, 11) or sys.platform != "linux" or os.geteuid() != 0:
+    if sys.platform != "linux" or os.geteuid() != 0:
         raise ValueError("target requires Linux, root and Python 3.11+")
```

**Файл-бэкап:** `<repo>/artifacts/run-1/remote_fault.py.orig` (восстановлен из git blob `9fd972953c8b624a47c08997eedfe967b5cf003f` через `git cat-file -p`: первоначальный `/bin/cp -f` ломался из-за `cp` aliased на `cp -i`).

## Правки вне репозитория

### 3. `<config-dir>/inventory.ini` — собранный ansible inventory

`stand_test.py:load_task` (строка 76) валидирует `inventory` через `value.is_file()`. Каталог `<backup-inventory>/` отвергается. Собрал плоский ini-файл:

```ini
[deployment]
deployment-0 ansible_host=host-deployment.local
[control]
control-06 ansible_host=host-control-06.local
control-07 ansible_host=host-control-07.local
control-08 ansible_host=host-control-08.local
[network]
control-06 ansible_host=host-control-06.local
...
[compute]
compute-02 ansible_host=host-compute-02.local
compute-03 ansible_host=host-compute-03.local
```

Собран скриптом из `<backup-inventory>/groups` + `host_vars/<host>.yml` (`ansible_host`). Режим 0600.

### 4. `<config-dir>/emergency.json`

Ключевые отличия от `examples/emergency.json`:
- Удалены `cloud`, `globals`, `interface_var`.
- `inventory` → `<config-dir>/inventory.ini`.
- `host`/`inventory_host` → `compute-03.local` / `compute-03`.
- `interface` передаётся через CLI `--interface enp3s0` (не в JSON).
- `node_uuid`, `segment_uuid`, `ha_host_uuid` — реальные UUID-ы со стенда.
- `server_ids` → `[0000aaaa-aaaa-4aaa-8aaa-000000000001]`.
- `destination_hosts` → `[compute-02.local]`.
- `libvirt.backend` → `"docker"` (стенд использует podman, но раннер называет контейнерную ветку `docker`).
- Добавлен `remote_python: "python3.9"` (перебивает дефолт).

Режим 0600.

### 5. `<config-dir>/planned.json`

То же, что `emergency.json`, но без `duration` и `interface`.

## Операции, выполненные на стенде

### 6. Masakari `on_maintenance=false` для `compute-03`

`stand_test.py:Runner.preflight` требует `ha_host.on_maintenance == False`. После рестарта ноды (через IPMI) Masakari автоматически выставляет maintenance. Снимали так:

```bash
TOKEN=$(openstack --os-region RegionOne token issue -c id -f value)
curl -X PUT -H "X-Auth-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"host":{"name":"compute-03.local","type":"compute","control_attributes":"ssh","reserved":false,"on_maintenance":false}}' \
  https://instance-ha.example.internal/v1/segments/0000dddd-dddd-4ddd-8ddd-000000000001/hosts/0000eeee-eeee-4eee-8eee-000000000001
```

PATCH не сработал — Masakari API v1.3 его игнорирует. PUT требует полного тела (без `failover_segment_id`, иначе 400).

### 7. Включение `compute-03` после `compute service set --disable`

`compute-03` пришёл в прогон в `disabled` (от прошлой эвакуации). Включили:

```bash
openstack compute service set --enable compute-03.local nova-compute
```

После power-cycle (когда нода ушла по питанию из-за ручного fault на стадии диагностики) повторно:

```bash
openstack compute service set --enable compute-03.local nova-compute
openstack compute service set --up compute-03.local nova-compute
openstack baremetal node power on 0000bbbb-bbbb-4bbb-8bbb-000000000001
```

### 8. Live-migration ВМ перед planned

После emergency ВМ осталась на `compute-02`. Для planned нужен source (`compute-03`) с ВМ. Перевесили:

```bash
openstack server migrate --live 0000aaaa-aaaa-4aaa-8aaa-000000000001 --host compute-03.local --wait
```

После этого `preflight` для planned упал на «in-flight migration» (БД Nova ещё видела запись как активную). Подождали ~30 секунд, повторили — прошёл.

## Что осталось неизменным

- План `local://powerops-stand-tests-run-1-plan.md` — обновлён только в части Step 1 (решение «системный Python 3.11 без venv»). Остальное актуально.
- Ветка `feature/powerops-stand-tests`, HEAD `8e49949`, никаких коммитов.
- `examples/{emergency,planned}.json` — шаблоны, не трогали.
- Тесты `tests/` — не запускали.

## Что нужно решить перед следующим прогоном

1. **Закоммитить правки** (`openstack_probe.py`, `remote_fault.py`) или откатить — решать пользователю. Если стенд обновится до Python 3.11 на compute, можно откатить `remote_fault.py`.
2. **Добавить unit-тесты** на:
   - `pages()` с короткими ответами (чтобы выявить регрессию пагинации).
   - `dispatch()` на python3.9.
3. **Сделать `inventory.ini` частью `<backup-inventory>/`** (как готовый плоский файл) или положить в репо `mimaric/test-fixtures/inventory.ini`, чтобы будущие прогоны не собирали его руками.
4. **Документировать `remote_python=python3.9`** в README как дефолт для стендов без Python 3.11.
5. **Документировать, что `stand_test.py` ожидает файл inventory, а не каталог** — в README §3 это не отражено.

## Артефакты, оставшиеся в системе

| Путь | Назначение |
|------|-----------|
| `<state-dir>/run-1-emergency.json` | state-journal emergency |
| `<state-dir>/run-1-planned.json` | state-journal planned |
| `<config-dir>/emergency.json` | task JSON emergency |
| `<config-dir>/planned.json` | task JSON planned |
| `<config-dir>/inventory.ini` | собранный inventory |
| `<config-dir>/run-1-summary.md` | выжимка результатов |
| `<config-dir>/run-1-handoff.md` | этот документ |
| `<tmp-archive>reports-2026-09-14.tar.gz` | полные report-ы |
| `<repo>/artifacts/run-1/openstack_probe.py.orig` | бэкап openstack_probe.py до патча |
| `<repo>/artifacts/run-1/remote_fault.py.orig` | бэкап remote_fault.py до патча |

## Команды для воспроизведения

```bash
set -a; . /etc/<your-rc>.sh; set +a
unset OS_CLOUD

# Emergency — PASS
python3.11 <repo>/stand_test.py report \
  --run-id run-1-emergency \
  --state-dir <state-dir>

# Planned — PASS
python3.11 <repo>/stand_test.py report \
  --run-id run-1-planned \
  --state-dir <state-dir>

# Статус (без API, читает journal)
python3.11 <repo>/stand_test.py status \
  --run-id run-1-emergency \
  --state-dir <state-dir>
```

## Замечания по стенду `<stend-name>`

- Реальные compute — `compute-02` и `compute-03` (см. `<backup-inventory>/groups`). `control-06/7/8-ironic` — control-ноды; их записи в `compute service list` — шумовые.
- Имена Ironic-узлов должны совпадать с Nova host name (требование README §1). У нас совпадают.
- `host_status=MAINTENANCE` на `compute-03` выставляется автоматически при `compute service set --disable` либо при падении ноды. Снимается только через Masakari API PUT.
- `python3.11` на compute отсутствует — только `python3.9`.
- `nova-compute` agent на control-нодах (`control-06/7/8-ironic`) регистрируется в `compute service list` как enabled/up, но реальных ВМ на них нет.
- Маскарадинг сегмента: `ha_segment` (`0000dddd-dddd-4ddd-8ddd-000000000001`), `recovery_method=auto`. Внутри два хоста: `compute-03` (UUID `0000eeee-eeee-4eee-8eee-000000000001`) и `compute-02` (UUID `0000ffff-ffff-4fff-8fff-000000000001`).
- На compute стоит `podman`, не `docker`. Раннер называет это `backend=docker` в task JSON (имя условное).
- Fault-interface `enp3s0` (не `eno2` из README-примера).
