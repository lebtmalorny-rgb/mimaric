# Очередь эвакуаций Masakari на принимающих compute

Назначение выбирает Nova. На каждом целевом compute одновременно допускается
одна эвакуация, во всём контуре — до трёх; после доказанного завершения на этой
цели выдерживается 5 секунд. Общий предел и пауза настраиваются. Несколько ВМ
одного задания могут работать параллельно на разных назначениях. Это предел
допуска, а не измеренная производительность: нагрузка и масштаб 1000 хостов
не проверены.

По умолчанию режим выключен. Очередь охватывает принимающий
`rebuild_instance(recreate=True)` при включённом guard, включая эвакуации вне
Masakari. Обычные build/start, live migration и плановые Mistral-сценарии
в эту очередь не входят. Scheduler/Placement, Ironic fencing, исходная защита
source-host и Watcher emergency epoch сохраняют свой прежний смысл.

## Комплект и точный порядок исходников

[Manifest](../hotfixes/masakari-per-target-evacuation/manifest.json) содержит
SHA256 wheel/патчей, исходные и конечные commits/trees. Патчи экспортированы
только из диапазонов новой функции. Предшествующий
[Watcher-комплект](../hotfixes/watcher-automation-hold/README.md) остаётся
неизменным; сначала проверяются оба manifest из корня комплекта:

```sh
python3 tools/watcher_automation_hold_delivery.py verify
python3 tools/watcher_automation_hold_delivery.py --manifest hotfixes/masakari-per-target-evacuation/manifest.json verify
shasum -a 256 -c SHA256SUMS
```

Историческое имя verifier сохранено. `dependency.manifest` нового manifest —
метаданные относительно корня комплекта, не путь к повторно включённому
артефакту. Verifier проверяет артефакты внутри выбранного manifest; проверка
предшественника — отдельная команда выше.

| Компонент | Требуемая база новой серии | Итоговое дерево |
|---|---|---|
| Nova stable/2025.1 | commit `ce37978276744e92d91251210a1d9c2784eea375`, tree `efaa1afe1685ffae2032c46ea1d03b3723c73e6f` | `85d45af66afefeb0317eb42d1d235d28dc61dc90` |
| Masakari | commit `0c2fa56a36e71612e32bf50e174c465138d0c8fb`, tree `f7eb2f799ba9db0ac44b01ca949c1070bd4b6f96` | `568c7daa3e71c85beb22be44252d90c310a98acf` |
| Kolla-Ansible | commit `3c8d0b9b04053855541fc33f5be91ab0541a6a77`, tree `d68e9dcf20ca05e2bea7fb07ab93e80aab40e2a2` | `f8c12755d41a469c910ee29ea3a37a90e999d5ce` |

Для Nova подготовьте чистый checkout указанного commit. Для пользовательских
архивов `0809` используйте их SHA256 из
[baseline](../baselines/0809.json), затем следующий порядок:

1. Masakari `0809` → `hotfixes/watcher-automation-hold/masakari/0000-prerequisite-post-fence-nova-down.patch`
   → `hotfixes/watcher-automation-hold/masakari/0001-feat-hold-Watcher-automation-on-host-failure.patch`.
   Первый патч помечен `applied_before_base=true` в старом manifest: его
   применяют до базы старого replay и никогда повторно.
2. Kolla `0809` → `hotfixes/watcher-automation-hold/kolla-ansible/0001-feat-configure-shared-Watcher-automation-guard.patch`
   → `hotfixes/watcher-automation-hold/kolla-ansible/0002-fix-require-managed-etcd-for-automation-guard.patch`.
3. Watcher stable/2025.1 и его прежняя серия/пакет устанавливаются по старому
   руководству. Его итоговое дерево `30e2ec8225db08ce46b71844bbcdb4a00767ab8d`
   является неизменной предпосылкой этого комплекта.
4. На точных новых базах: Nova `nova/0001-Guard-receiving-compute-evacuation-with-durable-per-.patch`;
   Masakari `masakari/0001-Add-durable-evacuation-intents-and-process-wide-Masa.patch`;
   Kolla `kolla-ansible/0001-feat-configure-per-target-evacuation-guard.patch`, затем
   `kolla-ansible/0002-fix-validate-evacuation-guard-IPv6-endpoints.patch`.
   Пути этого пункта относительно `hotfixes/masakari-per-target-evacuation/`.

У patch-архивов локальные commit IDs могут отличаться; точная проверка ведётся
по Git tree. `git apply --check` каждого патча выполняется после предыдущего.
Не накладывайте всю коллекцию `.patch` автоматически. Mistral здесь не меняется.

Безопасная проверка новых серий на чистых копиях исходников (подставьте свои
пути `NOVA_CLEAN_BASE`, `MASAKARI_CLEAN_BASE`, `KOLLA_CLEAN_BASE`):

