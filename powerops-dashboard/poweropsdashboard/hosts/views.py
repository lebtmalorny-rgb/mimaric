from collections import abc
import json
import logging
import re
import uuid

from django.conf import settings
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from horizon import views

from poweropsdashboard import api
from poweropsdashboard import auth
from poweropsdashboard import constants
from poweropsdashboard import error_handling
from poweropsdashboard import exceptions
from poweropsdashboard.hosts import forms
from poweropsdashboard.hosts import tables
from poweropsdashboard import presentation
from poweropsdashboard import submission


LOG = logging.getLogger(__name__)

_HOST_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_CORRELATION_RE = re.compile(r'^[A-Za-z0-9._-]{1,128}$')
_SOURCE_INPUT_KEYS = frozenset({
    'host', 'segment_uuid', 'instance_policy', 'allow_hard_off',
})
_SOURCE_OUTPUT_KEYS = frozenset({'result', 'stopped_instance_ids'})
_SOURCE_RESULT_KEYS = frozenset({
    'host',
    'operation',
    'power_state',
    'stopped_instance_ids',
    'nova_enabled',
    'masakari_maintenance',
})
_RETURN_INPUT_KEYS = frozenset({
    'host', 'segment_uuid', 'stopped_instance_ids',
})
_STATUS_RESULT_KEYS = frozenset({
    'host',
    'ironic_node_uuid',
    'power_state',
    'target_power_state',
    'ironic_last_error',
    'nova_enabled',
    'nova_state',
    'masakari_maintenance',
})
_TASK_STATES = frozenset({
    'IDLE', 'RUNNING', 'SUCCESS', 'ERROR', 'PAUSED', 'CANCELLED',
    'DELAYED', 'WAITING',
})
_NONTERMINAL_TASK_STATES = _TASK_STATES - constants.TERMINAL_STATES
_RETURN_TOKEN_BINDINGS = {
    'start': 'power_off',
    'resume': 'reboot',
}


def _resource_value(resource, name):
    if isinstance(resource, abc.Mapping):
        if name not in resource:
            raise submission.InvalidSubmission(
                'Required PowerOps data is missing')
        return resource[name]
    try:
        return getattr(resource, name)
    except (AttributeError, TypeError):
        raise submission.InvalidSubmission(
            'Required PowerOps data is missing') from None


def _reject_json_constant(value):
    raise ValueError(value)


def _mapping(value):
    if isinstance(value, str):
        try:
            value = json.loads(
                value,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError):
            raise submission.InvalidSubmission(
                'PowerOps data is malformed') from None
    if not isinstance(value, abc.Mapping):
        raise submission.InvalidSubmission('PowerOps data is malformed')
    return dict(value)


def _canonical_uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        raise submission.InvalidSubmission('PowerOps UUID is malformed')
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise submission.InvalidSubmission(
            'PowerOps UUID is malformed') from None
    if str(parsed) != value:
        raise submission.InvalidSubmission('PowerOps UUID is malformed')
    return value


def _host(value):
    if not isinstance(value, str) or not _HOST_RE.fullmatch(value):
        raise submission.InvalidSubmission('PowerOps host is malformed')
    return value


def _manifest(value):
    if not isinstance(value, list):
        raise submission.InvalidSubmission(
            'Stopped instance manifest is malformed')
    result = [_canonical_uuid(item) for item in value]
    if len(result) != len(set(result)):
        raise submission.InvalidSubmission(
            'Stopped instance manifest is malformed')
    return result


def _validate_source_result(result, workflow_input, manifest):
    if set(result) != _SOURCE_RESULT_KEYS:
        raise submission.InvalidSubmission(
            'Planned power-off result is malformed')
    expected = {
        'host': workflow_input['host'],
        'operation': 'planned_power_off',
        'power_state': 'power off',
        'stopped_instance_ids': manifest,
        'nova_enabled': False,
        'masakari_maintenance': True,
    }
    parsed = dict(result)
    parsed['stopped_instance_ids'] = _manifest(
        parsed['stopped_instance_ids'])
    if (type(parsed['nova_enabled']) is not bool
            or type(parsed['masakari_maintenance']) is not bool):
        raise submission.InvalidSubmission(
            'Planned power-off result types are malformed')
    if parsed != expected:
        raise submission.InvalidSubmission(
            'Planned power-off result is inconsistent')


