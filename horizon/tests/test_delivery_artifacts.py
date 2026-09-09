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
    "mistral-lib": [
        "0001-feat-carry-PowerOps-identity-in-action-context.patch",
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
        "0011-feat-propagate-trusted-PowerOps-action-identity.patch",
        "0012-feat-define-PowerOps-role-authorization.patch",
        "0013-feat-reject-unauthorized-PowerOps-starts.patch",
        "0014-feat-reauthorize-PowerOps-workflow-resume.patch",
        "0015-feat-enforce-PowerOps-roles-and-hard-off-policy.patch",
        "0016-feat-expose-read-only-PowerOps-host-inventory.patch",
    ],
    "kolla": [
        "0001-feat-package-PowerOps-Horizon-and-Mistral-components.patch",
    ],
    "kolla-ansible": [
        "0001-fix-sanitize-Ironic-enrollment-baseline.patch",
        "0002-feat-define-Kolla-PowerOps-deployment-contract.patch",
        "0003-feat-render-etcd-backed-PowerOps-configuration.patch",
        "0004-feat-reconcile-PowerOps-actions-and-workbook.patch",
        "0005-docs-add-Russian-PowerOps-operations-guide.patch",
        "0006-fix-load-Masakari-through-idempotent-WSGI-wrapper.patch",
        "0007-feat-configure-Horizon-PowerOps-RBAC-and-image.patch",
        "0008-feat-validate-Horizon-PowerOps-runtime-contract.patch",
    ],
}

