# Локальные доказательства поставки Watcher automation hold

Проверки выполнены 13 сентября 2026 года без обращения к OpenStack, BMC,
production etcd, без deploy/reconfigure и без изменения замороженных компонентных
репозиториев. Точные bases, final commits/trees и SHA256 находятся в
[`manifest.json`](manifest.json).

## Delivery tool: RED/GREEN

До появления tool и обновления build metadata:

```text
/tmp/watcher-hold-venv/bin/python -m unittest \
  tests.test_watcher_automation_hold_delivery -v

Ran 4 tests in 0.004s
FAILED (failures=1, errors=3)
```

Причины были ожидаемыми: отсутствовал `tools/watcher_automation_hold_delivery.py`,
license имел устаревшую table-форму, требование setuptools было ниже 77.
Первый GREEN: `Ran 4 tests in 0.174s; OK`.

Реальный replay Kolla выявил, что одновременный `git apply --check` двух
зависимых patch проверяет второй против исходной базы. Отдельный regression test
`test_replay_checks_dependent_patches_in_order` воспроизвёл ошибку. После
последовательного check/apply итоговая delivery-suite также проверяет, что patch
не меняет исключённый локальный файл:

```text
/tmp/watcher-hold-venv/bin/python -m unittest \
  tests.test_watcher_automation_hold_delivery -v

Ran 7 tests in 0.490s
OK
```

### Review fix: исключённый blob

Независимый review заметил, что первая версия tool выполняла `git add -Af` до
удаления excluded path из индекса. Файл отсутствовал в сравниваемом tree, но его
blob оставался в disposable object database. Synthetic-secret regression
сначала подтвердил дефект:

```text
/tmp/watcher-hold-venv/bin/python -m unittest \
  tests.test_watcher_automation_hold_delivery.WatcherAutomationHoldDeliveryTests.test_replay_matches_tree_without_storing_excluded_secret_blob -v

FAIL: 0 == 0
Ran 1 test in 0.154s
FAILED (failures=1)
```

Теперь каждый заранее проверенный относительный excluded path передаётся как
отдельный literal exclude pathspec уже в первоначальный `git add`. Файл никогда
не добавляется принудительно. Focused GREEN: `Ran 1 test in 0.144s; OK`;
covering GREEN: `Ran 7 tests in 0.478s; OK`.

Удалены только шесть `.git` каталогов старых Task4 replay outputs под
`/tmp/watcher-hold-delivery-replay.EGaBlp/replayed-*` и
`/tmp/watcher-hold-final-replay.VBG0kI/replayed-*`. Исходные/replayed файлы и
excluded-файл сохранены; kit и component Git metadata не затрагивались. Новые
outputs `replayed-safe-watcher`, `replayed-safe-masakari` и
`replayed-safe-kolla` созданы из сохранённых clean bases. Все три base/final tree
снова совпали с таблицей ниже. Для Kolla отдельная проверка без вывода содержимого
или digest подтвердила: excluded-файл неизменён, отсутствует в индексе и его blob
отсутствует в новой object database.

## Артефакты, replay и сборка

```text
/tmp/watcher-hold-venv/bin/python \
  tools/watcher_automation_hold_delivery.py verify

status: ok; 6 artifacts verified
```

Replay из чистых snapshot точных base commits, полученных через `git archive`,
выполнил отдельный `git apply --check`, application и сравнение итогового tree:

| Компонент | Base tree | Final tree | Результат |
|---|---|---|---|
| Watcher | `2a7737a49e85f5d5323cb1822cda30795baa498c` | `30e2ec8225db08ce46b71844bbcdb4a00767ab8d` | совпал |
| Masakari | `1e0d18ec2de5b76e8693d13e7a57ee2ee8ec5c13` | `f7eb2f799ba9db0ac44b01ca949c1070bd4b6f96` | совпал |
| Kolla-Ansible | `ab0c2a2293c0d93dc7ebdbd6cd800df5c9dc283a` | `d68e9dcf20ca05e2bea7fb07ab93e80aab40e2a2` | совпал |

