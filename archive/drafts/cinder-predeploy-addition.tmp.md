### 3.4. Что подготовить до первого deploy

**Пользовательский конфиг вы создаёте до развёртывания. Полный рабочий `cinder.conf` Kolla-Ansible собирает из шаблона и ваших дополнений во время `deploy`.** Поэтому ждать появления контейнера, чтобы вписать параметры хранилища, не требуется.

Машина, с которой запускается `kolla-ansible`, далее называется **deploy-узлом**. Это не обязательно controller или storage-хост. Файлы в следующем дереве находятся именно на deploy-узле:

```text
/etc/kolla/
├── globals.yml                         # общие переменные развёртывания
├── passwords.yml                       # служебные секреты OpenStack
├── multinode                           # inventory: имена и группы серверов
└── config/                             # пользовательские дополнения к конфигам
    ├── nfs_shares                      # адреса NFS export
    └── cinder/
        ├── cinder-volume.conf          # ваш override для cinder-volume
        └── cinder_huawei_dorado.xml     # параметры массива и доступ к его API
```

Это дерево для примера с одним общим набором NFS + Dorado. Создавать все допустимые override-файлы из раздела 3.2 не нужно. В частности, `/etc/kolla/config/cinder.conf` здесь не нужен: дополнение ограничено сервисом `cinder-volume`.

| Файл | Кто подготавливает | Когда |
|---|---|---|
| `/etc/kolla/globals.yml`, `/etc/kolla/multinode` на deploy-узле | Администратор развёртывания | До `bootstrap-servers`, затем уточняет перед `prechecks` и `deploy` |
| `/etc/kolla/passwords.yml` на deploy-узле | Администратор и штатный механизм подготовки секретов | До вызовов Kolla-Ansible; в обычном файловом режиме — из шаблона с заполнением через `kolla-genpwd` |
| `/etc/kolla/config/nfs_shares` на deploy-узле | Администратор по данным владельца NFS | До `deploy`; удобнее завершить весь комплект до `prechecks` |
| `/etc/kolla/config/cinder/cinder-volume.conf` на deploy-узле | Администратор развёртывания | До `deploy` |
| `/etc/kolla/config/cinder/cinder_huawei_dorado.xml` на deploy-узле | Администратор по данным владельца массива | До `deploy`; к этому моменту нужны действующие реквизиты API |
| `/etc/kolla/cinder-volume/cinder.conf` на целевом узле `cinder-volume` | Роль Cinder | Во время генерации конфигурации в `deploy` |
| `/etc/cinder/cinder.conf` внутри контейнера | Механизм конфигурации контейнера | При запуске контейнера из подготовленных файлов |

Совпадение начала пути `/etc/kolla` на разных машинах не означает, что это один файл. Вы редактируете **исходные overrides на deploy-узле**; роль создаёт **итоговые файлы на целевых узлах**. Итоговый конфиг содержит также настройки БД, Keystone, RabbitMQ и другие параметры, которые не нужно вручную переписывать в свой override.

Основание: значения путей в `ansible/group_vars/all.yml:7–16`; объединение и назначение файла в `ansible/roles/cinder/tasks/config.yml:90–103`; путь внутри контейнера в `ansible/roles/cinder/templates/cinder-volume.json.j2:2–8`. В этом CLI стандартный каталог — `/etc/kolla`, а `globals.yml` и `passwords.yml` передаются Ansible как файлы переменных: `kolla_ansible/ansible.py:24–26, 193–210, 247–259`. Все относительные пути исходников указаны от каталога `kolla-ansible-pvs_1.0.0`.

### 3.5. Пошаговая подготовка файлов и учётных данных

#### Шаг 1. Получить данные от администраторов хранилищ

Для NFS нужны имя/IP сервера и точный путь export, разрешённые клиентские хосты, права и необходимые параметры монтирования. Для Dorado нужны модель, версия ПО, выбранный транспорт, пул и параметры доступа к API. Транспортная подготовка описана в разделе 7.

