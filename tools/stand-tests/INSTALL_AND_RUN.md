# Установка и запуск PowerOps stand tests

Инструкция для ветки `feature/powerops-stand-tests`. Инструмент проверяет
аварийную эвакуацию и плановое выключение с live migration, затем включает
compute и возвращает его в обслуживание. В обоих сценариях тест сам передаёт
подтверждение оператора после проверки хоста на паузе Mistral.

## 1. Подготовить операторскую машину и стенд

Запускайте runner с отдельной Linux/macOS-машины с Python **3.11** и Git.
Она должна сохранять доступ к OpenStack API и не выключаться вместе с compute.

На стенде уже должны работать:

- Активный PowerOps baseline 0809: интеграции Kolla/Ironic, Mistral и Masakari,
  плюс [Masakari post-fence Nova-down hotfix](../../hotfixes/masakari-post-fence-nova-down/README.md).
- Mistral workflows `power_ops.planned_power_off` и
  `power_ops.power_on_and_return`; последний действительно останавливается
  на `operator_inspection_gate` в состоянии `PAUSED`.
- Ironic node, управляющий питанием выбранного compute, с настроенными BMC
  credentials. Nova host name и Ironic node name должны совпадать.
- Masakari host в указанном сегменте. Для аварийного сценария необходимы
  API **1.3** и сохранение TaskFlow recovery details с временными отметками.
- Nova API **2.59**, рабочая live migration/evacuation и достаточная ёмкость
  назначений. Настройки storage/CPU/network для переноса должны быть готовы.

На source compute требуются Linux, Python 3.11 или новее, `ip -j`, systemd
и доступ к `virsh -c qemu:///system` на хосте либо в контейнере libvirt.
Нужны SSH-доступ и root/become без интерактивного запроса пароля.

Выберите выделенный тестовый compute: все его ВМ должны быть явно перечислены
в задании, находиться в `ACTIVE`, без незавершённых миграций. Посторонних ВМ
или libvirt-доменов на source быть не должно. На время опыта исключите
параллельные DRS/manual операции с этими хостами и ВМ.

## 2. Получить ветку и установить зависимости

```bash
git clone --single-branch --branch feature/powerops-stand-tests \
  https://github.com/lebtmalorny-rgb/mimaric.git "$HOME/mimaric-stand-tests"
cd "$HOME/mimaric-stand-tests"

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/stand-tests/requirements.txt 'ansible-core==2.18.2'

python --version
ansible-playbook --version
python tools/stand-tests/stand_test.py --help
```

Используются `openstacksdk==4.20.0` и `ansible-core==2.18.2`. Активация venv
нужна и для поиска `ansible-playbook` в PATH. Runner обращается к API через SDK
session; `openstack` CLI и клиентские плагины ему не требуются.
При парольном SSH через OpenSSH на операторской машине также нужен `sshpass`.
Для checkout/venv выберите путь без двоеточия `:` — Python venv отвергает
каталоги, содержащие этот разделитель PATH.

Можно проверить сам инструмент без подключения к стенду:

```bash
python -m unittest discover -s tools/stand-tests/tests -v
python -m unittest discover -s tests -v
```

Полный локальный набор: **75 тестов инструмента и 7 проверок репозитория**.
Ansible в этих тестах использует только локальные фиктивные inventory;
OpenStack/SSH/systemd/IP-вызовы заменены тестовыми адаптерами.

## 3. Настроить OpenStack-доступ

Используйте уже работающий операторский `clouds.yaml` либо OpenStack RC.
Нужен project-scoped пользователь с правами чтения всех проектов и host-атрибутов
Nova, migrations, Masakari notifications/VMove, Ironic states, а также создания
и продолжения Mistral executions. Обычных прав tenant-пользователя недостаточно.

Вариант с `clouds.yaml`: имя облака в task JSON — `stand-admin`. Например,
файл `~/.config/openstack/clouds.yaml` имеет следующую структуру; реальные
значения внесите локально:

```yaml
clouds:
  stand-admin:
    auth_type: password
    auth:
      auth_url: https://keystone.example.org:5000/v3
      username: operator
      password: REPLACE_LOCALLY
      project_name: admin
      user_domain_name: Default
      project_domain_name: Default
    region_name: RegionOne
    interface: internal
```

Задайте права 0600 для файла. Выберите доступный операторской машине interface;
для внутреннего CA укажите `cacert` в конфигурации облака.
Не копируйте этот файл в репозиторий или отчёт.

Вариант с RC:

```bash
source /absolute/path/admin-openrc.sh
```

При работе через `OS_*` удалите поле `cloud` из обоих task JSON и снимите
ранее установленный `OS_CLOUD`, если он выбирает другое облако. Проверьте
`region_name`: в примерах указан `RegionOne`.

**BMC-пароли отдельно не нужны:** штатные действия PowerOps/Masakari используют
Ironic и уже сохранённые там credentials. Runner не читает `driver_info`.

## 4. Подключить inventory и globals

Можно использовать имеющийся Kolla inventory. Пример отдельного inventory:

