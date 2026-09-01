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
            "kolla-ansible prechecks",
            "kolla-ansible deploy",
            "kolla-ansible reconfigure",
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
        required = {
            "0fd34dd6a6d90525dbf806f35577c5ee1d7e9444",
            "9f3cb144958b8e60bba72adefb22edf51387c0ca",
            "3b2eab29e9dc71a5ba250d989155eb69a9bd8e48",
            "665cde880127f56c8335e6f8b210362f87ae19d9",
            "df27628ce641fefee30114ebeb3651490655aacb0930ad5bc30a298c88c3e08d",
            "703b06c9fa5771c758f703b424d63fb04192567a",
            "9bc9c63d8c1c42f575c0a47198884c75180d595a",
        }
        found = set(re.findall(r"[0-9a-f]{40,64}", text))
        self.assertEqual(set(), required - found)

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
            "106 passed",
            "60 passed",
            "3 passed",
            "4 inherited sandbox failures",
            "63 passed",
            "18 passed",
        ):
            self.assertIn(result, text)
        self.assertIn("INSTALL.md", text)
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
            "0010-fix-scope-workbook-updates-to-request-project.patch",
            "TOCTOU",
        ):
            self.assertIn(token, combined)


if __name__ == "__main__":
    unittest.main()
