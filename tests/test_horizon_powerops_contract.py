"""Source-only contract for the Horizon PowerOps integration.

The tests intentionally use only the Python standard library. They inspect
the reviewed component trees without importing OpenStack packages, opening a
socket, starting a container, or calling a service endpoint.
"""

import ast
import configparser
import hashlib
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]

WORKFLOWS = {
    'power_ops.host_inventory',
    'power_ops.host_power_status',
    'power_ops.planned_power_off',
    'power_ops.planned_reboot',
    'power_ops.power_on_and_return',
}
WORKFLOW_CONSTANTS = {
    'HOST_INVENTORY',
    'HOST_POWER_STATUS',
    'PLANNED_POWER_OFF',
    'PLANNED_REBOOT',
    'POWER_ON_AND_RETURN',
}
ACTIONS = {
    'powerops.host_inventory',
    'powerops.host_power_status',
    'powerops.planned_power_off',
    'powerops.planned_reboot',
    'powerops.power_on_for_inspection',
    'powerops.return_to_service',
}
INSTANCE_POLICIES = {'require_empty', 'live_migrate', 'stop'}
ROLE_NAMES = {'admin', 'powerops_operator'}
ALLOWLIST_VARIABLES = {
    'powerops_allowed_project_names',
    'powerops_allowed_user_names',
}
WSGI_PATCH = (
    ROOT / 'patches/kolla-ansible/'
    '0006-fix-load-Masakari-through-idempotent-WSGI-wrapper.patch'
)
WSGI_PATCH_SHA256 = (
    'b8e41f6ff7c8e54d0f14fdbe175b95d43d1d65ca542ec2d0f549fd0a98d0a27a'
)


def _required_tree(variable):
    value = os.environ.get(variable)
    if not value:
        raise AssertionError(
            '{} must name the source tree under test'.format(variable)
        )
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise AssertionError(
            '{} does not name a directory: {}'.format(variable, path)
        )
    return path


def _read(tree, relative):
    path = tree / relative
    if not path.is_file():
        raise AssertionError('required contract file is missing: {}'.format(
            path
        ))
    return path.read_text(encoding='utf-8')


def _module(tree, relative):
    source = _read(tree, relative)
    return source, ast.parse(source, filename=str(tree / relative))


def _literal_assignment(module, name):
    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
                isinstance(target, ast.Name) and target.id == name
                for target in targets):
            continue
        value = node.value
        if (isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == 'frozenset'
                and len(value.args) == 1):
            value = value.args[0]
        return ast.literal_eval(value)
    raise AssertionError('required assignment is missing: {}'.format(name))


def _class_method(module, class_name, method_name):
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if (isinstance(child, ast.FunctionDef)
                        and child.name == method_name):
                    return child
    raise AssertionError('required method is missing: {}.{}'.format(
        class_name, method_name
    ))


def _function(module, name):
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError('required function is missing: {}'.format(name))


def _entry_point_names(tree):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with (tree / 'setup.cfg').open(encoding='utf-8') as stream:
        parser.read_file(stream)
    lines = parser.get('entry_points', 'mistral.actions').splitlines()
    return {
        line.split('=', 1)[0].strip()
        for line in lines
        if line.strip().startswith('powerops.') and '=' in line
    }


def _workbook_names(workbook):
    names = set()
    inside = False
    for line in workbook.splitlines():
        if line == 'workflows:':
            inside = True
            continue
        if not inside:
            continue
        match = re.fullmatch(r'  ([a-z0-9_]+):', line)
        if match:
            names.add('power_ops.' + match.group(1))
        elif line and not line.startswith((' ', '#')):
            break
    return names


def _constant_values(module):
    values = {}
    for name in WORKFLOW_CONSTANTS:
        values[name] = _literal_assignment(module, name)
    return values


def _workflow_values_from_expression(expression, constants):
    if (isinstance(expression, ast.Attribute)
            and isinstance(expression.value, ast.Name)
            and expression.value.id == 'constants'):
        return {constants[expression.attr]}
    if isinstance(expression, ast.Subscript) and isinstance(
            expression.value, ast.Dict
    ):
        result = set()
        for value in expression.value.values:
            result.update(_workflow_values_from_expression(value, constants))
        return result
    raise AssertionError(
        'workflow create target is not closed: {}'.format(
            ast.unparse(expression)
        )
    )


class HorizonPowerOpsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.masakari = _required_tree('POWEROPS_MASAKARI_TREE')
        cls.mistral_lib = _required_tree('POWEROPS_MISTRAL_LIB_TREE')
        cls.mistral = _required_tree('POWEROPS_MISTRAL_TREE')
        cls.dashboard = _required_tree('POWEROPS_DASHBOARD_TREE')
        cls.kolla = _required_tree('POWEROPS_KOLLA_TREE')
        cls.kolla_ansible = _required_tree('POWEROPS_KOLLA_ANSIBLE_TREE')

    def test_exact_workflows_actions_and_instance_policies(self):
        _, dashboard_constants = _module(
            self.dashboard, 'poweropsdashboard/constants.py'
        )
        dashboard_workflows = _constant_values(dashboard_constants)
        self.assertEqual(WORKFLOWS, set(dashboard_workflows.values()))
        workflow_set = next(
            node.value for node in dashboard_constants.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == 'POWEROPS_WORKFLOWS'
                for target in node.targets
            )
        )
        self.assertEqual(
            WORKFLOW_CONSTANTS,
            {
                node.id for node in ast.walk(workflow_set)
                if isinstance(node, ast.Name)
                and node.id != 'frozenset'
            },
        )
        self.assertEqual(
            INSTANCE_POLICIES,
            set(_literal_assignment(dashboard_constants, 'INSTANCE_POLICIES')),
        )

        _, mistral_powerops = _module(
            self.mistral, 'mistral/services/powerops.py'
        )
        self.assertEqual(
            WORKFLOWS,
            set(_literal_assignment(
                mistral_powerops, 'POWEROPS_WORKFLOW_NAMES'
            )),
        )

        workbook = _read(self.mistral, 'etc/mistral/power_ops.yaml')
        self.assertEqual(WORKFLOWS, _workbook_names(workbook))
        self.assertEqual(
            ACTIONS,
            set(re.findall(
                r'(?m)^\s+action:\s+(powerops\.[A-Za-z0-9_.-]+)\s*$',
                workbook,
            )),
        )
        self.assertEqual(ACTIONS, _entry_point_names(self.mistral))

        registration = _read(
            self.kolla_ansible, 'ansible/roles/mistral/tasks/powerops.yml'
        )
        self.assertEqual(
            ACTIONS,
            set(re.findall(r"['\"](powerops\.[a-z0-9_]+)['\"]", registration)),
        )
        self.assertEqual(
            WORKFLOWS,
            set(re.findall(
                r"(?m)^\s+-\s+(power_ops\.[a-z0-9_]+)\s*$",
                registration,
            )),
        )

    def test_horizon_execution_create_targets_are_closed(self):
        _, constants_module = _module(
            self.dashboard, 'poweropsdashboard/constants.py'
        )
        constants = _constant_values(constants_module)
        _, api_module = _module(self.dashboard, 'poweropsdashboard/api.py')
        client_class = next(
            node for node in api_module.body
            if isinstance(node, ast.ClassDef)
            and node.name == 'MistralPowerOpsClient'
        )
        created = set()
        create_calls = 0

        for method in client_class.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            assignments = {
                target.id: node.value
                for node in ast.walk(method)
                if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            for call in ast.walk(method):
                if (not isinstance(call, ast.Call)
                        or ast.unparse(call.func)
                        != 'self._client.executions.create'):
                    continue
                create_calls += 1
                self.assertEqual(1, len(call.args))
                expression = call.args[0]
                if isinstance(expression, ast.Name):
                    expression = assignments[expression.id]
                created.update(_workflow_values_from_expression(
                    expression, constants
                ))

        self.assertEqual(4, create_calls)
        self.assertEqual(WORKFLOWS, created)

    def test_reboot_payload_is_false_and_hard_off_fields_are_admin_power_off(self):
        source, forms_module = _module(
            self.dashboard, 'poweropsdashboard/hosts/forms.py'
        )
        workflow_input = _class_method(
            forms_module, 'PlannedOperationForm', 'workflow_input'
        )
        result = next(
            node.value for node in workflow_input.body
            if isinstance(node, ast.Return)
        )
        self.assertIsInstance(result, ast.Dict)
        payload = {
            key.value: value
            for key, value in zip(result.keys, result.values)
            if isinstance(key, ast.Constant)
        }
        hard_off = payload['allow_hard_off']
        self.assertIsInstance(hard_off, ast.BoolOp)
        self.assertEqual(
            "self.operation == 'power_off'",
            ast.unparse(hard_off.values[0]),
            'the reboot branch must always short-circuit to False',
        )

        constructor = _class_method(
            forms_module, 'PlannedOperationForm', '__init__'
        )
        guarded_fields = set()
        guard = None
        for node in constructor.body:
            if not isinstance(node, ast.If):
                continue
            assignments = [
                child for child in ast.walk(node)
                if isinstance(child, ast.Assign)
                and any(
                    isinstance(target, ast.Subscript)
                    and ast.unparse(target.value) == 'self.fields'
                    for target in child.targets
                )
            ]
            if assignments:
                guard = ast.unparse(node.test)
                for assignment in assignments:
                    for target in assignment.targets:
                        if (isinstance(target, ast.Subscript)
                                and ast.unparse(target.value) == 'self.fields'
                                and isinstance(target.slice, ast.Constant)):
                            guarded_fields.add(target.slice.value)
        self.assertEqual(
            "operation == 'power_off' and authorization.is_admin", guard
        )
        self.assertEqual(
            {'allow_hard_off', 'confirm_hard_off'}, guarded_fields
        )
        self.assertEqual(1, source.count("self.fields['allow_hard_off']"))
        self.assertEqual(1, source.count("self.fields['confirm_hard_off']"))

    def test_trusted_action_context_carries_human_roles(self):
        _, module = _module(
            self.mistral_lib, 'mistral_lib/actions/context.py'
        )
        security = next(
            node for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == 'SecurityContext'
        )
        constructor = _class_method(module, 'SecurityContext', '__init__')
        parameters = [argument.arg for argument in constructor.args.args]
        self.assertEqual(['user_id', 'roles'], parameters[-2:])
        assignments = {
            ast.unparse(node.targets[0]): ast.unparse(node.value)
            for node in ast.walk(constructor)
            if isinstance(node, ast.Assign) and len(node.targets) == 1
        }
        self.assertEqual('user_id', assignments['self.user_id'])
        self.assertEqual(
            'list(roles) if roles else []', assignments['self.roles']
        )
        self.assertTrue(security)

    def test_kolla_build_inputs_are_local_and_opt_in(self):
        sources = _read(self.kolla, 'kolla/common/sources.py')
        for name, location in (
                ('horizon-plugin-powerops-dashboard',
                 '$locals_base/powerops-dashboard'),
                ('mistral-base-plugin-mistral-lib',
                 '$locals_base/worktrees/mistral-lib-horizon-clean')):
            pattern = (
                r"'{}':\s*\{{\s*'type':\s*'local',\s*"
                r"'location':\s*'{}',\s*'enabled':\s*False,?\s*\}}"
            ).format(re.escape(name), re.escape(location))
            self.assertRegex(sources, pattern)

        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / 'build/kolla-build.conf', encoding='utf-8')
        self.assertEqual(
            '$locals_base/powerops-dashboard',
            config['horizon-plugin-powerops-dashboard']['location'],
        )
        self.assertEqual(
            '$locals_base/worktrees/mistral-horizon-clean',
            config['mistral-base']['location'],
        )
        self.assertEqual(
            '$locals_base/worktrees/mistral-lib-horizon-clean',
            config['mistral-base-plugin-mistral-lib']['location'],
        )

    def test_roles_and_allowlists_match_horizon_mistral_and_kolla(self):
        _, auth_module = _module(self.dashboard, 'poweropsdashboard/auth.py')
        authorize_user = _function(auth_module, 'authorize_user')
        horizon_roles = {
            value.value
            for comparison in ast.walk(authorize_user)
            if isinstance(comparison, ast.Compare)
            and 'roles' in ast.unparse(comparison)
            for value in ast.walk(comparison)
            if isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        }
        self.assertEqual(ROLE_NAMES, horizon_roles)

        _, mistral_module = _module(
            self.mistral, 'mistral/services/powerops.py'
        )
        self.assertEqual(
            ROLE_NAMES,
            {
                _literal_assignment(mistral_module, 'ADMIN_ROLE'),
                _literal_assignment(mistral_module, 'OPERATOR_ROLE'),
            },
        )

        horizon_template = _read(
            self.kolla_ansible,
            'ansible/roles/horizon/templates/_9998-kolla-settings.py.j2',
        )
        mistral_template = _read(
            self.kolla_ansible,
            'ansible/roles/mistral/templates/mistral.conf.j2',
        )
        for variable in ALLOWLIST_VARIABLES:
            self.assertIn(variable, horizon_template)
            self.assertIn(variable, mistral_template)
        self.assertIn('POWEROPS_ALLOWED_PROJECT_NAMES', _read(
            self.dashboard, 'poweropsdashboard/auth.py'
        ))
        self.assertIn('POWEROPS_ALLOWED_USER_NAMES', _read(
            self.dashboard, 'poweropsdashboard/auth.py'
        ))
        service_source = _read(
            self.mistral, 'mistral/services/powerops.py'
        )
        self.assertIn('CONF.powerops.allowed_project_names', service_source)
        self.assertIn('CONF.powerops.allowed_user_names', service_source)

    def test_admin_precedes_operator_and_bypasses_both_allowlists(self):
        _, module = _module(self.mistral, 'mistral/services/powerops.py')
        authorize = _function(module, 'authorize')
        decisions = [
            node for node in authorize.body if isinstance(node, ast.If)
        ]
        role_decision = next(
            node for node in decisions
            if ast.unparse(node.test) == 'ADMIN_ROLE in roles'
        )
        self.assertEqual('branch = ADMIN_BRANCH', ast.unparse(
            role_decision.body[0]
        ))
        self.assertEqual(1, len(role_decision.orelse))
        operator = role_decision.orelse[0]
        self.assertIsInstance(operator, ast.If)
        condition = ast.unparse(operator.test)
        self.assertIn('OPERATOR_ROLE in roles', condition)
        self.assertIn('CONF.powerops.allowed_project_names', condition)
        self.assertIn('CONF.powerops.allowed_user_names', condition)

    def test_mistral_and_masakari_share_exact_host_lock_namespace(self):
        for tree, relative in (
                (self.mistral,
                 'mistral/actions/powerops/coordination.py'),
                (self.masakari, 'masakari/powerops/coordination.py')):
            source = _read(tree, relative)
            self.assertEqual(1, source.count('powerops/host/{}'))
            self.assertIn('.format(host)', source)

    def test_workbook_copy_and_mandatory_wsgi_patch_are_immutable(self):
        self.assertEqual(
            (self.mistral / 'etc/mistral/power_ops.yaml').read_bytes(),
            (self.kolla_ansible /
             'ansible/roles/mistral/files/power_ops.yaml').read_bytes(),
        )
        self.assertTrue(WSGI_PATCH.is_file())
        self.assertEqual(
            WSGI_PATCH_SHA256,
            hashlib.sha256(WSGI_PATCH.read_bytes()).hexdigest(),
        )

    def test_dashboard_has_no_infrastructure_mutation_client_imports(self):
        banned_modules = {
            'novaclient',
            'masakariclient',
            'ironicclient',
            'redfish',
            'sushy',
            'openstack.connection',
            'openstack.compute',
            'openstack.baremetal',
        }
        imported = set()
        production_files = sorted(
            path for path in (self.dashboard / 'poweropsdashboard').rglob(
                '*.py'
            )
            if 'tests' not in path.parts and 'test' not in path.parts
        )
        for path in production_files:
            module = ast.parse(path.read_text(encoding='utf-8'), str(path))
            for node in ast.walk(module):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
        offenders = {
            module for module in imported
            if any(
                module == banned or module.startswith(banned + '.')
                for banned in banned_modules
            )
        }
        self.assertEqual(set(), offenders)
        self.assertEqual(
            {'mistralclient.api'},
            {module for module in imported if module.startswith('mistralclient')},
        )

    def test_ui_routes_exclude_emergency_fencing_and_evacuation(self):
        routes = _read(self.dashboard, 'poweropsdashboard/hosts/urls.py')
        self.assertNotRegex(
            routes.lower(),
            r'emergency|fenc|evacuat|notification|baremetal|redfish|bmc',
        )
        self.assertEqual(
            {
                'index',
                'refresh_inventory',
                'execution',
                'planned',
                'start_return',
                'resume_return',
            },
            set(re.findall(r"name='([a-z_]+)'", routes)),
        )


if __name__ == '__main__':
    unittest.main()
