# Отдельные патчи Mistral: API, диагностика и безопасность PowerOps

Дата: 2026-09-05. Итоговый Mistral commit: `7be711a1df54655fed9cfdaca66516023536558a`.

Серия содержит прежние два исправления и три дополнения только для Mistral.
Masakari и Kolla-Ansible не изменялись. Подробности проверки и оставшиеся
ограничения: [WORKFLOW-AUDIT.md](WORKFLOW-AUDIT.md).

## Состав

| Патч | Назначение | Commit |
|---|---|---|
| [0001](0001-fix-use-Masakari-v1-and-public-UUIDs-in-PowerOps.patch) | Masakari API v1 и публичный UUID вместо числового id | `e5c5bcf` |
| [0002](0002-fix-give-PowerOps-errors-nonempty-default-messages.patch) | Непустые сообщения собственных исключений PowerOps | `ca39c2e` |
| [0003](0003-fix-enforce-shared-PowerOps-authorization-in-actions.patch) | Общая авторизация workflow/actions; hard-off только для admin | `3dec4ea` |
| [0004](0004-fix-bind-PowerOps-restart-manifests-to-the-target-host.patch) | Restart manifest привязан к целевому compute host | `18981c7` |
| [0005](0005-fix-arm-PowerOps-fail-safe-before-maintenance-changes.patch) | Fail-safe включён до попытки изменения maintenance | `7be711a` |

База: `ce804184cec4e63c7d488ce9920992d8d87b9938`, Mistral с ранее
установленными PowerOps-патчами. Это не патчи для чистого upstream.
Ветка: `fix/powerops-masakari-v1-uuid`.
Существующая серия `patches/mistral` не перезаписана; файлы 0001/0002
сохранены без изменений. Новые исправления — отдельные коммиты 0003–0005.

Изменяются runtime-файлы в `mistral/actions/powerops/`:
`clients.py`, `exceptions.py`, `base.py`, `planned.py`, `return_host.py`.
Остальные изменения — тесты.

## Что изменится

- Adapter Masakari использует `version='1'`, а ресурсы — проверенный `uuid`.
  Проверки точного имени, единственности хоста, сегмента и Boolean maintenance
  сохранены.
- `PowerOpsDisabled()` получает сообщение
  `PowerOps actions are disabled ([powerops] enabled=false)`.
  Fallback действует только для `PowerOpsError` и наследников; произвольное
  стороннее `Exception()` по-прежнему может иметь пустой текст.
- Прямые вызовы actions проверяют ту же policy, что workflow API. Admin
  допускается независимо от операторских списков; оператору нужны роль
  `powerops_operator` и точные project/user names из allowlists.
  `allow_hard_off=True` разрешён только admin.
- До первого запуска проверяется принадлежность всех ВМ из manifest целевому
  хосту. UUID/host повторно проверяются перед запуском или пропуском ACTIVE ВМ,
  а также при ожидании результата. Запуски остаются последовательными.
- При неопределённом исходе maintenance PUT/read-back выполняется попытка
  восстановить maintenance и Nova disabled под той же блокировкой.
  Если блокировка потеряна или API недоступен, конечное состояние не гарантируется;
  запрет записей без подтверждённого владения блокировкой сохранён.

## Применение к исходникам для сборки

Проверить чистоту рабочего дерева и базу. Накладывать по порядку, прекращая
работу при любой ошибке. Например, из корня исходников:

```sh
git status --short
powerops_hotfix_dir=/absolute/path/to/mistral-masakari-v1-uuid
for patch in \
  0001-fix-use-Masakari-v1-and-public-UUIDs-in-PowerOps.patch \
  0002-fix-give-PowerOps-errors-nonempty-default-messages.patch \
  0003-fix-enforce-shared-PowerOps-authorization-in-actions.patch \
  0004-fix-bind-PowerOps-restart-manifests-to-the-target-host.patch \
  0005-fix-arm-PowerOps-fail-safe-before-maintenance-changes.patch
do
  git apply --check "$powerops_hotfix_dir/$patch" &&
    git apply "$powerops_hotfix_dir/$patch" || break
done
```

Если 0001/0002 уже точно установлены, начинать с 0003. Не накладывать их
повторно. Не использовать `--reject` или принудительное применение:
при конфликте сначала сравнить исходники.

Контрольные суммы: `shasum -a 256 -c SHA256SUMS` из папки патчей.
Все пять патчей последовательно наложены на чистую копию базы;
обратная проверка каждого прошла. Все 13 результирующих файлов побайтно
совпали с итоговым commit.

Это Python-код: **reconfigure старого образа его не обновит**.
Нужен новый образ с согласованными PowerOps-зависимостями и последующая
выкладка на все соответствующие реплики Mistral. В частности, executor должен
получать роли в SecurityContext через ранее патченный mistral-lib; без ролей
actions теперь корректно отказывают в доступе.
Публикуются только патчи и инструкции. Сборку образов и перенос на стенд
выполняет оператор; здесь сборка, выкладка и рестарты не выполнялись.

## Локальная проверка

Из worktree Mistral с подготовленной тестовой `.venv`:

```sh
.venv/bin/stestr --test-path=./mistral/tests/unit/actions/powerops run --concurrency=1
.venv/bin/python -m testtools.run mistral.tests.unit.api.v2.test_executions_powerops mistral.tests.unit.services.test_powerops
.venv/bin/python -B /path/to/verify_sdk_contracts.py
.venv/bin/python -B /path/to/verify_workflow_safety.py
```

**130 + 21 + 6 = 157 тестов прошли**, плюс четыре standalone regression probes.
Новые негативные тесты воспроизвели дефекты до соответствующих правок.
`flake8`, `git diff --check` и независимое ревью пройдены.

Среда: Python 3.11, openstacksdk 4.10.0, keystoneauth1 5.17.0,
requests-mock 1.12.1, ранее патченный mistral-lib.
Есть предупреждения устаревания Eventlet/pkg_resources/SDK.
Версии библиотек контейнеров отдельно не подтверждены.

Общий cross-repository набор: **16/19**. Три структурные проверки требуют
актуализации: прежний Jinja block Kolla; inline allowlist вместо общего
authorize; один цикл selected вместо предварительной валидации плюс запуска.
Они не изменялись в Mistral-серии. Подробности в аудите.

Реальны actions, Python-клиенты, discovery и сериализация; внешние API и
оборудование подменены. Это не проверка живых TLS/RBAC, etcd, RabbitMQ,
BMC или полного engine pause/resume.

## Первые проверки после согласованной выкладки

1. На каждой executor-реплике сверить код, зависимости, передачу roles,
   `[powerops] enabled` и служебную авторизацию.
2. Через служебного пользователя executor выполнить только чтение Ironic,
   Nova и Masakari. Проверить `/v1/segments/<UUID>`, видимость ресурсов и
   точное совпадение имён хостов.
3. Создать новый `power_ops.host_power_status` и дождаться `SUCCESS`.
   HTTP 201 при создании означает только принятие запроса.
4. Проверить coordination/heartbeat всех участвующих служб. Изменяющие
   сценарии принимать отдельно на согласованном выделенном пустом хосте.
   Самостоятельно эти проверки на стенде не запускались.
