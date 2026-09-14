# PowerOps stand tests — run 1 (2026-09-14)

Прогон раннера `stand_test.py` на стенде `ultra1-poc`. Оба сценария — PASS.

## Результаты

| run-id | scenario | result |
|--------|----------|--------|
| `ha-emergency-001` | emergency | **PASS** |
| `ha-planned-001` | planned | **PASS** |

См. `SUMMARY.md` для краткой выжимки и `HANDOFF.md` для полного описания правок, операций и замечаний.

## Содержимое

| Файл | Назначение |
|------|-----------|
| `SUMMARY.md` | краткий отчёт по результатам |
| `HANDOFF.md` | handoff: все правки сессии, операции, замечания |
| `ha-emergency-001.json` | state-journal emergency (raw) |
| `ha-planned-001.json` | state-journal planned (raw) |
| `report-ha-emergency-001.json` | структурированный report emergency |
| `report-ha-planned-001.json` | структурированный report planned |
| `task-emergency.json` | task JSON, использованный для emergency |
| `task-planned.json` | task JSON, использованный для planned |
| `inventory.ini` | Ansible inventory, использованный раннером |
| `openstack_probe.py.orig` | бэкап `openstack_probe.py` до патча |
| `remote_fault.py.orig` | бэкап `remote_fault.py` до патча |

## Воспроизведение

```bash
set -a; . /etc/kolla/admin-openrc.sh; set +a
unset OS_CLOUD

# Структурированный report (читает state-journal + опционально API)
python3.11 /home/DVSokolov/work/mimaric/stand_test.py report \
  --run-id ha-emergency-001 \
  --state-dir /home/DVSokolov/work/mimaric/artifacts/run-1
```

## Контекст сессии

- Ветка: `feature/powerops-stand-tests`
- HEAD на момент прогона: `8e49949`
- Стенд: `ultra1-poc` (compute `ultra1-2` / `ultra1-3`, control `ultra1-6/7/8`)
- Тестовая ВМ: `e09d747f-c114-4d1f-ab89-b3d2f5d43bda`
- Fault-interface: `enp3s0`
- Python на compute: 3.9 (не 3.11)
