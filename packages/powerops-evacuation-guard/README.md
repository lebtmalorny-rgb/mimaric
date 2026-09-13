# PowerOps evacuation guard 0.1.0

Общий Python-пакет допуска для Masakari engine и принимающего nova-compute.
Отдельный daemon не требуется. Пакет не вызывает Nova, не выполняет эвакуации,
не меняет Watcher hold и не управляет процессом etcd.

Требуются Python >=3.11, `requests>=2.25.1`, `oslo.config>=9.0.0`, etcd v3 с
JSON gateway и линейризуемыми транзакциями. Лицензия: Apache-2.0.
Образы обоих компонентов должны содержать одинаковый пакет и согласованные
настройки; выключенный параметр `enabled` обрабатывают вызывающие компоненты.

```ini
[powerops_evacuation_guard]
enabled = false
endpoint = http://127.0.0.1:2379
prefix = /powerops/evacuation/v1
timeout = 5.0
max_parallel = 3
cooldown = 5.0
admission_timeout = 3600.0
poll_interval = 1.0
submission_workers = 3
# ca_file = /etc/ssl/certs/etcd-ca.pem
# cert_file = /etc/ssl/certs/etcd-client.pem
# key_file = /etc/ssl/private/etcd-client.key
```

`max_parallel` и `submission_workers`: целые числа 1..1024. `timeout`,
`admission_timeout`, `poll_interval`: конечные положительные числа; `cooldown`:
конечное неотрицательное. Общие `max_parallel` и `cooldown` хранятся в etcd;
каждое действие сверяет локальные значения. Чтение допускается при несовпадении,
`status` показывает `configuration_matches=false`. URL допускает HTTP(S),
корневой путь и корректный порт, без userinfo/query/fragment. HTTPS проверяет
сертификат через системное доверие либо `ca_file`; клиентские cert/key задаются
только парой. Сертификаты и права etcd подготавливаются отдельно.

## Контракт Python

`from powerops_evacuation_guard import Guard` и исключения `GuardError`,
`GuardBusy`, `GuardDuplicate`, `GuardConflict`, `GuardDenied`, `GuardUnavailable`.
Все исключения наследуют `GuardError`; специальные отказы также наследуют
`GuardDenied`. Только `GuardBusy` разрешает повтор опроса ожидающим владельцем;
ошибка никогда не означает право начать локальное восстановление.

```python
Guard(endpoint, prefix='/powerops/evacuation/v1', timeout=5.0,
      ca_file=None, cert_file=None, key_file=None,
      max_parallel=3, cooldown=5.0)
```

UUID — каноническая lowercase-строка с дефисами. Request ID — `req-<UUID>`.
Имена host и actor — непустые строки до 255 символов, reason — до 1024,
без управляющих символов. В snapshot присутствуют `schema=1`, `kind` и целый
`revision`: это revision соответствующего ключа для точного CAS.

| Метод | Результат и условие |
|---|---|
| `initialize(actor, reason)` | Создаёт metadata только в пустом namespace. Повтор — конфликт, без сброса. |
| `configure(expected_revision, max_parallel, cooldown, actor, reason)` | Точный CAS metadata и атомарное отсутствие всего диапазона claims. |
| `configuration()` | Фактическая общая конфигурация. |
| `create_intent(attempt_uuid, vm_uuid, source_host, request_id, actor)` | Однократное резервирование VM/attempt/request до POST; `SUBMITTING`. |
| `get_intent(attempt_uuid)` | Сохранённое намерение и привязанная migration UUID. |
| `note_intent_unknown(attempt_uuid, reason)` | Меняет только observation/reason намерения. |
| `register(migration_uuid, vm_uuid, source_host, target_uuid, target_host, owner_uuid, request_id=None)` | Однократная регистрация `WAITING`, привязка намерения при наличии. |
| `get_operation(migration_uuid)` | Сохранённая операция. |
| `try_admit(migration_uuid, owner_uuid)` | Атомарный `RUNNING` с VM/target/global slot, иначе отказ. |
| `deny_waiting(migration_uuid, owner_uuid, reason)` | `DENIED` до допуска; освобождает только VM claim. |
| `mark_unknown(migration_uuid, owner_uuid, reason)` | `UNKNOWN` из `RUNNING/UNKNOWN`; все claims сохраняются. |
| `complete(migration_uuid, owner_uuid, result)` | Только `RUNNING` и строгий Nova proof; переход `COOLDOWN`. |
| `finish_cooldown(migration_uuid, owner_uuid)` | Дожидается полной монотонной паузы, CAS `DONE` и освобождение claims. |
| `recover_cooldown(migration_uuid, expected_revision, actor, reason)` | CAS нового владельца, новая полная пауза, возврат `DONE`. |
| `resolve(migration_uuid, expected_revision, actor, reason, nova_terminal, executors_quiesced)` | Оба аргумента строго `True`; `WAITING→DENIED` либо `RUNNING/UNKNOWN→COOLDOWN→DONE`. |
| `resolve_intent(attempt_uuid, expected_revision, actor, reason, nova_terminal, executors_quiesced)` | Оба аргумента строго `True`; только непривязанное намерение → `RESOLVED`. |
| `status(limit=100, cursor=None)` | `revision`, `configuration`, `configuration_matches`, `records`, `cursor`; 1..1024 записей на страницу. |

`config.register_opts(conf)`, `config.list_opts()` и `config.from_conf(conf)`
используют группу выше; `from_conf` проверяет все настройки и возвращает Guard.