def _return_payload(source_execution_id, execution):
    actual_execution_id = _canonical_uuid(
        _resource_value(execution, 'id'))
    if actual_execution_id != source_execution_id:
        raise submission.InvalidSubmission(
            'Source execution identifier changed')
    if (_resource_value(execution, 'workflow_name')
            != constants.PLANNED_POWER_OFF):
        raise submission.InvalidSubmission(
            'Source execution is not a planned power-off')
    if _resource_value(execution, 'state') != 'SUCCESS':
        raise submission.InvalidSubmission(
            'Source planned power-off did not succeed')

    workflow_input = _mapping(_resource_value(execution, 'input'))
    if set(workflow_input) != _SOURCE_INPUT_KEYS:
        raise submission.InvalidSubmission(
            'Source planned power-off input is malformed')
    host = _host(workflow_input['host'])
    segment_uuid = _canonical_uuid(workflow_input['segment_uuid'])
    if workflow_input['instance_policy'] not in constants.INSTANCE_POLICIES:
        raise submission.InvalidSubmission(
            'Source planned power-off policy is malformed')
    if type(workflow_input['allow_hard_off']) is not bool:
        raise submission.InvalidSubmission(
            'Source planned hard-off value is malformed')

    output = _mapping(_resource_value(execution, 'output'))
    if (not set(output).issubset(_SOURCE_OUTPUT_KEYS)
            or 'stopped_instance_ids' not in output):
        raise submission.InvalidSubmission(
            'Source planned power-off output is malformed')
    manifest = _manifest(output['stopped_instance_ids'])
    if 'result' in output:
        _validate_source_result(_mapping(output['result']),
                                workflow_input, manifest)

    return {
        'host': host,
        'segment_uuid': segment_uuid,
        'stopped_instance_ids': list(manifest),
    }


def _return_execution_input(execution_id, execution):
    if _canonical_uuid(_resource_value(execution, 'id')) != execution_id:
        raise submission.SubmissionConflict(
            'Return execution identifier changed')
    if (_resource_value(execution, 'workflow_name')
            != constants.POWER_ON_AND_RETURN):
        raise submission.SubmissionConflict(
            'Execution is not a PowerOps return')
    if _resource_value(execution, 'state') != 'PAUSED':
        raise submission.SubmissionConflict(
            'PowerOps return is not paused')

    workflow_input = _mapping(_resource_value(execution, 'input'))
    if set(workflow_input) != _RETURN_INPUT_KEYS:
        raise submission.SubmissionConflict(
            'PowerOps return input is malformed')
    try:
        payload = {
            'host': _host(workflow_input['host']),
            'segment_uuid': _canonical_uuid(
                workflow_input['segment_uuid']),
            'stopped_instance_ids': _manifest(
                workflow_input['stopped_instance_ids']),
        }
    except submission.InvalidSubmission:
        raise submission.SubmissionConflict(
            'PowerOps return input is malformed') from None
    return payload


def _validate_paused_tasks(tasks):
    if not isinstance(tasks, (list, tuple)):
        raise submission.SubmissionConflict(
            'PowerOps return tasks are malformed')
    active = []
    manifest_restart_started = False
    for task in tasks:
        try:
            _canonical_uuid(_resource_value(task, 'id'))
            name = _resource_value(task, 'name')
            state = _resource_value(task, 'state')
        except submission.InvalidSubmission:
            raise submission.SubmissionConflict(
                'PowerOps return tasks are malformed') from None
        if not isinstance(name, str) or not name or state not in _TASK_STATES:
            raise submission.SubmissionConflict(
                'PowerOps return tasks are malformed')
        if name == 'return_to_service':
            manifest_restart_started = True
        if state in _NONTERMINAL_TASK_STATES:
            active.append((name, state))

    if manifest_restart_started:
        raise submission.SubmissionConflict(
            'Stopped instance restart has already started')
    if len(active) != 1 or active[0][0] != 'operator_inspection_gate':
        raise submission.SubmissionConflict(
            'PowerOps return is not at the operator inspection gate')
    return False


