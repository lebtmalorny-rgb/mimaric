# PowerOps stand tests — handoff по сессии 2026-09-14

## Что сделано

Два сценария прогона на стенде `ultra1-poc` (через раннер `mimaric/stand_test.py`):
- `ha-emergency-001` — PASS
- `ha-planned-001` — PASS

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

**Файл-бэкап:** `/tmp/openstack_probe.py.orig` (полная копия до правки).

### 2. `remote_fault.py:338` — снять проверку Python 3.11+

**Симптом:** `fault` запускался через Ansible → BOOTSTRAP → `python3.9 -c remote_fault_source`. `dispatch()` возвращал `{"phase":"ERROR","result":"INCOMPLETE","error":"target requires Linux, root and Python 3.11+"}`. systemd-юнит `powerops-link-ha-emergency-001` не создавался.

**Причина:** на стендовых compute (`ultra1-2`, `ultra1-3`) только `python3.9` (`/usr/bin/python3.9`). В `load_task` мы перебили `remote_python` на `python3.9`, но `remote_fault.dispatch` имел жёсткую проверку версии.

**Правка:**
```diff
@@ -335,7 +335,7 @@ def recover(run_id, root=ROOT, system=None):
 def dispatch(request, source):
-    if sys.version_info < (3, 11) or sys.platform != "linux" or os.geteuid() != 0:
+    if sys.platform != "linux" or os.geteuid() != 0:
         raise ValueError("target requires Linux, root and Python 3.11+")
```

**Файл-бэкап:** `/tmp/remote_fault.py.orig` (восстановлен из git blob `9fd972953c8b624a47c08997eedfe967b5cf003f` через `git cat-file -p`: первоначальный `/bin/cp -f` ломался из-за `cp` aliased на `cp -i`).

## Правки вне репозитория

### 3. `~/.config/powerops-stand/inventory.ini` — собранный ansible inventory

`stand_test.py:load_task` (строка 76) валидирует `inventory` через `value.is_file()`. Каталог `backups_globals/inventory/` отвергается. Собрал плоский ini-файл:

```ini
[deployment]
ultra1-0 ansible_host=10.101.25.41
[control]
ultra1-6 ansible_host=10.101.25.150
ultra1-7 ansible_host=10.101.25.151
ultra1-8 ansible_host=10.101.25.152
[network]
ultra1-6 ansible_host=10.101.25.150
...
[compute]
ultra1-2 ansible_host=10.101.25.146
ultra1-3 ansible_host=10.101.25.147
```

Собран скриптом из `backups_globals/inventory/groups` + `host_vars/<host>.yml` (`ansible_host`). Режим 0600.

### 4. `~/.config/powerops-stand/emergency.json`

Ключевые отличия от `examples/emergency.json`:
- Удалены `cloud`, `globals`, `interface_var`.
- `inventory` → `~/.config/powerops-stand/inventory.ini`.
- `host`/`inventory_host` → `ultra1-3.ultra1.test.pvs.un.sbt` / `ultra1-3`.
- `interface` передаётся через CLI `--interface enp3s0` (не в JSON).
- `node_uuid`, `segment_uuid`, `ha_host_uuid` — реальные UUID-ы со стенда.
- `server_ids` → `[e09d747f-c114-4d1f-ab89-b3d2f5d43bda]`.
- `destination_hosts` → `[ultra1-2.ultra1.test.pvs.un.sbt]`.
- `libvirt.backend` → `"docker"` (стенд использует podman, но раннер называет контейнерную ветку `docker`).
- Добавлен `remote_python: "python3.9"` (перебивает дефолт).

Режим 0600.

### 5. `~/.config/powerops-stand/planned.json`

То же, что `emergency.json`, но без `duration` и `interface`.

## Операции, выполненные на стенде

### 6. Masakari `on_maintenance=false` для `ultra1-3`

`stand_test.py:Runner.preflight` требует `ha_host.on_maintenance == False`. После рестарта ноды (через IPMI) Masakari автоматически выставляет maintenance. Снимали так:

```bash
TOKEN=$(openstack --os-region RegionOne token issue -c id -f value)
curl -X PUT -H "X-Auth-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"host":{"name":"ultra1-3.ultra1.test.pvs.un.sbt","type":"compute","control_attributes":"ssh","reserved":false,"on_maintenance":false}}' \
  http://10.101.25.42:15868/v1/segments/792c79ca-f5ea-4b75-bc71-36a26e6126a7/hosts/6fc141ab-a819-46ea-a122-110dc7af6df3
```