```sh
EVAC_REPLAY_DIR=$(mktemp -d /tmp/evac-replay.XXXXXX)
python3 tools/watcher_automation_hold_delivery.py --manifest hotfixes/masakari-per-target-evacuation/manifest.json replay --component nova --source "$NOVA_CLEAN_BASE" --output "$EVAC_REPLAY_DIR/nova"
python3 tools/watcher_automation_hold_delivery.py --manifest hotfixes/masakari-per-target-evacuation/manifest.json replay --component masakari --source "$MASAKARI_CLEAN_BASE" --output "$EVAC_REPLAY_DIR/masakari"
python3 tools/watcher_automation_hold_delivery.py --manifest hotfixes/masakari-per-target-evacuation/manifest.json replay --component kolla-ansible --source "$KOLLA_CLEAN_BASE" --output "$EVAC_REPLAY_DIR/kolla-ansible"
```

Используйте только чистую Kolla-копию без `etc/kolla/passwords.yml`, приватных,
игнорируемых и untracked файлов. Не передавайте эксплуатационный каталог
replay-инструменту. При первичном индексировании manifest исключает приватный
путь буквально; четыре `tools/*passwords.py` сохраняются symlink. Replay
отказывает при неверной базе и существующем output, исходник не меняет.

## Wheel и общая конфигурация

Исходим из того, что ваши обычные настроенные образы уже собираются с этими
патчами и wheel. Дополнительного выбора image/tag и отдельного обязательного
контроля содержимого образов нет. В существующем окружении сборки исходников
Nova и Masakari (Python >=3.11, зависимости из их constraints) установите
локальный wheel; например после копирования комплекта в `/opt/powerops-patches`:

```sh
python3.11 -m pip install --no-deps /opt/powerops-patches/hotfixes/masakari-per-target-evacuation/package/powerops_evacuation_guard-0.1.0-py3-none-any.whl
```

Эта команда относится к существующему процессу сборки, в рамках локальной
проверки образы не собирались. Нужны `requests>=2.25.1`, `oslo.config>=9.0.0`.
Wheel нужен всем образам из изменённых исходников даже при `enabled=false`,
поскольку config modules импортируют пакет. Перед включением все возможные
целевые compute и все активные Masakari engine должны использовать патчи:
смешанные старые/новые workers при включённой очереди не поддерживаются.

Kolla требует включённых Nova, Masakari, PowerOps и управляемого Kolla etcd.
Настройки по умолчанию в `globals.yml`:

```yaml
powerops_evacuation_guard_enabled: "no"
powerops_evacuation_guard_prefix: "/powerops/evacuation/v1"
powerops_evacuation_guard_timeout: 5.0
powerops_evacuation_guard_max_parallel: 3
powerops_evacuation_guard_cooldown: 5.0
powerops_evacuation_guard_admission_timeout: 3600.0
powerops_evacuation_guard_poll_interval: 1.0
powerops_evacuation_guard_submission_workers: 3
```

`powerops_evacuation_guard_endpoint` по умолчанию использует общий Kolla VIP и
порт etcd; явно заданный endpoint должен иметь вид `http(s)://host:port`
с портом 1..65535, без логина/пароля, path/query/fragment. При IPv6 нужны
валидные квадратные скобки. Один общий доступный всем endpoint, namespace,
`max_parallel` и `cooldown` обязательны; localhost каждого контейнера не является
общим backend. etcd v3 JSON gateway и линейризуемые транзакции обязательны.

Параметры TLS: `powerops_evacuation_guard_ca_file`, `..._cert_file`,
`..._key_file`; cert/key задаются парой. HTTPS проверяет системное доверие либо
указанный CA. Файлы с правами доступа заранее предоставляются контейнерам
через существующий процесс; допустимые пути Kolla начинаются с `/etc/pki/`,
`/etc/ssl/` или `/var/lib/kolla/share/ca-certificates/`. Precheck проверяет
синтаксис и зависимости, не доступность реальных файлов/etcd. Настройте etcd
права на этот namespace; namespace Watcher остаётся отдельным.

CLI использует те же значения в `/etc/powerops/evacuation.conf`:

```ini
[powerops_evacuation_guard]
enabled = false
endpoint = https://etcd.example.invalid:2379
prefix = /powerops/evacuation/v1
timeout = 5.0
max_parallel = 3
cooldown = 5.0
admission_timeout = 3600.0
poll_interval = 1.0
submission_workers = 3
ca_file = /etc/ssl/certs/etcd-ca.pem
```

Замените пример endpoint и CA своими значениями. При выключенных и согласованно
подготовленных потребителях однократно инициализируйте пустой namespace:

```sh
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf initialize --actor operator --reason 'initial coordinated setup'
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf status --limit 100
```

Повторный initialize не сбрасывает namespace. `enabled` переключают согласованно
в существующем процессе эксплуатации. Пакет не включает сервисы самостоятельно.

## Наблюдение и разбор неопределённого состояния

