# Cinder 2025.1: проверка active-active для руководства

Дата проверки: 2026-09-16. Это исследовательская записка и готовый фрагмент для русского руководства. Инфраструктура не запускалась и не изменялась.

## Краткий вывод

- Из явно шаблонизированных backend этого форка Cinder 2025.1 поддерживает active-active у **Ceph RBD, Pure iSCSI/FC/NVMe-RoCE/NVMe-TCP и Lightbits**. Поддержка подтверждена матрицей и атрибутом конкретных классов в upstream stable/2025.1.
- **Generic NFS, LVM, Quobyte, VMware VMDK/FCD и встроенные Huawei iSCSI/FC не поддерживают этот режим** в проверенном исходнике. Это относится к режиму нескольких `cinder-volume`, совместно управляющих одним backend.
- Для **Huawei Dorado** нельзя обещать Cinder AA по названию массива, двум контроллерам, multipath, HyperMetro либо наличию XML-файла. Встроенные Huawei-классы наследуют `SUPPORTS_ACTIVE_ACTIVE = False`; другой драйвер от производителя необходимо проверять отдельно по версии, протоколу, модели и прошивке.
- В опубликованной матрице **именно 2025.1** нет конфликта с этим кодом: `driver.huawei_dorado=missing`, `driver.nfs=missing`. Поисковая выдача `latest` и строки других возможностей не являются подтверждением AA 2025.1.
- Для generic NFS и встроенного Huawei также отдельно не подтверждён **multiattach**: матрица 2025.1 ставит `missing`, код capability `multiattach=True` не публикует. Это существенно для нескольких одновременных чтений одного Glance Image-Volume.

## Версия и граница доказательства

Локальный каталог: `kolla-ansible-pvs_1.0.0`. Это распакованное дерево без `.git`; локальный commit определить нельзя. У форка `ansible/group_vars/all.yml:852-854` задано `openstack_release: "latest"`, `openstack_tag: "{{ openstack_release }}"`, а `ansible/roles/cinder/defaults/main.yml:92-96` получает тег Cinder из `openstack_tag`. Следовательно, сам архив **не доказывает**, что реально запускаемый образ содержит именно Cinder 2025.1.

Upstream проверен по ветке `stable/2025.1`, SHA **`ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b`**. SHA получен через `git ls-remote https://github.com/openstack/cinder.git refs/heads/stable/2025.1`. Проверенная онлайн-матрица подписана `cinder 26.3.1.dev1`. Ни состав фактического контейнера, ни версия установленного vendor-драйвера, ни реальный failover не проверены.

Дополнительная локальная проверка примера Ceph: точные фрагменты `cinder.conf.j2` (строки 24–32, 147–255, 275–285) отрендерены Jinja с `StrictUndefined` и явно заданными входными значениями; восемь ожидаемых полей подтвердились, NFS-драйвер в результате отсутствует. Это проверка выбранных секций шаблона, а не полный Ansible render/deploy. Использован уже существующий `/tmp/watcher-hold-venv/bin/python`; зависимости не устанавливались.

SHA-256 локальных файлов:

```text
970bdcee8493e6b5955ad1c9c53096efe54959cf6add79bc8a528b51ec52219d  ansible/roles/cinder/templates/cinder.conf.j2
493ca5c43355ff78427d26475bfb7dad2a61e8c819bb02c7414954311ddfcb5a  ansible/roles/cinder/tasks/precheck.yml
4aa9e0e833ae6296d9d92cbc4b53ba9794507c02498fbb116f61a4c9b53b0bd5  ansible/group_vars/all.yml
```

## Первичные источники

Для исходников ссылки закреплены на SHA, поэтому не изменятся вместе с веткой:

