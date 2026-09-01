"""Contracts for the operator-facing PowerOps delivery artifacts."""

import hashlib
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]

PATCHES = {
    "masakari": [
        "0001-feat-add-PowerOps-coordination-primitives.patch",
        "0002-feat-fence-failed-hosts-through-Ironic.patch",
        "0003-fix-enforce-Ironic-fencing-deadlines.patch",
        "0004-fix-honor-service-TLS-for-Ironic.patch",
        "0005-feat-lock-complete-Masakari-host-recovery.patch",
        "0006-test-harden-Masakari-host-lock-coverage.patch",
        "0007-feat-serialize-Masakari-evacuations-through-etcd.patch",
        "0008-docs-describe-Masakari-PowerOps-fencing.patch",
        "0009-fix-satisfy-PowerOps-package-lint.patch",
        "0010-fix-fail-closed-on-PowerOps-coordination-loss.patch",
    ],
    "mistral": [
        "0001-feat-add-PowerOps-action-coordination.patch",
        "0002-fix-declare-PowerOps-etcd-backend.patch",
        "0003-feat-add-PowerOps-OpenStack-primitives.patch",
        "0004-fix-align-PowerOps-with-SDK-resources.patch",
        "0005-feat-add-planned-PowerOps-actions.patch",
        "0006-fix-harden-planned-action-boundaries.patch",
        "0007-feat-add-guarded-host-return-actions.patch",
        "0008-feat-register-the-PowerOps-workbook-API.patch",
        "0009-test-generalize-action-plugin-coverage.patch",
        "0010-fix-scope-workbook-updates-to-request-project.patch",
    ],
    "kolla-ansible": [
        "0001-fix-sanitize-Ironic-enrollment-baseline.patch",
        "0002-feat-define-Kolla-PowerOps-deployment-contract.patch",
        "0003-feat-render-etcd-backed-PowerOps-configuration.patch",
        "0004-feat-reconcile-PowerOps-actions-and-workbook.patch",
        "0005-docs-add-Russian-PowerOps-operations-guide.patch",
    ],
}


def _read(relative):
    path = ROOT / relative
    if not path.is_file():
        raise AssertionError(
            "required delivery file is missing: {}".format(path)
        )
    return path.read_text(encoding="utf-8")