`WAITING` — запрос зарегистрирован, ещё не допущен. Его владелец может ждать
свободную цель/общий слот. Admission timeout переводит ожидающую попытку в
долговечный `DENIED`; она не сможет исполниться позже. FIFO не гарантируется.
`RUNNING` удерживает claims. `COOLDOWN` означает доказанное завершение Nova,
но очередь ещё выдерживает паузу, Masakari success ещё не подтверждает.
В течение COOLDOWN удерживаются и целевой compute, и общий слот: это снижает
пиковую пропускную способность в пользу безопасного интервала после завершения.
Только `DONE` с совпадающим Nova proof позволяет `Attempt.confirmed` вернуть
успех. Смена host или VMove success сами по себе не являются доказательством.

`UNKNOWN`, пропавший процесс и потерянный ответ etcd сохраняют claims без TTL.
Намерение сохраняется даже если запрос ещё не дошёл до compute. Таймаут API
или наблюдения Masakari не отменяет Nova: не повторяйте POST вслепую. Сбой
одной recovery останавливает её новые отправки, уже начатые workers дренируются;
другие recovery продолжают работать в общем ограниченном пуле.

```sh
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf status --limit 100
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf status --limit 100 --cursor CURSOR_FROM_PREVIOUS_PAGE
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf inspect-intent ATTEMPT_UUID
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf inspect-operation MIGRATION_UUID
```

Страницы status не составляют один замороженный снимок. UUID и `revision`
берите из inspect, для configure — `configuration.revision` из status, не
общую revision снимка. При изменении revision повторите инспекцию и решение.

Для уже доказанного `COOLDOWN`, потерявшего завершающий процесс, команда ниже
берёт нового владельца по точной revision и ждёт новую полную монотонную паузу:

```sh
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf recover-cooldown MIGRATION_UUID --expected-revision REVISION --actor operator --reason 'proven completion; old finalizer lost'
```

Известный дубликат той же migration может сделать это автоматически; для
постороннего orphan cooldown нужен оператор. Изменение настенных часов не
сокращает паузу. Для UNKNOWN/RUNNING сначала независимо подтвердите терминальное
состояние Nova и невозможность действий старых executors/отложенной доставки.
CLI эти факты не проверяет: следующие флаги — ваши явные подтверждения.

```sh
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf resolve-operation MIGRATION_UUID --expected-revision REVISION --actor operator --reason 'Nova terminal; old executors and delivery quiesced' --nova-terminal --executors-quiesced
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf resolve-intent ATTEMPT_UUID --expected-revision REVISION --actor operator --reason 'submission terminal; no delayed delivery remains' --nova-terminal --executors-quiesced
```

`resolve-intent` применим только к непривязанному SUBMITTING. Для BOUND разбирают
migration. Resolve фиксирует операторское решение, не создаёт ложный Nova
completion proof. Если quiescence не доказана, операция остаётся заблокирована.
Не удаляйте claims, tombstones или namespace вручную, не используйте TTL.

Смена лимита/паузы требует остановки новых отправок, завершения либо доказанного
разбора всех активных и ожидающих intents/operations и согласованного обновления
конфигов всех потребителей. `configure` атомарно проверяет отсутствие claims:

```sh
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf configure --expected-revision CONFIGURATION_REVISION --max-parallel 3 --cooldown 5 --actor operator --reason 'all submissions and executors quiesced'
```

При отказе не обходите проверку: неуспешная quiescence сохраняет блокировку.
Затем согласованно обновите локальные значения; несовпадение с metadata
останавливает новые действия. Изменение `submission_workers` требует
согласованного перезапуска engine, иначе существующий пул откажет.

## Проверенные границы и цена решений

Включённый режим перечисляет все страницы серверов до создания VMove;
инвентарь source-host хранится в памяти. FAILED или ONGOING VMove запрещает
автоматическое продолжение notification до операторского разбора. Блокирующий
API/auth запрос может удерживать один ограниченный worker и source lock:
существующий HTTP timeout не изменён, безопасного автоматического освобождения
нет. Записи истории сохраняются постоянно; сборки мусора в этой версии нет.

API эвакуации Masakari сохраняет Nova microversion 2.53: исходное состояние
ACTIVE/STOPPED остаётся частью семантики. В исследованном libvirt-пути 2.95
выполняет spawn до последующего stop; переход на 2.95 не решает стартовую
нагрузку. Новая проверка требует нормального завершения всего rebuild, migration
`done`, совпадения ВМ/назначения, `task_state=None` и согласованного итогового
vm_state, с дополнительными свежими чтениями DB.

Локальные unit/source checks и smoke с настоящим etcd и разными процессами
описаны в [EVIDENCE](../hotfixes/masakari-per-target-evacuation/EVIDENCE.md).
В smoke настоящие Nova helper, Masakari Attempt и Guard; внешние Nova DB/virt
заменены тестовыми данными. Это не доказательство работы Linux/OpenStack,
облака, образов или производительности. Реальные SSH/BMC/эвакуации не выполнялись.
Все решения root и их издержки сохранены по хронологии в
[DECISIONS](../hotfixes/masakari-per-target-evacuation/DECISIONS.md).