def _fresh_return_status(client, payload):
    expected_input = {
        'host': payload['host'],
        'segment_uuid': payload['segment_uuid'],
    }
    execution = client.start_host_status(
        payload['host'], payload['segment_uuid'])
    try:
        execution = submission._wait_for_read(
            client,
            execution,
            constants.HOST_POWER_STATUS,
            expected_input,
        )
        output = _mapping(_resource_value(execution, 'output'))
        if set(output) != {'result'}:
            raise submission.InvalidSubmission(
                'Return status output is malformed')
        result = _mapping(output['result'])
        if set(result) != _STATUS_RESULT_KEYS:
            raise submission.InvalidSubmission(
                'Return status result is malformed')
        if (result['host'] != payload['host']
                or type(result['nova_enabled']) is not bool
                or type(result['masakari_maintenance']) is not bool):
            raise submission.InvalidSubmission(
                'Return status result is malformed')
        _canonical_uuid(result['ironic_node_uuid'])
        if (result['power_state'] not in {'power on', 'power off'}
                or result['target_power_state'] not in {
                    None, 'power on', 'power off'}
                or result['ironic_last_error'] is not None
                or result['nova_state'] not in {'up', 'down'}):
            raise submission.InvalidSubmission(
                'Return status result is malformed')
    except (submission.InvalidSubmission, submission.SubmissionConflict):
        raise submission.SubmissionConflict(
            'Fresh return status failed validation') from None

    if not (
            result['power_state'] == 'power on'
            and result['nova_enabled'] is False
            and result['nova_state'] == 'up'
            and result['masakari_maintenance'] is True):
        raise submission.SubmissionConflict(
            'Host is not ready for controlled return')
    return {
        'power_state': 'power on',
        'nova_status': 'disabled',
        'nova_state': 'up',
        'masakari_maintenance': True,
    }


def _resume_snapshot(client, execution_id):
    execution = client.get_execution(execution_id)
    payload = _return_execution_input(execution_id, execution)
    tasks = client.list_tasks(execution_id)
    manifest_restart_started = _validate_paused_tasks(tasks)
    status = _fresh_return_status(client, payload)
    status['manifest_restart_started'] = manifest_restart_started
    return execution, tasks, payload, status


def _return_token_target(flow, execution_id):
    return 'return-{}:{}'.format(flow, execution_id)


def _issue_return_token(request, flow, execution_id):
    return submission.issue_submission_token(
        request,
        _RETURN_TOKEN_BINDINGS[flow],
        _return_token_target(flow, execution_id),
    )


def _consume_return_token(request, token, flow, execution_id):
    submission.consume_submission_token(
        request,
        token,
        _RETURN_TOKEN_BINDINGS[flow],
        _return_token_target(flow, execution_id),
    )


def _single_post_value(post, name):
    if hasattr(post, 'getlist'):
        values = post.getlist(name)
    else:
        value = post.get(name)
        values = [] if value is None else [value]
    if len(values) != 1:
        raise submission.InvalidSubmission(
            'Required submission value is missing or repeated')
    return values[0]


def _classify_request_error(request, exc):
    status_code, public_message, _verification_required = (
        error_handling.classify_error(exc))
    correlation_id = getattr(request, 'request_id', None)
    if (not isinstance(correlation_id, str)
            or not _CORRELATION_RE.fullmatch(correlation_id)):
        correlation_id = 'unavailable'
    LOG.warning(
        'PowerOps HTTP request rejected [request_id=%s, exception_type=%s]',
        correlation_id,
        type(exc).__name__,
    )
    return status_code, public_message, _verification_required


def _error_response(request, exc):
    status_code, public_message, _verification_required = (
        _classify_request_error(request, exc))
    return HttpResponse(public_message, status=status_code)