EXPECTED_PATCH_COUNTS = {
    'masakari': 10,
    'mistral-lib': 1,
    'mistral': 16,
    'kolla': 1,
    'kolla-ansible': 8,
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
            "## Установка патча mistral-lib",
            "## Установка патчей Mistral",
            "## Установка патча Kolla",
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
            "masakari-api.wsgi",
            "ArgsAlreadyParsedError",
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
        for project in (
                "masakari", "mistral-lib", "mistral", "kolla",
                "kolla-ansible"):
            for filename in PATCHES[project]:
                token = "patches/{}/{}".format(project, filename)
                position = text.find(token, previous + 1)
                self.assertGreater(
                    position,
                    previous,
                    "missing or out-of-order patch path: {}".format(token),
                )
                previous = position

        self.assertEqual(5, text.count("git am \\\n"))

    def test_install_guide_pins_baselines_and_final_commits(self):
        text = _read("INSTALL.md")
        delivery = _read("DELIVERY.md")
        required = {
            "039850556d0516e52b94b28f95762f310d779f16",
            "693174dd0aac1da22870b31e4a2481c4e749916a",
            "cf20c15a39516272faf2ddfd69a74644fdc105c5",
            "0fd34dd6a6d90525dbf806f35577c5ee1d7e9444",
            "83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5",
            "3b2eab29e9dc71a5ba250d989155eb69a9bd8e48",
            "9f9dee83d0e7146ce3d2011bc2169f0834e94ae4",
            "d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c",
            "aba086df9f5a1e17f74eb5a67286fa00b805bb6b",
            "703b06c9fa5771c758f703b424d63fb04192567a",
            "0870059ba6ea82621002286e679bb93fbf719733",
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

    def test_install_guide_declares_exact_component_and_image_dependencies(self):
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
            "powerops_horizon_image",
            "powerops_horizon_tag",
        ):
            self.assertIn(variable, text)
        self.assertIn("Mistral Event Engine", text)
        self.assertIn("powerops-local/horizon:2025.1-powerops", text)
        self.assertIn("powerops-local/mistral-api:2025.1-powerops", text)
        self.assertIn("powerops-local/mistral-engine:2025.1-powerops", text)
        self.assertIn("powerops-local/mistral-executor:2025.1-powerops", text)
        self.assertIn("build/kolla-build.conf", text)
        self.assertNotIn("powerops_mistral_event_engine_image", text)

    def test_globals_example_is_etcd_only_and_has_exact_allowlists(self):
        text = _read("INSTALL.md")
        for token in (
            'enable_ironic: "yes"',
            'enable_masakari: "yes"',
            'enable_mistral: "yes"',
            'enable_horizon: "yes"',
            'enable_etcd: "yes"',
            'enable_powerops: "yes"',
            "openstack_region_name: RegionOne",
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
            "enable_horizon",
            "enable_etcd",
            "enable_powerops",
            "openstack_region_name",
            "powerops_coordination_url",
            "powerops_masakari_engine_image",
            "powerops_masakari_engine_tag",
            "powerops_mistral_api_image",
            "powerops_mistral_api_tag",
            "powerops_mistral_engine_image",
            "powerops_mistral_engine_tag",
            "powerops_mistral_executor_image",
            "powerops_mistral_executor_tag",
            "powerops_horizon_image",
            "powerops_horizon_tag",
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
            "admin разрешён в любом проекте",
            "только к powerops_operator",
            "не требуется человеческая роль powerops_operator",
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
        self.assertIn("INSTALL.md", text)
        self.assertIn("OPERATIONS.md", text)
        self.assertIn("POWEROPS_HORIZON_OPERATIONS.md", text)
        self.assertIn("POWEROPS-ARCHITECTURE.md", text)
        self.assertIn("36 ordered Git patches", text)
        normalized = " ".join(text.split())
        self.assertIn("four target images were built and inspected", normalized)
        self.assertIn("mock UI was started and inspected", normalized)
        self.assertIn("99 plugin tests", normalized)
        self.assertIn("57 focused Kolla tests", normalized)
        self.assertIn("no deployment or reconfiguration was run",
                      normalized.lower())
        for unproven in (
                "deployed Horizon/Mistral/Masakari behavior",
                "Keystone assignments",
                "real service endpoints",
                "etcd ownership",
                "VM migration/stop/start",
                "Ironic/BMC power",
                "Masakari evacuation"):
            self.assertIn(unproven, normalized)

    def test_checksum_manifest_exactly_covers_all_patches(self):
        install = _read("INSTALL.md")
        lines = [line for line in _read("SHA256SUMS").splitlines() if line]
        expected = sorted([
            "patches/{}/{}".format(project, filename)
            for project in PATCHES
            for filename in PATCHES[project]
        ])
        actual = sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "patches").rglob("*.patch")
        )

        self.assertEqual(expected, actual)
        self.assertEqual(EXPECTED_PATCH_COUNTS, {
            project: len(filenames)
            for project, filenames in PATCHES.items()
        })
        self.assertIn('test "$POWEROPS_PATCH_COUNT" -eq 36', install)
        self.assertEqual(36, len(lines))
        self.assertEqual(expected, [line.split("  ", 1)[1] for line in lines])

        for line in lines:
            digest, relative = line.split("  ", 1)
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, digest, relative)

    def test_horizon_delivery_artifacts_and_operations_guide_exist(self):
        required = (
            "docs/superpowers/specs/"
            "2026-09-02-horizon-powerops-clean-integration-design.md",
            "docs/superpowers/plans/"
            "2026-09-02-horizon-powerops-clean-integration.md",
            "docs/evidence/"
            "2026-09-02-horizon-powerops-backend-readiness.md",
            "powerops-dashboard/setup.cfg",
            "powerops-dashboard/poweropsdashboard/enabled/_50_powerops.py",
            "POWEROPS_HORIZON_OPERATIONS.md",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

        setup = _read("powerops-dashboard/setup.cfg")
        setup_py = _read("powerops-dashboard/setup.py")
        manifest = _read("powerops-dashboard/MANIFEST.in")
        self.assertIn("name = powerops-dashboard", setup)
        self.assertIn("packages =\n    poweropsdashboard", setup)
        self.assertIn(
            "os.environ.setdefault('PBR_VERSION', '0.0.1')", setup_py)
        self.assertIn("include requirements.txt", manifest)

    def test_horizon_operations_guide_has_searchable_role_and_flow_contract(self):
        text = _read("POWEROPS_HORIZON_OPERATIONS.md")
        headings = (
            "Назначение и границы",
            "Роли admin и powerops_operator",
            "Настройка project/user allowlist",
            "Установка и включение Horizon-плагина",
            "Проверка Masakari WSGI и API",
            "Плановое выключение",
            "Плановая перезагрузка",
            "Включение и возврат в эксплуатацию",
            "Политики require_empty, live_migrate и stop",
            "Hard-off только для admin",
            "Состояния Mistral execution",
            "Ошибки 403, 409, 422, 503 и неопределённый timeout",
            "Диагностика Nova, Masakari, Ironic и etcd lock",
            "Разделение планового Mistral и аварийного Masakari",
        )
        for heading in headings:
            self.assertRegex(text, r"(?m)^##+ {}$".format(re.escape(heading)))

        for token in (
                "POWEROPS_PROJECT_NAME=powerops-operators",
                "POWEROPS_USER_NAME=svc-powerops",
                "openstack role create --or-show powerops_operator",
                '--project "$POWEROPS_PROJECT_NAME"',
                '--user "$POWEROPS_USER_NAME"',
                "openstack role assignment list",
                "admin работает в любом проекте",
                "обходит оба allowlist",
                "списки применяются только к powerops_operator",
                "Mistral service credentials",
                "не требуют человеческой роли powerops_operator"):
            self.assertIn(token, text)

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
