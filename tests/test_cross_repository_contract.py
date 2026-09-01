"""Source-only contracts shared by Masakari, Mistral and Kolla-Ansible.

The suite intentionally uses only the Python standard library.  It reads the
three supplied source trees without importing OpenStack service packages,
opening sockets or invoking cloud commands.
"""

import ast
import configparser
import os
from pathlib import Path
import re
import unittest


ACTION_TARGETS = {
    "powerops.host_power_status": (
        "mistral.actions.powerops.return_host:HostPowerStatusAction"
    ),
    "powerops.planned_power_off": (
        "mistral.actions.powerops.planned:PlannedPowerOffAction"
    ),
    "powerops.planned_reboot": (
        "mistral.actions.powerops.planned:PlannedRebootAction"
    ),
    "powerops.power_on_for_inspection": (
        "mistral.actions.powerops.return_host:PowerOnForInspectionAction"
    ),
    "powerops.return_to_service": (
        "mistral.actions.powerops.return_host:ReturnToServiceAction"
    ),
}

WORKFLOW_NAMES = {
    "host_power_status",
    "planned_power_off",
    "planned_reboot",
    "power_on_and_return",
}

EMERGENCY_TASK_ORDER = [
    "disable_compute_service_task",
    "ironic_fence",
    "prepare_HA_enabled_instances_task",
    "evacuate_instances_task",
]


def _required_tree(variable):
    value = os.environ.get(variable)

    if not value:
        raise AssertionError(
            "{} must name the source tree under test".format(variable)
        )

    path = Path(value).expanduser().resolve()

    if not path.is_dir():
        raise AssertionError(
            "{} does not name a directory: {}".format(variable, path)
        )

    return path


def _read(tree, relative_path):
    path = tree / relative_path

    if not path.is_file():
        raise AssertionError(
            "required PowerOps contract file is missing: {}".format(path)
        )

    return path.read_text(encoding="utf-8")


def _read_bytes(tree, relative_path):
    path = tree / relative_path

    if not path.is_file():
        raise AssertionError(
            "required PowerOps contract file is missing: {}".format(path)
        )

    return path.read_bytes()


def _python_module(tree, relative_path):
    source = _read(tree, relative_path)

    try:
        return source, ast.parse(source, filename=str(tree / relative_path))
    except SyntaxError as exc:
        raise AssertionError(
            "PowerOps source is not valid Python: {}: {}".format(
                tree / relative_path, exc
            )
        ) from exc


def _class_method(module, class_name, method_name):
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if (
                        isinstance(child, (ast.FunctionDef,
                                           ast.AsyncFunctionDef))
                        and child.name == method_name):
                    return child

    raise AssertionError(
        "required method {}.{} is missing".format(class_name, method_name)
    )


def _function(module, function_name):
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node

    raise AssertionError(
        "required function {} is missing".format(function_name)
    )


def _assignment_literal(module, variable_name):
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )

        if not any(
                isinstance(target, ast.Name)
                and target.id == variable_name
                for target in targets):
            continue

        value = node.value

        if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "frozenset"
                and len(value.args) == 1):
            value = value.args[0]

        try:
            return ast.literal_eval(value)
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                "{} must have a literal value".format(variable_name)
            ) from exc

    raise AssertionError(
        "required assignment {} is missing".format(variable_name)
    )


def _entry_points(tree, group):
    path = tree / "setup.cfg"

    if not path.is_file():
        raise AssertionError("required setup.cfg is missing: {}".format(path))

    parser = configparser.ConfigParser(
        interpolation=None,
        strict=False,
    )
    parser.optionxform = str

    with path.open(encoding="utf-8") as stream:
        parser.read_file(stream)

    if not parser.has_option("entry_points", group):
        raise AssertionError(
            "setup.cfg has no {!r} entry-point group".format(group)
        )

    result = {}

    for line in parser.get("entry_points", group).splitlines():
        line = line.strip()

        if not line:
            continue

        if "=" not in line:
            raise AssertionError(
                "malformed entry point in {}: {!r}".format(path, line)
            )

        name, target = line.split("=", 1)
        result[name.strip()] = target.strip()

    return result


def _mapping_child_keys(source, parent_key, parent_indent):
    lines = source.splitlines()
    header = " " * parent_indent + parent_key + ":"

    try:
        start = lines.index(header)
    except ValueError as exc:
        raise AssertionError(
            "YAML mapping {!r} is missing".format(parent_key)
        ) from exc

    child_indent = parent_indent + 2
    keys = []

    for line in lines[start + 1:]:
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        if indent <= parent_indent:
            break

        if indent == child_indent:
            match = re.fullmatch(r"([A-Za-z0-9_.-]+):(?:\s.*)?", stripped)

            if match:
                keys.append(match.group(1))

    return keys


def _key_block(source, key, indent):
    lines = source.splitlines()
    header = " " * indent + key + ":"

    try:
        start = lines.index(header)
    except ValueError as exc:
        raise AssertionError(
            "required block {!r} at indent {} is missing".format(
                key, indent
            )
        ) from exc

    end = len(lines)

    for index in range(start + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        current_indent = len(line) - len(line.lstrip(" "))

        if current_indent <= indent:
            end = index
            break

    return "\n".join(lines[start:end])


def _top_level_value_block(source, key):
    lines = source.splitlines()
    prefix = key + ":"

    for start, line in enumerate(lines):
        if line.startswith(prefix):
            break
    else:
        raise AssertionError(
            "required top-level setting {!r} is missing".format(key)
        )

    end = len(lines)

    for index in range(start + 1, len(lines)):
        line = lines[index]

        if line and not line.startswith((" ", "#")):
            end = index
            break

    return "\n".join(lines[start:end])


def _ansible_tasks(source):
    matches = list(re.finditer(r"(?m)^- name: ([^\n]+)$", source))
    tasks = {}

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            source
        )
        tasks[match.group(1).strip().strip('"')] = source[
            match.start():end
        ]

    return tasks


