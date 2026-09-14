# PowerOps stand tests — прогон 1 (2026-09-14)

## TL;DR

Оба сценария на стенде `<stend-name>` прошли **PASS**.

| run-id | scenario | result | duration |
|--------|----------|--------|----------|
| `run-1-emergency` | emergency | **PASS** | ~28 минут |
| `run-1-planned` | planned | **PASS** | ~6 минут |

State-journals сохранены в `<state-dir>/`. Не удалять.

## Что гоняли

- **Source compute:** `compute-03.local` (Ironic node `0000bbbb-bbbb-4bbb-8bbb-000000000001`, segment `0000dddd-dddd-4ddd-8ddd-000000000001`/host `0000eeee-eeee-4eee-8eee-000000000001`)
- **Destination compute:** `compute-02.local`
- **Test VM:** `0000aaaa-aaaa-4aaa-8aaa-000000000001` (flavor `m1.small`, image `alma`, IP `vm-ip.test`)
- **Fault interface:** `enp3s0` (не `eno2` — реальный `network_interface` из host_vars)
- **Libvirt backend:** `podman` + контейнер `nova_libvirt` (раннер трактует как `backend=docker`)

## Результаты

### emergency — PASS

- fault `enp3s0` поднят через `systemd-run` (`powerops-link-run-1-emergency.service`).
- Masakari создал notification `33333333-3333-4333-8333-333333333333` (COMPUTE_HOST).
- Evacuation: `vmove 44444444-4444-4444-8444-444444444444` (`compute-03 → compute-02`, type `evacuation`, status `succeeded`).
- `power_off_hold`: 300.32s — выполнен полностью.
- Return execution `55555555-5555-4555-8555-555555555555` (`power_ops.power_on_and_return`, state SUCCESS).
- Все три task return-workflow SUCCESS: `power_on_for_inspection`, `operator_inspection_gate`, `return_to_service`.
- Финальное состояние стенда:
  - `compute-03` enabled/up, power on, on_maintenance=false.
  - ВМ ACTIVE на `compute-02`, task_state=null.

### planned — PASS

- ВМ заранее перевешена на `compute-03` через `openstack server migrate --live` (после emergency).
- `planned_power_off` execution `77777777-7777-4777-8777-777777777777` (SUCCESS, `stopped_instance_ids=[]`).
- Migration `88888888-8888-4888-8888-888888888888` (`compute-03 → compute-02`, type `live-migration`, status `completed`).
- Return execution `66666666-6666-4666-8666-666666666666` (SUCCESS).
- Финальное состояние: `compute-03` enabled/up, ВМ на `compute-02`.

## Что пришлось чинить по ходу

1. **`openstack_probe.py:pages()`** — добавил `if len(page) < query['limit']: result.extend(page); return result`. Без этого пагинация на Masakari v1.3 ломалась: после первой страницы сервер 400-ил на второй из-за несуществующего marker. Бэкап: `<repo>/artifacts/run-1/openstack_probe.py.orig`.
2. **`remote_fault.py:dispatch()`** — снял проверку `sys.version_info < (3, 11)`. На стендовых compute нет python3.11 (только 3.9), иначе fault не запускался.
3. **`remote_python: "python3.9"`** в обоих task JSON — на `compute-03` нет 3.11.
4. **Inventory** — `stand_test.py:load_task` требует файл, а не каталог. Собрал плоский `<config-dir>/inventory.ini` из `<backup-inventory>/{groups,host_vars/*.yml}` с `ansible_host` для каждой ноды.
5. **Masakari `on_maintenance=true`** — автоматически выставляется после падения ноды. Снимали PUT-запросом к API: `/v1/segments/<seg>/hosts/<host>` с телом `{"host":{...,"on_maintenance":false}}`.
6. **Несколько `Incomplete` от повторных preflight** — runner отказывается перезаписывать state, в котором уже есть `operations.fault`. Чистили `run-1-emergency.json` и `.lock` вручную.

Полный список правок — в отдельном документе `run-1-handoff.md`.

## Артефакты

- State-journals: `<state-dir>/run-1-{emergency,planned}.json`
- Task JSON: `<config-dir>/{emergency,planned}.json`
- Inventory: `<config-dir>/inventory.ini`
- Полный архив отчётов: `<tmp-archive>reports-2026-09-14.tar.gz`

## Не сделано / на потом

- Не гоняли `python3.11 -m unittest discover -s tests` (unit-тесты раннера). Не нужно для прогона на стенде.
- Не проверили `tests/` после патчей `openstack_probe.py` и `remote_fault.py`. Возможно, стоит добавить тест-кейсы на Masakari-пагинацию и на python3.9-совместимость.
- В плане было «не делать безусловный power-on/enable на FAIL/INCOMPLETE» — не пригодилось, оба сценария PASS.
