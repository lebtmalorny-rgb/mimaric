# Два отдельных патча: Kolla-Ansible и Masakari

Ветка публикации в `lebtmalorny-rgb/mimaric`:
`codex/masakari-service-role-and-revert`.

Это два дополнительных патча к уже исправленным исходникам PowerOps, а не
полный комплект с нуля. Каждый применяется только к своему репозиторию.
Одинаковый номер `0001` не означает общую серию; не запускайте `git am *.patch`
для обоих файлов в одном checkout.

## 1. Kolla-Ansible: роль service для пользователя Masakari

Файл: `0001-fix-grant-Masakari-service-role-for-PowerOps.patch`.

- База Kolla-Ansible: `792f2f0998697de4c9d4fad396d05de95208fd36`.
- Коммит исходников: `7fe65f436be842fc6bc0ea3fdb09d748f7254780`.
- Локальная ветка исходников: `fix/masakari-powerops-service-role`.
- Итоговый Git tree: `b36026c4d9636eb4cc75538cb76b4b9e5856c88c`.
- SHA256 файла: `e5c41aa1dc0faa96cbcf653a5a989e1ed2df3bdae7118e7134fa6e85a1716cde`.

При `enable_powerops=true` регистрация сервиса создаёт роль `service` и
назначает её пользователю `masakari_keystone_user` в проекте `service`,
сохраняя назначение `admin`. Настраиваемое имя пользователя поддерживается.
При выключении PowerOps существующая роль `service` не отзывается.

Это правка Kolla-Ansible на машине развёртывания, не Python-кода Masakari.
В указанной базе `masakari/tasks/reconfigure.yml` импортирует `deploy.yml`,
который выполняет `register.yml`: изменение роли применяется при выполнении
этой регистрации в deploy/reconfigure. Само применение Git-патча Keystone
не меняет. Пересборка сервисного образа только ради назначения роли не нужна.

Назначение роли не доказывает доступ ко всем API при произвольных policy
overrides: после применения нужен новый токен сервисной учётки и read-only
проверка необходимых операций Ironic. Политики Ironic этим патчем не меняются.

## 2. Masakari: достоверная диагностика при rollback fencing

Файл: `0001-fix-report-unconfirmed-fencing-accurately-on-rollbac.patch`.

- База Masakari: `4fcbe3da46d4ec6a231be10a933fd57e8856663f`.
- Коммит исходников: `1218340934e0f92a1ae81af82cb2636d3d155f52`.
- Локальная ветка исходников: `fix/powerops-fence-revert-diagnostic`.
- Итоговый Git tree: `d5f7b1591caaf2e512c6e562280de48990632a80`.
- SHA256 файла: `f80095b320d49e60e3dd503dd9f752add5441c428771d8b44a9a6877dac7a5a4`.

TaskFlow вызывает `revert` и для неуспешной fencing-задачи. Старое сообщение
ошибочно утверждало, что хост остаётся выключенным, даже если выключение не
подтверждалось. Патч различает предыдущее подтверждение `power off` и отсутствие
такого подтверждения. Текущее питание при rollback не перепроверяется.

Изменение находится в Python-коде Masakari: его нужно включить в собранный
образ, используемый `masakari_engine`. Один reconfigure со старым образом
этот код не добавит. Порядок fencing/evacuation и команды питания не меняются;
автоматического включения или возврата после аварии патч не добавляет.

## Применение

В чистом checkout соответствующего компонента сначала сверить базу:

```bash
git rev-parse HEAD
git status --short
git apply --check /absolute/path/to/the-component.patch
git am /absolute/path/to/the-component.patch
```

Вместо `/absolute/path/to/the-component.patch` указать только файл для этого
компонента из раздела 1 или 2. При другой базе или конфликте остановиться:
не использовать `--reject` и не перезаписывать существующие изменения.
Сборку, перенос образов и применение к стенду выполняет оператор.

## Проверки и границы

Перед публикацией повторно прошли 64 теста Kolla-Ansible PowerOps/Masakari
и 93 теста Masakari PowerOps/host recovery. Тесты используют локальные doubles
API и реальный TaskFlow, но не подключаются к стенду. Для прямого запуска
Masakari-тестов нужны ранний `eventlet.monkey_patch(os=False)` до остальных
импортов и `masakari.objects.register_all()`; для Kolla — окружение с Ansible
2.18, PyYAML и pbr. Системные Python-окружения не изменялись.

Проверки исходного `git diff --check` и flake8 изменённых файлов Masakari
прошли. Точные контрольные деревья после применения патчей приведены выше.
Сборка контейнеров, deploy/reconfigure, изменения Keystone, операции BMC и
эвакуация на стенде в рамках публикации не выполнялись.

В этой публикации нет Mistral, отключения SDK response cache, этапа 2
planned-to-emergency handoff или `planned-return-v2`. Патч Mistral для этапа 1
опубликован отдельно в ветке `codex/planned-live-migration-stage1`.
