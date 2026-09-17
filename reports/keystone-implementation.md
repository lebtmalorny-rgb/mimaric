# Keystone: реализация исключения парольной политики

База: `537e65b2b1d4b8e0fe1faa09c8f882a6b2899b21`, ветка
`password-policy-exempt`, Python 3.11, macOS, реальные SQLite/WebTest.

## Контракт

- `user.options.password_policy_exempt`: только Boolean `true` выключает regex,
  SQL self-service history/minimum age; false/отсутствие — обычная политика.
- `null` — штатное удаление resource option; разрешение проверяется также для
  false/null. SQL id `PPEX`, без миграции.
- Отдельное разрешение `identity:manage_password_policy_exemption` по умолчанию
  `role:admin and system_scope:all` без deprecated fallback. Поддержка трех scopes
  позволяет явное ограниченное исключение для deployment identity.
- Для reset используются существующие options целевого пользователя с request
  overlay; для create — request; для self-service — сохраненный target.
- Штатные first-use/expiry/lockout options независимы. Проверка старого пароля,
  lock_password, типы/технические пределы и revocation/cache сохранены.

## TDD и окружение

Первый baseline:

```sh
.venv/bin/stestr run --concurrency 1 'test_v3_identity.IdentityTestCase.test_create_user$'
```

Не достиг тестового поведения: `ldap.get_option(ldap.OPT_X_TLS_CACERTFILE)`
завершился `ValueError: option error` при setup. Причина: python-ldap был
собран с системным macOS LDAP framework без требуемых TLS options. Это
проблема окружения, не RED по функциональности. Root agent устраняет
сборкой отдельного OpenLDAP и перепривязкой python-ldap без изменения
исходников Keystone. Исходный вывод: `/tmp/keystone-baseline.log`.

Тесты написаны до изменения production-кода: реальные HTTP create/update/
self-service, SQL option storage, loaded-regex schema, malformed значения,
привилегии и guardrails. Результаты RED/GREEN будут добавлены после запуска.

После исправления LDAP baseline повторен, **1 passed / 0 failed**
(`/tmp/keystone-baseline-fixed.log`).

RED до production edits:

```sh
.venv/bin/python -m unittest keystone.tests.unit.test_password_policy_exemption.PasswordPolicyExemptionSchemaTests
.venv/bin/stestr run --concurrency 1 test_password_policy_exemption
```

Standalone schema assertion отказался принять true/false/null (1 тест,
3 failing subtests). Полный RED: **24 tests, 2 passed, 22 failed, 0 skipped**
(`/tmp/keystone-schema-red.log`, `/tmp/keystone-red.log`). Характерная ошибка
API: HTTP 400, `Additional properties are not allowed
('password_policy_exempt' was unexpected)`. Это отсутствующая функциональность,
а не проблема окружения.

GREEN:

```sh
.venv/bin/stestr run --concurrency 1 test_password_policy_exemption
```

**24 passed, 0 failed, 0 skipped**, 3.25 s (`/tmp/keystone-green.log`).
Промежуточные прогоны 16/24 и 23/24 выявили неточности новых тестов:
`authenticate` manager требует request context, технический max-length
возвращает штатный HTTP 403, policy fixture требует загрузить defaults перед
частичным override, AccountLocked маскируется как Unauthorized в notification
wrapper. Исправлены тестовые ожидания/контекст без изменения этих guardrails.

Штатный SQL create сохраняет `password_expires_at` даже при
`ignore_password_expiry=true`; native authentication игнорирует expiry по
этому option. Интеграционный тест проверяет успешную аутентификацию сервисного
пользователя со всеми четырьмя options при включенных first-use/expiry/lockout,
а не неверное ожидание `password_expires_at=null`. Порядок создания native
options в upstream не менялся.

## Уточнение плана: авторитетное SQL-состояние и cache

Security review обнаружил, что проверять exemption через закэшированный
`Manager.get_user` недостаточно: другой worker может снять классификацию в SQL,
а stale local cache продолжит разрешать слабый пароль. Воспроизведено на реальном
кэше и SQLite: populate manager cache, изменить options напрямую SQL driver
(эквивалент обновления другим worker без локальной invalidation), затем HTTP reset
или self-service. **Четыре RED**: cached true разрешал слабый пароль после revoke;
cached false ошибочно запрещал слабый пароль после grant.

```sh
PATH="$PWD/.venv/bin:$PATH" .venv/bin/stestr run --concurrency 1 'test_password_policy_exemption.*stale_cached'
```

`/tmp/keystone-stale-cache-red.log`: 4 failed / 0 passed. Дополнительный RED для
захвата SQL locking statements: 1 failed (`/tmp/keystone-sql-lock-red.log`).

Согласованное уточнение Task 1:

- SQL driver объявляет явную capability `password_policy_validation_in_driver`.
  Manager сохраняет прежнюю regex-проверку для остальных/custom drivers, которые
  не объявили capability. Он больше не решает SQL exemption по кэшу.
- SQL create/reset/self-change проверяют regex по effective persisted options в
  write transaction. Update сначала накладывает переданные options на сохраненные.
