# Документация OpenStack / PVS

Ветка `docs/all-markdown` содержит только Markdown. Собраны документы из всех веток `mimaric` и локальные материалы по подготовке PVS. Одинаковые файлы объединены; отличающиеся редакции сохранены отдельно.

## Основные документы

| Тема | Документ |
|---|---|
| Требования к окружению, hostname, DNS, VIP и Horizon | [Требования перед деплоем](PREDEPLOY_ENVIRONMENT_REQUIREMENTS.md) |
| Vault и управление секретами | [Vault](VAULT_SETUP_FROM_ANSIBLE.md) |
| TLS и mTLS | [TLS/mTLS](TLS_MTLS_WORKFLOWS_FROM_ANSIBLE.md) |
| Cinder: NFS, Huawei и подготовка backend | [Cinder](CINDER_BACKENDS_FROM_ANSIBLE.md) |
| Glance, общее хранилище и отказоустойчивость | [Glance и storage HA](GLANCE_CINDER_SHARED_STORAGE_AND_HA.md) |
| OpenStack CLI и Horizon 2025.1 | [Сравнение CLI/Horizon](docs/openstack-cli-horizon-2025.1/README.md) |
| PowerOps | [Обзор](docs/POWEROPS-OVERVIEW.md) |
| FRR и anycast VIP | [PowerOps FRR](docs/POWEROPS-FRR-VIP-ANYCAST.md) |
| Host firewall | [Инструкция](integrations/kolla-ansible/host-firewall/README.md) |
| Watcher automation hold | [Инструкция](docs/WATCHER-AUTOMATION-HOLD.md) |
| Masakari per-target evacuation | [Инструкция](docs/MASAKARI-PER-TARGET-EVACUATION.md) |
| Тестирование стенда | [PowerOps stand tests](stand-tests/README.md) |

## Остальные материалы

- [Документация PowerOps, ADR и планы](docs/).
- [Документы Horizon](horizon/README.md).
- [Предыдущие редакции документов](archive/versions/).
- [README исходных веток](archive/branch-readmes/).
- [Рабочие черновики Cinder](archive/drafts/) — сохранены для полноты; итоговые инструкции находятся в таблице выше.
- [Полный реестр документов и источников](DOCUMENT_SOURCES.md).

## Как читать ссылки и примеры

Код, патчи, CSV/TSV, JSON и другие приложения в эту ветку не включены. Ссылки на существующие приложения ведут на зафиксированные исходные коммиты. Для запуска команд используйте соответствующую ветку кода или архивный тег из реестра; checkout этой ветки предоставляет только документы.

Пути `kolla-ansible-pvs_1.0.0/...` относятся к исходному архиву `kolla-ansible-pvs_1.0.0_14.09.zip`, который предоставляется отдельно. Старые документы и планы сохраняют свой исходный контекст и не подтверждают состояние работающего кластера.

Ветки `main`, `feature/host-firewall-apply` и `feature/masakari-per-target-evacuation` сохранены. История убранных веток закреплена тегами `archive/2026-09-16/...`.
