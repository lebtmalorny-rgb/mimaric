from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from horizon import views

from poweropsdashboard import api
from poweropsdashboard import auth
from poweropsdashboard import exceptions
from poweropsdashboard.hosts import forms
from poweropsdashboard.hosts import tables
from poweropsdashboard import presentation
from poweropsdashboard import submission


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
            return super().get(request, *args, **kwargs)
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