```ini
[compute]
compute-01 ansible_host=192.0.2.11 ansible_user=operator

[compute:vars]
ansible_ssh_private_key_file=/home/operator/.ssh/id_ed25519
ansible_become=true
ansible_python_interpreter=/usr/bin/python3.11
```

Адрес, пользователь и пути здесь условные. `inventory_host` в задании должен
точно совпадать с inventory hostname, например `compute-01`. Он может отличаться
от Nova `host`, но обязан вести на ту же машину. Группа или шаблон вместо
конкретного хоста не допускаются. Заранее проверьте SSH host key обычным способом.

`globals` необязателен. Он передаётся Ansible как `-e @globals.yml` и подходит
для разрешения интерфейса через `network_interface`, `tunnel_interface` либо
`storage_interface`. Чтобы получить интерфейс из globals/inventory:

```json
"interface_var": "network_interface"
```

Чтобы задать точное Linux-имя:

```json
"interface": "eno2"
```

В JSON должно быть ровно одно из этих полей. `--interface eno2` переопределяет
выбор интерфейса из переменной. Runner не выбирает автоматически подходящий
bond/VLAN или сеть для аварийного сценария.

Для SSH/sudo-паролей используйте штатные Ansible variables и Vault.
При необходимости добавьте в task JSON путь к существующему файлу/скрипту:

```json
"vault_password_file": "/absolute/path/vault-password-file"
```

Пароли в task JSON не принимаются. При входе под root можно задать
`"become": false`. `remote_python` по умолчанию `python3.11`; его можно заменить
полным путём к подходящему интерпретатору на compute.

## 5. Заполнить два задания

Храните задания и журналы вне репозитория, на постоянной локальной файловой
системе. Эти переменные используйте во всех дальнейших командах:

```bash
POWEROPS_CONFIG_DIR="$HOME/.config/powerops-stand"
POWEROPS_STATE_DIR="$HOME/.local/state/powerops-stand"
install -d -m 700 "$POWEROPS_CONFIG_DIR" "$POWEROPS_STATE_DIR"

cp tools/stand-tests/examples/planned.json "$POWEROPS_CONFIG_DIR/planned.json"
cp tools/stand-tests/examples/emergency.json "$POWEROPS_CONFIG_DIR/emergency.json"
chmod 600 "$POWEROPS_CONFIG_DIR/planned.json" "$POWEROPS_CONFIG_DIR/emergency.json"
```

Отредактируйте файлы до запуска. Все UUID в примерах — заглушки.

| Поле | Что указать |
|---|---|
| `scenario` | `planned` или `emergency` |
| `cloud`, `region_name` | Имеющееся облако/регион; для RC поле cloud убрать |
| `inventory` | Абсолютный путь к реальному файлу inventory |
| `globals` | Путь к globals.yml; убрать поле, если он не нужен |
| `host` | Точное Nova compute service host name |
| `inventory_host` | Inventory alias того же физического compute |
| `node_uuid` | UUID Ironic node, управляющего питанием source |
| `segment_uuid` | UUID Masakari segment |
| `ha_host_uuid` | UUID Masakari host внутри этого сегмента; это не UUID Ironic |
| `server_ids` | Непустой список UUID всех исходных тестовых ВМ на source |
| `destination_hosts` | Допустимые Nova compute hosts назначения, отличные от source |
| `interface` / `interface_var` | Интерфейс для проверки/внесения сетевого отказа |
| `libvirt` | Например `{"backend":"docker","container":"nova_libvirt"}`; также поддерживаются podman и `{"backend":"host"}` |
| `duration` | Аварийный сетевой интервал, по умолчанию 300, допустимо 1–3600 секунд |
| `timeout`, `poll_interval` | Ожидание этапа и период опроса, по умолчанию 1800 и 5 секунд |

UUID и исходное размещение возьмите из вашего административного интерфейса/API
Nova, Ironic и Masakari. `--host` меняет только Nova host: остальные UUID и
`inventory_host` необходимо согласованно заполнить в JSON.
Относительные пути внутри task разрешаются от его каталога; CLI-пути
`--inventory`/`--globals` — от текущего каталога.

## 6. Аварийная эвакуация

Все три команды должны использовать одинаковые параметры. Укажите уникальный
run ID для нового опыта; ниже приведён пример `ha-emergency-001`.

План без вызовов Ansible/API:

```bash
python tools/stand-tests/stand_test.py plan \
  --task "$POWEROPS_CONFIG_DIR/emergency.json" --run-id ha-emergency-001 \
  --state-dir "$POWEROPS_STATE_DIR" --interface eno2 --duration 300
```

Чтение исходного состояния стенда:

```bash
python tools/stand-tests/stand_test.py preflight \
  --task "$POWEROPS_CONFIG_DIR/emergency.json" --run-id ha-emergency-001 \
  --state-dir "$POWEROPS_STATE_DIR" --interface eno2 --duration 300
```

При `PREFLIGHT` можно запускать сценарий. Следующая команда **реально отключает
интерфейс, ожидает автоматическую эвакуацию/fencing и выполняет power-on/return**:

