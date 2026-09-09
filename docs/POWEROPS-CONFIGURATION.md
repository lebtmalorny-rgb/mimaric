# PowerOps: справочник конфигурации

Справочник описывает существующий PowerOps для OpenStack 2025.1: аварийное восстановление Masakari, плановые действия Mistral, Ironic как backend управления питанием и их настройку через Kolla-Ansible. Значения из исходников и шаблонов не являются результатом чтения работающего стенда.

Общая схема и сценарии: [POWEROPS-OVERVIEW.md](POWEROPS-OVERVIEW.md). Проверка загруженных параметров и разбор отказов: [POWEROPS-DIAGNOSTICS.md](POWEROPS-DIAGNOSTICS.md).

## 1. Источники и правила чтения таблиц

Срез проверен 9 сентября 2026 года. Во всех ссылках ниже путь после префикса считается от корня соответствующего компонента:

| Префикс | Проверенный источник |
| --- | --- |
| `K/` | `kolla-ansible-enroll-ironic-patch-3_0809.zip`, каталог архива `kolla-ansible-enroll-ironic-patch-3`. Использованы именно его `ansible/`, `kolla_ansible/` и шаблоны. |
| `M/` | `mistral-integration-powerops-mistral-2025.1 _0809.zip` (с пробелом перед `_0809`), каталог `mistral-integration-powerops-mistral-2025.1`. Рабочие изменения тестов не использованы как изменения production-кода. |
| `A/` | `masakari-integration-powerops-masakari-2025.1_0809.zip` + post-fence patch; проверен `powerops-patches/worktrees/masakari-powerops`, HEAD `aabc8c0a9a874c798ff0c50139d15ed10472bd77`. Этот срез содержит ожидание Nova после fencing. |
| upstream | Официальная документация/исходники 2025.1 по приведённым веб-ссылкам. Версии пакетов и переопределения в запущенных образах не проверены. |

Основной файл переменных Kolla — `K/ansible/group_vars/all.yml`; значения роли — `K/ansible/roles/<role>/defaults/main.yml`. Закомментированная строка в `etc/kolla/globals.yml` является примером, а не действующей настройкой. Пользовательские globals, inventory и дополнительные INI-файлы могут переопределить перечисленные значения. Резервные копии globals не использованы как снимок стенда.

Контрольные суммы входных архивов и дополнительного патча приведены в разделе 9 [POWEROPS-OVERVIEW.md](POWEROPS-OVERVIEW.md).

В таблицах «код → Kolla» означает: default зарегистрированной опции компонента → значение, которое выдаст указанный шаблон при штатных переменных этого среза и включённом PowerOps. `None` означает отсутствие заданного default. Типы `int`, `float`, `bool`, `list[str]` относятся к опциям приложения; Ansible может получать их из YAML-строк.

Способ применения:

| Обозначение | Что нужно изменить |
| --- | --- |
| `C` | Значение поддерживаемой конфигурации: globals/INI override, затем согласованный deploy/reconfigure соответствующих сервисов. Новый Python-код не нужен. Проверить конечный файл и загруженное значение на каждой реплике. |
| `I` | Образ с нужным кодом/зависимостями и его развёртывание. Добавление строки INI не добавляет отсутствующую реализацию. |
| `D` | Только настройки Ansible при deploy/reconfigure/reconciliation; не параметры запущенного workflow. |
| `E` | Повторная согласованная регистрация/обновление узла Ironic; изменение ресурса через API, а не INI. |

Ни один из этих способов в рамках подготовки документа не выполнялся.

## 2. Включение, образы и доставка

Эти параметры объявлены в `K/ansible/group_vars/all.yml`, блок `PowerOps options`. В этом блоке 24 переменные: включение, 15 общих параметров/переключателей и 8 полей образов.

| Переменная Kolla | Тип, default | Куда поступает и что делает | Риск/применение |
| --- | --- | --- | --- |
| `enable_powerops` | bool-подобное, `"no"` | `mistral.conf.j2` и `masakari.conf.j2`: `[powerops].enabled=true`; выбирает специальные образы и подключает проверки/каталог. При выключении секция не рендерится. | Требует одновременно `enable_ironic`, `enable_masakari`, `enable_mistral`, `enable_etcd`. `C + I + D`. |
| `powerops_masakari_engine_image` | str, `""` | `roles/masakari/defaults/main.yml`: `masakari_services.masakari-engine.image`. | Непустое имя образа обязательно при включении. `I`. |
| `powerops_masakari_engine_tag` | str, `""` | Там же, итог `<image>:<tag>`. | Пустой tag отклоняет precheck. Версия должна содержать нужную реализацию fencing. `I`. |
| `powerops_mistral_api_image` | str, `""` | `roles/mistral/defaults/main.yml`: image сервиса `mistral-api`. | API тоже должен содержать PowerOps и правила авторизации. `I`. |
| `powerops_mistral_api_tag` | str, `""` | Там же, tag API. | Согласовать с engine/executor. `I`. |
| `powerops_mistral_engine_image` | str, `""` | Там же, image `mistral-engine`. | Проверять каждую реплику. `I`. |
| `powerops_mistral_engine_tag` | str, `""` | Там же, tag engine. | Непустое значение обязательно. `I`. |
| `powerops_mistral_executor_image` | str, `""` | Там же, image `mistral-executor`. | Именно executor выполняет PowerOps actions. `I`. |
| `powerops_mistral_executor_tag` | str, `""` | Там же, tag executor. | Изменение только API-образа не обновляет actions executor. `I`. |
| `powerops_reconcile_workbook` | bool-подобное, `"yes"` | `roles/mistral/tasks/powerops.yml`: читает `roles/mistral/files/power_ops.yaml`, создаёт или обновляет workbook `power_ops`. | Изменяет каталог Mistral при доставке; не запускает операции питания. `D`. |
| `powerops_validate_registration` | bool-подобное, `"yes"` | Там же, сверяет регистрацию actions/workflows через API. | Выключение снимает эту проверку, но не меняет runtime-авторизацию. `D`. |

Dependencies проверяются в `K/ansible/roles/prechecks/tasks/powerops_checks.yml` и `roles/{mistral,masakari}/tasks/precheck.yml`. Для allowlists precheck требует непустые списки непустых строк без запятых и внешних пробелов; для четырёх образов — непустые строки image/tag. Это не проверка результата fencing или миграции.

Специального PowerOps image-переключателя для Ironic, Masakari API и Mistral event-engine в указанном блоке нет. Их штатная доставка остаётся частью Kolla. Значение `enable_etcd` в `K/ansible/group_vars/all.yml` по умолчанию `"no"`; одно изменение `enable_powerops` не включает зависимости автоматически.

## 3. Полное соответствие Mistral `[powerops]`

Все 15 опций зарегистрированы в `M/mistral/config.py:powerops_opts`. Шаблон `K/ansible/roles/mistral/templates/mistral.conf.j2` рендерит их для `mistral-api`, `mistral-engine`, `mistral-executor`. Выходной файл контейнера — `/etc/mistral/mistral.conf`.

