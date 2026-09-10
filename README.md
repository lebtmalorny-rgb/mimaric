# PowerOps — единый актуальный комплект

Основная ветка репозитория `mimaric` — **main**. Состав сверен 10 сентября 2026 года.

Здесь объединены актуальные документы, диагностика и дополнительный патч для
пользовательской базы **0809**. Разработка Horizon сохранена отдельно.
`planned-return-v2` и planned-return kit выведены из текущего набора.

## Что использовать

| Задача | Файл / каталог |
|---|---|
| Ultra: короткие команды выключения и перезагрузки | [ULTRA-POWER-COMMANDS.md](docs/ULTRA-POWER-COMMANDS.md) |
| Общее устройство и сценарии | [POWEROPS-OVERVIEW.md](docs/POWEROPS-OVERVIEW.md) |
| Ручная диагностика всей цепочки | [POWEROPS-DIAGNOSTICS.md](docs/POWEROPS-DIAGNOSTICS.md) |
| Globals, Jinja, задержки и тайминги | [POWEROPS-CONFIGURATION.md](docs/POWEROPS-CONFIGURATION.md) |
| Пользователи, роли и аутентификация | [POWEROPS-AUTHENTICATION.md](docs/POWEROPS-AUTHENTICATION.md) |
| Ironic, Ansible-роли и enroll | [POWEROPS-IRONIC-ENROLLMENT.md](docs/POWEROPS-IRONIC-ENROLLMENT.md) |
| Consul, матрица и её генерация | [POWEROPS-CONSUL.md](docs/POWEROPS-CONSUL.md) |
| Команды для разбора отдельных проблем | [POWEROPS-TROUBLESHOOTING-COMMANDS.md](docs/POWEROPS-TROUBLESHOOTING-COMMANDS.md) |
| Универсальный сбор PowerOps | [collect-v2.yml](tools/diagnostics/collect-v2.yml) |
| Медленный Mistral, 504, зависшие executions | [collect-mistral.yml](tools/diagnostics/collect-mistral.yml) |
| Masakari: Nova down после fencing | [Патч и порядок применения](hotfixes/masakari-post-fence-nova-down/README.md) |
| Horizon: исходники и зависимые патчи | [horizon/README.md](horizon/README.md) |

Плейбуки автономные: достаточно скопировать нужный YAML. Запускать из обычного
операторского окружения с рабочим OpenStack CLI, не через `sudo`:

```bash
ansible-playbook collect-v2.yml
ansible-playbook collect-mistral.yml
```

Результат — приватный TXT в `artifacts/` рядом с соответствующим плейбуком.
Оба сборщика используют текущий момент/интервал, а не фиксированную дату аварии.
Подробности, ограничения и настройки — [диагностика](tools/diagnostics/README.md).

## Архитектурные решения

- [ADR-0001: локальный disk-monitor](docs/adr/0001-local-disk-monitor.md) —
  предложенная интеграция локальных проверок ФС/диска с Consul и hostmonitor.
  Не реализовано; автоматическое восстановление не включено.

## База и порядок применения

1. Использовать именно три пользовательских архива `0809`, перечисленных с SHA256
   в [baselines/0809.json](baselines/0809.json). Архивы содержат исходники для
   существующего процесса сборки; сами архивы в этот Git-комплект не включены.
2. Mistral `0809` уже содержит этап 1 ожидания live migration. Kolla-Ansible
   `0809` содержит service-role wiring Mistral/Masakari. **Не накладывать повторно
   старые repair-0509, service-role и planned-live-migration-stage1 патчи.**
3. Для Masakari `0809` дополнительным остаётся один патч
   [post-fence Nova down](hotfixes/masakari-post-fence-nova-down/README.md).
   Перед наложением проверить чистоту исходников и `git apply --check`.
4. Образы и конфигурацию доставлять существующим процессом после отдельных
   проверок. Объединение репозитория ничего не пересобирает и не меняет на стенде.

**Не применять все найденные `.patch` одной командой.** Каталог `horizon/`
имеет другую, зафиксированную базу. Его объединение в Git не доказывает
совместимость с `0809` и не включает Horizon на стенде.

При сборке сохранить проверенную совместимость зависимостей: на стенде импорт
`pkg_resources` ломался после перехода на setuptools 83, а возврат на ветку 80
устранил ошибку импорта. Это не новый pin в данном комплекте; проверять версии
и импорты нужно внутри собранных образов Mistral и Masakari.

## Проверки и известные ограничения

Из корня репозитория:

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tools/diagnostics/tests -v
python3 -m unittest discover -s tools/diagnostics/tests_mistral -v
shasum -a 256 -c SHA256SUMS
git diff --check
```

Для Mistral-тестов нужны PyYAML и Jinja2. Дополнительные Ansible/CLI тесты
включаются явно; команды приведены в [диагностическом README](tools/diagnostics/README.md).
Horizon проверяется отдельно, из своего каталога.

Сохраняются ручная пауза `operator_inspection_gate`, необходимость API-прав,
отключённого SDK response cache и проверки фактического состояния перед возвратом.
API-наблюдения не доказывают отсутствие stale domains на недоступном хосте.
См. [проверку плановой миграции](docs/AUDIT-2026-09-09-planned-off-live-migration.md)
и [запись исходного инцидента](docs/INCIDENT-2026-09-07-planned-off-live-migration.md).

[Состав объединения и происхождение файлов](docs/REPOSITORY-CONSOLIDATION.md).
[Результаты локальных проверок объединения](docs/REPOSITORY-VERIFICATION.md).