Intent snapshot: `attempt_uuid`, `vm_uuid`, `source_host`, `request_id`, `actor`,
`state` (`SUBMITTING/BOUND/RESOLVED`), `migration_uuid`, `observation`
(`PENDING/UNKNOWN`), `reason`, `resolution`, плюс общие поля. `BOUND` остаётся
привязкой после завершения; фактический результат берётся из операции.

Operation snapshot: `migration_uuid`, `vm_uuid`, `source_host`, `target_uuid`,
`target_host`, `owner_uuid`, `request_id`, `attempt_uuid`, `state`, `slot`,
`reason`, `result`, `resolution`, `recovery`, плюс общие поля. `slot` равен `None`
до допуска, иначе это индекс 0..`max_parallel-1`, сохраняемый в tombstone.
`resolution` — actor/reason и два подтверждения; `recovery` — только actor/reason
последнего восстановления уже доказанного cooldown. Nullable-поля равны `None`.

`result` содержит ровно шесть полей: `migration_status='done'`, совпадающие
`vm_uuid`, `target_uuid`, `target_host`, `vm_state='active'` или `'stopped'` и
`task_state=None`. Эти факты подтверждает Nova после всего пути rebuild.
Одиночное наблюдение ACTIVE и успешный HTTP-ответ такого доказательства не дают.

## Долговечность и восстановление

Ключи относительно namespace:

- `/metadata`: общие лимиты, cooldown и аудит конфигурации;
- `/records/intents/<attempt_uuid>` и `/requests/<request_id>`: намерение и неизменяемый индекс;
- `/records/operations/<migration_uuid>`: операция и её постоянный tombstone;
- `/claims/vms/<vm_uuid>`, `/claims/targets/<target_uuid>`, `/claims/slots/<index>`: ресурсы.

В claims отсутствует TTL. Успешная транзакция с потерянным ответом остаётся
неопределённым исходом для клиента: повтор не получает новое право исполнения.
Ресурсы сохраняются при падении процесса и рестарте etcd. Не удаляйте ключи
вручную и не переинициализируйте namespace: tombstone защищает от запоздалого RPC.
В первой версии очистки истории нет; объём истории растёт отдельными ключами,
а обычный допуск обращается только к одной операции/VM/цели и ограниченному
числу global slots. FIFO не гарантируется.

Монотонный таймер существует только в экземпляре Guard, успешно выполнившем
`complete`. Новый процесс использует `recover_cooldown` с точной ревизией и
ждёт всю паузу заново. Старый finisher не может освободить claims нового
владельца. Ошибки после допуска сохраняют занятую ёмкость до подтверждённого
разбора; автоматического разрешения по времени нет.

Пауза и RUNNING занимают одновременно target и global slot. Масштаб общего
предела 3 не подтверждён нагрузочным тестом. Пакет не ограничивает обычные
start/build, live migration, Mistral или прямые BMC/гипервизорные действия.

## Команды оператора

```sh
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf initialize --actor operator --reason 'initial commissioning'
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf status --limit 100
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf inspect-operation MIGRATION_UUID
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf inspect-intent ATTEMPT_UUID
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf configure --expected-revision REVISION --max-parallel 3 --cooldown 5 --actor operator --reason 'quiesced configuration change'
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf recover-cooldown MIGRATION_UUID --expected-revision REVISION --actor operator --reason 'executor restarted after proven completion'
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf resolve-operation MIGRATION_UUID --expected-revision REVISION --actor operator --reason 'Nova terminal and every executor/RPC quiesced' --nova-terminal --executors-quiesced
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf resolve-intent ATTEMPT_UUID --expected-revision REVISION --actor operator --reason 'submission terminal and no delayed delivery possible' --nova-terminal --executors-quiesced
```

Замените UUID/REVISION результатами inspect. Resolve-флаги являются явными
подтверждениями оператора; CLI самостоятельно не проверяет Nova или очереди RPC.
При невозможности подтвердить оба факта запись сохраняют. Для привязанного
намерения инспектируют и разбирают migration; `resolve-intent` его не освобождает.
Смена конфигурации требует отсутствия всех claims, включая ожидающие запросы
и непривязанные намерения, затем согласованного обновления конфигов потребителей.

Вывод — JSON, ошибки ограничены общей строкой без URL, значения конфигурации,
тела удалённого ответа и traceback. Пагинация предназначена для диагностики:
каждая страница читает линейризуемо, но несколько страниц не являются одним
замороженным снимком; конфигурация читается отдельно от страницы records.

## Локальная проверка

Из корня комплекта, после установки pytest и зависимостей:

```sh
PYTHONPATH=packages/powerops-evacuation-guard python -m pytest -q packages/powerops-evacuation-guard/tests
POWEROPS_EVACUATION_TEST_ENDPOINT=http://127.0.0.1:33379 PYTHONPATH=packages/powerops-evacuation-guard python -m pytest -q packages/powerops-evacuation-guard/tests
python -m build --no-isolation packages/powerops-evacuation-guard
```

Первый прогон использует тестовый JSON transport etcd. Второй использует
настоящий заранее запущенный локальный etcd с отдельным UUID namespace на тест,
включая оба порядка гонки изменения лимитов/создания claim и CLI в разных
процессах. Инъекции повреждённого транспорта выполняются только offline.
Тесты не управляют сервером и не подключаются к облаку. Проверка настоящего
рестарта сервера отдельно фиксируется в отчёте комплекта.