| Переменная / источник | Выходная опция | Тип / единица / минимум | Default: код → Kolla | Использование и риск | Применение |
| --- | --- | --- | --- | --- | --- |
| `enable_powerops` | `[powerops].enabled` | bool | `false → true` | `base.py:_run_locked`, status action и API-guard: без включения действия отклоняются. | `C + I` |
| `powerops_coordination_url` | `[powerops].coordination_url` | secret str | `None →` etcd3 HTTP(S), внутренний endpoint, `api_version=v3`, опционально CA | `coordination.py:OperationCoordinator.start`; только схемы `etcd3+http`/`etcd3+https`, распределённый линейризуемый backend. Полный URL может содержать секреты. | `C` |
| `powerops_host_lock_timeout` | `[powerops].host_lock_timeout` | float / с / ≥0.1 | `30.0 → 30` | `coordination.py:lock_host`: ожидание захвата `powerops/host/<host>`. Не TTL и не предел длительности операции. | `C` |
| `powerops_power_timeout` | `[powerops].power_timeout` | int / с / ≥1 | `180 → 180` | `clients.py`: поиск Ironic node, hard-off, power-on и проверка stable-on. Новый бюджет на соответствующий шаг. | `C` |
| `powerops_poll_interval` | `[powerops].poll_interval` | int / с / ≥1 | `5 → 5` | `clients.py:_wait_until`: пауза между опросами, ограниченная остатком бюджета. Меньше — больше API-запросов. | `C` |
| `powerops_stable_observations` | `[powerops].stable_observations` | int / наблюдения / ≥2 | `3 → 3` | `_wait_until`: последовательные подходящие состояния питания, сервисов и подтверждение live migration; несовпадение сбрасывает счётчик. Для stop/start ВМ явно задано `observations=1`. | `C` |
| `powerops_graceful_shutdown_timeout` | `[powerops].graceful_shutdown_timeout` | int / с / ≥1 | `300 → 300` | `clients.py:power_off`: бюджет soft power off. Hard-off возможен лишь после допустимого истечения ожидания и с `allow_hard_off=true`. | `C` |
| `powerops_vm_action_timeout` | `[powerops].vm_action_timeout` | int / с / ≥1 | `600 → 600` | `clients.py`, `live_migration.py:LiveMigrationWaiter.run`: stop/start/migrate одной ВМ, чтение inventory и повторная проверка перед выключением. Не лимит на весь список ВМ. | `C` |
| `powerops_service_timeout` | `[powerops].service_timeout` | int / с / ≥1 | `300 → 300` | `clients.py`: resolve набора Nova/Ironic/Masakari, disable/enable Nova, maintenance Masakari, ожидание состояния сервисов. На отдельные методы выдаются отдельные бюджеты. | `C` |
| `powerops_instance_interval` | `[powerops].instance_interval` | int / с / ≥0 | `5 → 5` | `clients.py:_pace_instances`: пауза после успешной stop/start/migrate ВМ, в том числе последней реально обработанной. `0` убирает паузу. | `C` |
| `openstack_region_name` | `[powerops].region_name` | str | `RegionOne → openstack_region_name` | `clients.py:connection_from_conf`, HA adapter: выбор региона каталога. | `C` |
| Литерал шаблона; отдельной globals-переменной нет | `[powerops].interface` | str | `internal → internal` | SDK connection и HA adapter выбирают internal endpoint. Для иной сети нужен поддержанный INI override. | `C` |
| Литерал шаблона; отдельной globals-переменной нет | `[powerops].nova_disable_reason` | str | `PowerOps planned operation →` то же | `planned.py`, `return_host.py`, `base.py:_fail_safe`: причина административного disable. Не маркер эксклюзивного владения ресурсом. | `C` |
| `powerops_allowed_project_names` | `[powerops].allowed_project_names` | list[str] | `[] → [openstack_auth.project_name]` | `services/powerops.py:authorize`: точное имя проекта для оператора без admin; шаблон соединяет список запятыми. | `C` |
| `powerops_allowed_user_names` | `[powerops].allowed_user_names` | list[str] | `[] → [openstack_auth.username]` | Там же, точное имя пользователя; требуется одновременно с проектом и ролью. | `C` |

В таблице пути `base.py`, `clients.py`, `planned.py`, `return_host.py`, `live_migration.py`, `coordination.py` относятся к `M/mistral/actions/powerops/`.

Тот же шаблон записывает `powerops_coordination_url` в `[coordination].backend_url` всех Mistral-сервисов. Сам PowerOps читает **`[powerops].coordination_url`**. Подмена только `[coordination].backend_url` не меняет адрес PowerOps coordinator. При выключенном PowerOps `[coordination].backend_url` получает `redis_connection_string`; это не разрешение использовать Redis для PowerOps.

## 4. Полное соответствие Masakari `[powerops]`

Все 10 опций зарегистрированы в `A/masakari/conf/powerops.py`. Шаблон `K/ansible/roles/masakari/templates/masakari.conf.j2` пишет `[powerops]` только для `masakari-engine`; `/etc/masakari/masakari.conf` — итоговый файл контейнера. `[coordination].backend_url` при включении PowerOps рендерится и для API, и для engine.

| Переменная / источник | Выходная опция | Тип / единица / минимум | Default: код → Kolla | Использование и риск | Применение |
| --- | --- | --- | --- | --- | --- |
| `enable_powerops` | `[powerops].enabled` | bool | `false → true` | Выбор fencing, обязательных locks и последовательной эвакуации; старый образ не получает эту реализацию от INI. | `C + I` |
| `powerops_host_lock_timeout` | `[powerops].host_lock_timeout` | float / с / ≥0.1 | `30.0 → 30` | `engine/drivers/taskflow/driver.py`: захват `powerops/host/<host>` вокруг host-failure flow. | `C` |
| `powerops_evacuation_lock_timeout` | `[powerops].evacuation_lock_timeout` | float / с / ≥1 | `3600.0 → 3600` | `host_failure.py`: ожидание глобального `powerops/evacuation/global` перед каждой ВМ. Это время ожидания очереди, не время эвакуации и не TTL. | `C` |
| `powerops_evacuation_interval` | `[powerops].evacuation_interval` | int / с / ≥0 | `5 → 5` | `host_failure.py`: пауза после успешно подтверждённой эвакуации, пока глобальный lock удерживается. Выполняется и после последней ВМ. | `C` |
| `powerops_power_timeout` | `[powerops].power_timeout` | int / с / ≥1 | `180 → 180` | `IronicFenceTask.execute → IronicPowerClient.fence`: один бюджет на поиск node, отправку off и stable-off. | `C` |
| Нет mapping в Kolla0809 | `[powerops].nova_down_timeout` | int / с / ≥1 | `180 →` не рендерится, действует code default | `IronicFenceTask._wait_for_nova_down`: отдельный бюджет после подтверждения off; требуется ровно один точный `nova-compute`, `status=disabled`, `state=down`. | `I` для появления функции; затем `C` через INI override |
| `powerops_poll_interval` | `[powerops].poll_interval` | int / с / ≥1 | `5 → 5` | Опрос Ironic и ожидание Nova down. Не определяет, когда сама Nova признает сервис down. | `C` |
| `powerops_stable_observations` | `[powerops].stable_off_observations` | int / наблюдения / ≥2 | `3 → 3` | `IronicPowerClient.fence`: последовательные согласованные off. На новый Nova-down gate это число не распространяется: достаточно одного допустимого ответа. | `C` |
| `openstack_region_name` | `[powerops].region_name` | str | `RegionOne → openstack_region_name` | `powerops/ironic.py:connection_from_conf`: регион Ironic SDK. Nova-client использует отдельно `[DEFAULT].os_region_name`. | `C` |
| Литерал шаблона | `[powerops].interface` | str | `internal → internal` | Там же, интерфейс Ironic SDK. Не заменяет `[DEFAULT].nova_catalog_admin_info`. | `C` |

