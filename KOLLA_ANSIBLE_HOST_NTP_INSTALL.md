# Установка host NTP для Kolla-Ansible 2025.1

## Краткий вывод

Патч `kolla-ansible-2025.1-host-ntp.patch` добавляет локальную роль
`host_ntp` в `bootstrap-servers`. Роль устанавливает `chrony`, полностью
управляет `/etc/chrony.conf`, проверяет конфигурацию, включает `chronyd` и
ждёт фактическую синхронизацию времени.

Роль по умолчанию выключена (`enable_host_ntp: false`). Само применение
патча к исходникам не меняет хосты. Изменения на хостах начинаются только
после явного включения роли и запуска `bootstrap-servers`.

> Не применяйте патч и не запускайте NTP-роль, пока текущий `reconfigure`
> не завершён и его результат не зафиксирован. Резкая коррекция времени может
> повлиять на TLS, токены, базы данных, очереди сообщений и HA-сервисы.

## Состав изменения

Патч:

- подключает `host_ntp` после `openstack.kolla.baremetal` в
  `ansible/kolla-host.yml`;
- добавляет тег `host-ntp` для отдельного запуска роли;
- поддерживает только хосты, для которых Ansible возвращает
  `ansible_facts.os_family == "RedHat"`;
- создаёт backup существующего `/etc/chrony.conf` при его изменении;
- перезапускает `chronyd` только при изменении конфигурации;
- завершает bootstrap ошибкой, если синхронизация не достигнута примерно за
  120 секунд при значениях по умолчанию.

Патч не изменяет `globals.yml`, inventory, установленную Galaxy collection и
не запускает `deploy`, `reconfigure` или какие-либо операции на BMC.

## Переменные в примерах

Подставьте свои пути и имя одного тестового узла:

```bash
KOLLA_SRC=/opt/kolla-ansible
NTP_PATCH=/path/to/kolla-ansible-2025.1-host-ntp.patch
INVENTORY=/etc/kolla/multinode
CANARY_HOST=controller01
```

`KOLLA_SRC` должен указывать на дерево исходников Kolla-Ansible 2025.1,
которое реально используется командой `kolla-ansible`.

Проверьте целостность патча:

```bash
shasum -a 256 "$NTP_PATCH"
```

Ожидаемый SHA-256:

```text
a2fa45e407367015728a09adb14cfe063ff31a2c8755b8afdad5e0a2b89757b6
```

## 1. Дождаться завершения текущей операции

Перед продолжением убедитесь, что запущенный `reconfigure` завершился. Сохраните
его exit code и итоговый вывод. Не запускайте параллельно второй Ansible-процесс
для тех же Kolla-хостов.

## 2. Проверить используемый путь Kolla-Ansible

```bash
python3 -c 'from kolla_ansible import utils; print(utils.get_data_files_path("ansible", "kolla-host.yml"))'
```

Если команда показывает установленный data directory, а не `$KOLLA_SRC`,
используйте один из контролируемых вариантов:

- editable install вашего Git-дерева;
- переменную `KOLLA_ANSIBLE_DATA_FILES_PATH="$KOLLA_SRC"` во всех командах
  применения и проверки.

Не редактируйте вручную файлы под `/usr/local/share` или в virtualenv: они
могут быть перезаписаны при обновлении пакета.

## 3. Проверить исходное дерево и патч

Рекомендуется работать в отдельной ветке чистого Git checkout, созданной от
вашей базы `stable/2025.1`:

```bash
git -C "$KOLLA_SRC" status --short --branch
git -C "$KOLLA_SRC" apply --check "$NTP_PATCH"
git -C "$KOLLA_SRC" diff --check
```

`git apply --check` должен завершиться без вывода. Если он сообщает конфликт,
не применяйте патч частично и не используйте `--reject`: сначала сопоставьте
вашу версию `ansible/kolla-host.yml` с базой патча.

## 4. Применить патч к исходникам

```bash
git -C "$KOLLA_SRC" apply "$NTP_PATCH"
git -C "$KOLLA_SRC" diff --check
git -C "$KOLLA_SRC" diff -- \
  ansible/kolla-host.yml \
  ansible/roles/host_ntp
```

На этом этапе изменены только исходники на deployment host. Удалённые узлы
ещё не затронуты.

## 5. Проверить семейство ОС всех целевых хостов

Локальная роль рассчитана на Red Hat-совместимые системы. Это особенно важно
для конфигурации с `kolla_base_distro: "sberlinux"`: значение
`kolla_base_distro` не заменяет проверку реальных Ansible facts.

```bash
ansible \
  -i "$INVENTORY" \
  baremetal \
  -m ansible.builtin.setup \
  -a 'filter=ansible_os_family'
```

Продолжайте только если каждый целевой хост возвращает:

```text
"ansible_os_family": "RedHat"
```

Также заранее проверьте, что выбранные NTP-серверы доступны с каждого хоста по
UDP/123 и являются доверенными источниками времени.

## 6. Зафиксировать состояние времени до изменения

Эти команды только читают состояние:

```bash
ansible \
  -i "$INVENTORY" \
  baremetal \
  -b \
  -m ansible.builtin.command \
  -a 'timedatectl status'

ansible \
  -i "$INVENTORY" \
  baremetal \
  -b \
  -m ansible.builtin.command \
  -a 'date -u +%s'
```

Если обнаружен большой разброс времени, остановитесь и согласуйте отдельное
окно работ. Значение по умолчанию `makestep 1.0 3` разрешает `chronyd` сделать
скачок времени при большом смещении в первых обновлениях после запуска.

## 7. Настроить NTP-серверы

Создайте `/etc/kolla/globals.d/10-host-ntp.yml` либо добавьте параметры в
`/etc/kolla/globals.yml`. Не дублируйте одни и те же переменные в обоих местах.

