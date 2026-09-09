# Универсальная диагностика PowerOps одним файлом

В единой ветке main сохранены два независимых автономных плейбука:

- [collect-v2.yml](collect-v2.yml) — вся цепочка PowerOps; описание ниже.
- [collect-mistral.yml](collect-mistral.yml) — Mistral API, 504, executions,
  контроллеры, HAProxy и RPC/БД-диагностика. Его переменные имеют префикс
  `mistral_diag_`, их defaults находятся в начале самого YAML.

Оба создают приватный TXT в `artifacts/` рядом с запущенным плейбуком; дата
вычисляется при запуске. `PARTIAL` и недоступный узел не означают успех операции.
В Mistral-сборщике есть получение временного Keystone-токена для чтения API и
ограниченные диагностические команды внутри контейнеров; ограничения разделов
ниже, относящиеся к collect-v2, не следует автоматически переносить на него.
Токен не должен попадать в отчёт. Полученный TXT всё равно конфиденциален.

```bash
ansible-playbook collect-mistral.yml
```

## Локальные проверки обоих плейбуков

Из корня репозитория, в Python-окружении с Ansible, PyYAML и Jinja2:

```bash
python3 -m unittest discover -s tools/diagnostics/tests -v
python3 -m unittest discover -s tools/diagnostics/tests_mistral -v
POWEROPS_RUN_ANSIBLE_TEST=1 python3 -m unittest discover -s tools/diagnostics/tests -v
MISTRAL_DIAG_RUN_ANSIBLE=1 python3 -m unittest discover -s tools/diagnostics/tests_mistral -v
ansible-playbook tools/diagnostics/collect-v2.yml --syntax-check
ansible-playbook tools/diagnostics/collect-mistral.yml --syntax-check
```

Integration-тесты используют fixtures и loopback/подставленные команды, не стенд.
Проверка настоящего CLI parser включается отдельно через
`POWEROPS_REAL_OPENSTACK=/path/to/venv/bin/openstack`; сетевой доступ внутри
этой проверки запрещён. Не заменяйте тестовые команды запуском playbook с
настоящим inventory: это уже сбор на стенде, а не локальный тест.

## collect-v2: запуск и состав

Скопируйте только `collect-v2.yml` на операторский узел (в этом стенде — ultra1-0).
Плейбук содержит inventory и Python-сборщик, создаёт один приватный UTF-8 TXT,
без архива. Подходит для диагностики планового выключения/включения, миграции,
аварийного fencing/эвакуации, включая сценарии без ВМ. Не выполняет сами операции.

## Запуск

```bash
ansible-playbook collect-v2.yml
```

Запускайте обычным пользователем в окружении, где работают команды OpenStack.
Не запускайте весь плейбук через sudo: API использует авторизацию оператора.
SSH — по существующим ключам; пользователь из текущего окружения/SSH config.
При необходимости укажите `-u USERNAME`; если пароль нужен sudo — `-K`.

На операторе нужны Ansible, Python 3.8+, OpenStack CLI с Masakari, Ironic и
Mistral plugins. На удалённых узлах — Python 3.8+, SSH и sudo для системных
журналов/rootful Podman. Плейбук ничего не устанавливает, образы не пересобирает.

Встроенные соответствия взяты из переданного inventory 0809:

| Идентификатор хоста | Management/LAN IP для SSH |
|---|---|
| ultra1-2.ultra1.test.pvs.un.sbt | 10.101.25.146 |
| ultra1-3.ultra1.test.pvs.un.sbt | 10.101.25.147 |
| ultra1-6.ultra1.test.pvs.un.sbt | 10.101.25.150 |
| ultra1-7.ultra1.test.pvs.un.sbt | 10.101.25.151 |
| ultra1-8.ultra1.test.pvs.un.sbt | 10.101.25.152 |

Это не BMC-адреса. Для SSH не нужен DNS; API продолжает использовать полные
имена объектов. Host-key checking не отключается. Перед чтением привилегированных
журналов выполняется `hostname -f` без sudo: несовпадение имени или недоступность
фиксируется в TXT, сбор остальных узлов продолжается. SSH здесь — транспорт и
проверка идентичности источника логов, не доказательство безопасности хоста/ВМ.

В конце выводится путь `artifacts/powerops-diag-XXXXXXXX.txt` рядом с плейбуком.
Файл имеет права 0600, каталог — 0700. Сначала прочитайте сводку:

- `PARTIAL` — ошибки, таймауты, недоступные узлы, скрытые поля или усечение сбора;
  это не автоматический диагноз облака.
- `COLLECTED` — не обнаружено признаков неполноты собранных источников; это
  не подтверждение успешного fencing/эвакуации.