Пути `driver.py`, `host_failure.py`, `powerops.py` в этом разделе относятся к `A/masakari/engine/drivers/taskflow/`. Источник fencing — `A/masakari/powerops/ironic.py`; координатор — `A/masakari/powerops/coordination.py`.

`powerops_coordination_url` → шаблон `masakari.conf.j2` → `[coordination].backend_url` → `PowerOpsCoordinator.start`. Code default этой опции — `None` (`A/masakari/conf/coordination.py`). Нужен тот же backend, что и в Mistral, иначе одинаковые имена locks не дают общего исключения операций.

### Порядок recovery tasks — часть конфигурационного контракта

В `K/ansible/roles/masakari/templates/masakari.conf.j2` при включённом PowerOps заданы:

```ini
[taskflow_driver_recovery_flows]
host_auto_failure_recovery_tasks = pre:['disable_compute_service_task', 'ironic_fence'],main:['prepare_HA_enabled_instances_task'],post:['evacuate_instances_task']
host_rh_failure_recovery_tasks = pre:['disable_compute_service_task', 'ironic_fence'],main:['prepare_HA_enabled_instances_task', 'evacuate_instances_task'],post:[]
```

Upstream defaults в `A/masakari/conf/engine_driver.py` не содержат `ironic_fence`. Проверка `A/masakari/engine/drivers/taskflow/base.py:validate_powerops_host_flow` требует безопасный порядок, а загрузка tasks выполняется строго. Одного `[powerops].enabled=true` при старом порядке недостаточно. Удаление fencing меняет контракт и не является настройкой производительности.

### Параметры Masakari, унаследованные аварийным flow

Ниже значения подтверждены локальным кодом `A/masakari/conf/engine.py` и `engine_driver.py`. В Kolla0809 отдельного globals mapping и строк в `masakari.conf.j2` для них нет: при необходимости применяется INI override (`C`).

| Секция.опция | Тип / default | Реальное использование / ограничение |
| --- | --- | --- |
| `[DEFAULT].wait_period_after_service_update` | int, `180` с | `DisableComputeServiceTask.execute`: фиксированный sleep сразу после disable Nova и **до** fencing. Не проверяет service down. Новый `nova_down_timeout` его не заменяет. |
| `[DEFAULT].wait_period_after_evacuation` | int, `90` с | `_evacuate_and_confirm`: ожидание переноса ВМ на иной допустимый host, очищенного task_state и требуемого vm_state. Бюджет петли начинается после вызова API эвакуации. |
| `[DEFAULT].verify_interval` | int, `1` с | Интервал `FixedIntervalWithTimeoutLoopingCall` при подтверждении эвакуации/остановки ВМ. Не интервал Ironic. |
| `[DEFAULT].wait_period_after_power_off` | int, `180` с | `_stop_after_evacuation`: остановка конкретной ВМ после восстановления, когда требуется восстановить исходное состояние. Не physical-host power timeout. |
| `[DEFAULT].wait_period_after_power_on` | int, `60` с | Унаследованное восстановление instance-failure; текущий PowerOps host-fencing flow этим параметром не управляет. |
| `[DEFAULT].host_failure_recovery_threads` | int, `3`, min 1 | Используется GreenPool только в ветке `powerops.enabled=false`; PowerOps-ветка обходит пул и выполняет ВМ последовательно под глобальным lock. Значение `1` не заменяет PowerOps pacing. |
| `[DEFAULT].duplicate_notification_detection_interval` | int, `180` с, min 0 | `A/masakari/ha/api.py`: окно фильтрации одинаковых notifications со статусом new/running. Не lock. |
| `[DEFAULT].process_unfinished_notifications_interval` | int, `120` с | `A/masakari/engine/manager.py`: периодический разбор незавершённых notifications. Не автоматический безопасный повтор любой BMC-команды. |
| `[DEFAULT].retry_notification_new_status_interval` | int, `60` с, mutable | Там же, возраст notification в new для повторной обработки. Сверять совместно с очередями и периодической задачей. |
| `[DEFAULT].check_expired_notifications_interval` | int, `600` с | Там же, период поиска просроченных running notifications. |
| `[DEFAULT].notifications_expired_interval` | int, `86400` с | Там же, возраст running notification для признания просроченной. Не общий гарантированный deadline host-failure flow. |
| `[host_failure].evacuate_all_instances` | bool, `true` | `PrepareHAEnabledInstancesTask`: включает и ВМ без HA-метки. Поэтому default не означает «эвакуировать только HA_Enabled». |
| `[host_failure].ha_enabled_instance_metadata_key` | str, `HA_Enabled` | Имя признака HA в metadata ВМ. |
| `[host_failure].ignore_instances_in_error_state` | bool, `false` | При true исключает error-ВМ из отбора; влияет на полноту восстановления. |
| `[host_failure].add_reserved_host_to_aggregate` | bool, `false` | Для reserved-host flow: добавление выбранного резерва в aggregate исходного host. |
| `[host_failure].service_disable_reason` | str, `Masakari detected host failed.` | Причина disable Nova в аварийном сценарии. Отличается от причины плановой операции Mistral. |

## 5. Locks, heartbeat, параллелизм и кэш

### Разные механизмы heartbeat

| Механизм | Параметры / default | Кто использует | Чего он не подтверждает |
| --- | --- | --- | --- |
| PowerOps distributed lock | `host_lock_timeout=30`, `evacuation_lock_timeout=3600` | Mistral/Masakari wrappers вызывают tooz `start(start_heart=True)`, проверяют `heart.is_alive()` и владение lock через etcd transaction. | Значения timeout задают ожидание acquire, а не срок lease. Живой heartbeat-поток сам по себе не доказывает сохранность lock. |
| Mistral action heartbeat | `[action_heartbeat].check_interval=20` с; `max_missed_heartbeats=15`; `batch_size=10`; `first_heartbeat_timeout=3600` с | `M/mistral/services/action_heartbeat_sender.py`, `action_heartbeat_checker.py`, `db/v2/sqlalchemy/models.py`. `check_interval=0` или `max_missed_heartbeats=0` выключает механизм; `batch_size=0` снимает лимит пачки. | Это состояние выполнения action в Mistral, не владение etcd-lock, не состояние ВМ/питания. |
| Старая Mistral coordination-опция | `[coordination].heartbeat_interval=5.0` с | В `M/mistral/config.py` явно помечена unused/deprecated; Kolla0809 её не рендерит. | Не управляет PowerOps tooz heartbeat. |
| RabbitMQ heartbeat | `[oslo_messaging_rabbit].heartbeat_in_pthread`: Mistral `false`; Masakari/Ironic `true` только для API | Литералы соответствующих `.conf.j2`; механизм oslo.messaging. | Не health/readiness compute и не BMC timeout. Численные defaults interval/threshold библиотеки в установленном образе здесь не установлены. |
| Nova service heartbeat | `[DEFAULT].report_interval`, `service_down_time` | Nova; отдельно от Consul и Mistral, см. следующий раздел. | `status=disabled` не означает `state=down`. |

Mistral checker ищет heartbeat старше `20 × 15 = 300` секунд, с дискретностью проверок и ограничением пачки. В этой реализации `last_heartbeat` новой action инициализируется временем `now + first_heartbeat_timeout`; поэтому фактическая отсечка ещё не начатой action зависит также от обычного окна missed heartbeat и запуска checker. Число `3600` нельзя представлять как точный момент завершения action в ERROR. Источники defaults: `M/mistral/config.py:action_heartbeat_opts`; применения — файлы из таблицы.

