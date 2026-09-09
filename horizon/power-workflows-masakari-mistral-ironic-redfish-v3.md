# Управление питанием compute-хостов через Masakari, Mistral, Ironic и Redfish

## Краткое заключение

Задача — безопасно управлять питанием физических compute-хостов OpenStack при плановых работах и авариях, не допуская потери ВМ, повторного запуска одной ВМ на двух хостах и неконтролируемого выключения узлов.

Для этого предлагается разделить ответственность:

- **Mistral** оркестрирует плановое выключение, перезагрузку и возврат хоста;
- **Masakari** управляет аварийным recovery и evacuation;
- **Ironic** хранит Redfish-параметры хостов и выполняет команды питания;
- **Redfish/BMC** непосредственно включает, выключает и перезагружает сервер;
- **Horizon** предоставляет оператору единый интерфейс запуска и контроля операций.

Ключевой принцип аварийного workflow: evacuation разрешается только после подтверждённого физического выключения отказавшего хоста.

## Рекомендуемая архитектура

**Плановые операции:**

```text
Horizon
  → Mistral
    → Masakari: maintenance
    → Nova: disable / drain
    → Ironic
    → Redfish
    → проверки
    → Nova / Masakari: возврат хоста
```

**Аварийные операции:**

```text
Masakari Monitor
  → Masakari recovery workflow
    → custom ironic_fence_task
    → Ironic
    → Redfish: hard power off
    → подтверждение fencing
    → evacuation
```

Mistral рекомендуется использовать для плановых многошаговых операций.  
В аварийном пути Masakari должен обращаться к Ironic напрямую через кастомную TaskFlow-задачу, без дополнительной зависимости от Mistral.

## Роли компонентов

| Компонент | Назначение |
|---|---|
| Horizon | Пользовательский интерфейс и запуск операций |
| Mistral | Оркестрация планового выключения, перезагрузки и возврата хоста |
| Masakari | Обнаружение отказа и аварийное восстановление |
| Nova | Отключение хоста от scheduler, migration и evacuation ВМ |
| Ironic | Хранение BMC/Redfish-параметров и выполнение power operations |
| Redfish | Фактическое управление питанием через BMC |

## Общие шаги для всех workflow

1. Определить хост по единому имени:  
   `Nova hostname = Masakari host.name = Ironic Node.name`.
2. Установить блокировку операции, чтобы исключить параллельные power actions.
3. Отключить `nova-compute` от размещения новых ВМ.
4. Обработать ВМ:
   - планово — migration или штатная остановка;
   - аварийно — сначала fencing, затем evacuation.
5. Выполнить power operation через Ironic.
6. Дождаться завершения операции и проверить:
   - `power_state`;
   - `target_power_state`;
   - `last_error`.
7. Проверить состояние ОС и сервисов после включения.
8. Зафиксировать результат, снять блокировку и обновить состояния Nova/Masakari.

## Матрица workflow

| Workflow | Основной оркестратор | Операция питания | Работа с ВМ | Итоговое состояние |
|---|---|---|---|---|
| Плановое выключение | Mistral | `soft power off` | Migration/остановка до выключения | Хост выключен, Nova disabled, Masakari maintenance |
| Плановая перезагрузка | Mistral | `soft rebooting` либо `power off → power on` | Migration либо согласованный простой | Хост включён и возвращён в scheduler |
| Аварийное выключение | Masakari | `power off` | Fencing до evacuation | Хост выключен, ВМ эвакуированы |
| Внеплановая перезагрузка/возврат | Masakari + отдельный recovery workflow | `power off → power on` | Evacuation до возврата хоста | Хост включён после диагностики и проверок |

## Workflow: плановое выключение

```text
Horizon
  → Mistral
  → установить Masakari on_maintenance=true
  → nova service-disable
  → мигрировать или остановить ВМ
  → проверить отсутствие активных ВМ
  → Ironic: soft power off
  → дождаться power_state=power off
  → оставить Nova disabled и Masakari maintenance
```

Переход к жёсткому `power off` допускается только по явно заданной политике и после тайм-аута graceful shutdown.

## Workflow: плановая перезагрузка

```text
Horizon
  → Mistral
  → установить Masakari on_maintenance=true
  → nova service-disable
  → мигрировать ВМ либо подтвердить допустимый простой
  → Ironic: soft rebooting
       или
    Ironic: power off → подтвердить off → power on
  → проверить ОС, libvirt, nova-compute и сетевые/storage-агенты
  → nova service-enable
  → установить Masakari on_maintenance=false
```

Вариант `power off → подтверждение → power on` обеспечивает более контролируемую точку проверки.

## Workflow: аварийное выключение и evacuation

```text
Masakari Monitor
  → создать host-failure notification
  → disable_compute_service_task
  → custom ironic_fence_task
      → найти Ironic Node
      → выполнить hard power off
      → дождаться power_state=power off
      → проверить target_power_state и last_error
  → prepare_HA_enabled_instances_task
  → evacuate_instances_task
```

Критическое правило:

```text
Power off не подтверждён
  → workflow завершается с ошибкой
  → evacuation не выполняется
```

Это режим **fail closed**, исключающий одновременный запуск одной ВМ на исходном и новом хосте.

## Workflow: внеплановая перезагрузка / возврат хоста

Прямой `reboot` отказавшего хоста не должен заменять fencing.

```text
Обнаружение отказа
  → hard power off
  → подтверждение fencing
  → evacuation ВМ
  → диагностика или ремонт
  → Ironic: power on
  → проверить ОС и все compute-сервисы
  → убедиться в отсутствии старых активных ВМ
  → nova service-enable
  → снять Masakari maintenance
```

Возврат хоста рекомендуется выполнять отдельным Mistral workflow или отдельной операторской процедурой.

## Хранение Redfish-данных в Ironic

Для каждого compute-хоста создаётся Ironic `Node`:

```text
driver = redfish
driver_info:
  redfish_address
  redfish_system_id
  redfish_username
  redfish_password
  redfish_verify_ca
```

Рекомендуемые параметры эксплуатации:

```text
Node.name = Nova/Masakari hostname
provision_state = manageable
network_interface = noop
```

Такой узел используется только как реестр BMC и power backend. Его не следует переводить в `available` или запускать для него cleaning/provisioning.



## Основные правила

- Horizon не должен напрямую выключать compute-хост через Ironic, минуя Nova и Masakari.
- Плановые операции выполняются через Mistral.
- Аварийный fencing выполняется внутри Masakari custom TaskFlow.
- Evacuation разрешается только после подтверждённого `power off`.
- Все операции должны быть идемпотентными, иметь timeout, retry и блокировку по имени хоста.
- Redfish-пароли должны быть закрыты RBAC Ironic; предпочтителен Redfish HTTPS с проверкой CA.
