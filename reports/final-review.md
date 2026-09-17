# Независимое итоговое ревью

## Решение

**Одобрено для подготовки и передачи пакета патчей.** Открытых Critical,
Important или Minor замечаний к проверенной реализации не обнаружено.
Это решение о готовности исходников и инструкции, а не разрешение на
развёртывание и не подтверждение работоспособности кластера.

Проверены полный Keystone diff от
`537e65b2b1d4b8e0fe1faa09c8f882a6b2899b21`, включая 31 новый тест,
и Kolla diff
`54f4ee851cc2fc5db1068a8c5807f2b8e8e2c475..0f9aac2d479087808283ddb7fa382b6a8a1db00c`.
Итоговый Keystone HEAD: `323e6fadc43b342afb9315c0efef837c8dd10320`,
включая исправление порядка двух imports; рабочее дерево чистое.
Проверены текущие исходники, implementation
reports, отдельное Kolla review, README пакета, примеры и корневая SQL-инструкция.
Ревью не изменяло исходники и не запускало тестовые suites повторно.
Экспорт патчей, сборка sdist, применение к чистой базе и контрольные суммы
проверяются отдельно исполнителем упаковки и не являются результатом этого ревью.

## Безопасность и семантика Keystone

- `keystone/api/users.py:276` и `:365`: дополнительная policy проверяется
  при наличии ключа на create/update, включая `false` и `null`; обычное
  разрешение create/update остаётся обязательным. Request schema отклоняет
  некорректные типы до использования options.
- `keystone/common/policies/user.py:81`: default требует одновременно
  `role:admin` и `system_scope:all`, без deprecated admin fallback. Три
  объявленных scope допускают документированный явный operator override,
  не расширяя default. Обычный project/domain admin не классифицирует запись
  только за счёт роли.
- `keystone/identity/backends/sql.py:46`: только настоящий Boolean `true`
  в options целевого пользователя разрешает пропуск проверки. SQL create
  проверяет переданные options; update применяет overlay к сохранённым
  options перед проверкой нового пароля; self-change использует сохранённое
  состояние. Снятие флага и короткий пароль в одном запросе отклоняются.
- `keystone/identity/backends/sql.py:53`: update, включая изменение только
  классификации, и self-change сначала блокируют `User.id`, затем читают
  модель с options. Lock-query не содержит nullable JOIN. Четыре регрессии
  проверяют stale cached true/false для reset и self-change. Manager cache
  не используется для решения о пропуске SQL regex.
- `keystone/identity/core.py:1193`, `:1399`, `:1735`: перенос проверки
  ограничен драйверами с явной capability. Для остальных драйверов сохранён
  manager-side regex; это подтверждено чтением всех трёх путей, а не отдельным
  выполнением внешнего LDAP backend.
- `keystone/identity/schema.py:299` и SQL self-change сохраняют проверки
  типа и технических пределов. Проверка старого пароля, account state,
  `lock_password`, native revocation и cache invalidation не удалены.
  First-use, expiry и lockout остаются отдельными native options. Человеческие
  history/minimum-age проверки сохраняются; сервисная классификация их
  пропускает. Схема БД не меняется.
- `keystone/identity/core.py:1151`: аудит фиксирует успешные явные
  назначения, включая повторные значения, false и удаление, с итоговой
  классификацией и идентификаторами. Он не выдаёт cached old value за
  достоверное предыдущее состояние и не включает пароль/request body.

## Интеграция Kolla

- Включение явное, default `false`. При выключении используется штатный
  `openstack.cloud.identity_user`.
- `ansible/roles/service-ks-register/files/kolla_service_user.py:71`:
  точный user lookup по name/domain, проверки несовпадения и дубликатов,
  проверка project domain и поддержка Magnum trustee без default project.
  Создание отправляет пароль и четыре options одним POST. Обновление
  сохраняет посторонние options; `on_create` не вращает пароль, повторный
  вызов с уже актуальным состоянием не пишет; `always` сохраняет семантику
  ротации. Если options уже актуальны, PATCH только пароля безопасно
  опирается на актуальные SQL options внутри Keystone.
