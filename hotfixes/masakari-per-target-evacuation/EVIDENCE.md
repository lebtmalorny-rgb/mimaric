# Доказательства локальной поставки

Дата: 2026-09-13. Исходная ветка комплекта:
`feature/masakari-per-target-evacuation`, база поставки
`1d3bd3255b3678347414578fd89dbd6f05430b19`, опубликованный предшественник
`c866d56fbf382afa4612c07039c34fbb5032aef5`.

## Замороженные исходники и воспроизводимый wheel

Core: `7aa25702654a3a7e545123c59a04009f85b30ac0`.
Nova: `69730e9fc77f1e57ac1ba884bc2dd0c567e01a3a`.
Masakari: `4e93865141f6113570ce80ac3e33f5bae836e3a6`.
Kolla: `b6b66dfe883b98b9dc6b5dc702caa66eea9a7cdb` (три новых commits).
Полные BASE..HEAD экспортированы `git format-patch`; исходные worktrees
не изменялись. Точные SHA256 всех артефактов находятся в [manifest](https://github.com/lebtmalorny-rgb/mimaric/blob/71b0123f390bfeaab4dc4ca2dffaa6fab32a6cdf/hotfixes/masakari-per-target-evacuation/manifest.json).

Wheel `powerops_evacuation_guard-0.1.0-py3-none-any.whl`:
`b38359c6c83e868f0fa0e63901a4c93043c13183735e81600996541a71b3544f`.
Два независимых `git archive` core, Python 3.11.15, build 1.6.1,
setuptools 80.9.0, `SOURCE_DATE_EPOCH=1789295229`, `build --wheel --no-isolation`
дали побайтово одинаковые wheel. Сборка происходила в `/tmp`, не в frozen source.
Пример воспроизведения из корня комплекта:

```sh
EVAC_BUILD_DIR=$(mktemp -d /tmp/evac-build.XXXXXX)
git archive 7aa25702654a3a7e545123c59a04009f85b30ac0 packages/powerops-evacuation-guard > "$EVAC_BUILD_DIR/source.tar"
tar -xf "$EVAC_BUILD_DIR/source.tar" -C "$EVAC_BUILD_DIR"
SOURCE_DATE_EPOCH=1789295229 python3.11 -m build --wheel --no-isolation --outdir "$EVAC_BUILD_DIR/dist" "$EVAC_BUILD_DIR/packages/powerops-evacuation-guard"
```

В отдельный `/tmp/evac-delivery-wheel-venv` установлены зависимости из cache,
затем wheel командой `uv pip install --offline --no-deps --python ...`.
Из `/tmp`, с `python -I`, импорт разрешился в
`/tmp/evac-delivery-wheel-venv/lib/python3.11/site-packages/powerops_evacuation_guard/__init__.py`;
metadata version `0.1.0`, CLI `--help` exit 0. Это отдельный venv без editable
источников. Его разрешённые зависимости включают requests 2.32.3,
oslo.config 9.7.2 и setuptools 84.0.0; последний не использован для сборки
wheel и не меняет constraints Nova/Masakari.

## RED, replay и неизменность предшественника

Первый delivery RED: 3 ожидаемых assertion failures из-за отсутствующих
manifest/wheel/replay, immutable Watcher check PASS, один opt-in replay skip.
Первый composed harness RED: отсутствовал service adapter (1 failure,
один integration skip). После экспорта delivery suite: 5 PASS, включая все
три реальные replay на чистых archive-базах, symlink и compile изменённых `.py`.

| Компонент | Базовое дерево | Доказанное итоговое дерево |
|---|---|---|
| Nova | `efaa1afe1685ffae2032c46ea1d03b3723c73e6f` | `85d45af66afefeb0317eb42d1d235d28dc61dc90` |
| Masakari | `f7eb2f799ba9db0ac44b01ca949c1070bd4b6f96` | `568c7daa3e71c85beb22be44252d90c310a98acf` |
| Kolla | `d68e9dcf20ca05e2bea7fb07ab93e80aab40e2a2` | `f888c531b3d80f1ce2e6b2098933e7a098fb99aa` |

Kolla `etc/kolla/passwords.yml` отсутствует в чистой replay-базе. Настоящий
приватный файл не читался, не хешировался и не индексировался. Начальный Git
add использует literal exclusion; synthetic regression доказывает отсутствие
исключённого blob в object DB. Четыре обязательные symlink сохранены.
Wrong-base и no-overwrite отказывают без изменения входа/существующего output;
прежний regression последовательного применения зависимых patches проходит.
Старые Watcher package/source/patch/docs проверены побайтово относительно
базы комплекта. Оба manifest проверяются отдельно; никаких `../` artifact paths
или копий прежней поставки не добавлено. SHA256SUMS покрывает точный набор
patches, wheels, manifest и диагностических YAML без устаревшего фиксированного
счётчика файлов.

Финальная коррекция default endpoint добавляет только production-фильтр
`put_address_in_context('url')` для новой evacuation-настройки. RED доказал,
что оба IPv6 default под HTTP/HTTPS рендерились без скобок и отклонялись
настоящим общим precheck; DNS и IPv4 проходили. После исправления все шесть
вариантов рендерятся точно и проходят precheck. Обновлённый delivery содержит
ровно шесть новых артефактов: wheel, патчи Nova/Masakari и три Kolla-патча.
Точный replay всех трёх компонентов — 5 PASS; offline suite — 22 теста,
19 PASS/3 opt-in SKIP; оба manifest verifier и все 17 записей SHA256SUMS
прошли. Проверка неизменности прежнего Watcher payload осталась PASS.

## Composed proof и границы исполнения

Опциональный тест запускает фактические `masakari.powerops.evacuation.Attempt`
и `nova.compute.powerops_evacuation.guard_rebuild/_execute` в разных процессах
и Python-окружениях, с настоящим локальным etcd 3.5.21. Nova DB object lookups
и внешний rebuild/virt заменены синтетическими записями и барьерами; production
helper, Guard, clocks, CAS, claims, correlation и proof validation не заменены.
MacOS import shim для отсутствующих Linux capabilities разрешает только импорт:
любой вызов отсутствующего syscall завершается явной ошибкой.

Root выполнил приведённый ниже socket-run вне sandbox: **2 PASS за 21.609 s**,
exit 0. Подтверждены correlation намерения с настоящим receiving helper,
ожидание второй ВМ на той же цели, одновременный RUNNING на трёх разных целях,
WAITING четвёртой цели и её допуск после освобождения общего слота. Проверены
Nova COOLDOWN и окончательный Masakari proof, отказ дубликату без исполнения,
сохранение UNKNOWN и блокировка той же цели до durable admission timeout,
а также сохранение RUNNING/revision и отказ повторному исполнителю после
принудительного завершения процесса. Каждый запуск очищает только свой
namespace; реальный etcd не перезапускался.

Два первых root-прогона обнаружили ошибки bootstrap тестового adapter:
неинициализированный oslo CONF для Masakari policy и отсутствие
`nova.objects.register_all()`. Исправлены только штатная инициализация adapter
и диагностика теста; frozen production sources не изменялись. Финальный
offline комплект: 19 PASS/3 явных opt-in SKIP (22 collected); отдельные replay
и composed прогоны выше закрывают новые opt-in проверки. Прежний неизменённый
Watcher crossprocess не повторялся.

Команды из корня комплекта; endpoint принадлежит заранее запущенному
одноразовому локальному серверу, переменные Python указывают на независимые
окружения с соответствующими frozen Nova и Masakari sources:

```sh
PYTHONDONTWRITEBYTECODE=1 /tmp/watcher-hold-venv/bin/python -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 EVAC_CLEAN_REPLAY_BASES=/path/to/clean-replay-bases.json /tmp/masakari-evac-venv/bin/python -m unittest discover -s tests -p test_masakari_per_target_evacuation_delivery.py -v
PYTHONDONTWRITEBYTECODE=1 EVAC_TEST_ENDPOINT=http://127.0.0.1:33379 EVAC_NOVA_PYTHON=/tmp/masakari-evac-venv/bin/python EVAC_MASAKARI_PYTHON=/tmp/watcher-hold-venv/bin/python /tmp/masakari-evac-venv/bin/python -m unittest discover -s tests -p test_masakari_per_target_evacuation_crossprocess.py -v
python3 tools/watcher_automation_hold_delivery.py verify
python3 tools/watcher_automation_hold_delivery.py --manifest hotfixes/masakari-per-target-evacuation/manifest.json verify
shasum -a 256 -c SHA256SUMS
git diff --check
```

`clean-replay-bases.json` содержит для `nova`, `masakari`, `kolla` объект
`{"path": "/absolute/path/to/clean/base"}`; используйте деревья из таблицы выше.
Тест создаёт только собственный UUID namespace и очищает только его. Он
не запускает/перезапускает etcd и не обращается к облаку.

## Уже принятые компонентные доказательства

Core после parser fix: offline 88 PASS/3 real-only SKIP; actual etcd
51 PASS/40 offline-only SKIP. Ранее выполнен настоящий stop/start etcd с той
же data directory: RUNNING revision 233 сохранилась, target exclusion и отказ
дубликату сохранились. Это root evidence Task1, сервер здесь не перезапускался.
Nova: 35 новых +73 существующих =108 PASS с реальным manager до внешнего virt
boundary. Masakari: 20 новых +78 legacy +42 root native =140 distinct PASS,
включая 24 ВМ, ограниченный process pool и настоящий SDK с fake HTTP transport.
Kolla: 55 PowerOps tests PASS; затем два scoped IPv6 correction запуска по
30 PASS. Финальный запуск рендерит DNS, IPv4 и IPv6 defaults под HTTP/HTTPS
через production `put_address_in_context('url')` и передаёт каждый результат
в настоящий общий Ansible precheck. Эти неизменённые тяжёлые suites в delivery
не повторялись.

Существующее предупреждение eventlet early-import в Nova runner и три baseline
W503 в Kolla раскрыты ранее; это не чистый Linux runtime/lint результат.
Источники семантики: Nova `api/openstack/compute/evacuate.py:110` (2.95 STOPPED),
`compute/manager.py:4192` (rebuild/spawn прежде stop); Masakari сохраняет 2.53.
Полный текст решений и издержек: [DECISIONS](DECISIONS.md).

Никаких образов, deploy, SSH/BMC, cloud evacuation или нагрузочных испытаний.
Глобальный предел 3 — консервативный default, не capacity recommendation.
Готовность к эксплуатации и 1000-host scale не доказаны. Финальная публикация
ветки и remote SHA принадлежат отдельному этапу root после review.