class ProtectedViewMixin:

    def dispatch(self, request, *args, **kwargs):
        self.authorization = auth.authorize_user(request.user)
        return super().dispatch(request, *args, **kwargs)


class IndexView(ProtectedViewMixin, views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/index.html'
    page_title = 'Compute Hosts'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['region_name'] = settings.POWEROPS_REGION_NAME
        context['inventory_error'] = None
        context['inventory_verified'] = False
        rows = ()
        active_executions = {}

        try:
            client = api.get_client(self.request)
            executions = client.list_executions(
                all_projects=self.authorization.is_admin)
            parsed_rows = presentation.latest_successful_inventory(
                executions)
            if parsed_rows is None:
                context['inventory_error'] = (
                    'No verified inventory snapshot is available'
                )
            else:
                rows = parsed_rows
                active_executions = presentation.match_active_executions(
                    executions)
                context['inventory_verified'] = True
        except Exception:
            context['inventory_error'] = (
                'Verified PowerOps inventory is unavailable'
            )

        table = tables.ComputeHostsTable(self.request, data=rows)
        table.active_executions = active_executions
        context['table'] = table
        return context


class RefreshInventoryView(ProtectedViewMixin,
                           views.HorizonTemplateView):

    def get(self, request, *args, **kwargs):
        try:
            execution = api.get_client(request).start_inventory()
            execution_id = presentation.execution_id(execution)
        except Exception:
            return HttpResponse(
                'PowerOps inventory refresh is unavailable', status=503)
        return redirect(reverse(
            'horizon:powerops:compute_hosts:execution',
            args=(execution_id,),
        ))


class ExecutionView(ProtectedViewMixin, views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/execution.html'
    page_title = 'PowerOps Execution'

    def get(self, request, *args, **kwargs):
        try:
            context = self.get_context_data(**kwargs)
            accept = request.META.get('HTTP_ACCEPT', '')
            if accept.split(';', 1)[0].strip() == 'application/json':
                return JsonResponse({
                    'id': context['execution'].id,
                    'state': context['execution'].state,
                    'tasks': [
                        {'id': task.id, 'state': task.state}
                        for task in context['tasks']
                    ],
                })
            return render(request, self.template_name, context)
        except exceptions.InvalidBackendData:
            return HttpResponse(
                'PowerOps execution data failed validation', status=502)
        except Exception:
            return HttpResponse(
                'PowerOps execution state is unavailable', status=503)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        execution_id = self.kwargs['execution_id']
        client = api.get_client(self.request)
        execution = client.get_execution(execution_id)
        tasks = client.list_tasks(execution_id)
        execution_state = presentation.parse_execution_state(execution)
        if execution_state.id != execution_id:
            raise exceptions.InvalidBackendData(
                'Execution identifier does not match the requested resource'
            )
        context['execution'] = execution_state
        context['tasks'] = presentation.parse_tasks(tasks)
        context['can_start_return'] = (
            execution_state.workflow_name == constants.PLANNED_POWER_OFF
            and execution_state.state == 'SUCCESS'
            and 'stopped_instance_ids' in execution_state.output
        )
        context['can_resume_return'] = (
            execution_state.workflow_name == constants.POWER_ON_AND_RETURN
            and execution_state.state == 'PAUSED'
        )
        return context


class PlannedOperationView(ProtectedViewMixin, views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/confirm_planned.html'
    page_title = 'Confirm Planned Power Operation'

    @staticmethod
    def _conflict(message='PowerOps preflight rejected the operation'):
        return HttpResponse(message, status=409)

    @staticmethod
    def _invalid():
        return HttpResponse(
            'PowerOps operation parameters failed validation', status=422)

    def _preflight(self, request, host, segment_uuid):
        client = api.get_client(request)
        host_row = submission.planned_preflight(
            client,
            self.authorization,
            host,
            segment_uuid,
        )
        return client, host_row

    def _context(self, form, host_row, operation,
                 verification_required=False):
        selected_policy = form['instance_policy'].value()
        return {
            'form': form,
            'host_row': host_row,
            'operation': operation,
            'operation_label': {
                'power_off': 'planned power-off',
                'reboot': 'planned reboot',
            }[operation],
            'selected_policy': selected_policy,
            'show_hard_off': (
                operation == 'power_off'
                and self.authorization.is_admin
            ),
            'verification_required': verification_required,
        }

    def get(self, request, operation, segment_uuid, host, *args, **kwargs):
        try:
            _client, host_row = self._preflight(
                request, host, segment_uuid)
            token = submission.issue_submission_token(
                request, operation, host_row.host)
        except (submission.InvalidSubmission,
                submission.SubmissionConflict):
            return self._conflict()
        except Exception:
            return self._conflict()

        form = forms.PlannedOperationForm(
            self.authorization,
            host_row,
            operation,
            initial={'submission_token': token},
        )
        return render(
            request,
            self.template_name,
            self._context(form, host_row, operation),
        )

    def post(self, request, operation, segment_uuid, host, *args, **kwargs):
        if hasattr(request.POST, 'getlist'):
            tokens = request.POST.getlist('submission_token')
        else:
            token = request.POST.get('submission_token')
            tokens = [] if token is None else [token]
        if len(tokens) != 1:
            return self._invalid()

        try:
            submission.consume_submission_token(
                request, tokens[0], operation, host)
        except submission.InvalidSubmission:
            return self._invalid()
        except submission.SubmissionConflict:
            return self._conflict('Submission token is invalid or consumed')

        try:
            client, host_row = self._preflight(
                request, host, segment_uuid)
        except submission.SubmissionConflict:
            return self._conflict()
        except Exception:
            return self._conflict()

        form = forms.PlannedOperationForm(
            self.authorization,
            host_row,
            operation,
            data=request.POST,
        )
        if not form.is_valid():
            return self._invalid()

        try:
            execution = client.start_planned(
                operation, form.workflow_input())
            execution_id = presentation.execution_id(execution)
        except exceptions.MockMutationDisabled:
            return self._conflict(
                'PowerOps mutations are disabled in mock mode')
        except TimeoutError:
            return render(
                request,
                self.template_name,
                self._context(
                    form,
                    host_row,
                    operation,
                    verification_required=True,
                ),
                status=503,
            )
        except Exception:
            return HttpResponse(
                'PowerOps submission is unavailable; verification required',
                status=503,
            )

        request.session[submission.SESSION_EXECUTION_KEY] = execution_id
        request.session.modified = True
        return redirect(reverse(
            'horizon:powerops:compute_hosts:execution',
            args=(execution_id,),
        ))


class StartReturnView(ProtectedViewMixin, views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/start_return.html'
    page_title = 'Start Controlled Return'

    def _source(self, request, source_execution_id):
        client = api.get_client(request)
        source = client.get_execution(source_execution_id)
        payload = _return_payload(source_execution_id, source)
        return client, payload

    @staticmethod
    def _context(form, payload, verification_required=False,
                 public_error=None):
        return {
            'form': form,
            'payload': payload,
            'verification_required': verification_required,
            'public_error': public_error,
        }

    def get(self, request, source_execution_id, *args, **kwargs):
        try:
            _client, payload = self._source(
                request, source_execution_id)
            token = _issue_return_token(
                request, 'start', source_execution_id)
        except Exception as exc:
            return _error_response(request, exc)

        form = forms.StartReturnForm(
            initial={'submission_token': token})
        return render(
            request,
            self.template_name,
            self._context(form, payload),
        )

    def post(self, request, source_execution_id, *args, **kwargs):
        try:
            token = _single_post_value(
                request.POST, 'submission_token')
            _consume_return_token(
                request, token, 'start', source_execution_id)
        except Exception as exc:
            return _error_response(request, exc)

        try:
            client, payload = self._source(
                request, source_execution_id)
        except Exception as exc:
            return _error_response(request, exc)

        form = forms.StartReturnForm(data=request.POST)
        if not form.is_valid():
            return _error_response(
                request,
                submission.InvalidSubmission(
                    'Return start parameters failed validation'),
            )

        try:
            result = client.start_return({
                'host': payload['host'],
                'segment_uuid': payload['segment_uuid'],
                'stopped_instance_ids': list(
                    payload['stopped_instance_ids']),
            })
        except Exception as exc:
            status_code, public_message, verification_required = (
                _classify_request_error(request, exc))
            if verification_required:
                return render(
                    request,
                    self.template_name,
                    self._context(
                        form,
                        payload,
                        verification_required=True,
                        public_error=public_message,
                    ),
                    status=status_code,
                )
            return HttpResponse(public_message, status=status_code)

        try:
            execution_id = presentation.execution_id(result)
        except Exception:
            return render(
                request,
                self.template_name,
                self._context(
                    form,
                    payload,
                    verification_required=True,
                    public_error=(
                        'Обязательный сервис временно недоступен.'),
                ),
                status=503,
            )

        request.session[submission.SESSION_EXECUTION_KEY] = execution_id
        request.session.modified = True
        return redirect(reverse(
            'horizon:powerops:compute_hosts:execution',
            args=(execution_id,),
        ))


class ResumeReturnView(ProtectedViewMixin, views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/resume_return.html'
    page_title = 'Resume Controlled Return'

    def _snapshot(self, request, execution_id):
        client = api.get_client(request)
        execution, tasks, payload, status = _resume_snapshot(
            client, execution_id)
        return client, execution, tasks, payload, status

    @staticmethod
    def _context(form, execution_id, payload, status,
                 verification_required=False, public_error=None):
        return {
            'form': form,
            'execution_id': execution_id,
            'payload': payload,
            'status': status,
            'verification_required': verification_required,
            'public_error': public_error,
        }

    def get(self, request, execution_id, *args, **kwargs):
        try:
            _client, _execution, _tasks, payload, status = self._snapshot(
                request, execution_id)
            token = _issue_return_token(request, 'resume', execution_id)
        except Exception as exc:
            return _error_response(request, exc)

        form = forms.ResumeReturnForm(
            initial={'submission_token': token})
        return render(
            request,
            self.template_name,
            self._context(form, execution_id, payload, status),
        )

    def post(self, request, execution_id, *args, **kwargs):
        try:
            token = _single_post_value(
                request.POST, 'submission_token')
            _consume_return_token(
                request, token, 'resume', execution_id)
        except Exception as exc:
            return _error_response(request, exc)

        try:
            client, _execution, _tasks, payload, status = self._snapshot(
                request, execution_id)
        except Exception as exc:
            return _error_response(request, exc)

        form = forms.ResumeReturnForm(data=request.POST)
        if (not form.is_valid()
                or form.cleaned_data.get('stale_domains_checked') is not True):
            return _error_response(
                request,
                submission.InvalidSubmission(
                    'Return resume parameters failed validation'),
            )

        try:
            result = client.resume_return(execution_id)
        except Exception as exc:
            status_code, public_message, verification_required = (
                _classify_request_error(request, exc))
            if verification_required:
                return render(
                    request,
                    self.template_name,
                    self._context(
                        form,
                        execution_id,
                        payload,
                        status,
                        verification_required=True,
                        public_error=public_message,
                    ),
                    status=status_code,
                )
            return HttpResponse(public_message, status=status_code)

        try:
            returned_id = presentation.execution_id(result)
            if returned_id != execution_id:
                raise exceptions.InvalidBackendData(
                    'Resume response identifier changed')
        except Exception:
            return render(
                request,
                self.template_name,
                self._context(
                    form,
                    execution_id,
                    payload,
                    status,
                    verification_required=True,
                    public_error=(
                        'Обязательный сервис временно недоступен.'),
                ),
                status=503,
            )

        request.session[submission.SESSION_EXECUTION_KEY] = execution_id
        request.session.modified = True
        return redirect(reverse(
            'horizon:powerops:compute_hosts:execution',
            args=(execution_id,),
        ))