class DeliveryArtifactsTest(unittest.TestCase):
    def test_install_guide_has_safe_operator_flow(self):
        text = _read("INSTALL.md")
        headings = [
            "# Установка OpenStack PowerOps",
            "## Краткий вывод",
            "## Проверка комплекта",
            "## Подготовка исходных репозиториев",
            "## Установка патчей Masakari",
            "## Установка патчей Mistral",
            "## Установка патчей Kolla-Ansible",
            "## Требования к сборке образов",
            "## Настройка globals.yml",
            "## Prechecks и явный gate изменения",
            "## Проверки после установки",
            "## Первый live canary",
            "## Возобновление workflow возврата",
            "## Откат",
            "## Граница статической и live-проверки",
        ]
        for heading in headings:
            self.assertIn(heading, text)

        for token in (
            "git am --abort",
            "kolla-ansible prechecks -i /path/to/inventory",
            "kolla-ansible deploy -i /path/to/inventory",
            "kolla-ansible reconfigure -i /path/to/inventory",
            "powerops_reconcile_workbook",
            "powerops_validate_registration",
            "kolla_admin_openrc_cacert",
            "stale_domains_checked",
            '"state": "RUNNING"',
            "Mistral 0010",
            "Kolla-Ansible 0004",
            "не запускает workflow",
            "отдельного разрешения оператора",
        ):
            self.assertIn(token, text)

        self.assertNotRegex(
            text,
            r"kolla-ansible\s+-i\s+/path/to/inventory\s+"
            r"(?:prechecks|deploy|reconfigure)",
        )

    def test_post_install_commands_read_the_claimed_state(self):
        text = _read("INSTALL.md")
        normalized = " ".join(text.split())

        self.assertIn("openstack action definition list", normalized)
        self.assertNotIn("openstack action list", normalized)
        self.assertIn(
            "openstack baremetal node list --fields uuid name",
            normalized,
        )
        self.assertIn(
            "openstack baremetal node show NODE_UUID --fields uuid name "
            "provision_state power_state target_power_state last_error "
            "network_interface",
            normalized,
        )

    def test_controller_ca_is_checked_before_and_inside_mutation_gate(self):
        text = _read("INSTALL.md")
        normalized = " ".join(text.split())

        self.assertIn('test -f "$POWEROPS_CONTROLLER_CA"', text)
        self.assertIn('test -r "$POWEROPS_CONTROLLER_CA"', text)
        self.assertIn(
            "prechecks не проверяет kolla_admin_openrc_cacert",
            normalized,
        )
        self.assertIn(
            "после meta: flush_handlers и Mistral action population",
            normalized,
        )
        self.assertNotIn(
            "prechecks подтверждает доступность controller CA",
            normalized,
        )

    def test_install_guide_lists_exact_patch_order(self):
        text = _read("INSTALL.md")
        previous = -1
        for project in ("masakari", "mistral", "kolla-ansible"):
            for filename in PATCHES[project]:
                token = "patches/{}/{}".format(project, filename)
                position = text.find(token, previous + 1)
                self.assertGreater(
                    position,
                    previous,
                    "missing or out-of-order patch path: {}".format(token),
                )
                previous = position

        self.assertEqual(3, text.count("git am \\\n"))

    def test_install_guide_pins_baselines_and_final_commits(self):
        text = _read("INSTALL.md")
        delivery = _read("DELIVERY.md")
        required = {
            "0fd34dd6a6d90525dbf806f35577c5ee1d7e9444",
            "9f3cb144958b8e60bba72adefb22edf51387c0ca",
            "83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5",
            "3b2eab29e9dc71a5ba250d989155eb69a9bd8e48",
            "3e4fe82455de7473809b0e0bc677fa3df3a3d1e2",
            "8e3009eb1abf8033608d31d7e60cdb02ab8da1ed",
            "df27628ce641fefee30114ebeb3651490655aacb0930ad5bc30a298c88c3e08d",
            "703b06c9fa5771c758f703b424d63fb04192567a",
            "63a8d0f597f9034a42f2e1b0bd415f1746d33b8d",
            "287bac4223f24393c32fbfd55c140601c8611a21",
        }
        found = set(re.findall(r"[0-9a-f]{40,64}", text))
        self.assertEqual(set(), required - found)
        delivery_found = set(re.findall(r"[0-9a-f]{40,64}", delivery))
        self.assertEqual(set(), required - delivery_found)
        self.assertNotIn(
            "665cde880127f56c8335e6f8b210362f87ae19d9",
            text,
        )
        self.assertNotIn(
            "9bc9c63d8c1c42f575c0a47198884c75180d595a",
            text,
        )
        self.assertNotIn(
            "665cde880127f56c8335e6f8b210362f87ae19d9",
            delivery,
        )
        self.assertNotIn(
            "9bc9c63d8c1c42f575c0a47198884c75180d595a",
            delivery,
        )

    def test_install_guide_declares_exact_images_and_no_build_recipe(self):
        text = _read("INSTALL.md")
        for variable in (
            "powerops_masakari_engine_image",
            "powerops_masakari_engine_tag",
            "powerops_mistral_api_image",
            "powerops_mistral_api_tag",
            "powerops_mistral_engine_image",
            "powerops_mistral_engine_tag",
            "powerops_mistral_executor_image",
            "powerops_mistral_executor_tag",
        ):
            self.assertIn(variable, text)
        self.assertIn("Mistral Event Engine", text)
        self.assertNotRegex(text, r"(?m)^\s*(?:kolla-build|kolla build)\b")
        self.assertNotIn("powerops_mistral_event_engine_image", text)

    def test_globals_example_is_etcd_only_and_has_exact_allowlists(self):
        text = _read("INSTALL.md")
        for token in (
            'enable_ironic: "yes"',
            'enable_masakari: "yes"',
            'enable_mistral: "yes"',
            'enable_etcd: "yes"',
            'enable_powerops: "yes"',
            "etcd3+{{ internal_protocol }}",
            "powerops_allowed_project_names:",
            "  - powerops-operators",
            "powerops_allowed_user_names:",
            "  - svc-powerops",
            'powerops_reconcile_workbook: "yes"',
            'powerops_validate_registration: "yes"',
        ):
            self.assertIn(token, text)
        self.assertIn("пустой список запрещает все вызовы", text)
        self.assertIn("запятые", text)
        self.assertNotRegex(text, r"(?im)^\s*(?:password|token|secret)\s*:")
        self.assertNotRegex(text, r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
        self.assertNotIn("Redis как зависимость PowerOps", text)

    def test_globals_section_explains_every_example_parameter(self):
        text = _read("INSTALL.md")
        globals_section = text.split("## Настройка globals.yml", 1)[1]
        globals_section = globals_section.split(
            "## Prechecks и явный gate изменения", 1
        )[0]

        documented_parameters = (
            "enable_ironic",
            "enable_masakari",
            "enable_mistral",
            "enable_etcd",
            "enable_powerops",
            "powerops_coordination_url",
            "powerops_masakari_engine_image",
            "powerops_masakari_engine_tag",
            "powerops_mistral_api_image",
            "powerops_mistral_api_tag",
            "powerops_mistral_engine_image",
            "powerops_mistral_engine_tag",
            "powerops_mistral_executor_image",
            "powerops_mistral_executor_tag",
            "powerops_allowed_project_names",
            "powerops_allowed_user_names",
            "powerops_host_lock_timeout",
            "powerops_evacuation_lock_timeout",
            "powerops_evacuation_interval",
            "powerops_power_timeout",
            "powerops_poll_interval",
            "powerops_stable_observations",
            "powerops_graceful_shutdown_timeout",
            "powerops_vm_action_timeout",
            "powerops_service_timeout",
            "powerops_instance_interval",
            "powerops_reconcile_workbook",
            "powerops_validate_registration",
            "kolla_admin_openrc_cacert",
        )
        for parameter in documented_parameters:
            self.assertIn(
                "| `{}` |".format(parameter),
                globals_section,
                "missing globals parameter explanation: {}".format(
                    parameter
                ),
            )

        normalized = " ".join(globals_section.split())
        for statement in (
            "имя проекта Keystone",
            "имя пользователя Keystone",
            "оба условия одновременно",
            "не создают Keystone-проект",
            "не заменяют Keystone RBAC",
            "любая комбинация пользователя и проекта",
            "регистрозависимо",
            "сервисными credentials Mistral",
        ):
            self.assertIn(statement, normalized)

    def test_operations_runbook_is_linked_and_read_only(self):
        operations = _read("OPERATIONS.md")
        install = _read("INSTALL.md")
        delivery = _read("DELIVERY.md")

        for heading in (
            "# PowerOps: контроль и диагностика",
            "## Краткий вывод",
            "## Правила безопасности",
            "## Базовый read-only снимок",
            "## Плановое выключение",
            "## Плановая перезагрузка",
            "## Двухфазный возврат хоста",
            "## Аварийное отключение, fencing и evacuation",
            "## Диагностика по компонентам",
            "## Матрица неисправностей",
            "## Контролируемая runtime-приёмка",
            "## Пакет доказательств",
        ):
            self.assertIn(heading, operations)

        for token in (
            'openstack compute service list --host "$HOST"',
            'openstack server list --all-projects --host "$HOST" --long',
            'openstack baremetal node show "$NODE_UUID"',
            'openstack segment host show "$SEGMENT_UUID" "$HOST"',
            'openstack workflow execution show "$EXECUTION_ID"',
            'openstack task execution list "$EXECUTION_ID"',
            'openstack action execution list "$TASK_EXECUTION_ID"',
            'openstack notification show "$NOTIFICATION_ID"',
            'openstack notification vmove list "$NOTIFICATION_ID"',
            "etcdctl --endpoints=\"$ETCD_ENDPOINTS\" endpoint health",
            "powerops/host/<host>",
            "powerops/evacuation/global",
            "stale_domains_checked=true",
            "stable-off",
            "FAILED",
            "PASS",
        ):
            self.assertIn(token, operations)

        routine = operations.split(
            "## Контролируемая runtime-приёмка", 1
        )[0]
        for mutation in (
            "openstack workflow execution create",
            "openstack workflow execution update",
            "openstack notification create",
            "openstack segment host update",
            "openstack compute service set",
            "openstack baremetal node power",
            "openstack server evacuate",
            "openstack server migrate",
            "openstack server start",
            "openstack server stop",
            "openstack server reboot",
        ):
            self.assertNotIn(mutation, routine)

        link = "[`OPERATIONS.md`](OPERATIONS.md)"
        self.assertIn(link, install)
        self.assertIn(link, delivery)

        planned_procedure = "### Плановое выключение: готовая процедура"
        self.assertIn(planned_procedure, operations)
        self.assertGreater(
            operations.find(planned_procedure),
            operations.find("## Контролируемая runtime-приёмка"),
        )
        for token in (
            "command -v jq",
            "INSTANCE_POLICY=require_empty",
            "ALLOW_HARD_OFF=false",
            'case "$INSTANCE_POLICY" in',
            'case "$ALLOW_HARD_OFF" in',
            'allow-hard-off:$HOST',
            'jq -nc \\\n',
            '--argjson allow_hard_off "$ALLOW_HARD_OFF"',
            'power_ops.planned_power_off "$WORKFLOW_INPUT"',
            "-f value -c ID",
            'test -n "$EXECUTION_ID"',
            'openstack workflow execution output show "$EXECUTION_ID"',
            "allow_hard_off=true",
        ):
            self.assertIn(token, operations)

    def test_delivery_manifest_records_verified_evidence_and_boundary(self):
        text = _read("DELIVERY.md")
        for heading in (
            "# OpenStack PowerOps patch delivery",
            "## Baselines",
            "## Patch order",
            "## Implemented scenarios",
            "## Test commands and results",
            "## Static verification boundary",
            "## Live verification still required",
            "## Safe apply and rollback notes",
        ):
            self.assertIn(heading, text)
        for result in (
            "895 passed, 3 skipped",
            "85 passed",
            "1620 passed, 8 skipped",
            "332/332",
            "6/6",
            "120/120",
            "PowerOps 106/106",
            "broader 106/106",
            "stopped after 829",
            "64/64",
            "19/19",
            "31/31",
        ):
            self.assertIn(result, text)
        self.assertNotIn("29/29", text)
        self.assertNotIn("30/30", text)
        self.assertIn("INSTALL.md", text)
        self.assertIn("OPERATIONS.md", text)
        self.assertIn("POWEROPS-ARCHITECTURE.md", text)
        self.assertIn("25", text)
        normalized = " ".join(text.split())
        self.assertIn("no images were built or pushed", normalized)
        self.assertIn("no deployment or reconfiguration was run", normalized)

    def test_checksum_manifest_exactly_covers_all_patches(self):
        install = _read("INSTALL.md")
        lines = [line for line in _read("SHA256SUMS").splitlines() if line]
        expected = [
            "patches/{}/{}".format(project, filename)
            for project in sorted(PATCHES)
            for filename in PATCHES[project]
        ]
        actual = sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "patches").rglob("*.patch")
        )

        self.assertEqual(expected, actual)
        self.assertIn('test "$POWEROPS_PATCH_COUNT" -eq 25', install)
        self.assertEqual(25, len(lines))
        self.assertEqual(expected, [line.split("  ", 1)[1] for line in lines])

        for line in lines:
            digest, relative = line.split("  ", 1)
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, digest, relative)

    def test_plans_and_design_capture_final_owner_scope_contract(self):
        combined = "\n".join(
            _read(path)
            for path in (
                "docs/superpowers/plans/2026-08-31-kolla-ansible-powerops.md",
                "docs/superpowers/plans/2026-08-31-mistral-powerops.md",
                (
                    "docs/superpowers/specs/"
                    "2026-08-31-openstack-powerops-design.md"
                ),
            )
        )
        for token in (
            "/workbooks?name=power_ops&namespace=",
            "powerops_keystone_project_id",
            "ambiguous or foreign public power_ops workbook",
            "kolla_admin_openrc_cacert",
            "/actions/{{ item }}",
            "/workflows?name={{ item }}&namespace=",
            "models.Workbook.project_id == security.get_project_id()",
            "ActionDefinition",
            "WorkflowDefinition",
            "project_id=wb_db.project_id",
            "one SQLAlchemy transaction",
            "0010-fix-scope-workbook-updates-to-request-project.patch",
            "TOCTOU",
        ):
            self.assertIn(token, combined)

        all_docs = "\n".join((combined, _read("INSTALL.md"),
                              _read("DELIVERY.md")))
        normalized = " ".join(all_docs.split())
        self.assertIn("structured LOG.info process log", normalized)
        self.assertIn("no external durable audit store", normalized)
        self.assertIn("no delivery or persistence guarantee", normalized)
        self.assertNotIn("durable success audit", normalized)


if __name__ == "__main__":
    unittest.main()
