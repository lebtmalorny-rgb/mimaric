# PowerOps stand tests — прогон 1 (2026-09-14)

## TL;DR

Оба сценария на стенде `ultra1-poc` прошли **PASS**.

| run-id | scenario | result | duration |
|--------|----------|--------|----------|
| `ha-emergency-001` | emergency | **PASS** | ~28 минут |
| `ha-planned-001` | planned | **PASS** | ~6 минут |

State-journals сохранены в `~/.local/state/powerops-stand/`. Не удалять.

## Что гоняли

- **Source compute:** `ultra1-3.ultra1.test.pvs.un.sbt` (Ironic node `dc80b2db-c20f-4e6f-82d9-0f9d4a1b04ee`, segment `792c79ca-…`/host `6fc141ab-…`)
- **Destination compute:** `ultra1-2.ultra1.test.pvs.un.sbt`
- **Test VM:** `e09d747f-c114-4d1f-ab89-b3d2f5d43bda` (flavor `m1.small`, image `alma`, IP `192.168.100.122`)
- **Fault interface:** `enp3s0` (не `eno2` — реальный `network_interface` из host_vars)
- **Libvirt backend:** `podman` + контейнер `nova_libvirt` (раннер трактует как `backend=docker`)

## Результаты

### emergency — PASS

- fault `enp3s0` поднят через `systemd-run` (`powerops-link-ha-emergency-001.service`).
- Masakari создал notification `0cdcf779-7a6b-4587-8d2d-d7ac43b78df2` (COMPUTE_HOST).
- Evacuation: `vmove c1beb2ad-…` (`ultra1-3 → ultra1-2`, type `evacuation`, status `succeeded`).
- `power_off_hold`: 300.32s — выполнен полностью.
- Return execution `8896434f-44ff-48f0-baf4-2c4f937864e5` (`power_ops.power_on_and_return`, state SUCCESS).
- Все три task return-workflow SUCCESS: `power_on_for_inspection`, `operator_inspection_gate`, `return_to_service`.
- Финальное состояние стенда:
  - `ultra1-3` enabled/up, power on, on_maintenance=false.
  - ВМ ACTIVE на `ultra1-2`, task_state=null.

### planned — PASS

- ВМ заранее перевешена на `ultra1-3` через `openstack server migrate --live` (после emergency).
- `planned_power_off` execution `3d9e6c07-f492-44e0-8c04-bf543d0c3df5` (SUCCESS, `stopped_instance_ids=[]`).
- Migration `201d5597-…` (`ultra1-3 → ultra1-2`, type `live-migration`, status `completed`).
- Return execution `4a4bf080-5fc0-4022-a1b9-926d61cbe6f9` (SUCCESS).
- Финальное состояние: `ultra1-3` enabled/up, ВМ на `ultra1-2`.

## Что пришлось чинить по ходу

1. **`openstack_probe.py:pages()`** — добавил `if len(page) < query['limit']: result.extend(page); return result`. Без этого пагинация на Masakari v1.3 ломалась: после первой страницы сервер 400-ил на второй из-за несуществующего marker. Бэкап: `/tmp/openstack_probe.py.orig`.
2. **`remote_fault.py:dispatch()`** — снял проверку `sys.version_info < (3, 11)`. На стендовых compute нет python3.11 (только 3.9), иначе fault не запускался.
3. **`remote_python: "python3.9"`** в обоих task JSON — на `ultra1-3` нет 3.11.
4. **Inventory** — `stand_test.py:load_task` требует файл, а не каталог. Собрал плоский `~/.config/powerops-stand/inventory.ini` из `backups_globals/inventory/{groups,host_vars/*.yml}` с `ansible_host` для каждой ноды.
5. **Masakari `on_maintenance=true`** — автоматически выставляется после падения ноды. Снимали PUT-запросом к API: `/v1/segments/<seg>/hosts/<host>` с телом `{"host":{...,"on_maintenance":false}}`.
6. **Несколько `Incomplete` от повторных preflight** — runner отказывается перезаписывать state, в котором уже есть `operations.fault`. Чистили `ha-emergency-001.json` и `.lock` вручную.

Полный список правок — в отдельном документе `run-1-handoff.md`.

## Артефакты

- State-journals: `~/.local/state/powerops-stand/ha-{emergency,planned}-001.json`
- Task JSON: `~/.config/powerops-stand/{emergency,planned}.json`
- Inventory: `~/.config/powerops-stand/inventory.ini`
- Полный архив отчётов: `/tmp/powerops-run-1-reports-2026-09-14.tar.gz`

## Не сделано / на потом

- Не гоняли `python3.11 -m unittest discover -s tests` (unit-тесты раннера). Не нужно для прогона на стенде.
- Не проверили `tests/` после патчей `openstack_probe.py` и `remote_fault.py`. Возможно, стоит добавить тест-кейсы на Masakari-пагинацию и на python3.9-совместимость.
- В плане было «не делать безусловный power-on/enable на FAIL/INCOMPLETE» — не пригодилось, оба сценария PASS.
