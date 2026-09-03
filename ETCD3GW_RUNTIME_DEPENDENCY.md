# Зависимость `etcd3gw` в runtime-образах PowerOps

## Краткий вывод

Python-пакет `etcd3gw` должен быть установлен в runtime-окружении каждого
патченного сервиса, который загружает код PowerOps:

- `masakari_engine`;
- `mistral_api`;
- `mistral_engine`;
- `mistral_executor`.

Устанавливать пакет нужно при сборке соответствующих образов в Python venv
Kolla. Ручная установка в работающий контейнер не является исправлением:
изменение исчезнет после пересоздания контейнера.

## Наблюдавшаяся ошибка

Masakari Engine завершал загрузку notification driver с ошибкой:

```text
masakari.engine.driver: Failed to load notification driver 'taskflow_driver'
ModuleNotFoundError: No module named 'etcd3gw'
```

Цепочка импорта:

```text
masakari taskflow_driver
  -> masakari.engine.drivers.taskflow.host_failure
  -> masakari.powerops.coordination
  -> tooz.drivers.etcd3gw
  -> import etcd3gw
```

Слово `taskflow_driver` здесь относится к TaskFlow-драйверу Masakari. Эта
конкретная ошибка возникает не в задаче Mistral: Engine Masakari не может
загрузить собственный recovery driver.

Ошибка возникает до соединения с etcd. Она подтверждает отсутствие
Python-модуля в интерпретаторе контейнера, но сама по себе ничего не говорит о
доступности или состоянии сервиса etcd.

## Где пакет обязателен

| Контейнер | Нужен `etcd3gw` | Причина |
|---|---:|---|
| `masakari_engine` | да | Выполняет PowerOps fencing и использует общие блокировки через tooz. |
| `mistral_api` | да | Загружает каталог патченных `powerops.*` actions. |
| `mistral_engine` | да | Оркестрирует PowerOps workflow и coordination. |
| `mistral_executor` | да | Исполняет PowerOps actions. |
| `masakari_api` | нет | Остаётся vanilla и не исполняет добавленный PowerOps-код. |
| Masakari monitors | нет | Не исполняют PowerOps coordination; hostmonitor может отдельно использовать Consul. |
| `mistral_event_engine` | нет | Остаётся vanilla и не исполняет PowerOps actions. |

Если три сервиса Mistral используют один и тот же патченный образ, зависимость
достаточно один раз включить в этот образ. Если для API, Engine и Executor
собираются разные образы, пакет должен присутствовать в каждом из них.

## Проверка работающих контейнеров

Проверка только читает состав Python-окружения и не перезапускает сервисы:

```bash
for container in masakari_engine mistral_api mistral_engine mistral_executor; do
  docker exec "$container" /var/lib/kolla/venv/bin/python -c \
    "import etcd3gw; print('$container: etcd3gw OK')" \
    || printf '%s\n' "$container: etcd3gw MISSING"
done
```

Для проблемного Masakari Engine можно вывести пути всех связанных модулей:

```bash
docker exec masakari_engine /var/lib/kolla/venv/bin/python -c \
  "import sys, importlib.util as u; print('python:', sys.executable); print('masakari:', u.find_spec('masakari')); print('tooz:', u.find_spec('tooz')); print('etcd3gw:', u.find_spec('etcd3gw'))"
```

Значение `etcd3gw: None` подтверждает, что модуль отсутствует в эффективном
Python-окружении контейнера.

Используемый immutable image tag или digest проверяется отдельно:

```bash
for container in masakari_engine mistral_api mistral_engine mistral_executor; do
  docker inspect -f '{{.Name}} -> {{.Config.Image}}' "$container"
done
```

## Правильное исправление

В исходных патчах Masakari и Mistral зависимость уже объявлена:

```text
etcd3gw!=0.2.2,!=0.2.3,!=0.2.6
```

Поэтому штатная установка финального Python-проекта вместе с зависимостями
должна установить её автоматически. Если сборка использует `pip install
--no-deps` либо копирует wheel или исходники поверх готового образа без
разрешения зависимостей, runtime-зависимость необходимо добавить в рецепт
сборки явно.

Команда в build stage соответствующего образа имеет следующий смысл:

```bash
/var/lib/kolla/venv/bin/pip install \
  'etcd3gw!=0.2.2,!=0.2.3,!=0.2.6'
```

Конкретная команда сборки должна сохранять constraints и остальные правила
используемого Kolla image pipeline. После изменения требуется:

1. пересобрать затронутые образы;
2. присвоить им новые immutable tags или digests;
3. проверить импорт `etcd3gw` непосредственно внутри каждого образа;
4. только затем выполнить согласованный deploy/reconfigure контейнеров;
5. повторить runtime-проверку во всех четырёх контейнерах.

Не используйте `docker exec ... pip install` как постоянное исправление. Такая
установка изменяет только текущий экземпляр контейнера, не исправляет образ и
не воспроизводится при следующем развертывании.

## Почему существующая проверка пропустила ошибку

Текущий acceptance check Masakari подтверждает наличие entry point
`ironic_fence` через `importlib.metadata`. Наличие metadata доказывает, что
патченный пакет попал в образ, но не доказывает импортируемость всех его
runtime-зависимостей.

Для полного read-only acceptance check образа дополнительно нужно выполнить:

```bash
/var/lib/kolla/venv/bin/python -c \
  "import etcd3gw; import openstack; from masakari.powerops import coordination"
```

Для каждого патченного образа Mistral:

```bash
/var/lib/kolla/venv/bin/python -c \
  "import etcd3gw; import openstack; from mistral.actions.powerops import coordination"
```

Эти команды проверяют состав образа и цепочку импортов. Они не являются
доказательством доступности OpenStack API, etcd или BMC: сетевые endpoints и
реальное выполнение PowerOps проверяются отдельно после развертывания.

## Etcd и Consul

В текущей реализации PowerOps coordination допускаются только схемы
`etcd3+http` и `etcd3+https`, а работа с ними выполняется драйвером tooz
`etcd3gw`. Поэтому Consul не заменяет etcd для общих блокировок PowerOps.

Consul можно продолжать использовать отдельно для обнаружения отказов через
`masakari-hostmonitor`. Это независимый контур и он не устраняет отсутствие
Python-пакета `etcd3gw` в патченных runtime-образах.
