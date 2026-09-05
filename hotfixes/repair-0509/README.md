# Ремонт PowerOps поверх архивов 0509

Дата: 2026-09-05. Два самостоятельных git-патча. Старые пять hotfixes повторно
накладывать не нужно: их runtime-изменения уже находятся в этих архивах.

## Коротко о kolla-pvs

Проверен предоставленный `kolla-pvs_1.0.0.zip`, а не прежний локальный рецепт.

- `docker/mistral/mistral-base/Dockerfile.j2` устанавливает `mistral-lib`,
  openstacksdk, oslo.*, tooz и etcd3gw из RPM. Отдельного источника для
  патченного `mistral-lib` в `kolla/common/sources.py` нет.
- Исходники Mistral приходят через `mistral-base-archive` и устанавливаются
  отдельно. `docker/macros.j2:install_pip` использует `--no-deps --no-index`:
  изменение requirements.txt само по себе не обновит эти библиотеки.
- Этот ремонт работает со штатным `mistral-lib`. Роли берутся из проверенного
  Mistral request context, который настоящий executor передаёт в поток action.
  Формат сериализации SecurityContext библиотеки не расширяется.
- Эти git-патчи нужно накладывать **на исходники до установки Python-пакета**.
  `kolla_patch_sources()` расположен уже после pip, а `kolla_patch.sh` применяет
  патчи из `/` с `patch -p0`. Это НЕ способ применения приложенного source git
  patch с путями `a/mistral/...` и `b/mistral/...`.
- Отдельное предупреждение о рецепте: последняя строка `chmod` перед
  `kolla_patch_sources()` заканчивается обратным слешем. При включённом
  `patches_path` следующая инструкция `COPY` может продолжить предыдущий RUN.
  Перед использованием этого позднего механизма нужно исправить/проверить
  сгенерированный Dockerfile. Рецепт этим комплектом не изменён; рекомендуемый
  ниже путь — Git-источник с уже применённым патчем, без этого механизма.

Точные версии RPM и содержимое готовых образов по одному рецепту определить
нельзя. Их проверяет `verify_images.py` на машине сборки до переноса.

## Зафиксированная база

| Архив | SHA256 |
|---|---|
| `mistral-integration-powerops-mistral-2025.1_0509.zip` | `2261f38005551d4c6f24b904a6a507009d731dbfe9e94aae95265c4bb714d39d` |
| `kolla-ansible-enroll-ironic-patch-3_0509.zip` | `af92a0e4e3dde10bfc1e3cc461007c9d87c720b241ac72a71174181865bbdae4` |
| `kolla-pvs_1.0.0.zip` | `1c5c89977e9ec60079534bc82b03a132a6d790070ac4a1707275e75a396b2867` |

## Состав

1. `0001-mistral-0509.patch` — отсутствующий helper авторизации; проверенный
   request context вместо неподдерживаемого расширения mistral-lib; отказ
   target-cloud контексту; явные host/binary для старой ветки Nova service API;
   автономная проверка образа; актуальные fixtures и дополнительные тесты.
2. `0002-kolla-ansible-0509.patch` — исправленный перенос строки в конфиге;
   фактическая загрузка пяти actions и проверка авторизации на каждой реплике
   API/engine/executor до populate; ожидание последней партии `kolla_serial`;
   отказ при частично проваленном deploy; bounded HTTP и безопасная диагностика.

Политика: `admin` разрешён вне allowlists; `powerops_operator` требует точного
совпадения обеих allowlists; hard-off только для admin. Недостающие/невалидные
роли и `is_target=True` отклоняются. Роль из workflow input не используется.

Собственные PowerOps exceptions уже имеют непустые сообщения в 0509 — это
сохранено и проверено. Произвольные сторонние исключения могут иметь пустой
`str(exc)`; универсального исправления всех исключений здесь нет.

## Как применить и собрать

Используйте чистые Git checkout соответствующих исходников, совпадающих с
базой 0509. Не применяйте патчи вслепую к другой версии. Сначала `git status
--short`; при посторонних изменениях остановитесь и сохраните их отдельно.

В репозитории Mistral:

```bash
git apply --check /PATH/repair-0509/0001-mistral-0509.patch
git am /PATH/repair-0509/0001-mistral-0509.patch
git rev-parse HEAD
```

В репозитории Kolla-Ansible:

```bash
git apply --check /PATH/repair-0509/0002-kolla-ansible-0509.patch
git am /PATH/repair-0509/0002-kolla-ansible-0509.patch
```

Для простой распаковки ZIP без Git вместо `git am` используется `git apply`.
Но для сборки Mistral через PBR предпочтителен полный Git clone с историей:
простой ZIP без `.git`/PKG-INFO не содержит данных о версии пакета.

В конфигурации сборки Kolla укажите именно свой commit с новым Mistral-патчем:

```ini
[mistral-base]
type = git
location = YOUR_MISTRAL_GIT_URL
reference = YOUR_PATCHED_COMMIT_SHA
```

В этом рецепте Git-источник клонируется и упаковывается вместе с `.git`;
`reference` должен быть доступен сборщику. Не используйте старую ветку по
умолчанию `${pvs_branch}`, если новый commit туда не включён. Ветка
`codex/powerops-0509-repair` в репозитории `lebtmalorny-rgb/mimaric` содержит
комплект патчей и проверок, а не полный Git-источник Mistral для сборщика.
Применение патча и публикация полученного commit в вашем репозитории Mistral,
а затем сборка образов остаются отдельными шагами оператора.

