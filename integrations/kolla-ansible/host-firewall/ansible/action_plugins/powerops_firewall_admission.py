"""Controller-side admission before copying helpers or changing a host."""
import importlib.util
import json
from pathlib import Path
import re

from ansible.plugins.action import ActionBase

_spec = importlib.util.spec_from_file_location(
    '_firewall_plan', Path(__file__).resolve().parents[1] / 'module_utils/powerops_firewall_plan.py')
_plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_plan)
_verify_spec = importlib.util.spec_from_file_location('_firewall_verify_admission',
    Path(__file__).resolve().parents[1] / 'module_utils/powerops_firewall_verification.py')
_verify = importlib.util.module_from_spec(_verify_spec)
_verify_spec.loader.exec_module(_verify)


class ActionModule(ActionBase):
    TRANSFERS_FILES = False
    _requires_connection = False

    def run(self, tmp=None, task_vars=None):
        result = super().run(tmp, task_vars)
        result['changed'] = False
        values = task_vars or {}

        def get(key, default=None):
            return self._templar.template(values.get(key, default),
                                          fail_on_undefined=True, disable_lookups=True)

        try:
            mode = get('host_firewall_mode', 'report')
            if mode == 'rollback':
                txid = get('host_firewall_rollback_transaction_id', '')
                if not isinstance(txid, str) or not re.fullmatch(
                        r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', txid):
                    raise ValueError('INVALID_TRANSACTION_ID')
                return dict(result, allowed=True, operation='rollback', txid=txid)
            if mode != 'apply':
                raise ValueError('INVALID_FIREWALL_MODE')
            initialize = get('host_firewall_initialize', False)
            reload_allowed = get('host_firewall_allow_initial_reload', False)
            if type(initialize) is not bool or type(reload_allowed) is not bool:
                raise ValueError('FIREWALL_FLAGS_REQUIRE_YAML_BOOLEANS')
            if initialize:
                if not reload_allowed:
                    raise ValueError('INITIAL_RELOAD_APPROVAL_REQUIRED')
                return dict(result, allowed=True, operation='prepare')
            path = get('host_firewall_plan_file', '')
            plan_id = get('host_firewall_plan_id', '')
            if not isinstance(path, str) or not path or not isinstance(plan_id, str):
                raise ValueError('APPROVED_REPORT_REQUIRED')
            file = Path(path)
            if file.is_symlink() or not file.is_file() or file.stat().st_size > 4194304:
                raise ValueError('INVALID_REPORT_FILE')
            bundle = json.loads(file.read_text())
            if sorted(bundle['selected_hosts']) != sorted(values['ansible_play_hosts_all']):
                raise ValueError('REPORT_HOST_SELECTION_CHANGED')
            if set(bundle['reports']) != set(bundle['selected_hosts']):
                raise ValueError('INCOMPLETE_HOST_REPORTS')
            for host, report in bundle['reports'].items():
                if report['host'] != host:
                    raise ValueError('REPORT_HOST_MISMATCH')
                _plan.rules_from_report(report)
            if _plan.report_digest(bundle) != plan_id:
                raise ValueError('REPORT_DIGEST_MISMATCH')
            checks = get('host_firewall_verification_checks', [])
            if not isinstance(checks, list) or not checks:
                raise ValueError('SERVICE_VERIFICATION_REQUIRED')
            required_checks = _verify.validate_checks(checks)
            if self._task.args.get('require_fresh', False):
                fresh = values.get('host_firewall_report', {}).get('bundle', {})
                if not fresh.get('collection_complete') or _plan.report_digest(fresh) != plan_id:
                    raise ValueError('FRESH_REPORT_MISMATCH')
                for report in fresh['reports'].values():
                    _plan.rules_from_report(report)
            timeout = get('host_firewall_rollback_timeout', 300)
            if type(timeout) is not int or not 60 <= timeout <= 900:
                raise ValueError('INVALID_ROLLBACK_TIMEOUT')
            return dict(result, allowed=True, operation='apply', plan_id=plan_id,
                        report=bundle['reports'][values['inventory_hostname']],
                        checks=checks, required_checks=required_checks, rollback_timeout=timeout)
        except Exception as exc:
            # Emit only our fixed identifiers, never paths, expressions or secrets.
            code = str(exc)
            if not re.fullmatch(r'[A-Z_]+', code):
                code = 'INVALID_FIREWALL_INPUT'
            return dict(result, failed=True, allowed=False, msg=code)