```bash
python tools/stand-tests/stand_test.py run \
  --task "$POWEROPS_CONFIG_DIR/emergency.json" --run-id ha-emergency-001 \
  --state-dir "$POWEROPS_STATE_DIR" --interface eno2 --duration 300 --execute
```

Runner ожидает настоящее уведомление Masakari и успешный VMove каждой ВМ,
проверяет временной порядок Ironic fencing → Nova disabled/down → эвакуация,
затем возвращает source через Mistral. Если выбранный интерфейс не вызывает
host failure при текущей матрице мониторинга, уведомление не подделывается.

Fencing может прервать Linux-таймер отключением питания. Поэтому runner
дополнительно выдерживает **duration секунд после наблюдения завершённого
recovery и выключенного source**. Общая длительность опыта больше пяти минут.
После restart runner эта выдержка выполняется полностью заново, если намерение
return ещё не было сохранено; используется монотонное время.

## 7. Плановое выключение с миграциями

Перед следующим опытом подготовьте его собственное исходное размещение:
после аварийного теста ВМ находятся на destination. Возврат compute не переносит
ВМ обратно. Нельзя просто запустить planned.json с прежним пустым source.

План и проверка:

```bash
python tools/stand-tests/stand_test.py plan \
  --task "$POWEROPS_CONFIG_DIR/planned.json" --run-id ha-planned-001 \
  --state-dir "$POWEROPS_STATE_DIR"

python tools/stand-tests/stand_test.py preflight \
  --task "$POWEROPS_CONFIG_DIR/planned.json" --run-id ha-planned-001 \
  --state-dir "$POWEROPS_STATE_DIR"
```

Реальные live migrations, выключение и возврат source:

```bash
python tools/stand-tests/stand_test.py run \
  --task "$POWEROPS_CONFIG_DIR/planned.json" --run-id ha-planned-001 \
  --state-dir "$POWEROPS_STATE_DIR" --execute
```

Mistral получает `instance_policy=live_migrate`, `allow_hard_off=false`.
Runner требует отдельную новую завершённую live migration каждой ВМ и пустой
source перед подтверждением выключения. В baseline 0809 история migration
со статусом `done` блокирует плановый сценарий ещё на preflight; тест не меняет
историю Nova, чтобы обойти это ограничение.

## 8. Автоподтверждение и итоговый отчёт

В обоих сценариях runner наблюдает настоящий `PAUSED`, проверяет power-on,
Nova `disabled/up`, maintenance, новую загрузку той же машины, исходные MAC/адреса
и отсутствие старых доменов на source. Для аварийного теста также сверяются
удалённый fault-журнал и уникальная метка текущего прогона. После этого **тот же
execution** получает `stale_domains_checked=true` и продолжается автоматически.
Отдельно подтверждать оператора в середине прогона не нужно.

Успех требует workflow SUCCESS, source power on, Nova enabled/up, снятого
maintenance и всех ВМ ACTIVE/idle на ожидаемых destination. Старые домены
блокируют подтверждение: тест сам не выполняет undefine.

Посмотреть сохранённые результаты без подключения к стенду:

```bash
python tools/stand-tests/stand_test.py report --run-id ha-emergency-001 --state-dir "$POWEROPS_STATE_DIR"
python tools/stand-tests/stand_test.py report --run-id ha-planned-001 --state-dir "$POWEROPS_STATE_DIR"
```

Файлы: `$POWEROPS_STATE_DIR/<run-id>.json`. Команда `status` также читает журнал,
а не опрашивает стенд. Отчёт содержит исходные/финальные состояния, VM placement,
Mistral execution IDs, notification/VMove/migration evidence и результат inspection.

| Статус | Exit code | Значение |
|---|---|---|
| PLAN / PREFLIGHT | 0 | Подготовка; сам сценарий ещё не проверен |
| PASS | 0 | Выбранный сценарий и возврат подтверждены |
| FAIL | 2 | Нарушен критерий; тот же run ID не запускается заново |
| INCOMPLETE | 3 | Недостаточно доказательств, таймаут или неизвестный результат запроса |

При потере связи повторите **исходный `run --execute` с теми же параметрами**.
Сохранённые POST/PUT не повторяются; наблюдается прежний execution. Deadline
этапа не продлевается. Если срок истёк или намерение сохранилось до фактической
отправки, потребуется разбор состояния. PASS/FAIL по тому же ID возвращаются
как исторические результаты, без повторного воздействия.

Не удаляйте журнал ради повторного запуска. После ошибки source может остаться
выключенным или PAUSED/maintenance; безусловного power-on/enable в cleanup нет.
Журналы с незавершённым изменяющим намерением удерживают source для разбора.
Для ручного чтения/восстановления только сетевого fault через отдельный CLI
см. [LINK_FAULT.md](LINK_FAULT.md), включая `--intent-nonce`.

Критерии и ограничения PASS подробнее описаны в [README.md](README.md).
Проверка не включает гостевой SSH/HTTP, сохранность прикладных данных или
доказательство непрерывного физического L3/carrier outage. Локальные тесты
инструмента прошли; **на реальном стенде сценарии ещё не запускались**.