def _ordered(source, tokens, description):
    position = -1

    for token in tokens:
        next_position = source.find(token, position + 1)

        if next_position < 0:
            raise AssertionError(
                "{} is missing ordered token {!r}".format(
                    description, token
                )
            )

        if next_position <= position:
            raise AssertionError(
                "{} has token {!r} out of order".format(
                    description, token
                )
            )

        position = next_position


def _quoted_task_order(template, variable_name):
    match = re.search(
        r"(?m)^{}\s*=\s*(.+)$".format(re.escape(variable_name)),
        template,
    )

    if not match:
        raise AssertionError(
            "Kolla template does not set {}".format(variable_name)
        )

    return re.findall(r"'([^']+)'", match.group(1))


class CrossRepositoryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.masakari = _required_tree("POWEROPS_MASAKARI_TREE")
        cls.mistral = _required_tree("POWEROPS_MISTRAL_TREE")
        cls.kolla = _required_tree("POWEROPS_KOLLA_TREE")

    def test_masakari_fence_entrypoint_and_recovery_order(self):
        entries = _entry_points(
            self.masakari, "masakari.task_flow.tasks"
        )
        self.assertEqual(
            "masakari.engine.drivers.taskflow.powerops:IronicFenceTask",
            entries.get("ironic_fence"),
            "Masakari must expose the ironic_fence TaskFlow entry point",
        )

        template = _read(
            self.kolla,
            "ansible/roles/masakari/templates/masakari.conf.j2",
        )

        for variable in (
                "host_auto_failure_recovery_tasks",
                "host_rh_failure_recovery_tasks"):
            self.assertEqual(
                EMERGENCY_TASK_ORDER,
                _quoted_task_order(template, variable),
                (
                    "{} must fence before instance preparation and "
                    "evacuation"
                ).format(variable),
            )

    def test_masakari_fence_proves_stable_power_off_before_return(self):
        source, module = _python_module(
            self.masakari, "masakari/powerops/ironic.py"
        )
        method = _class_method(module, "IronicPowerClient", "fence")
        body = ast.get_source_segment(source, method)

        _ordered(
            body,
            (
                "set_node_power_state",
                'node, "power off", wait=False',
                "stable = 0",
                "stable += 1",
                "stable >= stable_observations",
                "return _result(node)",
            ),
            "Ironic fencing",
        )
        self.assertIn(
            "node.target_power_state in (None, \"power off\")",
            source,
            "stable-off proof must reject a conflicting Ironic target",
        )
        self.assertIn(
            "not node.last_error",
            source,
            "stable-off proof must reject Ironic errors",
        )

    def test_mistral_actions_and_workflows_match_kolla_catalogue(self):
        entries = _entry_points(self.mistral, "mistral.actions")
        actual_actions = {
            name: entries.get(name) for name in ACTION_TARGETS
        }
        self.assertEqual(
            ACTION_TARGETS,
            actual_actions,
            "Mistral must register all five composite PowerOps actions",
        )

        workbook = _read(self.mistral, "etc/mistral/power_ops.yaml")
        self.assertEqual(
            WORKFLOW_NAMES,
            set(_mapping_child_keys(workbook, "workflows", 0)),
            "the operator workbook must expose exactly four workflows",
        )
        custom_references = {
            match.group(1)
            for match in re.finditer(
                r"(?m)^\s+action:\s+(powerops\.[A-Za-z0-9_.-]+)\s*$",
                workbook,
            )
        }
        self.assertEqual(
            set(ACTION_TARGETS),
            custom_references,
            "workbook action references must match Mistral entry points",
        )

        registration = _read(
            self.kolla, "ansible/roles/mistral/tasks/powerops.yml"
        )

        for name in ACTION_TARGETS:
            self.assertIn(
                name,
                registration,
                "Kolla does not validate Mistral action {}".format(name),
            )

        for name in WORKFLOW_NAMES:
            qualified = "power_ops." + name
            self.assertIn(
                qualified,
                registration,
                "Kolla does not validate workflow {}".format(qualified),
            )

    def test_kolla_deploys_the_exact_mistral_workbook_bytes(self):
        self.assertEqual(
            _read_bytes(self.mistral, "etc/mistral/power_ops.yaml"),
            _read_bytes(
                self.kolla,
                "ansible/roles/mistral/files/power_ops.yaml",
            ),
            "Kolla workbook copy must be byte-identical to Mistral source",
        )

    def test_lock_namespaces_are_shared_and_global_is_masakari_only(self):
        masakari_coord = _read(
            self.masakari, "masakari/powerops/coordination.py"
        )
        mistral_coord = _read(
            self.mistral,
            "mistral/actions/powerops/coordination.py",
        )

        for source_name, source in (
                ("Masakari", masakari_coord),
                ("Mistral", mistral_coord)):
            self.assertIn(
                "powerops/host/{}",
                source,
                "{} must use the shared per-host lock namespace".format(
                    source_name
                ),
            )

        self.assertIn(
            'GLOBAL_EVACUATION_LOCK = "powerops/evacuation/global"',
            masakari_coord,
            "Masakari must define the cluster-wide evacuation lock",
        )

        mistral_powerops = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(
                (self.mistral / "mistral/actions/powerops").glob("*.py")
            )
        )
        self.assertNotIn(
            "powerops/evacuation/global",
            mistral_powerops,
            "planned Mistral actions must not own the emergency global lock",
        )

    def test_host_locks_use_target_host_and_enclose_mutations(self):
        _, masakari_module = _python_module(
            self.masakari,
            "masakari/engine/drivers/taskflow/driver.py",
        )
        execute = _class_method(
            masakari_module, "TaskFlowDriver", "execute_host_failure"
        )
        masakari_locks = []

        for node in ast.walk(execute):
            if not isinstance(node, ast.With):
                continue

            for item in node.items:
                context = item.context_expr

                if (
                        isinstance(context, ast.Call)
                        and ast.unparse(context.func) == "coord.lock"):
                    masakari_locks.append((node, context))

        self.assertEqual(
            1,
            len(masakari_locks),
            "Masakari host recovery must own exactly one per-host lock",
        )
        masakari_with, masakari_lock = masakari_locks[0]
        self.assertEqual(
            "powerops_coordination.host_lock_name(host_name)",
            ast.unparse(masakari_lock.args[0]),
            "Masakari must derive its lock from the recovered host_name",
        )
        self.assertEqual(
            "CONF.powerops.host_lock_timeout",
            ast.unparse(masakari_lock.args[1]),
        )
        dispatches = [
            call for call in ast.walk(masakari_with)
            if isinstance(call, ast.Call)
            and ast.unparse(call.func) == "self._dispatch_host_failure"
        ]
        self.assertEqual(
            1,
            len(dispatches),
            "Masakari host lock must enclose the recovery dispatch",
        )
        self.assertEqual("host_name", ast.unparse(dispatches[0].args[1]))
        self.assertEqual("coord", ast.unparse(dispatches[0].args[4]))

        _, mistral_module = _python_module(
            self.mistral, "mistral/actions/powerops/base.py"
        )
        validate = _class_method(
            mistral_module, "PowerOpsAction", "_validate_inputs"
        )
        normalized_hosts = [
            call for call in ast.walk(validate)
            if isinstance(call, ast.Call)
            and ast.unparse(call.func) == "coordination.host_lock_name"
        ]
        self.assertEqual(1, len(normalized_hosts))
        self.assertEqual(
            "self.host",
            ast.unparse(normalized_hosts[0].args[0]),
            "Mistral must validate the same self.host used for locking",
        )

        run_locked = _class_method(
            mistral_module, "PowerOpsAction", "_run_locked"
        )
        mistral_locks = []

        for node in ast.walk(run_locked):
            if not isinstance(node, ast.With):
                continue

            for item in node.items:
                context = item.context_expr

                if (
                        isinstance(context, ast.Call)
                        and ast.unparse(context.func) == (
                            "coordinator.lock_host"
                        )):
                    mistral_locks.append((node, context))

        self.assertEqual(
            1,
            len(mistral_locks),
            "Mistral planned mutation must own exactly one host lock",
        )
        mistral_with, mistral_lock = mistral_locks[0]
        self.assertEqual(
            ["self.host"],
            [ast.unparse(argument) for argument in mistral_lock.args],
            "Mistral must lock the exact action target host",
        )
        enclosed_calls = {
            ast.unparse(call.func)
            for call in ast.walk(mistral_with)
            if isinstance(call, ast.Call)
        }

        for required_call in (
                "clients.CloudClients",
                "operation",
                "self._fail_safe"):
            method_calls = [
                call for call in ast.walk(run_locked)
                if isinstance(call, ast.Call)
                and ast.unparse(call.func) == required_call
            ]
            locked_calls = [
                call for call in ast.walk(mistral_with)
                if isinstance(call, ast.Call)
                and ast.unparse(call.func) == required_call
            ]
            self.assertEqual(
                1,
                len(method_calls),
                "Mistral state machine must call {} exactly once".format(
                    required_call
                ),
            )
            self.assertEqual(
                method_calls,
                locked_calls,
                "all {} calls must remain inside the host lock".format(
                    required_call
                ),
            )
            self.assertIn(
                required_call,
                enclosed_calls,
                "Mistral host lock must enclose {}".format(required_call),
            )

    def test_planned_policies_exclude_evacuation(self):
        _, module = _python_module(
            self.mistral, "mistral/actions/powerops/clients.py"
        )
        self.assertEqual(
            {"require_empty", "live_migrate", "stop"},
            _assignment_literal(module, "_INSTANCE_POLICIES"),
            "planned instance policies must be the three approved policies",
        )

        entries = _entry_points(self.mistral, "mistral.actions")
        workbook = _read(self.mistral, "etc/mistral/power_ops.yaml")
        self.assertFalse(
            any(
                "evacuat" in name.lower()
                for name in entries
                if name.startswith("powerops.")
            ),
            "Mistral must not expose a planned evacuation action",
        )
        self.assertNotIn(
            "evacuat",
            workbook.lower(),
            "Mistral workbook must not expose planned evacuation",
        )

    def test_privileged_actions_require_both_exact_allowlists(self):
        _, module = _python_module(
            self.mistral, "mistral/actions/powerops/base.py"
        )
        method = _class_method(module, "PowerOpsAction", "_authorize")
        checks = [
            node for node in ast.walk(method)
            if isinstance(node, ast.If)
        ]
        self.assertEqual(
            1,
            len(checks),
            "PowerOps authorization must have one fail-closed decision",
        )
        condition = checks[0].test
        self.assertIsInstance(
            condition,
            ast.BoolOp,
            "project and user checks must share one authorization decision",
        )
        self.assertIsInstance(
            condition.op,
            ast.Or,
            "either missing exact membership must deny the caller",
        )
        self.assertEqual(2, len(condition.values))

        expected = {
            "security.project_name not in "
            "CONF.powerops.allowed_project_names",
            "security.user_name not in CONF.powerops.allowed_user_names",
        }
        actual = {ast.unparse(value) for value in condition.values}
        self.assertEqual(
            expected,
            actual,
            "empty or non-matching project/user allowlists must deny all",
        )

        template = _read(
            self.kolla,
            "ansible/roles/mistral/templates/mistral.conf.j2",
        )
        self.assertIn(
            "allowed_project_names = "
            "{{ powerops_allowed_project_names | join(',') }}",
            template,
        )
        self.assertIn(
            "allowed_user_names = "
            "{{ powerops_allowed_user_names | join(',') }}",
            template,
        )

        for role in ("masakari", "mistral"):
            precheck = _read(
                self.kolla,
                "ansible/roles/{}/tasks/precheck.yml".format(role),
            )

            for variable in (
                    "powerops_allowed_project_names",
                    "powerops_allowed_user_names"):
                self.assertIn(
                    variable + " | length > 0",
                    precheck,
                    "{} precheck must reject an empty {}".format(
                        role, variable
                    ),
                )

    def test_enabled_powerops_coordination_is_etcd_and_not_redis(self):
        for tree, relative_path, component in (
                (
                    self.masakari,
                    "masakari/powerops/coordination.py",
                    "Masakari",
                ),
                (
                    self.mistral,
                    "mistral/actions/powerops/coordination.py",
                    "Mistral",
                )):
            source = _read(tree, relative_path)
            constants = {
                node.value
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
            }
            self.assertTrue(
                {"etcd3+http", "etcd3+https"}.issubset(constants),
                "{} must accept etcd3 HTTP(S) coordination".format(
                    component
                ),
            )
            self.assertNotIn(
                "redis",
                source.lower(),
                "{} PowerOps coordination code must not select Redis".format(
                    component
                ),
            )

        globals_source = _read(self.kolla, "ansible/group_vars/all.yml")
        coordination = _top_level_value_block(
            globals_source, "powerops_coordination_url"
        )
        self.assertIn("etcd3+", coordination)
        self.assertNotIn(
            "redis",
            coordination.lower(),
            "PowerOps coordination default must be etcd-only",
        )

        masakari_template = _read(
            self.kolla,
            "ansible/roles/masakari/templates/masakari.conf.j2",
        )
        enabled_start = masakari_template.index(
            "{% if enable_powerops | bool %}"
        )
        enabled_end = masakari_template.index(
            "{% elif service_name == 'masakari-api' %}",
            enabled_start,
        )
        enabled_branch = masakari_template[enabled_start:enabled_end]
        self.assertIn(
            "backend_url = {{ powerops_coordination_url }}",
            enabled_branch,
        )
        self.assertNotIn("redis", enabled_branch.lower())

        mistral_template = _read(
            self.kolla,
            "ansible/roles/mistral/templates/mistral.conf.j2",
        )
        conditional = re.search(
            r"backend_url\s*=\s*\{% if enable_powerops \| bool %\}"
            r"\{\{ powerops_coordination_url \}\}"
            r"\{% else %\}\{\{ redis_connection_string \}\}"
            r"\{% endif %\}",
            mistral_template,
        )
        self.assertIsNotNone(
            conditional,
            "Mistral must select etcd in the enabled PowerOps branch",
        )

    def test_kolla_deploy_and_reconfigure_are_reconcile_only(self):
        role_sources = []
        powerops_sources = {}

        for role in ("masakari", "mistral"):
            deploy = _read(
                self.kolla,
                "ansible/roles/{}/tasks/deploy.yml".format(role),
            )
            reconfigure = _read(
                self.kolla,
                "ansible/roles/{}/tasks/reconfigure.yml".format(role),
            )
            powerops = _read(
                self.kolla,
                "ansible/roles/{}/tasks/powerops.yml".format(role),
            )
            self.assertLess(
                deploy.index("meta: flush_handlers"),
                deploy.index("import_tasks: powerops.yml"),
                "{} must reconcile only after service handlers flush".format(
                    role
                ),
            )
            self.assertIn("import_tasks: deploy.yml", reconfigure)
            role_sources.extend((deploy, reconfigure, powerops))
            powerops_sources[role] = powerops

        tasks = "\n".join(role_sources).lower()

        for forbidden in (
                "/executions",
                "/action-executions",
                "/states/power",
                "baremetal node power",
                "server evacuate",
                "server migrate",
                "server start",
                "server stop",
                "evacuate_instance",
                "live_migrate_server",
                "set_node_power_state",
                "start_server(",
                "stop_server("):
            self.assertNotIn(
                forbidden,
                tasks,
                (
                    "deploy/reconfigure must not perform runtime mutation: "
                    "{}"
                ).format(forbidden),
            )

        for forbidden_cli in (
                r"\bopenstack\s+workflow\s+execution\s+create\b",
                r"\bmistral\s+execution(?:-|\s+)create\b",
                r"\bworkflow(?:-|_)execution(?:-|_)create\b",
                r"\bexecution(?:-|_)create\b"):
            self.assertNotRegex(
                tasks,
                forbidden_cli,
                "deploy/reconfigure must never create a workflow execution",
            )

        allowed_commands = {
            "masakari": {
                "Verify PowerOps Masakari fencing entry point": (
                    "masakari_engine python -c",
                    "masakari.task_flow.tasks",
                    "ironic_fence",
                ),
            },
            "mistral": {
                "Verify PowerOps Mistral action entry points": (
                    "{{ item.container }} python -c",
                    "mistral.actions",
                ),
                "Populate Mistral action definitions": (
                    "mistral-db-manage --config-file "
                    "/etc/mistral/mistral.conf populate",
                ),
            },
        }
        allowed_uris = {
            "masakari": {},
            "mistral": {
                "Authenticate PowerOps workbook reconciliation": (
                    "method: POST",
                    "/v3/auth/tokens",
                ),
                "List matching PowerOps workbooks": (
                    "method: GET",
                    "/workbooks?name=power_ops&namespace=",
                ),
                "Create PowerOps workbook": (
                    "method: POST",
                    "/workbooks?scope=public",
                ),
                "Update changed PowerOps workbook": (
                    "method: PUT",
                    "/workbooks?scope=public",
                ),
                "Read registered PowerOps actions": (
                    "method: GET",
                    "/actions/{{ item }}",
                ),
                "Read registered PowerOps workflows": (
                    "method: GET",
                    "/workflows?name={{ item }}&namespace=",
                ),
            },
        }

        for role, source in powerops_sources.items():
            named_tasks = _ansible_tasks(source)
            self.assertEqual(
                len(allowed_commands[role]),
                source.count("ansible.builtin.command:"),
                "{} PowerOps tasks contain an unnamed command".format(role),
            )

            for forbidden_module in (
                    "ansible.legacy.command:",
                    "ansible.builtin.shell:",
                    "ansible.legacy.shell:",
                    "ansible.builtin.raw:",
                    "ansible.builtin.script:"):
                self.assertNotIn(forbidden_module, source)

            command_tasks = {
                name: block for name, block in named_tasks.items()
                if any(
                    module in block
                    for module in (
                        "ansible.builtin.command:",
                        "ansible.legacy.command:",
                        "ansible.builtin.shell:",
                        "ansible.legacy.shell:",
                        "ansible.builtin.raw:",
                        "ansible.builtin.script:",
                    )
                )
            }
            self.assertEqual(
                set(allowed_commands[role]),
                set(command_tasks),
                "{} PowerOps tasks contain an unapproved command".format(
                    role
                ),
            )

            for name, required_fragments in allowed_commands[role].items():
                block = command_tasks[name]
                self.assertIn("ansible.builtin.command:", block)

                for fragment in required_fragments:
                    self.assertIn(fragment, block)

            uri_tasks = {
                name: block for name, block in named_tasks.items()
                if "ansible.builtin.uri:" in block
            }
            self.assertEqual(
                len(allowed_uris[role]),
                source.count("ansible.builtin.uri:"),
                "{} PowerOps tasks contain an unnamed URI call".format(role),
            )
            self.assertEqual(
                set(allowed_uris[role]),
                set(uri_tasks),
                "{} PowerOps tasks contain an unapproved URI call".format(
                    role
                ),
            )

            for name, required_fragments in allowed_uris[role].items():
                block = uri_tasks[name]

                for fragment in required_fragments:
                    self.assertIn(fragment, block)

        self.assertIn(
            "mistral-db-manage --config-file "
            "/etc/mistral/mistral.conf populate",
            tasks,
            "Kolla deploy must reconcile Mistral action definitions",
        )

    def test_only_required_services_use_patched_images(self):
        masakari_defaults = _read(
            self.kolla, "ansible/roles/masakari/defaults/main.yml"
        )
        masakari_api = _key_block(
            masakari_defaults, "masakari-api", 2
        )
        masakari_engine = _key_block(
            masakari_defaults, "masakari-engine", 2
        )
        self.assertIn("powerops_masakari_engine_image", masakari_engine)
        self.assertIn("if enable_powerops | bool", masakari_engine)
        self.assertNotIn("powerops_masakari", masakari_api)

        mistral_defaults = _read(
            self.kolla, "ansible/roles/mistral/defaults/main.yml"
        )

        for service, variable in (
                ("mistral-api", "powerops_mistral_api_image"),
                ("mistral-engine", "powerops_mistral_engine_image"),
                ("mistral-executor", "powerops_mistral_executor_image")):
            block = _key_block(mistral_defaults, service, 2)
            self.assertIn(
                variable,
                block,
                "{} must use its patched PowerOps image".format(service),
            )
            self.assertIn("if enable_powerops | bool", block)

        event_engine = _key_block(
            mistral_defaults, "mistral-event-engine", 2
        )
        self.assertNotIn(
            "powerops_mistral",
            event_engine,
            "Mistral Event Engine must retain its vanilla image",
        )

        registration = _read(
            self.kolla, "ansible/roles/mistral/tasks/powerops.yml"
        )

        for container, group in (
                ("mistral_api", "mistral-api"),
                ("mistral_engine", "mistral-engine"),
                ("mistral_executor", "mistral-executor")):
            self.assertRegex(
                registration,
                r"- container: {}\s+group: {}".format(
                    re.escape(container), re.escape(group)
                ),
                "Kolla must validate entry points in {}".format(container),
            )

    def test_controller_api_calls_use_kolla_admin_ca(self):
        tasks = _read(
            self.kolla, "ansible/roles/mistral/tasks/powerops.yml"
        )
        self.assertIn(
            'path: "{{ kolla_admin_openrc_cacert }}"',
            tasks,
            "Kolla must preflight the controller-side CA path",
        )
        self.assertIn("powerops_controller_ca.stat.readable", tasks)
        self.assertNotIn(
            "openstack_cacert",
            tasks,
            "controller URI calls must not use a container-only CA path",
        )

        ca_paths = tasks.count("ca_path:")
        controller_ca_paths = len(re.findall(
            r"ca_path:\s*>-\s*\n\s*\{\{ kolla_admin_openrc_cacert",
            tasks,
        ))
        self.assertGreater(ca_paths, 0)
        self.assertEqual(
            ca_paths,
            controller_ca_paths,
            "every controller URI call must use kolla_admin_openrc_cacert",
        )

    def test_kolla_workbook_reconciliation_fails_closed_on_collision(self):
        source = _read(
            self.kolla, "ansible/roles/mistral/tasks/powerops.yml"
        )
        tasks = _ansible_tasks(source)

        listing = tasks.get("List matching PowerOps workbooks", "")
        self.assertIn("/workbooks?name=power_ops&namespace=", listing)
        self.assertNotIn("limit=", listing)

        matching = tasks.get("Store matching PowerOps workbooks", "")
        self.assertIn("selectattr('name', 'equalto', 'power_ops')", matching)
        self.assertIn("selectattr('namespace', 'equalto', '')", matching)

        ownership = tasks.get("Validate PowerOps workbook ownership", "")
        self.assertIn("powerops_matching_workbooks | length <= 1", ownership)
        self.assertIn(
            "powerops_matching_workbooks[0].project_id ==",
            ownership,
        )
        self.assertIn("powerops_keystone_project_id", ownership)
        self.assertIn("ambiguous or foreign", ownership)

        create = tasks.get("Create PowerOps workbook", "")
        self.assertIn("powerops_matching_workbooks | length == 0", create)

        update = tasks.get("Update changed PowerOps workbook", "")
        self.assertIn("powerops_matching_workbooks | length == 1", update)
        self.assertIn(
            "powerops_matching_workbooks[0].project_id ==",
            update,
        )
        self.assertIn("powerops_keystone_project_id", update)
        self.assertIn("method: PUT", update)
        self.assertIn("Content-Type: text/plain", update)
        self.assertIn(
            "rstrip=False",
            tasks.get("Load PowerOps workbook definition", ""),
            "workbook reconciliation must preserve exact source bytes",
        )

    def test_mistral_workbook_update_is_atomically_owner_scoped(self):
        source, module = _python_module(
            self.mistral, "mistral/db/v2/sqlalchemy/api.py"
        )
        function = _function(module, "update_workbook")
        body = ast.get_source_segment(source, function)
        decorators = {ast.unparse(item) for item in function.decorator_list}
        self.assertIn(
            "b.session_aware()",
            decorators,
            "owner lookup and workbook update must share one DB session",
        )

        required_predicates = (
            "models.Workbook.project_id == security.get_project_id()",
            "models.Workbook.name == name",
            "models.Workbook.namespace == namespace",
        )

        for predicate in required_predicates:
            self.assertIn(
                predicate,
                body,
                "Mistral workbook update is missing predicate {}".format(
                    predicate
                ),
            )

        self.assertIn("model_query(models.Workbook, session=session)", body)
        self.assertNotIn(
            "_get_db_object_by_name",
            body,
            "workbook update must not use a cross-project name-only lookup",
        )
        _ordered(
            body,
            (
                "models.Workbook.project_id ==",
                ").first()",
                "if not wb:",
                "wb.update(values.copy())",
            ),
            "owner-scoped Mistral workbook update",
        )

    def test_mistral_workbook_children_are_owner_scoped_end_to_end(self):
        _, service_module = _python_module(
            self.mistral, "mistral/services/workbooks.py"
        )
        _, facade_module = _python_module(
            self.mistral, "mistral/db/v2/api.py"
        )
        _, backend_module = _python_module(
            self.mistral, "mistral/db/v2/sqlalchemy/api.py"
        )

        child_contracts = (
            (
                "_create_or_update_actions",
                "create_or_update_action_definition",
                "models.ActionDefinition",
            ),
            (
                "_create_or_update_workflows",
                "create_or_update_workflow_definition",
                "models.WorkflowDefinition",
            ),
        )

        for service_name, operation_name, model_name in child_contracts:
            with self.subTest(child=operation_name):
                service = _function(service_module, service_name)
                service_calls = [
                    node for node in ast.walk(service)
                    if isinstance(node, ast.Call)
                    and ast.unparse(node.func) == (
                        "db_api_v2." + operation_name
                    )
                ]
                self.assertEqual(
                    1,
                    len(service_calls),
                    "workbook service must issue exactly one {} call".format(
                        operation_name
                    ),
                )
                service_project_args = [
                    keyword.value
                    for keyword in service_calls[0].keywords
                    if keyword.arg == "project_id"
                ]
                self.assertEqual(
                    ["wb_db.project_id"],
                    [ast.unparse(value) for value in service_project_args],
                    (
                        "workbook service must pass the persisted workbook "
                        "owner to {}"
                    ).format(operation_name),
                )

                facade = _function(facade_module, operation_name)
                facade_parameters = [
                    argument.arg
                    for argument in (
                        facade.args.posonlyargs + facade.args.args
                    )
                ]
                self.assertIn(
                    "project_id",
                    facade_parameters,
                    "DB facade must accept the workbook owner",
                )
                facade_calls = [
                    node for node in ast.walk(facade)
                    if isinstance(node, ast.Call)
                    and ast.unparse(node.func) == "IMPL." + operation_name
                ]
                self.assertEqual(
                    1,
                    len(facade_calls),
                    "DB facade must issue exactly one backend call",
                )
                facade_project_args = [
                    keyword.value
                    for keyword in facade_calls[0].keywords
                    if keyword.arg == "project_id"
                ]
                self.assertEqual(
                    ["project_id"],
                    [ast.unparse(value) for value in facade_project_args],
                    "DB facade must preserve the explicit owner argument",
                )

                backend = _function(backend_module, operation_name)
                backend_parameters = [
                    argument.arg
                    for argument in (
                        backend.args.posonlyargs + backend.args.args
                    )
                ]
                self.assertIn("project_id", backend_parameters)
                self.assertIn("session", backend_parameters)
                self.assertIn(
                    "b.session_aware()",
                    {ast.unparse(item) for item in backend.decorator_list},
                    "owner lookup must use the transaction session",
                )
                owner_branches = [
                    node for node in backend.body
                    if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "project_id is not None"
                ]
                self.assertEqual(
                    1,
                    len(owner_branches),
                    "explicit owner handling must have one guarded branch",
                )
                owner_branch = owner_branches[0]
                validation_calls = [
                    node for node in ast.walk(owner_branch)
                    if isinstance(node, ast.Call)
                    and ast.unparse(node.func) == "_check_request_project"
                ]
                self.assertEqual(
                    1,
                    len(validation_calls),
                    "backend must validate the supplied owner exactly once",
                )
                self.assertEqual(
                    ["project_id"],
                    [
                        ast.unparse(argument)
                        for argument in validation_calls[0].args
                    ],
                )
                lookup_calls = [
                    node for node in ast.walk(owner_branch)
                    if isinstance(node, ast.Call)
                    and ast.unparse(node.func) == (
                        "_get_db_object_by_name_namespace_and_project"
                    )
                ]
                self.assertEqual(
                    1,
                    len(lookup_calls),
                    (
                        "{} must use the exact owner-aware lookup"
                    ).format(operation_name),
                )
                self.assertEqual(
                    [
                        model_name,
                        "name",
                        "namespace",
                        "project_id",
                        "session",
                    ],
                    [
                        ast.unparse(argument)
                        for argument in lookup_calls[0].args
                    ],
                    (
                        "{} must bind model, key, owner and the same session"
                    ).format(operation_name),
                )
                self.assertLess(
                    validation_calls[0].lineno,
                    lookup_calls[0].lineno,
                    "request owner validation must precede the DB lookup",
                )

        checker = _function(backend_module, "_check_request_project")
        checker_branches = [
            node for node in checker.body
            if isinstance(node, ast.If)
        ]
        self.assertEqual(1, len(checker_branches))
        self.assertEqual(
            "project_id != security.get_project_id()",
            ast.unparse(checker_branches[0].test),
            "the supplied owner must equal the request project",
        )
        checker_raises = [
            node for node in checker_branches[0].body
            if isinstance(node, ast.Raise)
        ]
        self.assertEqual(
            1,
            len(checker_raises),
            "a mismatched request project must be rejected",
        )
        self.assertEqual(
            "exc.NotAllowedException",
            ast.unparse(checker_raises[0].exc.func),
        )

        lookup = _function(
            backend_module,
            "_get_db_object_by_name_namespace_and_project",
        )
        lookup_parameters = [
            argument.arg
            for argument in lookup.args.posonlyargs + lookup.args.args
        ]
        self.assertEqual(
            ["model", "name", "namespace", "project_id", "session"],
            lookup_parameters,
        )
        returns = [
            node for node in lookup.body
            if isinstance(node, ast.Return)
        ]
        self.assertEqual(1, len(returns))
        lookup_calls = [
            node for node in ast.walk(lookup)
            if isinstance(node, ast.Call)
        ]
        self.assertFalse(
            any(
                ast.unparse(node.func) == "sa.or_"
                for node in lookup_calls
            ),
            "owner lookup must not include a public-aware alternative",
        )
        filter_calls = [
            node for node in lookup_calls
            if isinstance(node.func, ast.Attribute)
            and node.func.attr == "filter"
        ]
        self.assertEqual(
            1,
            len(filter_calls),
            "owner lookup must contain exactly one filter",
        )

        first_call = returns[0].value
        self.assertIsInstance(first_call, ast.Call)
        self.assertEqual([], first_call.args)
        self.assertEqual([], first_call.keywords)
        self.assertIsInstance(first_call.func, ast.Attribute)
        self.assertEqual("first", first_call.func.attr)

        direct_filter = first_call.func.value
        self.assertIs(
            filter_calls[0],
            direct_filter,
            "the exact owner filter must be the direct source of first()",
        )
        self.assertEqual([], direct_filter.keywords)
        self.assertEqual(1, len(direct_filter.args))
        self.assertIsInstance(direct_filter.func, ast.Attribute)
        self.assertEqual("filter", direct_filter.func.attr)

        query_call = direct_filter.func.value
        self.assertIsInstance(query_call, ast.Call)
        self.assertEqual(
            "b.model_query",
            ast.unparse(query_call.func),
            "owner filter must directly follow b.model_query",
        )
        self.assertEqual(
            ["model"],
            [ast.unparse(argument) for argument in query_call.args],
        )
        query_session_args = [
            keyword.value
            for keyword in query_call.keywords
            if keyword.arg == "session"
        ]
        self.assertEqual(
            ["session"],
            [ast.unparse(value) for value in query_session_args],
            "owner lookup must query through its supplied session",
        )
        self.assertEqual(
            ["session"],
            [keyword.arg for keyword in query_call.keywords],
            "model query must have no alternate scope arguments",
        )

        conjunction = direct_filter.args[0]
        self.assertIsInstance(conjunction, ast.Call)
        self.assertEqual(
            "sa.and_",
            ast.unparse(conjunction.func),
            "the direct filter predicate must be the owner conjunction",
        )
        self.assertEqual([], conjunction.keywords)
        self.assertEqual(3, len(conjunction.args))
        self.assertTrue(
            all(isinstance(argument, ast.Compare)
                for argument in conjunction.args),
            "owner predicates must be direct comparisons",
        )
        self.assertEqual(
            {
                "model.project_id == project_id",
                "model.name == name",
                "model.namespace == namespace",
            },
            {ast.unparse(argument) for argument in conjunction.args},
            (
                "owner lookup must use only exact project, name and "
                "namespace predicates"
            ),
        )

    def test_emergency_evacuation_is_deterministic_serial_and_paced(self):
        source, module = _python_module(
            self.masakari,
            "masakari/engine/drivers/taskflow/host_failure.py",
        )
        method = _class_method(
            module, "EvacuateInstancesTask", "execute"
        )
        sort_assignments = [
            node for node in ast.walk(method)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and ast.unparse(node.targets[0]) == "all_vmoves"
            and isinstance(node.value, ast.Call)
            and ast.unparse(node.value.func) == "sorted"
            and ast.unparse(node.value) == (
                "sorted(all_vmoves, key=lambda item: item.instance_uuid)"
            )
        ]
        self.assertEqual(
            1,
            len(sort_assignments),
            "emergency VM moves must be sorted by instance UUID",
        )

        global_withs = []

        for node in ast.walk(method):
            if not isinstance(node, ast.With):
                continue

            if any(
                    isinstance(item.context_expr, ast.Call)
                    and "GLOBAL_EVACUATION_LOCK" in ast.unparse(
                        item.context_expr
                    )
                    for item in node.items):
                global_withs.append(node)

        self.assertEqual(
            1,
            len(global_withs),
            "each emergency VM evacuation must use one global lock scope",
        )
        global_with = global_withs[0]
        parents = {
            child: parent
            for parent in ast.walk(method)
            for child in ast.iter_child_nodes(parent)
        }
        vmove_loop = parents.get(global_with)
        self.assertIsInstance(
            vmove_loop,
            ast.For,
            "global evacuation lock must be acquired inside the VM loop",
        )
        self.assertEqual("vmove", ast.unparse(vmove_loop.target))
        self.assertEqual("all_vmoves", ast.unparse(vmove_loop.iter))
        enabled_branch = parents.get(vmove_loop)
        self.assertIsInstance(
            enabled_branch,
            ast.If,
            "per-VM global lock loop must be in the PowerOps-enabled branch",
        )
        self.assertEqual(
            "CONF.powerops.enabled",
            ast.unparse(enabled_branch.test),
        )

        lock_call = global_with.items[0].context_expr
        self.assertEqual(
            "powerops_coordination.GLOBAL_EVACUATION_LOCK",
            ast.unparse(lock_call.args[0]),
        )
        self.assertEqual(
            "CONF.powerops.evacuation_lock_timeout",
            ast.unparse(lock_call.args[1]),
        )
        protected = ast.get_source_segment(source, global_with)
        _ordered(
            protected,
            (
                "self._evacuate_and_confirm(",
                "if vmove.status == fields.VMoveStatus.FAILED:",
                "break",
                "eventlet.sleep(CONF.powerops.evacuation_interval)",
            ),
            "global evacuation critical section",
        )
        self.assertNotIn(
            "spawn_n",
            protected,
            "PowerOps emergency evacuation must not spawn concurrent VMs",
        )
        evacuations = [
            call for call in ast.walk(global_with)
            if isinstance(call, ast.Call)
            and ast.unparse(call.func) == "self._evacuate_and_confirm"
        ]
        pacing_calls = [
            call for call in ast.walk(global_with)
            if isinstance(call, ast.Call)
            and ast.unparse(call.func) == "eventlet.sleep"
        ]
        failure_breaks = [
            node for node in ast.walk(global_with)
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == (
                "vmove.status == fields.VMoveStatus.FAILED"
            )
            and any(isinstance(child, ast.Break) for child in node.body)
        ]
        self.assertEqual(1, len(evacuations))
        self.assertEqual(1, len(pacing_calls))
        self.assertEqual(1, len(failure_breaks))
        self.assertLess(evacuations[0].lineno, pacing_calls[0].lineno)

    def test_planned_vm_operations_are_deterministic_serial_and_paced(self):
        source, module = _python_module(
            self.mistral, "mistral/actions/powerops/clients.py"
        )
        instances = _class_method(
            module, "CloudClients", "instances_on_host"
        )
        self.assertIn(
            "return sorted(servers, key=lambda server: server.id)",
            ast.unparse(instances),
            "planned stop/live-migration order must be deterministic",
        )

        start = _class_method(module, "CloudClients", "start_instances")
        start_source = ast.get_source_segment(source, start)
        _ordered(
            start_source,
            (
                "for server_id in sorted(instance_ids)",
                "for server in selected:",
                "self.connection.compute.start_server(server)",
                "self._wait_until(",
                "self._pace_instances()",
            ),
            "planned VM restart",
        )
        self.assertNotIn(
            "GreenPool",
            start_source,
            "planned restart must not fan out VM starts",
        )
        restart_loops = [
            node for node in ast.walk(start)
            if isinstance(node, ast.For)
            and ast.unparse(node.target) == "server"
            and ast.unparse(node.iter) == "selected"
        ]
        self.assertEqual(
            1,
            len(restart_loops),
            "planned restart must have one sequential selected-VM loop",
        )
        restart_loop = restart_loops[0]
        direct_calls = [
            statement.value
            for statement in restart_loop.body
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
        ]
        mutations = [
            call for call in direct_calls
            if ast.unparse(call.func) == "self._mutation"
            and "start_server(server)" in ast.unparse(call)
        ]
        waits = [
            call for call in direct_calls
            if ast.unparse(call.func) == "self._wait_until"
        ]
        pacing_calls = [
            call for call in direct_calls
            if ast.unparse(call.func) == "self._pace_instances"
        ]
        self.assertEqual(1, len(mutations))
        self.assertEqual(1, len(waits))
        self.assertEqual(1, len(pacing_calls))
        self.assertIn("server.id", ast.unparse(waits[0]))
        self.assertIn("current.status == 'ACTIVE'", ast.unparse(waits[0]))
        self.assertLess(mutations[0].lineno, waits[0].lineno)
        self.assertLess(waits[0].lineno, pacing_calls[0].lineno)

        pacing = _class_method(module, "CloudClients", "_pace_instances")
        self.assertIn(
            "CONF.powerops.instance_interval",
            ast.unparse(pacing),
            "planned VM operations must honor instance_interval",
        )

    def test_return_workflow_pauses_for_explicit_stale_domain_gate(self):
        workbook = _read(self.mistral, "etc/mistral/power_ops.yaml")
        return_workflow = _key_block(
            workbook, "power_on_and_return", 2
        )
        gate = _key_block(
            return_workflow, "operator_inspection_gate", 6
        )
        self.assertIn("action: std.noop", gate)
        self.assertIn(
            "pause-before: true",
            gate,
            "host return must pause before the operator inspection gate",
        )
        self.assertIn("on-success: return_to_service", gate)
        self.assertIn(
            "stale_domains_checked: "
            "<% env().get('stale_domains_checked', false) %>",
            return_workflow,
            "resumed workflow must pass the explicit stale-domain assertion",
        )

        source, module = _python_module(
            self.mistral,
            "mistral/actions/powerops/return_host.py",
        )
        validate = _class_method(
            module, "ReturnToServiceAction", "_validate_inputs"
        )
        body = ast.get_source_segment(source, validate)
        self.assertIn("self.stale_domains_checked is not True", body)
        self.assertIn("OperatorGateRequired", body)

    def test_emergency_failure_never_automatically_powers_on_host(self):
        source, module = _python_module(
            self.masakari,
            "masakari/engine/drivers/taskflow/powerops.py",
        )
        revert = _class_method(module, "IronicFenceTask", "revert")
        calls = {
            ast.unparse(node.func)
            for node in ast.walk(revert)
            if isinstance(node, ast.Call)
        }
        self.assertEqual(
            {"LOG.critical"},
            calls,
            "fence revert may log only; it must never power on the host",
        )

        _, ironic_module = _python_module(
            self.masakari, "masakari/powerops/ironic.py"
        )
        fence = _class_method(ironic_module, "IronicPowerClient", "fence")
        power_targets = []

        for node in ast.walk(fence):
            if not isinstance(node, ast.Call):
                continue

            if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "set_node_power_state"):
                if len(node.args) < 2:
                    raise AssertionError(
                        "Ironic fencing power mutation has no explicit target"
                    )

                power_targets.append(ast.literal_eval(node.args[1]))

        self.assertEqual(
            ["power off"],
            power_targets,
            "emergency fencing may request physical power off only",
        )


if __name__ == "__main__":
    unittest.main()