Четыре Kolla symlink после replay сохранили исходные targets. Неизменённый
`etc/kolla/passwords.yml` исключён из сравниваемого индекса и не включён в
комплект; он также не попадает в replay object database. Его содержимое и digest
в evidence не публикуются.

Wheel дважды собран из отдельных копий source следующей командой:

```sh
SOURCE_DATE_EPOCH=1789295229 /tmp/watcher-hold-venv/bin/python -m build \
  --wheel --no-isolation --outdir <separate-output> \
  packages/powerops-watcher-guard
```

Оба artifact имеют SHA256
`8dcdb3d1b0fd4ac57287c5df08db24b4f636107b479e60fed79e46f317dfbd63`.
Wheel установлен с `--no-deps --target` отдельно от editable source. Импорт
пришёл из этого target; version `0.1.0`, `License-Expression: Apache-2.0`, CLI
`--help` завершился с кодом 0. Проверка `status` отсутствующего состояния из
этого wheel против настоящего loopback etcd завершилась кодом 1 и выдала
санитизированный JSON `Guard state is missing`, тип `GuardDenied`.

Из replayed Kolla выполнены три точечных теста одинакового рендера Watcher и
Masakari, optional TLS и реальных Ansible precheck-условий:

```text
ANSIBLE_LOCAL_TEMP=/tmp/watcher-hold-delivery-ansible \
/tmp/watcher-hold-venv/bin/python -m pytest -q \
  kolla_ansible/tests/unit/test_powerops_templates.py::WatcherAutomationGuardTemplateTest::test_masakari_and_watcher_render_identical_guard_values \
  kolla_ansible/tests/unit/test_powerops_templates.py::WatcherAutomationGuardTemplateTest::test_optional_tls_paths_render_only_when_configured \
  kolla_ansible/tests/unit/test_powerops_configuration_contract.py::PowerOpsConfigurationContractTest::test_guard_prechecks_execute_real_ansible_conditions \
  --disable-warnings --tb=short

3 passed in 0.18s
```

`py_compile` всех изменённых Python-файлов из replayed деревьев завершился с
кодом 0: Watcher 25, Masakari 9, Kolla-Ansible 2.

## Межсервисный smoke с настоящим etcd

Watcher и Masakari запускались разными subprocess, потому что их глобальные
oslo-config registry нельзя смешивать в одном процессе:

```text
POWEROPS_GUARD_TEST_ENDPOINT=http://127.0.0.1:32379 \
/tmp/watcher-hold-venv/bin/python -m unittest \
  tests.test_watcher_automation_hold_crossprocess -v

test_epoch_lifecycle_across_real_service_helpers ... ok
Ran 1 test in 1.768s
OK
```

Использован уникальный disposable prefix, удалённый тестом. Проверены состояния:
initialize BLOCKED; resume E1; scheduled Watcher audit принят с E1; допустимый
Masakari incident устанавливает hold; старый план E1 запрещён; после operator
resume E3 старый план остаётся запрещён; следующий audit получает E3; новый
manual plan допускается; повтор того же incident UUID не меняет разрешённое
состояние. Никакие service DB/API или cloud actions не вызывались.

Ранее замороженные компонентные проверки не повторялись без нового сомнения:
Task 1 — 32 package tests с настоящим etcd и restart persistence; Task 2 — 350
Watcher tests; Task 3 — 149 Masakari tests с 16 классифицированными baseline
warnings, 37 Kolla tests до review fix и 24 covering Kolla tests после fix.

## Непроверенные границы

Нет stand/production доказательств состава образов, schema rollout, API/RPC,
реальных Nova migrations, Masakari evacuation, Ironic/BMC fencing, HA/failover
etcd, гонок процесса под нагрузкой или масштаба 1000+ хостов. Admission до hold
может обратиться к Nova позже; drain активных Watcher actions отсутствует.
Watcher `SUCCEEDED` не доказывает терминальный статус конкретной Nova migration.
Плановые PowerOps/Mistral операции и самостоятельные миграции ВМ с guard не
скоординированы; новые manual Watcher plans также вне этой защиты. Mistral этим
комплектом не изменён.