- Парольные задачи имеют безусловный `no_log: true`; модуль не возвращает
  пароль, SDK error body заменён общим сообщением и status code.
  Vault resolver toolbox не менялся. Общий путь и три отдельных Magnum
  вызова передают CA и соответствующие endpoint client cert/key.
- Helper копируется в существующий toolbox config mount; module search path
  передаётся отдельным argv. Исходная интеграция и упаковка Ansible-модуля
  подтверждены имеющимися проверками; выполнение именно внутри рабочего
  toolbox container не подтверждалось.
- Ограничение первого whole-Kolla `--check` и проверки после обновления helper
  явно описано: check mode не размещает новый файл и может видеть старую
  копию. Это не скрывается утверждением об успешной runtime-проверке.

## Инструкция и сборка

README и SQL-инструкция задают точную исходную базу и согласованный порядок:
сначала образ и policy во всех workers, затем явная классификация технических
identities и автоматизация, затем человеческая политика. Bootstrap/deployment
admin отделён от личного администратора. Динамические Heat/Magnum producers
обозначены как требующие собственного защищённого payload; эвристической
классификации по именам или ролям нет. Без их инвентаризации инструкция не
объявляет полное требование выполненным для конкретного кластера.

Сверены сохранённые официальные исходники инструкции сборки Kolla и
`keystone-base/Dockerfile.j2`: `[keystone-base] type=local` поддерживает tarball,
а образ устанавливает Keystone из извлечённого источника. Настройки
`keystone_tag` распространяются на семейство образов в supplied Kolla;
инструкция требует собрать нужные варианты и проверить digest/overrides.
Это проверка рецепта, без запуска Linux image build.

Regex разрешает 94 печатных ASCII-символа без пробела, требует минимум 8
символов и использует `\Z`. Порог `4`, временный первый пароль, отдельные
native exclusions, Horizon backend validation, приёмка и порядок отката
описаны согласованно. Конкурентная точность native lockout и прекращение
ранее выданного доступа не выдаются за результат новой опции.

## Проверки и разрешённое замечание

Просмотрен итоговый лог `/tmp/keystone-final-regression.log`: **1040 tests,
1037 passed, 3 skipped, 0 failed**, включая **31 новый feature test**.
Лог захвата SQL statements доказывает наличие lock-query и возможность
компиляции для MySQL/PostgreSQL; SQLite не доказывает реальное row locking.
Kolla implementation/review фиксируют **37 targeted tests passed**, syntax
checks и загрузку Ansible helper до проверки обязательных аргументов.

Во время ревью обнаружены два Minor H306 import-order замечания:
`keystone/identity/backends/sql.py:26` и
`keystone/tests/unit/test_password_policy_exemption.py:27`. Они исправлены
в итоговом коммите `323e6fa`; обновлённый `/tmp/keystone-flake8.log` содержит
только dependency warnings. Дополнительно просмотрен выполненный исполнителем
после исправления `/tmp/keystone-final-feature.log`: **31 passed, 0 failed,
0 skipped**. Функциональная логика при перестановке imports не менялась.

Два существующих Kolla Vault/mTLS failures и 29 Keystone protection setup
errors отделены от результатов патча; имеющееся baseline-воспроизведение
подтверждает несвязанный исходный дефект, а не скрытый регресс этой работы.

**Не проверены runtime:** production MySQL/MariaDB/Galera/PostgreSQL locking
и конкуренция, Linux Keystone image, рабочий toolbox container, несколько
Keystone workers, Horizon UI, реальные producer flows и развёртывание
кластера. Эти границы совместимы с задачей выпуска патч-пакета и должны
оставаться явно указанными в поставке.
