# Watcher automation hold

Самодостаточный offline-комплект патчей и общего wheel для аварийной блокировки
периодической автоматизации Watcher. Точные базы, итоговые commit/tree и SHA256
зафиксированы в `manifest.json`.

Порядок подготовки исходников, сборки образов, миграции, включения и ручного
возобновления описан в
[`docs/WATCHER-AUTOMATION-HOLD.md`](../../docs/WATCHER-AUTOMATION-HOLD.md).

Локальная проверка неизменности комплекта:

```sh
python3 tools/watcher_automation_hold_delivery.py verify
```

Replay одного компонента всегда создаёт новый каталог и отказывается работать с
неверным исходным Git tree:

```sh
python3 tools/watcher_automation_hold_delivery.py replay \
  --component watcher --source /path/to/exact/watcher-base \
  --output /tmp/watcher-hold-replay/watcher
```

Для Masakari сначала нужен включённый в комплект prerequisite
`0000-prerequisite-post-fence-nova-down.patch`; replay принимает уже
подготовленное дерево базы `e7943db...`. Для Kolla-Ansible нужно сохранить четыре
исходные ссылки из `required_symlinks`; `etc/kolla/passwords.yml` остаётся в
рабочем каталоге, но исключается из сравниваемого Git tree и не поставляется.