| Данные | Где задаются | Для чего используются |
|---|---|---|
| NFS server и export | `/etc/kolla/config/nfs_shares` | Указать, какую файловую систему монтировать |
| Разрешённые NFS-клиенты, права на export и файлы | На NFS-сервере; соответствующие права и параметры — на клиентской стороне | Разрешить доступ узлам Cinder и compute; в обычной схеме NFS здесь нет пары «логин/пароль хранилища» |
| Имя пользователя и пароль API Dorado | Элементы `<UserName>` и `<UserPassword>` в Huawei XML | Авторизация драйвера в управляющем API массива |
| Управляющий URL Dorado | Элемент `<RestURL>` в Huawei XML | Адрес API; это не адрес порта передачи данных iSCSI |
| Учётные данные iSCSI CHAP, если CHAP используется | Отдельная настройка доступа инициаторов, согласованная с массивом и драйвером | Аутентификация iSCSI; это отдельные реквизиты, не пароль API Dorado |
| `cinder_keystone_password` | В обычном режиме `/etc/kolla/passwords.yml` | Пароль сервисной учётной записи Cinder в Keystone |
| `cinder_database_password` | В обычном режиме `/etc/kolla/passwords.yml` | Пароль пользователя БД Cinder |

NFS с дополнительной схемой аутентификации, например Kerberos, требует своей подготовки; обычный пример `server:/export` её не описывает. Формат списка export подтверждён [документацией NFS backend](https://docs.openstack.org/cinder/2025.1/admin/nfs-backend.html). Назначение полей API и отдельная настройка CHAP описаны в [документации Huawei driver 2025.1](https://docs.openstack.org/cinder/2025.1/configuration/block-storage/drivers/huawei-storage-driver.html).

`kolla-genpwd` не создаёт пользователя на Dorado и не генерирует согласованный с массивом пароль. Он заполняет незаданные служебные значения в существующем файле `passwords.yml` (`kolla_ansible/cmd/genpwd.py:70–119`). В обычном файловом режиме начальная подготовка паролей выполняется командой:

```bash
kolla-genpwd -p /etc/kolla/passwords.yml
```

Перед этой командой на deploy-узле уже должен существовать `passwords.yml`, подготовленный из шаблона установленной версии. Действующие файлы существующего облака нельзя заменять новым пустым шаблоном.

В архиве есть отдельный режим `enable_config_vault`, по умолчанию выключенный. Если он используется, служебные секреты OpenStack подготавливаются по его процедуре. Это само по себе не означает, что можно поместить произвольную ссылку на секрет или Jinja-выражение в Huawei XML: исследованная задача доставки XML выполняет обычное копирование.

#### Шаг 2. Задать переменные в globals.yml

Для рассматриваемого совместного подключения на deploy-узле в `/etc/kolla/globals.yml`:

```yaml
enable_cinder: "yes"
enable_cinder_backend_lvm: "no"
enable_cinder_backend_nfs: "yes"

cinder_backend_huawei: "yes"
cinder_backend_huawei_xml_files:
  - cinder_huawei_dorado.xml
```

Эти строки дополняют общую конфигурацию облака; они не заменяют остальные параметры `globals.yml`.

`enable_cinder_backend_nfs` включает штатную NFS-секцию. `cinder_backend_huawei` включает доставку перечисленных XML-файлов. Саму секцию Huawei и полный список `enabled_backends` вы задаёте в следующем шаге.

Если после уточнения проекта выбран **iSCSI**, для его служб нужен также `enable_cinder_backend_iscsi: "yes"`. Настройки multipath выбираются вместе с транспортной схемой; их действие на Cinder и Nova разобрано в разделе 7.4. Флаг Huawei не выбирает транспорт автоматически.

Основание: `ansible/group_vars/all.yml:935–939, 985, 1309–1310`; `ansible/roles/cinder/defaults/main.yml:243–267`; `ansible/roles/cinder/templates/cinder.conf.j2:177–185`.

#### Шаг 3. Создать список NFS export

На deploy-узле создать `/etc/kolla/config/nfs_shares`. Пример одной строки:

```text
nfs.example:/volumes
```

Замените имя сервера и путь на фактические. В этот файл не вписывают логин и пароль администратора NFS-сервера. Сам export и разрешения клиентов должны быть настроены на сервере заранее.

Во время `deploy` роль возьмёт список с deploy-узла, доставит его в `/etc/kolla/cinder-volume/nfs_shares` на целевом хосте; контейнер получит `/etc/cinder/nfs_shares`. Доставка: `ansible/roles/cinder/tasks/config.yml:126–145`; контейнерный путь: `ansible/roles/cinder/templates/cinder-volume.json.j2:23–28`.

#### Шаг 4. Создать свой cinder-volume.conf

На deploy-узле создать `/etc/kolla/config/cinder/cinder-volume.conf`. Ниже учебный вариант **для iSCSI**, соответствующий примеру раздела 6:

```ini
[DEFAULT]
enabled_backends = nfs-1,dorado-1

[dorado-1]
volume_driver = cinder.volume.drivers.huawei.huawei_driver.HuaweiISCSIDriver
volume_backend_name = dorado
cinder_huawei_conf_file = /etc/cinder/cinder_huawei_dorado.xml
```

Это весь ваш небольшой override для данного примера. Секция `[nfs-1]` поступит из шаблона. Путь `/etc/cinder/cinder_huawei_dorado.xml` относится к **контейнеру**, потому что именно там драйвер будет открывать файл.

Пока модель и транспорт массива не определены, этот пример нельзя считать утверждённой конфигурацией площадки. Для FC выбирают соответствующий класс и XML, как описано в разделе 6.2. При наличии других backend их имена также должны остаться в `enabled_backends`: значение заменяется целиком.

#### Шаг 5. Создать Huawei XML и внести реквизиты API

На deploy-узле создать `/etc/kolla/config/cinder/cinder_huawei_dorado.xml`. Именно **на этом шаге, до `deploy`**, в файл вносятся реквизиты уже подготовленной учётной записи массива.

Учебный каркас для иллюстрации iSCSI и расположения полей:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <Storage>
    <Product>Dorado</Product>
    <Protocol>iSCSI</Protocol>
    <UserName>REPLACE_WITH_ARRAY_API_USER</UserName>
    <UserPassword>REPLACE_WITH_ARRAY_API_PASSWORD</UserPassword>
    <RestURL>REPLACE_WITH_ARRAY_REST_URL</RestURL>
  </Storage>
  <LUN>
    <LUNType>Thin</LUNType>
    <StoragePool>REPLACE_WITH_POOL_NAME</StoragePool>
  </LUN>
  <iSCSI>
    <DefaultTargetIP>REPLACE_WITH_ISCSI_TARGET_IP</DefaultTargetIP>
  </iSCSI>
</config>
```

Все `REPLACE_WITH_...` — текстовые заглушки. Администратор массива предоставляет действительные URL, пул, адреса и реквизиты. XML, включая `Product`, параметры инициаторов и multipath, нужно сверить с моделью, ПО и драйвером. Этот каркас не подтверждает совместимость любого Dorado. Значения `Dorado`, `iSCSI`, `Thin` и назначение полей приведены по [официальной документации Huawei 2025.1](https://docs.openstack.org/cinder/2025.1/configuration/block-storage/drivers/huawei-storage-driver.html#volume-driver-configuration).

Секреты вводите в защищённом редакторе, а не в командах `echo`, аргументах команд или истории shell. Например, для создания **нового** XML, под учётной записью с правом записи в каталог:

```bash
umask 077
mkdir -p /etc/kolla/config/cinder
vi /etc/kolla/config/cinder/cinder_huawei_dorado.xml
chmod 0600 /etc/kolla/config/cinder/cinder_huawei_dorado.xml
```

Ansible запускается под учётной записью, которая может прочитать этот файл. Защитите также временные и резервные копии редактора. В XML символы `&` и `<` внутри значений записываются как `&amp;` и `&lt;`; проверка синтаксиса XML не подтверждает правильность самого пароля.

**В XML должны быть готовые значения.** Запись `{{ dorado_password }}` не подставит пароль из `passwords.yml`: задача `external_huawei.yml:2–11` использует `copy`, а не `template`. При `deploy` скопированный XML попадёт на storage-хост, затем в контейнер по пути из `cinder_huawei_conf_file`.

Файлы с действительными секретами и их копии не добавляйте в Git. В репозитории можно хранить только отдельные примеры с заглушками. Не выводите полный XML и сгенерированный `cinder.conf` в общие журналы или отчёты.

### 3.6. Порядок запуска: подготовка → bootstrap → prechecks → deploy

Следующая последовательность относится к **первичному развёртыванию**. Команды приведены для выполнения оператором на deploy-узле после подготовки окружения Kolla-Ansible этого форка, его зависимостей, SSH-доступа и общей конфигурации облака.

| Момент | Что уже готово | Что происходит |
|---|---|---|
| До `bootstrap-servers` | Inventory, `globals.yml`, доступ SSH/become, файл служебных секретов; определены роли серверов и транспорт | Оператор подготавливает исходные данные. Удобно сразу заполнить комплект файлов хранилищ из раздела 3.5 |
| `bootstrap-servers` | Конфигурация базовой подготовки серверов | Вызывается `kolla-host.yml` и внешняя роль `openstack.kolla.baremetal`; итоговый `cinder.conf` ролью Cinder здесь не собирается |
| До `prechecks` | Завершены подготовка NFS/массива, транспортных путей и все overrides/XML | Оператор проверяет значения и согласованность файлов; фактические секреты уже внесены |
| `prechecks` | Все выбранные сервисы и backend описаны | Выполняются предусмотренные Ansible-проверки. Их успех не доказывает вход в API Dorado, доступ ко всем export или работоспособность attach |
| До `deploy` | Проверки пройдены, образы подготовлены штатной процедурой площадки | В этом форке `deploy` сначала проверяет локальные образы через image-lock preflight |
| `deploy` | Полный комплект исходных файлов и доступных зависимостей | Роль Cinder собирает `cinder.conf`, доставляет XML и `nfs_shares`, подготавливает и запускает сервисы |
| После `deploy` | Сервисы запущены | Проверяются backend и пулы, затем типы томов и полный цикл тестового тома из разделов 6 и 9 |

Основные команды в синтаксисе CLI исследованного архива; следующую выполняют после успешного завершения предыдущего этапа:

```bash
kolla-ansible bootstrap-servers -i /etc/kolla/multinode
kolla-ansible prechecks -i /etc/kolla/multinode
```

Затем подготовьте контейнерные образы по процедуре площадки. Если их нужно загрузить из настроенного registry, штатная команда:

```bash
kolla-ansible pull -i /etc/kolla/multinode
```

После успешных проверок и подготовки образов:

```bash
kolla-ansible deploy -i /etc/kolla/multinode
```

Параметры хранилища читаются из подготовленных файлов. Команда `deploy` не запрашивает в диалоге логин и пароль Dorado. XML технически нужен к моменту доставки в `deploy`; требование подготовить его до `prechecks` в этой последовательности — практический порядок работы, а не наличие специальной проверки XML в роли.

`genconfig` для этого порядка не обязателен. В исследованном форке доставка изменившегося Huawei XML уведомляет обработчик перезапуска `cinder-volume`, поэтому `genconfig` нельзя безусловно использовать как безопасный предварительный просмотр работающего облака; см. раздел 10.2.

Основание: `kolla_ansible/cli/commands.py:196–226, 262–294, 375–389`; `ansible/kolla-host.yml:1–14`; порядок действий роли — `ansible/roles/cinder/tasks/deploy.yml:1–14`; проверки Cinder — `ansible/roles/cinder/tasks/precheck.yml`. Аргумент `-i` объявлен в `kolla_ansible/ansible.py:62–68`.
