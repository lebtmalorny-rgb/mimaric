# Masakari: отдельный ремонт PowerOps, 06.09.2026

Два независимых git-патча. Комплект Mistral `repair-0509` не заменяется.
Образы и стенд этим комплектом автоматически не изменяются.

## Порядок и точные базы

| Патч | Куда применять | Проверенная база → результат |
|---|---|---|
| `0001-masakari-0509-repair.patch` | Git-исходники Masakari **после** прежних `0001–0010` | `9f3cb144958b8e60bba72adefb22edf51387c0ca` → `4fcbe3da46d4ec6a231be10a933fd57e8856663f` |
| `0002-kolla-masakari-preflight.patch` | Kolla-Ansible 0509 **после** `repair-0509/0002-kolla-ansible-0509.patch` | `5325c8abd781968f5478f2a7cfff7c002c647324` → `792f2f0998697de4c9d4fad396d05de95208fd36` |

Отдельного актуального Masakari-архива 0509 не было. Совпадение этой базы с
исходниками вашего engine-образа нужно подтвердить перед сборкой.
Если `git apply --check` не проходит, не применять с `--reject` и не переносить
куски вручную: сначала сопоставить вашу исходную ветку с базой выше.

Пример — заменить пути на свои, выполнять в чистых отдельных ветках:

```bash
patch_dir=/absolute/path/to/masakari-0509-repair
git -C /path/to/masakari apply --check "$patch_dir/0001-masakari-0509-repair.patch"
git -C /path/to/masakari apply "$patch_dir/0001-masakari-0509-repair.patch"
git -C /path/to/kolla-ansible apply --check "$patch_dir/0002-kolla-masakari-preflight.patch"
git -C /path/to/kolla-ansible apply "$patch_dir/0002-kolla-masakari-preflight.patch"
```

Каждую следующую команду выполнять только после успешного завершения предыдущей.
Для применения вместе с авторским commit вместо `git apply` можно использовать
`git am`, также предварительно проверив патч.

## Исправления

- Runtime больше не пропускает отсутствующий или не загружающийся task.
  Отвергаются дубликаты entry points, неверные типы задач и небезопасный порядок.
  Обязателен `disable → fence → prepare → evacuate`; для reserved-host последние
  две задачи остаются внутри `main` с retry. Это действует и при fallback.
  Дополнительные корректные Task-плагины поддерживаются; обычные non-PowerOps
  recovery flow сохраняют прежний режим загрузки.
- Эвакуация подтверждается по **Nova `OS-EXT-SRV-ATTR:host`**, а не по
  `hypervisor_hostname`: другой непустой host, `task_state=None`, ожидаемый
  `vm_state`, совпадение с явно выбранным reserved host. Финальное чтение не
  должно противоречить подтверждению; `dest_host` хранится как Nova host.
  Правило применяется к общей реализации эвакуации, включая non-PowerOps.
- Ошибка владения блокировкой или `stop_server` до создания таймера больше
  не заменяется `UnboundLocalError` при cleanup. Это **не** универсальное
  исправление пустого `msg=''` в Mistral или всех исключений Masakari.
- Kolla после handlers проверяет реальную загрузку/конструкторы и компиляцию
  обоих flow на **всех** `masakari-engine` из inventory, даже при `--limit`.
  Проверка ждёт последний выбранный serial batch и отказывает при частичном
  deploy. Это post-deploy gate, не откат уже изменённых контейнеров.
- Checker ограничен собственным `SIGALRM` на 50 секунд; внешний Ansible
  `async: 60` — дополнительный предел. На таймауте gate завершается ошибкой.

## Сборка и проверка до переноса

В предоставленном рецепте `kolla-pvs_1.0.0` Masakari устанавливается из Git
в `masakari-base`. Применить source patch **до** установки Python-пакета и
собрать зависимый engine-образ. Поздний `kolla_patch_sources` после установки
Python не заменяет этот шаг. Теги существующего проверяемого образа не затирать.

На машине с уже собранным локальным образом:

```bash
python3 /path/to/masakari-0509-repair/verify_images.py \
  --engine podman --engine-image REGISTRY/masakari-engine:NEW_TAG
```

Скрипт не делает pull/build: фиксирует локальный image ID, запускает только
Python в одноразовом контейнере с `--network=none`, без runtime-конфига и
host mounts. Проверяет SHA256 runtime-файлов, `pip check`, реальные plugins и
flow; удаляет только собственный одноразовый контейнер, в том числе при ошибке.
`PASS` не доказывает работоспособность облака. Если в образе отсутствует pip,
проверка зависимостей завершится ошибкой — не игнорировать её как успешную.

После успешной проверки образа Kolla выбирает его через существующие переменные
`powerops_masakari_engine_image` и `powerops_masakari_engine_tag` в globals.
Значения для Mistral/Ironic этот ремонт не меняет. Применение globals,
перезапуск и reconfigure выполняются отдельно оператором.

Checker с `--config-file /etc/masakari/masakari.conf` проверяет **реальный**
config, не дописывая отсутствующий fencing. Он не обращается к API, RabbitMQ,
БД или etcd и не выполняет `execute()` recovery-задач. Отсутствие ошибок
конфигурации здесь не подтверждает полномочия Keystone или доступ к BMC.

## Локальная проверка

Результаты, версии и границы доказательства — `VERIFICATION.json`.
`test-environment.lock` фиксирует зависимости проверенного Python 3.11/macOS,
но **не** предназначен для замены RPM-набора SberLinux в рецепте.

Для повторения unit-тестов внутри исходников Masakari с установленными deps:

```bash
python -B -c 'import masakari.tests.unit; from masakari import objects; objects.register_all(); import unittest; unittest.main(module=None)' \
  discover -s masakari/tests/unit -t .
```

Порядок import важен: eventlet bootstrap → objects → unittest.
Полный suite использует локальные WSGI-сокеты и тестовые DB backend.

Безопасная проверка Ansible `serial/limit/partial deploy`, без контейнеров и API:

```bash
python verify_ansible_preflight.py /path/to/patched/kolla-ansible
```

Нужны PyYAML и `ansible-playbook` рядом с используемым Python. Скрипт заменяет
контейнерные команды локальными маркерами, сохраняя реальную Ansible-логику
gate, loop, delegation и async. Реальное исполнение checker проверяется отдельно.

Не проверялись: SberLinux/RPM-образы, live Keystone/RBAC, etcd lease/ownership,
BMC, настоящая Nova evacuation, отказ/возврат физического узла. Новые сценарии
питания, автоматический возврат после аварии и изменения Masakari API/БД в
этот ремонт не входят. Аварийный хост автоматически не включается.
