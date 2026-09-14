# PowerOps stand tests — run 1 (2026-09-14)

Прогон раннера `stand_test.py` на стенде `<stend-name>`. Оба сценария — PASS.

## Результаты

| run-id | scenario | result |
|--------|----------|--------|
| `run-1-emergency` | emergency | **PASS** |
| `run-1-planned` | planned | **PASS** |

См. `SUMMARY.md` для краткой выжимки и `HANDOFF.md` для полного описания правок, операций и замечаний.

## Содержимое

| Файл | Назначение |
|------|-----------|
| `SUMMARY.md` | краткий отчёт по результатам |
| `HANDOFF.md` | handoff: все правки сессии, операции, замечания |
| `run-1-emergency.json` | state-journal emergency (raw) |
| `run-1-planned.json` | state-journal planned (raw) |
| `report-run-1-emergency.json` | структурированный report emergency |
| `report-run-1-planned.json` | структурированный report planned |
| `task-run-1-emergency.json` | task JSON, использованный для emergency |
| `task-run-1-planned.json` | task JSON, использованный для planned |
| `inventory.ini` | Ansible inventory, использованный раннером |
| `openstack_probe.py.orig` | бэкап `openstack_probe.py` до патча |
| `remote_fault.py.orig` | бэкап `remote_fault.py` до патча |

## Воспроизведение

```bash
set -a; . /etc/kolla/<your-rc>.sh; set +a
unset OS_CLOUD

# Структурированный report (читает state-journal + опционально API)
python3.11 <repo>/stand_test.py report \
  --run-id run-1-emergency \
  --state-dir <repo>/artifacts/run-1
```

## Контекст сессии

- Ветка: `feature/powerops-stand-tests`
- HEAD на момент прогона: `8e49949`
- Стенд: `<stend-name>` (compute `compute-02` / `compute-03`, control `control-06/7/8`)
- Тестовая ВМ: `0000aaaa-aaaa-4aaa-8aaa-000000000001`
- Fault-interface: `enp3s0`
- Python на compute: 3.9 (не 3.11)