- [Матрица Cinder 2025.1](https://docs.openstack.org/cinder/2025.1/reference/support-matrix.html).
- [Исходник матрицы, AA: строки 981–1063](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/doc/source/reference/support-matrix.ini#L981).
- [Исходник матрицы, multiattach: строки 818–900](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/doc/source/reference/support-matrix.ini#L818).
- [Cinder HA, исходный документ stable/2025.1](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/doc/source/contributor/high_availability.rst): координация 711–717, active-passive 925–936, cluster 938–949, opt-in драйвера 1055–1075.
- [Базовый запрет AA, driver.py:419–424](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/driver.py#L419).
- [Runtime-проверка запрета, manager.py:311–323](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/manager.py#L311).
- [Kolla-Ansible 2025.1: Cinder HA](https://docs.openstack.org/kolla-ansible/2025.1/reference/storage/cinder-guide.html#ha).
- [Kolla-Ansible 2025.1: External Ceph / Cinder](https://docs.openstack.org/kolla-ansible/2025.1/reference/storage/external-ceph-guide.html#cinder).
- [Huawei driver 2025.1: XML, iSCSI/FC, multipath, модели/версии](https://docs.openstack.org/cinder/2025.1/configuration/block-storage/drivers/huawei-storage-driver.html).
- [Glance 2025.1: multiattach Image-Volume](https://docs.openstack.org/glance/2025.1/configuration/configuring.html#configuring-multi-attach-volume-type).

## Проверенные backend и классы

`missing` в таблице означает отсутствие заявленной возможности именно в матрице AA 2025.1, а не отсутствие обычной поддержки backend в Cinder.

| Backend из форка | Класс `volume_driver` | AA 2025.1 | Проверка исходника |
|---|---|---|---|
| Ceph RBD | `cinder.volume.drivers.rbd.RBDDriver` | Да | [rbd.py:285–305](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/rbd.py#L285), явно `SUPPORTS_ACTIVE_ACTIVE = True` |
| Generic NFS | `cinder.volume.drivers.nfs.NfsDriver` | Нет | [nfs.py:83](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/nfs.py#L83), цепочка RemoteFS → BaseVD без opt-in |
| LVM | `cinder.volume.drivers.lvm.LVMVolumeDriver` | Нет | [lvm.py:81](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/lvm.py#L81), VolumeDriver → BaseVD без opt-in |
| VMware VMDK | `cinder.volume.drivers.vmware.vmdk.VMwareVcVmdkDriver` | Нет | [vmdk.py:250](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/vmware/vmdk.py#L250), без opt-in |
| VMware FCD | `cinder.volume.drivers.vmware.fcd.VMwareVStorageObjectDriver` | Нет | [fcd.py:44](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/vmware/fcd.py#L44), наследует VMwareVcVmdkDriver; отдельной строки FCD в матрице нет, вывод по классу |
| Quobyte | `cinder.volume.drivers.quobyte.QuobyteDriver` | Нет | [quobyte.py:85](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/quobyte.py#L85), RemoteFS без opt-in |
| Pure iSCSI, FC | `PureISCSIDriver`, `PureFCDriver` | Да | [pure.py:229–232](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/pure.py#L229), общий PureBaseVolumeDriver разрешает AA; наследники строки 3601, 3852 |
| Pure NVMe-RoCE/TCP | `cinder.volume.drivers.pure.PureNVMEDriver` | Да | [pure.py:4059](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/pure.py#L4059), тот же разрешающий базовый класс |
| Lightbits NVMe/TCP | `cinder.volume.drivers.lightos.LightOSVolumeDriver` | Да | [lightos.py:380–392](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/lightos.py#L380), явно `True` |
| Huawei iSCSI/FC через встроенный XML-драйвер | `HuaweiISCSIDriver`, `HuaweiFCDriver` | Нет | [huawei_driver.py:38, 229](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/huawei/huawei_driver.py#L38) и [common.py:79–98](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/huawei/common.py#L79), HuaweiBaseDriver → VolumeDriver → BaseVD, opt-in отсутствует |

`RemoteFSSnapDriverDistributed` в названии класса означает логику распределённых snapshot-операций; слово `Distributed` не означает opt-in AA. В [remotefs.py](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/remotefs.py) цепочка наследования прослеживается по строкам 158, 771, 1993. `VolumeDriver` наследует `BaseVD` в `driver.py:2248–2249`.

### Huawei: почему нельзя переносить возможности массива на драйвер

1. В документации 2025.1 встроенного Huawei-драйвера описаны iSCSI/FC, XML, отдельные поколения/версии, multipath, replication и HyperMetro. Наличие этих возможностей не заявляет AA Cinder.
2. Конкретные классы `HuaweiISCSIDriver` и `HuaweiFCDriver` в проверенной ветке AA не разрешают. Даже наличие `coordination.synchronized` в отдельных методах не заменяет opt-in всего драйвера.
3. Dorado по NFS при `volume_driver = cinder.volume.drivers.nfs.NfsDriver` получает ограничения **generic NFS**, независимо от бренда NFS-сервера.
4. Если установлен отдельно поставляемый Huawei-драйвер, вывод об upstream-классе на него автоматически не переносится. Нужны точные модель, версия ПО массива, протокол, имя Python-класса и версия пакета/образа. Для него AA здесь **не установлено**.
5. При непустом `cluster` Cinder проверяет `self.driver.SUPPORTS_ACTIVE_ACTIVE` сразу после создания драйвера и бросает `VolumeDriverException`, если флаг ложный (`manager.py:319–323`).

### Multiattach для Glance: самостоятельная проверка

- Матрица `support-matrix.ini:853,878,884`: Huawei Dorado — `missing`, generic NFS — `missing`, RBD — `complete` в **[operation.multi-attach]**.
- NFS получает stats от RemoteFS и не объявляет `multiattach`: `nfs.py:528–532`, `remotefs.py:642–665`. Более того, `remotefs.py:1731–1732` работает с единственным attachment.
- Huawei: `huawei_driver.py:73–78,265–270` вызывает общие stats; `common.py:177–216` и [rest_client.py:1213–1235](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/drivers/huawei/rest_client.py#L1213) не публикуют capability multiattach. В [host_manager.py:443](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/scheduler/host_manager.py#L443) отсутствие capability трактуется как `False`.
- RBD публикует `'multiattach': True` в `rbd.py:773`. Специальный type всё равно необходим; наличие способности не превращает каждый volume в multiattach-volume. Не смешивать RBD multiattach и RBD replication: драйвер отдельно запрещает их совместное применение (`rbd.py:1067–1069`).
- Документация Glance объясняет: образ в cinder-store — Image-Volume, который при чтении присоединяется к Glance-хосту; параллельные запросы одного образа требуют multiattach type. Нельзя обещать такую работу generic NFS/Huawei только потому, что Glance API либо Cinder API имеет несколько экземпляров.

## Что действительно делает локальный форк

Все пути ниже относительно `kolla-ansible-pvs_1.0.0/`.

| Место | Наблюдение |
|---|---|
| `ansible/group_vars/all.yml:935–951,1076,1308–1319` | Cinder и generic NFS включены; Ceph/Huawei, Redis, etcd выключены; backend координации выбирается Redis → etcd → пусто; backup включён и его драйвер по умолчанию Ceph |
| `ansible/roles/cinder/defaults/main.yml:380–381` | `cinder_cluster_name: ""`, `cinder_cluster_skip_precheck: false` |
| `ansible/roles/cinder/defaults/main.yml:288` | `skip_cinder_backend_check: False` — другой независимый флаг |
| `ansible/roles/cinder/templates/cinder.conf.j2:24–31` | Для `cinder-volume` непустое имя попадает в `[DEFAULT] cluster`; список backend — `enabled_backends` |
| `ansible/roles/cinder/templates/cinder.conf.j2:147–255` | Указаны конкретные драйверы из таблицы; Huawei-секции нет |
| `ansible/roles/cinder/templates/cinder.conf.j2:275–285` | Redis — `backend_url = redis_connection_string`; etcd — `etcd3+http[s]://<internal-fqdn>:<etcd-port>?api_version=v3` с CA при наличии |
| `ansible/roles/cinder/tasks/precheck.yml:60–68` | Проверяет наличие координатора только для Ceph, если в `cinder-volume` больше одного узла; пропускается через `skip_cinder_backend_check` |
| `ansible/roles/cinder/tasks/precheck.yml:92–115` | Требует непустой cluster для >1 узла; требует пустой для одного узла; эти проверки выключает только `cinder_cluster_skip_precheck` |
| `ansible/roles/cinder/tasks/precheck.yml:29–46` | Проверка «хотя бы один известный backend» не включает Huawei; custom Huawei приходится учитывать отдельно |
| `ansible/roles/cinder/tasks/config.yml:12–16`, `external_huawei.yml:1–11`, `templates/cinder-volume.json.j2:9–16` | Huawei-флаги копируют перечисленные XML в `/etc/cinder/`; драйвер, backend-секция и `enabled_backends` автоматически не настраиваются |
| `ansible/roles/cinder/tasks/config.yml:90–103` | Override последовательно: `global.conf`, `cinder.conf`, `cinder/<service>.conf`, `cinder/<inventory_hostname>/cinder.conf` |

Пропуск любой Ansible-проверки **не меняет возможности драйвера** и не создаёт распределённые блокировки. Если проверка координатора написана только для Ceph, это не означает, что остальным AA-драйверам координатор не требуется.

Сообщение single-node precheck говорит «cluster configuration will not be applied», но сам шаблон `cinder.conf.j2:24` проверяет только имя и service. Поэтому нельзя превращать текст ошибки в утверждение о шаблоне: при bypass непустое `cluster` будет отрендерено и для единственного узла. Upstream Cinder допускает одноузловой cluster, но штатный Kolla precheck здесь этого не допускает.

### Топология и координатор

- `ansible/inventory/multinode:3–7`: три control-узла; `29–30`: один storage-узел в образце.
- `110–111,285–295`: Cinder API и scheduler идут на `control` через `cinder`; volume и backup — на `storage`. Чтобы получить AA volume, реально нужны как минимум два разных узла в итоговой группе `cinder-volume`, обычно через `[storage]`. Просто три control не дают три volume-сервиса.
- `62–63,180–181`: etcd и Redis назначены группе `control`.
- `ansible/group_vars/all.yml:1127–1128`: Redis URL использует Sentinel первого узла и sentinel_fallback остальных, не один обычный Redis endpoint.
- `ansible/roles/redis/defaults/main.yml:2–21`: на узлах Redis запускаются `redis` и `redis-sentinel`; `templates/redis-sentinel.conf.j2:8` задаёт quorum `2`. Для стандартной схемы отказ одного узла предполагает три Sentinel на независимых узлах.
- `ansible/roles/etcd/defaults/main.yml:11–17,50–55`: etcd перечисляет членов из группы `etcd`; endpoint Cinder проходит через внутренний балансировщик. Для обычной отказоустойчивой конфигурации etcd используют три члена.
- Координатор должен быть один логический кластер для всех членов Cinder cluster. Если включены оба сервиса, default выбирает **Redis**. Явно заданный `cinder_coordination_backend: "etcd"` полезен для однозначности примера.
- `cinder_cluster_name` — общее логическое имя **Cinder** cluster, не Ceph fsid и не `ceph_cluster`. Оно должно быть одинаковым у служб одного backend и отличаться от `host`/`backend_host`.
- Потребуются общий backend, одинаковые соответствующие backend-настройки, доступ к DB/RabbitMQ, координатору и хранилищу со всех volume-узлов. Кластеризация Cinder не делает саму СХД, сеть и эти сервисы отказоустойчивыми автоматически.

### Замечания о других шаблонах

Поддержку AA драйверами Pure и Lightbits можно указать, но нельзя представлять их как уже проверенный готовый deploy этого форка. В его шаблонах обнаружены дополнительные проблемы переменных:

- Pure NVMe использует `pure_nvme_tcp_backend`, `pure_roce_backend` (`cinder.conf.j2:231,240`), но их defaults в дереве нет.
- Lightbits defaults/precheck используют `lightos_api_address`, `lightos_jwt` (`defaults/main.yml:319–324`, `precheck.yml:85–90`), а шаблон читает `lightbits_target_ips`, `lightbits_api_port`, `lightbits_default_num_replicas`, `lightbits_skip_ssl_verify`, `lightbits_JWT` (`cinder.conf.j2:250–254`). Для последних в дереве не найдены defaults. Это отделяется от upstream AA-поддержки и требует отдельной настройки/исправления перед deploy.

## Готовый фрагмент для начинающего

### Active-active в Cinder: что это означает

Cinder управляет виртуальными дисками. `cinder-api` принимает запрос, `cinder-scheduler` выбирает backend, а `cinder-volume` выполняет операции с хранилищем. **Active-active `cinder-volume`** означает, что несколько работающих служб на разных узлах совместно обслуживают один backend. При потере одного узла оставшиеся могут принимать работу этого backend.

Это отдельный уровень отказоустойчивости:

| Возможность | Что она решает |
|---|---|
| Несколько Cinder API за балансировщиком | Доступность API |
| Active-active Cinder volume | Доступность службы управления одним backend |
| Два контроллера СХД, multipath | Доступность массива и путей до данных |
| Репликация, HyperMetro | Возможности копирования/доступности данных конкретной СХД |
| Multiattach | Одновременное подключение одного volume нескольким потребителям |

Одна строка таблицы не включает остальные. Например, два контроллера Dorado не разрешают автоматически запуск двух `cinder-volume` с одним backend. А active-active Cinder не включает multiattach для томов. [Правила Cinder HA](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/doc/source/contributor/high_availability.rst#L923).

### Какие backend подходят в OpenStack 2025.1

Для backend, предусмотренных шаблоном данного форка:

| Backend | Active-active `cinder-volume` |
|---|---|
| Ceph RBD | Поддерживается |
| Pure iSCSI, FC, NVMe-RoCE, NVMe-TCP | Поддерживается драйверами; параметры форка проверяются отдельно |
| Lightbits | Поддерживается драйвером; параметры форка проверяются отдельно |
| Generic NFS, LVM, Quobyte, VMware VMDK/FCD | Не поддерживается проверенными драйверами |
| Huawei Dorado через встроенные Huawei iSCSI/FC классы Cinder 2025.1 | Не поддерживается проверенными драйверами |
| Huawei с отдельно установленным vendor-драйвером | Требует проверки точной версии и совместимости |

Источник: [матрица 2025.1](https://docs.openstack.org/cinder/2025.1/reference/support-matrix.html) и закреплённые исходники классов выше. Для generic NFS общий экспорт доступен нескольким машинам, но этого недостаточно для AA Cinder. Для Dorado сначала определяют модель, прошивку, протокол и установленный драйвер. Если Dorado используется как NFS-сервер с `NfsDriver`, действуют ограничения generic NFS.

### Пример настроек: Cinder active-active с внешним Ceph

Ниже пример для нового проекта, где Cinder хранит volumes только в Ceph. Он проверен по шаблонам форка и возможностям upstream-драйвера; это не результат испытания живого стенда.

В существующем inventory два разных узла должны входить в `[storage]` (либо непосредственно в `cinder-volume`), а три control-узла — в группу etcd через штатную связь `[etcd:children] control`:

```ini
[storage]
storage01
storage02
```

Фрагмент `/etc/kolla/globals.yml`:

```yaml
enable_cinder: "yes"
cinder_backend_ceph: "yes"

# В этом форке generic NFS включён по умолчанию; для примера выключаем.
enable_cinder_backend_nfs: "no"
enable_cinder_backend_lvm: "no"
cinder_backend_huawei: "no"

# Одинаковое имя для обеих cinder-volume служб.
cinder_cluster_name: "cinder-ceph-aa"
cinder_cluster_skip_precheck: false
skip_cinder_backend_check: false

# Координатор распределённых блокировок.
enable_etcd: "yes"
cinder_coordination_backend: "etcd"

ceph_cluster: "ceph"
ceph_cinder_user: "cinder"
ceph_cinder_pool_name: "volumes"

# Backup настраивается отдельно; в минимальном примере выключен.
enable_cinder_backup: "no"
```

Все остальные backend-флаги в этом примере должны оставаться выключенными. При общем `cluster` нельзя оставить неподдерживаемый NFS backend в том же `cinder-volume`. Имя Cinder cluster не должно совпадать с именем хоста либо `backend_host`.

Для внешнего Ceph необходимы подготовленные pool/cephx права и файлы:

```text
/etc/kolla/config/cinder/ceph.conf
/etc/kolla/config/cinder/cinder-volume/ceph.client.cinder.keyring
```

Для подключения этих volumes к ВМ Nova также нужен доступ к Ceph и штатно используемые файлы:

```text
/etc/kolla/config/nova/ceph.conf
/etc/kolla/config/nova/ceph.client.cinder.keyring
```

Это не требует переводить ephemeral-диски Nova на Ceph. Если нужен `cinder-backup`, отдельно включают его и готовят backup pool, пользователя и соответствующие keyring-файлы. [Подготовка внешнего Ceph](https://docs.openstack.org/kolla-ansible/2025.1/reference/storage/external-ceph-guide.html#cinder).

Ожидаемые ключи в сгенерированном `cinder.conf` volume-служб:

```ini
[DEFAULT]
cluster = cinder-ceph-aa
enabled_backends = rbd-1

[rbd-1]
volume_driver = cinder.volume.drivers.rbd.RBDDriver
volume_backend_name = rbd-1
rbd_pool = volumes
rbd_ceph_conf = /etc/ceph/ceph.conf
rbd_user = cinder

[coordination]
# Пример для internal_protocol=http и etcd_client_port=2379.
backend_url = etcd3+http://<внутреннее-имя-Kolla>:2379?api_version=v3
```

Альтернативный штатный координатор — Redis/Sentinel: `enable_redis: "yes"` вместе с `cinder_coordination_backend: "redis"`. Тогда Kolla формирует `backend_url` из своей Sentinel-строки. Для HA нужен отказоустойчивый координатор; один экземпляр Redis/etcd оставляет единую точку отказа.

### Что делать с NFS или Dorado

Для неподдерживающего AA драйвера оставляют один активный `cinder-volume` на backend. Если требуется переключение на резервный узел, проектируют active-passive: общий backend, одинаковые настройки, `backend_host` и внешний менеджер ресурсов, который гарантирует единственного активного владельца. Форк не создаёт такую схему одной настройкой `cinder_cluster_name`. API и scheduler при этом могут работать на нескольких узлах.

`cinder_cluster_skip_precheck: true` лишь выключает проверку схемы inventory. `skip_cinder_backend_check: true` отключает другую часть Ansible prechecks. Ни один из этих флагов не добавляет AA в драйвер: Cinder всё равно проверяет его поддержку при старте. [Проверка Cinder при запуске](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/manager.py#L319).

### Если Glance хранит образы в Cinder

Glance cinder-store хранит один образ в одном Image-Volume. Для нескольких одновременных чтений такого образа документация Glance требует поддерживаемый **multiattach** backend и специально настроенный volume type. Это проверяют отдельно от AA. В Cinder 2025.1 generic NFS и встроенный Huawei-драйвер не заявляют multiattach; для них нельзя обещать параллельное чтение образа несколькими подключениями. [Glance: multiattach type](https://docs.openstack.org/glance/2025.1/configuration/configuring.html#configuring-multi-attach-volume-type).

### Что проверить перед утверждением «HA работает»

Сначала проверяют фактическую версию образа/драйвера, итоговые группы inventory, одинаковый cluster и backend на узлах, непустой coordinator URL, видимость всех служб и состояние DB/RabbitMQ/координатора/хранилища. Наличие конфигурации доказывает подготовку; работу после отказа доказывает отдельное согласованное испытание с операциями создания и подключения volume. Здесь такое испытание не проводилось.

## Дополнительная проверка раздела 6 основного руководства

Проверен раздел 6 `GLANCE_CINDER_SHARED_STORAGE_AND_HA.md` без редактирования. Критических ошибок в показанных service credentials, разграничении AA/multiattach и границах транспортной подготовки FC/NFS не обнаружено.

Нужное уточнение последовательности: свойство `multiattach=<is> True` следует задавать **до создания Image-Volumes**. Изменение extra specs типа не включает автоматически multiattach у ранее загруженных образов: Cinder вычисляет и сохраняет флаг при создании volume ([create_volume.py:490–495,595](https://github.com/openstack/cinder/blob/ef0d50cb18d0ceb5d70d500c9a032b0eb66e749b/cinder/volume/flows/api/create_volume.py#L490)). Glance проверяет именно `volume.multiattach`, а не свежие свойства типа ([glance_store store.py:738](https://github.com/openstack/glance_store/blob/5db60a4a979662d2a09d937cf460f8d72f8403dd/glance_store/_drivers/cinder/store.py#L738)). Для существующих Image-Volumes необходима отдельная проверка/процедура переноса.

Проверенный SHA `glance_store stable/2025.1`: `5db60a4a979662d2a09d937cf460f8d72f8403dd`; локальный исходник `/tmp/cinder-aa-glance-store.py`. Это не установленная версия контейнера. Дополнительный Cinder-источник: `/tmp/cinder-aa-create-volume.py` с тем же Cinder SHA, что указан выше.