- Exit code 0 Ansible не означает отсутствия ошибок внутри TXT.

## Что собирается

- Masakari: автоматическое обнаружение segments/hosts; уведомления отдельно по
  UUID заданных compute-хостов; детали уведомлений и VMove. Старые уведомления
  сохраняются в списках, но не выдаются за свидетельство нового отказа.
- Ironic: node show для каждого compute по имени, опционально по явному UUID.
  Только uuid/name, power_state, target_power_state, last_error, provision_state,
  network_interface, maintenance. `driver_info` не запрашивается. Скрытый политикой
  last_error отмечается как неполные данные, не как отсутствие ошибки.
- Nova: service state/status, текущие ВМ и история миграций по исходному/целевому
  хосту за интервал. UUID обнаруживаются из этих списков, VMove и первого снимка.
  Для найденных и явно указанных ВМ — состояние, размещение, события и миграции.
  Так учитывается ВМ, покинувшая исходный хост до запуска диагностики.
- Mistral: PowerOps executions, input/output, задачи и подробности/result задач
  ERROR/RUNNING/PAUSED. Автоотбор учитывает время и host во входных параметрах.
  RUNNING/PAUSED могут быть старше интервала. Явный workflow UUID позволяет
  собрать запуск, не попавший в ограниченную выборку.
- Узлы: FQDN/UTC/uptime, timedatectl, chrony tracking/sources и журнал синхронизации.
- Podman: версия, список контейнеров, image ID, PID, exit code, Error, OOMKilled,
  время старта/завершения. Журналы ядра, podman.service/socket, conmon — для
  диагностики смерти/зависания контейнеров.
- Ограниченное чтение файлов журналов Masakari, Ironic, Nova, Mistral, Consul,
  etcd, RabbitMQ в /var/log/kolla, включая .gz-ротации, и podman logs за интервал.
  Продолжения traceback сохраняются с настоящими переводами строк.

API читаются до и после сбора журналов, каждый запрос имеет время начала/окончания.
Это неатомарные снимки текущего состояния: они не восстанавливают состояние до
аварии. Один power off не доказывает stable-off. Пустой список ВМ нормален;
отсутствие эвакуации при отсутствии ВМ само по себе не ошибка.

Прямых запросов к BMC/libvirt/etcd KV, проверки stale domains или доказательства
владения блокировкой нет. Tooz/Consul/etcd/RabbitMQ исследуются через журналы;
сборщик не делает вывод о безопасности операций только по SSH-доступности.

## Настройки без привязки к инциденту

По умолчанию — последний час на момент запуска, без заданных дат и UUID.
Имя секции `diag_incident` сохранено для совместимости. Для конкретного интервала:

```bash
ansible-playbook collect-v2.yml -e '{"diag":{"since":"2026-09-08T13:00:00+03:00","until":"2026-09-08T15:00:00+03:00"}}'
```

Дополнительные параметры можно добавлять в секцию в начале YAML или в объект
`diag` через -e:

| Настройка | Назначение / default |
|---|---|
| since, until | ISO8601 с Z или явным смещением; по умолчанию последний час |
| log_timezone | +00:00 для строк логов без timezone, не зона рабочего стола |
| compute_hosts | Полные API-имена compute; по умолчанию ultra1-2 и ultra1-3 |
| segment_id, notification_id, node_id | Необязательные точные UUID |
| server_ids, workflow_ids | Необязательные списки UUID |
| max_segments, max_notifications | 20 сегментов; 10 уведомлений на хост |
| max_servers, max_migrations | 30 подробных ВМ; 30 миграций на хост |
| max_workflows, max_tasks, max_vmoves | 10 executions; 30 задач на execution; 50 VMove на notification |
| command_timeout, api_timeout | 25 / 20 секунд на subprocess |
| total_timeout | 240 секунд на каждый API/host сборщик |
| max_command_bytes, max_file_bytes | 256 KiB / 512 KiB |
| max_scan_bytes, max_total_bytes | 8 MiB сканирования файла / 8 MiB данных на сборщик |
| max_files, max_containers, container_log_lines | 48 / 24 / 3000 |

API-история миграций по хосту требует Nova microversion 2.66+ и разрешённых
политикой чтений. Версия передаётся только конкретному CLI-запросу. Отказ версии,
прав или plugin сохраняется в отчёте, настройки облака не меняются.

Отсутствующее auth-окружение прекращает повторение API-команд, но не сбор логов.
401/403 одного сервиса не отключает независимые сервисы. В сводке различаются
auth_config/authentication/permission, missing_plugin, DNS/SSH key/SSH auth/sudo,
timeout/connection. Это категории ошибок сбора, не диагноз первопричины.