Пример для `globals.d`:

```yaml
---
enable_host_ntp: true

host_ntp_servers:
  - "ntp1.example.internal"
  - "ntp2.example.internal"
  - "ntp3.example.internal"

host_ntp_server_options: "iburst"
host_ntp_verify_sync: true
host_ntp_waitsync_tries: 60
host_ntp_waitsync_interval: 2
```

Замените имена на реальные адреса вашей инфраструктуры. Не отключайте штатную
проверку `prechecks_enable_host_ntp_checks`, если синхронизация должна работать.

## 8. Выполнить check mode на одном узле

```bash
KOLLA_ANSIBLE_DATA_FILES_PATH="$KOLLA_SRC" \
kolla-ansible \
  -i "$INVENTORY" \
  bootstrap-servers \
  --tags host-ntp \
  --limit "$CANARY_HOST" \
  --check \
  --diff
```

Check mode не заменяет реальный запуск: в нём шаблон не проверяется командой
`chronyd -p -f`, сервис не перезапускается и `chronyc waitsync` не выполняется.

Проверьте diff `/etc/chrony.conf`. Шаблон управляет этим файлом целиком и не
объединяет существующие ручные директивы с новым содержимым.

## 9. Применить роль на canary-узле

Только после отдельного разрешения на изменение времени:

```bash
KOLLA_ANSIBLE_DATA_FILES_PATH="$KOLLA_SRC" \
kolla-ansible \
  -i "$INVENTORY" \
  bootstrap-servers \
  --tags host-ntp \
  --limit "$CANARY_HOST"
```

Реальный запуск:

1. устанавливает пакет `chrony`;
2. валидирует новый конфиг через `chronyd -p -f`;
3. сохраняет предыдущий конфиг в backup при изменении;
4. запускает или перезапускает `chronyd`;
5. ждёт синхронизацию и выводит `chronyc tracking`.

Если `waitsync` завершился ошибкой, не переходите к остальным узлам. К этому
моменту новый конфиг уже установлен и `chronyd` запущен; автоматического отката
конфигурации роль не выполняет.

## 10. Проверить canary-узел

```bash
ansible \
  -i "$INVENTORY" \
  "$CANARY_HOST" \
  -b \
  -m ansible.builtin.shell \
  -a 'rpm -q chrony && systemctl is-enabled chronyd && systemctl is-active chronyd && chronyc -n sources -v && chronyc -n tracking && timedatectl status'
```

Ожидается:

- `chronyd` имеет состояния `enabled` и `active`;
- `chronyc sources -v` показывает выбранный источник `^*`;
- `chronyc tracking` показывает нормальный reference и ограниченное смещение;
- `timedatectl` показывает `System clock synchronized: yes`.

Проверьте состояние OpenStack/HA-сервисов на canary-узле по вашему штатному
регламенту до расширения изменения.

## 11. Расширить применение на остальные хосты

Применяйте роль последовательно, сохраняя кворум управляющих сервисов. Для
поштучной обработки inventory-группы:

```bash
KOLLA_ANSIBLE_DATA_FILES_PATH="$KOLLA_SRC" \
kolla-ansible \
  -i "$INVENTORY" \
  bootstrap-servers \
  --tags host-ntp \
  -e kolla_serial=1
```

После каждого узла проверяйте синхронизацию и состояние кластерных сервисов.
Не переходите к следующему узлу при ошибке.

## 12. Выполнить итоговые проверки

```bash
ansible \
  -i "$INVENTORY" \
  baremetal \
  -b \
  -m ansible.builtin.command \
  -a 'chronyc -n tracking'

KOLLA_ANSIBLE_DATA_FILES_PATH="$KOLLA_SRC" \
kolla-ansible \
  -i "$INVENTORY" \
  prechecks
```

Успешный Ansible/check-mode/syntax-check подтверждает структуру патча, но не
доказывает доступность NTP или синхронизацию живых хостов. Для runtime-приёмки
нужен фактический вывод `chronyc sources`, `chronyc tracking`, `timedatectl` и
штатных проверок здоровья кластера.

## Откат

### Остановить дальнейшее управление ролью

Установите в Kolla globals:

```yaml
enable_host_ntp: false
```

Это делает роль no-op при следующих `bootstrap-servers`, но не восстанавливает
старый конфиг, не удаляет пакет и не останавливает уже запущенный `chronyd`.

### Восстановить конфигурацию хоста

Сначала найдите созданные Ansible backup-файлы:

```bash
ls -1t /etc/chrony.conf*
```

Выберите нужный backup, проверьте его и только затем, в согласованное окно,
восстановите:

```bash
chronyd -p -f /etc/chrony.conf.SELECTED_BACKUP
cp -a /etc/chrony.conf.SELECTED_BACKUP /etc/chrony.conf
systemctl restart chronyd
chronyc -n tracking
```

Это live-изменение времени и сервиса; выполняйте его отдельно на каждом узле с
контролем здоровья кластера.

### Удалить изменение из исходников

Если патч ещё не закоммичен и поверх него нет других правок:

```bash
git -C "$KOLLA_SRC" apply --reverse --check "$NTP_PATCH"
git -C "$KOLLA_SRC" apply --reverse "$NTP_PATCH"
```

Если изменение было закоммичено, используйте обычный `git revert` этого
коммита. Откат исходников сам по себе не отменяет уже применённую конфигурацию
на хостах.

## Граница проверки

Локально можно подтвердить формат патча, чистое применение к совместимой базе,
Ansible syntax и идемпотентную структуру задач. Только запуск на ваших узлах
может подтвердить совместимость пакета `chrony` со SberLinux, доступность
реальных NTP-серверов, величину коррекции времени и отсутствие влияния на
работающий кластер.