Ни Mistral, ни Masakari в проверенных PowerOps-опциях не задают TTL lease, tooz heartbeat interval или отдельный timeout etcd HTTP. URL из Kolla содержит `api_version` и при необходимости CA, но не эти настройки. Их defaults зависят от реально установленных tooz/etcd3gw; `requirements.txt` задаёт диапазоны, а не полный pin пакетов. Численные значения не подтверждены. Нельзя считать, что `host_lock_timeout=30` автоматически продлевает lease каждые 30 секунд или ограничивает любую backend-проверку 30 секундами.

Host-lock удерживается Mistral внутри одного action, Masakari — вокруг аварийного host flow. Глобальный lock эвакуации Masakari сериализует отдельные ВМ между авариями разных hosts и удерживается во время паузы `evacuation_interval`. Плановые Mistral-операции разных hosts не берут этот глобальный evacuation-lock и могут идти параллельно. Административные операции напрямую в Nova/Ironic не становятся участниками PowerOps-lock автоматически.

### Кэш и достоверность наблюдений

`M/mistral/actions/powerops/clients.py:connection_from_conf` и `A/masakari/powerops/ironic.py:connection_from_conf` создают `openstack.connection.Connection` с session/region/interface. В обоих вызовах нет явного `cache=False`/отключения SDK response cache. Отдельной PowerOps globals/INI-опции управления этим кэшем в данном срезе нет.

Для `live_migrate` Mistral явно проверяет `connection.cache_enabled is False` (`live_migration.py:require_uncached`) и отклоняет действие при включённом кэше. Тот же guard участвует в проверке незавершённых миграций перед выключением. Для остальных повторных Ironic/Nova/Masakari чтений код не даёт общего доказательства принудительного обхода SDK-кэша. Само наличие трёх одинаковых ответов не доказывает три независимых обращения к BMC: Ironic API возвращает состояние ресурса, а собственный опрос BMC выполняет conductor.

Новый Nova-down gate Masakari использует отдельный `python-novaclient` и свежий `services.list`, без OpenStackSDK response cache (`A/masakari/compute/nova.py:get_compute_service`). Это свойство нельзя переносить на другие методы SDK.

Memcached из `[keystone_authtoken]` — кэш аутентификации; Mistral `[engine].action_definition_cache_time` (code default `60` с) — кэш определений actions. Ни тот, ни другой параметр не отключает SDK response cache. Для оценки его фактического состояния требуется проверка библиотеки и созданного клиента в образе.

## 6. Consul hostmonitor и Nova service down

Источники Kolla: `K/ansible/group_vars/all.yml`, `roles/masakari/defaults/main.yml`, `roles/masakari/templates/masakari-monitors.conf.j2`, `matrix.yaml.j2`, `K/kolla_ansible/masakari_consul.py`. Выход: `/etc/masakari-monitors/masakari-monitors.conf` и `/etc/masakari-monitors/matrix.yaml`.

| Переменная | Тип / default среза Kolla | Шаблон → выход / использование | Ограничение и применение |
| --- | --- | --- | --- |
| `masakari_hostmonitor_driver` | str; role default `default`, group_vars **`consul`** | `masakari-monitors.conf.j2` → `[host].monitoring_driver=consul` | Сверять итог после precedence. Другая ветка использует Pacemaker. `C`, при отсутствии драйвера в образе `I`. |
| `masakari_hostmonitor_monitoring_interval` | int, `60` с | Там же → `[host].monitoring_interval` | Интервал hostmonitor, отдельно от gossip probe. `C`. |
| `masakari_hostmonitor_monitoring_samples` | int, `1` наблюдение | Там же → `[host].monitoring_samples` | Порог последовательных наблюдений драйвера, не stable-off. `C`. |
| `masakari_consul_monitoring_interval` | int, `30` с | В role/group_vars объявлен, в рассматриваемых tasks/templates чтение не найдено | Изменение этого имени не меняет `[host].monitoring_interval`. |
| `masakari_consul_monitoring_samples` | int, `3` | Аналогично, объявлен без использования в рассматриваемом пути | Нельзя рассчитывать задержку hostmonitor как `30 × 3` по этим значениям. |
| `masakari_hostmonitor_consul_use_loopback` | bool, `true` | `masakari-monitors.conf.j2` → `[consul].agent_<masakari_name>` | При true адрес `127.0.0.1:<consul_http_port>`, иначе адрес соответствующей сети. Проверить достижимость именно из hostmonitor. `C`. |
| `masakari_consul_matrix_policy` | str, `all_down` | `matrix.yaml.j2` → `masakari_consul_matrix` → `sequence`, `matrix[].health/action` | `all_down`: все выбранные сети down; `majority_down`: строго больше половины; `threshold`: заданное число; `custom`: точные перечисленные комбинации. Меняет условия аварийного восстановления. `C`. |
| `masakari_consul_down_threshold` | int/null, `null` | Там же; только `policy=threshold`, диапазон `1..N` | Меньший порог допускает восстановление при меньшем числе недоступных сетей. `C`. |
| `masakari_consul_custom_recovery_states` | list[dict], `[]` | Там же; только `policy=custom` | Каждая запись должна содержать ровно все выбранные `masakari_name`, значения `up/down`. `C`. |
| `consul_networks` | map, `management/customer/storage` | `masakari-monitors.conf.j2` строит `agent_manage/agent_tenant/agent_storage`; фильтр матрицы использует enabled, masakari_monitor/name/order | Матрица зависит от реально включённых сетей, а не всегда от трёх. `C`. |
| Литерал шаблона | path | `[consul].matrix_config_file=/etc/masakari-monitors/matrix.yaml` | JSON-шаблон контейнера копирует matrix при `enable_consul`. Проверить совпадение файла с agent-набором. `C`. |