PATCH не сработал — Masakari API v1.3 его игнорирует. PUT требует полного тела (без `failover_segment_id`, иначе 400).

### 7. Включение `ultra1-3` после `compute service set --disable`

`ultra1-3` пришёл в прогон в `disabled` (от прошлой эвакуации). Включили:

```bash
openstack compute service set --enable ultra1-3.ultra1.test.pvs.un.sbt nova-compute
```

После power-cycle (когда нода ушла по питанию из-за ручного fault на стадии диагностики) повторно:

```bash
openstack compute service set --enable ultra1-3.ultra1.test.pvs.un.sbt nova-compute
openstack compute service set --up ultra1-3.ultra1.test.pvs.un.sbt nova-compute
openstack baremetal node power on dc80b2db-c20f-4e6f-82d9-0f9d4a1b04ee
```

### 8. Live-migration ВМ перед planned

После emergency ВМ осталась на `ultra1-2`. Для planned нужен source (`ultra1-3`) с ВМ. Перевесили:

```bash
openstack server migrate --live e09d747f-c114-4d1f-ab89-b3d2f5d43bda --host ultra1-3.ultra1.test.pvs.un.sbt --wait
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
3. **Сделать `inventory.ini` частью `backups_globals/inventory/`** (как готовый плоский файл) или положить в репо `mimaric/test-fixtures/inventory.ini`, чтобы будущие прогоны не собирали его руками.
4. **Документировать `remote_python=python3.9`** в README как дефолт для стендов без Python 3.11.
5. **Документировать, что `stand_test.py` ожидает файл inventory, а не каталог** — в README §3 это не отражено.

## Артефакты, оставшиеся в системе

| Путь | Назначение |
|------|-----------|
| `~/.local/state/powerops-stand/ha-emergency-001.json` | state-journal emergency |
| `~/.local/state/powerops-stand/ha-planned-001.json` | state-journal planned |
| `~/.config/powerops-stand/emergency.json` | task JSON emergency |
| `~/.config/powerops-stand/planned.json` | task JSON planned |
| `~/.config/powerops-stand/inventory.ini` | собранный inventory |
| `~/.config/powerops-stand/run-1-summary.md` | выжимка результатов |
| `~/.config/powerops-stand/run-1-handoff.md` | этот документ |
| `/tmp/powerops-run-1-reports-2026-09-14.tar.gz` | полные report-ы |
| `/tmp/openstack_probe.py.orig` | бэкап openstack_probe.py до патча |
| `/tmp/remote_fault.py.orig` | бэкап remote_fault.py до патча |

## Команды для воспроизведения

```bash
set -a; . /etc/kolla/admin-openrc.sh; set +a
unset OS_CLOUD

# Emergency — PASS
python3.11 /home/DVSokolov/work/mimaric/stand_test.py report \
  --run-id ha-emergency-001 \
  --state-dir /home/DVSokolov/.local/state/powerops-stand

# Planned — PASS
python3.11 /home/DVSokolov/work/mimaric/stand_test.py report \
  --run-id ha-planned-001 \
  --state-dir /home/DVSokolov/.local/state/powerops-stand

# Статус (без API, читает journal)
python3.11 /home/DVSokolov/work/mimaric/stand_test.py status \
  --run-id ha-emergency-001 \
  --state-dir /home/DVSokolov/.local/state/powerops-stand
```

## Замечания по стенду `ultra1-poc`

- Реальные compute — `ultra1-2` и `ultra1-3` (см. `backups_globals/inventory/groups`). `ultra1-6/7/8-ironic` — control-ноды; их записи в `compute service list` — шумовые.
- Имена Ironic-узлов должны совпадать с Nova host name (требование README §1). У нас совпадают.
- `host_status=MAINTENANCE` на `ultra1-3` выставляется автоматически при `compute service set --disable` либо при падении ноды. Снимается только через Masakari API PUT.
- `python3.11` на compute отсутствует — только `python3.9`.
- `nova-compute` agent на control-нодах (`ultra1-6/7/8-ironic`) регистрируется в `compute service list` как enabled/up, но реальных ВМ на них нет.
- Маскарадинг сегмента: `ha_cd` (`792c79ca-…`), `recovery_method=auto`. Внутри два хоста: `ultra1-3` (UUID `6fc141ab-…`) и `ultra1-2` (UUID `a7e39cc2-…`).
- На compute стоит `podman`, не `docker`. Раннер называет это `backend=docker` в task JSON (имя условное).
- Fault-interface `enp3s0` (не `eno2` из README-примера).