Для другого набора узлов измените `diag_default_hosts`, `diag_ssh_hosts` и API-список
`compute_hosts`. Отдельный inventory не нужен. Если явно передать inventory с
группой powerops_diag, используются её подключения; ожидаемый FQDN можно задать
как diag_expected_fqdn. Дополнительные параметры: diag_hosts, diag_python,
diag_output_parent, diag_become. Не отключайте become для root-only источников.
Не исключайте localhost через --limit. Имена localhost/api/api_after зарезервированы.

## Ограничения полноты

Лимиты обнаружения ограничивают разбираемые записи и последующие detail-запросы.
У Masakari CLI --limit может быть размером страницы: SDK способен прочитать
несколько страниц перед выдачей JSON. Процесс всё равно ограничен временем и
объёмом stdout. Усечённый JSON не используется для автоматического обнаружения.
Mistral сначала ограничивает общую выборку executions, затем фильтрует PowerOps/
хосты. Для не попавшего туда запуска доступны явный UUID и увеличенные лимиты.

Обычные файлы читаются с конца в пределах max_scan_bytes, gzip — ограниченным
распакованным префиксом. Усечение отмечается; отсутствие совпадений не доказывает
отсутствие события. unparsed_time сохраняет ограниченный нефильтрованный fallback.
Ошибка чтения существующего каталога журналов не скрывается. Достижение лимита
строк journalctl/podman logs помечается как возможное усечение.

Интервал журналов/автоотбора фиксируется при старте. Новые события после until
могут не попасть в автоотбор второго API-снимка: для продолжающегося теста сделайте
повторный сбор. Уже найденные UUID ВМ/workflow отслеживаются во втором снимке.

total_timeout не равен времени всего playbook: два API-прохода, параллельный сбор
узлов (Ansible forks), SSH/sudo и служебные задачи добавляют время. При таймауте
завершается только запущенная группа диагностического subprocess, не службы.
--check намеренно отклоняется; --syntax-check проверяет YAML без SSH/API.

## Безопасность

Нет restart/reconfigure, scheduling/maintenance изменений, питания, миграции,
эвакуации, reset-state, удаления блокировок. Не читаются полные inspect/Env/Config,
healthcheck output, RC-файлы, BMC driver_info и полное окружение. Нет --debug и
специальной команды token issue.

Типовые password/token/secret/Authorization/cookie, URL credentials и PEM private
keys маскируются до передачи Ansible; секретные значения из окружения сборщика
также маскируются. Незавершённая строка subprocess при усечении исключается.
Очистка произвольных логов не гарантируется: TXT конфиденциален, проверьте его
перед передачей. Без no_log выполняется только SSH/FQDN preflight, не чтение логов.
Текст Ironic "Rejecting authorization: baremetal:... is disallowed by policy"
сохраняется, HTTP Authorization маскируется.

На узлах создаются обычные временные файлы Ansible. На операторе sanitized JSON
сохраняются в новом закрытом каталоге и удаляются после успешной записи TXT.
При прерывании могут остаться промежуточные файлы. Предыдущие результаты не
перезаписываются и не удаляются.

## Локальная проверка, не стендовая приёмка

Из каталога tools/diagnostics:

```bash
python3 -m unittest discover -s tests -v
POWEROPS_RUN_ANSIBLE_TEST=1 python3 -m unittest discover -s tests -p test_playbook.py -v
POWEROPS_REAL_OPENSTACK=/path/to/venv/bin/openstack python3 -m unittest discover -s tests -p test_real_cli.py -v
ansible-playbook collect-v2.yml --syntax-check
```

Unit-тесты подменяют внешние subprocess ответы, а не построение команд/обработку
результатов. Сквозные тесты копируют только YAML в пустой каталог: фиктивный
OpenStack, localhost, закрытый порт 127.0.0.1 и fake SSH вместо стенда. Проверяются
два API-снимка, недоступные узлы, неверный FQDN, auth failure, маскирование,
traceback, один TXT, scoped cleanup и подключение по IP без отключения host keys.

Отдельный тест проверяет точное совпадение встроенного Python с files/collect.py.
Разработческие исходники/tests не требуются для запуска единственного YAML.

Команды проверяются настоящими command-manager/parser OpenStack CLI 7.5.0,
python-masakariclient 8.9.0, python-ironicclient 6.3.0 и python-mistralclient 5.4.0.
Сетевые соединения в этом тесте запрещены. Это проверка регистрации и синтаксиса
команд, не исполнения API в облаке. Локальные проверки не заменяют запуск на стенде.