Официальные определения `[host]` подтверждают defaults `monitoring_interval=60`, `monitoring_samples=1`, а также не рендеримые Kolla0809 `[host].api_retry_max=12` и `[host].api_retry_interval=10` секунд для повторной доставки notification. Число попыток и интервал доставки — отдельный уровень; это не повтор эвакуации. Их фактическое применение конкретным образом hostmonitor не проверено. [Исходник masakari-monitors 2025.1, conf/host.py](https://raw.githubusercontent.com/openstack/masakari-monitors/stable/2025.1/masakarimonitors/conf/host.py).

### Сеть и параметры Consul, влияющие на детектирование

Активный путь — `K/ansible/roles/consul/tasks/config.yml` → **`templates/consul.hcl.j2`**, не старые `consul-server.hcl.j2`/`consul-agent.hcl.j2`. Выход на хосте: `{{ node_config_directory }}/consul-<network>/consul.hcl`; `consul.json.j2` копирует его в `/etc/consul.d/consul.hcl`.

| Вход Kolla | Default / тип | Выход HCL или результат | Ограничение / применение |
| --- | --- | --- | --- |
| `enable_consul` | `"yes"`, bool-подобное | Включение сервисов по сети и inventory | Не заменяет `enable_etcd`: у PowerOps locks другой backend. `C`. |
| `consul_management_enabled`, `consul_customer_enabled`, `consul_storage_enabled` | default `true` внутри `consul_networks` | `network.enabled`, выбор контейнера/матрицы | `roles/consul/tasks/main.yml` выполняет автоопределение до precheck. Проверять конечный network map. `C`. |
| `consul_networks.<name>.{datacenter,kolla_network,address_override_var}` | `management/api/consul_management_address`; `customer/tunnel/consul_customer_address`; `storage/storage/consul_storage_address` | `datacenter`, `bind_addr`, `advertise_addr`; non-loopback agent endpoint | Не должны непреднамеренно описывать один канал как независимые сети. `C`. |
| `consul_networks.<name>.{server_group,client_group}` | `consul-<name>-server`, `consul-client` | Выбор server/client; `bootstrap_expect=length(server_group)` | Старый `consul_server_bootstrap_expect` не является входом этого выражения. `C`. |
| `consul_networks.<name>.{masakari_monitor,masakari_name,masakari_order}` | `true`; `manage/tenant/storage`; `10/20/30` | Набор и порядок осей матрицы | Допустимые имена в фильтре ограничены `manage`, `tenant`, `storage`; дубликаты отклоняются. `C`. |
| `consul_min_server_count`, `consul_require_odd_server_count` | `3`, `true` | Проверки топологии `tasks/precheck.yml` | Size-check пропускается для пустой server group; сам успешный precheck не доказывает quorum. Не время обнаружения отказа. `D`. |
| `consul_client_addr`, `consul_http_port` | `127.0.0.1`, `8500` | `client_addr`, `ports.http`; hostmonitor agent endpoints | При изменении порта/адреса согласовать оба шаблона. `C`. |
| `consul_server_port`, `consul_serf_lan_port`, `consul_serf_wan_port` | `8300`, `8301`, `8302` | `ports.server/serf_lan/serf_wan` | Нужна соответствующая связность по сетям. `C`. |
| `consul_dns_port`, `consul_https_port`, `consul_grpc_port`, `consul_grpc_tls_port` | `-1` каждое | Соответствующие поля `ports` | Не считать HTTPS настроенным только по наличию TLS-переменных. `C`. |
| `consul_log_level` | str, `INFO` | `log_level` | Уровень логов, не детектирование. `C`. |
| `consul_node_name` | str, `inventory_hostname` | Объявлен в defaults, активный шаблон вместо него пишет **`node_name=ansible_fqdn`** | Проверить совпадение идентичности с Nova/Masakari/Ironic; изменение неиспользуемой переменной не исправляет имя. |
| Нет globals mapping | литералы `1s`, `1s`, `6` | `gossip_lan.probe_interval`, `probe_timeout`, `suspicion_mult` | Настройки заданы прямо в `consul.hcl.j2`. Не являются формулой SLA отказа; изменение требует правки шаблона/доставки, не PowerOps image. |
| `consul_require_gossip_key` | bool, `true` | Precheck обязательности ключей | `D`. Сами ключи не публиковать. |
| `consul_management_gossip_key`, `consul_customer_gossip_key`, `consul_storage_gossip_key` | secret str, пустые defaults | `consul_networks.*.gossip_encrypt_key` → `encrypt` | Участники одного datacenter должны использовать согласованный ключ. `C`. |
| `consul_acl_enabled`, `consul_acl_default_policy`, `consul_acl_down_policy`, `consul_acl_token_ttl` | `false`, `deny`, `extend-cache`, `30s` | `acl.enabled/default_policy/down_policy/token_ttl` | TTL ACL token cache не TTL PowerOps-lock. Не найден mapping токена hostmonitor в `[consul]`; отдельно проверить доступность agent API при включении ACL. `C`. |
| `consul_tls_enabled` | bool, `false` | Условие записи `verify_*`, `ca_file`, `cert_file`, `key_file` | Hostmonitor template строит agent address через `consul_http_port`; перевод Consul на HTTPS требует проверки совместимости monitor. `C`. |
| `consul_tls_ca_file`, `consul_tls_cert_file`, `consul_tls_key_file` | `/etc/consul.d/ca.pem`, `/etc/consul.d/consul.pem`, `/etc/consul.d/consul-key.pem` | `ca_file`, `cert_file`, `key_file` | Пути должны существовать в контейнере; содержимое ключей не выводить. `C`. |
| `consul_tls_verify_incoming`, `consul_tls_verify_outgoing`, `consul_tls_verify_server_hostname` | bool, `true` каждое | Соответствующие `verify_*` | При включённом TLS неверная CA/имя нарушат обмен и детектирование. `C`. |

### Nova признаёт сервис down независимо от Consul

Kolla0809 не задаёт `service_down_time` или `report_interval` в проверенных Nova-ролях/шаблонах. Официальные defaults Nova 2025.1: `[DEFAULT].report_interval=10` секунд, `[DEFAULT].service_down_time=60` секунд; это период отчёта и допустимый возраст последнего отчёта. `report_interval` должен быть меньше `service_down_time`. [Nova 2025.1: service_down_time](https://docs.openstack.org/nova/2025.1/configuration/config.html#DEFAULT.service_down_time).

Это upstream-значения, не подтверждение настроек стенда. Изменения задаются поддерживаемым Nova INI override и применяются к нужным Nova-сервисам (`C`). Masakari `nova_down_timeout` не изменяет порог самой Nova. В новом gate допустим `disabled/up` как промежуточное состояние; `enabled`, неизвестный state, неоднозначный host или ошибка API прекращают recovery, а не разрешают эвакуацию.

## 7. Ironic: настройки питания и регистрации BMC

### Что непосредственно пишет Kolla0809

`K/ansible/roles/ironic/templates/ironic.conf.j2` задаёт следующую конфигурацию conductor литералами. Переменных вида `powerops_ironic_*` для этих строк нет. Изменение поддержанных INI-опций выполняется через override и reconfigure Ironic (`C`); добавление недоступного драйвера может также требовать образ (`I`).

| Выход `[DEFAULT]`, если не указана другая секция | Значение шаблона | Назначение |
| --- | --- | --- |
| `rbac_service_role_elevated_access` | `true`, API и conductor | Контракт привилегированного доступа service role. |
| `enabled_hardware_types` | `ipmi,redfish` | Только эти hardware types разрешены шаблоном. |
| `enabled_power_interfaces`, `enabled_management_interfaces` | `ipmitool,redfish` | Питание и управление BMC. |
| `enabled_boot_interfaces`, `default_boot_interface` | `pxe` | Обязательная interface family Ironic; сама строка не запускает PXE. |
| `enabled_deploy_interfaces`, `default_deploy_interface` | `direct` | Обязательная interface family; PowerOps не вызывает deploy. |
| `enabled_inspect_interfaces`, `default_inspect_interface` | `no-inspect` | Без inspection. |
| `enabled_network_interfaces`, `default_network_interface` | `noop` | Без управления сетью действующего Nova-host. |
| `enabled_storage_interfaces`, `default_storage_interface` | `noop` | Без provisioning storage. |
| `enabled_raid_interfaces`, `default_raid_interface` | `no-raid` | Без RAID-действий. |
| `enabled_bios_interfaces`, `default_bios_interface` | `no-bios` | Без BIOS-действий. |
| `enabled_console_interfaces`, `default_console_interface` | `no-console` | Без console. |
| `enabled_rescue_interfaces`, `default_rescue_interface` | `no-rescue` | Без rescue. |
| `enabled_firmware_interfaces`, `default_firmware_interface` | `no-firmware` | Без firmware-действий. |
| `enabled_vendor_interfaces`, `default_vendor_interface` | `no-vendor` | Без vendor passthrough. |
| `[conductor].automated_clean` | `false` | Автоматическая cleaning выключена. |

PowerOps дополнительно требует у конкретной Ironic node `provision_state=manageable`, `network_interface=noop`, точное `name=<Nova host>`, отсутствие `last_error` и согласованный `target_power_state`. Три поля читаются из ресурса, а не гарантируются одним conductor INI. Регистрация и PowerOps не должны переводить существующий compute в provisioning/cleaning/available.

### Унаследованные интервалы Ironic

Указанные опции не рендерятся Kolla0809; числа ниже — официальные defaults 2025.1, не данные образа/стенда. Для изменения — Ironic INI override (`C`).

| Секция.опция | Тип / upstream default | Назначение |
| --- | --- | --- |
| `[conductor].power_state_change_timeout` | int, `60` с | Ожидание смены питания. |
| `[conductor].soft_power_off_timeout` | int, `600` с | Soft-off/reboot. |
| `[conductor].sync_power_state_interval` | int, `60` с | Синхронизация power state. |
| `[conductor].heartbeat_interval` | int, `10` с | Heartbeat conductor. |
| `[conductor].heartbeat_timeout` | int, `60` с | Признание conductor неактивным. |
| `[ipmi].command_retry_timeout` | int, `60` с | Повторы IPMI. |
| `[ipmi].min_command_interval` | int, `5` с | Пауза между командами. |
| `[ipmi].use_ipmitool_retries` | bool, `false` | Повторяет Ironic, не ipmitool. |
| `[redfish].connection_attempts` | int, `5` | Попытки соединения. |
| `[redfish].connection_retry_interval` | int, `4` с | Интервал попыток. |
| `[redfish].connection_cache_size` | int, `1000` | Кэш соединений BMC. |

Источник таблицы: [Ironic 2025.1, conductor](https://docs.openstack.org/ironic/2025.1/configuration/config.html#conductor.power_state_change_timeout), [IPMI](https://docs.openstack.org/ironic/2025.1/configuration/config.html#ipmi.command_retry_timeout), [Redfish](https://docs.openstack.org/ironic/2025.1/configuration/config.html#redfish.connection_attempts). Кэш соединений Redfish не является SDK response cache Mistral. Таймаут HTTP Sushy, параметры node-level driver_info и индивидуальные задержки BMC здесь не установлены.

### Регистрация BMC: отдельные параметры Ansible

Источники: `K/ansible/enroll-ironic.yml`, `ironic-enroll-inventory.yml`, `roles/ironic_enroll/defaults/main.yml`, `tasks/{validate,detect_driver,prepare,resolve_passwords,enroll,verify}.yml`. У этих параметров **нет `.conf.j2` и INI-секции**: они управляют регистрацией ресурса/API/CLI. Это не настройки runtime PowerOps.

| Переменная | Тип / default роли | Фактическое применение / ограничение |
| --- | --- | --- |
| `ironic_enroll_mode` | str, `bmc-only` | `enroll.yml` → `node.extra.enrollment_profile`; описание профиля, не самостоятельный запрет API provision. `E`. |
| `ironic_enroll_cloud` | str, `kolla-admin` | Профиль `clouds.yaml` для CLI и `openstack.cloud`; play задаёт `OS_CLIENT_CONFIG_FILE={{ node_config }}/clouds.yaml`, очищает `OS_SYSTEM_SCOPE`. `D/E`. |
| `ironic_enroll_api_interface` | str, `internal` | CLI `--os-interface`, module `interface`. `D/E`. |
| `ironic_enroll_serial` | int, `25` hosts | `enroll-ironic.yml`: размер serial batch регистрации. Не число параллельных runtime выключений. `D`. |
| `ironic_enroll_throttle` | int, `10` tasks | `enroll.yml`: throttle создания/обновления ресурса и manage-команды. Ограничивается также serial/forks. `D`. |
| `ironic_enroll_manage_timeout` | int, `300` с | CLI `baremetal node manage --wait <seconds>`. Не `power_timeout`. `D`. |
| `ironic_enroll_state_read_retries` | int, `6` | `enroll.yml`: retries чтения начального состояния и повторного чтения после гонки manage. `D`. |
| `ironic_enroll_state_read_delay` | int, `2` с | Интервал этих чтений. Не ограничивает время одного API-вызова. `D`. |
| `ironic_enroll_verify_retries` | int, `12` | `verify.yml`: retries ожидания `manageable`. `D`. |
| `ironic_enroll_verify_delay` | int, `5` с | Интервал финальной проверки. `D`. |
| `ironic_enroll_bmc_ca_source` | str; fallback `/etc/kolla/certificates/bmc-ca.pem` в task | Файл источника CA на Ansible controller; копируется на conductors. Copy использует `failed_when:false`: отсутствие ошибки play не доказывает наличие CA. `D`. |
| `ironic_enroll_bmc_ca_host_path` | path, `{{ node_config }}/certificates/bmc-ca.pem` | Destination CA на conductor host. `D`. |
| `ironic_enroll_bmc_ca_container_path` | path, `/etc/ironic/bmc-ca.pem` | Default `driver_info.redfish_verify_ca`; само поле не монтирует файл в контейнер. Проверить volume/copy. `C/E`. |
| `ironic_enroll_bmc_ca_owner`, `ironic_enroll_bmc_ca_group` | str, `root`, `root` | Владелец каталога/CA; файл копируется с mode `0644`. `D`. |
| `ironic_enroll_default_system_id` | str, `""` | Последний fallback `driver_info.redfish_system_id`; пустое значение не записывается. `E`. |
| `ironic_enroll_overwrite_existing` | bool, `false` | Объявлен; использования в задачах роли не найдено. Не считать защитой от update существующего ресурса: фактические проверки находятся в `enroll.yml`. |
| `ironic_enroll_allow_empty` | bool, `true` | Объявлен; использования в задачах роли не найдено. Не управляет runtime host resolution. |
| `ironic_supported_bmc_types` | map | `detect_driver.yml`: hardware/power/management mapping. Таблица ниже. `E`, совместимость conductors обязательна. |
| `ironic_driver_priority` | list, `redfish, ilo5, drac5, xclarity, irmc, ipmi` | Выбор первого подходящего типа из объявленных для BMC. Не доказательство доступности протокола или его runtime failover. `E`. |
| `ironic_bmc_hosts` | map; inventory builder fallback `{}` | Создаёт недостающие inventory-hosts группы `bmc`; уже существующий inventory-host этой процедурой не заменяется. `E`. |
| `ironic_bmc_username` | str; inventory builder fallback `admin` | Username BMC. Поле inventory `ironic_bmc_username_global`, затем host `ironic_bmc_username`; в driver_info fallback `admin`. `E`. |
| `ironic_bmc_default_redfish_system_id` | str; fallback `ironic_enroll_default_system_id` | Общий Redfish System resource; host `redfish_system_id` приоритетнее. `E`. |
| `ironic_bmc_<type>_password`, `vault_ironic_bmc_<type>_password` | secrets; отсутствие значения даёт пустую строку | `resolve_passwords.yml` → защищённый driver_info: при `enable_config_vault=true` используется только `vault_bootstrap_passwords`, иначе direct variable; автоматического перехода с пустого Vault-значения на direct password нет. `E`. |
| `ironic_conductor_extra_volumes` | list; default `ironic_extra_volumes`, далее `default_extra_volumes` | `roles/ironic/defaults/main.yml`: дополнительные mount conductors; может потребоваться для CA. Не создаётся автоматически от значения `redfish_verify_ca`. `C`. |

У записи `ironic_bmc_hosts.<key>` обязательны `address`, `type`; `attached_host` по умолчанию равен ключу и становится **именем Ironic node**. Необязательны `redfish_address` (по умолчанию `https://<address>`), `redfish_system_id`, `redfish_verify_ca` (по умолчанию путь CA в контейнере). `redfish_address` валидируется как HTTP(S) endpoint без userinfo и пути; не помещать пароль в URL. Runtime PowerOps разрешает host по точному имени, не по приблизительному совпадению BMC/inventory/FQDN.

Фактический guard обновления существующей node в `enroll.yml` требует `extra.managed_by=ansible` и одно из состояний `enroll`, `enroll failed`, `verifying`, `manageable`. Это проверка task-кода; неиспользуемый `ironic_enroll_overwrite_existing=false` её не заменяет.

| BMC type в enroll | Hardware driver | Power / management interfaces |
| --- | --- | --- |
| `redfish` | `redfish` | `redfish / redfish` |
| `ipmi` | `ipmi` | `ipmitool / ipmitool` |
| `ilo5` | `ilo` | `ilo / ilo` |
| `drac5` | `idrac` | `idrac / idrac` |
| `xclarity` | `xclarity` | `xclarity / xclarity` |
| `irmc` | `irmc` | `irmc / irmc` |

Этот mapping шире жёстко заданных `ipmi,redfish` в conductor-шаблоне 0809. Наличие BMC type в enroll не доказывает, что такой hardware/interface загружен на conductors. Расширение требует проверки образа, всех interface families и итогового `ironic.conf`.

## 8. Аутентификация, роли и endpoint-параметры

| Участник | Конфигурационный путь | Что проверяет/использует код |
| --- | --- | --- |
| Пользователь Mistral | `powerops_allowed_project_names`, `powerops_allowed_user_names` → `[powerops]` | `M/mistral/services/powerops.py:authorize`: аутентифицированная роль `admin` либо роль `powerops_operator` вместе с точным совпадением обоих allowlists. `allow_hard_off=true` требует admin. `is_target=true` отклоняется. |
| Mistral → Nova/Ironic/Masakari | `mistral.conf.j2` → `[keystone_authtoken]`: `auth_url=keystone_internal_url`, `auth_type=password`, `username=mistral_keystone_user`, `password` из secret, `project_name=service`, domain IDs из `default_*_domain_id`, `cafile=openstack_cacert` | `clients.py:connection_from_conf` создаёт v3 Password. Пара domain IDs должна быть полной; если IDs не заданы, нужны оба domain names. Проверка TLS использует `cafile` либо системную CA (`verify=True`). |
| Masakari fencing → Ironic | `masakari.conf.j2` → `[keystone_authtoken]`: service user Masakari, `service` project, `default_*_domain_name`, CA; `[powerops].region_name/interface` | `A/masakari/powerops/ironic.py`: keystoneauth loader/session, затем SDK. Параметры TLS session берутся из загруженной auth-конфигурации. |
| Masakari → Nova | `masakari.conf.j2` → `[DEFAULT].os_privileged_user_name=nova_keystone_user`, `os_privileged_user_tenant=service`, auth URL и secret; `os_region_name`, `os_user_domain_name`, `os_project_domain_name`, `nova_ca_certificates_file` | `A/masakari/compute/nova.py:novaclient`. Отдельные credentials от Ironic SDK. В шаблоне domain **name**-опции получают `default_*_domain_id`; соответствие реальным именам надо проверить. |
| Masakari Nova endpoint | Нет mapping для `[DEFAULT].nova_catalog_admin_info`, code default `compute:nova:publicURL` | `novaclient` разбирает service type/name/endpoint type. `[powerops].interface=internal` не переключает этот Nova-client на internal. `nova_api_insecure` code default `false`. |
| Hostmonitor → Masakari | `masakari-monitors.conf.j2` → `[api]`: region, auth URL, service project/user, domain IDs, `api_interface=internal`, CA | Отдельная клиентская конфигурация monitor; не `[powerops]` Mistral. |
| Ironic API | `ironic.conf.j2` → `rbac_service_role_elevated_access=true`, Keystone auth при `ironic_enable_keystone_integration` | Регистрация пользователей и service-role assignments должна соответствовать политике Ironic. `ironic_enable_keystone_integration` default равен `enable_keystone`. |

Service-role wiring в Kolla0809:

- `roles/mistral/defaults/main.yml`: Mistral service user получает `admin` в project `service`; дополнительный `service` assignment имеет `state=present` при PowerOps, `absent` при выключении. Это поведение регистрации при доставке.
- `roles/masakari/defaults/main.yml`: Masakari service user получает `admin`; при PowerOps создаётся/назначается также `service`. При выключении список дополнительных assignments пуст, что не является явным отзывом ранее выданной роли.
- `roles/ironic/defaults/main.yml`: Ironic service user имеет `admin` и `service` в project `service`; inspector отдельно получает system-scope `service`.
- В проверенном Mistral0809 defaults/register пути нет создания роли **`powerops_operator`**. Allowlists не создают роль и не назначают её пользователю. Для не-admin оператора наличие и scope назначения необходимо проверить отдельно.

Backend actions используют service credentials только после проверки прав вызывающего пользователя. Наличие привилегий service user не разрешает произвольному пользователю запускать PowerOps. Имена ролей/пользователей/проектов сравниваются как точные строки; allowlists здесь не содержат domain IDs и не являются host-allowlist.

Для Masakari API `M/mistral/actions/powerops/clients.py:CloudClients.__init__` создаёт adapter с `service_type='ha'`, `version='1'`, тогда как Kolla регистрирует type `instance-ha`. При диагностике каталога необходимо проверить разрешение этого service type/alias фактически установленной библиотекой; одного корректного hostname URL недостаточно.

## 9. Deploy-time retries и проверки — отдельно от runtime

| Настройка / литерал | Где задано | Что ограничивает |
| --- | --- | --- |
| `async:60`, `poll:5` | `K/ansible/roles/{mistral,masakari}/tasks/powerops.yml` | Запуск команды `python -m <component>.cmd.powerops_check` на требуемых репликах. Не длительность workflow. |
| URI `timeout:20` с | `K/ansible/roles/mistral/tasks/powerops.yml` | Отдельный HTTP-запрос reconciliation/проверки каталога. |
| `retries:12`, `delay:5` | Там же, чтение workbook/actions/workflows | Повтор GET при доставке. Не повтор POST Nova/Ironic. |
| `powerops_reconcile_workbook`, `powerops_validate_registration` | `K/ansible/group_vars/all.yml` | Включение соответствующих частей reconciliation. Populate action definitions и entry-point preflight имеют отдельные задачи. |
| `database_bootstrap_retries=5`, `database_bootstrap_delay=10` с | `K/ansible/group_vars/all.yml` → `roles/{mistral,masakari}/tasks/bootstrap.yml` | Доступность БД при bootstrap. |
| `default_container_healthcheck_interval` | `60` с при одном inventory-host, иначе `30` с | Через role `*_healthcheck_interval` — Docker healthcheck Mistral API/engine/executor и Ironic API/conductor. |
| `default_container_healthcheck_timeout=30`, `retries=3`, `start_period=5` | `K/ansible/group_vars/all.yml`, role defaults | Контейнерные healthchecks. Их успешность не доказывает BMC access, владение lock или безопасную эвакуацию. |
| `[database].max_retries=-1` | `mistral.conf.j2`, `masakari.conf.j2`, `ironic.conf.j2` | Библиотечные повторы подключения к БД; это не ограниченный PowerOps retry-budget. |

Время Ansible-задачи не равно просто `retries × delay`: добавляются длительности самих попыток, а точное число выполнений зависит от semantics установленного Ansible. `mistral-db-manage populate` в PowerOps task не имеет указанного `async:60`; нельзя распространить лимит preflight на весь этап доставки.

Workbook источники — `K/ansible/roles/mistral/files/power_ops.yaml` и `M/etc/mistral/power_ops.yaml`. В проверенном workbook нет общего `timeout`, `retry` или `concurrency` для PowerOps tasks. Последовательность конкретных ВМ реализована внутри Python actions, а аварийная эвакуация — в Masakari. Ошибка/timeout после отправки операции требует проверки фактического состояния; слепой запуск того же workflow может создать вторую операцию.

В `M/mistral/actions/powerops/live_migration.py:submit` запрос `os-migrateLive` отправляется один раз с `connect_retries=0`, `status_code_retries=0`, `redirect=False`, `allow_reauth=False`, microversion `2.59`; ожидается HTTP `202`. Это локальная настройка именно этого POST. Для других SDK-вызовов общий запрет библиотечных retries таким кодом не установлен.

## 10. Как читать общий бюджет времени

Для аварии порядок такой:

```text
Consul / hostmonitor → доставка notification → очередь Masakari
  → захват host-lock (до 30 с ожидания)
  → disable Nova → фиксированный sleep wait_period_after_service_update (180 с)
  → Ironic fencing и stable-off (power_timeout, 180 с)
  → ожидание Nova disabled/down (nova_down_timeout, 180 с)
  → отбор ВМ
  → для каждой ВМ: ожидание global evacuation lock (до 3600 с)
                  → API evacuation → подтверждение (90 с)
                  → необходимые действия восстановления состояния ВМ
                  → пауза под global lock (5 с)
```

Эта цепочка — состав ожиданий, а не обещание верхней границы всей аварии. Первый этап зависит от Consul, monitor, доступности API и очередей. Часть унаследованных Nova-вызовов Masakari не получает явный timeout; время внутри callbacks и backend coordination также нельзя автоматически включать в число `90` или `180`.

Для Mistral `vm_action_timeout=600` применяется к каждой операции ВМ отдельно. При `N` реально обработанных ВМ ожидания суммируются, добавляются `instance_interval`, service-бюджеты, host-lock и питание. Soft-off имеет бюджет `300`; допустимый hard-off fallback — дополнительный `180`; при reboot power-on получает ещё один бюджет. Потерянный ответ/`PowerOpsCallTimeout` не является условием автоматического hard-off: код разрешает fallback только после соответствующего `PowerOpsTimeout` ожидания.

Mistral graceful-бюджет `300` секунд и upstream Ironic soft-off timeout `600` секунд не согласуются автоматически: внешний наблюдатель может закончить ждать, пока conductor ещё обрабатывает исходную команду. Последующий запрос не гарантирует немедленное завершение предыдущей BMC-задачи. Фактические настройки и target/error node нужно проверить до изменения этих бюджетов.

При `poll_interval=5`, `stable_observations=3` между первым и третьим подходящими наблюдениями нужно как минимум две паузы, то есть около `10` секунд плюс запросы. Реальное время больше при переходных состояниях/ошибках. Уменьшение timeout ниже окна наблюдений делает успех невозможным даже при исправном BMC; увеличение числа наблюдений не устраняет кэш и не превращает API readback в независимое физическое измерение.

Новый `nova_down_timeout` ограничивает цикл Nova-read после fencing: код использует monotonic deadline, eventlet timeout, отдельный native worker и session timeout на остаток бюджета. Уже выполняющийся read может завершиться после истечения срока, не выполняя power/recovery mutations. Существующие coordination/progress callbacks сохраняют свои backend blocking semantics. Это точнее, чем утверждение «каждая операция Masakari ограничена 180 секундами».

В Mistral `_call_with_deadline` временно задаёт `session.timeout` и `eventlet.Timeout`, но работа native I/O, библиотечных повторов и coordination должна проверяться в реальном образе. `M/mistral/executors/default_executor.py` после истечения переданного task timeout вызывает неограниченный `thread.join()`, если action thread ещё жив. Поэтому DSL timeout, ERROR heartbeat checker и обрыв клиентского HTTP-запроса не доказывают прекращение запущенного action или BMC/Nova-задачи.

## 11. Применение через Kolla и контроль результата

Поддержанные INI overrides объединяются после базового шаблона. Источники: `K/ansible/roles/{mistral,masakari,ironic}/tasks/config.yml`.

| Компонент | Порядок дополнительных файлов после `.conf.j2` | Результат на узле |
| --- | --- | --- |
| Mistral | `{{ node_custom_config }}/global.conf` → `mistral.conf` → `mistral/{{ item.key }}.conf` → `mistral/{{ inventory_hostname }}/mistral.conf` | `{{ node_config_directory }}/{{ item.key }}/mistral.conf` |
| Masakari API/engine | `global.conf` → `masakari.conf` → `masakari/{{ service_name }}.conf` → `masakari/{{ inventory_hostname }}/masakari.conf` | `{{ node_config_directory }}/{{ service_name }}/masakari.conf` |
| Masakari monitors | `global.conf` → `masakari/{{ service_name }}.conf` → `masakari/masakari-monitors.conf` → `masakari/{{ inventory_hostname }}/masakari-monitors.conf` | `{{ node_config_directory }}/{{ service_name }}/masakari-monitors.conf` |
| Ironic | `global.conf` → `ironic.conf` → `ironic/{{ item.key }}.conf` → `ironic/{{ inventory_hostname }}/ironic.conf` | `{{ node_config_directory }}/{{ item.key }}/ironic.conf` |

В таблице после первой строки все относительные пути также начинаются с `{{ node_custom_config }}/`. Имена `item.key`/`service_name` содержат дефисы, например `mistral-executor`, `masakari-engine`, `ironic-conductor`; имена контейнеров обычно содержат подчёркивания.

Например, в уже совместимом Masakari-образе `[powerops].nova_down_timeout` можно задать в `{{ node_custom_config }}/masakari/masakari-engine.conf`. Переменной `powerops_nova_down_timeout` в globals среза 0809 нет: добавление такого имени без mapping не меняет итоговый INI. Если образ ещё не содержит новый gate, требуется обновление образа, а не только конфигурации.

Перед изменением значения необходимо определить, какому уровню принадлежит симптом: очередь/deployment, мониторинг, lease/lock, API/BMC, ожидание Nova, отдельная ВМ. После согласованного применения проверить конечный INI/HCL, фактическую загрузку опций и entry points на всех затронутых репликах; затем отдельно выполнить предусмотренную приёмку сценария. Порядок проверок и безопасные команды приведены в [POWEROPS-DIAGNOSTICS.md](POWEROPS-DIAGNOSTICS.md).

Подтверждено чтением исходников: все 24 переменные блока PowerOps в Kolla0809, все 15 Mistral и 10 Masakari `[powerops]` опций, их template mapping и runtime consumers, выбранные inherited параметры, регистрация BMC и пути override. Не подтверждены: активные globals/overrides стенда, версии/настройки библиотек в образах, их сетевые и BMC-задержки, независимость всех SDK-наблюдений, успешное выполнение операций в работающем OpenStack.