- SQL update (включая classification-only update) и self-change сначала выполняют
  `SELECT user.id ... FOR UPDATE`, затем загружают options/passwords. Lock-query
  не содержит nullable joined tables; порядок одинаковый: parent row → данные.
- Native cache invalidation и revocation manager сохранены. Нет миграции.
- Аудит записывает каждое успешное явное назначение/удаление флага и итоговую
  классификацию, включая false и повторные значения. Не строит недостоверное
  old→new из кэшированного old user. CADF reason и INFO log не содержат паролей.
  Для false assignment был отдельный RED: 1 failed
  (`/tmp/keystone-assignment-audit-red.log`).

После SQL guard: 30/30 feature tests PASS (`/tmp/keystone-authoritative-green.log`),
включая четыре stale-cache сценария и реальный захват statement при двух writes.
Захваченные statements дополнительно компилируются dialects MySQL/PostgreSQL:
`FOR UPDATE` присутствует, JOIN отсутствует. **SQLite не реализует row-level
FOR UPDATE; реальная конкуренция/locking на MySQL/PostgreSQL не проверялась.**
Это локальная SQL/statement проверка, не runtime-доказательство production DB.

## Дополнительные upstream-проверки

Первый широкий запуск: 1009 tests — 1004 passed, 3 skipped, 2 failed. Причины
двух failures устранены: добавлен новый action в обязательный
`doc/source/getting-started/policy_mapping.rst`; `.venv/bin` добавлен в PATH для
subprocess `oslopolicy-policy-generator`. Feature + policy после этого: 48/48 PASS.

Дополнительный upstream user-protection suite:

```sh
.venv/bin/python -m unittest keystone.tests.protection.v3.test_users
```

110 tests: 81 passed, 29 errors (`/tmp/keystone-user-protection.log`). Все 29
ошибок в setup существующих DomainAdminTests/ProjectAdminTests: ссылка на
отсутствующий `up.SYSTEM_ADMIN_OR_DOMAIN_ADMIN`. Причина воспроизведена отдельно
на **неизмененном pinned baseline**, распакованном через `git archive`:

```sh
cd /private/tmp/keystone-password-policy-baseline
/Users/dmitry/Desktop/debug/password-policy-work/keystone/.venv/bin/python -m unittest -f keystone.tests.protection.v3.test_users.DomainAdminTests.test_user_can_create_users_within_domain
```

Тот же AttributeError, 1 error (`/tmp/keystone-protection-baseline.log`).
Несвязанные upstream protection tests не исправлялись. Этот дополнительный
запуск предшествовал уточнению SQL guard; итоговая проверка ниже включает
feature, SQL, API, validation, resource-option, policy и notification suites.

## Итоговая проверка и коммит

```sh
PATH="$PWD/.venv/bin:$PATH" .venv/bin/stestr run --concurrency 1 'test_password_policy_exemption|test_v3_identity|test_backend_sql|test_validation|test_resource_options_common|test_policy|common.test_notifications'
```

**1040 tests: 1037 passed, 3 skipped, 0 failed**, 49.57 s
(`/tmp/keystone-final-regression.log`). В составе — **31 новый feature test**.
Три skips штатные upstream WIP для иерархии domains/projects:
`test_create_project_under_domain_hierarchy`,
`test_create_project_with_parent_id_and_without_domain_id`,
`test_is_domain_sub_project_has_parent_domain_id`.

Ruff 0.6.9 check и format --check на всех семи измененных Python files: PASS.
Flake8/hacking 7.0.0 на тех же files: PASS. `git diff --check`: PASS.
Release-note YAML parsed: PASS. Имеются dependency warnings про deprecated
`pkg_resources` и upstream CADF fixture identifiers `region_one`/`region_two`;
они не менялись патчем.

Локальный коммит: `58ec376` (`Protect explicit SQL user password-policy exemptions`).
После коммита worktree чистый. Изменены только 10 файлов Keystone: API, policy,
resource-option registry, SQL driver, manager, password-change schema, tests,
resource-option doc, policy mapping doc, release note.

Патч не запускался на кластере, контейнерный Keystone image не строился.
MySQL/PostgreSQL transaction concurrency и Horizon UI отдельно не проверены.
Никаких production/network инфраструктурных действий не было.

Финальный review лога Flake8 после основного коммита выявил два H306
(import order: sql/validators и sqlalchemy dialects/event). Исправлены отдельным
коммитом **`323e6fadc43b342afb9315c0efef837c8dd10320`**; production logic не менялась.
Повторный Flake8 завершился exit 0, Ruff check/format --check — exit 0,
`git diff --check` — exit 0. Повторный feature run после исправления:
**31 passed, 0 failed, 0 skipped**, 4.03 s (`/tmp/keystone-final-feature.log`).
Финальный HEAD — `323e6fa`; worktree чистый. Для экспорта нужен полный diff
`537e65b2b1d4b8e0fe1faa09c8f882a6b2899b21..323e6fadc43b342afb9315c0efef837c8dd10320`.
