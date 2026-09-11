# Python 3.11: два сценария PowerOps на стенде

Реализация и команды: [stand-tests](../../tools/stand-tests/README.md).
Самостоятельный runner с JSON-заданием и постоянным JSON-журналом поддерживает
emergency и planned, каждый с включением и возвратом source в работу.
Совместимость с Rally, создание/удаление ВМ и обратная миграция не входят в версию.

## Согласованное поведение

Пользователь явно разрешил автоматическое подтверждение оператора. После
реального PAUSED в power_ops.power_on_and_return тест проверяет source:
Ironic включён, Nova disabled/up, Masakari maintenance, новая загрузка той же
машины, сеть вернулась, source пуст по Nova/libvirt, ВМ на ожидаемых destination.
Затем тот же execution получает Boolean stale_domains_checked=true.
При stale domains подтверждение не отправляется, автоматического undefine нет.

Emergency вносит административный DOWN параметризованного интерфейса через
Ansible/systemd. Duration по умолчанию 300. Masakari должен сам получить настоящее
событие, подтвердить fencing/Nova-down и эвакуировать весь manifest. Проверяются
notification/VMove и временной порядок. Fencing может прервать сетевой таймер;
runner дополнительно удерживает выключенный source duration секунд после
наблюдения завершённого recovery. Оба обстоятельства сохраняются в отчёте.

Planned запускает power_ops.planned_power_off с live_migrate и без hard-off
fallback. Успех требует новой завершённой global Nova migration на каждую ВМ,
пустого source, подтверждённого power-off и корректного output workflow.

## Архитектура и повторяемость

Task JSON задаёт host/UUID/manifest/destination/libvirt/duration/timeout.
Inventory обязателен, globals опционален. Ansible разрешает Jinja/Vault и
использует штатные SSH/become credentials без выгрузки всех переменных.
SDK 4.20.0 под Python 3.11 предоставляет clouds.yaml/OS_* auth и Keystone session;
REST-адаптер использует Nova 2.59, Masakari 1.3, Ironic 1.52 и Mistral v2.
BMC secrets остаются в Ironic.

scenario_runner.py содержит критерии/последовательность; openstack_probe.py — API
и пагинацию; ansible_target.py — source inspection/fault transport; stand_test.py —
plan/preflight/run/status/report. remote_fault.py выполняет bounded DOWN/UP
и закрывает журнал после reboot без изменения сети.

Один изменяющий прогон одновременно, выделенный source, локальный flock.
Журнал записывается атомарно с fsync до изменяющего запроса и привязан к
заданию/cloud/user/project. Для Mistral POST заранее назначается UUID,
поддерживаемый baseline0809. После потери ответа выполняется только GET этого
UUID с проверкой input/name/description. Потерянный resume не повторяется.

Перед ещё не отправленной первой операцией повторно проверяется baseline,
включая restart runner. Перед новым return POST сверяется выключенный source
и placement. Deadline сохраняется. FAIL/PASS — исторические терминальные
результаты. INCOMPLETE не даёт ложного успеха или безусловного восстановления.

## Источники и проверка

Контракты сверены с локальными активными архивами0809:
etc/mistral/power_ops.yaml, mistral/api/controllers/v2/execution.py,
mistral/actions/powerops/{planned,return_host,live_migration,clients}.py,
Masakari notifications/vmoves API и TaskFlow recovery details, а также
локальным post-fence Nova-down hotfix. Проверены формы Mistral JSON-object/string,
literal Boolean env, dest_host и VMove succeeded.

Локальные тесты не являются стендовым подтверждением. Приёмка требует реальной
работы установленных workflow, мониторинга, fencing, libvirt и сетевого worker.
Границы PASS и условия запуска перечислены в README инструмента.
