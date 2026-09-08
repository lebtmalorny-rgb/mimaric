# Mistral: planned live-migration wait, часть 1

Патч: `0001-fix-confirm-planned-Nova-live-migrations-before-powe.patch`.

- База Mistral: `7be711a1df54655fed9cfdaca66516023536558a`.
- Новый commit: `f9e57d78fd3f4ffd1aec03a87065d1df81b5bc88`.
- Локальная ветка исходников Mistral: `fix/planned-live-migration-wait`.
- Ветка публикации патча в `lebtmalorny-rgb/mimaric`:
  `codex/planned-live-migration-stage1`.
- SHA256 патча: `23bf6dcb75abed77dc7d4b8ac76302245a8f18a8ee982000df90b9949e173af1`.
- Итоговый Git tree: `ef6bcddc7f3586500ad6679f3448cc6b18b19a60`.

Это дополнительный патч к указанной базе старого Mistral PowerOps, не полный
набор PowerOps с нуля. На произвольную upstream-базу или `planned-return-v2`
применение не проверялось. Masakari, Kolla, YAML workflow и globals не меняются.

## Что проверено локально

- 163 теста PowerOps до упаковки и те же 163 после `git am` в чистую копию базы.
- Flake8 изменённых Python-файлов и `git diff --check` без ошибок.
- Независимый read-only review: существенных открытых замечаний нет.
- `git apply --check`, затем `git am` на точную базу; итоговый tree совпал.
- Offline `setup.py build_py`; новый модуль включён в пакет, совпадает с исходным
  файлом, импорт `clients`, `live_migration`, `planned` из build-каталога прошёл.

Контейнерный образ не собирался. Deploy/reconfigure, настоящие ВМ, BMC и SSH
не запускались. Перед публикацией повторены 163 теста в исходном worktree и
163 теста в чистой копии с применённым патчем; итоговый Git tree совпал.

Дополнительно: 12 проверок файлов поставки прошли. Общий набор из 31 проверки
прошёл на точных исторических версиях компонентов из корневого `DELIVERY.md`.
На текущем сочетании исходников Mistral/Masakari/Kolla этот старый набор имеет
7 несовпадений: revert fencing, выбор coordination backend, команды runtime
preflight, reconciliation workbook, проверки образов, форма последовательного
restart-цикла и форма проверки авторизации. На базе Mistral `7be711a` до этого
патча получены ровно те же 7 несовпадений с идентичными сообщениями assertions.
Это не новые регрессии этапа 1, но общий межкомпонентный набор на текущих
версиях не является зелёным и не доказывает готовность всего стенда.

## Состав этапа 1 для стенда

Этот каталог содержит только дополнительный патч Mistral и эту инструкцию.
Для проверки нужен образ Mistral с применённым патчем; изменение кода одним
reconfigure без обновления образа не доставляется. Сборку и перенос образов,
а также запуск операций на стенде выполняет оператор.

Принудительное отключение SDK response cache **не входит** в этот патч:
сейчас добавлена только проверка, отклоняющая включённый кеш. Обсуждавшаяся
точечная правка создания SDK-соединения остаётся отдельной доработкой.
Кеши Keystone/Memcached и globals для неё в этой публикации не меняются.
Этап 2 (planned → emergency handoff) также не включён.

## Применение к исходникам для своей сборки

В чистом checkout Mistral на указанной базе, когда patch-файл лежит в текущем
каталоге:

```bash
git rev-parse HEAD
git status --short
git apply --check 0001-fix-confirm-planned-Nova-live-migrations-before-powe.patch
git am 0001-fix-confirm-planned-Nova-live-migrations-before-powe.patch
```

При несовпадении базы или конфликте остановиться и проверить набор уже
наложенных патчей; не применять с `--reject` и не перезаписывать чужие изменения.
Это команды изменения локальных исходников, а не команды для работающего стенда.

## Ограничения

Патч требует Nova microversion >=2.59, доступа PowerOps к глобальной истории
миграций/ВМ всех проектов и выключенного SDK response cache. Он ждёт штатные
промежуточные состояния, подтверждает новую completed migration UUID и
ACTIVE/null на её destination; перед Ironic повторно проверяет source через Nova.
HTTP POST миграции не повторяется после потери ответа, redirect или reauth.

Nova-пустота source не доказывает отсутствия локальных доменов/дисков.
Историческая evacuation `done` пока консервативно блокирует затронутую плановую
операцию до разрешения соответствующего состояния Nova. Аварийный handoff,
возврат после evacuation и `planned-return-v2` здесь не менялись.

Полное описание, тестовая матрица и доказательные границы включены в патч:
`docs/POWEROPS-PLANNED-LIVE-MIGRATION-WAIT.md`.
