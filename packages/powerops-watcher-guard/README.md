# powerops-watcher-guard

Общий долговечный запрет автоматической балансировки Watcher для Masakari и
Watcher. Python 3.11+, etcd v3 JSON gateway, `requests`, `oslo.config`.
Пакет не запускает отдельный сервис и не обращается к Nova, Ironic или Mistral.

## Установка и конфигурация

```sh
python3.11 -m pip install ./packages/powerops-watcher-guard
```

Одинаковая группа в конфигурациях обоих сервисов и в отдельном файле оператора:

```ini
[watcher_automation_guard]
enabled = false
endpoint = http://127.0.0.1:2379
prefix = /powerops/watcher-automation/v1
timeout = 5.0
# ca_file = /etc/powerops/etcd-ca.pem
# cert_file = /etc/powerops/etcd-client.pem
# key_file = /etc/powerops/etcd-client-key.pem
```

`enabled` проверяет вызывающий сервис. CLI всегда выполняет явно указанную
операторскую команду, даже при `enabled=false`. Для нескольких реплик нужен один
общий etcd gateway/HA endpoint и одинаковый `prefix`; разные префиксы изолированы.
HTTPS проверяет серверный сертификат через системные CA или `ca_file`; отключения
проверки нет. `cert_file` принимает PEM-сертификат, в том числе объединённый с
ключом; отдельный `key_file` требует `cert_file`. Учётные данные внутри URL,
query/fragment, URL с путём, редиректы и некорректная конфигурация запрещены.
HTTP поддерживается для локального либо отдельно защищённого транспорта.
Параметр `timeout` задаёт connect/read timeout каждого HTTP-запроса, не общий
deadline составной операции.

## Операторские команды

Начальное отсутствие состояния запрещает автоматическую работу. Инициализация
создаёт только заблокированное состояние; повторная команда ничего не меняет:

```sh
powerops-watcher-guard --config-file /etc/powerops/guard.conf initialize \
  --actor operator@example --reason 'Initial setup'
powerops-watcher-guard --config-file /etc/powerops/guard.conf status
```

После проверки восстановления оператор передаёт **ревизию из свежего `status`**:

```sh
powerops-watcher-guard --config-file /etc/powerops/guard.conf resume \
  --expected-revision 42 --actor operator@example \
  --reason 'Host recovery verified' --acknowledge-recovery
```

Число `42` — пример, его нельзя копировать вместо фактической ревизии.
Конкурентный инцидент отклоняет устаревший resume. Каждый успешный resume
создаёт новый UUID epoch, в том числе если состояние уже было разрешающим.
Успех: JSON в stdout и код 0. Отказ: JSON в stderr и ненулевой код;
ошибки backend/config не раскрывают исходные исключения или endpoint credentials.
Ни установка пакета, ни вызов `register_opts` не инициализируют и не снимают hold.

## API и гарантии

```python
from powerops_watcher_guard.gate import Gate, GuardDenied

gate = Gate('https://etcd.example:2379', ca_file='/etc/powerops/etcd-ca.pem')
gate.hold(incident_id='d3825d99-911a-46ca-b2b3-9250b50908fb', host='compute-1')

# Вызывающий код прекращает автоматическую операцию при любом GuardDenied.
epoch = gate.admit()                 # до расчёта CONTINUOUS audit
gate.admit(expected_epoch=epoch)     # перед запуском плана / новой action
```

- `status()`, `initialize(actor, reason)`, `hold(incident_id, host, reason=...)`,
  `resume(expected_revision, actor, reason)` возвращают словарь состояния с
  целочисленной `revision`; `admit(expected_epoch=None)` возвращает UUID epoch.
- Под `prefix/state` хранится JSON `schema=1`, `epoch`, `blocked`, `incident_id`,
  `host`, `actor`, `reason`. До первого инцидента `incident_id` и `host` равны null.
  После resume сведения о последнем инциденте сохраняются.
- `hold` атомарно пишет новый blocked epoch и постоянный маркер
  `prefix/incidents/<UUID>`. До восьми попыток разрешают только CAS-коллизии.
  Повтор того же UUID, даже после resume и пересоздания клиента, не ставит hold.
  Маркеры не удаляются автоматически: их рост и резервное копирование относятся
  к эксплуатации etcd. Удаление маркеров нарушает пожизненную дедупликацию.
- Все чтения линейны. Admission сравнивает прочитанную mod_revision и повторно
  читает состояние внутри одной etcd-транзакции. Конфликт не повторяется в новой
  генерации. У клиента нет кеша разрешающего состояния.
- Состояние и маркеры не имеют lease/TTL; ключи с lease отклоняются. Отсутствующие,
  повреждённые или недоступные данные запрещают автоматическую работу.
  `GuardUnavailable` и `GuardConflict` наследуют `GuardDenied`.
- Timeout/потеря ответа не повторяют запись автоматически: операция могла уже
  выполниться. Для hold безопасен явный повтор с тем же UUID. Для resume нужно
  заново прочитать состояние и проверить восстановление.
- Admission и hold упорядочены транзакциями etcd. Уже разрешённая перед hold
  операция может обратиться к Nova позже. Этот пакет не отменяет, не дренирует
  и не откатывает запущенные операции и не гарантирует полного отсутствия миграций.

Идентификатор инцидента и epoch — UUID в стандартной форме с дефисами; регистр
входного UUID нормализуется. Actor/host ограничены 255 символами, reason — 1024,
prefix — 1024, endpoint — 2048. Пустые строки, управляющие символы и некорректный
Unicode запрещены. `expected_revision` — положительное целое число.

Протокол: [etcd v3 API](https://etcd.io/docs/v3.5/learning/api/) и
[JSON gateway](https://etcd.io/docs/v3.5/dev-guide/api_grpc_gateway/).

## Локальные тесты

Из каталога пакета, после установки зависимостей:

```sh
python3.11 -m unittest discover -s tests
```

Интеграционные тесты по умолчанию пропущены. Для **одноразового локального etcd**:

```sh
POWEROPS_GUARD_TEST_ENDPOINT=http://127.0.0.1:32379 \
  python3.11 -m unittest discover -s tests
```

Допустим только loopback endpoint. Каждый тест создаёт случайный namespace
`/powerops-guard-test/<UUID>/` и удаляет только его. Тесты проверяют CAS,
конкурентные admissions/hold по фактическим ревизиям etcd, resume против нового
инцидента, два конкурентных инцидента и пересоздание клиента. Unit-тесты отдельно
задают неблагоприятный порядок транзакций, потерю ответа после commit и повреждения
протокола. Эти проверки не являются испытанием кворума, аварийного восстановления
кластера или проверкой live OpenStack.