Пересоберите общий `mistral-base` и три его образа: `mistral-api`,
`mistral-engine`, `mistral-executor`. Используйте новый уникальный tag и
проверьте SHA исходников в build log. `mistral-lib`, Masakari и Ironic этим
комплектом не патчатся. Остальные параметры SberLinux/registry сохраняются.

## Проверка готовых образов — до переноса

В каталоге комплекта, на машине с уже собранными локальными образами
(заменить все три ссылки на реальные):

```bash
python3 verify_images.py --engine podman \
  --api-image 'REGISTRY/pvs/mistral-api:NEW_TAG' \
  --engine-image 'REGISTRY/pvs/mistral-engine:NEW_TAG' \
  --executor-image 'REGISTRY/pvs/mistral-executor:NEW_TAG'
```

Для Docker заменить `--engine podman` на `--engine docker`.
Скрипт не скачивает образы, закрепляет каждый запуск за локальным image ID,
отключает сеть, не монтирует конфиги и не запускает службы. Проверяет SHA256
13 runtime-файлов, `pip check`, пять entry points и путь авторизации через
executor. Временные контейнеры проверки удаляются, включая случай тайм-аута.

Успех всех трёх — последняя строка `PASS: all three local image contracts
verified; live cloud untested`. Любое несовпадение файла/зависимостей/импорта
останавливает проверку. Не обходите ошибку заменой ожидаемых хешей.

После успешной проверки в globals выбираются новые
`powerops_mistral_api_tag`, `powerops_mistral_engine_tag`,
`powerops_mistral_executor_tag`; поля `powerops_mistral_*_image` должны содержать
правильные repository без tag. Одного `mistral_tag` при enable_powerops мало.
Reconfigure автоматически нами не выполнялся.

## Что проверено локально

- 147 PowerOps-тестов, включая 11 тестов через настоящие SDK-прокси с полностью
  перехваченным HTTP. Включены off/on без ВМ, stop/off/on/start по manifest,
  live migration/off/on, reboot с ВМ, запрещённые переходы, ошибки и fail-safe.
- 43 теста Kolla: конфигурация, шаблоны enabled/disabled по сервисам, TLS/CA,
  registration, секреты, охват реплик и serial gate.
- 3 дополнительных теста общего context/local executor.
- Независимый reviewer прогнал 8 сценариев настоящего локального Ansible:
  serial=0/1, отказ третьей реплики, --limit одного host с проверкой остальных,
  отказ последнего выбранного host. До успешной проверки всех девяти
  host/container пар populate не выполняется.
- Патчи применены к свежей распаковке исходных ZIP; 147 и 43 теста повторены
  в отдельном чистом Python 3.11 venv. Mistral установлен обычным wheel, не
  editable; из каталога вне исходников проверены все 13 файлов, импорты,
  авторизация и `pip check`.
- Новые Mistral Python-файлы прошли Hacking/flake8; `git diff --check` чистый.

`test-environment.lock` фиксирует локальное проверочное окружение, а не
версии для замены RPM в образе. В частности проверены штатный mistral-lib
3.5.0 и openstacksdk 4.20.0. Для ZIP без Git в локальной проверке использована
синтетическая `PBR_VERSION=0.0.0`; не переносите её в production recipe.

Для повторения после создания venv и установки `test-environment.lock`:

```bash
# Установка обеих исходных распаковок с патчами в тестовый venv:
PBR_VERSION=0.0.0 python -m pip install --no-deps --no-build-isolation /PATH/MISTRAL /PATH/KOLLA_ANSIBLE
# Из корня Mistral:
python -m unittest discover -s mistral/tests/unit/actions/powerops -t .
# Из корня Kolla-Ansible:
python -m unittest discover -s kolla_ansible/tests/unit -t . -p 'test_powerops*.py'
# Из каталога комплекта (только локальные маркеры, никаких cloud команд):
python verify_ansible_preflight.py /PATH/KOLLA_ANSIBLE
```

SDK HTTP-проверка покрывает современное обновление сервиса по UUID и старый
вызов с host/binary; граница API 2.53 описана в
[Nova Compute API](https://docs.openstack.org/api-ref/compute/#update-compute-service).

## Что НЕ подтверждено

Это не end-to-end приёмка облака и не сборка SberLinux-образов. Готовые образы
пользователя не предоставлены: payload image-check проверен на установленном
локальном wheel, но три конкретных образа ещё должен проверить сборщик.

Нужны runtime-проверки доступности каждого Mistral API, Keystone/RBAC
служебного пользователя, видимости Nova/Ironic/Masakari, etcd, BMC, TLS,
реальных переходов питания и migration. Причина тайм-аутов `.151` не
установлена; пропущенный импорт не доказывает причину всех тайм-аутов.

YAML workflow не изменены: остаются четыре workflow 0509. Возврат после
аварии ручной; `power_on_and_return` сохраняет pause/operator gate.
Boolean `stale_domains_checked=True` остаётся утверждением оператора, а не
серверным доказательством trusted resume. Новая автоматизация planned return
и полная engine pause/resume приёмка в этот ремонт не включались.

Во время --limit проверка всё равно посещает все inventory API/engine/executor
реплики. Старый или недоступный контейнер вне --limit блокирует reconciliation
намеренно. После 504 не повторяйте опасный workflow, пока не выяснены наличие
execution и его состояние.
